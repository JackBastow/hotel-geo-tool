"""
The hotel dashboard as HTML: the progress line, the headline numbers, the score trend, the action list (with the buttons a hotel user presses) and the history of checks.

The same page is shown to the hotel (editable) and, read-only, to the operator in the admin pages, so the operator sees exactly what the hotel sees.
Wording rule: this shows PROGRESS (what was done, what changed). It never claims the actions caused the change.
"""

import datetime as dt
import urllib.parse
import json
import re

import progress
import trend
from charts import BAD, BRAND, GOOD, GREY, WARN, esc
from timeutil import uk_date, uk_time

PRI_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRI_TONE = {"critical": "bad", "high": "bad", "medium": "warn", "low": ""}
TEAM = {"web": "Website", "reputation management": "Reputation", "distribution": "Distribution", "marketing": "Marketing", "operations": "Operations", "PR": "PR"}
STATUS_LABEL = [("todo", "To do"), ("working", "Working on it"), ("done", "Done"), ("not_relevant", "Not relevant")]
SECTIONS = [("working", "Working on it", True), ("todo", "To do", True), ("completed", "Marked done, waiting for a check to confirm", True), ("verified", "Verified: done and confirmed by a check", True), ("cleared", "No longer flagged by the checks (not marked done)", False), ("not_relevant", "Marked not relevant", False)]


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
            + (f' ({a["verified"]} verified: a later check confirmed {"they are" if a["verified"] != 1 else "it is"} gone)' if a["verified"] else "")
            + (f'. The latest check no longer flags <b>{a["cleared_site"]} more</b>, but nobody marked {"them" if a["cleared_site"] != 1 else "it"} done, so {"they are" if a["cleared_site"] != 1 else "it is"} not counted as completed' if a["cleared_site"] else "") + '.</div>')


def kpi(label, value, sub, colour=GREY, unit=""):
    return f'<div class="kpi" style="--kc:{colour}"><span class="kpi-label">{esc(label)}</span><span class="kpi-value">{esc(value)}<small>{esc(unit)}</small></span><span class="kpi-sub">{esc(sub)}</span></div>'


def kpis_raw(tiles):
    """[(label, value, sub, colour)] -> a row of figure tiles."""
    return '<div class="kpis">' + "".join(kpi(l, v, sub, c) for l, v, sub, c in tiles) + "</div>"


def kpis(sm):
    a = sm["actions"]
    sc = sm["latest_score"]
    tone = GOOD if (sc or 0) >= 75 else WARN if (sc or 0) >= 50 else BAD
    d = "" if sm["delta"] is None else f"{sm['delta']:+g} since {_short_date(sm['first_run_at'])}"
    out = [kpi("Readiness score", "-" if sc is None else f"{sc:g}", d or "the first check sets the baseline", tone if sc is not None else GREY, "/100"),
           kpi("Actions completed", a["completed"], f"marked done, of {a['total']} recommended" + (f" · {a['verified']} verified by a check" if a["verified"] else "") + (f" · {a['cleared_site']} more no longer flagged by the checks" if a["cleared_site"] else ""), GOOD),
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


def _short(iso):
    try:
        return uk_date(iso) if iso else ""
    except Exception:  # noqa: BLE001
        return ""


def _state_chips(a, latest_run_id, runs):
    out = []
    done = a["status"] == "done"
    if a["state"] == "resolved":
        when = _short(a.get("resolved_at"))
        if done and a["resolution"] == "verified":
            out.append(chip(f"Verified: the check on {when} no longer found it" if when else "Verified by a check", "good"))
        elif done and a["resolution"] == "verified_repeat":
            out.append(chip("Verified: not in the answers two checks in a row", "good"))
        elif done:
            out.append(chip("Not flagged this time; one more check to confirm (answers vary)", "warn"))
        elif a["resolution"] == "verified":
            out.append(chip("No longer found on the site (nobody marked this done)", "good"))
        else:
            out.append(chip("Not flagged lately (answers vary: keep an eye on it)", "warn"))
    elif done and a["reopened"]:
        out.append(chip("Marked done, but the latest check still flags it", "bad"))
    elif done:
        out.append(chip("Marked done: the next check will confirm it", "brand"))
    if runs > 1 and a["first_run_id"] == latest_run_id and a["state"] == "open":
        out.append(chip("New this week", "brand"))
    return "".join(out)


def steps_of(rec):
    """An action's steps as [{title, detail, link, copy}]: strategy actions carry them; a fix is turned into what to do, the wording to use and how you will know."""
    out = []
    for x in rec.get("steps") or []:
        out.append(x if isinstance(x, dict) else {"title": str(x)})
    if out:
        return out
    if rec.get("action"):
        out.append({"title": rec["action"]})
    if rec.get("example"):
        out.append({"title": "Use this wording (adapt it to your voice)", "copy": {"label": "Copy wording", "text": rec["example"]}})
    if rec.get("success_check") or rec.get("expected_outcome"):
        out.append({"title": "How you will know it worked", "detail": rec.get("success_check") or rec.get("expected_outcome")})
    return out


def _done_steps(a):
    return {int(x) for x in str(a.get("steps_done") or "").split(",") if x.strip().isdigit()}


def _step_html(i, s, done, editable):
    link = s.get("link") or {}
    lk = (f'<a class="btn small primary" href="{esc(link["url"])}" target="_blank" rel="noopener noreferrer">{esc(link.get("label") or "Open")} &#8599;</a>'
          if str(link.get("url") or "").startswith(("http://", "https://")) else "")
    cp = ""
    if (s.get("copy") or {}).get("text"):
        cp = (f'<div class="th-reply a2-copy"><div class="th-reply-h"><b>{esc(s["copy"].get("label") or "Copy")}</b><button type="button" class="btn small" data-copy>Copy</button></div>'
              f'<pre class="reply">{esc(s["copy"]["text"])}</pre></div>')
    return (f'<li class="a2-step{" done" if i in done else ""}"><label class="a2-check"><input type="checkbox" data-step="{i}"{" checked" if i in done else ""}{"" if editable else " disabled"}>'
            f'<span class="a2-num">{i + 1}</span></label><div class="a2-step-b"><b>{esc(s.get("title") or "")}</b>'
            + (f'<p>{esc(s["detail"])}</p>' if s.get("detail") else "") + (f'<div class="a2-btns">{lk}</div>' if lk else "") + cp + "</div></li>")


def action_card2(a, sm, editable):
    """An action as a card that drops down into clear, numbered steps (with buttons to the right page and text to copy); the reasoning and evidence are one more click away."""
    rec = _rec(a)
    steps = steps_of(rec)
    done = _done_steps(a)
    team = TEAM.get(a["team"], a["team"])
    eff = a["effort"] or ""
    eff = f"{eff} effort" if eff.lower() in ("small", "medium", "large", "low", "high") else eff
    kicker = " · ".join(x for x in (rec.get("kind_label") or "", (a["priority"] or "").capitalize() + " priority" if a["priority"] else "", team, eff) if x)
    sub = rec.get("finding") or rec.get("why") or ""
    buttons = ""
    if editable:
        buttons = '<div class="seg" role="group" aria-label="Status">' + "".join(
            f'<button type="button" class="act-set{" on" if a["status"] == v else ""}" data-v="{v}">{lbl}</button>' for v, lbl in STATUS_LABEL) + "</div>"
    ev = []
    for e in (rec.get("evidence") or [])[:3]:
        if str(e.get("url") or "").startswith("http"):
            ev.append(f'<a href="{esc(e["url"])}" target="_blank" rel="noopener noreferrer">{esc(urllib.parse.urlparse(e["url"]).netloc + urllib.parse.urlparse(e["url"]).path)}</a>' + (f' &mdash; {esc((e.get("snippet") or "")[:200])}' if e.get("snippet") else ""))
    more = ("".join(f'<p><b>{esc(l)}</b> {t}</p>' for l, t in (("Why it matters:", esc(rec.get("why", "")) if rec.get("why") and rec.get("why") != sub else ""),
                                                             ("Evidence:", "<br>".join(ev)), ("How sure:", esc(rec.get("confidence_label") or ""))) if t))
    prog = f'<span class="a2-prog">{len(done & set(range(len(steps))))} of {len(steps)} steps</span>' if steps else ""
    return (f'<article class="act act2 {PRI_TONE.get(a["priority"], "")}" data-id="{a["id"]}" data-kind="{progress.board_group(a)}"><details class="a2"><summary class="a2-sum"><div class="a2-main">'
            f'<div class="a2-kicker">{esc(kicker)}</div><div class="a2-title">{esc(a["title"])}</div>' + (f'<div class="a2-sub">{esc(sub[:220])}</div>' if sub else "")
            + f'</div><div class="a2-side">{prog}<span class="a2-chev"></span></div></summary><div class="a2-body">'
            + (f'<ol class="a2-steps">{"".join(_step_html(i, s, done, editable) for i, s in enumerate(steps))}</ol>' if steps else "")
            + (f'<details class="a2-more"><summary>Why, and the evidence</summary><div>{more}</div></details>' if more else "")
            + f'</div></details><div class="act-row">{_state_chips(a, sm["latest_run_id"], sm["runs"])}{buttons}</div></article>')


def action_card(a, sm, editable, lead=None):
    rec = _rec(a)
    kind = progress.board_group(a)
    team = TEAM.get(a["team"], a["team"])
    buttons = ""
    if editable:
        buttons = '<div class="seg" role="group" aria-label="Status">' + "".join(
            f'<button type="button" class="act-set{" on" if a["status"] == v else ""}" data-v="{v}">{lbl}</button>' for v, lbl in STATUS_LABEL) + "</div>"
    def row(label, text):
        return f'<div class="rec-row"><b>{esc(label)}</b><span>{text}</span></div>' if text else ""
    ev = []
    for e in (rec.get("evidence") or [])[:3]:
        sn = (e.get("snippet") or "").strip()
        if not sn:
            continue
        link = f'<a href="{esc(e["url"])}" target="_blank" rel="noopener noreferrer">{esc(urllib.parse.urlparse(e["url"]).path or "/")}</a>: ' if str(e.get("url") or "").startswith("http") else ""
        ev.append(f'{link}{"" if sn.lower().startswith(("pages inspected", "no page about")) else "&ldquo;"}{esc(sn[:300])}{"" if sn.lower().startswith(("pages inspected", "no page about")) else "&rdquo;"}')
    why = (row("The issue", esc(rec.get("finding", ""))) + row("Evidence", "<br>".join(ev)) + row("Why it matters", esc(rec.get("why", ""))))
    steps = rec.get("steps") or []
    def step_html(x):
        if not isinstance(x, dict):
            return esc(str(x))
        lk = x.get("link") or {}
        t = esc(x.get("title") or "")
        if str(lk.get("url") or "").startswith("http"):
            t = f'<a href="{esc(lk["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{t}</a>'
        cp = x.get("copy") or {}
        return (t + (f'<br><span class="caption">{esc(x["detail"])}</span>' if x.get("detail") else "")
                + (f'<details class="details"><summary>{esc(cp.get("label") or "Text to copy")}</summary><pre class="copy-text">{esc(cp.get("text") or "")}</pre></details>' if cp.get("text") else ""))
    do = ((row("Steps", "<ol class=\"steps-mini\">" + "".join(f"<li>{step_html(x)}</li>" for x in steps) + "</ol>") if steps else row("What to do", esc(rec.get("action", ""))))
          + row("Example wording", esc(rec.get("example", "")) if rec.get("example") else "")
          + row("How you will know", esc(rec.get("success_check") or rec.get("expected_outcome") or "")))
    conf = rec.get("confidence_label")
    import advice
    track = rec.get("track") or advice.track_of({"id": rec.get("id", ""), "source": a.get("source") or rec.get("source", ""), "tag": rec.get("tag", "")})
    # `lead` (a number) is the short form used on Start here: the number, the title and what to do are visible at once, and the reasoning opens on request
    n_html = f'<span class="act-n">{lead}</span>' if lead else ""
    do_html = (f'<div class="act-do"><b>What to do</b>{esc(rec.get("action", ""))}</div>' if lead and rec.get("action") else "")
    more = '<span class="act-more">Why, and the evidence</span>' if lead else ""
    return (f'<article class="act {PRI_TONE.get(a["priority"], "")}{" first" if lead else ""}" data-id="{a["id"]}" data-kind="{kind}" data-track="{track}"><details class="rec-d"><summary>{n_html}<span class="rec-t">{esc(a["title"])}</span>'
            f'<span class="rec-meta">{chip((a["priority"] or "").capitalize(), PRI_TONE.get(a["priority"], ""))}{chip(team)}{chip("Effort: " + a["effort"]) if a["effort"] else ""}{chip(conf) if conf else ""}{chip(advice.TRACKS.get(track, ""), "brand")}</span>{more}</summary>'
            f'<div class="rec-body">{why}{do}</div></details>{do_html}<div class="act-row">{_state_chips(a, sm["latest_run_id"], sm["runs"])}{buttons}</div></article>')


def action_board(sm, actions, editable, strategy_context="", research_html=""):
    """The Actions tab: the fixes (the hotel's own site, listings and data) and, in their own section, the strategy actions (getting onto the outside sources AI reads)."""
    if not actions:
        return '<div class="alert info">No actions yet. They appear after the first check.</div>'
    strat = [a for a in actions if a.get("source") == "strategy"]
    fixes = [a for a in actions if a.get("source") != "strategy"]
    open_s = sum(1 for a in strat if progress.board_group(a) in ("todo", "working"))
    open_f = sum(1 for a in fixes if progress.board_group(a) in ("todo", "working"))
    s_html = ('<p class="lede">The bigger moves: getting onto the outside sources AI assistants read about hotels like yours (articles, guides, tourism boards, directories, review sites, creators), '
              'so you are positioned in the market you want. Each has its steps.</p>'
              + research_html
              + (_board(sm, strat, editable, filters=False) if strat else '<div class="alert info">No strategy actions yet. Complete your hotel profile (Settings) and they appear for the market you describe; '
                 'the next check adds the sites the assistant was seen to use.</div>')
              + (f'<details class="details"><summary>Where you could win, and what makes you different</summary><div class="details-body">{strategy_context}</div></details>' if strategy_context else "")
              + '<p class="caption">Being on a source does not guarantee that an assistant will recommend you, and paying for undisclosed placement is never suggested. Another hotel group&rsquo;s own website, '
                'or a rival hotel&rsquo;s, is never suggested as a source.</p>')
    f_html = _board(sm, fixes, editable) if fixes else '<div class="alert info">No fixes flagged.</div>'
    return (f'<div class="tabs act-tabs"><div class="tab-bar act-switch" role="tablist">'
            f'<button type="button" class="tab active" data-tab="act-fixes"><span class="as-n">{open_f}</span><span class="as-t"><b>Fixes</b><small>Your website, listings and data: quicker, concrete fixes</small></span></button>'
            f'<button type="button" class="tab" data-tab="act-strategy"><span class="as-n">{open_s}</span><span class="as-t"><b>Strategy</b><small>Longer-term: get onto the sources AI reads and become one</small></span></button></div>'
            f'<div class="tab-panel active" id="act-fixes">{f_html}</div><div class="tab-panel" id="act-strategy">{s_html}</div></div>')


def _board(sm, actions, editable, filters=True):
    groups = {k: [] for k, _t, _o in SECTIONS}
    for a in actions:
        groups[progress.board_group(a)].append(a)
    bar = ('<div class="filters-bar" role="group" aria-label="Filter by kind of action"><button type="button" class="fchip on" data-t="all">All kinds</button>'
           '<button type="button" class="fchip" data-t="visibility">AI visibility opportunities</button><button type="button" class="fchip" data-t="content">Website content</button>'
           '<button type="button" class="fchip" data-t="accuracy">Data accuracy</button></div>')
    out = [bar] if filters else []
    for key, title, openn in SECTIONS:
        items = sorted(groups[key], key=lambda a: (PRI_ORDER.get(a["priority"], 9), a["id"]))
        if not items:
            continue
        cards = "".join(action_card2(a, sm, editable) for a in items)
        if openn:
            out.append(f'<h3 class="grp">{esc(title)} <small>{len(items)}</small></h3>{cards}')
        else:
            out.append(f'<details class="details"><summary>{esc(title)} ({len(items)})</summary><div class="details-body">{cards}</div></details>')
    return "".join(out)


def research_box(res, running, post_url, csrf, can_run=True):
    """The line above the strategy actions: which specific sources were found for the hotel's market, and a button to look (again)."""
    when = uk_date(res["at"]) if res and res.get("at") else ""
    if running:
        msg = '<b>Looking for the specific sources and contacts for your market&hellip;</b> This takes a minute or two; refresh the page to see them.'
    elif res and res.get("status") == "ok" and res.get("sources"):
        msg = f'<b>{len(res["sources"])} specific sources found for your market</b> ({esc(when)}), with their contact pages: they are in the actions below.'
    elif res:
        msg = f'<b>No specific sources found yet.</b> {esc(res.get("reason") or "")}'
    else:
        msg = '<b>Find the specific sources for your market:</b> the tourism board, directories, guides, writers, operators and awards that fit you, with their contact pages.'
    btn = (f'<form method="post" action="{esc(post_url)}" style="display:inline"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="btn small" type="submit">'
           f'{"Look again" if res else "Find sources and contacts"}</button></form>') if (can_run and not running and post_url) else ""
    return f'<div class="research-box"><span>{msg}</span>{btn}</div>'


def history_table(runs):
    if not runs:
        return ""
    rows = "".join(f'<tr><td>{esc(uk_time(r["run_at"]))}</td><td>{"-" if r["headline_score"] is None else format(r["headline_score"], "g")}</td>'
                   f'<td>{esc(str(r["recs_total"]) if r["recs_total"] is not None else "-")}</td><td>' + (f'<a href="/r/{r["access_token"]}">Detailed analysis</a>' if r.get("access_token") else "") + '</td></tr>' for r in runs[:30])
    return ('<div class="table-wrap"><table class="table"><thead><tr><th>Checked (UK time)</th><th>Readiness</th><th>Actions</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def live_panel(state, url):
    """A box that shows a check while it runs and reloads the page when it finishes. Empty when nothing is running (and nothing has been checked yet, a first check is expected soon)."""
    st = (state or {}).get("state", "idle")
    if st not in ("queued", "running"):
        return ""
    msgs = "".join(f"<li>{esc(m)}</li>" for m in (state.get("messages") or [])[-6:])
    return (f'<section class="live" data-url="{esc(url)}" data-state="{st}"><div class="live-h"><span class="spinner"></span><b>{"Waiting for its turn" if st == "queued" else "Checking the hotel now"}</b> '
            f'<span class="hk-muted">This takes a few minutes. This page updates by itself.</span></div><ul class="live-m">{msgs}</ul></section>')


def opportunities_panel(ops):
    """The Overview's list of the few biggest AI discovery opportunities, each with the evidence in one line and the supporting actions."""
    if not ops:
        return ""
    import opportunities
    cards = "".join(
        f'<article class="prio"><div class="prio-n">{i}</div><div><h4>{esc(o["title"])}</h4><p class="prio-why">{esc(opportunities.sentence(o))}</p>'
        + (f'<div class="prio-do"><b>Supporting actions</b> {esc("; ".join(x["title"] for x in o["supporting"][:3]))}</div>' if o["supporting"] else "") + "</div></article>" for i, o in enumerate(ops, 1))
    return f'<div class="sec-head"><h3>Your biggest AI discovery opportunities</h3></div><div class="prios">{cards}</div>'


def dashboard(sm, actions, runs, editable=True, csrf="", ai="", live=None, live_url="", prompts="", prompts_alert=False, opps=None, strategy="", start="", analysis="", competitors="", talk="", settings_url="", research_html="", glance=None):
    """
    The hotel's dashboard. With settings_url (the hotel's own view) its prompts and history live on its Settings page and the dashboard links there; without it (the operator's view of the hotel)
    they stay as tabs, so the operator can edit the prompts in place.
    """
    h = sm["hotel"]
    nxt = ""
    if h.get("weekly") and sm["last_run_at"]:
        try:
            d = dt.datetime.fromisoformat(sm["last_run_at"].replace("Z", "+00:00")) + dt.timedelta(days=7)
            nxt = chip("Next automatic check: around " + uk_date(d.isoformat()), "brand") if d > dt.datetime.now(dt.timezone.utc) else chip("Next automatic check: at the next weekly run (Mondays)", "brand")
        except ValueError:
            nxt = ""
    latest = runs[0] if runs else None
    btns = ""
    if latest and latest.get("access_token"):
        t = latest["access_token"]
        btns = (f'<a class="btn primary" href="/r/{t}">Detailed analysis</a> <a class="btn" href="/r/{t}/management.pdf">Management report (PDF)</a>')
    hero = (f'<section class="hero"><div><h1>{esc(h["name"])}</h1><div class="sub">{esc(" · ".join(x for x in (h.get("city"), h.get("website")) if x))}</div>'
            f'<div class="hk-chips">{chip("Last checked " + uk_time(sm["last_run_at"]), "brand") if sm["last_run_at"] else ""}{nxt}</div></div><div>{btns}</div></section>')
    board = action_board(sm, actions, editable, strategy_context=strategy, research_html=research_html)
    caveat = ('<p class="caption">This shows progress: what has been done and how the score has moved. It does not prove that the actions caused the change. The AI figures come from a sample of answers from one assistant, '
              'which is why they are given with a range.</p>')
    try:
        top = glance(runs[1] if len(runs) > 1 else None) if callable(glance) else (glance or "")
    except Exception:  # noqa: BLE001
        top = ""
    overview = (f'{top}{progress_line(sm)}{kpis(sm)}{opportunities_panel(opps)}{caveat}'
                f'<div class="sec-head"><h3>Readiness score over time</h3></div><section class="panel">{trend_svg(sm["points"])}</section>'
                f'<div class="sec-head"><h3>Actions completed over time</h3></div><section class="panel">{trend_svg(sm["completed_points"], maximum=max(4, sm["actions"]["total"] or 4), name="Actions completed")}</section>')
    recs = (('<p class="lede">Mark each action as you go. After every weekly check the list updates: fixed items are ticked off, and new ones are added.</p>' if editable else "") + f'<div id="act-list">{board}</div>')
    history = f'<p class="caption">Every check of this hotel, newest first.</p>{history_table(runs)}'
    open_n = sm["actions"]["todo"] + sm["actions"]["working"] + sm["actions"]["still_flagged"]
    go_prompts = (f'<a class="btn primary" href="{esc(settings_url)}#prompts">Review the prompts &rarr;</a>' if settings_url else '<button type="button" class="btn primary" data-goto="prompts">Review the prompts &rarr;</button>')
    if prompts_alert:
        overview = ('<section class="talk-callout"><div><h3>Confirm the prompts we ask AI about your hotel</h3><p>We have chosen a recommended set from your website and the places around you. Review it and confirm it, '
                    f'so every check asks the same prompts and your progress can be tracked.</p></div>{go_prompts}</section>') + overview
    if settings_url and start:
        start = re.sub(r'<button type="button" class="btn primary" data-goto="prompts">(.*?)</button>', lambda m_: f'<a class="btn primary" href="{esc(settings_url)}#prompts">{m_.group(1)}</a>', start)
    later = '<div class="alert info">This appears after the first check.</div>'
    tabs = [("overview", "Overview", overview), ("ai", "AI visibility", ai or later), ("actions", f"Actions ({open_n})", recs), ("competitors", "Competitors", competitors or later),
            ("analysis", "Prompt analysis", analysis or later), ("talk", "Join the conversation", talk or later)]
    if not settings_url:                                                   # a dashboard with nowhere else to put them keeps the prompts and history as tabs
        tabs += [("prompts", "Prompts", prompts or '<div class="alert info">Prompts appear after the first check.</div>'), ("history", "History", history)]
    if start:
        tabs.insert(0, ("start", "Start here", start))
    nav = "".join(f'<button type="button" class="tab{" active" if i == 0 else ""}" data-tab="tab-{k}" data-name="{k}">{esc(lbl)}</button>' for i, (k, lbl, _b) in enumerate(tabs))
    body = "".join(f'<div class="tab-panel{" active" if i == 0 else ""}" id="tab-{k}">{b}</div>' for i, (k, _l, b) in enumerate(tabs))
    return f'<div class="pt" data-csrf="{esc(csrf)}">{hero}{live_panel(live, live_url)}<div class="tabs top"><div class="tab-bar" role="tablist">{nav}</div>{body}</div></div>'
