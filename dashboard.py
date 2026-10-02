"""
Builds the dashboard as one self-contained HTML document.

Kept free of any Streamlit import on purpose: it is a pure function from data
to a string, so it can be tested directly - in particular that third-party
text (review excerpts, article judgments, text lifted from a hotel's own
pages) is escaped. Rendered with components.html, which drops the string into
an iframe untouched; st.markdown(unsafe_allow_html=True) was tried first and
its Markdown pass broke a multi-line block mid-render.

Every dynamic value goes through _esc(). The only <script> in the output is
the small resize helper at the bottom, which is a constant.
"""

import html as html_lib

CARD_COLOR = {"good": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "mute": "#9ca3af"}
SEVERITY_DOT = {"critical": CARD_COLOR["bad"], "high": "#f97316",
                "medium": CARD_COLOR["warn"], "low": CARD_COLOR["mute"]}

# state -> (chip text, colour). Five different states on purpose: "not found on
# the pages checked" and "couldn't check" are NOT the same as "missing".
GUEST_STATE_STYLE = {
    "answered": ("Answered", "#16a34a"),
    "partial": ("Partly answered", "#d97706"),
    "needs_checking": ("Needs checking", "#2563eb"),
    "not_found": ("Not found on pages checked", "#475569"),
    "couldnt_check": ("Couldn't check", "#9ca3af"),
}

EFFORT_LABEL = {"quick": "Quick fix", "moderate": "Moderate", "larger": "Bigger piece of work"}


def esc(s):
    return html_lib.escape(str(s if s is not None else ""))


def safe_url(u):
    """Only http(s) links go into the page; anything else is dropped."""
    return u if str(u).lower().startswith(("http://", "https://")) else ""


def score_color(score):
    if score is None:
        return CARD_COLOR["mute"]
    if score >= 70:
        return CARD_COLOR["good"]
    if score >= 40:
        return CARD_COLOR["warn"]
    return CARD_COLOR["bad"]


def _link(url, text):
    u = safe_url(url)
    return (f'<a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(text)} ↗</a>'
            if u else "")


def fixes_html(top):
    """'Fix these first': who, where, why, and an example to adapt."""
    if not top:
        return ""
    rows = ""
    for i, r in enumerate(top, 1):
        page = r.get("page") or ""
        where = _link(page, "page") if safe_url(page) else (
            f'<span class="pill">{esc(page)}</span>' if page else "")
        example = ""
        if r.get("example"):
            example = (f'<details><summary>Example you can adapt</summary>'
                       f'<pre>{esc(r["example"])}</pre></details>')
        rows += f"""
        <div class="fix">
          <div class="fnum">{i}</div>
          <div class="fbody">
            <b>{esc(r['action'])}</b>
            <div class="fmeta">
              <span class="pill owner">{esc(r.get('owner', ''))}</span>
              <span class="pill">{esc(EFFORT_LABEL.get(r.get('effort'), ''))}</span>
              {where}
            </div>
            <p>{esc(r['why'])}</p>
            {example}
          </div>
        </div>"""
    heading = {1: "Fix this first", 2: "Fix these two things first"}.get(
        len(top), "Fix these three things first")
    return f"""
      <div class="fixes">
        <h2 class="first">{esc(heading)}</h2>
        {rows}
      </div>"""


def guest_html(guest):
    """Each guest question: its state, what's missing, the exact text relied on."""
    if not guest or not guest.get("questions"):
        return ""
    n_ok, n_all = guest.get("pages_ok", 0), guest.get("pages_attempted", 0)
    total = guest.get("sitemap_total") or 0
    scope = f"We read {n_ok} of {n_all} pages"
    if total > n_all:
        scope += f" (the site lists about {total})"
    rows = ""
    for q in guest["questions"]:
        chip, color = GUEST_STATE_STYLE.get(q["state"], ("", "#9ca3af"))
        detail = ""
        if q["state"] == "partial" and q["missing"]:
            detail = f'<div class="gmiss">Missing: {esc(", ".join(q["missing"]))}</div>'
        if q.get("note"):
            detail += f'<div class="gmiss">{esc(q["note"])}</div>'
        quote = ""
        if q["snippet"]:
            link = _link(q["source_url"], "view page")
            quote = f'<div class="gquote">“{esc(q["snippet"])}” {link}</div>'
        rows += f"""
        <div class="grow">
          <div class="gtop"><b>{esc(q['label'])}</b>
            <span class="chip" style="background:{color}1f;color:{color}">{esc(chip)}</span></div>
          {detail}{quote}
        </div>"""
    return f"""
      <h2>What your website tells guests</h2>
      <p class="gscope">{esc(scope)}. “Not found” means not found on those pages —
      it does not prove the information is missing. “Couldn't check” is never
      counted against you.</p>
      {rows}"""


_CSS = """
  html, body { margin:0; padding:0; background:#f7f8fa; }
  @media (prefers-color-scheme: dark) { html, body { background:#15161c; } }
  .dash {
    --bg:#f7f8fa; --card:#ffffff; --border:#e7e9ee; --ink:#1a1d29; --sub:#6b7280; --accent:#2563eb;
    font-family:-apple-system,'Segoe UI',system-ui,sans-serif;
    background:var(--bg); color:var(--ink); padding:20px; border-radius:12px;
    margin:0; box-sizing:border-box;
  }
  @media (prefers-color-scheme: dark) {
    .dash { --bg:#15161c; --card:#1d1f28; --border:#2a2d38; --ink:#eef0f4; --sub:#9aa0ad; }
  }
  .dash .head { display:flex; justify-content:space-between; align-items:flex-start;
                margin-bottom:18px; flex-wrap:wrap; gap:14px; }
  .dash h1 { font-size:19px; font-weight:700; margin:0 0 3px; }
  .dash .meta { font-size:12.5px; color:var(--sub); }
  .dash .scorewrap { display:flex; align-items:center; gap:14px; }
  .dash .ring { position:relative; width:76px; height:76px; flex:none; }
  .dash .ring svg { transform:rotate(-90deg); width:100%; height:100%; }
  .dash .ring .bgring { stroke:var(--border); }
  .dash .ring .fgring { stroke:var(--accent); stroke-linecap:round; }
  .dash .ring .num { position:absolute; inset:0; display:flex; align-items:center;
                     justify-content:center; flex-direction:column; }
  .dash .ring .num b { font-size:22px; line-height:1; }
  .dash .ring .num span { font-size:9.5px; color:var(--sub); }
  .dash .covnote { font-size:11.5px; color:var(--sub); max-width:170px; }
  .dash .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(165px,1fr));
                gap:10px; margin-bottom:18px; }
  .dash .card { background:var(--card); border:1px solid var(--border);
                border-radius:10px; padding:11px 12px; }
  .dash .card .top { display:flex; justify-content:space-between; align-items:center;
                     margin-bottom:6px; gap:4px; }
  .dash .card .cat { font-size:12px; font-weight:600; }
  .dash .card .wt { font-size:10.5px; color:var(--sub); }
  .dash .card .scoreline { display:flex; align-items:baseline; gap:5px; margin-bottom:6px; }
  .dash .card .scoreline b { font-size:19px; }
  .dash .card .scoreline small { font-size:10px; color:var(--sub); }
  .dash .bar { height:5px; border-radius:3px; background:var(--border); overflow:hidden; }
  .dash .bar i { display:block; height:100%; border-radius:3px; }
  .dash .card.na { opacity:.6; }
  .dash .tag { font-size:9.5px; padding:1px 6px; border-radius:20px; font-weight:600; }
  .dash .tag.mute { background:var(--border); color:var(--sub); }
  .dash h2 { font-size:13px; margin:18px 0 9px; color:var(--sub);
             text-transform:uppercase; letter-spacing:.04em; }
  .dash h2.first { margin-top:0; color:var(--ink); }
  .dash .fixes { background:var(--card); border:1px solid var(--border);
                 border-left:4px solid var(--accent); border-radius:10px;
                 padding:14px 14px 4px; margin-bottom:18px; }
  .dash .fix { display:flex; gap:12px; padding:10px 0; border-top:1px solid var(--border); }
  .dash .fix:first-of-type { border-top:none; }
  .dash .fnum { flex:none; width:24px; height:24px; border-radius:50%;
                background:var(--accent); color:#fff; font-size:12px; font-weight:700;
                display:flex; align-items:center; justify-content:center; }
  .dash .fbody { min-width:0; flex:1; }
  .dash .fbody b { font-size:13px; }
  .dash .fbody p { font-size:11.8px; color:var(--sub); margin:6px 0 4px; line-height:1.45; }
  .dash .fmeta { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-top:5px; }
  .dash .pill { font-size:10.5px; padding:2px 8px; border-radius:20px;
                background:var(--border); color:var(--ink); }
  .dash .pill.owner { background:#2563eb1f; color:var(--accent); font-weight:600; }
  .dash .fmeta a, .dash .gquote a { font-size:11px; color:var(--accent);
                                    text-decoration:none; white-space:nowrap; }
  .dash details { margin-top:4px; }
  .dash summary { font-size:11.5px; cursor:pointer; color:var(--accent); }
  .dash pre { white-space:pre-wrap; word-break:break-word; font-size:11px; line-height:1.45;
              background:var(--bg); border:1px solid var(--border); border-radius:8px;
              padding:10px; margin:6px 0 4px; user-select:all;
              font-family:ui-monospace,Consolas,monospace; }
  .dash .rec { display:flex; gap:9px; padding:9px 0; border-top:1px solid var(--border); }
  .dash .rec:first-of-type { border-top:none; }
  .dash .dot { width:8px; height:8px; border-radius:50%; margin-top:5px; flex:none; }
  .dash .rec b { font-size:12.5px; display:block; }
  .dash .rec p { font-size:11.5px; color:var(--sub); margin:2px 0 0; }
  .dash .gscope { font-size:11.5px; color:var(--sub); margin:0 0 10px; }
  .dash .grow { padding:10px 0; border-top:1px solid var(--border); }
  .dash .grow:first-of-type { border-top:none; }
  .dash .gtop { display:flex; justify-content:space-between; align-items:center;
                gap:10px; flex-wrap:wrap; }
  .dash .gtop b { font-size:12.5px; }
  .dash .chip { font-size:10.5px; font-weight:600; padding:2px 8px;
                border-radius:20px; white-space:nowrap; }
  .dash .gmiss { font-size:11.5px; color:#d97706; margin-top:3px; }
  .dash .gquote { font-size:11.5px; color:var(--sub); margin-top:4px;
                  font-style:italic; line-height:1.45; }
  .dash .gquote a { font-style:normal; }
"""

# Constant (no dynamic values). Lets the frame grow when an example is opened.
# Works because Streamlit's component iframe is same-origin; if a browser
# refuses, the try/catch means nothing happens and the estimated height stands.
_RESIZE_JS = """
<script>
(function () { try {
  var f = window.frameElement; if (!f) return;
  function fit() { f.style.height = (document.documentElement.scrollHeight + 4) + 'px'; }
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(document.body);
  document.addEventListener('toggle', fit, true);
} catch (e) {} })();
</script>
"""


def build(hotel_name, website, sc, rest_recs, guest=None, top=None):
    """
    Returns (html, estimated_height_px).

    `top` are the fixes to do first; `rest_recs` is everything else.
    """
    overall, coverage = sc["overall"], sc["coverage_pct"]
    circumference = 213.6  # 2*pi*34, matching the SVG radius below
    offset = circumference * (1 - min(max(overall, 0), 100) / 100)

    cards = ""
    for c in sc["categories"]:
        assessed = c["assessed"]
        score = c["score"] if assessed else None
        color = score_color(score) if assessed else CARD_COLOR["mute"]
        tag = ""
        if c.get("partial"):
            tag = f'<span class="tag" style="background:{color}22;color:{color}">partial</span>'
        elif not assessed:
            tag = '<span class="tag mute">not assessed</span>'
        cards += f"""
        <div class="card {'na' if not assessed else ''}">
          <div class="top"><span class="cat">{esc(c['label'])}</span>
            <span class="wt">{esc(c['weight'])}%</span>{tag}</div>
          <div class="scoreline"><b style="color:{color}">{esc(score) if assessed else '—'}</b>
            {'<small>/100</small>' if assessed else ''}</div>
          <div class="bar"><i style="width:{int(score or 0)}%;background:{color}"></i></div>
        </div>"""

    recs_html = ""
    for r in rest_recs:
        dot = SEVERITY_DOT.get(r["priority"], CARD_COLOR["mute"])
        recs_html += f"""
        <div class="rec"><div class="dot" style="background:{dot}"></div>
          <div><b>{esc(r['action'])}</b>
          <p><i>{esc(r['category'])}</i> — {esc(r['why'])}</p></div></div>"""
    if not recs_html and not top:
        recs_html = ('<p style="color:var(--sub);font-size:12.5px">No recommendations '
                     'from the categories that were assessed.</p>')

    fixes = fixes_html(top)
    guest_block = guest_html(guest)
    rest_heading = ("<h2>Everything else to look at</h2>" if top and rest_recs
                    else "<h2>What to fix, worst first</h2>" if rest_recs or not top else "")

    height = 170 + -(-len(sc["categories"]) // 4) * 95 + 40 + len(rest_recs) * 70 + 40
    height += len(top or []) * 150 + (60 if top else 0)
    if guest_block:
        height += 150 + len(guest["questions"]) * 108

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head><body>
    <div class="dash">
      <div class="head">
        <div><h1>{esc(hotel_name or website)}</h1><div class="meta">{esc(website)}</div></div>
        <div class="scorewrap">
          <div class="ring">
            <svg viewBox="0 0 80 80">
              <circle class="bgring" cx="40" cy="40" r="34" fill="none" stroke-width="7"/>
              <circle class="fgring" cx="40" cy="40" r="34" fill="none" stroke-width="7"
                stroke-dasharray="{circumference}" stroke-dashoffset="{offset}" />
            </svg>
            <div class="num"><b>{esc(overall)}</b><span>SCORE</span></div>
          </div>
          <div class="covnote">Weighted across <b style="color:var(--ink)">{esc(coverage)}%</b> of the model.</div>
        </div>
      </div>
      {fixes}
      <div class="grid">{cards}</div>
      {rest_heading}
      {recs_html}
      {guest_block}
    </div>{_RESIZE_JS}</body></html>"""
    return doc, height
