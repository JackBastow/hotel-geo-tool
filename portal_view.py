"""
The hotel dashboard as HTML: the progress line, the headline numbers, the score trend, the action list (with the buttons a hotel user presses) and the history of checks.

The same page is shown to the hotel (editable) and, read-only, to the operator in the admin pages, so the operator sees exactly what the hotel sees.
Wording rule: this shows PROGRESS (what was done, what changed). It never claims the actions caused the change.
"""

import datetime as dt
import json

import progress
import trend
from charts import BAD, BRAND, GOOD, GREY, WARN, esc
from timeutil import uk_date, uk_time

PRI_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRI_TONE = {"critical": "bad", "high": "bad", "medium": "warn", "low": ""}
TEAM = {"web": "Website", "reputation management": "Reputation", "distribution": "Distribution", "marketing": "Marketing", "operations": "Operations", "PR": "PR"}
STATUS_LABEL = [("todo", "To do"), ("working", "Working on it"), ("done", "Done"), ("not_relevant", "Not relevant")]
SECTIONS = [("working", "Working on it", True), ("todo", "To do", True), ("completed", "Completed", True), ("cleared", "Not flagged this time", False), ("not_relevant", "Marked not relevant", False)]


def chip(text, kind=""):
    return f'<span class="hk-chip {kind}">{esc(text)}</span>'


def trend_svg(points, w=640, h=190, maximum=100, name="Readiness score"):
    """A value at each check as a labelled line (the readiness score on a 0 to 100 scale by default)."""
    pts = [p for p in points if p.get("score") is not None]
    if not pts:
        return '<p class="caption">No score yet.</p>'
    l, r, t, b = 36, 18, 14, 30
    iw, ih = w - l - r, h - t - b
    xs = [l + (iw * i / (len(pts) - 1) if len(pts) > 1 else iw / 2) for i in range(len(pts))]
    ys = [t + ih * (1 - max(0, min(maximum, p["score"])) / maximum) for p in pts]
    ticks = sorted({round(maximum * q / 4) for q in range(5)})
    grid = "".join(f'<line x1="{l}" y1="{t + ih * (1 - v / maximum):.1f}" x2="{w - r}" y2="{t + ih * (1 - v / maximum):.1f}" stroke="#eef0f6"/><text x="{l - 6}" y="{t + ih * (1 - v / maximum) + 4:.1f}" font-size="10" text-anchor="end" fill="#667085">{v}</text>' for v in ticks)
    line = f'<polyline fill="none" stroke="{BRAND}" stroke-width="2.6" stroke-linejoin="round" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)) + '"/>' if len(pts) > 1 else ""
    step = max(1, len(pts) // 8)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{BRAND}"/><text x="{x:.1f}" y="{y - 9:.1f}" font-size="11" font-weight="600" text-anchor="middle" fill="#1a1d29">{p["score"]:g}</text>'
                   + (f'<text x="{x:.1f}" y="{h - 8}" font-size="10" text-anchor="middle" fill="#667085">{esc(_short_date(p["run_at"]))}</text>' if i % step == 0 or i == len(pts) - 1 else "")
                   for i, (x, y, p) in enumerate(zip(xs, ys, pts)))
    return f'<svg class="trend" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(name)} at each check">{grid}{line}{dots}</svg>'


def _short_date(iso):
    t = uk_date(iso)
    parts = t.split(chr(160)) if t else []
    return " ".join(parts[1:3]) if len(parts) >= 3 else str(iso)[:10]


def progress_line(sm):
    """The sentence a hotel (or the operator) can show: what has been done and how the score has moved."""
    a = sm["actions"]
    if sm["runs"] == 0:
        return '<div class="alert info">No check has been run for this hotel yet. The first one appears here as soon as it has run.</div>'
    done = a["completed"]
    if sm["delta"] is None:
        return (f'<div class="pt-progress"><b>Baseline set on {esc(uk_date(sm["first_run_at"]))}.</b> Readiness score {sm["latest_score"]:g}/100. '
                f'Progress shows here after the next weekly check.</div>' if sm["latest_score"] is not None else '<div class="alert info">The first check did not produce a score.</div>')
    word = "improved" if sm["delta"] > 0 else "changed" if sm["delta"] == 0 else "moved"
    return (f'<div class="pt-progress"><b>Since {esc(uk_date(sm["first_run_at"]))}:</b> the readiness score has {word} from <b>{sm["first_score"]:g}</b> to <b>{sm["latest_score"]:g}</b> '
            f'({sm["delta"]:+g}), and <b>{done} action{"s" if done != 1 else ""}</b> {"have" if done != 1 else "has"} been completed'
            + (f' ({a["verified"]} checked and confirmed on the site)' if a["verified"] else "") + '.</div>')


def kpi(label, value, sub, colour=GREY, unit=""):
    return f'<div class="kpi" style="--kc:{colour}"><span class="kpi-label">{esc(label)}</span><span class="kpi-value">{esc(value)}<small>{esc(unit)}</small></span><span class="kpi-sub">{esc(sub)}</span></div>'


def kpis(sm):
    a = sm["actions"]
    sc = sm["latest_score"]
    tone = GOOD if (sc or 0) >= 75 else WARN if (sc or 0) >= 50 else BAD
    d = "" if sm["delta"] is None else f"{sm['delta']:+g} since {_short_date(sm['first_run_at'])}"
    out = [kpi("Readiness score", "-" if sc is None else f"{sc:g}", d or "the first check sets the baseline", tone if sc is not None else GREY, "/100"),
           kpi("Actions completed", a["completed"], f"of {a['total']} recommended" + (f" · {a['verified']} confirmed on the site" if a["verified"] else ""), GOOD),
           kpi("Working on", a["working"], "marked as in progress", BRAND),
           kpi("Still to do", a["todo"] + a["still_flagged"], (f"includes {a['still_flagged']} marked done but still flagged" if a["still_flagged"] else "not started"), WARN if a["todo"] else GOOD)]
    c0, c1 = sm["cov_first"], sm["cov_latest"]
    if c1:
        lo, hi = trend.wilson(*c1)
        sub = f"{c1[0]} of {c1[1]} answers · likely {round(100 * lo)}% to {round(100 * hi)}%" + (f" · at the start: {round(100 * c0[0] / c0[1])}%" if c0 and sm["runs"] > 1 else "")
        out.append(kpi("Named by an AI assistant", f"{round(100 * c1[0] / c1[1])}", sub, BRAND, "%"))
    return '<div class="kpis">' + "".join(out) + "</div>"


def _rec(a):
    try:
        return json.loads(a.get("rec_json") or "{}")
    except ValueError:
        return {}


def _state_chips(a, latest_run_id, runs):
    out = []
    if a["state"] == "resolved":
        out.append(chip("Checked: no longer found on the site", "good") if a["resolution"] == "verified" else chip("Not flagged this time (answers vary: keep an eye on it)", "warn"))
    elif a["status"] == "done" and a["reopened"]:
        out.append(chip("Marked done, but the latest check still flags it", "bad"))
    if runs > 1 and a["first_run_id"] == latest_run_id and a["state"] == "open":
        out.append(chip("New this week", "brand"))
    return "".join(out)


def action_card(a, sm, editable):
    rec = _rec(a)
    kind = progress.classify(a)
    team = TEAM.get(a["team"], a["team"])
    buttons = ""
    if editable:
        buttons = '<div class="seg" role="group" aria-label="Status">' + "".join(
            f'<button type="button" class="act-set{" on" if a["status"] == v else ""}" data-v="{v}">{lbl}</button>' for v, lbl in STATUS_LABEL) + "</div>"
    why = f'<p class="rec-why">{esc(rec.get("why", ""))}</p>' if rec.get("why") else ""
    do = f'<div class="rec-do"><b>What to do</b> {esc(rec.get("action", ""))}</div>' if rec.get("action") else ""
    conf = rec.get("confidence_label")
    return (f'<article class="act {PRI_TONE.get(a["priority"], "")}" data-id="{a["id"]}" data-kind="{kind}"><details class="rec-d"><summary><span class="rec-t">{esc(a["title"])}</span>'
            f'<span class="rec-meta">{chip((a["priority"] or "").capitalize(), PRI_TONE.get(a["priority"], ""))}{chip(team)}{chip("Effort: " + a["effort"]) if a["effort"] else ""}{chip(conf) if conf else ""}</span></summary>'
            f'<div class="rec-body">{why}{do}</div></details><div class="act-row">{_state_chips(a, sm["latest_run_id"], sm["runs"])}{buttons}</div></article>')


def action_board(sm, actions, editable):
    if not actions:
        return '<div class="alert info">No recommendations yet. They appear after the first check.</div>'
    groups = {k: [] for k, _t, _o in SECTIONS}
    for a in actions:
        groups[progress.classify(a)].append(a)
    out = []
    for key, title, openn in SECTIONS:
        items = sorted(groups[key], key=lambda a: (PRI_ORDER.get(a["priority"], 9), a["id"]))
        if not items:
            continue
        cards = "".join(action_card(a, sm, editable) for a in items)
        if openn:
            out.append(f'<h3 class="grp">{esc(title)} <small>{len(items)}</small></h3>{cards}')
        else:
            out.append(f'<details class="details"><summary>{esc(title)} ({len(items)})</summary><div class="details-body">{cards}</div></details>')
    return "".join(out)


def history_table(runs):
    if not runs:
        return ""
    rows = "".join(f'<tr><td>{esc(uk_time(r["run_at"]))}</td><td>{"-" if r["headline_score"] is None else format(r["headline_score"], "g")}</td>'
                   f'<td>{esc(str(r["recs_total"]) if r["recs_total"] is not None else "-")}</td><td>' + (f'<a href="/r/{r["access_token"]}">Open the full report</a>' if r.get("access_token") else "") + '</td></tr>' for r in runs[:30])
    return ('<div class="table-wrap"><table class="table"><thead><tr><th>Checked (UK time)</th><th>Readiness</th><th>Recommendations</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def dashboard(sm, actions, runs, editable=True, csrf=""):
    h = sm["hotel"]
    nxt = ""
    if h.get("weekly") and sm["last_run_at"]:
        try:
            d = dt.datetime.fromisoformat(sm["last_run_at"].replace("Z", "+00:00")) + dt.timedelta(days=7)
            nxt = chip("Next automatic check: around " + uk_date(d.isoformat()), "brand")
        except ValueError:
            nxt = ""
    latest = runs[0] if runs else None
    btns = ""
    if latest and latest.get("access_token"):
        t = latest["access_token"]
        btns = (f'<a class="btn primary" href="/r/{t}">Open the latest full report</a> <a class="btn" href="/r/{t}/management.pdf">Management report (PDF)</a>')
    hero = (f'<section class="hero"><div><h1>{esc(h["name"])}</h1><div class="sub">{esc(" · ".join(x for x in (h.get("city"), h.get("website")) if x))}</div>'
            f'<div class="hk-chips">{chip("Last checked " + uk_time(sm["last_run_at"]), "brand") if sm["last_run_at"] else ""}{nxt}</div></div><div>{btns}</div></section>')
    board = action_board(sm, actions, editable)
    caveat = ('<p class="caption">This shows progress: what has been done and how the score has moved. It does not prove that the actions caused the change. The AI figures come from a sample of answers from one assistant, '
              'which is why they are given with a range.</p>')
    return (f'<div class="pt" data-csrf="{esc(csrf)}">{hero}{progress_line(sm)}{kpis(sm)}{caveat}'
            f'<div class="sec-head"><h3>Readiness score over time</h3></div><section class="panel">{trend_svg(sm["points"])}</section>'
            f'<div class="sec-head"><h3>Actions completed over time</h3></div><section class="panel">{trend_svg(sm["completed_points"], maximum=max(4, sm["actions"]["total"] or 4), name="Actions completed")}</section>'
            f'<div class="sec-head"><h3>Your actions</h3></div>'
            + ('<p class="lede">Mark each action as you go. After every weekly check the list updates: fixed items are ticked off, and new ones are added.</p>' if editable else "")
            + f'<div id="act-list">{board}</div><div class="sec-head"><h3>Checks so far</h3></div>{history_table(runs)}</div>')
