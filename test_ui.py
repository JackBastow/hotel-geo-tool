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
check("the nine top-level tabs are there (plus two nested in the AI check)", len(at.tabs) == 11, len(at.tabs))
labels = [t.label for t in at.tabs]
check("Tools tab present", "Tools" in labels, labels)
for want in ("Overview", "Identity & distribution", "Reviews & reputation", "Media & validation",
             "Traveller fit", "Social & local", "Website", "Gaps & method"):
    check(f"tab present: {want}", want in labels, labels)
text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
check("priority actions are shown", "Five priority actions" in text)
check("the 30-check table section is shown", "All 30 checks" in text)
check("the guest-review limitation is on the page", any("lawful, free, automated source" in (i.value or "") for i in at.info))
check("tables rendered (dataframes present)", len(at.dataframe) >= 10, len(at.dataframe))
check("the existing manual AI check still renders", "Check what AI assistants actually say" in " ".join(
    s.value for s in at.subheader) or "AI assistants" in text)

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
