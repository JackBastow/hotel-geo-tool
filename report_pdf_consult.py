"""
PDF sections for the consultant report. Imported lazily by report_pdf.build_story
(it uses report_pdf's table and text helpers, so it must load after them).
"""

from reportlab.platypus import KeepTogether, PageBreak, Preformatted, Spacer

import report_pdf as R
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
    return urlparse(u or "").path or "/"


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


def rec_block(r):
    """One recommendation: Finding / Why / Evidence / Action / Where / Add / Example / Priority / Effort."""
    head = cat(Markup(f"<b>{esc(r['title'])}</b>"))
    meta = cat(R.coloured(r["priority"].upper() + " priority", PRI_COL[r["priority"]]), f" - effort {r['effort']} - team: {r['team']}")
    rows = [[head, meta], ["What we found", r["finding"]], ["Why it matters", r["why"]]]
    if r["evidence"]:
        rows.append(["Evidence", _ev(r["evidence"])])
    rows.append(["What to do", r["action"]])
    p = r.get("page")
    if p and (p.get("url") or p.get("label")):
        rows.append(["Where", link(p["url"], p["label"]) if p.get("url") else p["label"]])
    if r.get("additions"):
        rows.append(["Add", _bullets(r["additions"][:10])])
    rows.append(["Confidence", r["confidence"]])
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
        out.append(para("What the hotel is already doing well", "h2"))
        out += R.bullets([w["point"] for w in c["working"]])
    return out


def sections(c, H1):
    """The dedicated consultant sections, in reading order."""
    recs = {r["id"]: r for r in c["recommendations"]}
    out = []
    u = c["understanding"]

    # ---- how AI understands the hotel
    out += [PageBreak(), H1("How AI understands this hotel"),
            para("What a machine could learn from the hotel's own pages, and which traveller searches that content supports. Built only from wording "
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
        out.append(para("Nothing important is unclear: the common traveller questions are answered on the pages read.", "base"))
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
        out.append(KeepTogether([table(rows, [0.2, 0.8], header=False, zebra=False)]))
        if q.get("example"):
            out.append(Preformatted("\n".join(R._wrap_code(R.clean(q["example"])).splitlines()[:10]), R.S["code"]))
        out.append(Spacer(1, 5))

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
    sd = c["structured"]
    out.append(para("Structured data: what it says, not just whether it exists", "h2"))
    rows = [["Item", "Status", "Detail", "Advice"]]
    for i in sd["items"]:
        rows.append([i["item"] + (" (optional)" if i["optional"] else ""), R.coloured(SD_LABEL[i["status"]], SD_COL[i["status"]]), i["detail"], i["advice"]])
    out.append(table(rows, [0.2, 0.13, 0.37, 0.3]))
    out.append(para(sd["caution"], "note"))

    # ---- action plan
    out += [PageBreak(), H1("Action plan"),
            para("Every recommendation below was generated from a specific finding and shows its evidence. Priority reflects what travellers can see "
                 "and the effort involved; the confidence label separates established good practice from reasonable inference and experiment. "
                 "None guarantees that any AI assistant will recommend the hotel.", "muted")]
    done = set()
    for label, ids in (("Top actions", c["top_actions"]), ("Quick wins", c["quick_wins"])):
        out.append(para(label, "h2"))
        for rid in ids:
            out += rec_block(recs[rid])
            done.add(rid)
    rest = [r for r in c["recommendations"] if r["id"] not in done]
    if rest:
        out.append(para("All other recommendations", "h2"))
        for cat_, (title, _q) in BUCKET.items():
            rs = [r for r in rest if r["category"] == cat_]
            if rs:
                out.append(para(title, "h3"))
                for r in rs:
                    out += rec_block(r)
    return out
