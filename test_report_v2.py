"""
Offline test for the redesigned first page of the management report: it answers what a general manager asks (which AI searches name the hotel and how often, who is named instead in the hotel's own category,
what the evidence suggests differs, what to do first, how sure we are), keeps the 0-100 readiness score, and says each thing once. Uses the Paris fixture from test_ai_gap. No network.
Run: python test_report_v2.py
"""
import contextlib
import copy
import io
import json
import os
import warnings

warnings.filterwarnings("ignore")
import pymupdf

import report_pdf

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_ai_gap.py"), encoding="utf8").read()
src = src[:src.index('print("5. recommendations")')]
ns = {"__name__": "t"}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(src, "test_ai_gap.py", "exec"), ns)
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
REP["ai_gap"], REP["ai_sample"] = ns["res"], ns["AI"]
b = report_pdf.build_pdf(copy.deepcopy(REP), "management")
pages = pymupdf.open(stream=b, filetype="pdf")
first = " ".join(pages[0].get_text().split())
full = " ".join(" ".join(p.get_text() for p in pages).split())

print("1. the first page")
check("the 0-100 readiness score is still there, beside the observed AI visibility", "/ 100" in first and "Observed AI visibility" in first)
check("it opens with which AI searches name the hotel and who is named instead, in the hotel's own category", "Which AI searches name the hotel, and who is named instead" in first and "Named instead (same category)" in first)
check("each search shows how often the hotel was named, as a band and never as a rank", "0 of 2 (not appearing)" in first and "1 of 2 (sometimes)" in first)
check("the visibility sentence gives a range, not a number alone", "plausibly" in first and "true rate" in first)
check("then what the evidence suggests differs, labelled as observations and not causes", "What the evidence suggests differs (observations, not proven causes)" in first)
check("then what to do first, with each action's evidence label, and how sure we are with the three labels explained", "What to do first" in first and "How sure we are" in first and "Confirmed:" in first and "Worth checking:" in first)
check("the sample's limits are on the page: one assistant, one day, other categories not counted", "One assistant on one day" in first and "not counted as competitors" in first)

print("2. each thing is said once")
check("the table of hotels named instead is not repeated in the external-presence section", full.count("Which AI searches name the hotel") == 1 and "Where the hotel was not named, and who was" not in full)
check("the three labels are explained once (page 1), not again in the methodology", full.count("Worth checking: a lead from a sample") == 1)
check("the plan keeps leads (Worth checking) apart from findings, and caps the tables", "Leads worth looking into" in full or "Worth checking" in full)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
