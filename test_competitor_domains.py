"""
One competitor-website exclusion for every recommendation module (competitor_domains.py).
Run: python test_competitor_domains.py
"""

import competitor_domains as cd

FAILS = []


def check(label, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + label + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILS.append(label)


REP = {
    "meta": {"hotel": "Saunton Sands Hotel", "base": "https://www.sauntonsands.com/"},
    "identity": {"aliases": [{"name": "Saunton Sands Hotel"}]},
    "ai_gap": {"rivals": [{"name": "Woolacombe Bay Hotel", "url": "https://www.woolacombe-bayhotel.co.uk/"}],
               "markets": [{"rivals": [{"name": "Northcote Manor, Burrington (near Umberleigh)"}, {"name": "Watersmeet Hotel"}]}],
               "articles": [{"rivals_in": ["The Imperial Hotel, Barnstaple"]}]},
    "ai_insights": {"brand_ranking": {"all": [{"name": "Saunton Sands Hotel", "is_target": True}, {"name": "The Headland Hotel & Spa", "is_target": False},
                                              {"name": "Devon Hotel", "is_target": False}, {"name": "Newquay Beach Hotel", "is_target": False}]}},
    "competitors": {"competitors": [{"name": "Durrant House", "url": "https://durranthouse.com"}]},
}
X = cd.excluded(REP)

print("1. rivals whose website nobody looked up are still excluded")
check("a rival named only in the answers: its own address is excluded", bool(X.reason("northcotemanor.co.uk")), X.reason("northcotemanor.co.uk"))
check("with 'the' and 'hotel' around the name", bool(X.reason("www.thewatersmeethotel.co.uk")))
check("hyphenated address", bool(X.reason("the-headland-hotel.co.uk")))
check("a rival named on a cited page only (The Imperial Hotel)", bool(X.reason("theimperialhotel.co.uk")))
check("a rival whose URL the research found", bool(X.reason("woolacombe-bayhotel.co.uk")) and bool(X.reason("durranthouse.com")))
check("a hotel group's own site", bool(X.reason("www.marriott.com")) and bool(X.reason("hilton.com")))

print("2. a site that only shares a word with a rival is NOT excluded")
check("a county tourism board is not 'Devon Hotel'", not X.reason("visitdevon.co.uk") and not X.reason("devon.gov.uk"), (X.reason("visitdevon.co.uk"), X.reason("devon.gov.uk")))
check("a town tourism site is not 'Newquay Beach Hotel'", not X.reason("visitnewquay.com") and not X.reason("newquay.com"))
check("a travel blog that mentions a rival's word is not that rival", not X.reason("watersmeet-walks.org") and not X.reason("visitwatersmeet.org"))
check("a publisher is allowed", not X.reason("cntraveller.com") and not X.reason("theguardian.com"))

print("3. the hotel itself is not a competitor")
check("the hotel's own site is left to the callers", not X.reason("sauntonsands.com") and not X.reason("www.sauntonsands.com"))

print("4. a source named after a rival, at any address")
check("a researched source called 'The Headland Hotel & Spa' on another address", bool(X.reason("devon-escapes.co.uk", name="The Headland Hotel & Spa")))
check("a source with another name is allowed", not X.reason("devon-escapes.co.uk", name="Devon Escapes Magazine"))

print("5. the matcher on its own")
for n, d, want in [("Northcote Manor", "northcote.co.uk", True), ("Northcote Manor", "northcotemanor.com", True), ("Chewton Glen", "chewtonglen.com", True),
                   ("Chewton Glen Hotel & Spa", "chewtonglen.com", True), ("The Cliff House", "cliffhouse.co.uk", True), ("Boundary Shoreditch", "boundary.london", False),
                   ("Fistral Beach Hotel & Spa", "fistralbeachhotel.com", True), ("Hotel Arts Barcelona", "hotelartsbarcelona.com", True), ("Royal Hotel", "royal.com", False)]:
    check(f"{n} / {d} -> {want}", cd.name_matches_domain(n, d) == want, cd.name_matches_domain(n, d))

print("6. a report with nothing in it never raises")
check("empty report", cd.excluded({}).reason("example.com") == "" and cd.excluded(None).reason("marriott.com") != "")

print("7. the recommendation modules use it (the review: a rival whose website the research never found was still eligible)")
import source_actions
import strategy_actions
_pages = [{"url": "https://www.timeout.example/devon/best-hotels", "domain": "timeout.example", "cited": 3, "names_hotel": False, "names_competitor": "Northcote Manor"},
          {"url": "https://www.northcotemanor.co.uk/rooms", "domain": "northcotemanor.co.uk", "cited": 4, "names_hotel": False, "names_competitor": "Northcote Manor"},
          {"url": "https://www.thewatersmeethotel.co.uk/", "domain": "thewatersmeethotel.co.uk", "cited": 2, "names_hotel": False, "names_competitor": "Watersmeet Hotel"},
          {"url": "https://www.hilton.com/en/hotels/xyz", "domain": "hilton.com", "cited": 3, "names_hotel": False, "names_competitor": "Hilton Garden Inn"}]
REP2 = {"meta": {"base": "https://www.sauntonsands.com/", "hotel": "Saunton Sands Hotel", "city": "Saunton"}, "ai_insights": {"pages": _pages},
        "ai_gap": {"status": "ok", "markets": [{"qid": "q", "question": "Where should I stay near Saunton?", "named": 0, "of": 3, "gap": True, "rivals": [{"name": "Northcote Manor"}, {"name": "Watersmeet Hotel"}]}], "rivals": [],
                   "articles": [{"url": _pages[0]["url"], "domain": "timeout.example", "cited": 3, "read": "ok", "hotel_in": False, "rivals_in": ["Northcote Manor", "Watersmeet Hotel"], "questions": [], "contact_url": "https://www.timeout.example/contact"},
                                {"url": _pages[1]["url"], "domain": "northcotemanor.co.uk", "cited": 4, "read": "ok", "hotel_in": False, "rivals_in": ["Northcote Manor"], "questions": []},
                                {"url": _pages[2]["url"], "domain": "thewatersmeethotel.co.uk", "cited": 2, "read": "ok", "hotel_in": False, "rivals_in": ["Watersmeet Hotel"], "questions": []}]}}
_src = [s["domain"] for s in source_actions.build(REP2, limit=20)]
check("'where to get listed' keeps the publisher and drops both rival hotels' own sites and the group's", "timeout.example" in _src and not any(d in _src for d in ("northcotemanor.co.uk", "thewatersmeethotel.co.uk", "hilton.com")), _src)
_st = [a["title"] for a in strategy_actions.build(REP2, {"town": "Saunton", "reasons": ["a beach"], "kinds": ["coastal"], "audiences": ["couples"]}, "Saunton Sands Hotel")]
check("the strategy actions never send the hotel to a rival's or a group's website", not any(w in t for t in _st for w in ("northcotemanor", "watersmeet", "hilton.com")), _st)
_rs = [{"name": "Northcote Manor", "domain": "northcotemanor.co.uk", "url": "https://www.northcotemanor.co.uk/", "kind": "publication", "kind_label": "Publication", "why": "x"},
       {"name": "Devon Life", "domain": "devonlife.example", "url": "https://devonlife.example/", "kind": "publication", "kind_label": "Publication", "why": "x"},
       {"name": "The Watersmeet Hotel", "domain": "devon-escapes.example", "url": "https://devon-escapes.example/", "kind": "publication", "kind_label": "Publication", "why": "x"}]
_ra = [a["title"] for a in strategy_actions.build(REP2, {"town": "Saunton", "reasons": ["a beach"], "kinds": ["coastal"], "audiences": ["couples"]}, "Saunton Sands Hotel", research={"sources": _rs})]
check("researched sources: a rival's own address and a source named after a rival are dropped; a real publication stays", any("Devon Life" in t for t in _ra) and not any("Northcote" in t or "Watersmeet" in t for t in _ra), _ra)

print("\nFAILURES:", FAILS or "none")
raise SystemExit(1 if FAILS else 0)
