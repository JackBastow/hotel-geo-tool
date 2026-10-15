"""
Charts drawn as plain SVG and HTML on the server: no script, no library, and the same output every time. Every label is escaped, so text that came from the web cannot become markup.

These are for the dashboard-style parts of the report (the Overview and the Action plan). The line and bar charts on the AI tab are Vega-Lite specs drawn in the browser (ui_theme.py).
"""

import html
import math

INK, MUTED, LINE = "#1a1d29", "#667085", "#e6e8f0"
BRAND, GOOD, WARN, BAD, GREY = "#4f46e5", "#12b76a", "#f79009", "#f04438", "#98a2b3"
PALETTE = [BRAND, "#06aed4", GOOD, WARN, "#ee46bc", GREY]


def esc(x):
    return html.escape(str(x), quote=True)


def tone(score):
    """Colour for a 0-100 score; grey when there is none."""
    if score is None:
        return GREY
    return GOOD if score >= 80 else BRAND if score >= 60 else WARN if score >= 40 else BAD


def ring(score, label="of 100", size=120, colour=None):
    """A donut for one 0-100 number; a dash when there is no score."""
    r, w = 44, 9
    circ = 2 * math.pi * r
    frac = 0 if score is None else max(0, min(score, 100)) / 100
    colour = colour or tone(score)
    num = "&mdash;" if score is None else str(round(score))
    return (f'<div class="hk-ring" style="width:{size}px;height:{size}px" role="img" aria-label="{esc("no score" if score is None else f"{round(score)} {label}")}">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 100 100"><circle cx="50" cy="50" r="{r}" fill="none" stroke="#eef0f6" stroke-width="{w}"/>'
            f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{colour}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="{circ * frac:.1f} {circ:.1f}"/></svg>'
            f'<div class="hk-num"><b>{num}</b><span>{esc(label)}</span></div></div>')


def donut(parts, size=150, top="", bottom="", legend=True):
    """
    parts: [{"label", "value", "colour"}]. A segmented donut with a number in the middle and, below, a legend with the counts. Zero-value parts are left out of the ring but kept in the legend.
    """
    total = sum(max(p["value"], 0) for p in parts)
    r, w = 42, 15
    circ = 2 * math.pi * r
    segs, off = [], 0.0
    for p in parts:
        v = max(p["value"], 0)
        if not total or not v:
            continue
        ln = circ * v / total
        gap = 1.2 if len([q for q in parts if q["value"] > 0]) > 1 else 0
        segs.append(f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{p["colour"]}" stroke-width="{w}" stroke-dasharray="{max(ln - gap, 0.1):.2f} {circ - max(ln - gap, 0.1):.2f}" '
                    f'stroke-dashoffset="{-off:.2f}" transform="rotate(-90 50 50)"><title>{esc(p["label"])}: {v}</title></circle>')
        off += ln
    track = f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="#eef0f6" stroke-width="{w}"/>'
    centre = (f'<div class="ch-centre"><b>{esc(top)}</b><span>{esc(bottom)}</span></div>' if top else "")
    leg = ""
    if legend:
        leg = '<ul class="ch-legend">' + "".join(f'<li><i style="background:{p["colour"]}"></i>{esc(p["label"])} <b>{p["value"]}</b></li>' for p in parts) + "</ul>"
    return f'<div class="ch-donut"><div class="ch-donut-svg" style="width:{size}px;height:{size}px"><svg viewBox="0 0 100 100" width="{size}" height="{size}" role="img">{track}{"".join(segs)}</svg>{centre}</div>{leg}</div>'


def stacked(parts, legend=True):
    """One horizontal bar split into parts: [{"label", "value", "colour"}]."""
    total = sum(max(p["value"], 0) for p in parts) or 1
    segs = "".join(f'<i style="width:{100 * max(p["value"], 0) / total:.2f}%;background:{p["colour"]}" title="{esc(p["label"])}: {p["value"]}"></i>' for p in parts if p["value"] > 0)
    leg = '<ul class="ch-legend inline">' + "".join(f'<li><i style="background:{p["colour"]}"></i>{esc(p["label"])} <b>{p["value"]}</b></li>' for p in parts) + "</ul>" if legend else ""
    return f'<div class="ch-stacked"><div class="ch-stack-bar">{segs}</div>{leg}</div>'


def bars(rows, suffix="", maximum=100):
    """
    Horizontal bars: [{"label", "value" (None = not assessed), "colour" (optional), "note" (optional), "hot" (bool: the hotel itself)}]. A row with no value reads 'n/a', never zero.
    """
    out = []
    for r in rows:
        v = r.get("value")
        note = f'<small>{esc(r["note"])}</small>' if r.get("note") else ""
        cls = "ch-row hot" if r.get("hot") else "ch-row"
        if v is None:
            out.append(f'<div class="{cls}"><div class="ch-lab">{esc(r["label"])}{note}</div><div class="ch-track"></div><div class="ch-val na">n/a</div></div>')
        else:
            col = r.get("colour") or (BRAND if r.get("hot") else tone(v) if maximum == 100 and r.get("tone", True) else "#c9cfe6")
            out.append(f'<div class="{cls}"><div class="ch-lab">{esc(r["label"])}{note}</div><div class="ch-track"><div class="ch-fill" style="width:{max(1.5, min(100 * v / maximum, 100)):.1f}%;background:{col}"></div></div>'
                       f'<div class="ch-val">{v:g}{esc(suffix)}</div></div>')
    return f'<div class="ch-rows">{"".join(out)}</div>'


def radar(rows, size=300):
    """
    A radar of 0-100 scores: rows [{"label", "value"}]. Only rows with a value are drawn (a category not assessed has no point, never a zero); needs three or more.
    """
    pts = [r for r in rows if r.get("value") is not None]
    if len(pts) < 3:
        return ""
    n, cx, cy = len(pts), size / 2, size / 2
    R = size / 2 - 62
    ang = lambda i: -math.pi / 2 + 2 * math.pi * i / n      # noqa: E731
    rings = "".join(f'<polygon points="{" ".join(f"{cx + R * k / 4 * math.cos(ang(i)):.1f},{cy + R * k / 4 * math.sin(ang(i)):.1f}" for i in range(n))}" fill="none" stroke="{LINE}" stroke-width="1"/>' for k in (1, 2, 3, 4))
    spokes = "".join(f'<line x1="{cx}" y1="{cy}" x2="{cx + R * math.cos(ang(i)):.1f}" y2="{cy + R * math.sin(ang(i)):.1f}" stroke="{LINE}" stroke-width="1"/>' for i in range(n))
    poly = " ".join(f"{cx + R * max(p['value'], 3) / 100 * math.cos(ang(i)):.1f},{cy + R * max(p['value'], 3) / 100 * math.sin(ang(i)):.1f}" for i, p in enumerate(pts))
    dots = "".join(f'<circle cx="{cx + R * max(p["value"], 3) / 100 * math.cos(ang(i)):.1f}" cy="{cy + R * max(p["value"], 3) / 100 * math.sin(ang(i)):.1f}" r="4" fill="{tone(p["value"])}" stroke="#fff" stroke-width="1.5"><title>{esc(p["label"])}: {p["value"]:g}</title></circle>' for i, p in enumerate(pts))
    labels = []
    for i, p in enumerate(pts):
        x, y = cx + (R + 14) * math.cos(ang(i)), cy + (R + 14) * math.sin(ang(i))
        anchor = "middle" if abs(math.cos(ang(i))) < 0.3 else "start" if math.cos(ang(i)) > 0 else "end"
        text = p["label"] if len(p["label"]) <= 20 else p["label"][:19] + "…"
        labels.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" font-size="11" fill="{MUTED}">{esc(text)} <tspan font-weight="700" fill="{INK}">{p["value"]:g}</tspan></text>')
    return (f'<svg class="ch-radar" viewBox="-80 0 {size + 160} {size}" width="100%" style="max-width:{size + 220}px" role="img" aria-label="Scores by area">{rings}{spokes}'
            f'<polygon points="{poly}" fill="{BRAND}" fill-opacity=".14" stroke="{BRAND}" stroke-width="2" stroke-linejoin="round"/>{dots}{"".join(labels)}</svg>')


def matrix(items):
    """
    The priority map: impact (rows) against effort (columns). items: [{"n" (the number shown), "title", "impact" (high|medium|low), "effort" (low|medium|high), "kind" (fix|opportunity)}].
    The top-left cell (high impact, low effort) is the quick-win corner.
    """
    cell = {}
    for it in items:
        imp = it["impact"] if it["impact"] in ("high", "medium", "low") else "medium"
        eff = it["effort"] if it["effort"] in ("low", "medium", "high") else "medium"
        cell.setdefault((imp, eff), []).append(it)
    rows = []
    for imp in ("high", "medium", "low"):
        tds = []
        for eff in ("low", "medium", "high"):
            dots = "".join(f'<a class="mx-dot {esc(i["kind"])}" href="#rec-{i["n"]}" title="{esc(i["title"])}">{i["n"]}</a>' for i in cell.get((imp, eff), []))
            tds.append(f'<div class="mx-cell{" win" if (imp, eff) == ("high", "low") else ""}">{dots}</div>')
        rows.append(f'<div class="mx-lab">{imp.capitalize()} impact</div>' + "".join(tds))
    head = '<div></div>' + "".join(f'<div class="mx-col">{e} effort</div>' for e in ("Low", "Medium", "High"))
    return f'<div class="matrix" role="img" aria-label="Priority map: impact against effort"><div class="mx-grid">{head}{"".join(rows)}</div><p class="caption">Numbers match the list. The top-left corner is the quick wins: high impact for little effort.</p></div>'


def delta(now, before, unit="", better="up"):
    """A small chip: +4 against the last audit (green when it moved the right way). Empty when either number is missing."""
    if now is None or before is None:
        return ""
    d = round(now - before, 1)
    if d == 0:
        return '<span class="delta flat">no change</span>'
    good = (d > 0) == (better == "up")
    d_txt = f"{d:+g}"
    return f'<span class="delta {"up" if good else "down"}">{d_txt}{esc(unit)} since last audit</span>'
