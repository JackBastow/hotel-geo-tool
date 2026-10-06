"""
Tests for the PDF report: layout, pagination, links, page numbers, escaping,
hostile content and degraded input. Uses a real saved audit
(tests_data/sample_report.json) so the layout is tested against real data
shapes. Run: python test_pdf.py

PyMuPDF is used only to INSPECT the PDF here (it is not a project dependency);
if it is not installed the layout checks are skipped and say so.
"""
import copy
import json
import os
import re

import report_pdf

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
rep = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))


def inspect(data):
    doc = pymupdf.open(stream=data, filetype="pdf")
    text = " ".join("\n".join(p.get_text() for p in doc).split())   # table cells wrap lines
    links = sum(len(p.get_links()) for p in doc)
    return doc, text, links


print("1. a real audit becomes a real PDF")
data = report_pdf.build_pdf(rep)
check("output is a PDF", data[:5] == b"%PDF-")
if pymupdf is None:
    print("  SKIP  layout inspection (PyMuPDF not installed)")
else:
    doc, text, links = inspect(data)
    check("more than a handful of pages (all findings, not a summary)", len(doc) >= 10, len(doc))
    check("text is selectable, not an image", len(text) > 5000)
    check("hotel name present", rep["meta"]["hotel"] in text)
    check("clickable links are present", links >= 20, links)
    n = len(doc)
    check("every page has 'Page x of N' in its footer",
          all(f"Page {i + 1} of {n}" in doc[i].get_text() for i in range(n)))
    for heading in ("Executive summary", "Identity and distribution", "Reviews and reputation",
                    "Media coverage and independent validation", "Traveller fit and positioning",
                    "Social, video and local context", "Website support", "Coverage gaps and methodology",
                    "Evidence appendix", "How AI understands this hotel", "Questions AI may struggle to answer",
                    "Machine readiness and structured data", "Recommendation register"):
        check(f"section present: {heading}", heading in text)
    check("all 30 checks are listed", all(c["name"] in text for c in rep["intel"]["checks"]))
    check("sections are numbered in order", all(f"{i}. " in text for i in range(1, 9)))
    check("recommendation cards use the Finding / Why / Action shape", "What we found" in text and "Why it matters" in text and "What to do" in text)
    check("the readiness profile explains what drove each score", "What drove it" in text)
    check("the media-target table is present with its caveat", "Media and organisation targets" in text)
    check("the guest-review limitation is stated", "0 guest reviews" in text)
    check("limitations stated: nothing measures what AI recommends", "Nothing here measures what any AI assistant recommends" in text)
    check("no escaping artefacts leaked into the text",
          not any(x in text for x in ("&amp;", "&lt;", "<br", "<b>", "<font", "<link")))
    check("every evidence id used by a recommendation appears in the appendix",
          all(e in text for r in rep["intel"]["recommendations"] for e in r["evidence_ids"]))
    # pagination: a long table must repeat its header and not clip rows
    big = copy.deepcopy(rep)
    base = big["intel"]["ledger"]
    for k in range(250):
        e = dict(base[k % len(base)])
        e["id"] = f"E{1000 + k}"
        big["intel"]["ledger"].append(e)
    d2, t2, _ = inspect(report_pdf.build_pdf(big))
    check("a 250-row table paginates (more pages)", len(d2) > len(doc), (len(d2), len(doc)))
    check("table header repeats on continuation pages", t2.count("Published / collected") >= 3, t2.count("Published / collected"))
    check("no evidence row is lost to clipping", all(f"E{1000 + k}" in t2 for k in (0, 100, 249)))

print("1b. the management report is short, decision-oriented and says each thing once")
if pymupdf is not None:
    mdata = report_pdf.build_pdf(rep, "management")
    mdoc, mtext, mlinks = inspect(mdata)
    check("the management report is about 4-11 pages (the appendix holds the detail)", 4 <= len(mdoc) <= 11, len(mdoc))
    adoc, atext, _ = inspect(report_pdf.build_pdf(rep, "appendix"))
    check("the appendix is separate and much longer than the management report", len(adoc) >= 3 * len(mdoc), (len(adoc), len(mdoc)))
    for heading in ("Executive summary", "Readiness score and coverage", "things most worth doing", "What AI and search can clearly understand",
                    "Important information gaps", "Reputation and distribution risks", "already doing well", "30 / 60 / 90-day plan"):
        check(f"management section present: {heading}", heading in mtext)
    check("the score is shown WITH its coverage and a provisional label", "Measurement coverage" in mtext and "PROVISIONAL" in mtext)
    check("what was not measured is stated", "Not measured" in mtext and "AI Visibility" in mtext)
    check("each evidence-strength level is shown beside component scores", "evidence" in mtext and "Evidence strength" in mtext)
    for fld in ("Issue", "Why it matters", "Evidence", "Exact action", "Owner", "Expected outcome"):
        check(f"each top action shows: {fld}", mtext.count(fld) >= 3, mtext.count(fld))
    check("each top action shows priority, effort and confidence", all(w in mtext for w in ("priority - effort", "confidence:")))
    check("the 2/5 food hygiene rating reaches the management report", "Food hygiene rating" in mtext)
    check("at most seven top actions", mtext.count("Appendix reference") <= 7, mtext.count("Appendix reference"))
    check("opportunities are labelled as not defects", "Not defects" in mtext)
    check("the limits are stated up front and at the end", "does not show what any AI assistant actually says" in mtext)
    import re as _re
    sents = [x.strip() for x in _re.split(r"(?<=[.!?])\s+", mtext) if len(x.strip()) >= 90]
    dup = sorted({x for x in sents if sents.count(x) > 1})
    check("no long sentence is repeated word-for-word in the management report", not dup, dup[:2])
    ex = [r["example"].strip().splitlines()[0] for r in rep["consultant"]["recommendations"] if r.get("example") and len(r["example"].strip().splitlines()[0]) > 25]
    ex_clean = [" ".join(e.split())[:50] for e in ex]
    check("a worked example appears once in the appendix, not in several sections",
          all(atext.count(e) <= 1 for e in ex_clean), [(e, atext.count(e)) for e in ex_clean if atext.count(e) > 1])
    check("the appendix carries the crawler-access evidence table, with its limits",
          "Crawler access and speed" in atext and "Common Crawl" in atext and "PageSpeed Insights" in atext and "not a lock" in atext)
    check("the appendix says what it is and points back to the management report", "Technical & evidence appendix" in atext and "management report" in atext)
    check("the management report links to the evidence by reference, not by repeating it", "Appendix reference" in mtext)
    check("filenames say which document it is", "management-report" in report_pdf.filename(rep, "management") and "appendix" in report_pdf.filename(rep, "appendix"))

print("2. hostile and awkward content")
hostile = copy.deepcopy(rep)
hostile["meta"]["hotel"] = "Bad <script>alert(1)</script> & \"Quote\" Hotel"
for a in hostile["intel"]["media"]["articles"][:2]:
    a["title"] = "<b>Bold</b> & <img src=x onerror=alert(1)> 中文 \U0001F600"
    a["url"] = "javascript:alert(1)"
hostile["intel"]["ledger"][0]["extract"] = "x < y & z > w → ≥ 'q' “smart”"
try:
    hb = report_pdf.build_pdf(hostile)
    check("hostile/non-Latin text does not crash the build", hb[:5] == b"%PDF-")
    if pymupdf:
        _, ht, hl = inspect(hb)
        check("markup in data is shown as text, not interpreted", "<script>" in ht or "script" in ht)
        check("a javascript: URL is not turned into a link",
              not any("javascript" in (l.get("uri") or "") for p in pymupdf.open(stream=hb, filetype="pdf") for l in p.get_links()))
except Exception as e:  # noqa: BLE001
    check("hostile/non-Latin text does not crash the build", False, repr(e))

print("3. degraded input")
noi = copy.deepcopy(rep)
noi["intel"] = {"error": "RuntimeError: boom"}
try:
    nb = report_pdf.build_pdf(noi)
    check("a failed wider analysis still yields a usable PDF with a notice", nb[:5] == b"%PDF-")
    if pymupdf:
        _, nt, _ = inspect(nb)
        check("the notice explains what is missing", "did not complete" in nt)
except Exception as e:  # noqa: BLE001
    check("a failed wider analysis still yields a usable PDF", False, repr(e))
import consultant  # noqa: E402
unreadable = copy.deepcopy(rep)
unreadable["consultant"] = consultant.analyse(
    own_pages=[], pages_meta=[{"url": "https://x.com/p%d/" % i, "ok": False, "reason": "request failed or timed out", "status": None, "title": ""} for i in range(10)],
    base="https://x.com/", hotel="X Hotel", city="Leeds", location={}, guest={"questions": [], "conflicts": [], "own_facts_node": {}},
    site={"robots": {"present": False}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
try:
    ub = report_pdf.build_pdf(unreadable)
    check("a PDF for an unreadable site builds", ub[:5] == b"%PDF-")
    if pymupdf:
        _, ut, _ = inspect(ub)
        check("it says how little was read and does not claim anything is missing",
              "Read 0 of 10 pages" in ut and "Check that the website can be read" in ut)
except Exception as e:  # noqa: BLE001
    check("a PDF for an unreadable site builds", False, repr(e))
empty = copy.deepcopy(rep)
for k in ("articles", "rejected", "unread", "targets", "angles", "comparison", "awards", "ratings", "roundups", "clusters"):
    empty["intel"]["media"][k] = []
empty["intel"]["media"]["themes"] = {"themes": [], "disagreements": [], "own_only": [], "independent_only": []}
empty["intel"]["media"]["summary"].update(articles=0, stories=0, publishers=0, independent_publishers=0,
                                          duplicates_removed=0, by_type={}, by_freshness={}, by_language={})
empty["intel"]["media"]["research_directions"] = [{"category": "c", "why": "w", "how": "h"}]
empty["intel"]["identity"]["footprint"] = []
empty["intel"]["ledger"] = []
try:
    eb = report_pdf.build_pdf(empty)
    check("a report with no coverage, listings or evidence still builds", eb[:5] == b"%PDF-")
    if pymupdf:
        _, et, _ = inspect(eb)
        check("empty coverage is stated, not hidden", "No page naming the hotel could be read" in et)
        check("research directions are labelled as not a shortlist", "NOT a researched shortlist" in et)
except Exception as e:  # noqa: BLE001
    check("a report with no coverage still builds", False, repr(e))
check("file name is safe and dated", report_pdf.filename(rep).endswith(".pdf") and "/" not in report_pdf.filename(rep)
      and rep["meta"]["run_at"][:10] in report_pdf.filename(rep))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
