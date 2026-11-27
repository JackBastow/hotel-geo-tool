"""
Source intelligence: what was retrieved, what was cited, and what kind of site each page is on.
Two defects found by an independent code review, reproduced here:
  1. source_actions counted `cited or answers`, so a page an assistant only retrieved could be counted as a citation, and another assistant's retrieved pages were all counted as citations.
  2. commercial.source_plays worked out each page's site type in one loop and read it in a second, so every recommendation took the type of the last page examined (a booking site could be told
     to "write to the editor", a magazine to "claim your listing").
Run: python test_source_intelligence.py
"""
import copy
import sys
import warnings

warnings.filterwarnings("ignore")
import advice
import commercial
import source_actions

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


print("1. retrieved is not cited")


def page(domain, cited, questions, **kw):
    return {"url": f"https://{domain}/hotels", "domain": domain, "title": f"Hotels on {domain}", "questions": questions, "cited": cited, "passage": "", "names_hotel": False,
            "names_competitor": "Rival Hotel", "own_site": False, **kw}


REP = {"meta": {"hotel": "Test Hotel", "city": "Bath", "base": "https://www.testhotel.example/"},
       "ai_insights": {"pages": [page("retrieved-only.example", 0, 5, answers=4), page("cited-page.example", 3, 2)]}, "ai_gap": {"articles": [], "markets": []}}
rows = {r["domain"]: r for r in source_actions.build(copy.deepcopy(REP))}
check("a page retrieved in 5 questions but cited in none has 0 citations, and 5 retrieved, even if an older field says 'answers: 4'",
      rows["retrieved-only.example"]["cited"] == 0 and rows["retrieved-only.example"]["retrieved"] == 5, rows.get("retrieved-only.example"))
check("it is not credited to the assistant as a source it cited", rows["retrieved-only.example"]["cited_by"] == [], rows["retrieved-only.example"]["cited_by"])
check("a page that was cited keeps its count and credit", rows["cited-page.example"]["cited"] == 3 and rows["cited-page.example"]["cited_by"] == ["Claude"], rows["cited-page.example"])

rep2 = copy.deepcopy(REP)
rep2["ai_insights"]["pages"] = []
rep2["ai_engines"] = {"chatgpt": {"status": "ok", "items": [{"pages": [{"url": "https://engine-site.example/a", "cited": True}, {"url": "https://engine-site.example/b", "cited": False},
                                                                      {"url": "https://engine-site.example/c", "cited": False}]}]}}
r2 = {r["domain"]: r for r in source_actions.build(rep2)}["engine-site.example"]
check("another assistant's search results it did not cite are counted as retrieved, not cited (1 cited, 2 retrieved)", r2["cited"] == 1 and r2["retrieved"] == 2, r2)

print("2. each recommendation uses its own page's site type")
LUX = {"key": "luxury"}


def market(qid):
    return {"qid": qid, "kind": "niche", "question": f"Which hotels near the abbey {qid}?", "angle": "Near a place", "named": 0, "of": 3, "status": "not_named", "rivals": [], "consistent": True}


def article(domain, kind):
    return {"url": f"https://{domain}/best-hotels", "title": f"Best hotels ({domain})", "domain": domain, "kind": kind, "cited": 3, "questions": ["q1", "q2"],
            "rivals_in": ["Alpha Hotel", "Beta House"], "hotel_in": False, "sponsored": False}


BOOKING, MAGAZINE = article("booking.com", "Booking and comparison site"), article("oyster.com", "Other")
conf = {"INFER": advice.INFER, "EXPER": advice.EXPER}
for label, order in (("booking site first", [BOOKING, MAGAZINE]), ("magazine first", [MAGAZINE, BOOKING])):
    gap = {"markets": [market("q1"), market("q2")], "articles": copy.deepcopy(order), "hotel_tier": "upscale"}
    got = {r["title"].split("onto ")[1].split(":")[0]: r["action"] for r in commercial.source_plays(gap, advice._rec, conf)}
    check(f"({label}) the booking site is a listing to claim, not an editor to write to", "booking.com" in got and "Claim or update" in got["booking.com"] and "editor" not in got["booking.com"], got.get("booking.com", "")[:120])
    check(f"({label}) the magazine is an editor to write to, not a listing to claim", "oyster.com" in got and "editor" in got["oyster.com"] and "Claim or update" not in got["oyster.com"], got.get("oyster.com", "")[:120])

print("\nFAILURES:", fails or "none")
sys.exit(1 if fails else 0)
