"""
The management report: short, decision-oriented, written for a hotel General Manager.

It says each thing once and points to the Technical & Evidence Appendix for the quotes, URLs and method. Seven sections:

  1 Executive summary                          5 Commercial opportunities
  2 Discoverability and technical readiness    6 Prioritised action plan
  3 Traveller recommendation readiness         7 Methodology and limitations
  4 External presence and reputation

Readiness (how well the hotel is set up) is kept apart from observed AI visibility (what assistants actually say) throughout.

Imported lazily by report_pdf.build_story (it uses report_pdf's helpers).
"""

from reportlab.platypus import KeepTogether, PageBreak, Spacer

import headline as headline_mod
import report_pdf as R
import scoring
from report_pdf import Markup, cat, esc, link, para, table

PRI_COL = {"critical": R.BAD, "high": "#c2570c", "medium": R.WARN, "low": R.GREY}
LEVEL_COL = {"high": R.GOOD, "medium": R.WARN, "low": R.BAD}
STATUS_COL = {"assessed": R.GOOD, "provisional": R.WARN, "withheld": R.BAD}
STATE_COL = {"confirmed": R.GOOD, "partial": R.WARN, "missing": R.BAD, "unknown": R.GREY, "not_offered": R.GREY}
STATE_TXT = {"confirmed": "Confirmed", "partial": "Partially confirmed", "missing": "Missing", "unknown": "Unknown", "not_offered": "Stated as not available"}
EXT_COL = {"verified": R.GOOD, "identified": R.GOOD, "contradicts": R.BAD, "unclear": R.WARN, "limited": R.WARN, "not_verified": R.GREY}

CONF_KEY = ("Confirmed: shown by a quotation from the hotel's own pages or a source the audit read, which the audit checked. Likely: the evidence points to it but cannot show it (for example something not found on pages that may "
            "not be all there is). Worth checking: a lead from a sample, such as one assistant on one day; look into it before acting.")
NOREAD = "Not assessed: the website could not be read, so nothing can be said about this either way."


def short(text, n):
    """Trim to a sentence or word boundary, never mid-word."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    for sep in (". ", "; ", ", ", " "):
        i = cut.rfind(sep)
        if i > n * 0.55:
            return cut[: i + (1 if sep == ". " else 0)].rstrip(" ;,") + ("" if sep == ". " else "...")
    return cut.rstrip() + "..."


def _path(u):
    from urllib.parse import urlparse
    return urlparse(u or "").path or "/"


def _ev1(r):
    """The first two evidence lines in full enough to read: what was found, and which pages were inspected for the rest."""
    parts = []
    for e in (r.get("evidence") or [{}])[:2]:
        q = short(e.get("snippet", ""), 330)
        lead = link(e["url"], _path(e["url"])) if e.get("url") else Markup("")
        note = "pages inspected for this" in q.lower() or q.startswith("No page about this topic")      # the audit's own note about what it looked at, not words from the website
        parts.append(cat(lead, ": " if lead and q else "", (f"Audit note: {q}" if note else f"“{q}”") if q else ""))
    out = parts[0]
    for x in parts[1:]:
        out = cat(out, Markup("<br/>"), x)
    return out


def _conf(r):
    return r.get("confidence_label") or "Likely"


def action_card(i, r):
    head = R.Paragraph(f"{i}. {esc(short(r['title'], 120))}", R.S["h3"])
    meta = R.P(cat(R.coloured(r["priority"].upper() + " priority", PRI_COL[r["priority"]]),
                   f" - effort {r['effort']} - {_conf(r)} - owner: {r.get('owner') or r['team'].capitalize()}"), "small")
    rows = [["Issue", short(r["finding"], 250)],
            ["Evidence", _ev1(r)],
            ["Why it matters", short(r["why"], 230)],
            ["Action", short(r["action"], 300)]]
    if r.get("example") and "[" in str(r["example"]):
        rows.append(["Example wording", short(r["example"], 330)])
    rows += [["How you will know", short(r.get("success_check") or r["expected_outcome"], 210)],
             ["Detail", f"Appendix reference {r['ref']}"]]
    return [KeepTogether([head, meta, table(rows, [0.17, 0.83], header=False, zebra=False), Spacer(1, 5)])]


def _breakdown(rep):
    sc = rep.get("scorecard") or {}
    if sc.get("categories"):
        t = scoring.totals_for(sc)
        return t["breakdown"], t["method"], t["simple_average"]
    return [], "", None


def _ai_line(rep):
    """One honest sentence on observed AI visibility: what was sampled, on which assistant, and what was not tested."""
    import ai_sample
    ai = rep.get("ai_sample") or {}
    log = ai_sample.test_log(ai) if ai.get("status") == "ok" else None
    if not log:
        return ("Not measured. No AI assistant was asked about the hotel in this audit, so AI visibility was not measured.", False)
    s = log["summary"]
    import trend
    where = f" Searches were run as if from {ai['search_country']}." if ai.get("search_country") else ""
    return (f"Sampled on one assistant only: {log['platform']}, on {log['date'] or 'the audit date'}.{where} It named the hotel in {s['appeared']} of {s['non_branded_answers']} answers to {s['prompts']} questions that do not "
            f"mention the hotel ({trend.band(s['appeared'], s['non_branded_answers'])}; from that many answers the true rate is plausibly {round(100 * trend.wilson(s['appeared'], s['non_branded_answers'])[0])}% to "
            f"{round(100 * trend.wilson(s['appeared'], s['non_branded_answers'])[1])}%), and recommended it in {s['recommended']}. This is a sample of answers, not a ranking.", True)


def _exec_sentences(c, h, top, hotel):
    score, cov = h["score"], h["coverage_pct"]
    if h["status"] == "withheld":
        s1 = (f"Too little of the full model could be assessed ({cov:.0f}%) to give {hotel} a single readiness score, so the category "
              "results are shown on their own.")
    else:
        lvl = "well" if score >= 75 else ("partly" if score >= 50 else "weakly")
        s1 = (f"On the factors we could measure, {hotel} is {lvl} set up to be found and understood (readiness {score}/100"
              f"{', provisional' if h['status'] == 'provisional' else ''} - {cov:.0f}% of the full model measured).")
    u = c["understanding"]
    s2 = ("What search and AI tools can clearly pick up from the website: " + ", ".join(u["strong_signals"][:4]) + ".") if u["strong_signals"] else ""
    return [x for x in (s1, s2) if x]


def _markets_block(rep, c):
    """The three things a general manager asks about the AI tests: in which searches does the assistant name the hotel, who does it name instead (only hotels in the hotel's own category), and what the evidence suggests differs."""
    import trend
    gap = rep.get("ai_gap") or {}
    ai = rep.get("ai_sample") or {}
    out = []
    if gap.get("status") == "ok" and gap.get("markets"):
        ms = [m for m in gap["markets"] if m["kind"] in ("niche", "custom", "generic")]
        ms.sort(key=lambda m: (m.get("priority") != "core", m["kind"] != "niche", m["qid"]))
        out.append(para("Which AI searches name the hotel, and who is named instead", "h3"))
        rows = [["A search a traveller might make", "Names the hotel", "Named instead (same category)"]]
        for m in ms[:12]:
            inst = ", ".join(f"{r['name']} ({r['answers']} of {r['of']})" for r in m["rivals"][:2]) or ("only hotels in a higher category" if m.get("other_category") else "-")
            rows.append([short(m["question"], 105), f"{m['named']} of {m['of']} ({trend.band(m['named'], m['of'])})", short(inst, 90)])
        out.append(table(rows, [0.46, 0.2, 0.34]))
        gm = [m for m in gap["markets"] if m["gap"]]
        obs = []
        for m in sorted(gm, key=lambda m: (not m["consistent"], m["qid"]))[:2]:
            for o in (gap.get("observations") or {}).get(m["qid"], []):
                if o["kind"] in ("criterion", "source", "facility") and o["text"] not in obs:
                    obs.append(o["text"])
        if obs:
            out.append(para("What the evidence suggests differs (observations, not proven causes)", "h3"))
            out += R.bullets([short(t, 260) for t in obs[:3]])
        opp = [a for a in gap.get("articles") or [] if a.get("opportunity")]
        if opp:
            out.append(para("Editorial pages the assistant cited that name rivals and not the hotel: " + "; ".join(f"{a['domain']} ({short(a['title'], 60)})" for a in opp[:3]) + ".", "base"))
        elif not gm and any(m["status"] != "named" for m in gap["markets"]):
            out.append(para(gap.get("reason") or "", "base"))
        fr = rep.get("forums") or {}
        n_live = len([o for o in fr.get("opportunities") or [] if o["can_comment"] != "closed"])
        if n_live:
            out.append(para(f"{n_live} open forum conversation(s) where travellers ask for hotels like this one's are listed, with links, in the appendix.", "base"))
        out.append(para("One assistant on one day: a lead to investigate, not a ranking or a cause. Hotels in a different category from this one are not counted as competitors. The evidence for each row, the pages the assistant cited and the "
                        "comparison with the rivals' own sites are in the appendix.", "tiny"))
    elif ai.get("status") == "ok":
        out.append(para("Which AI searches name the hotel", "h3"))
        log = __import__("ai_sample").test_log(ai)
        rows = [["A search a traveller might make", "Names the hotel"]] + [[short(g["text"], 120), f"{g['named']} of {g['of']} ({trend.band(g['named'], g['of'])})"] for g in __import__("ai_sample").by_question([i for i in ai["items"] if i["kind"] != "direct"])][:7]
        out.append(table(rows, [0.7, 0.3]))
    return out


# ----------------------------------------------------------------------------- at a glance: where the hotel does well and where it does not

AREA_MEANING = {"ai_visibility": "How often AI assistants name the hotel (sampled)", "otas": "Found on booking platforms (presence only)", "reviews": "Guest reviews and the hotel's replies",
                "editorial": "Coverage by travel writers and blogs", "website": "The hotel's own website: content and technical set-up", "social": "Social media and community presence",
                "entity": "Outside sources agree on name, address and phone", "freshness": "How up to date the published information is"}
AI_AIM_PCT = 30            # the owner's aim for how often the hotel is named; shown as an aim, never forced


def _verdict(score):
    if score is None:
        return "Not measured", R.GREY
    return ("Strong", R.GOOD) if score >= 75 else ("Partly there", R.WARN) if score >= 50 else ("Weak", R.BAD)


def _bar(score, colour, w=76, h=8):
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.lib import colors
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor("#e6e8ee"), strokeColor=None))
    if score is not None:
        d.add(Rect(0, 0, w * max(0, min(100, score)) / 100, h, fillColor=colors.HexColor(colour), strokeColor=None))
    return d


def _scoreboard(rep, h):
    """Every area the readiness score covers, as a bar and a plain verdict, plus the AI sample against the 30% aim."""
    from reportlab.platypus import Table, TableStyle
    cats = (rep.get("scorecard") or {}).get("categories") or []
    rows = [(c["label"], c.get("score") if c.get("assessed") else None, AREA_MEANING.get(c["key"], ""), c["key"], c.get("partial")) for c in cats if c["key"] != "ai_visibility"]
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    ai = rep.get("ai_sample") or {}
    ai_row = None
    if ai.get("status") == "ok":
        import ai_sample
        sm = (ai_sample.test_log(ai) or {}).get("summary") or {}
        if sm.get("non_branded_answers"):
            pct = round(100 * sm["appeared"] / sm["non_branded_answers"])
            ai_row = ("AI visibility (sampled)", pct, f"Named in {sm['appeared']} of {sm['non_branded_answers']} answers (aim: about {AI_AIM_PCT}%)", pct >= AI_AIM_PCT)
    data = [[R.Paragraph("<b>Area</b>", R.S["cellb"]), R.Paragraph("<b>Score</b>", R.S["cellb"]), "", R.Paragraph("<b>Verdict</b>", R.S["cellb"]), R.Paragraph("<b>What it covers</b>", R.S["cellb"])]]
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, R.RULE), ("BACKGROUND", (0, 0), (-1, 0), R.HEAD_BG), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for label, score, meaning, _k, partial in rows:
        word, col = _verdict(score)
        data.append([R.Paragraph(esc(label + (" (partial)" if partial else "")), R.S["cell"]), R.Paragraph(f"<b>{score}</b>" if score is not None else "-", R.S["cell"]), _bar(score, col),
                     R.Paragraph(R.coloured(word, col), R.S["cell"]), R.Paragraph(esc(meaning), R.S["cell"])])
    if ai_row:
        label, pct, meaning, ok = ai_row
        col = R.GOOD if ok else R.WARN
        data.append([R.Paragraph(f"<b>{esc(label)}</b>", R.S["cell"]), R.Paragraph(f"<b>{pct}%</b>", R.S["cell"]), _bar(pct, col),
                     R.Paragraph(R.coloured("Meets the aim" if ok else "Below the aim", col), R.S["cell"]), R.Paragraph(esc(meaning), R.S["cell"])])
    t = Table(data, colWidths=[w * R.W for w in (0.24, 0.07, 0.17, 0.13, 0.39)], repeatRows=1)
    t.setStyle(TableStyle(style))
    return [para("Scorecard at a glance", "h3"), t,
            para("Strong is 75 or more, partly there 50 to 74, weak under 50. AI visibility is a sample from one assistant and is not part of the readiness score.", "tiny")]


def _engines_band(rep):
    """One line near the top of page 1: which assistant was asked, with how many prompts and answers."""
    import engines
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    tested = [e for e in engines.rows(rep) if e["tested"]]
    if not tested:
        return []
    t = Table([[R.Paragraph("<font color='%s'><b>AI assistant asked</b></font><br/>%s" % (R.GOOD, esc(tested[0]["detail"].replace("Tested: ", "", 1))), R.S["cell"])]], colWidths=[R.W])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f1f8f3")), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return [Spacer(1, 3), t]


def _strengths_weaknesses(rep, c, h, top):
    """Two plain lists the manager reads first: what is working, and what is not, each item concrete and taken from the audit."""
    good, bad = [], []
    for cat_ in (rep.get("scorecard") or {}).get("categories") or []:
        if cat_.get("assessed") and cat_.get("score") is not None and cat_["key"] != "ai_visibility":
            line = f"{cat_['label']}: {cat_['score']}/100. {short(AREA_MEANING.get(cat_['key'], ''), 80)}"
            (good if cat_["score"] >= 75 else bad if cat_["score"] < 60 else []).append(line)
    for sig in (c.get("understanding") or {}).get("strong_signals", [])[:2]:
        good.append(f"The website clearly shows: {short(sig, 90)}")
    for seg in (c.get("traveller") or {}).get("segments", []):
        cn = seg["counts"]
        tot = cn["confirmed"] + cn["partial"] + cn["missing"]
        if tot and cn["confirmed"] >= max(2, tot * 0.6):
            good.append(f"{seg['label']}: {cn['confirmed']} of {tot} things travellers need to know are stated on the website")
        elif tot and cn["missing"] >= max(2, tot * 0.4):
            miss = [r["label"] for r in seg["requirements"] if r["state"] == "missing"][:3]
            bad.append(f"{seg['label']}: {cn['missing']} of {tot} things travellers need to know are missing ({', '.join(miss)})")
    for f in c.get("facility_depth") or []:
        n_ = len(f["found"])
        if f["thin"]:
            bad.append(f"{f['label']} is mentioned but only {n_} of {f['total']} details are stated (missing: {', '.join(m['label'].split(' (')[0].lower() for m in f['missing'][:3])})")
        else:
            good.append(f"{f['label']}: {n_} of {f['total']} details are stated on the website")
    gap = rep.get("ai_gap") or {}
    for m in (gap.get("markets") or []):
        q = short(m["question"], 80)
        if m["named"] and m["named"] >= m["of"] / 2:
            good.append(f"AI names the hotel for \u201c{q}\u201d ({m['named']} of {m['of']} answers)")
        elif m["gap"] and m["rivals"]:
            bad.append(f"AI does not name the hotel for \u201c{q}\u201d ({m['named']} of {m['of']}); it names {m['rivals'][0]['name']} instead")
    cit = rep.get("citations") or {}
    if cit.get("basis") == "named":
        if cit.get("own_answers", 0) >= cit["answers"] / 2:
            good.append(f"The hotel's own website is one of the sources AI uses when it names the hotel ({cit['own_answers']} of {cit['answers']} answers)")
        elif cit.get("ota_answers", 0) > cit.get("own_answers", 0):
            bad.append(f"When AI names the hotel it cites booking sites in {cit['ota_answers']} of {cit['answers']} answers and the hotel's own website in {cit.get('own_answers', 0)}")
    for r in top[:3]:
        bad.append(short(r.get("short_title") or r["title"], 120))
    if not any("hygiene" in b.lower() or "risk" in b.lower() for b in bad) and not [r for r in c["recommendations"] if r["source"] == "intel" and r["kind"] == "fix" and r["priority"] in ("critical", "high")]:
        good.append("No serious reputation or consistency problem was found in the outside sources checked")
    seen = set()
    good = [x for x in good if not (x in seen or seen.add(x))][:6]
    bad = [x for x in dict.fromkeys(bad)][:7]
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    def col(title, items, colour, empty):
        cells = [R.Paragraph(f"<font color='{colour}'><b>{title}</b></font>", R.S["h3"])]
        cells += [R.Paragraph("&bull; " + esc(x), R.S["cell"]) for x in items] or [R.Paragraph(esc(empty), R.S["cell"])]
        return cells
    left, right = col("Where the hotel does well", good, R.GOOD, "Nothing stood out as strong in what could be measured."), col("Where it does not", bad, R.BAD, "No clear weakness was found.")
    t = Table([[left, right]], colWidths=[0.5 * R.W, 0.5 * R.W])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f1f8f3")), ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fdf3f2")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LINEAFTER", (0, 0), (0, 0), 3, colors.white)]))
    return [Spacer(1, 4), t]


# ----------------------------------------------------------------------------- competitors and sources

def _competitor_block(rep):
    """Every hotel the assistant named, ranked: how often, where in its list, and how it described each. The hotel is marked."""
    ins = rep.get("ai_insights") or {}
    br = ins.get("brand_ranking") or {}
    rows = br.get("all") or br.get("rows") or []
    if not rows:
        return [para("No ranking of the hotels the assistant names could be made in this audit (the AI sample was not run, or it named no hotels).", "base")]
    rows = sorted(rows, key=lambda r: (-(r.get("mentions") or 0), r.get("avg_rank") or 99))
    me = next((r for r in rows if r.get("is_target")), None)
    pos = rows.index(me) + 1 if me else None
    first = rows[0]
    answers = max((r.get("of") or 0) for r in rows)
    hotel = (rep.get("meta") or {}).get("hotel", "the hotel")
    intro = (f"Across {answers} sampled answers the assistant named {len(rows)} different hotels. " + (f"{hotel} came {pos} of {len(rows)}, named in {me['mentions']} answers ({me.get('coverage_pct', 0)}%). " if me else f"{hotel} was not named. ")
             + (f"The most-named hotel was {first['name']} ({first.get('coverage_pct', 0)}%)." if first is not me else "The hotel was the most-named."))
    show = rows[:8]
    if me and me not in show:
        show = show[:7] + [me]
    table_rows = [["#", "Hotel", "Named in", "Average position", "How it was described"]]
    for r in show:
        n = rows.index(r) + 1
        name = Markup(f"<b>{esc(r['name'])} (this hotel)</b>") if r.get("is_target") else r["name"]
        sent = r.get("sentiment")
        table_rows.append([str(n), name, f"{r.get('mentions', 0)} of {r.get('of', 0)} ({r.get('coverage_pct', 0)}%)", "-" if r.get("avg_rank") is None else f"{r['avg_rank']:g}",
                           "not judged" if sent is None else ("positive" if sent >= 40 else "negative" if sent <= -40 else "mixed") + f" ({sent:+d})"])
    return [KeepTogether([para(intro, "base"), table(table_rows, [0.05, 0.37, 0.2, 0.15, 0.23])]),
            para("Average position: the hotel's place in the hotels an answer listed (1 is first). One assistant, a sample of answers on one day: a guide to who the assistant reaches for, not a ranking of hotels.", "tiny")]


def _sources_block(rep):
    """The sources that came up first: ranked by how many answers used them, with the kind of site, and whether the hotel's own site is among them."""
    cit = rep.get("citations") or {}
    if cit.get("rows"):
        n = cit["answers"] if cit["basis"] == "named" else cit.get("answers_all") or cit["answers"]
        basis = "the answers that named the hotel" if cit["basis"] == "named" else "all the answers (none of them named the hotel)"
        rows = [["#", "Source", "Type of site", f"Came up in (of {n} answers)", "Share"]]
        for i, r in enumerate(cit["rows"][:8], 1):
            nm = Markup(f"<b>{esc(r['domain'])} (the hotel's own site)</b>") if r["is_own"] else r["domain"]
            rows.append([str(i), nm, r["kind"], str(r["came_up"]), f"{r['share_pct']}%"])
        out = [para(f"The sources the assistant used, in {basis}, most-used first.", "base"), table(rows, [0.05, 0.33, 0.27, 0.23, 0.12])]
        kinds = [f"{k['kind'].lower()} {k['answers']} of {k['of']}" for k in cit.get("by_kind") or []][:4]
        if kinds:
            out.append(para("By type of site: " + "; ".join(kinds) + ".", "base"))
        if cit["basis"] == "named":
            if cit.get("ota_answers", 0) > cit.get("own_answers", 0):
                out.append(para(f"Booking and comparison sites (which charge commission) were cited in {cit['ota_answers']} of {cit['answers']} answers; the hotel's own website in {cit.get('own_answers', 0)}. "
                                "Getting the hotel's own pages quoted instead is one of the actions below.", "note"))
            else:
                out.append(para(f"The hotel's own website was cited in {cit.get('own_answers', 0)} of {cit['answers']} answers, as often as the booking sites ({cit.get('ota_answers', 0)}).", "base"))
        pages = sorted((p for r in cit["rows"] for p in r.get("pages") or []), key=lambda p: -p["n"])[:5]
        if pages:
            out.append(para("Pages cited most", "h3"))
            out += R.bullets([cat(link(p["url"], short(p.get("title") if p.get("title") and p["title"] != "t" else p["url"], 70)), f" - cited in {p['n']} answers") for p in pages])
        return out
    ins = rep.get("ai_insights") or {}
    srcs = ins.get("sources") or []
    if srcs:
        rows = [["#", "Source", "Type of site", "Answers that used it"]] + [[str(i), s_["domain"], s_["kind"], str(s_["answers"])] for i, s_ in enumerate(srcs[:8], 1)]
        return [para("The sources the assistant used across its answers, most-used first.", "base"), table(rows, [0.06, 0.4, 0.34, 0.2])]
    return [para("No sources were recorded: the AI sample was not run or used no web pages.", "base")]


def _facility_block(c):
    """How completely the website describes each facility it has: the details stated, and the ones left out that an assistant would need to quote."""
    fd = c.get("facility_depth") or []
    if not fd:
        return []
    rows = [["Facility", "Details stated", "Left out (an assistant has nothing to quote)"]]
    for f in fd:
        n = len(f["found"])
        col = R.GOOD if not f["thin"] else (R.BAD if n <= 1 else R.WARN)
        rows.append([f["label"], R.coloured(f"{n} of {f['total']}", col), short("; ".join(m["label"] for m in f["missing"]) or "nothing important", 230)])
    return [para("How completely the website describes its facilities", "h3"),
            para("A facility that is only mentioned (“we have event space”) gives an assistant nothing to answer “which hotels can host 120 people?”. Stating each size, capacity and the events hosted is what lets it name the hotel.", "tiny"),
            table(rows, [0.22, 0.13, 0.65])]


def _forums_block(rep):
    """Open conversations (Reddit and similar) where travellers ask for hotels like this one's: each with its link, whether a comment is still possible, and what to do."""
    fr = rep.get("forums") or {}
    ops = [o for o in fr.get("opportunities") or [] if o.get("can_comment") != "closed"]
    hotel = (rep.get("meta") or {}).get("hotel", "the hotel")
    if fr.get("status") != "ok":
        return [para("The open forums were not searched in this audit" + (": " + short(fr.get("reason"), 160) if fr.get("reason") else "") + ".", "base")]
    if not ops:
        import forums as _forums
        links = _forums.search_links(fr.get("topics") or [], ("reddit.com",))[:3]
        out = [para("No open thread matching this market turned up in this audit's searches. That shows what the search saw, not that none exist.", "base")]
        if links:
            out.append(para("Search Reddit yourself:", "h3"))
            out += R.bullets([cat(link(x["url"], x["topic"])) for x in links])
        return out
    rows = [["Forum", "Thread (opens the link)", "Can you reply?", "Age", "Cited by AI"]]
    word = {"open": "Yes", "likely open": "Probably", "check": "Check the link"}
    for o in ops[:7]:
        rows.append([o["forum"], link(o["url"], short(o["title"], 80)), word.get(o["can_comment"], "Check"), o.get("age") or "-", "Yes" if o.get("cited_by_ai") else "No"])
    n_cited = sum(1 for o in ops if o.get("cited_by_ai"))
    out = [para(f"{len(ops)} open conversation{'s' if len(ops) != 1 else ''} where travellers are asking where to stay in this hotel's market" + (f"; {n_cited} of them {'was' if n_cited == 1 else 'were'} cited by an AI answer in this audit." if n_cited else "."), "base"),
           table(rows, [0.17, 0.47, 0.14, 0.12, 0.1])]
    out.append(para("What to do", "h3"))
    out += R.bullets(["Open each link, check the thread still takes comments (Reddit locks threads about six months after they were posted) and read the forum's rules on businesses.",
                      f"Reply once, as {hotel}, and say you work there. Answer the question that was asked with facts: where the hotel is, what is included, who it suits and who it does not.",
                      "Never post as a guest, write reviews, ask for upvotes or offer anything in return: forums ban it and assistants learn to discount it.",
                      "The web dashboard gives suggested wording for each thread."])
    return out


def _action_plan(c, recs, top, H1):
    out = []
    out.append(R.PageBreak())
    out.append(H1("What to do first: the action plan"))
    out.append(para("Chosen and ordered from the whole audit by one ranking model: commercial and operational importance, relevance to discovery and traveller decisions, confidence in the evidence, and implementation "
                    "effort. Every action rests on evidence from the pages or sources named. None guarantees that any AI assistant will recommend the hotel.", "muted"))
    for i, r in enumerate(top, 1):
        out += action_card(i, r)
    plan = c["plan"]
    order, phase = [], {}
    for label, key in (("Days 1-30", "30"), ("Days 31-60", "60"), ("Days 61-90", "90")):
        for rid in plan.get(key, []):
            if rid not in phase:
                order.append(rid)
                phase[rid] = label
    for heading, kind, intro in (("Confirmed problems: suggested implementation order", "fix", "Things the audit found missing, wrong or broken on evidence it holds."),
                                  ("Optional opportunities: not deficiencies", "opportunity", "Ways to strengthen a market the hotel may want. None of these is a fault, and none is needed unless the hotel wants that market.")):
        order, phase = [], {}
        for label, key in (("Days 1-30", "30"), ("Days 31-60", "60"), ("Days 61-90", "90")):
            for rid in c["plan"].get(key, []):
                if rid not in phase and recs[rid]["kind"] == kind and _conf(recs[rid]) != "Worth checking":
                    order.append(rid)
                    phase[rid] = label
        order = order[:8 if kind == "fix" else 5]            # a short list a manager can act on; everything else is in the appendix
        out.append(para(heading, "h3"))
        out.append(para(intro, "tiny"))
        if order:
            rows = [["#", "Action", "Owner", "Priority", "Effort", "When", "Ref"]]
            for n, rid in enumerate(order, 1):
                r = recs[rid]
                rows.append([str(n), short(r.get("short_title") or r["title"], 90), r.get("owner") or r["team"].capitalize(), R.coloured(r["priority"], PRI_COL[r["priority"]]), r["effort"], phase[rid], r["ref"]])
            out.append(table(rows, [0.04, 0.38, 0.13, 0.1, 0.08, 0.12, 0.15]))
        else:
            out.append(para("None.", "base"))
    out.append(para("Days 1-30: serious and quick items. Days 31-60: medium-effort fixes. Days 61-90: larger pieces of work. Re-run the audit afterwards to check what changed.", "tiny"))
    leads = sorted((r for r in recs.values() if _conf(r) == "Worth checking"), key=lambda r: -r["rank"])
    if leads:
        out.append(para("Leads worth looking into (not yet findings)", "h3"))
        out.append(para("These come from a sample (one assistant on one day, a search result) or an experimental reading. Look at them before acting; the evidence for each is in the appendix.", "tiny"))
        out.append(table([["Lead", "Owner", "Ref"]] + [[short(r.get("short_title") or r["title"], 100), r.get("owner") or r["team"].capitalize(), r["ref"]] for r in leads[:5]], [0.7, 0.15, 0.15]))

    out.append(para("How sure we are", "h3"))
    out.append(para(CONF_KEY, "tiny"))
    return out


def story(rep, H1):
    c = rep["consultant"]
    meta = rep.get("meta", {})
    hotel = meta.get("hotel", "the hotel")
    h = rep.get("headline") or headline_mod.build(rep)
    recs = {r["id"]: r for r in c["recommendations"]}
    top = [recs[i] for i in c["top_actions"] if recs[i]["kind"] == "fix" and recs[i].get("confidence_label") != "Worth checking"][:5]
    out = [R.Spacer(1, 6 * R.mm), para("Management report", "title"), para(hotel, "h1"),
           R.P(link(meta.get("base", ""), meta.get("website", "")) + " - " + esc(meta.get("city", "")) +
               " - audit run " + esc(R._date(meta.get("run_at"))), "base"), Spacer(1, 4),
           para("How well this hotel is set up to be found and understood by search and AI systems, what travellers and assistants cannot yet learn from it, and what to do first. "
                "Quotes, URLs and method are in the Technical & Evidence Appendix; every action gives its reference.", "muted")]

    cov = c.get("coverage") or {}
    if cov.get("limited") or cov.get("text_only"):
        why = "; ".join(f"{n} x {r}" for r, n in (cov.get("failure_reasons") or {}).items())
        head = "" if str(cov.get("note", "")).startswith(("We could read", "We could only read")) or "which is only part of a hotel" in str(cov.get("note", "")) else f"Read {cov['pages_read']} of {cov['pages_attempted']} pages. "
        out.append(para(f"{head}{cov['note']}" + (f" Why pages failed: {why}." if why else ""), "note"))

    # 1 -------------------------------------------------------------- executive summary
    out.append(H1("Executive summary"))
    num = "-" if h["score"] is None else f"{h['score']} / 100"
    ai_text, ai_sampled = _ai_line(rep)
    out.append(table([["Readiness score", "Readiness (how well the hotel is set up)", "Observed AI visibility (what assistants actually say)"],
                      [Markup(f"<font size=20><b>{esc(num)}</b></font>"),
                       cat(R.coloured(h["badge"].upper(), STATUS_COL[h["status"]]), Markup("<br/>"), f"Measurement coverage: {h['coverage_pct']:.0f}% of the full model"),
                       cat(R.coloured("SAMPLED, ONE ASSISTANT" if ai_sampled else "NOT MEASURED", R.WARN if ai_sampled else R.BAD), Markup("<br/>"), ai_text)]],
                     [0.18, 0.27, 0.55], zebra=False))
    out.append(Spacer(1, 3))
    for s in _exec_sentences(c, h, top, hotel)[1:]:
        out.append(para(s, "base"))
        out.append(Spacer(1, 2))
    out += _engines_band(rep)
    out += _scoreboard(rep, h)
    out += _strengths_weaknesses(rep, c, h, top)
    out.append(para("Readiness and observed AI visibility are kept separate on purpose: a well-prepared hotel can still not be recommended, and a hotel can be recommended by chance while poorly prepared. "
                    "This report scores readiness. It does not claim to measure visibility.", "tiny"))
    out.append(R.PageBreak())
    out.append(H1("Competitors: who AI recommends instead"))
    out += _competitor_block(rep)
    out += _markets_block(rep, c)
    out.append(H1("Where AI gets its information"))
    out += _sources_block(rep)
    out.append(H1("Open conversations you can join"))
    out += _forums_block(rep)
    out += _action_plan(c, recs, top, H1)

    # 2 -------------------------------------------------------------- discoverability and technical readiness
    out.append(H1("Discoverability and technical readiness"))
    prof = {p["key"]: p for p in c["profile"]}
    rows = [["Measure", "Score", "Evidence strength", "What drove it"]]
    skipped = [prof[k]["label"] for k in ("discoverability", "technical", "structured") if prof.get(k) and not prof[k]["assessed"]]
    for k in ("discoverability", "technical", "structured", "entity"):
        p = prof.get(k)
        if not p or (len(skipped) >= 2 and k in ("discoverability", "technical", "structured") and not p["assessed"]):
            continue                                   # several 'not assessed' rows say one thing once, below the table
        ev = p.get("evidence") or {}
        sc = f"{p['score']} / 100" if p["assessed"] else "not assessed"
        rows.append([p["label"], sc, R.coloured((ev.get("level") or "-") + " evidence", LEVEL_COL.get(ev.get("level"), R.GREY)),
                     short("; ".join(p["drivers"][:2]), 140) + (f" ({ev['why']})" if ev.get("why") else "")])
    out.append(table(rows, [0.2, 0.12, 0.16, 0.52]))
    if len(skipped) >= 2:
        out.append(para("Not assessed: " + ", ".join(skipped) + ". " + ("The pages were read as plain text, so their markup, titles, headings and images could not be inspected." if (c.get("coverage") or {}).get("text_only") else "Too few pages could be read to judge them."), "base"))
    out.append(para("A score and the evidence behind it are different things: a high score on thin evidence is shown as such.", "tiny"))
    # how the overall number is made
    bd, method, simple = _breakdown(rep)
    if bd:
        out.append(para("How the readiness score is calculated", "h3"))
        rows = [["Category", "Score", "Weight", "Share of the measured weight", "Points added"]]
        for b in bd:
            rows.append([b["label"] + (" (partial)" if b.get("partial") else ""), f"{b['score']}", f"{b['weight']:g}%", f"{b['share_pct']:g}%", f"{b['points']:g}"])
        rows.append([Markup("<b>Readiness</b>"), "", "", "", Markup(f"<b>{h['score'] if h['score'] is not None else '-'}</b>")])
        out.append(table(rows, [0.34, 0.12, 0.14, 0.24, 0.16]))
        out.append(para(method, "tiny"))
    if h["unassessed"]:
        out.append(para("Not measured, and therefore not counted", "h3"))
        out += R.bullets([f"{u['label']} ({u['weight']:g}% of the model): {short(u['why'], 170)}" for u in h["unassessed"]])
    # structured data and booking
    sd = c.get("structured") or {}
    sd_items = {i["item"]: i for i in sd.get("items", [])}
    hot = sd_items.get("Hotel / LodgingBusiness")
    if cov.get("unreadable"):
        out.append(para(NOREAD, "base"))
    elif hot:
        out.append(para("Structured data", "h3"))
        out.append(para(short(hot["detail"], 420), "base"))
    bk = c.get("booking") or {}
    if bk.get("status") == "ok" and bk.get("checks"):
        out.append(para("Booking readiness", "h3"))
        sym = {"pass": ("OK", R.GOOD), "warn": ("Check", R.WARN), "fail": ("Problem", R.BAD), "not_verified": ("Not verified", R.GREY)}
        out.append(table([["Check", "Result", "Detail"]] + [[ck["label"], R.coloured(*sym.get(ck["state"], ("-", R.GREY))), short(ck["detail"], 200)] for ck in bk["checks"]], [0.34, 0.14, 0.52]))
    sig = [r for r in c["recommendations"] if r["source"] in ("machine", "structured") and r["kind"] == "fix" and r["priority"] in ("critical", "high", "medium")][:5]
    if sig:
        out.append(para("Significant technical issues", "h3"))
        out += R.bullets([cat(Markup(f"<b>{esc(short(r['title'], 90))}</b>"), f" - {short(r['finding'], 170)} ({r['ref']})") for r in sig])
    elif cov.get("text_only"):
        out.append(para("The technical checks that need a page's markup (structured data, titles, headings, image text, canonical tags) were not made, because the pages were read as plain text. No technical conclusion is drawn.", "base"))
    elif not hot and not cov.get("unreadable"):
        out.append(para("No significant technical issue was found in the pages read.", "base"))

    # 3 -------------------------------------------------------------- traveller recommendation readiness
    out.append(H1("Traveller recommendation readiness"))
    trv = c.get("traveller") or {}
    segs = trv.get("segments") or []
    out.append(para("For each kind of traveller the hotel serves: does its own website state what that traveller needs to know before booking? Confirmed means clearly stated; Missing means not found in pages "
                    "that were read well enough to say so; Unknown means too little was read, or the hotel gives no sign it offers the thing, so nothing is recommended.", "muted"))
    if not segs:
        out.append(para(NOREAD if cov.get("unreadable") else "No traveller segment could be assessed from the pages read.", "base"))
    for seg in segs:
        cn = seg["counts"]
        out.append(para(f"{seg['label']}: {cn['confirmed']} confirmed, {cn['partial']} partly, {cn['missing']} missing" + (f", {cn['unknown']} unknown" if cn["unknown"] else ""), "h3"))
        rows = [["Requirement", "Status", "What the website says, or what to add"]]
        for r in seg["requirements"]:
            if r["state"] == "confirmed":
                det = "States: " + "; ".join(f["fact"] for f in r["found"][:2])
            elif r["state"] in ("partial", "missing"):
                w = (r.get("where") or {})
                det = "Add: " + "; ".join(r["add"][:2]) + (f" (on {w['label']})" if w.get("label") else "")
            else:
                det = short(r.get("why", ""), 150)
            rows.append([r["label"], R.coloured(STATE_TXT[r["state"]], STATE_COL[r["state"]]), short(det, 190)])
        out.append(table(rows, [0.3, 0.2, 0.5]))
    out += _facility_block(c)
    if trv.get("skipped"):
        out.append(para("Not assessed (the site shows no sign the hotel serves these travellers): " + ", ".join(s["label"] for s in trv["skipped"]) + ".", "tiny"))

    # 4 -------------------------------------------------------------- external presence and reputation
    out.append(H1("External presence and reputation"))
    ext = c.get("external") or rep.get("external") or {}
    if ext.get("rows"):
        out.append(para("Whether the right hotel can be identified on each outside source, and whether what they show agrees with the website. A source that cannot be checked reliably is marked Not verified, never missing or wrong.", "muted"))
        rows = [["Source", "Status", "Notes"]]
        for r in ext["rows"]:
            note = "; ".join(r["contradictions"]) if r["contradictions"] else short(r["note"], 170)
            rows.append([r["source"], R.coloured(r["label"], EXT_COL[r["status"]]), note])
        out.append(table(rows, [0.28, 0.2, 0.52]))
        nm = (rep.get("listing_checks") or {}).get("names") or []
        if nm:
            out.append(para("How each booking platform shows the hotel's name", "h3"))
            rows_n = [["Platform", "Name shown", "Same as the website?", "Difference"]]
            by_row = {(r["platform"], r["fact"]): r for r in (rep.get("listing_checks") or {}).get("rows", [])}
            for n_ in nm:
                rw = by_row.get((n_["platform"], "Hotel name")) or {}
                rows_n.append([n_["platform"], short(n_["shown_name"], 70), R.coloured("Yes", R.GOOD) if n_["status"] == "matches" else R.coloured("No", R.BAD), short(rw.get("note") or "-", 90)])
            out.append(table(rows_n, [0.18, 0.36, 0.16, 0.30]))
            out.append(para("Read from the titles and quoted passages in public search results, not from the platforms' own pages. Check the live listing before changing anything.", "tiny"))
        diffs = [f"{r['platform']}: {r['fact'].lower()} shows {r['listing_says']}, the website says {r['site_says']}" for r in (rep.get("listing_checks") or {}).get("rows", []) if r["status"] == "differs"]
        items = [f"{x['source']}: {x['text']}" for x in ext.get("contradictions", [])]
        out.append(para("Information inconsistencies", "h3"))
        out += R.bullets(list(dict.fromkeys(items + diffs)) or ["None found among the facts that could be compared (names, addresses, phone numbers, check-in and check-out times quoted by outside sources)."])
    else:
        out.append(para("The outside sources were not checked in this run.", "base"))
    risks = [r for r in c["recommendations"] if r["source"] == "intel" and r["kind"] == "fix" and not r["id"].startswith("X-S-") and r.get("confidence") != "Reasonable inference"]
    out.append(para("Confirmed reputation risks", "h3"))
    if risks:
        rows = [["Risk", "What we found", "Priority", "Ref"]]
        for r in risks:
            rows.append([short(r["title"], 80), short(r["finding"], 190), R.coloured(r["priority"], PRI_COL[r["priority"]]), r["ref"]])
        out.append(table(rows, [0.28, 0.5, 0.1, 0.12]))
    else:
        out.append(para("No reputation risk was confirmed in the sources checked.", "base"))
    rs = rep.get("review_snapshot") or {}
    rpk = rep.get("review_pack") or {}
    out.append(para(f"The hotel's own review export ({rpk['reviews']} reviews) was analysed: reply rate {rpk['reply_rate']}%, {rpk['critical_unanswered']} critical review(s) without a reply. "
                    "These figures are for that file only; the detail is in the appendix."
                    if rpk.get("reviews") and rpk.get("reply_rate") is not None and rpk.get("critical_unanswered") is not None else
                    "An indicative snapshot of public reviews and the hotel's replies is in the appendix; it is a small sample, not a reply rate."
                    if rs.get("status") == "ok" else
                    "Guest reviews could not be assessed (the platforms prohibit automated collection), so the absence of a finding here is not evidence of a healthy review profile. "
                    "Uploading the hotel's own review export adds this.", "tiny"))

    # 5 -------------------------------------------------------------- commercial opportunities
    out.append(H1("Commercial opportunities"))
    hc = (c.get("hotel_class") or {}).get("classes") or []
    out.append(para("What kind of hotel this is, and who it mainly serves", "h3"))
    if hc:
        out.append(table([["Hotel type", "Why"]] + [[x["label"], "; ".join(x["reasons"][:2])] for x in hc], [0.28, 0.72]))
    else:
        out.append(para("The pages did not show a clear type (airport, business, spa, resort...), so traveller segments are assessed only where the site itself describes the facilities.", "base"))
    trv_ = c.get("traveller") or {}
    seg_rows = [[sg["label"], "Core to this hotel" if sg.get("relevance", "core") == "core" else "Secondary: offered, but not what the hotel is for",
                 f"{sg['counts']['confirmed']} confirmed, {sg['counts']['partial']} partly, {sg['counts']['missing']} missing"] for sg in trv_.get("segments", [])]
    if seg_rows:
        out.append(table([["Traveller segment", "Relevance", "Information on the website"]] + seg_rows, [0.3, 0.4, 0.3]))
    if trv_.get("skipped"):
        out.append(para("Not assessed, and no marketing advice given, because nothing shows the hotel serves or wants this market: " + ", ".join(x["label"] for x in trv_["skipped"]) + ".", "tiny"))
    elif not seg_rows:
        out.append(para(NOREAD if cov.get("unreadable") else "No traveller segment could be assessed from the pages read.", "base"))
    opp = c.get("opportunities") or []
    if opp:
        out.append(para("Underrepresented facilities and services", "h3"))
        out.append(para("Not defects. Weak signals matter only if the segment is one the hotel wants to attract.", "tiny"))
        out += R.bullets([o["statement"] for o in opp[:3]])
    cp = c.get("competitors") or {}
    out.append(para("Verified competitive opportunities", "h3"))
    if cp.get("status") == "ok":
        behind = [x for x in cp["comparisons"] if x["behind"]]
        out.append(para("Compared with " + ", ".join(k["name"] for k in cp["competitors"]) + " (chosen automatically as comparable by rating or size and by facilities; only pages read on both sides are compared).", "tiny"))
        out += R.bullets([x["statement"] for x in behind] or ["On the facilities compared, the hotel's pages state as much as the comparable hotels' pages."])
    else:
        out.append(para((cp.get("reason") or "A competitor comparison was not possible in this run.") + " The hotel's own opportunity analysis above stands without it.", "base"))

    # 7 -------------------------------------------------------------- methodology and limitations
    out.append(H1("Methodology and limitations"))
    gq = rep.get("guest_questions") or {}
    web = rep.get("web_signals") or {}
    import assessment
    asm = assessment.assess(rep)
    for bucket, title in (("assessed", "Assessed"), ("partial", "Partly assessed"), ("not_assessed", "Not assessed")):
        out.append(para(title, "h3"))
        out += R.bullets([cat(Markup(f"<b>{esc(i['what'])}</b>"), (": " + i["detail"]) if i["detail"] else "") for i in asm[bucket]] or ["Nothing in this group."])
    cnc = c.get("could_not_confirm") or []
    if cnc:
        out.append(para("Could not be confirmed either way (no recommendation made)", "h3"))
        out += R.bullets([f"{x['topic']}: {x['why']}" for x in cnc])
    n_ver = sum(1 for r in c["recommendations"] if _conf(r) == "Confirmed")
    out.append(para("Confidence", "h3"))
    n_lik = sum(1 for r in c["recommendations"] if _conf(r) == "Likely")
    n_chk = sum(1 for r in c["recommendations"] if _conf(r) == "Worth checking")
    out.append(para(f"Of the {len(c['recommendations'])} findings in this audit, {n_ver} are Confirmed, {n_lik} Likely and {n_chk} Worth checking (what each label means is explained in the executive summary). "
                    f"{len(c.get('dropped_recommendations') or [])} candidate finding(s) were withheld for lacking evidence or a specific action.", "base"))
    out.append(para("AI recommendation testing", "h3"))
    out.append(para(("The AI assistant asked was " + (rep.get("ai_sample") or {}).get("model", "Claude") + " with live web search; every prompt and answer is logged in the appendix. "
                     "Observed AI visibility stays separate from the readiness score.")
                    if ai_sampled else "No AI assistant was asked in this audit, so observed AI visibility is not measured. Readiness is reported on its own.", "base"))
    out += R.bullets([f"The readiness score rests on {h['coverage_pct']:.0f}% of the full model and is a set-up indicator, not a measure of AI visibility.",
                      "Findings come from the hotel's own pages and public sources read during the audit; search results and open data vary between runs.",
                      "Nothing here guarantees that any AI assistant will recommend the hotel."])
    return out
