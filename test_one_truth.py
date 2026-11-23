"""
One source of truth (code review, Nov 2026): every screen, PDF and stored summary shows the SAME "named by AI" figure for one check. Before this, the same check showed 20 of 26 on Start here
and 19 of 26 on the AI tab, 77% in the management PDF and 73% on the page.

The fixture adds what used to split the figures: a tracked prompt and a custom prompt (left out of some counts, not others) and an answer named only after the check against the
answer's own list of hotels. Then it reads the figure from every place a hotel or the operator can see it.
Run: python test_one_truth.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import backend
import dashboard_view
import glance
import progress
import report_model

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


rep = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
hotel = rep["meta"]["hotel"]
items = rep["ai_sample"]["items"]
base = copy.deepcopy(next(i for i in items if i["kind"] == "niche"))
items += [{**copy.deepcopy(base), "id": "t1", "qid": "t1", "source": "benchmark", "text": "A tracked prompt about hotels near the airport", "mentioned": True, "names_hotel": False},
          {**copy.deepcopy(base), "id": "c1", "qid": "c1", "kind": "custom", "text": "A custom prompt the hotel added", "mentioned": False, "names_hotel": False},
          {**copy.deepcopy(base), "id": "n9", "qid": "n9", "text": "A market prompt whose answer was matched only by its list of hotels", "mentioned": True, "reconciled": True, "names_hotel": False}]
report_model.apply(rep)
one = report_model.ai_counts(rep)
n, m, pct = one["named"], one["asked"], one["pct"]
print(f"the one count: {n} of {m} ({pct}%)")
old = rep["ai_sample"]["summary"]
check("(the fixture really would have split the old counts)", (old["generic_named"] + old["niche_named"], old["generic_asked"] + old["niche_asked"]) != (n, m))

print("1. the report and its own copies")
check("the model is in the report", rep["model"]["ai"]["named"] == n and rep["model"]["ai"]["asked"] == m)
sb = rep["ai_insights"]["scoreboard"]
check("the scoreboard carries it", sb["coverage_pct"] == pct and sb["named_all"] == n and sb["asked_all"] == m, sb)
me = next(r for r in rep["ai_insights"]["brand_ranking"]["rows"] if r["is_target"])
check("the hotel's line in the brand ranking carries it", (me["mentions"], me["of"], me["coverage_pct"]) == (n, m, pct), me)

print("2. the Overview and the management report")
card = re.sub(r"<[^>]+>", " ", dashboard_view.at_a_glance(rep))
check("'Is the hotel named?' card", f"{pct}%" in card and f"({n} of {m})" in card, card[:200])
tile = next(k for k in dashboard_view.kpis(rep, {}) if k["label"] == "Named by an AI assistant")
check("the 'Named by an AI assistant' tile", tile["value"] == str(pct) and tile["sub"].startswith(f"{n} of {m} "), tile)
check("the scorecard row", f"Named in {n} of {m} answers" in glance.scorecard_html(rep) and f"{pct}%" in glance.scorecard_html(rep))
try:
    import pymupdf
    import report_pdf
    pdf = " ".join(" ".join(p.get_text() for p in pymupdf.open(stream=report_pdf.build_pdf(copy.deepcopy(rep), "management"), filetype="pdf")).split())
    check("the management PDF", f"named the hotel in {n} of {m}" in pdf or f"Named in {n} of {m}" in pdf, re.findall(r"[Nn]amed[^.]{0,60}", pdf)[:4])
except ImportError:
    print("  (PyMuPDF not installed: the PDF text is not read here)")

print("3. what is stored for the check, and the screens built from it")
db = backend.open_store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db"))
key = backend.hotel_key(rep)
rid = db.save_run(copy.deepcopy(rep))
row = db.hotel_runs(key)[0]
check("the stored columns", (row["ai_named"], row["ai_asked"]) == (n, m), (row.get("ai_named"), row.get("ai_asked")))
check("Start here and the portal tiles (progress)", progress._cov(row) == (n, m), progress._cov(row))
ch = db.competitor_history(key)
me_line = next(r for r in ch["rows"] if r["is_target"])["points"][-1]
check("the AI visibility tab's line for the hotel", (me_line["mentions"], me_line["coverage_pct"]) == (n, pct), me_line)
check("a saved report read back carries the same model", db.get_report(rid)["model"]["ai"]["named"] == n)

print("4. checks saved before the one count existed")
conn = db._connect()
try:
    db._run(conn, "UPDATE runs SET ai_named = NULL, ai_asked = NULL WHERE id = ?", (rid,))
    conn.commit()
finally:
    conn.close()
check("are filled in from their saved report", db.backfill_ai_counts() == 1 and (db.hotel_runs(key)[0]["ai_named"], db.hotel_runs(key)[0]["ai_asked"]) == (n, m))

print("5. top priorities: one rule")
import start_here
cons = rep["consultant"]
first = report_model.priorities_of(cons)
by_id = {r["id"]: r for r in cons["recommendations"]}
check("(the fixture has top priorities)", len(first) >= 2, first)
check("they leave out what rests on uncertain evidence", all(by_id[i].get("confidence_label") != "Worth checking" for i in first))
check("the management report's top fixes are the model's", [r["id"] for r in glance.top_fixes(cons)] == first)
ordered, top_ids = dashboard_view._ordered(cons)
check("the Overview's 'Start here' list is the model's, in order", [r["id"] for r in ordered[:len(first)]] == first)
hid = db.create_hotel(hotel, rep["meta"]["website"], rep["meta"]["city"], key)
h = db.get_hotel(hid)
progress.sync(db, h, db.get_report(rid), rid)
acts = db.list_actions(hid)
lead = start_here._top_actions(acts, 1)
check("the hotel's Start here leads with the same action", lead and json.loads(lead[0]["rec_json"]).get("id") == first[0], (lead[0]["title"] if lead else None, by_id[first[0]]["title"]))

print("6. stable recommendation ids")
import ranking
r1 = ranking.fill_missing([{"title": "A recommendation added after the ranking", "source": "identity"}])[0]["id"]
r2 = ranking.fill_missing([{"title": "A recommendation added after the ranking", "source": "identity"}])[0]["id"]
check("a recommendation without an id gets the same one every time (not Python's per-start hash)", r1 == r2 and r1 == "R-" + __import__("hashlib").sha1(b"identity|A recommendation added after the ranking").hexdigest()[:10])

print("7. changes compare like with like")
db2 = backend.open_store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "c.db"))


def check_of(score, cats, tracked_named, tracked_texts, run_at):
    r = copy.deepcopy(rep)
    r["meta"]["run_at"] = run_at
    r["headline"]["score"] = score
    for c in r["scorecard"]["categories"]:
        c["assessed"] = c["key"] in cats
        c["score"] = 60 if c["key"] in cats else None
    base_i = next(i for i in r["ai_sample"]["items"] if i["kind"] == "niche")
    r["ai_sample"]["items"] = [i for i in r["ai_sample"]["items"] if i.get("source") != "benchmark"] + [
        {**copy.deepcopy(base_i), "id": f"b{k}", "qid": f"b{k}", "source": "benchmark", "text": t, "mentioned": k < tracked_named, "names_hotel": False} for k, t in enumerate(tracked_texts)]
    return r


T8 = [f"Tracked prompt {k} about airport hotels" for k in range(8)]
db2.save_run(check_of(40, {"website", "entity"}, 1, T8, "2026-10-01T05:00:00+00:00"))
db2.save_run(check_of(50, {"website", "entity", "otas"}, 1, T8, "2026-10-08T05:00:00+00:00"))
db2.save_run(check_of(55, {"website", "entity", "otas"}, 3, T8, "2026-10-15T05:00:00+00:00"))
hid2 = db2.create_hotel(hotel, rep["meta"]["website"], rep["meta"]["city"], key)
sm = progress.hotel_summary(db2, db2.get_hotel(hid2), list(reversed(db2.hotel_runs(key))))
check("the score change is counted from the first check that measured the same parts (50 -> 55, not 40 -> 55)", sm["first_score"] == 50 and sm["delta"] == 5 and "measured different parts" in sm["score_note"], (sm["first_score"], sm["delta"]))
check("the change since the last check uses the same tracked prompts", sm["cov_week"] == ((1, 8), (3, 8)) and sm["cov_basis"] == "tracked", sm["cov_week"])
check("1 of 8 then 3 of 8 is within sampling noise: not a change", report_model.ai_moved((1, 8), (3, 8)) == "same" and report_model.ai_moved((1, 20), (15, 20)) == "up")
db2.save_run(check_of(56, {"website", "entity", "otas"}, 4, [f"A different tracked prompt {k}" for k in range(8)], "2026-10-22T05:00:00+00:00"))
sm = progress.hotel_summary(db2, db2.get_hotel(hid2), list(reversed(db2.hotel_runs(key))))
check("a check with a different set of tracked prompts is not compared with earlier ones", sm["cov_week"] is None and sm["cov_change"] is None, (sm["cov_week"], sm["cov_change"]))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
