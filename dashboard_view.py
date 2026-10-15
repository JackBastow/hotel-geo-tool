"""
The Overview and the Action plan: the parts of the report a hotel acts on, laid out as a dashboard.

Overview: the readiness score and what it rests on, the headline numbers (AI coverage, where the hotel stands among those the assistant names, guest questions answered, reviews), the three
things to do first, charts (score by area, guest questions, who AI names), what stands out, and the priority map.
Action plan: every recommendation as a card, numbered the way the priority map is, grouped as start here / fix next / opportunities, filterable by team, with the 30/60/90-day plan.

Everything is built from the finished report (and, when there is one, the hotel's previous audit for 'since last time'). Nothing is invented here: each number and sentence comes from a field
the audit already produced, and a figure that was not measured shows as such.
"""

import htmlst
import ui_consult
from charts import BAD, BRAND, GOOD, GREY, WARN, bars, delta, donut, esc, matrix, radar, ring, stacked, tone

htmlst.install()

TEAM_LABEL = {"web": "Website", "reputation management": "Reputation", "distribution": "Distribution", "marketing": "Marketing", "operations": "Operations", "PR": "PR"}
PRI_TONE = {"critical": "bad", "high": "bad", "medium": "warn", "low": ""}
GOTO = {"overview": "Overview", "action": "Action plan", "ai": "AI visibility", "site": "Your website", "reputation": "Reputation & listings", "score": "Scorecard"}


def chip(text, kind=""):
    return f'<span class="hk-chip {kind}">{esc(text)}</span>'


def short(text, n):
    return ui_consult._short(text, n)


def _guest_counts(rep):
    qs = (rep.get("guest_questions") or {}).get("questions") or []
    n = {"answered": 0, "partial": 0, "needs_checking": 0, "not_found": 0, "couldnt_check": 0}
    for q in qs:
        n[q["state"]] = n.get(q["state"], 0) + 1
    return n, qs


def _ai(rep):
    ins = rep.get("ai_insights") or {}
    return ins, (ins.get("scoreboard") or {}), (ins.get("brand_ranking") or {})


# ----------------------------------------------------------------------------- headline numbers

def kpis(rep, prev=None):
    prev = prev or {}
    h = rep.get("headline") or {}
    ins, sb, br = _ai(rep)
    cons = rep.get("consultant") or {}
    counts, qs = _guest_counts(rep)
    out = []

    if sb.get("coverage_pct") is not None:
        named = (sb.get("named") or 0) + (sb.get("niche_named") or 0)
        c = sb["coverage_pct"]
        out.append({"label": "Named by an AI assistant", "value": f"{c}", "unit": "%", "tone": GOOD if c >= 50 else WARN if c >= 20 else BAD,
                    "sub": f"{named} of {sb.get('asked_all', 0)} sampled answers, one model", "delta": delta(c, prev.get("ai_coverage_pct"), "pts"), "goto": "ai"})
        place = sb.get("place")
        n_br = len(br.get("rows") or [])
        sent = sb.get("sentiment")
        out.append({"label": "Place among hotels it names", "value": f"{place}" if place else "—", "unit": f"of {n_br}" if place else "",
                    "tone": GOOD if place == 1 else BRAND if place and place <= 3 else WARN, "sub": ("sentiment " + (f"{sent:+d}" if sent is not None else "not judged")),
                    "delta": delta(sent, prev.get("ai_sentiment")), "goto": "ai"})
    else:
        why = (rep.get("ai_sample") or {}).get("reason") or "The AI sample was not run for this audit."
        out.append({"label": "Named by an AI assistant", "value": "Not run", "unit": "", "tone": GREY, "sub": short(why, 90), "delta": "", "goto": "ai"})

    if qs:
        full = counts["answered"]
        out.append({"label": "Guest questions answered", "value": f"{full}", "unit": f"of {len(qs)}", "tone": GOOD if full >= len(qs) * .8 else WARN if full >= len(qs) * .5 else BAD,
                    "sub": f"{counts['partial'] + counts['needs_checking']} partly, {counts['not_found']} not found" + (f", {counts['couldnt_check']} couldn't check" if counts["couldnt_check"] else ""), "delta": "", "goto": "site"})

    pk, snap = rep.get("review_pack") or {}, rep.get("review_snapshot") or {}
    if pk.get("reply_rate") is not None:
        out.append({"label": "Reviews replied to", "value": f"{pk['reply_rate']}", "unit": "%", "tone": GOOD if pk["reply_rate"] >= 80 else WARN if pk["reply_rate"] >= 50 else BAD,
                    "sub": f"{pk['reviews']} reviews in your export · {pk.get('critical_unanswered', 0)} critical unanswered", "delta": delta(pk["reply_rate"], prev.get("pack_reply_rate"), "pts"), "goto": "reputation"})
    elif snap.get("status") == "ok" and (snap.get("summary") or {}).get("examined"):
        s = snap["summary"]
        out.append({"label": "Replies seen on reviews", "value": f"{s['replied']}", "unit": f"of {s['examined']}", "tone": GOOD if s["replied"] >= s["examined"] * .7 else WARN, "sub": "a small search sample, not a rate", "delta": "", "goto": "reputation"})
    else:
        out.append({"label": "Reviews and replies", "value": "Add your export", "unit": "", "tone": GREY, "sub": "Upload the hotel's review export for a full analysis", "delta": "", "goto": "reputation", "cta": True})
    return out


def _kpi_html(k):
    return (f'<button type="button" class="kpi{" cta" if k.get("cta") else ""}" data-goto="{esc(k["goto"])}" style="--kc:{k["tone"]}"><span class="kpi-label">{esc(k["label"])}</span>'
            f'<span class="kpi-value">{esc(k["value"])}<small>{esc(k["unit"])}</small></span><span class="kpi-sub">{esc(k["sub"])}</span>{k["delta"]}</button>')


# ----------------------------------------------------------------------------- what stands out

def insights(rep, limit=8):
    """The few things most worth noticing, each from a field the audit produced. -> [{tone: bad|warn|info|good, title, body, goto}]"""
    out = []
    ins, sb, br = _ai(rep)
    cons = rep.get("consultant") or {}
    counts, qs = _guest_counts(rep)
    if sb.get("coverage_pct") is not None:
        c = sb["coverage_pct"]
        top = next((r for r in (br.get("rows") or []) if not r["is_target"]), None)
        tail = f" The hotel it names most is {top['name']}, in {top['coverage_pct']}% of answers." if top else ""
        out.append({"tone": "bad" if c < 20 else "warn" if c < 50 else "good", "title": f"An AI assistant named the hotel in {c}% of its sampled answers",
                    "body": f"This is one model on one day, asked about the hotel's own markets as well as the town.{tail}", "goto": "ai"})
    osr = ins.get("own_site") or {}
    if osr.get("answers"):
        share = osr["own_cited"] / osr["answers"]
        inst = ", ".join(x["domain"] for x in osr.get("instead", [])[:3])
        out.append({"tone": "good" if share >= .5 else "warn", "title": f"Your own website was behind {osr['own_cited']} of {osr['answers']} AI answers",
                    "body": ("Other sites were cited instead: " + inst + ". If an answer is not on your site in plain language, the assistant finds it elsewhere." if inst else "Good: the assistant used your own pages."), "goto": "ai"})
    acc = [r for r in ((ins.get("accuracy") or {}).get("rows") or []) if r["status"] == "differs"]
    if acc:
        r = acc[0]
        out.append({"tone": "bad", "title": "An AI assistant stated something that differs from your own record", "body": f"{r['claim']}: it said {r['assistant_says']}; your record says {r['our_record']}.", "goto": "ai"})
    lc = rep.get("listing_checks") or {}
    diff = [r for r in lc.get("rows", []) if r["status"] == "differs"]
    if diff:
        r = diff[0]
        out.append({"tone": "warn", "title": f"{r['platform']} shows a different {r['fact'].lower()} from your site", "body": f"The listing says {r['listing_says']}; your site says {r['site_says']}. "
                    + (f"{len(diff) - 1} more difference(s). " if len(diff) > 1 else "") + "Find out which is right and correct the other.", "goto": "reputation"})
    for h in (lc.get("former_name") or [])[:1]:
        out.append({"tone": "bad", "title": f"{h['platform']} still shows a former name", "body": f"'{h['name']}' appears in the listing. After a rebrand the old name lingers in listings and AI answers.", "goto": "reputation"})
    pk = rep.get("review_pack") or {}
    if pk.get("critical_unanswered"):
        out.append({"tone": "bad", "title": f"{pk['critical_unanswered']} critical review(s) have no reply", "body": "Replying to critical reviews is the one place the hotel's own words sit inside third-party evidence.", "goto": "reputation"})
    gaps = [r for r in pk.get("praised", []) if r.get("site") in ("not_found", "partial", "needs_checking") and r["reviews"] >= 3]
    if gaps:
        out.append({"tone": "warn", "title": f"Guests praise {gaps[0]['topic']}, but the website does not state it clearly", "body": "What guests praise is what the next guest wants to know; say it in plain sentences on the site.", "goto": "site"})
    elif not pk and not (rep.get("review_snapshot") or {}).get("summary", {}).get("examined"):
        out.append({"tone": "info", "title": "Add the hotel's review export for a full reviews analysis", "body": "Reply rate, unanswered critical reviews, how replies are written and what guests praise or criticise, from every review in the file.", "goto": "reputation"})
    open_q = [q for q in qs if q["state"] in ("partial", "not_found", "needs_checking")]
    if open_q:
        names = ", ".join(q["short"] for q in open_q[:3])
        out.append({"tone": "bad" if counts["not_found"] >= 3 else "warn", "title": f"{len(open_q)} of {len(qs)} guest questions are only partly answered or missing", "body": f"Including {names}. Each is a fact an assistant may find elsewhere instead.", "goto": "site"})
    machine = [r for r in cons.get("recommendations", []) if r.get("source") == "machine" and r.get("priority") in ("critical", "high")]
    if machine:
        out.append({"tone": "bad", "title": machine[0]["title"], "body": short(machine[0]["finding"], 200), "goto": "site"})
    for w in (cons.get("working") or [])[:2]:
        out.append({"tone": "good", "title": "Already working: " + short(w["point"], 90), "body": "", "goto": "site"})
    order = {"bad": 0, "warn": 1, "info": 2, "good": 3}
    out.sort(key=lambda x: order[x["tone"]])
    return out[:limit]


def _insight_html(i):
    body = f"<p>{esc(i['body'])}</p>" if i["body"] else ""
    return f'<button type="button" class="insight {i["tone"]}" data-goto="{esc(i["goto"])}"><b>{esc(i["title"])}</b>{body}<span class="ins-go">{esc(GOTO[i["goto"]])} &rarr;</span></button>'


# ----------------------------------------------------------------------------- the Overview

def _ordered(cons):
    """Recommendations in display order: start here (the top actions), then other fixes, then opportunities. -> (list, set of top ids)"""
    recs = cons.get("recommendations") or []
    top = [r for r in recs if r["id"] in (cons.get("top_actions") or [])]
    top.sort(key=lambda r: (cons.get("top_actions") or []).index(r["id"]))
    fixes = [r for r in recs if r["kind"] == "fix" and r["id"] not in (cons.get("top_actions") or [])]
    opps = [r for r in recs if r["kind"] != "fix" and r["id"] not in (cons.get("top_actions") or [])]
    return top + fixes + opps, {r["id"] for r in top}


def overview(rep, prev=None):
    cons = rep.get("consultant") or {}
    h = rep.get("headline") or {}
    sc = rep.get("scorecard") or {}
    ins, sb, br = _ai(rep)
    counts, qs = _guest_counts(rep)
    parts = []

    # --- banner: the score and what it rests on
    unassessed = "".join(chip(f"{u['label']} · {u['weight']:g}%", "warn") for u in h.get("unassessed", []))
    parts.append(f'<section class="ov-hero">{ring(h.get("score"), "of 100", 132)}<div class="ov-hero-text"><div class="ov-title">AI discoverability readiness {chip((h.get("badge") or "").capitalize(), "brand")} {delta(h.get("score"), (prev or {}).get("headline_score"))}</div>'
                 f'<div class="p-track" style="margin:8px 0 4px"><div class="p-fill" style="width:{min(max(h.get("coverage_pct", 0), 0), 100):.0f}%"></div></div>'
                 f'<div class="caption">Measurement coverage: {h.get("coverage_pct", 0):.0f}% of the full model assessed</div><p class="ov-expl">{esc(h.get("explanation", ""))}</p>'
                 f'{"<div><span class=hk-label>Not measured</span> " + unassessed + "</div>" if unassessed else ""}</div></section>')

    # --- headline numbers
    parts.append('<div class="kpis">' + "".join(_kpi_html(k) for k in kpis(rep, prev)) + "</div>")

    # --- start here
    ordered, top_ids = _ordered(cons)
    num = {r["id"]: i + 1 for i, r in enumerate(ordered)}
    tops = [r for r in ordered if r["id"] in top_ids][:3]
    if tops:
        cards = "".join(f'<article class="prio {PRI_TONE.get(r["priority"], "")}"><div class="prio-n">{num[r["id"]]}</div><div><h4>{esc(r["title"])}</h4><p class="prio-why">{esc(short(r["why"], 170))}</p>'
                        f'<div class="prio-do"><b>What to do</b> {esc(short(r["action"], 210))}</div><div class="chips">{chip(r["priority"].capitalize() + " priority", PRI_TONE.get(r["priority"], ""))}{chip("Effort: " + r["effort"])}'
                        f'{chip(TEAM_LABEL.get(r["team"], r["team"]))}</div></div></article>' for r in tops)
        parts.append(f'<div class="sec-head"><h3>Start here: your top priorities</h3><button type="button" class="link" data-goto="action">All {len(ordered)} recommendations &rarr;</button></div><div class="prios">{cards}</div>')
    else:
        parts.append('<div class="alert success">Nothing in this audit met the bar for a required fix.</div>')

    # --- charts
    cat_rows = [{"label": c["label"], "value": c["score"] if c.get("assessed") else None} for c in sc.get("categories", [])]
    left = radar(cat_rows) + bars(cat_rows)
    qd = donut([{"label": "Answered", "value": counts["answered"], "colour": GOOD}, {"label": "Partly", "value": counts["partial"] + counts["needs_checking"], "colour": WARN},
                {"label": "Not found", "value": counts["not_found"], "colour": BAD}, {"label": "Couldn't check", "value": counts["couldnt_check"], "colour": GREY}],
               top=f"{counts['answered']}/{len(qs)}", bottom="answered") if qs else '<p class="caption">The guest questions were not checked.</p>'
    ai_rows = [{"label": r["name"], "value": r["coverage_pct"], "hot": r["is_target"], "note": None} for r in (br.get("rows") or [])]
    ai_panel = (bars(ai_rows, suffix="%") + '<p class="caption">Share of the sampled answers that named each hotel. One model on one day: a sample, not a ranking.</p>') if ai_rows else '<p class="caption">No AI answers were sampled for this audit.</p>'
    parts.append('<div class="ov-grid"><section class="panel"><h4>Score by area</h4>' + left + '</section><div class="ov-col"><section class="panel"><h4>Guest questions on your website</h4>' + qd
                 + '</section><section class="panel"><h4>Who the AI assistant names</h4>' + ai_panel + '</section></div></div>')

    # --- what stands out
    items = insights(rep)
    if items:
        parts.append('<div class="sec-head"><h3>What stands out</h3></div><div class="insights">' + "".join(_insight_html(i) for i in items) + "</div>")

    # --- priority map
    if ordered:
        mx = matrix([{"n": num[r["id"]], "title": r["title"], "impact": r.get("impact"), "effort": r.get("effort"), "kind": r["kind"]} for r in ordered])
        parts.append(f'<div class="sec-head"><h3>Priority map</h3><button type="button" class="link" data-goto="action">Open the action plan &rarr;</button></div><section class="panel">{mx}</section>')
    return "".join(parts)


# ----------------------------------------------------------------------------- the Action plan

def _rec_card(r, n, start):
    detail = htmlst.build(ui_consult.rec_card, r, True)
    team = TEAM_LABEL.get(r["team"], r["team"])
    return (f'<article class="rec {PRI_TONE.get(r["priority"], "")}" id="rec-{n}" data-team="{esc(r["team"])}" data-kind="{esc(r["kind"])}" data-start="{1 if start else 0}">'
            f'<div class="rec-n">{n}</div><div class="rec-main"><h4>{esc(r["title"])}</h4><p class="rec-why">{esc(short(r["why"], 230))}</p>'
            f'<div class="rec-do"><b>What to do</b> {esc(short(r["action"], 260))}</div>'
            f'<div class="chips">{chip(r["priority"].capitalize() + " priority", PRI_TONE.get(r["priority"], ""))}{chip("Effort: " + r["effort"])}{chip("Owner: " + team)}{chip("Confidence: " + r["confidence"].lower())}'
            f'{chip("Opportunity", "brand") if r["kind"] != "fix" else ""}{chip(r["ref"])}</div>'
            f'<details class="details"><summary>Evidence, example wording and full detail</summary><div class="details-body">{detail}</div></details></div></article>')


def action_plan(rep):
    cons = rep.get("consultant") or {}
    if not cons or "recommendations" not in cons:
        return '<div class="alert info">This section needs the consultant analysis, which did not run for this audit.</div>'
    ordered, top_ids = _ordered(cons)
    if not ordered:
        return '<div class="alert success">Nothing in this audit met the bar for a recommendation.</div>'
    n_fix = sum(1 for r in ordered if r["kind"] == "fix")
    teams = sorted({r["team"] for r in ordered})
    quick = [r for r in ordered if r["id"] in (cons.get("quick_wins") or [])]
    head = (f'<p class="lede">{len(ordered)} recommendations: <b>{n_fix} fixes</b> and <b>{len(ordered) - n_fix} opportunities</b>, ranked by risk, how much travellers care, how much it affects discoverability and how sure we are, '
            f'moderated by effort. Nothing here is a guarantee about what any AI assistant will recommend.</p>')
    mx = matrix([{"n": i + 1, "title": r["title"], "impact": r.get("impact"), "effort": r.get("effort"), "kind": r["kind"]} for i, r in enumerate(ordered)])
    qw = ("<ul class='qw'>" + "".join(f'<li><a href="#rec-{[x["id"] for x in ordered].index(r["id"]) + 1}">{esc(r.get("short_title") or r["title"])}</a> {chip(TEAM_LABEL.get(r["team"], r["team"]))}</li>' for r in quick[:8]) + "</ul>") if quick else '<p class="caption">No low-effort quick wins beyond the top priorities.</p>'
    top = (f'<div class="ov-grid even"><section class="panel"><h4>Priority map</h4>{mx}</section><section class="panel"><h4>Quick wins</h4>{qw}</section></div>')
    filters = ('<div class="filters-bar" role="group" aria-label="Filter the recommendations"><button type="button" class="fchip on" data-f="all">All</button><button type="button" class="fchip" data-f="start">Start here</button>'
               '<button type="button" class="fchip" data-f="kind:fix">Fixes</button><button type="button" class="fchip" data-f="kind:opportunity">Opportunities</button>'
               + "".join(f'<button type="button" class="fchip" data-f="team:{esc(t)}">{esc(TEAM_LABEL.get(t, t))}</button>' for t in teams) + "</div>")
    groups = []
    for title, sel in (("Start here", lambda r: r["id"] in top_ids), ("Fix next", lambda r: r["kind"] == "fix" and r["id"] not in top_ids), ("Opportunities, if the segment matters to you", lambda r: r["kind"] != "fix" and r["id"] not in top_ids)):
        items = [(i + 1, r) for i, r in enumerate(ordered) if sel(r)]
        if items:
            groups.append(f'<h3 class="grp">{esc(title)} <small>{len(items)}</small></h3>' + "".join(_rec_card(r, n, r["id"] in top_ids) for n, r in items))
    plan = cons.get("plan") or {}
    byid = {r["id"]: r for r in ordered}
    cols = []
    for key, name in (("30", "First 30 days"), ("60", "Days 31 to 60"), ("90", "Days 61 to 90")):
        li = "".join(f'<li><a href="#rec-{[x["id"] for x in ordered].index(rid) + 1}">{esc(byid[rid].get("short_title") or byid[rid]["title"])}</a> {chip(TEAM_LABEL.get(byid[rid]["team"], byid[rid]["team"]))}</li>' for rid in plan.get(key, []) if rid in byid)
        cols.append(f'<section class="plan-col"><h4>{name}</h4><ul>{li or "<li class=hk-muted>Nothing scheduled</li>"}</ul></section>')
    plan_html = ('<div class="sec-head"><h3>30 / 60 / 90-day plan</h3></div><p class="caption">30 days: serious and quick items. 60 days: medium-effort required fixes. 90 days: opportunities and larger work. Re-run the audit afterwards to check what changed.</p>'
                 f'<div class="plan-cols">{"".join(cols)}</div>')
    return head + top + filters + '<div id="rec-list">' + "".join(groups) + "</div>" + plan_html
