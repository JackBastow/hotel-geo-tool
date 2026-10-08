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

check("the crawler-access card is shown, with its plain-English AI-crawler summary", "How crawlers and phones meet the website" in text and "deliberate choice about content use" in text)
check("Common Crawl, llms.txt and PageSpeed each get their own box", all(w in text for w in ("Common Crawl (public web archive", "llms.txt", "Google PageSpeed Insights")))
check("a refused crawler is flagged, and the card says presence/absence is not proof of AI knowledge",
      any("forbidden" in w.value for w in at.warning) and "not evidence that any AI model knows" in " ".join(c.value for c in at.caption))
check("the four PageSpeed scores are shown as metrics", {"Performance", "Accessibility", "SEO", "Best practice"} <= {m.label for m in at.metric}, [m.label for m in at.metric])

_src = open(os.path.join(HERE, "app.py"), encoding="utf8").read()
check("every download button is set not to re-run the page (a re-run snapped users back to the first tab)",
      _src.count(".download_button(") == 3 and _src.count('on_click="ignore"') >= 3, _src.count('on_click="ignore"'))

print("1b. a redeploy that leaves OLD modules in memory heals itself (seen live)")
import sys  # noqa: E402
import types  # noqa: E402
run(rep, "warm")                                    # first run records the code fingerprint
real_mods = {k: sys.modules[k] for k in ("report_pdf", "ui_consult") if k in sys.modules}
old_pdf = types.ModuleType("report_pdf")
old_pdf.build_pdf = lambda rep_: b"%PDF-old"          # the previous version: no `part` argument
old_pdf.filename = lambda rep_: "old.pdf"
old_ui = types.ModuleType("ui_consult")
old_ui.overview = lambda c: None                      # the previous version: no `headline` argument
for _n in ("ai_view", "fix_site"):
    setattr(old_ui, _n, lambda c: None)
sys.modules["report_pdf"], sys.modules["ui_consult"] = old_pdf, old_ui
atx = run(rep, "stale, same fingerprint")
check("(control) with the OLD modules kept in memory the page does fail - this is the live bug",
      bool(atx.exception) and any("positional argument" in e.message or "takes" in e.message for e in atx.exception),
      [e.message[:80] for e in atx.exception])
sys.modules["report_pdf"], sys.modules["ui_consult"] = old_pdf, old_ui
sys._hotel_audit_build = None                         # a redeploy changes the code fingerprint
aty = run(rep, "stale, new deployment")
check("after a code change the stale modules are dropped and the page renders", not aty.exception, [e.message[:100] for e in aty.exception])
check("...with the CURRENT modules in use (two PDFs offered, new overview)",
      sys.modules["report_pdf"] is not old_pdf and sys.modules["ui_consult"] is not old_ui)

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
