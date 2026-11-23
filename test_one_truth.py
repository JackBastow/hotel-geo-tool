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

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
