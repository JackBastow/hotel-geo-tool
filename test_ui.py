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
check("the headline score is labelled readiness (never AI visibility), shown as a ring with its measurement coverage and what was not measured",
      "AI discoverability readiness" in " ".join(m.value for m in at.markdown) and "AI visibility score" not in " ".join(m.value for m in at.markdown)
      and 'class="hk-ring"' in " ".join(m.value for m in at.markdown) and any("Measurement coverage" in str(p_.text) for p_ in at.get("progress")) and "Not measured" in " ".join(m.value for m in at.markdown))
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

check("the sampled AI answers are shown, labelled a sample and never a ranking",
      "What an AI assistant said (a sample)" in text and any("not a ranking" in c.value for c in at.caption), [c.value[:60] for c in at.caption][:5])
check("what it found is stated in numbers a reader can hold (named in 0 of 2, known directly, sources listed)",
      {"Town-wide", "Known directly"} <= {m.label for m in at.metric} and "Own website cited: " in " ".join(m.value for m in at.markdown) and "booking.com" in text)

check("the reviews-and-replies snapshot is shown with its limits: seen on examined, never a reply rate, and not part of any score",
      "Reviews and replies: an indicative snapshot" in text and any("not the hotel's reply rate" in c.value for c in at.caption), [c.value[:50] for c in at.caption][:6])
check("it states the numbers it found (examined, with a reply, critical with a reply)",
      {"Reviews examined", "With a reply from the hotel", "Critical reviews with a reply"} <= {m.label for m in at.metric})

import copy as _copy  # noqa: E402
tx = _copy.deepcopy(rep)
tx["consultant"]["coverage"].update(text_only=True, limited=False, note="These pages were read through Anthropic's page reader as plain text, because the site refused this tool's own reader.")
at_tx = run(tx, "text-only")
check("a report built from the fallback reader renders and tells the reader how the pages were read",
      not at_tx.exception and any("read through Anthropic's page reader" in i.value for i in at_tx.info), [e.message for e in at_tx.exception])

check("the AI analysis is shown: who is recommended instead, the question matrix, sources, hypotheses, perception, accuracy and head to head",
      all(w in text for w in ("Who the assistant recommends instead", "Question by question", "Where the assistant got its information", "Why the hotel may not be named: hypotheses",
                              "What the assistant says about the hotel", "Is what it said correct?", "Oatlands Park Hotel")), [w for w in ("Who the assistant recommends instead", "Question by question", "Why the hotel may not be named: hypotheses", "Is what it said correct?") if w not in text])
check("hypotheses are labelled as hypotheses, not causes, and cite their evidence", any("not as causes" in w.value for w in at.warning) and "evidence E1, E2" in text)
_tables = " ".join(str(d.value.to_dict()) for d in at.dataframe)
check("the mismatch is shown plainly: free parking said, a charge in the hotel's own record", "free parking" in _tables and "differs" in _tables and "parking charge" in _tables)
_md = " ".join(m.value for m in at.markdown)
check("the share of names, the place in the table and the average position are shown as figures",
      all(w in _md for w in ("Share of the names given: ", "Your place in that table: ", "Average position when named: ")))

check("the niche markets get their own section, with the reason each question was asked",
      "Where the hotel actually competes" in text and "None names the hotel" in " ".join(c.value for c in at.caption))
_tb = " ".join(str(d.value.to_dict()) for d in at.dataframe)
check("each niche question is shown with its market (Airport, Spa), the question, why it was asked and whether the hotel was named, as a dot per answer",
      all(w in _md for w in ("Airport", "Spa", "Why we asked: ", "Heathrow", "hk-dot y", "hk-dot n")))
check("the metrics show both counts: town-wide and niche markets", {"Town-wide", "Niche markets"} <= {m.label for m in at.metric})

check("the brand ranking shows the hotel and the top named hotels with coverage, position and sentiment, and says it describes this one sample",
      "Brand ranking: the hotel and the hotels named most" in text and {"Coverage", "Sentiment"} <= {m.label for m in at.metric} and "Your place: " in _md
      and "Positive / neutral / negative" in _tb and any("not the market" in c.value for c in at.caption) and "**Coverage** is the share of answers that named the hotel" in _md)
check("the exact pages are listed, with the caveat that they are judged only from the title and the quoted passage",
      "The exact pages the assistant used" in text and "booking.com/hotel/gb/oatlands-park.html" in _tb and any("we do not read these pages" in c.value for c in at.caption))

check("the AI tab says how the hotel's market was read (price level, kind, audiences with their evidence), because that decided the questions",
      "How we read this hotel's market:" in _md and "Upscale airport hotel" in _md and "Price level: upscale" in _md and "Weddings" in _md and "not for 'the best hotels in town'" in " ".join(c.value for c in at.caption))
check("the form lets the hotel say who it is for: a price level and the audiences to attract", any(x.label == "Price level" for x in at.selectbox) and any(x.label.startswith("Audiences the hotel wants") for x in at.multiselect),
      ([x.label for x in at.selectbox], [x.label for x in at.multiselect]))
check("the reviews card shows how replies were written (specific, thanks, action, signed) and what reviews were about",
      all(w in _md for w in ("How the replies were written", "specific to the guest: 1 of 2", "What positive reviews were about", "breakfast", "What critical or mixed reviews were about", "noise")))
check("the AI tab says how often the hotel's own site was behind the answers, which sites were cited instead, and why that matters",
      (lambda t: "Your own website was among the sources in 1 of 4 answers" in t and "booking.com (2)" in t and "finds it elsewhere and cites elsewhere" in t)(" ".join(e.value for e in list(at.info) + list(at.success))))
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
check("an unreadable site renders, with a clear error banner", not at7.exception and any("None of the 10 pages we tried could be read" in e.value for e in at7.error),
      [e.message for e in at7.exception])
noname = copy.deepcopy(rep)
noname["intel"] = None
noname["meta"]["hotel"] = ""
noname["meta"]["hotel_name_source"] = "could not be determined"
noname.setdefault("site", {}).setdefault("meta", {})["scope_note"] = ("You entered a page inside a larger website (www.hilton.com), so only this hotel's own pages were read. "
                                                                    "robots.txt, the sitemap and other site-wide settings belong to the whole www.hilton.com website.")
at8 = run(noname, "no hotel name, chain page")
check("a run with no hotel name and no outside analysis renders", not at8.exception, [e.message for e in at8.exception])
check("it asks for the hotel name and city instead of silently skipping the outside checks",
      any("hotel's name couldn't be worked out" in w.value and "run the audit again" in w.value for w in at8.warning))
check("a chain page explains that site-wide settings belong to the brand", any("page inside a larger website" in i.value for i in at8.info))
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
