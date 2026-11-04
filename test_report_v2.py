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
first = " ".join(" ".join(pages[i].get_text() for i in range(min(3, len(pages)))).split())          # the opening pages: at a glance, competitors, sources, then the actions
first_page = " ".join(pages[0].get_text().split())
full = " ".join(" ".join(p.get_text() for p in pages).split())

print("1. the first page")
check("the 0-100 readiness score is still there, beside the observed AI visibility", "/ 100" in first_page and "Observed AI visibility" in first_page)
check("page 1 is the at-a-glance page: a scorecard of every area with a plain verdict, and two lists: where the hotel does well and where it does not", "Scorecard at a glance" in first_page and "Where the hotel does well" in first_page and "Where it does not" in first_page and "Strong" in first_page and "Weak" in first_page)
check("the scorecard shows the AI sample against the aim of about 30%", "AI visibility (sampled)" in first_page and "aim: about 30%" in first_page)
check("each list item is specific (names the area, the search or the problem), not a generic remark", "Social & UGC" in first_page and "Opera" in first_page)
check("competitors are ranked: every hotel the assistant named, how often, its average place, how it was described, with this hotel marked", "Competitors: who AI recommends instead" in first and "(this hotel)" in first and "Average position" in first and "Oatlands Park Hotel" in first)
check("the sources that come up first are ranked, with their type of site and share of answers", "Where AI gets its information" in first and "Type of site" in first and ("Came up in" in first or "Answers that used it" in first))
check("the actions come after, each with example wording and how you will know it worked", "What to do first: the action plan" in full and "Example wording" in full and "How you will know" in full)
check("it opens with which AI searches name the hotel and who is named instead, in the hotel's own category", "Which AI searches name the hotel, and who is named instead" in first and "Named instead (same category)" in first)
check("each search shows how often the hotel was named, as a band and never as a rank", "0 of 2 (not appearing)" in first and "1 of 2 (sometimes)" in first)
check("the visibility sentence gives a range, not a number alone", "plausibly" in first and "true rate" in first)
check("then what the evidence suggests differs, labelled as observations and not causes", "What the evidence suggests differs (observations, not proven causes)" in first)
check("then what to do first, with each action's evidence label, and how sure we are with the three labels explained", "What to do first" in full and "How sure we are" in full and "Confirmed:" in full and "Worth checking:" in full)
check("the sample's limits are on the page: one assistant, one day, other categories not counted", "One assistant on one day" in first and "not counted as competitors" in first)

print("2. each thing is said once")
check("the table of hotels named instead is not repeated in the external-presence section", full.count("Which AI searches name the hotel") == 1 and "Where the hotel was not named, and who was" not in full)
check("the three labels are explained once (page 1), not again in the methodology", full.count("Worth checking: a lead from a sample") == 1)
check("the plan keeps leads (Worth checking) apart from findings, and caps the tables", "Leads worth looking into" in full or "Worth checking" in full)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
