"""
The monthly pack: one Excel workbook of every audit run in a period, shaped to be read by a person AND fed to a dashboard.

Sheets
  Read me         what each sheet holds, and the caveats that apply to every number
  Hotels          one row per audit: scores, AI visibility, reviews, speed, top 3 actions, and the change since that hotel's previous run
  Metrics         the same numbers in 'tidy' form (one row per hotel, run and metric) - the easiest shape to chart or pivot
  Scores and why  every score with its status, how strong the evidence is, and a one-line reason
  AI rankings     question by question: was the hotel named, where in the list, and who was named instead
  AI competitors  the hotels the assistant named most for each audited hotel (town-wide and niche markets)
  AI why          the hypotheses for why a hotel may not be named (hypotheses, not causes)
  Top 3 actions   the three most worthwhile things for each hotel, with why and what to do
  Sources         the sites the assistant leaned on, and whether the hotel was found there

Everything comes from the saved report of each run. Nothing here is re-measured.
"""

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ai_insights import sentiment_label

CATEGORY_ORDER = [("ai_visibility", "AI Visibility"), ("otas", "OTAs & Travel Platforms"), ("reviews", "Reviews & Reputation"), ("editorial", "Editorial & Blogs"),
                  ("website", "Website & Technical"), ("social", "Social & UGC"), ("entity", "Entity Consistency")]
MEASURE_ORDER = [("discoverability", "Discoverability"), ("intent", "Traveller-intent coverage"), ("entity", "Entity clarity"), ("technical", "Technical accessibility"),
                 ("content", "Content completeness"), ("structured", "Structured data"), ("location", "Location relevance"), ("authority", "External authority / evidence")]
KIND_LABEL = {"generic": "Town-wide", "niche": "Niche market", "direct": "About the hotel"}

README = [
    ("Hotel AI Discoverability Audit: monthly pack", True),
    ("One row per audit run. If a hotel was audited more than once in the period, every run is here and 'Latest in month' marks the last one; use that for dashboards.", False),
    ("", False),
    ("Sheets", True),
    ("Hotels: one row per audit. Scores, AI visibility, reviews, speed, the top 3 actions, and the change since that hotel's latest run in the previous month(s).", False),
    ("Metrics: the same numbers, one row per hotel/run/metric. Best for pivot tables and dashboards.", False),
    ("Scores and why: every score with its status, how strong the evidence behind it is (high / medium / low) and a brief reason.", False),
    ("AI rankings: for each question put to the AI assistant, whether the hotel was named, its position in the list, and the hotels named instead.", False),
    ("AI brand ranking: for each audit, every hotel the assistant named across all its answers with coverage %, average position and net sentiment; 'Place in top table' is filled for the hotel and the five named most. One row per hotel per run, so it pivots by month into a competitors-over-time view.", False),
    ("AI competitors: the hotels the assistant named most, for each audited hotel, separately for town-wide and niche-market questions.", False),
    ("AI citations: the exact pages the assistant cited or searched, how many times, and whether the page title or quoted passage names the hotel or a competitor.", False),
    ("AI why: hypotheses for why a hotel may not have been named. They are hypotheses to check, not causes.", False),
    ("Top 3 actions: the three most worthwhile things for each hotel, with why it matters and what to do.", False),
    ("Sources: the websites the assistant relied on and whether the hotel was found on each.", False),
    ("", False),
    ("How to read the numbers", True),
    ("Readiness (0-100) is an indicator of how well the hotel is set up, on the factors that could be assessed; read it with Coverage %. It is not a measure of how visible the hotel is to AI. It is blank when too little could be measured.", False),
    ("AI visibility figures come from a SAMPLE: one AI model (with web search) asked a handful of ordinary traveller questions on one day. Answers change between runs and between assistants. Look for a sustained move over several months, not a single reading.", False),
    ("'Town-wide' questions ask for hotels in the whole town. 'Niche market' questions are narrower (near an airport, in a district, at a price level, for a feature the hotel is known for) and are written from facts the audit holds about the hotel.", False),
    ("'Share of hotel names %' is the hotel's part of all the hotel names the assistant gave across the town-wide questions.", False),
    ("'Coverage %' is the share of ALL the answers (town-wide and niche) that named the hotel. Town-wide and niche questions are each asked more than once, so one odd answer does not decide it; the 'Answers asked' column says how many.", False),
    ("'Net sentiment' is % positive minus % negative among the answers that named the hotel (-100 to +100), an AI's reading of how each answer spoke of it. Blank when the hotel was never named.", False),
    ("In AI citations, 'not seen' means the page title and the short passage the assistant quoted do not name the hotel; we do not read those pages, so it is not a statement that the page leaves the hotel out.", False),
    ("'Listing differences' counts facts (check-in and check-out time, star rating, telephone) a travel site shows that differ from the hotel's own site, read from passages quoted in public search results. It is a list of things to check, not proof the listing is wrong; blank means no listing was quoted.", False),
    ("'Reviews in uploaded export' and the two columns after it come from a review export the hotel uploaded to the audit, for that file only; blank means none was uploaded.", False),
    ("Reviews figures are replies SEEN on reviews EXAMINED in public search results: a small sample, not the hotel's reply rate.", False),
    ("Blank cells mean not assessed or not available, never zero.", False),
]


def _clip(s, n=300):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "..."


def _pct(n, d):
    return None if n is None or not d else round(100 * n / d)


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _yn(v):
    return "" if v is None else ("Yes" if v else "No")


def _delta(new, old, nd=1):
    a, b = _num(new), _num(old)
    return None if a is None or b is None else round(a - b, nd)


# ---------------------------------------------------------------- per-run facts

def top_actions(rep, n=3):
    c = rep.get("consultant") or {}
    by_id = {r.get("id"): r for r in c.get("recommendations", [])}
    return [by_id[i] for i in (c.get("top_actions") or [])[:n] if i in by_id]


def category_rows(rep):
    return {c["key"]: c for c in (rep.get("scorecard") or {}).get("categories", [])}


def category_why(c):
    if not c.get("assessed"):
        return _clip(c.get("detail"), 260)
    ev = [e for e in (c.get("evidence") or []) if e]
    return _clip("; ".join(ev[:3]) or c.get("detail"), 300)


def run_facts(row, rep, prev):
    """Everything one run contributes, as plain values."""
    ai = rep.get("ai_sample") or {}
    s = ai.get("summary") or {}
    ins = rep.get("ai_insights") or {}
    sb = ins.get("scoreboard") or {}
    rv = (rep.get("review_snapshot") or {}).get("summary") or {}
    ps = ((rep.get("web_signals") or {}).get("pagespeed") or {}).get("scores") or {}
    cats = category_rows(rep)
    head = rep.get("headline") or {}
    acts = top_actions(rep)
    f = {
        "month": str(row["run_at"])[:7], "run_id": row["id"], "run_at": str(row["run_at"])[:16].replace("T", " "), "hotel": row["hotel"] or row["hotel_key"], "city": row["city"],
        "website": row["website"], "hotel_key": row["hotel_key"],
        "readiness": _num(head.get("score")), "status": head.get("status") or "", "coverage": _num(head.get("coverage_pct")),
        "pages": f"{row['pages_read']}/{row['pages_attempted']}" if row.get("pages_attempted") else "", "read_via": row.get("read_via") or "",
        "cats": {k: (cats[k].get("score") if k in cats and cats[k].get("assessed") else None) for k, _ in CATEGORY_ORDER},
        "town_named": s.get("generic_named"), "town_asked": s.get("generic_asked"), "town_pct": _pct(s.get("generic_named"), s.get("generic_asked")),
        "niche_named": s.get("niche_named"), "niche_asked": s.get("niche_asked"), "niche_pct": _pct(s.get("niche_named"), s.get("niche_asked")),
        "cov_ai": sb.get("coverage_pct"), "sentiment": sb.get("sentiment"), "brand_place": sb.get("place"), "answers": sb.get("asked_all") or s.get("asked"),
        "repeats": sb.get("repeats") or s.get("repeats"),
        "share": _num(sb.get("share")), "place": sb.get("rank_in_table"), "table_size": sb.get("table_size"), "top_competitor": sb.get("top_competitor") or "",
        "known": None if s.get("direct_known") is None else bool(s.get("direct_known")), "own_cited": None if not s else bool(s.get("own_site_cited")),
        "rv_examined": rv.get("examined"), "rv_replied": rv.get("replied"), "rv_neg": rv.get("negative_examined"), "rv_neg_replied": rv.get("negative_replied"),
        "speed": ps.get("performance"), "a11y": ps.get("accessibility"),
        "pk_n": (rep.get("review_pack") or {}).get("reviews"), "pk_rate": (rep.get("review_pack") or {}).get("reply_rate"), "pk_unans": (rep.get("review_pack") or {}).get("critical_unanswered"),
        "lc_diff": ((rep.get("listing_checks") or {}).get("summary") or {}).get("differs"), "lc_former": ((rep.get("listing_checks") or {}).get("summary") or {}).get("former_name"), "recs": row.get("recs_total"),
        "acts": [a.get("short_title") or a.get("title") for a in acts], "cost": row.get("ai_cost_usd"),
    }
    # profile measures
    f["measures"] = {p["key"]: p for p in (rep.get("consultant") or {}).get("profile", [])}
    if prev:
        f.update(prev_date=str(prev["run_at"])[:10], d_readiness=_delta(row.get("headline_score"), prev.get("headline_score")),
                 d_share=_delta(row.get("ai_share"), prev.get("ai_share")),
                 d_cov=_delta(row.get("ai_coverage_pct"), prev.get("ai_coverage_pct"), 0), d_sent=_delta(row.get("ai_sentiment"), prev.get("ai_sentiment"), 0),
                 d_town=_delta(_pct(row.get("ai_generic_named"), row.get("ai_generic_asked")), _pct(prev.get("ai_generic_named"), prev.get("ai_generic_asked")), 0),
                 d_niche=_delta(_pct(row.get("ai_niche_named"), row.get("ai_niche_asked")), _pct(prev.get("ai_niche_named"), prev.get("ai_niche_asked")), 0))
        pc = {}
        try:
            import json
            pc = json.loads(prev.get("cat_scores") or "{}")
        except ValueError:
            pass
        f["d_ai_score"] = _delta(f["cats"].get("ai_visibility"), pc.get("ai_visibility"), 0)
    else:
        f.update(prev_date=None, d_readiness=None, d_share=None, d_cov=None, d_sent=None, d_town=None, d_niche=None, d_ai_score=None)
    return f


# ------------------------------------------------------------------ workbook

def _sheet(wb, title, headers, rows, widths=None, wrap=()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="DDE7F0")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(["" if v is None else v for v in r])
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    for i, h in enumerate(headers, 1):
        w = (widths or {}).get(h) or min(max(len(h) + 2, 10), 24)
        ws.column_dimensions[get_column_letter(i)].width = w
    for col in wrap:
        idx = headers.index(col) + 1
        for r in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            for c in r:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    return ws


def build_workbook(runs, all_rows=None):
    """
    runs: list of (summary row dict, report dict) to include. all_rows: every summary row (any period) so each run's PREVIOUS run can be found.
    -> .xlsx bytes.
    """
    all_rows = all_rows or [r for r, _ in runs]
    by_key = {}
    for r in all_rows:
        by_key.setdefault(r["hotel_key"], []).append(r)
    for v in by_key.values():
        v.sort(key=lambda r: (r["run_at"], r["id"]))

    def previous(row):
        """The hotel's latest run in an EARLIER month (so a re-run within the month is not compared with itself)."""
        month = str(row["run_at"])[:7]
        earlier = [r for r in by_key.get(row["hotel_key"], []) if str(r["run_at"])[:7] < month]
        return earlier[-1] if earlier else None

    latest = {}
    for row, _ in runs:
        k = (row["hotel_key"], str(row["run_at"])[:7])
        if k not in latest or (row["run_at"], row["id"]) > latest[k]:
            latest[k] = (row["run_at"], row["id"])

    facts = []
    for row, rep in sorted(runs, key=lambda x: (x[0]["hotel"] or x[0]["hotel_key"], x[0]["run_at"])):
        f = run_facts(row, rep, previous(row))
        f["latest"] = latest[(row["hotel_key"], str(row["run_at"])[:7])] == (row["run_at"], row["id"])
        f["rep"], f["row"] = rep, row
        facts.append(f)

    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    for text, bold in README:
        ws.append([text])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=bold, size=13 if bold and ws.max_row == 1 else 11)
        ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 130

    # ---- Hotels
    cat_heads = [f"{label} (score)" for _, label in CATEGORY_ORDER]
    heads = (["Month", "Run id", "Run date", "Hotel", "City", "Website", "Latest in month", "Readiness (0-100)", "Headline", "Coverage %", "Pages read", "Read via"] + cat_heads +
             ["Named, town-wide", "Asked, town-wide", "Named % town-wide", "Named, niche", "Asked, niche", "Named % niche", "Share of hotel names %", "Place in competitor table",
              "Hotels in table", "Top competitor", "Coverage % (all answers)", "Net sentiment", "Place in brand ranking", "Answers asked", "Repeats per question", "Known when asked directly", "Own site cited", "Reviews examined", "Hotel replied", "Critical reviews examined",
              "Critical replied", "Mobile speed", "Accessibility", "Listing differences", "Former name on listings", "Reviews in uploaded export", "Reply rate % (export)", "Critical reviews unanswered (export)", "Recommendations in plan", "Top action 1", "Top action 2", "Top action 3", "AI cost $",
              "Previous run", "Readiness change", "AI Visibility score change", "Share of names change (pts)", "Named % town-wide change", "Named % niche change", "Coverage change (pts)", "Net sentiment change"])
    rows = []
    for f in facts:
        a = f["acts"] + [None] * (3 - len(f["acts"]))
        rows.append([f["month"], f["run_id"], f["run_at"], f["hotel"], f["city"], f["website"], _yn(f["latest"]), f["readiness"], f["status"], f["coverage"], f["pages"], f["read_via"]]
                    + [f["cats"][k] for k, _ in CATEGORY_ORDER] +
                    [f["town_named"], f["town_asked"], f["town_pct"], f["niche_named"], f["niche_asked"], f["niche_pct"], f["share"], f["place"], f["table_size"],
                     f["top_competitor"], f["cov_ai"], f["sentiment"], f["brand_place"], f["answers"], f["repeats"], _yn(f["known"]), _yn(f["own_cited"]), f["rv_examined"], f["rv_replied"], f["rv_neg"], f["rv_neg_replied"], f["speed"], f["a11y"], f["lc_diff"], f["lc_former"], f["pk_n"], f["pk_rate"], f["pk_unans"],
                     f["recs"], a[0], a[1], a[2], f["cost"], f["prev_date"], f["d_readiness"], f["d_ai_score"], f["d_share"], f["d_town"], f["d_niche"], f["d_cov"], f["d_sent"]])
    _sheet(wb, "Hotels", heads, rows, {"Hotel": 30, "Website": 32, "Top action 1": 48, "Top action 2": 48, "Top action 3": 48, "Top competitor": 28, "Run date": 17}, wrap=("Top action 1", "Top action 2", "Top action 3"))

    # ---- Metrics (tidy)
    m = []

    def metric(f, group, name, value, unit=""):
        if value is not None and value != "":
            m.append([f["month"], f["run_id"], f["run_at"], f["hotel"], f["city"], f["hotel_key"], group, name, value, unit])
    for f in facts:
        metric(f, "Overall", "Readiness", f["readiness"], "0-100")
        metric(f, "Overall", "Coverage", f["coverage"], "%")
        for k, label in CATEGORY_ORDER:
            metric(f, "Scorecard category", label, f["cats"][k], "0-100")
        for k, label in MEASURE_ORDER:
            p = f["measures"].get(k)
            metric(f, "Readiness measure", label, None if not p or not p.get("assessed") else p.get("score"), "0-100")
        metric(f, "AI visibility", "Named % town-wide", f["town_pct"], "%")
        metric(f, "AI visibility", "Named % niche markets", f["niche_pct"], "%")
        metric(f, "AI visibility", "Share of hotel names", f["share"], "%")
        metric(f, "AI visibility", "Place in competitor table", f["place"], "rank")
        metric(f, "AI visibility", "Coverage % all answers", f["cov_ai"], "%")
        metric(f, "AI visibility", "Net sentiment", f["sentiment"], "-100 to +100")
        metric(f, "AI visibility", "Place in brand ranking", f["brand_place"], "rank")
        metric(f, "AI visibility", "Known when asked directly", None if f["known"] is None else int(f["known"]), "0/1")
        metric(f, "AI visibility", "Own site cited", None if f["own_cited"] is None else int(f["own_cited"]), "0/1")
        metric(f, "Reviews", "Reviews examined", f["rv_examined"], "count")
        metric(f, "Reviews", "Hotel replied", f["rv_replied"], "count")
        metric(f, "Reviews", "Critical reviews replied", f["rv_neg_replied"], "count")
        metric(f, "Web", "Mobile speed", f["speed"], "0-100")
        metric(f, "Web", "Accessibility", f["a11y"], "0-100")
        metric(f, "Reviews (export)", "Reviews in the export", f["pk_n"], "count")
        metric(f, "Reviews (export)", "Reply rate", f["pk_rate"], "%")
        metric(f, "Reviews (export)", "Critical reviews unanswered", f["pk_unans"], "count")
        metric(f, "Listings", "Facts differing from the website", f["lc_diff"], "count")
        metric(f, "Listings", "Listings showing a former name", f["lc_former"], "count")
    _sheet(wb, "Metrics", ["Month", "Run id", "Run date", "Hotel", "City", "Hotel key", "Group", "Metric", "Value", "Unit"], m, {"Hotel": 30, "Metric": 30, "Hotel key": 34, "Group": 20})

    # ---- Scores and why
    sw = []
    for f in facts:
        rep = f["rep"]
        head = rep.get("headline") or {}
        base = [f["month"], f["run_id"], f["hotel"], f["city"]]
        sw.append(base + ["Overall readiness", "Readiness", f["readiness"], head.get("status", ""), "", _clip(head.get("explanation"), 320)])
        cats = category_rows(rep)
        for k, label in CATEGORY_ORDER:
            c = cats.get(k)
            if not c:
                continue
            sw.append(base + ["Scorecard category", label, c.get("score") if c.get("assessed") else None,
                              "partial" if c.get("partial") else ("assessed" if c.get("assessed") else "not assessed"), c.get("evidence_level") or "", category_why(c)])
        for k, label in MEASURE_ORDER:
            p = f["measures"].get(k)
            if p:
                sw.append(base + ["Readiness measure", label, p.get("score") if p.get("assessed") else None, p.get("band") or "", (p.get("evidence") or {}).get("level", ""),
                                  _clip("; ".join(p.get("drivers") or []), 300)])
    _sheet(wb, "Scores and why", ["Month", "Run id", "Hotel", "City", "Type", "Name", "Score", "Status / band", "Evidence strength", "Why"], sw,
           {"Hotel": 30, "Name": 30, "Why": 90, "Type": 20}, wrap=("Why",))

    # ---- AI rankings
    rk = []
    for f in facts:
        rep, ins, ai = f["rep"], f["rep"].get("ai_insights") or {}, f["rep"].get("ai_sample") or {}
        matrix = ins.get("matrix") or [{"id": i["id"], "kind": i["kind"], "question": i["text"], "hotel_named": i.get("mentioned"), "position": i.get("position"),
                                         "angle": i.get("angle"), "why": i.get("why"), "hotels_named": []} for i in ai.get("items", [])]
        for q in matrix:
            named = q.get("hotel_named") if q["kind"] != "direct" else None
            of = q.get("of")
            rk.append([f["month"], f["run_id"], f["hotel"], f["city"], KIND_LABEL.get(q["kind"], q["kind"]), q.get("angle") or "", q["question"], _clip(q.get("why"), 200),
                       _yn(named), (f"{q['named']} of {of}" if of and q["kind"] != "direct" else None), q.get("position"), ", ".join(q.get("hotels_named") or [])])
    _sheet(wb, "AI rankings", ["Month", "Run id", "Hotel", "City", "Question type", "Market", "Question asked", "Why we asked it", "Hotel named", "Named in answers", "Position in list", "Hotels named"],
           rk, {"Hotel": 30, "Question asked": 60, "Why we asked it": 50, "Hotels named": 60, "Question type": 16, "Named in answers": 16}, wrap=("Question asked", "Why we asked it", "Hotels named"))

    # ---- AI brand ranking (long form: one row per hotel per run)
    bk = []
    for f in facts:
        br = (f["rep"].get("ai_insights") or {}).get("brand_ranking") or {}
        top_names = {r["name"]: r.get("place") for r in br.get("rows", [])}
        for r in (br.get("all") or br.get("rows") or [])[:25]:
            bk.append([f["month"], f["run_id"], f["hotel"], f["city"], ("THIS HOTEL: " if r.get("is_target") else "") + r["name"], _yn(bool(r.get("is_target"))), top_names.get(r["name"]),
                       r.get("mentions"), r.get("of"), r.get("coverage_pct"), r.get("avg_rank"), r.get("sentiment"), sentiment_label(r.get("sentiment")),
                       r.get("positive"), r.get("neutral"), r.get("negative")])
    _sheet(wb, "AI brand ranking", ["Month", "Run id", "Hotel", "City", "Hotel named by the assistant", "This hotel", "Place in top table", "Named in answers", "Of answers", "Coverage %",
                                    "Average position", "Net sentiment", "Sentiment", "Positive", "Neutral", "Negative"],
           bk, {"Hotel": 30, "Hotel named by the assistant": 36, "Place in top table": 12})

    # ---- AI competitors
    cp = []
    for f in facts:
        ins = f["rep"].get("ai_insights") or {}
        for label, lb in (("Town-wide", ins.get("leaderboard")), ("Niche market", (ins.get("niche") or {}).get("leaderboard"))):
            for r in ((lb or {}).get("rows") or [])[:12]:
                cp.append([f["month"], f["run_id"], f["hotel"], f["city"], label, ("THIS HOTEL: " if r.get("is_target") else "") + r["name"], r["mentions"], r["of"], r["share"],
                           r.get("avg_rank"), _clip("; ".join(r.get("reasons") or []), 200)])
    _sheet(wb, "AI competitors", ["Month", "Run id", "Hotel", "City", "List", "Hotel named by the assistant", "Named in", "Of questions", "Share of names %", "Average position", "Reason given"],
           cp, {"Hotel": 30, "Hotel named by the assistant": 36, "Reason given": 60}, wrap=("Reason given",))

    # ---- AI citations (pages)
    ct = []
    for f in facts:
        for x in ((f["rep"].get("ai_insights") or {}).get("pages") or [])[:25]:
            ct.append([f["month"], f["run_id"], f["hotel"], f["city"], x["url"], x["domain"], _clip(x.get("title"), 120), x.get("cited"), x.get("questions"),
                       "Yes" if x.get("names_hotel") else "Not seen", x.get("names_competitor") or "Not seen", _yn(bool(x.get("own_site"))), _clip(x.get("passage"), 200)])
    _sheet(wb, "AI citations", ["Month", "Run id", "Hotel", "City", "Page", "Site", "Title", "Times cited", "Used in questions", "Names the hotel", "Names a competitor", "Own site",
                                "Passage the assistant quoted"], ct, {"Hotel": 30, "Page": 60, "Site": 24, "Title": 40, "Passage the assistant quoted": 60}, wrap=("Passage the assistant quoted",))

    # ---- AI why
    wy = []
    for f in facts:
        exp = (f["rep"].get("ai_insights") or {}).get("explanation") or {}
        if exp.get("summary"):
            wy.append([f["month"], f["run_id"], f["hotel"], f["city"], "Summary", _clip(exp["summary"], 500), "", ""])
        for h in exp.get("hypotheses") or []:
            wy.append([f["month"], f["run_id"], f["hotel"], f["city"], "Hypothesis", _clip(h["text"], 400), ", ".join(h.get("evidence") or []), _clip(h.get("action"), 300)])
    _sheet(wb, "AI why", ["Month", "Run id", "Hotel", "City", "Type", "Text (a hypothesis to check, not a cause)", "Evidence ids", "Worth checking"], wy,
           {"Hotel": 30, "Text (a hypothesis to check, not a cause)": 80, "Worth checking": 60}, wrap=("Text (a hypothesis to check, not a cause)", "Worth checking"))

    # ---- Top 3 actions
    ta = []
    for f in facts:
        for i, a in enumerate(top_actions(f["rep"]), 1):
            ta.append([f["month"], f["run_id"], f["hotel"], f["city"], i, a.get("short_title") or a.get("title"), a.get("priority"), a.get("effort"), a.get("team"),
                       a.get("confidence"), _clip(a.get("why"), 320), _clip(a.get("action"), 320), a.get("ref") or a.get("id")])
    _sheet(wb, "Top 3 actions", ["Month", "Run id", "Hotel", "City", "Rank", "Action", "Priority", "Effort", "Owner", "Confidence", "Why it matters", "What to do", "Reference"], ta,
           {"Hotel": 30, "Action": 50, "Why it matters": 70, "What to do": 70, "Confidence": 24}, wrap=("Action", "Why it matters", "What to do"))

    # ---- Sources
    sr = []
    for f in facts:
        for s in ((f["rep"].get("ai_insights") or {}).get("sources") or [])[:12]:
            sr.append([f["month"], f["run_id"], f["hotel"], f["city"], s["domain"], s["kind"], s["answers"], {True: "Yes", False: "No", None: "Not checked"}[s["hotel_evidenced"]]])
    _sheet(wb, "Sources", ["Month", "Run id", "Hotel", "City", "Site the assistant used", "Type", "Used in answers", "Hotel found there"], sr, {"Hotel": 30, "Site the assistant used": 34, "Type": 28})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(start, end):
    return f"hotel-audit-pack-{start}.xlsx" if start == end else f"hotel-audit-pack-{start}-to-{end}.xlsx"
