"""
The "Start here" screen of a hotel's dashboard: one screen that answers, in order, "how visible are we, who is recommended instead, what do I do first, and what changed since last time", with the
three first actions shown OPEN (the issue, the evidence, the exact fix and the Done button in one place). The full dashboard stays in the other tabs for anyone who wants the depth.

After the first check the screen opens on WHAT CHANGED (the weekly view): the score and visibility movement, rivals that now appear, and the actions finished or added since the previous check. The first
check shows what was found instead, and says it is the baseline.

Honest by construction: the AI figures are a sample from one assistant, so changes are called changes in the sample, never proof that an action caused them; nothing is shown that the stored data
does not support (no change is claimed when there was no earlier check).
"""

import html

import portal_view as pv
import progress

esc = html.escape


def _fmt(v):
    return f"{v:g}"


def _delta(now, before, unit="", better_up=True):
    if now is None or before is None:
        return ""
    d = round(now - before, 1)
    if d == 0:
        return "no change since the last check"
    good = (d > 0) == better_up
    return f'<span class="{"good" if good else "bad"}">{d:+g}{unit}</span> since the last check'


def _top_actions(actions, n=3):
    """The first things to do: open actions only, most serious first, those that take the least effort breaking ties."""
    effort = {"low": 0, "medium": 1, "high": 2}
    open_ = [a for a in actions if progress.classify(a) in ("todo", "working")]
    return sorted(open_, key=lambda a: (pv.PRI_ORDER.get(a["priority"], 9), effort.get(a.get("effort") or "", 1), a["id"]))[:n]


def _rivals(ch):
    """-> (me_points, [rivals named most in the latest check], [rivals new in the latest check])"""
    rows = (ch or {}).get("rows") or []
    me = next((r for r in rows if r["is_target"]), None)
    others = [r for r in rows if not r["is_target"]]
    last = [(r["name"], r["points"][-1]["coverage_pct"] or 0) for r in others if r["points"]]
    top = sorted([x for x in last if x[1] > 0], key=lambda x: -x[1])[:3]
    new = [r["name"] for r in others if len(r["points"]) > 1 and (r["points"][-1]["coverage_pct"] or 0) > 0 and (r["points"][-2]["coverage_pct"] or 0) == 0][:3]
    return me, top, new


def _since(actions, prev_run_at):
    """Actions finished and actions added since the previous check."""
    done = [a for a in actions if prev_run_at and progress.classify(a) == "completed" and (a.get("done_at") or a.get("resolved_at") or "") >= prev_run_at]
    return done


def panel(db, hotel, sm, actions, runs, editable=True, prompts_alert=False):
    """The whole screen as HTML. `runs` are newest first, as the dashboard has them."""
    if not runs:
        return '<div class="alert info">The first check has not run yet. This screen fills in as soon as it has: how visible the hotel is, who is recommended instead, and what to do first.</div>'
    try:
        ch = db.competitor_history(hotel["hotel_key"], 8)
    except Exception:  # noqa: BLE001 - a missing piece leaves that tile out; the screen still shows
        ch = None
    me, top_rivals, new_rivals = _rivals(ch)
    weekly = len(runs) > 1
    prev_at = runs[1]["run_at"] if weekly else None
    pts = sm.get("points") or []
    sc_now = sm["latest_score"]
    sc_prev = pts[-2]["score"] if len(pts) > 1 else None

    # ---- the three tiles
    c1 = sm["cov_latest"]
    cov_prev = me["points"][-2]["coverage_pct"] if me and len(me["points"]) > 1 else None
    if c1:
        pct = round(100 * c1[0] / c1[1])
        vis = pv.kpi("Named by an AI assistant", f"{pct}", f"{c1[0]} of {c1[1]} sampled answers" + (f" · {_plain(_delta(pct, cov_prev, ' pts'))}" if cov_prev is not None else ""), pv.BRAND, "%")
    else:
        vis = pv.kpi("Named by an AI assistant", "-", "no AI answers were sampled in the latest check", pv.GREY)
    tone = pv.GOOD if (sc_now or 0) >= 75 else pv.WARN if (sc_now or 0) >= 50 else pv.BAD
    ready = pv.kpi("Readiness score", "-" if sc_now is None else _fmt(sc_now), (_plain(_delta(sc_now, sc_prev)) if sc_prev is not None else "set up to be found and understood"), tone if sc_now is not None else pv.GREY, "/100")
    if top_rivals:
        inst = pv.kpi("Recommended instead", top_rivals[0][0][:34], "; ".join(f"{n} ({p:g}%)" for n, p in top_rivals[:3]) + " · share of sampled answers naming them", pv.WARN)
    else:
        inst = pv.kpi("Recommended instead", "-", "no rivals were named often enough to list", pv.GREY)
    tiles = f'<div class="kpis">{vis}{ready}{inst}</div>'

    # ---- what changed (the weekly view), or what was found (the first check)
    if weekly:
        bits = []
        if sc_prev is not None and sc_now is not None:
            d = round(sc_now - sc_prev, 1)
            bits.append(f"The readiness score {'did not change' if d == 0 else ('went up' if d > 0 else 'went down')}" + ("" if d == 0 else f" by {abs(d):g}") + f" ({_fmt(sc_prev)} to {_fmt(sc_now)}).")
        if cov_prev is not None and c1:
            now_pct = 100 * c1[0] / c1[1]
            d = round(now_pct - cov_prev, 1)
            bits.append(f"In the sampled answers the hotel was named {'about as often as before' if abs(d) < 5 else ('more often' if d > 0 else 'less often')} ({cov_prev:g}% then, {now_pct:g}% now). Sampled answers vary, so only a large, repeated move means something.")
        if new_rivals:
            bits.append("New in the answers: " + ", ".join(esc(n) for n in new_rivals) + ".")
        done = _since(actions, prev_at)
        if done:
            bits.append(f"{len(done)} action{'s' if len(done) != 1 else ''} finished since the last check: " + "; ".join(esc(a["title"])[:70] for a in done[:3]) + ".")
        added = [a for a in actions if a.get("first_run_id") == sm["latest_run_id"] and a["state"] == "open"]
        if added:
            bits.append(f"{len(added)} new recommendation{'s' if len(added) != 1 else ''} appeared in this check.")
        changed = ('<section class="panel"><h4>What changed since the last check</h4><ul class="chg">' + "".join(f"<li>{b}</li>" for b in bits) + "</ul>"
                   '<p class="caption">This shows movement, not cause: a change after an action does not prove the action made it.</p></section>') if bits else ""
    else:
        changed = ('<section class="panel"><h4>This is the first check</h4><p>It sets the baseline. After the next weekly check this screen opens on what changed, so you can see whether the work is moving anything.</p></section>')

    # ---- the first things to do, open: issue, evidence, fix and Done in one place
    first = _top_actions(actions)
    if first:
        cards = "".join(pv.action_card(a, sm, editable).replace('<details class="rec-d">', '<details class="rec-d" open>', 1) for a in first)
        todo = f'<div class="sec-head"><h3>Do these first</h3></div><p class="caption">The most important things still open. Mark each one as you go; it is kept up to date in the Recommendations tab too.</p>{cards}'
    else:
        todo = '<div class="sec-head"><h3>Do these first</h3></div><div class="alert success">Nothing serious is open. Keep the weekly checks running and watch the AI visibility tab.</div>'
    callout = ""
    if prompts_alert:
        callout = ('<section class="talk-callout"><div><h3>Confirm the prompts we ask AI about your hotel</h3><p>Review the recommended set and confirm it, so every check asks the same prompts and progress can be tracked.</p></div>'
                   '<button type="button" class="btn primary" data-goto="prompts">Review the prompts &rarr;</button></section>')
    more = '<p class="caption">Want the depth? <button type="button" class="linkbtn" data-goto="ai">AI visibility</button> · <button type="button" class="linkbtn" data-goto="actions">all recommendations</button> · <button type="button" class="linkbtn" data-goto="strategy">strategy</button>.</p>'
    order = (callout, tiles, changed, todo, more) if weekly else (callout, tiles, todo, changed, more)
    return "".join(order)


def _plain(s):
    import re
    return re.sub(r"<[^>]+>", "", s or "")


def safe(db, hotel, sm, actions, runs, editable, pst=None):
    """panel(), never raising: a problem here leaves the Start here tab out and the rest of the dashboard as it was."""
    try:
        return panel(db, hotel, sm, actions, runs, editable, prompts_alert=bool(pst and pst.get("draft") and not pst.get("active")))
    except Exception:  # noqa: BLE001
        return ""
