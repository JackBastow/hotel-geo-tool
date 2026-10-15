"""
A small stand-in for the parts of Streamlit's API that the report screens use (ui_consult.py, ui_intel.py, ui_theme.py), writing HTML instead of drawing a Streamlit page.

Why: the report screens hold all the careful wording and the honesty rules. Re-writing them as templates would risk changing what they say. Instead, the Flask site
(server.py) swaps this module in for `streamlit` inside those screens and the same code produces the HTML, styled by web/static/app.css. The Streamlit app is unaffected
(it is a different process and still imports the real streamlit).

What it covers: markdown, caption, write, headers, alerts, code, metric, progress, columns, container, expander, popover, tabs, dataframe (with link columns), altair charts
(drawn in the browser by Vega-Embed), text_area and no-op download buttons. Nothing that needs a server round trip (uploads, forms) lives here: those are routes in server.py.

Safety: text is escaped unless a caller passes unsafe_allow_html=True (our own chips and cards, which escape what they are given). Even then <script>, inline event handlers and
javascript: links are removed. Table cells are always escaped, and a link column only links http(s) addresses.
"""

import html
import json
import re
import threading

import markdown as _md

_local = threading.local()

_tl = threading.local()


def _md_instance():
    """python-markdown keeps state between calls, so each thread gets its own converter."""
    if not hasattr(_tl, "md"):
        _tl.md = _md.Markdown(extensions=["sane_lists"], output_format="html")
    return _tl.md
_SCRIPT = re.compile(r"<\s*/?\s*(?:script|iframe|object|embed|style)\b[^>]*>", re.I)
_ON = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS = re.compile(r"(href|src)\s*=\s*([\"']?)\s*javascript:", re.I)
_HREF = re.compile(r"<a\s+href=\"([^\"]*)\"([^>]*)>", re.I)
_IMG = re.compile(r"<img\b[^>]*>", re.I)


def _anchors(s):
    """Links in rendered text: only http(s), mailto and in-page links survive, and they open safely. Images are dropped (no third-party tracking pixels)."""
    def fix(m):
        u = html.unescape(m.group(1)).strip()
        if not u.lower().startswith(("http://", "https://", "mailto:", "#")):
            return "<a href=\"#\"" + ">"
        return f'<a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">'
    return _HREF.sub(fix, _IMG.sub("", s))


def _scrub(s):
    s = _SCRIPT.sub("", s)
    s = _ON.sub("", s)
    return _JS.sub(r"\1=\2#", s)


def render_md(body, unsafe=False, inline=False):
    body = "" if body is None else str(body)
    if not unsafe:
        body = html.escape(body, quote=False)
    md = _md_instance()
    md.reset()
    out = _anchors(md.convert(body))
    if unsafe:
        out = _scrub(out)
    if inline:
        out = re.sub(r"^<p>(.*)</p>$", r"\1", out.strip(), flags=re.S)
    return out


class _ColumnConfig:
    @staticmethod
    def LinkColumn(label=None, display_text="open", **_kw):
        return {"link": True, "text": display_text or "open"}

    @staticmethod
    def TextColumn(*_a, **_kw):
        return {}

    @staticmethod
    def NumberColumn(*_a, **_kw):
        return {}

    @staticmethod
    def ProgressColumn(*_a, **_kw):
        return {}


class Ctx:
    """A place content is written to: the page, a column, a card, a tab, an expander. Items are strings or child contexts, joined when the page is finished."""

    kind = "root"

    def __init__(self, parent=None):
        self.buf = []
        self.parent = parent
        self.uid = parent.uid if parent is not None else [0]

    def _id(self, prefix="n"):
        self.uid[0] += 1
        return f"{prefix}{self.uid[0]}"

    # --- context manager: `with st.container(): ...` makes this the current target
    def __enter__(self):
        _stack().append(self)
        return self

    def __exit__(self, *exc):
        _stack().pop()
        return False

    def add(self, item):
        self.buf.append(item)

    def render(self):
        return "".join(i if isinstance(i, str) else i.render() for i in self.buf)

    # --- text
    def markdown(self, body="", unsafe_allow_html=False, **_kw):
        self.add(f'<div class="md">{render_md(body, unsafe_allow_html)}</div>')

    def caption(self, body="", unsafe_allow_html=False, **_kw):
        self.add(f'<div class="caption">{render_md(body, unsafe_allow_html)}</div>')

    def raw(self, html_text):
        """Trusted HTML written by our own code (a form, an iframe): added as it is, with no markdown pass."""
        self.add(str(html_text))

    def write(self, *items, **_kw):
        for x in items:
            if isinstance(x, str):
                self.markdown(x)
            else:
                self.add(f'<pre class="code">{html.escape(json.dumps(x, indent=2, default=str))}</pre>')

    def title(self, body, **_kw):
        self.add(f"<h1>{html.escape(str(body))}</h1>")

    def header(self, body, **_kw):
        self.add(f"<h2>{html.escape(str(body))}</h2>")

    def subheader(self, body, **_kw):
        self.add(f"<h3>{html.escape(str(body))}</h3>")

    def divider(self):
        self.add("<hr>")

    def code(self, body="", language=None, **_kw):
        self.add(f'<pre class="code"><code>{html.escape(str(body))}</code></pre>')

    def _alert(self, kind, body, **_kw):
        self.add(f'<div class="alert {kind}" role="note">{render_md(body)}</div>')

    def info(self, body, **kw):
        self._alert("info", body, **kw)

    def success(self, body, **kw):
        self._alert("success", body, **kw)

    def warning(self, body, **kw):
        self._alert("warning", body, **kw)

    def error(self, body, **kw):
        self._alert("error", body, **kw)

    # --- figures
    def metric(self, label, value, delta=None, help=None, **_kw):
        d = ""
        if delta is not None:
            try:
                n = float(delta)
                d = f'<div class="m-delta {"up" if n > 0 else "down" if n < 0 else ""}">{n:+g}</div>'
            except (TypeError, ValueError):
                d = f'<div class="m-delta">{html.escape(str(delta))}</div>'
        tip = f' title="{html.escape(str(help), quote=True)}"' if help else ""
        self.add(f'<div class="metric"{tip}><div class="m-label">{html.escape(str(label))}</div><div class="m-value">{html.escape(str(value))}</div>{d}</div>')

    def progress(self, value, text=""):
        pct = max(0, min(100, round(float(value) * 100)))
        self.add(f'<div class="progress"><div class="p-text">{html.escape(str(text))}</div><div class="p-track"><div class="p-fill" style="width:{pct}%"></div></div></div>')

    def dataframe(self, data, column_config=None, width=None, hide_index=True, height=None, **_kw):
        if hasattr(data, "to_dict"):
            data = data.to_dict("records")
        rows = list(data or [])
        if not rows:
            return
        cols = list(rows[0])
        cfg = column_config or {}
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        body = []
        for r in rows:
            tds = []
            for c in cols:
                v = r.get(c)
                if (cfg.get(c) or {}).get("link"):
                    u = str(v or "")
                    tds.append(f'<td><a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">{html.escape(cfg[c]["text"])}</a></td>' if u.startswith(("http://", "https://")) else "<td></td>")
                else:
                    tds.append(f"<td>{'' if v is None else html.escape(str(v))}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        self.add(f'<div class="table-wrap"><table class="table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')

    def altair_chart(self, chart, width=None, use_container_width=None, **_kw):
        spec = chart.to_dict()
        self.add(f'<div class="vega" data-spec="{html.escape(json.dumps(spec, default=str), quote=True)}"></div>')

    def text_area(self, label, value="", height=None, key=None, **_kw):
        self.add(f'<label class="field"><span>{html.escape(str(label))}</span><textarea rows="{max(3, int((height or 120) / 24))}">{html.escape(str(value))}</textarea></label>')
        return value

    def download_button(self, *a, **kw):
        return False

    # --- layout
    def columns(self, spec=2, vertical_alignment=None, **_kw):
        g = Group("columns", self)
        n = spec if isinstance(spec, int) else len(spec)
        g.ratios = [1] * n if isinstance(spec, int) else list(spec)
        g.align = vertical_alignment
        g.children = [Ctx(self) for _ in range(n)]
        self.add(g)
        return g.children

    def container(self, border=False, **_kw):
        c = Box(self, "card" if border else "box")
        self.add(c)
        return c

    def expander(self, label, expanded=False, **_kw):
        c = Box(self, "details")
        c.label, c.open = label, expanded
        self.add(c)
        return c

    def popover(self, label, icon=None, **_kw):
        c = Box(self, "popover")
        c.label = label
        self.add(c)
        return c

    def tabs(self, labels):
        g = Group("tabs", self)
        g.labels = list(labels)
        g.gid = self._id("tabs")
        g.children = [Ctx(self) for _ in labels]
        self.add(g)
        return g.children


class Box(Ctx):
    def __init__(self, parent, style):
        super().__init__(parent)
        self.style, self.label, self.open = style, "", False

    def render(self):
        inner = super().render()
        if self.style == "card":
            return f'<div class="card">{inner}</div>'
        if self.style == "details":
            return f'<details class="details"{" open" if self.open else ""}><summary>{html.escape(str(self.label))}</summary><div class="details-body">{inner}</div></details>'
        if self.style == "popover":
            return f'<details class="popover"><summary>{html.escape(str(self.label))}</summary><div class="popover-body">{inner}</div></details>'
        return f'<div class="box">{inner}</div>'


class Group:
    def __init__(self, kind, parent):
        self.kind, self.parent = kind, parent
        self.children, self.ratios, self.labels, self.gid, self.align = [], [], [], "", None

    def render(self):
        if self.kind == "columns":
            tpl = " ".join(f"{max(r, 0.1):g}fr" for r in self.ratios)
            cls = "cols" + (" center" if self.align == "center" else "")
            return f'<div class="{cls}" style="grid-template-columns:{tpl}">' + "".join(f'<div class="col">{c.render()}</div>' for c in self.children) + "</div>"
        nav = "".join(f'<button type="button" class="tab{" active" if i == 0 else ""}" data-tab="{self.gid}-{i}">{html.escape(str(l))}</button>' for i, l in enumerate(self.labels))
        panels = "".join(f'<div class="tab-panel{" active" if i == 0 else ""}" id="{self.gid}-{i}">{c.render()}</div>' for i, c in enumerate(self.children))
        return f'<div class="tabs"><div class="tab-bar" role="tablist">{nav}</div>{panels}</div>'


def _stack():
    if not hasattr(_local, "stack"):
        _local.stack = []
    return _local.stack


class Page(Ctx):
    """A page being built. `with Page() as p:` makes it the current target for the module-level calls below; p.render() gives the HTML."""

    def __init__(self):
        super().__init__(None)


class _Module:
    """Stands in for `import streamlit as st`: every call goes to whatever is being written to now."""

    column_config = _ColumnConfig()
    session_state = {}

    def __getattr__(self, name):
        stack = _stack()
        if not stack:
            raise RuntimeError("htmlst: nothing is being written to; use `with htmlst.Page() as page:`")
        return getattr(stack[-1], name)


st = _Module()


def build(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) with the screens writing into a fresh page; return the HTML."""
    page = Page()
    with page:
        fn(*args, **kwargs)
    return page.render()
