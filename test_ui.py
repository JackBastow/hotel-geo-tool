"""
Headless UI test of the whole results page (Streamlit AppTest): the tabs, the
report sections, and the failure paths. Run: python test_ui.py
"""
import copy
import json
import os
import warnings

warnings.filterwarnings("ignore")
from streamlit.testing.v1 import AppTest

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
rep = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))


def run(report, label):
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=90)
    at.session_state["fa_res"] = report
    at.run()
    return at


print("1. the full report renders")
at = run(rep, "full")
check("no exception", not at.exception, [e.message for e in at.exception])
labels = [t.label for t in at.tabs]
for want in ("Overview", "How AI sees your hotel", "Fix your website", "Beyond your website", "Scorecard", "Tools & method"):
    check(f"top-level tab present: {want}", want in labels, labels)
for want in ("Identity & distribution", "Reviews & reputation", "Media & validation", "Traveller fit", "Social & local"):
    check(f"'Beyond your website' sub-tab present: {want}", want in labels, labels)
text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
check("the AI-understanding statement leads the page", "AI currently understands this hotel as" in text)
check("the readiness profile is shown as separate measures", "Readiness, measure by measure" in text)
check("the headline metric is labelled readiness, never AI visibility",
      any(m.label == "AI discoverability readiness" for m in at.metric) and not any("AI visibility score" in m.label for m in at.metric), [m.label for m in at.metric])
check("the explanation says what was not measured", any("not measured" in c.value.lower() for c in at.caption) or "Not measured" in " ".join(m.value for m in at.markdown))
check("top actions are shown", "things most worth doing" in text)
check("fixes, opportunities, quick wins and the 30/60/90 plan are separate views",
      all(any(w in l for l in labels) for w in ("Other required fixes", "Commercial opportunities", "Quick wins", "30 / 60 / 90-day plan")), labels)
check("what is already working is shown", "already doing well" in text)
check("the unanswered-questions section is shown", "Questions AI may struggle to answer" in text)
check("the structured-data audit is shown", "Structured data" in text)
check("the 30-check method table is shown", "All 30 checks" in text)
check("recommendation cards use the Finding / Why / Action shape", "What we found." in text and "Why it matters." in text and "What to do." in text)
check("tables rendered (dataframes present)", len(at.dataframe) >= 8, len(at.dataframe))
check("no generic GEO claim leaks into the page", not any(p in text.lower() for p in ("boost your chatgpt", "guarantees better", "llms prefer")))

print("2. degraded runs")
bad = copy.deepcopy(rep)
bad["intel"] = {"error": "RuntimeError: boom"}
at2 = run(bad, "intel failed")
check("a failed wider analysis does not crash the page", not at2.exception, [e.message for e in at2.exception])
check("a warning says what failed", any("wider discovery and reputation analysis failed" in w.value for w in at2.warning))
old = copy.deepcopy(rep)
old.pop("intel", None)
at3 = run(old, "old report format")
check("a report from before this feature (no 'intel') still renders", not at3.exception,
      [e.message for e in at3.exception])
nocons = copy.deepcopy(rep)
nocons.pop("consultant", None)
at5 = run(nocons, "no consultant")
check("a report from before the consultant layer still renders", not at5.exception, [e.message for e in at5.exception])
errcons = copy.deepcopy(rep)
errcons["consultant"] = {"error": "RuntimeError: boom"}
at6 = run(errcons, "consultant failed")
check("a failed consultant analysis does not crash the page", not at6.exception, [e.message for e in at6.exception])
import consultant  # noqa: E402
unread = copy.deepcopy(rep)
unread["consultant"] = consultant.analyse(
    own_pages=[], pages_meta=[{"url": "https://x.com/p%d/" % i, "ok": False, "reason": "request failed or timed out", "status": None, "title": ""} for i in range(10)],
    base="https://x.com/", hotel="X Hotel", city="Leeds", location={}, guest={"questions": [], "conflicts": [], "own_facts_node": {}},
    site={"robots": {"present": False}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
at7 = run(unread, "unreadable site")
check("an unreadable site renders, with a clear error banner", not at7.exception and any("Read 0 of 10 pages" in e.value for e in at7.error),
      [e.message for e in at7.exception])
nothing = copy.deepcopy(rep)
m = nothing["intel"]["media"]
for k in ("articles", "rejected", "unread", "targets", "angles", "comparison", "awards", "ratings", "roundups", "clusters"):
    m[k] = []
m["themes"] = {"themes": [], "disagreements": [], "own_only": [], "independent_only": []}
m["summary"].update(articles=0, stories=0, publishers=0, independent_publishers=0, duplicates_removed=0,
                    by_type={}, by_freshness={}, by_language={}, recent_independent=0)
nothing["intel"]["identity"]["footprint"] = []
at4 = run(nothing, "no coverage")
check("a hotel with no coverage renders without error", not at4.exception, [e.message for e in at4.exception])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
