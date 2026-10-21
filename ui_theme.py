"""
The look of the app: one stylesheet, a small set of components and chart helpers, so every page shares the same cards, type, spacing and colours.

Nothing here reads third-party text: components take numbers and our own labels. Anything that may carry text from the web goes through the
callers' md_safe(), and this module escapes what it is given before putting it in HTML.
"""

import html

try:
    import streamlit as st
except ImportError:        # the Flask site draws these screens with htmlst.py instead of Streamlit
    from htmlst import st

INK, MUTED, LINE, BRAND = "#1A1D29", "#667085", "#E6E8F0", "#4F46E5"
GOOD, WARN, BAD, GREY, SOFT = "#12B76A", "#F79009", "#F04438", "#98A2B3", "#EEF0FF"
BAR_OTHER = "#C9CFE6"

CSS = f"""
<style>
:root {{ --ink:{INK}; --muted:{MUTED}; --line:{LINE}; --brand:{BRAND}; --soft:{SOFT}; }}
html, body, [data-testid="stAppViewContainer"] {{ font-feature-settings: "cv11", "ss01"; -webkit-font-smoothing: antialiased; }}
[data-testid="stAppViewContainer"] {{ background: #FBFBFD; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ max-width: 1160px; padding-top: 2.4rem; padding-bottom: 5rem; }}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}

/* type */
h1 {{ font-size: 1.9rem !important; font-weight: 700 !important; letter-spacing: -0.025em; margin-bottom: .1rem; padding: 0 !important; }}
h2, h3 {{ letter-spacing: -0.02em; font-weight: 650 !important; }}
h4 {{ font-size: 1.12rem !important; font-weight: 650 !important; letter-spacing: -0.015em; margin-top: 1.7rem !important; padding-bottom: .15rem !important; }}
h5 {{ font-size: 1rem !important; font-weight: 650 !important; margin-top: 1.2rem !important; }}
h6 {{ font-size: .98rem !important; font-weight: 650 !important; color: var(--ink); margin-top: 1.6rem !important; padding-bottom: .1rem !important; }}
p, li {{ line-height: 1.55; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: var(--muted); font-size: .84rem; line-height: 1.5; }}

/* cards */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ border-radius: 14px; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: var(--line) !important; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.04); border-radius: 14px !important; }}
[data-testid="stMetric"] {{ background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 14px 18px 12px; box-shadow: 0 1px 2px rgba(16,24,40,.04); height: 100%; }}
[data-testid="stMetricLabel"] p {{ color: var(--muted); font-size: .8rem; font-weight: 550; text-transform: none; }}
[data-testid="stMetricValue"] {{ font-size: 1.85rem; font-weight: 650; letter-spacing: -0.02em; }}
[data-testid="stMetricDelta"] {{ font-size: .8rem; }}

/* tabs */
[data-baseweb="tab-list"] {{ gap: .2rem; border-bottom: 1px solid var(--line); }}
button[role="tab"] {{ padding: .55rem .95rem; border-radius: 10px 10px 0 0; }}
button[role="tab"] p {{ font-size: .93rem; font-weight: 550; color: var(--muted); }}
button[role="tab"][aria-selected="true"] p {{ color: var(--brand); font-weight: 650; }}
[data-baseweb="tab-highlight"] {{ background-color: var(--brand) !important; height: 2px !important; }}
[data-baseweb="tab-border"] {{ display: none; }}

/* tables, expanders, alerts */
[data-testid="stDataFrame"] {{ border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: #fff; }}
[data-testid="stExpander"] {{ border: 1px solid var(--line) !important; border-radius: 12px !important; background: #fff; box-shadow: none; }}
[data-testid="stExpander"] summary {{ font-weight: 550; }}
[data-testid="stAlert"] {{ border-radius: 12px; border: 1px solid var(--line); }}
[data-testid="stAlert"] p {{ font-size: .92rem; }}
[data-testid="stProgress"] [role="progressbar"] {{ height: 8px; border-radius: 99px; }}
[data-testid="stProgress"] [role="progressbar"] > div {{ border-radius: 99px; height: 8px; }}
[data-testid="stProgress"] p {{ font-size: .86rem; font-weight: 550; margin-bottom: .25rem; }}

/* inputs and buttons */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{ border-radius: 10px; font-weight: 600; padding: .5rem 1.1rem; border: 1px solid var(--line); box-shadow: 0 1px 2px rgba(16,24,40,.05); }}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {{ filter: brightness(1.08); }}
[data-testid="stTextInput"] input {{ border-radius: 10px; }}
[data-testid="stForm"] {{ border: 1px solid var(--line); border-radius: 16px; background: #fff; padding: 1.2rem 1.3rem; box-shadow: 0 1px 3px rgba(16,24,40,.05); }}

/* our own components */
.hk-hero {{ display: flex; gap: 1.6rem; align-items: center; background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 1.3rem 1.6rem; box-shadow: 0 1px 3px rgba(16,24,40,.05); margin: .4rem 0 1rem; }}
.hk-hero .hk-name {{ font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); line-height: 1.2; }}
.hk-hero .hk-sub {{ color: var(--muted); font-size: .9rem; margin-top: .25rem; }}
.hk-chips {{ display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .7rem; }}
.hk-chip {{ display: inline-flex; align-items: center; gap: .35rem; font-size: .76rem; font-weight: 600; padding: .22rem .6rem; border-radius: 99px; background: #F2F4F7; color: #344054; }}
.hk-chip.good {{ background: #ECFDF3; color: #067647; }} .hk-chip.warn {{ background: #FFFAEB; color: #B54708; }} .hk-chip.bad {{ background: #FEF3F2; color: #B42318; }} .hk-chip.brand {{ background: var(--soft); color: #3730A3; }}
.hk-ring {{ flex: 0 0 auto; position: relative; width: 112px; height: 112px; }}
.hk-ring svg {{ transform: rotate(-90deg); }}
.hk-ring .hk-num {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1; }}
.hk-ring .hk-num b {{ font-size: 1.9rem; font-weight: 700; letter-spacing: -0.03em; color: var(--ink); }} .hk-ring .hk-num span {{ font-size: .68rem; color: var(--muted); margin-top: .2rem; }}
.hk-bars {{ display: grid; gap: .55rem; }}
.hk-bar {{ display: grid; grid-template-columns: 11.5rem 1fr 3rem; gap: .8rem; align-items: center; font-size: .88rem; }}
.hk-bar .hk-track {{ height: 9px; background: #EEF0F6; border-radius: 99px; overflow: hidden; }} .hk-bar .hk-fill {{ height: 100%; border-radius: 99px; }}
.hk-bar .hk-val {{ text-align: right; font-weight: 650; font-variant-numeric: tabular-nums; }} .hk-bar .hk-na {{ color: var(--muted); font-weight: 500; }}
.hk-bar small {{ color: var(--muted); display: block; font-size: .72rem; }}
.hk-grid {{ display: grid; gap: .45rem; font-size: .86rem; }}
.hk-row {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 1rem; align-items: center; padding: .55rem .8rem; background: #fff; border: 1px solid var(--line); border-radius: 12px; }}
.hk-dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 99px; margin-right: 5px; vertical-align: middle; }}
.hk-dot.y {{ background: var(--brand); }} .hk-dot.n {{ background: #fff; border: 2px solid #D0D5DD; box-sizing: border-box; }}
.hk-muted {{ color: var(--muted); }}
.hk-label {{ font-size: .72rem; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }}
@media (max-width: 720px) {{ .hk-hero {{ flex-direction: column; align-items: flex-start; }} .hk-bar {{ grid-template-columns: 1fr 2fr 2.6rem; }} .hk-row {{ grid-template-columns: 1fr; }} }}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def tone(score):
    """Colour for a 0-100 score."""
    if score is None:
        return GREY
    return GOOD if score >= 80 else BRAND if score >= 60 else WARN if score >= 40 else BAD


def ring(score, label="out of 100", size=112, colour=None):
    """A donut showing a 0-100 score; a dash when there is no score."""
    r, w = 44, 9
    circ = 2 * 3.14159265 * r
    frac = 0 if score is None else max(0, min(score, 100)) / 100
    colour = colour or tone(score)
    return (f'<div class="hk-ring" style="width:{size}px;height:{size}px"><svg width="{size}" height="{size}" viewBox="0 0 100 100">'
            f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="#EEF0F6" stroke-width="{w}"/>'
            f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{colour}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="{circ * frac:.1f} {circ:.1f}"/></svg>'
            f'<div class="hk-num"><b>{"&mdash;" if score is None else round(score)}</b><span>{html.escape(label)}</span></div></div>')


def chip(text, kind=""):
    return f'<span class="hk-chip {kind}">{html.escape(str(text))}</span>'


def hero(name, subtitle, score, ring_label, chips=()):
    """The top of a report: the hotel, a line under it, chips, and the score ring."""
    st.markdown(f'<div class="hk-hero">{ring(score, ring_label) if (ring_label or score is not None) else ""}<div><div class="hk-name">{html.escape(str(name))}</div>'
                f'<div class="hk-sub">{html.escape(str(subtitle))}</div><div class="hk-chips">{"".join(chips)}</div></div></div>', unsafe_allow_html=True)


def bars(rows):
    """
    Horizontal score bars. rows: [{"label", "score" (0-100 or None), "note" (optional), "colour" (optional)}]. A row with no score is shown as 'not assessed', never as zero.
    """
    out = []
    for r in rows:
        s = r.get("score")
        note = f"<small>{html.escape(str(r['note']))}</small>" if r.get("note") else ""
        if s is None:
            out.append(f'<div class="hk-bar"><div>{html.escape(str(r["label"]))}{note}</div><div class="hk-track"></div><div class="hk-val hk-na">n/a</div></div>')
        else:
            out.append(f'<div class="hk-bar"><div>{html.escape(str(r["label"]))}{note}</div><div class="hk-track"><div class="hk-fill" style="width:{max(2, min(s, 100)):.0f}%;'
                       f'background:{r.get("colour") or tone(s)}"></div></div><div class="hk-val">{s:.0f}</div></div>')
    st.markdown(f'<div class="hk-bars">{"".join(out)}</div>', unsafe_allow_html=True)


def count_bars(rows, neutral=False):
    """
    Horizontal bars that say 'n of m': rows [{"label", "named", "of", "note"}]. Green when the hotel was named in at least three quarters of the answers, amber when sometimes, red when never; a row with no
    answers is shown as such, never as zero.
    """
    out = []
    for r in rows:
        n, of = r.get("named", 0), r.get("of", 0)
        note = f"<small>{html.escape(str(r['note']))}</small>" if r.get("note") else ""
        if not of:
            out.append(f'<div class="hk-bar wide"><div>{html.escape(str(r["label"]))}{note}</div><div class="hk-track"></div><div class="hk-val hk-na">no answers</div></div>')
            continue
        pct = 100 * n / of
        colour = r.get("colour") or ("#6B5CE7" if neutral else "#1B873F" if pct >= 75 else "#D9822B" if n else "#C0392B")
        out.append(f'<div class="hk-bar wide"><div>{html.escape(str(r["label"]))}{note}</div><div class="hk-track"><div class="hk-fill" style="width:{max(3, pct):.0f}%;background:{colour}"></div></div>'
                   f'<div class="hk-val">{n} of {of}</div></div>')
    st.markdown(f'<div class="hk-bars">{"".join(out)}</div>', unsafe_allow_html=True)


def dots(named, of):
    """● ● ○ : which of a question's answers named the hotel."""
    return "".join(f'<span class="hk-dot {"y" if i < named else "n"}"></span>' for i in range(of))


def ranked_chart(rows, label="name", value="value", highlight="is_target", fmt="{:.0f}%", height_per=34, domain_max=None):
    """
    A clean horizontal bar chart: bars sorted high to low, the hotel in the brand colour and the rest muted, values at the bar ends, no axes or gridlines.
    rows: [{label, value, highlight}] with plain numbers; the chart carries no third-party markup.
    """
    import altair as alt
    data = [{"name": str(r[label])[:38], "value": r[value] or 0, "me": bool(r.get(highlight)), "text": (fmt(r[value] or 0) if callable(fmt) else fmt.format(r[value] or 0))} for r in rows]
    if not data:
        return
    order = [d["name"] for d in data]
    top = domain_max or max(10, max(d["value"] for d in data) * 1.18)
    base = alt.Chart(alt.Data(values=data)).encode(y=alt.Y("name:N", sort=order, title=None, axis=alt.Axis(labelLimit=260, ticks=False, domain=False, labelFontSize=12, labelColor=INK)))
    bar = base.mark_bar(cornerRadiusEnd=5, size=16).encode(
        x=alt.X("value:Q", title=None, axis=None, scale=alt.Scale(domain=[0, top])),
        color=alt.condition(alt.datum.me, alt.value(BRAND), alt.value(BAR_OTHER)), tooltip=[alt.Tooltip("name:N", title="Hotel"), alt.Tooltip("text:N", title="Value")])
    txt = base.mark_text(align="left", dx=6, fontSize=12, fontWeight=600, color=INK).encode(x="value:Q", text="text:N")
    st.altair_chart((bar + txt).configure(background="rgba(0,0,0,0)").configure_view(stroke=None).properties(height=height_per * len(data) + 8), width="stretch")


def lines_chart(frame, height=240, colours=None):
    """Smooth multi-line chart from a pandas DataFrame indexed by run label: the hotel's line is the brand colour, others muted palette."""
    import altair as alt
    import pandas as pd
    long = frame.reset_index(names="run").melt("run", var_name="series", value_name="value")
    names = [c for c in frame.columns]
    palette = colours or ([BRAND] + ["#F79009", "#12B76A", "#06AED4", "#EE46BC", "#98A2B3", "#84CAFF"])[:len(names)]
    chart = alt.Chart(long).mark_line(point=alt.OverlayMarkDef(size=45), strokeWidth=2.4, interpolate="monotone").encode(
        x=alt.X("run:N", sort=list(frame.index), title=None, axis=alt.Axis(labelAngle=0, labelColor=MUTED, domain=False, ticks=False)),
        y=alt.Y("value:Q", title=None, axis=alt.Axis(gridColor="#EEF0F6", domain=False, ticks=False, labelColor=MUTED)),
        color=alt.Color("series:N", scale=alt.Scale(domain=names, range=palette), legend=alt.Legend(orient="bottom", title=None, labelColor=INK)),
        tooltip=["run", "series", "value"])
    st.altair_chart(chart.configure(background="rgba(0,0,0,0)").configure_view(stroke=None).properties(height=height), width="stretch")


def note(text):
    """A short 'how to read this' line folded away, so explanations do not crowd the figures."""
    with st.popover("How to read this", icon=":material/info:"):
        st.markdown(text)
