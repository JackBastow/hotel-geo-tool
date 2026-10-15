"""
PDF sections for the consultant report. Imported lazily by report_pdf.build_story
(it uses report_pdf's table and text helpers, so it must load after them).
"""

from reportlab.platypus import KeepTogether, PageBreak, Preformatted, Spacer

import report_pdf as R
from ai_insights import sentiment_label
from report_pdf import Markup, cat, esc, link, para, table

PRI_COL = {"critical": R.BAD, "high": "#c2570c", "medium": R.WARN, "low": R.GREY}
BUCKET = {"access": ("Machine access", "Can AI and search crawlers reach the information?"),
          "understanding": ("Machine understanding", "Can the hotel, its facts and amenities be understood?"),
          "content": ("Content gaps", "Is important traveller information missing?"),
          "authority": ("Authority and outside evidence", "Where might external validation be lacking?")}
LEVEL_LABEL = {"strong": "Strongly supported", "some": "Some evidence", "weak": "Weak / unclear", "none": "No evidence found"}
STATE_LABEL = {"missing": "missing", "unclear": "unclear", "partial": "partly answered"}
SD_LABEL = {"present": "Present", "could_improve": "Could be improved", "missing": "Missing", "incorrect": "Incorrect"}
SD_COL = {"present": R.GOOD, "could_improve": R.WARN, "missing": R.BAD, "incorrect": "#c2570c"}


def _path(u):
    from urllib.parse import urlparse
    p = urlparse(u or "")
    if p.netloc.endswith(("pagespeed.web.dev", "commoncrawl.org")):     # outside tools: show the tool, not a meaningless path
        return p.netloc
    return p.path or "/"


def _ev(evs, n=3):
    parts = []
    for e in (evs or [])[:n]:
        q = (e.get("snippet") or "")[:220]
        lead = link(e["url"], _path(e["url"])) if e.get("url") else Markup("")
        parts.append(cat(lead, ": " if lead and q else "", f"“{q}”" if q else ""))
    if not parts:
        return Markup("")
    out = parts[0]
    for p in parts[1:]:
        out = cat(out, Markup("<br/>"), p)
    return out


def _bullets(items):
    out = Markup("")
    for i, t in enumerate(items):
        out = cat(out, Markup("<br/>") if i else "", "- ", t)
    return out


def rec_block(r, compact=False):
    """
    One recommendation. Full form: Finding / Why / Evidence / Action / Where / Add / Example.
    Compact form (used in the appendix register) leaves out what the detailed sections already say
    and keeps what is unique to the recommendation: where, what to add, and the worked example.
    """
    head = cat(Markup(f"<b>{esc(r['ref'])} - {esc(r['title'])}</b>"))
    meta = cat(R.coloured(r["priority"].upper() + " priority", PRI_COL[r["priority"]]), f" - effort {r['effort']} - team: {r['team']}")
    rows = [[head, meta]]
    if not compact:
        rows += [["What we found", r["finding"]], ["Why it matters", r["why"]]]
        if r["evidence"]:
            rows.append(["Evidence", _ev(r["evidence"])])
    rows.append(["What to do", r["action"]])
    p = r.get("page")
    if p and (p.get("url") or p.get("label")):
        rows.append(["Where", link(p["url"], p["label"]) if p.get("url") else p["label"]])
    if r.get("additions"):
        rows.append(["Add", _bullets(r["additions"][:10])])
    rows.append(["Confidence", r["confidence"]])
    if not compact:
        rows.append(["Technical detail", r["technical"] or "-"])
    block = [table(rows, [0.2, 0.8], header=False, zebra=False)]
    if r.get("example"):
        lines = R._wrap_code(R.clean(r["example"])).splitlines()[:28]
        block += [Spacer(1, 2), Preformatted("\n".join(lines), R.S["code"])]
    block.append(Spacer(1, 6))
    return block


def summary_parts(c, recs):
    """Executive-summary additions: understanding, readiness, top actions, quick wins, what works."""
    u = c["understanding"]
    out = []
    cov = c.get("coverage") or {}
    if cov.get("limited"):
        why = "; ".join(f"{n} x {r}" for r, n in (cov.get("failure_reasons") or {}).items())
        out.append(para(f"Read {cov['pages_read']} of {cov['pages_attempted']} pages. {cov['note']}" + (f" Why pages failed: {why}." if why else ""), "note"))
    out += [para("How AI currently understands this hotel", "h2")]
    if u["summary"]:
        out.append(para(u["summary"], "note"))
    out.append(para(f"Based on {u['pages_read']} page(s) of the hotel's own website. {u['note']}", "tiny"))
    out.append(para("AI visibility readiness", "h2"))
    rows = [["Measure", "Score", "What drove it"]]
    for p in c["profile"]:
        s = f"{p['score']} / 100 ({p['band']})" if p["assessed"] else "not assessed"
        rows.append([p["label"], s, "; ".join(p["drivers"][:3])])
    out.append(table(rows, [0.22, 0.17, 0.61]))
    out.append(para("Eight separate measures, deliberately not blended into one score: they need different people and different fixes.", "tiny"))
    out.append(para(f"The {len(c['top_actions'])} things most worth doing", "h2"))
    rows = [["#", "Action", "Where", "Priority", "Effort"]]
    for i, rid in enumerate(c["top_actions"], 1):
        r = recs[rid]
        pg = r.get("page") or {}
        rows.append([str(i), Markup(f"<b>{esc(r['title'])}</b><br/>{esc(r['action'])}"),
                     link(pg["url"], pg["label"]) if pg.get("url") else (pg.get("label") or ""),
                     r["priority"], r["effort"]])
    out.append(table(rows, [0.04, 0.58, 0.18, 0.1, 0.1]))
    out.append(para("Ranked by likely impact against effort and spread across the four kinds of problem. Each comes from something found on this "
                    "hotel's own pages; none is a guarantee about what any AI assistant will do.", "tiny"))
    if c["quick_wins"]:
        out.append(para("Quick wins", "h2"))
        rows = [["Quick win", "Where", "What to do"]]
        for rid in c["quick_wins"]:
            r = recs[rid]
            pg = r.get("page") or {}
            rows.append([r["title"], pg.get("label", ""), r["action"][:170]])
        out.append(table(rows, [0.35, 0.2, 0.45]))
    if c["working"]:
        out.append(para("What we could establish without reading the website" if c.get("working_is_outside") else "What the hotel is already doing well", "h2"))
        out += R.bullets([w["point"] for w in c["working"]])
    return out


def web_section(web):
    """Evidence behind the crawler-access and speed findings: the four free checks, each stating plainly if it was not measured."""
    if not web:
        return []
    out = [para("Crawler access and speed: the evidence", "h2"),
           para("Four free checks of how automated visitors and phones meet the website. None shows what any AI assistant says about the hotel.", "tiny")]
    pol = web.get("ai_policy") or {}
    rows = [["Check", "Result", "Limits"]]
    groups = "; ".join(f"{k}: " + (", ".join(g["blocked"]) if g["blocked"] else "not singled out") for k, g in (pol.get("groups") or {}).items())
    rows.append(["AI crawlers in robots.txt", cat(pol.get("summary", ""), Markup("<br/>"), groups), pol.get("caveat", "")])
    cc = web.get("commoncrawl") or {}
    if cc.get("status") == "ok":
        parts = []
        for i in cc["items"]:
            parts += [f"{i['crawl']}: {i['captures']}{'+' if i['capped'] else ''} capture(s); {i['counts']['ok']} readable, {i['counts']['refused']} refused, "
                      f"{i['counts']['redirect']} redirect(s), {i['counts']['error']} error(s)"
                      + (f"; robots.txt answered HTTP {i['robots_status']}" if i.get("robots_status") else ""), Markup("<br/>")]
        res = cat(*parts[:-1])
    else:
        res = cc.get("reason", "Not assessed.")
    rows.append(["Common Crawl", res, "Presence in the archive is not evidence that any AI model knows or recommends the hotel."])
    ll = web.get("llms_txt") or {}
    rows.append(["llms.txt", "Published" if ll.get("present") else ll.get("reason", "Not assessed."), ll.get("note", "")])
    ps = web.get("pagespeed") or {}
    if ps.get("status") == "ok":
        sc = ps["scores"]
        res = ", ".join(f"{lab} {sc[k]}/100" for k, lab in (("performance", "performance"), ("accessibility", "accessibility"), ("seo", "SEO"),
                                                             ("best-practices", "best practice")) if sc.get(k) is not None)
        if ps.get("metrics"):
            res += "; " + "; ".join(f"{m['label'].lower()} {m['value']}" for m in ps["metrics"][:3])
        if ps.get("weak"):
            res += ". Flagged: " + "; ".join(w["title"] for w in ps["weak"][:4])
    else:
        res = ps.get("reason", "Not assessed.")
    rows.append(["PageSpeed Insights (mobile, homepage)", res, "One page, one lab test; scores vary run to run."])
    out.append(table(rows, [0.2, 0.5, 0.3]))
    return out


def listing_section(lc):
    """What the travel sites show against the hotel's own site, and listings still carrying a former name."""
    if not lc:
        return []
    out = [para("What the travel sites show, against the hotel's own site", "h2"),
           para("Read from short passages quoted in public search results, not from the platforms' pages. A difference is worth checking: the listing may be right and the hotel's "
                "own site out of date, or the other way round. A fact a listing does not show is not shown here.", "tiny")]
    if lc["rows"]:
        rows = [["Platform", "Fact", "The listing shows", "The site says", "Result"]]
        for r in sorted(lc["rows"], key=lambda r: (r["status"] != "differs", r["platform"])):
            rows.append([r["platform"], r["fact"], r["listing_says"], r["site_says"], r["status"]])
        out.append(table(rows, [0.2, 0.22, 0.2, 0.2, 0.18]))
    else:
        out.append(para("The quoted passages did not show a fact the hotel's own site also states, so nothing could be compared.", "tiny"))
    for h in lc.get("former_name") or []:
        out.append(para(f"{h['platform']} still shows a former name, '{h['name']}' (page title: {h['title'] or 'not shown'}).", "tiny"))
    return out


def pack_section(p):
    """The analysis of the hotel's own review export: aggregates only (the file's review text is never in the report)."""
    if not p or not p.get("reviews"):
        return []
    out = [para("Reviews and replies from the hotel's own export", "h2"),
           para(f"Every figure is for the {p['reviews']} review(s) in the file the hotel supplied ({p.get('first_date') or 'dates not found'} to {p.get('last_date') or ''}), not for every review "
                "the hotel has on every platform. How the replies were written is a rule-based reading. No review text or reviewer name is kept in this report.", "tiny")]
    rt = p.get("response_time") or {}
    bits = [f"average rating {p['avg_rating']} out of 5" if p.get("avg_rating") is not None else None,
            f"reply rate {p['reply_rate']}% ({p['replied']} replies)" if p.get("reply_rate") is not None else "the file has no replies column",
            f"{p['critical_unanswered']} of {p['critical']} critical reviews without a reply" if p.get("critical_unanswered") is not None else None,
            f"median time to reply {rt['median_days']:g} days, {rt['within_3_days_pct']}% within 3 days" if rt.get("median_days") is not None else None]
    out.append(para("; ".join(b for b in bits if b) + ".", "tiny"))
    if p.get("platforms"):
        rows = [["Platform", "Reviews", "Replied", "Reply rate"]]
        for k, v in p["platforms"].items():
            rows.append([k, v["reviews"], v["replied"], "-" if v["rate"] is None else f"{v['rate']}%"])
        out.append(table(rows, [0.4, 0.2, 0.2, 0.2]))
    q = p.get("reply_quality") or {}
    lab = {"personal": "specific to the guest", "acknowledges": "thanks or apologises", "offers_action": "says what will be done", "signed": "signed by a role or team"}
    qb = [f"{lab[k]}: {v['yes']} of {v['judged']}" for k, v in q.items() if v["judged"]]
    t = p.get("templates") or {}
    if t.get("pct") is not None and t.get("replies_compared"):
        qb.append(f"in repeated templates: {t['in_repeated_templates']} of {t['replies_compared']} ({t['pct']}%)")
    if qb:
        out.append(para("How the replies were written (a rule-based reading): " + "; ".join(qb) + ".", "tiny"))
    out.append(para("Guests praise: " + (", ".join(f"{r['topic']} ({r['reviews']})" for r in p.get("praised", [])) or "-") + ". Guests criticise: "
                    + (", ".join(f"{r['topic']} ({r['reviews']})" for r in p.get("criticised", [])) or "-") + ".", "tiny"))
    return out


def review_section(rs):
    """Reviews and replies as seen in public search results: a sample with its limits, never scored."""
    if not rs:
        return []
    out = [para("Reviews and replies: an indicative snapshot", "h2")]
    if rs.get("status") != "ok":
        out.append(para(rs.get("reason", "Not run."), "tiny"))
        return out
    s = rs["summary"]
    out.append(para("One AI model with web search read the review pages that appear in public search results; anything it could not confirm against those "
                    "results was dropped. This is a small, unrepresentative sample: it shows replies SEEN on reviews EXAMINED, not the hotel's reply rate. "
                    f"{s['examined']} reviews examined; the hotel replied to {s['replied']}; critical reviews with a reply: {s['negative_replied']} of "
                    f"{s['negative_examined']}. Reviews are paraphrased, nobody is named, and it is not part of any score.", "tiny"))
    rq = s.get("reply_quality") or {}
    lab = {"personal": "specific to the guest", "acknowledges": "thanks or apologises", "offers_action": "says what will be done", "signed": "signed by a role or team"}
    bits = [f"{lab[k]}: {v['yes']} of {v['judged']}" for k, v in rq.items() if v["judged"]]
    if bits:
        out.append(para("How the replies were written (an AI's reading of a small sample): " + "; ".join(bits) + ".", "tiny"))
    if s.get("praised") or s.get("criticised"):
        out.append(para("Positive reviews were about: " + (", ".join(f"{t['topic']} ({t['reviews']})" for t in s.get("praised", [])) or "-")
                        + ". Critical or mixed reviews were about: " + (", ".join(f"{t['topic']} ({t['reviews']})" for t in s.get("criticised", [])) or "-") + ".", "tiny"))
    rows = [["Platform", "Date", "Review", "Replied", "By", "Tone", "What the reply said (paraphrase)"]]
    for i in rs["items"]:
        rows.append([i["platform"], i["review_date"] or "-", i["sentiment"] or "-", {True: "yes", False: "no", None: "can't tell"}[i["owner_replied"]],
                     i["reply_by"] or "-", i["reply_tone"] or "-", i["reply_summary"] or "-"])
    out.append(table(rows, [0.11, 0.09, 0.09, 0.09, 0.12, 0.14, 0.36]))
    if rs.get("not_found"):
        out.append(para("Not found: " + "; ".join(rs["not_found"][:5]), "tiny"))
    return out


def ai_section(ai, ins=None):
    """The sampled assistant answers and what they mean, with their limits. Never scored."""
    if not ai:
        return []
    out = [para("What an AI assistant said: a sample", "h2")]
    if ai.get("status") != "ok":
        out.append(para(ai.get("reason", "Not run."), "tiny"))
        return out
    s = ai["summary"]
    reps = s.get("repeats", 1)
    asked_txt = f"{s['asked']} ordinary questions" if reps <= 1 else f"{s.get('questions', s['asked'])} different questions ({s['asked']} answers; the town-wide and niche ones were asked {reps} times each)"
    out.append(para(f"One model ({ai.get('model', '')}) with live web search was asked {asked_txt} on {ai.get('run_at', '')}. "
                    "It is a sample: answers change between runs and between assistants, it is not a ranking, and it is not part of any score. "
                    f"Named in {s['generic_named']} of {s['generic_asked']} town-wide 'where to stay' answers"
                    + (f" and {s['niche_named']} of {s['niche_asked']} answers about the markets it is positioned for; " if s.get("niche_asked") else "; ") +
                    f"{'known' if s['direct_known'] else 'not known' if s['direct_known'] is False else 'not assessed'} when asked directly; "
                    f"own website {'cited' if s['own_site_cited'] else 'not cited'}.", "tiny"))
    mk = ai.get("market")
    if mk:
        out.append(para("How the hotel's market was read, which decided the questions: " + mk["summary"] + ". "
                        + "; ".join(([f"price level {mk['tier']['label']} ({mk['tier']['why']})"] if mk.get("tier") else [])
                                    + [f"{a['label']} ({a['why']})" for a in mk.get("audiences", [])[:8]]) + ". Brand level is an inference.", "tiny"))
    osr = (ins or {}).get("own_site")
    if osr and osr["answers"]:
        out.append(para(f"The hotel's own website was among the sources in {osr['own_cited']} of {osr['answers']} answers to the town and market questions"
                        + (", with pages from other sites cited instead: " + ", ".join(f"{x['domain']} ({x['cited']})" for x in osr["instead"][:4]) if osr["instead"] else "")
                        + ". If an answer is not on the hotel's site in plain language, the assistant finds it elsewhere and cites elsewhere.", "tiny"))
    br = (ins or {}).get("brand_ranking")
    if br and br.get("rows"):
        sb0 = ins.get("scoreboard") or {}
        out.append(para("Brand ranking: the hotel and the hotels the assistant named most. Coverage is the share of answers that named the hotel; sentiment is the net of "
                        "positive minus negative mentions (-100 to +100), an AI's reading. It describes this one sample, not the market."
                        + (f" The hotel's coverage was {sb0['coverage_pct']}%" + (f" with a net sentiment of {sb0['sentiment']:+d}." if sb0.get("sentiment") is not None else ".")
                           if sb0.get("coverage_pct") is not None else ""), "tiny"))
        rows = [["Place", "Hotel", "Coverage", "Avg position", "Sentiment", "Pos / neutral / neg"]]
        for r in br["rows"]:
            rows.append([r["place"], ("YOU: " if r["is_target"] else "") + r["name"], f"{r['coverage_pct']}%", "-" if r["avg_rank"] is None else r["avg_rank"],
                         "-" if r["sentiment"] is None else f"{r['sentiment']:+d} ({sentiment_label(r['sentiment'])})", f"{r['positive']} / {r['neutral']} / {r['negative']}"])
        out.append(table(rows, [0.08, 0.34, 0.12, 0.12, 0.2, 0.14]))
    if ins and ins.get("status") in ("ok", "partial") and ins.get("leaderboard"):
        lb, sb = ins["leaderboard"], ins["scoreboard"]
        out.append(para(f"Who the assistant recommended instead. The hotel's share of the hotel names given was {sb['share']}% (place {sb['rank_in_table']} of "
                        f"{sb['table_size']} in the table). Counts are arithmetic on this one sample.", "tiny"))
        rows = [["Hotel", "Named in", "Avg position", "Why the assistant gave it"]]
        for r in lb["rows"][:8]:
            rows.append([("YOU: " if r["is_target"] else "") + r["name"], f"{r['mentions']} of {r['of']}", "-" if r["avg_rank"] is None else r["avg_rank"],
                         "; ".join(r["reasons"]) or "-"])
        out.append(table(rows, [0.3, 0.12, 0.13, 0.45]))
        if ins.get("alternatives"):
            out.append(para("Its view of the competitive set (asked which hotels are similar): " + ", ".join(h["name"] for h in ins["alternatives"]) + ".", "tiny"))
    nn = (ins or {}).get("niche")
    if nn:
        out.append(para("Where the hotel actually competes. A hotel is chosen in its own market, so these narrower questions were written from facts the audit holds about "
                        "the hotel; none names it.", "tiny"))
        rows = [["Market", "Question asked", "Why we asked", "Hotel", "Hotels it named"]]
        for m in nn["questions"]:
            rows.append([m.get("angle") or "-", m["question"], m.get("why") or "-", (f"named in {m['named']} of {m['of']}" if m.get("of", 1) > 1 else "named" if m["hotel_named"] else "not named"),
                         ", ".join(m["hotels_named"][:4]) or "-"])
        out.append(table(rows, [0.12, 0.3, 0.24, 0.1, 0.24]))
    if ins and ins.get("sources"):
        rows = [["Site the assistant used", "Type", "Used in", "Hotel there?"]]
        for x in ins["sources"][:8]:
            rows.append([x["domain"], x["kind"], f"{x['answers']} answers", {True: "found", False: "not found", None: "not checked"}[x["hotel_evidenced"]]])
        out.append(table(rows, [0.34, 0.3, 0.16, 0.2]))
    if ins and ins.get("pages"):
        out.append(para("The exact pages the assistant used, most cited first. Whether a page names the hotel or a competitor is judged only from its title and the short passage "
                        "the assistant quoted (we do not read these pages), so 'not seen' is not a statement that the page leaves it out.", "tiny"))
        rows = [["Page", "Cited", "Names the hotel", "Names a competitor"]]
        for x in ins["pages"][:10]:
            rows.append([(x["title"] or x["domain"]) + " (" + x["domain"] + ")", x["cited"], "yes" if x["names_hotel"] else "not seen", x["names_competitor"] or "not seen"])
        out.append(table(rows, [0.5, 0.1, 0.16, 0.24]))
    exp = (ins or {}).get("explanation")
    if exp and exp.get("hypotheses"):
        out.append(para("Why the hotel may not be named: hypotheses. The assistant cannot show its reasoning and neither can we; these are differences visible in the "
                        "audit's evidence, offered to be checked, not causes.", "tiny"))
        out += R.bullets([h["text"] + f" (evidence {', '.join(h['evidence'])})" + (f" Worth checking: {h['action']}" if h.get("action") else "") for h in exp["hypotheses"]])
    ab = (ins or {}).get("about")
    if ab and (ab.get("strengths") or ab.get("weaknesses")):
        out.append(para("What the assistant says about the hotel. Positives: " + ("; ".join(ab["strengths"][:6]) or "none") + ". Drawbacks: "
                        + ("; ".join(ab["weaknesses"][:6]) or "none") + f". Tone: {ab.get('tone', 'unclear')} (an AI's reading).", "tiny"))
    acc = (ins or {}).get("accuracy")
    if acc and acc["rows"]:
        rows = [["Detail", "The assistant said", "Our record", "Result"]]
        for r in acc["rows"]:
            rows.append([r["claim"], r["assistant_says"], f"{r['our_record']} ({r['source']})" if r["source"] else r["our_record"], r["status"]])
        out.append(table(rows, [0.16, 0.26, 0.42, 0.16]))
    rows = [["Question asked", "Hotel", "What it answered", "Sources it used"]]
    for i in ai["items"]:
        rows.append([i["text"] + (f" (answer {i['repeat']} of {i['repeats']})" if i.get("repeats", 1) > 1 else ""),
                     {True: "named", False: "not named", None: "no answer"}[i["mentioned"]] + (f" (#{i['position']})" if i.get("position") else ""),
                     (i["answer"] or "(no answer text)")[:420], ", ".join(i["domains"][:6])])
    out.append(table(rows, [0.22, 0.1, 0.46, 0.22]))
    h2h = (ins or {}).get("head_to_head")
    if h2h:
        out.append(para(f"Head to head with {h2h['rival']}: " + h2h["answer"][:700], "tiny"))
    return out


def sections(c, H1, web=None, ai=None, reviews=None, ins=None, listings=None, pack=None):
    """The dedicated consultant sections, in reading order."""
    recs = {r["id"]: r for r in c["recommendations"]}
    out = []
    u = c["understanding"]

    # ---- how AI understands the hotel
    out += [PageBreak(), H1("How AI understands this hotel"),
            para("What automated systems could learn from the hotel's own pages, and which traveller searches that content supports. Built only from wording "
                 "found on the pages read.", "muted")]
    out.append(para("Strong signals", "h3"))
    out += R.bullets(u["strong_signals"] or ["(none stood out)"])
    out.append(para("Weak or unclear signals", "h3"))
    out += R.bullets([f"{w['label']} - {w['why']}" for w in u["weak_signals"]] or ["(none)"])
    out.append(para("Traveller searches this content supports", "h2"))
    shown = [r for r in c["intents"] if r["level"] != "none"]
    order = {"strong": 0, "some": 1, "weak": 2}
    rows = [["Traveller type", "Evidence", "Why it was classed this way"]]
    for r in sorted(shown, key=lambda r: order[r["level"]]):
        rows.append([r["label"], LEVEL_LABEL[r["level"]], r["reason"]])
    out.append(table(rows, [0.2, 0.15, 0.65]))
    none = [r["label"] for r in c["intents"] if r["level"] == "none"]
    if none:
        out.append(para("No evidence found (may simply not apply to this hotel): " + ", ".join(none) + ".", "tiny"))

    # ---- questions
    out += [PageBreak(), H1("Questions AI may struggle to answer"),
            para("Traveller questions the pages leave unclear or unanswered - only those that apply to this hotel - with the page where each answer belongs.", "muted")]
    if not c["questions"]:
        out.append(para("Not assessed: the website could not be read, so nothing can be said about this either way." if (c.get("coverage") or {}).get("unreadable")
                        else "Nothing important is unclear: the common traveller questions are answered on the pages read.", "base"))
    for q in c["questions"]:
        rows = [[Markup(f"<b>{esc(q['question'])}</b>"), STATE_LABEL[q["state"]]]]
        if q["found"]:
            rows.append(["Already covered", ", ".join(q["found"])])
        if q["missing"]:
            rows.append(["Not clearly stated", ", ".join(q["missing"])])
        if q["evidence"]:
            rows.append(["What the pages say now", _ev(q["evidence"], 2)])
        w = q["where"]
        rows.append(["Where to add it", cat(link(w["url"], w["label"]) if w.get("url") else w["label"], f" - {w['reason']}")])
        out.append(KeepTogether([table(rows, [0.2, 0.8], header=False, zebra=False), Spacer(1, 5)]))

    # ---- location
    out += [H1("How the website relates the hotel to its location")]
    loc = c["location"]
    if loc["items"]:
        lab = {"stated": "described with a distance/time", "mentioned_no_distance": "mentioned, no distance", "not_mentioned": "not mentioned"}
        rows = [["Place", "Type", "On the website", "What to do"]]
        for i in loc["items"]:
            rows.append([i["place"] or i["label"], i["label"], lab[i["state"]], i["suggestion"]])
        out.append(table(rows, [0.2, 0.17, 0.18, 0.45]))
    else:
        out.append(para("The pages read don't tie the hotel to any named transport link, airport or landmark, and no nearby places could be mapped.", "base"))
    out.append(para(loc["note"], "tiny"))

    # ---- consistency and hidden strengths
    out += [H1("Consistency and strengths that are easy to miss")]
    out.append(para("Consistency across the hotel's own pages", "h2"))
    if c["consistency"]:
        for k in c["consistency"]:
            rows = [[Markup(f"<b>{esc(k['title'])}</b>"), k["severity"]]]
            rows.append(["Values found", _bullets([cat(v["value"][:140], " (", link(v["url"], _path(v["url"])), ")") if v.get("url") else v["value"][:140]
                                                   for v in k["values"][:4]])])
            rows.append(["Why it matters", k["detail"]])
            rows.append(["Fix", k["fix"]])
            out.append(KeepTogether([table(rows, [0.2, 0.8], header=False, zebra=False), Spacer(1, 5)]))
    else:
        out.append(para("No contradictions found between the pages read (check-in times, phone numbers, address, hotel name, hours, offers).", "base"))
    out.append(para("Strengths that are hard to find", "h2"))
    if c["hidden"]:
        rows = [["Finding", "Suggestion", "Evidence"]]
        for h in c["hidden"]:
            rows.append([h["finding"], h["suggestion"], _ev(h["evidence"], 1)])
        out.append(table(rows, [0.4, 0.35, 0.25]))
    else:
        out.append(para("No real strength was found hidden in a PDF, an image, a single mention or a buried page.", "base"))

    # ---- machine readiness and structured data
    out += [PageBreak(), H1("Machine readiness and structured data"),
            para("Four separate groups, because they need different people and different fixes. The crawl reads raw HTML and does not run JavaScript.", "muted")]
    for key, (title, q) in BUCKET.items():
        rows_ = [f for f in c["machine"] if f["bucket"] == key]
        out.append(para(f"{title}: {q}", "h2"))
        if not rows_:
            out.append(para("Nothing to report.", "tiny"))
            continue
        rows = [["Finding", "Status", "Why it matters / what to do"]]
        for f in sorted(rows_, key=lambda f: {"issue": 0, "info": 1, "ok": 2}[f["status"]]):
            st = {"issue": f"issue ({f['severity']})", "info": "note", "ok": "OK"}[f["status"]]
            col = {"issue": PRI_COL.get(f["severity"], R.WARN), "info": R.GREY, "ok": R.GOOD}[f["status"]]
            body = cat(f["detail"], Markup("<br/>") if f["consequence"] else "", f["consequence"],
                       Markup("<br/><b>What to do:</b> ") if f["fix"] else "", f["fix"])
            rows.append([f["title"], R.coloured(st, col), body])
        out.append(table(rows, [0.28, 0.12, 0.6]))
    out += web_section(web)
    out += ai_section(ai, ins)
    out += pack_section(pack)
    out += review_section(reviews)
    out += listing_section(listings)
    sd = c["structured"]
    out.append(para("Structured data: what it says, not just whether it exists", "h2"))
    rows = [["Item", "Status", "Detail", "Advice"]]
    for i in sd["items"]:
        rows.append([i["item"] + (" (optional)" if i["optional"] else ""), R.coloured(SD_LABEL[i["status"]], SD_COL[i["status"]]), i["detail"], i["advice"]])
    out.append(table(rows, [0.2, 0.13, 0.37, 0.3]))
    out.append(para(sd["caution"], "note"))

    # ---- recommendation register: every recommendation once; worked examples only where they exist
    out += [PageBreak(), H1("Recommendation register"),
            para("Every recommendation, once. The references match the management report. Each was generated from a specific finding described in "
                 "the sections above; this register adds only what is unique to it (where to make the change, what to add, worked examples). "
                 "Priority comes from one ranking model (business and reputation risk, traveller importance, effect on discoverability, "
                 "confidence, moderated by effort). None guarantees that any AI assistant will recommend the hotel.", "muted")]
    rows = [["Ref", "Type", "Recommendation", "Priority", "Effort", "Team", "Where"]]
    for r in c["recommendations"]:
        pg = r.get("page") or {}
        rows.append([r["ref"], "Fix" if r["kind"] == "fix" else "Opportunity", r["title"][:110], R.coloured(r["priority"], PRI_COL[r["priority"]]),
                     r["effort"], r["team"], link(pg["url"], pg["label"]) if pg.get("url") else (pg.get("label") or "-")])
    out.append(table(rows, [0.07, 0.1, 0.38, 0.09, 0.07, 0.12, 0.17]))
    withdetail = [r for r in c["recommendations"] if r.get("example") or r.get("additions")]
    if withdetail:
        out.append(para("Where to make each change, what to add, and worked examples", "h2"))
        for r in withdetail:
            out += rec_block(r, compact=True)
    return out
