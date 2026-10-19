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
EXT_COL = {"verified": R.GOOD, "identified": R.GOOD, "contradicts": R.BAD, "unclear": R.WARN, "not_verified": R.GREY}

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
        parts.append(cat(lead, ": " if lead and q else "", f"“{q}”" if q else ""))
    out = parts[0]
    for x in parts[1:]:
        out = cat(out, Markup("<br/>"), x)
    return out


def _conf(r):
    return r.get("confidence_label") or ("Verified finding" if r.get("confidence") == "Established good practice" else "Reasonable inference")


def action_card(i, r):
    head = R.Paragraph(f"{i}. {esc(short(r['title'], 120))}", R.S["h3"])
    meta = R.P(cat(R.coloured(r["priority"].upper() + " priority", PRI_COL[r["priority"]]),
                   f" - effort {r['effort']} - {_conf(r)} - owner: {r.get('owner') or r['team'].capitalize()}"), "small")
    rows = [["Issue", short(r["finding"], 250)],
            ["Evidence", _ev1(r)],
            ["Why it matters", short(r["why"], 230)],
            ["Action", short(r["action"], 300)],
            ["Expected outcome", short(r["expected_outcome"], 210)],
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
        return ("Not measured. No AI assistant was asked about the hotel in this audit, so nothing here shows whether ChatGPT, Gemini, Copilot or any other assistant recommends it.", False)
    s = log["summary"]
    return (f"Sampled on one assistant only: {log['platform']}, on {log['date'] or 'the audit date'}. It named the hotel in {s['appeared']} of {s['non_branded_answers']} answers to {s['prompts']} questions that do not "
            f"mention the hotel, and recommended it in {s['recommended']}. ChatGPT, Gemini and Copilot were NOT tested, so this is a sample, not a measure of AI visibility.", True)


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


def story(rep, H1):
    c = rep["consultant"]
    meta = rep.get("meta", {})
    hotel = meta.get("hotel", "the hotel")
    h = rep.get("headline") or headline_mod.build(rep)
    recs = {r["id"]: r for r in c["recommendations"]}
    top = [recs[i] for i in c["top_actions"] if recs[i]["kind"] == "fix"][:5]
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
    for s in _exec_sentences(c, h, top, hotel):
        out.append(para(s, "base"))
        out.append(Spacer(1, 2))
    out.append(para("Readiness and observed AI visibility are kept separate on purpose: a well-prepared hotel can still not be recommended, and a hotel can be recommended by chance while poorly prepared. "
                    "This report scores readiness. It does not claim to measure visibility.", "tiny"))
    out.append(para(f"The {len(top)} highest-priority actions" if top else "Highest-priority actions", "h3"))
    if top:
        out += R.bullets([cat(Markup(f"<b>{esc(short(r['title'], 95))}</b>"), f" - {r.get('owner') or r['team'].capitalize()}, {r['priority']} priority, effort {r['effort']} ({r['ref']})") for r in top])
    else:
        out.append(para("Nothing in this audit met the bar for a required fix.", "base"))

    # 2 -------------------------------------------------------------- discoverability and technical readiness
    out.append(H1("Discoverability and technical readiness"))
    prof = {p["key"]: p for p in c["profile"]}
    rows = [["Measure", "Score", "Evidence strength", "What drove it"]]
    for k in ("discoverability", "technical", "structured", "entity"):
        p = prof.get(k)
        if not p:
            continue
        ev = p.get("evidence") or {}
        sc = f"{p['score']} / 100" if p["assessed"] else "not assessed"
        rows.append([p["label"], sc, R.coloured((ev.get("level") or "-") + " evidence", LEVEL_COL.get(ev.get("level"), R.GREY)),
                     short("; ".join(p["drivers"][:2]), 140) + (f" ({ev['why']})" if ev.get("why") else "")])
    out.append(table(rows, [0.2, 0.12, 0.16, 0.52]))
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

    # 6 -------------------------------------------------------------- prioritised action plan
    out.append(R.PageBreak())
    out.append(H1("Prioritised action plan"))
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
                if rid not in phase and recs[rid]["kind"] == kind:
                    order.append(rid)
                    phase[rid] = label
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
    n_ver = sum(1 for r in c["recommendations"] if _conf(r) == "Verified finding")
    out.append(para("Confidence", "h3"))
    out.append(para(f"{n_ver} of the {len(c['recommendations'])} recommendations are verified findings (the evidence directly shows the issue on pages that were read). The rest are reasonable inferences: "
                    "they carry lower confidence because the crawl was limited, a page had sections that could not be read, the finding depends on a sample, or the benefit is an estimate. "
                    f"{len(c.get('dropped_recommendations') or [])} candidate recommendation(s) were withheld for lacking evidence or a specific action.", "base"))
    out.append(para("AI recommendation testing", "h3"))
    out.append(para(("Genuine tests were run on one assistant only (" + (rep.get("ai_sample") or {}).get("model", "Claude") + " with web search); every prompt and answer is logged in the appendix, and a checklist is provided to test the "
                     "other assistants by hand. No test of ChatGPT, Gemini or Copilot took place, so nothing here describes what they recommend. Observed AI visibility stays separate from the readiness score.")
                    if ai_sampled else "No test of any AI assistant took place in this audit, so observed AI visibility is not measured; a checklist in the appendix lets the hotel test by hand. Readiness is reported on its own.", "base"))
    out += R.bullets([f"The readiness score rests on {h['coverage_pct']:.0f}% of the full model and is a set-up indicator, not a measure of AI visibility.",
                      "Findings come from the hotel's own pages and public sources read during the audit; search results and open data vary between runs.",
                      "Nothing here guarantees that any AI assistant will recommend the hotel."])
    return out
