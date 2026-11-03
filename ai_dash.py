"""
The AI visibility tab of a hotel's dashboard, built from what every weekly check already saved: how often each hotel was named (coverage), where it was placed (position) and how it was described (sentiment),
for this hotel and its top competitors over time; the pages the assistant cited, and how that changed since the check before.

Reading it honestly: one assistant (Claude with live web search), a sample of answers each week. Coverage is the share of sampled answers that named the hotel; position is its average place in the hotels an answer
listed (1 is first; lower is better); sentiment runs from -100 (all negative) to +100 (all positive). A few answers per week means small moves are noise, and the tab says so.
"""

import datetime as dt
import html

import ai_insights
from charts import BAD, BRAND, GOOD, GREY, esc
from timeutil import uk_date

PALETTE = ["#F79009", "#12B76A", "#06AED4", "#EE46BC", "#7A5AF8", "#84CAFF"]
OWN = "#E11D74"


def _short_date(iso):
    t = uk_date(iso)
    parts = t.split(chr(160)) if t else []
    return " ".join(parts[1:3]) if len(parts) >= 3 else str(iso)[:10]


def lines_svg(runs, series, lo, hi, invert=False, w=760, h=270, name="value", fmt="{:g}"):
    """Several lines over the checks. series: [{name, own, points: [value or None]}]. Missing values break the line; each point has a hover label."""
    l, r, t, b = 40, 18, 14, 30
    iw, ih = w - l - r, h - t - b
    n = len(runs)
    xs = [l + (iw * i / (n - 1) if n > 1 else iw / 2) for i in range(n)]

    def y(v):
        f = (v - lo) / (hi - lo) if hi != lo else 0.5
        f = max(0.0, min(1.0, f))
        return t + ih * (f if invert else 1 - f)
    ticks = sorted({round(lo + (hi - lo) * q / 4, 1) for q in range(5)})
    grid = "".join(f'<line x1="{l}" y1="{y(v):.1f}" x2="{w - r}" y2="{y(v):.1f}" stroke="#eef0f6"/><text x="{l - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="#667085">{fmt.format(v)}</text>' for v in ticks)
    step = max(1, n // 8)
    xl = "".join(f'<text x="{xs[i]:.1f}" y="{h - 8}" font-size="10" text-anchor="middle" fill="#667085">{esc(_short_date(runs[i]["run_at"]))}</text>' for i in range(n) if i % step == 0 or i == n - 1)
    out = []
    cm = colours(series)
    for s in sorted(series, key=lambda s: s["own"]):               # the hotel is drawn last, on top
        col = cm[s["name"]]
        seg, pts = [], []
        for i, v in enumerate(s["points"]):
            if v is None:
                if seg:
                    pts.append(seg)
                seg = []
                continue
            seg.append((xs[i], y(v)))
        if seg:
            pts.append(seg)
        sw = 3 if s["own"] else 1.8
        for sg in pts:
            if len(sg) > 1:
                out.append(f'<polyline fill="none" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round" points="' + " ".join(f"{a:.1f},{c:.1f}" for a, c in sg) + '"/>')
        for i, v in enumerate(s["points"]):
            if v is not None:
                out.append(f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="{4 if s["own"] else 2.6}" fill="{col}"><title>{esc(s["name"])}: {fmt.format(v)} ({esc(_short_date(runs[i]["run_at"]))})</title></circle>')
    return f'<svg class="trend" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(name)} over time">{grid}{xl}{"".join(out)}</svg>'


def colours(series):
    """name -> colour: the hotel in pink, each rival its own colour (the same in the chart and its legend)."""
    out, k = {}, 0
    for s in series:
        if s["own"]:
            out[s["name"]] = OWN
        else:
            out[s["name"]] = PALETTE[k % len(PALETTE)]
            k += 1
    return out


def legend(series):
    items = []
    cm = colours(series)
    for s in sorted(series, key=lambda s: (not s["own"], s["name"])):
        col = cm[s["name"]]
        items.append(f'<span class="lg"><i style="background:{col}"></i>{esc(s["name"])}{" (you)" if s["own"] else ""}</span>')
    return '<div class="lgs">' + "".join(items) + "</div>"


def _change(now, before, unit="", better="up", places=1):
    if now is None or before is None:
        return '<span class="delta flat">no earlier check</span>'
    d = round(now - before, places)
    if d == 0:
        return '<span class="delta flat">no change</span>'
    good = (d > 0) == (better == "up")
    return f'<span class="delta {"up" if good else "down"}">{d:+g}{esc(unit)} since the last check</span>'


def _tile(label, value, sub, active=False, target=""):
    return f'<button type="button" class="tab mt{" active" if active else ""}" data-tab="{target}"><span class="kpi-label">{esc(label)}</span><span class="kpi-value">{value}</span><span class="kpi-sub">{sub}</span></button>'


def brand_section(ch):
    runs = ch["runs"]
    rows = ch["rows"]
    if not runs or not rows:
        return '<div class="alert info">No AI answers have been saved for this hotel yet.</div>', None
    me = next((r for r in rows if r["is_target"]), None)
    cov = [{"name": r["name"], "own": r["is_target"], "points": [p["coverage_pct"] for p in r["points"]]} for r in rows]
    pos = [{"name": r["name"], "own": r["is_target"], "points": [p["avg_rank"] for p in r["points"]]} for r in rows]
    sen = [{"name": r["name"], "own": r["is_target"], "points": [p["sentiment"] for p in r["points"]]} for r in rows]
    top_cov = max([v for s in cov for v in s["points"] if v is not None] or [10])
    ranks = [v for s in pos for v in s["points"] if v is not None] or [5]
    last = me["points"][-1] if me else None
    prev = me["points"][-2] if me and len(me["points"]) > 1 else None
    tiles = ""
    if me:
        c1, c0 = last["coverage_pct"], (prev["coverage_pct"] if prev else None)
        p1, p0 = last["avg_rank"], (prev["avg_rank"] if prev else None)
        s1, s0 = last["sentiment"], (prev["sentiment"] if prev else None)
        n = last.get("asked")
        tiles = ('<div class="tab-bar tile-bar" role="tablist">'
                 + _tile("Brand coverage", f"{c1:g}<small>%</small>" if c1 is not None else "n/a", _change(c1, c0, " pts") + (f'<br><span class="hk-muted">{last["mentions"]} of {n} sampled answers</span>' if n else ""), True, "bm-cov")
                 + _tile("Brand position", f"{p1:g}" if p1 is not None else "n/a", _change(p1, p0, "", "down") + '<br><span class="hk-muted">1 is first; lower is better</span>', False, "bm-pos")
                 + _tile("Brand sentiment", (f"{s1:+d}" if s1 is not None else "n/a"), _change(s1, s0, "", "up", 0) + '<br><span class="hk-muted">-100 to +100</span>', False, "bm-sen") + "</div>")
    panels = (f'<div class="tab-panel active" id="bm-cov">{lines_svg(runs, cov, 0, max(20, -(-top_cov * 1.1 // 20) * 20), name="Brand coverage", fmt="{:.0f}%")}{legend(cov)}</div>'
              f'<div class="tab-panel" id="bm-pos">{lines_svg(runs, pos, 1, max(3, max(ranks) + 0.5), invert=True, name="Brand position", fmt="{:g}")}{legend(pos)}<p class="caption">The line drops when the hotel is placed higher. A gap means the hotel was not named that week.</p></div>'
              f'<div class="tab-panel" id="bm-sen">{lines_svg(runs, sen, -100, 100, name="Brand sentiment", fmt="{:+.0f}")}{legend(sen)}</div>')
    return f'<section class="panel"><h4>Brand performance over time</h4><div class="tabs">{tiles}{panels}</div></section>', me


def _changes(cur, prev):
    """Pages cited in the latest check against the one before: -> dict of lists (top, new, increased, stable, decreased, lost)."""
    out = {"top": [], "new": [], "increased": [], "stable": [], "decreased": [], "lost": []}
    for u, p in cur.items():
        q = prev.get(u) if prev is not None else None
        row = {**p, "before": q["cited"] if q else None}
        if prev is None or q is None:
            row["delta"], row["pct"], row["is_new"] = None, None, True
            (out["new"] if prev is not None else out["stable"]).append(row)
            continue
        row["delta"] = p["cited"] - q["cited"]
        row["pct"] = round(100 * row["delta"] / q["cited"]) if q["cited"] else None
        out["increased" if row["delta"] > 0 else "decreased" if row["delta"] < 0 else "stable"].append(row)
    if prev is not None:
        for u, q in prev.items():
            if u not in cur:
                out["lost"].append({**q, "cited": 0, "before": q["cited"], "delta": -q["cited"], "pct": -100})
    out["top"] = sorted(cur.values(), key=lambda r: -r["cited"])[:10]
    for k in ("new", "increased", "stable"):
        out[k].sort(key=lambda r: -r["cited"])
    out["decreased"].sort(key=lambda r: r["delta"])
    out["lost"].sort(key=lambda r: -r["before"])
    top_rows = []
    for r in out["top"]:
        q = prev.get(r["url"]) if prev is not None else None
        top_rows.append({**r, "before": q["cited"] if q else None, "delta": (r["cited"] - q["cited"]) if q else None, "pct": (round(100 * (r["cited"] - q["cited"]) / q["cited"]) if q and q["cited"] else None)})
    out["top"] = top_rows
    return out


def _badge(r):
    if r.get("is_new"):
        return '<span class="delta up">new</span>'
    if r.get("delta") is None:
        return '<span class="delta flat">-</span>'
    if r["delta"] == 0:
        return '<span class="delta flat">no change</span>'
    cls = "up" if r["delta"] > 0 else "down"
    pct = f' {abs(r["pct"])}%' if r.get("pct") is not None else ""
    return f'<span class="delta {cls}">{"&uarr;" if r["delta"] > 0 else "&darr;"}{pct}</span>'


def _page_cell(r):
    t = r.get("title") or r["url"]
    return f'<a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer"><b>{esc(t[:90])}</b></a><br><span class="hk-muted url">{esc(r["url"][:110])}</span>'


def _change_table(rows, empty):
    if not rows:
        return f'<p class="caption">{esc(empty)}</p>'
    body = "".join(f'<tr><td>{_page_cell(r)}</td><td>{r["cited"]}</td><td>{"-" if r.get("delta") is None else format(r["delta"], "+d")}</td><td>{_badge(r)}</td></tr>' for r in rows[:12])
    return f'<div class="table-wrap"><table class="table"><thead><tr><th>Page</th><th>Cited</th><th>Change</th><th></th></tr></thead><tbody>{body}</tbody></table></div>'


def citation_section(cur, prev, own_domain):
    if not cur:
        return '<section class="panel"><h4>Citations</h4><p class="caption">No cited pages have been saved yet. They appear after a check that used the assistant.</p></section>'
    ch = _changes(cur, prev)
    note = ("Compared with the check before." if prev is not None else "There is only one check so far, so nothing can be compared yet.")
    names = [("top", "Top"), ("new", "New"), ("increased", "Increased"), ("stable", "Stable"), ("decreased", "Decreased"), ("lost", "Lost")]
    empty = {"top": "Nothing cited.", "new": "No page was cited for the first time.", "increased": "No page was cited more often.", "stable": "No page was cited the same number of times.",
             "decreased": "No page was cited less often.", "lost": "No page dropped out of the citations."}
    bar = '<div class="tab-bar">' + "".join(f'<button type="button" class="tab{" active" if k == "top" else ""}" data-tab="cc-{k}">{lbl} <small>{len(ch[k])}</small></button>' for k, lbl in names) + "</div>"
    pan = "".join(f'<div class="tab-panel{" active" if k == "top" else ""}" id="cc-{k}">{_change_table(ch[k], empty[k])}</div>' for k, _l in names)
    win = sorted([r for r in ch["increased"] + ch["new"]], key=lambda r: (-(r["pct"] or 999), -r["cited"]))[:3]
    los = sorted([r for r in ch["decreased"] + ch["lost"]], key=lambda r: (r["pct"] if r["pct"] is not None else 0, r["delta"]))[:3]

    def mini(rows, empty_):
        if not rows:
            return f'<p class="caption">{empty_}</p>'
        return "<ul class=\"wl\">" + "".join(f'<li><a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">{esc((r.get("title") or r["url"])[:80])}</a> '
                                             + (f'<span class="delta {"up" if (r["delta"] or 0) > 0 else "down"}">{r["delta"]:+d}</span>' if r.get("delta") is not None else '<span class="delta up">new</span>') + "</li>" for r in rows) + "</ul>"
    wl = ('<div class="ov-grid even"><section class="panel"><h4>Top winners</h4>' + mini(win, "No page gained citations.") + '</section><section class="panel"><h4>Top losers</h4>' + mini(los, "No page lost citations.") + "</section></div>")
    # all cited URLs
    allrows = sorted(cur.values(), key=lambda r: (-r["cited"], r["url"]))

    def trow(r):
        kind = ai_insights.source_kind(r["domain"], own_domain)
        brand = "N/A" if r.get("own_site") else ("Yes" if r.get("names_hotel") else "No")
        cls = {"Yes": "good", "No": "bad", "N/A": ""}[brand]
        comp = esc(r.get("names_competitor") or "-")
        return (f'<tr><td>{_page_cell(r)}</td><td>{r["cited"]}</td><td><span class="hk-chip {cls}">{brand}</span></td><td>{esc(r["domain"])}</td><td>{esc(kind)}</td><td>{comp}</td></tr>')
    head = "<thead><tr><th>Page</th><th>Cited</th><th>Hotel named there</th><th>Site</th><th>Type of site</th><th>Competitors named there</th></tr></thead>"
    first, more = allrows[:20], allrows[20:80]
    table = f'<div class="table-wrap"><table class="table">{head}<tbody>{"".join(trow(r) for r in first)}</tbody></table></div>'
    if more:
        table += f'<details class="details"><summary>{len(more)} more pages</summary><div class="details-body"><div class="table-wrap"><table class="table">{head}<tbody>{"".join(trow(r) for r in more)}</tbody></table></div></div></details>'
    return (f'<h3 class="grp" style="margin-top:24px">Citations</h3><p class="caption">The web pages the assistant relied on when it answered. {note} '
            f'Each count is the number of answers that cited the page.</p>{wl}<section class="panel"><h4>Citation changes</h4><div class="tabs">{bar}{pan}</div></section>'
            f'<section class="panel"><h4>All cited pages ({len(allrows)})</h4>{table}</section>')


def panel(db, hotel):
    """The whole tab as HTML for one hotel."""
    key = hotel["hotel_key"]
    ch = db.competitor_history(key, 5)
    brand, _me = brand_section(ch)
    runs = [r["run_id"] for r in ch["runs"]]
    with_pages = [rid for rid in runs if db.run_pages(rid)]
    cur = {p["url"]: p for p in db.run_pages(with_pages[-1])} if with_pages else {}
    prev = {p["url"]: p for p in db.run_pages(with_pages[-2])} if len(with_pages) > 1 else None
    own = key.split("/")[0]
    chips = ('<div class="hk-chips"><span class="hk-chip brand">Engine: Claude with live web search</span><span class="hk-chip">' + f'{len(runs)} weekly check{"s" if len(runs) != 1 else ""}</span>'
             '<span class="hk-chip">Sampled answers: small moves are noise</span></div>')
    return (f'<p class="lede">How AI assistants talk about this hotel and the hotels around it. One assistant, a sample of answers each week: ChatGPT, Gemini and Google AI Overviews are not included. '
            f'Coverage is how often the hotel was named; position is its average place in the hotels listed.</p>{chips}{brand}{citation_section(cur, prev, own)}')
