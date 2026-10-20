"""
Golden regression test built from the Paris Marriott Opera Ambassador report (20 October 2026), a chain hotel read through the plain-text page reader. Every error found in that report is reproduced here
and must stay fixed:

  * a telephone number that is not a number, a chain's freephone line, and digits run together were reported as contradictions;
  * 'Paris Marriott Opera Ambassador Hotel Hotel' was reported as a second name for the hotel, and labelled Verified;
  * a brand's amenity template ('Fire Pit + Grill Grate ... Picnic Table') was quoted as evidence of what a Paris room rate includes;
  * breakfast text ('a live egg-station') was quoted as evidence for transport connections;
  * a brand-wide meeting-planning page was offered as 'a page on this topic that was not read' for parking;
  * findings that something is NOT stated were labelled as confirmed.

The pages imitate that situation; they are not a copy of Marriott's site. Nothing touches the network. Run: python test_golden.py
"""
import re
import warnings

warnings.filterwarnings("ignore")
import advice
import consultant
import guest_questions as gq
import identity
import listing_facts
import phones
import ranking

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


BASE = "https://www.marriott.com/en-us/hotels/paroa-paris-marriott-opera-ambassador-hotel/"
HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
TEMPLATE = "Center Complimentary On-Site Laundry No Fire Pit + Grill Grate No Chairs + Picnic Table Complimentary Wi-Fi Free for Marriott Bonvoy members"
OUT_OF_SCOPE = "https://www.marriott.com/meeting-event-hotels/meeting-planning.mi"


def page(path, text, links=(), title=""):
    return {"url": BASE + path, "title": title or HOTEL, "text": text, "h1": [], "tels": [], "mails": [], "links": list(links), "signals": {}, "footer_text": "", "ok": True}


OVERVIEW = page("overview/", f"Welcome to the {HOTEL}, in the heart of Paris. The hotel is close to the Louvre Museum, about 15 minutes away. Call us on +33 1 44 83 40 40 or use our freephone 1-800-228-9290. "
                f"{TEMPLATE} For breakfast, guests will enjoy a full American buffet with a live egg-station. An a-la-carte menu is also available as well as in-room dining offering. Learn More Brasserie Sixtine. "
                "Our 3 meeting rooms host up to 120 delegates. Wi-Fi is complimentary throughout the hotel. " * 2, links=[OUT_OF_SCOPE, BASE + "rooms/", BASE + "dining/"])
DINING = page("dining/", "Brasserie Sixtine serves lunch and dinner. Reserve on +33 1 44 83 40 40. Breakfast is served from 6:30 to 10:30. " * 4)
ROOMS = page("rooms/", "Our rooms and suites offer king beds and city views. Premium rooms sleep up to 3 guests. Complimentary Wi-Fi is included in every rate. Contact reservations on +33 1 44 83 40 40. Call 0019271927. " * 3)
EVENTS = page("events/", "Meetings and events. Events team: +33 1 44 83 40 41. Our meeting rooms host up to 120 delegates theatre-style with a projector and screen. " * 3)
PAGES = [OVERVIEW, DINING, ROOMS, EVENTS]
META = [{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in PAGES]
guest = {"questions": gq.evaluate(PAGES), "conflicts": [], "own_facts_node": {}, "read_via": "anthropic_page_reader", "pages_ok": 4, "pages_attempted": 4}
out = consultant.analyse(own_pages=PAGES, pages_meta=META, base=BASE, hotel=HOTEL, city=CITY, location={"lat": 48.87, "lon": 2.33}, guest=guest, site={"robots": {"present": False, "status": 403}, "sitemap": {},
                         "meta": {"scope": "/en-us/hotels/paroa-paris-marriott-opera-ambassador-hotel/"}}, entities=[], intel=None, osm_ctx=None, text_only=True)
recs = out["recommendations"]
blob = " ".join(e.get("snippet", "") for r in recs for e in r.get("evidence") or []) + " " + " ".join(r["finding"] + r["title"] for r in recs)

print("1. telephone numbers")
cons = out.get("consistency") or []
check("a string that is not a valid number, a chain's freephone line and the events team's own line do not make '3 different telephone numbers'", not any(c.get("type") == "phone" for c in cons) and not any("telephone numbers" in r["title"] for r in recs), [c.get("title") for c in cons])
check("phones: a US toll-free line on a Paris listing is a different line by design, not a contradiction", phones.compare("33144834040", "18446310595")[0] == "not_comparable")
check("phones: digits run together after the real number are that number", phones.compare("33144834040", "3314483404077")[0] == "same")
check("phones: a genuinely different direct number is still different", phones.compare("33144834040", "+33 1 44 83 40 41")[0] == "different")
check("phones: '0019271927' is not a telephone number", phones.parse("0019271927", "FR") is None)
listings = {"TripAdvisor": {"url": "https://tripadvisor.example/x", "title": "", "check_in": None, "check_out": None, "stars": None, "phone": "18446310595", "quotes": {}},
            "Kayak": {"url": "https://kayak.example/x", "title": "", "check_in": None, "check_out": None, "stars": None, "phone": "3314483404077", "quotes": {}},
            "Trivago": {"url": "https://trivago.example/x", "title": "", "check_in": "15:00", "check_out": None, "stars": None, "phone": None, "quotes": {}}}
rows = listing_facts.compare(listings, {"phone": "33144834040", "check_in": "16:00"})
by = {(r["platform"], r["fact"]): r["status"] for r in rows}
check("the listing comparison drops the freephone line, accepts the run-together number as the same, and keeps the real check-in difference",
      ("TripAdvisor", "Telephone") not in by and by.get(("Kayak", "Telephone")) == "matches" and by.get(("Trivago", "Check-in time")) == "differs", str(by))

print("2. the hotel's name")
v = identity.name_variants_seen(HOTEL, {"candidates": [{"source_type": "search", "title": HOTEL + " Hotel deals", "snippet": "Book " + HOTEL + " hotel now", "label": "x", "domain": "x.com", "url": "u"}]}, [], HOTEL, [])
check("a repeated word is not a second form of the name", [x["variant"] for x in v] == [HOTEL], v)

print("3. evidence has to be about the thing it supports")
check("the brand's amenity template is never quoted", "Fire Pit" not in blob and "Picnic Table" not in blob)
tr = [r for r in recs if "transport" in (r.get("topics") or [])]
check("breakfast text is never evidence for transport connections", not any("egg-station" in e.get("snippet", "") for r in recs for e in r.get("evidence") or []), [e.get("snippet", "")[:80] for r in tr for e in r.get("evidence") or []])
check("every quotation kept as evidence passes the topic test for its recommendation", all(advice._on_topic(advice._quoted_part(e.get("snippet", "")), r.get("topics")) for r in recs for e in r.get("evidence") or []))
trav = out["traveller"]
ptxt = " ".join(str(r.get("why", "")) + str(r.get("found", "")) for s in trav["segments"] for r in s["requirements"])
check("a brand-wide meeting-planning page outside the hotel's own folder is not 'a page on this topic that was not read'", "meeting-planning" not in ptxt, ptxt[:200])

print("4. 'not stated' is never 'confirmed'")
check("no recommendation based on something not being stated is labelled Confirmed", all(r.get("confidence_label") != "Confirmed" for r in recs if r.get("absence_based")), [(r["id"], r.get("confidence_label")) for r in recs if r.get("absence_based")])
check("no recommendation is Confirmed on an audit note alone", all(r.get("confidence_label") != "Confirmed" or any(e.get("url") and not re.match(r"(?i)(pages inspected|no page about|audit note)", (e.get("snippet") or "")) for e in r.get("evidence") or []) for r in recs))
check("every recommendation has one of the three labels", {r.get("confidence_label") for r in recs} <= {"Confirmed", "Likely", "Worth checking"}, {r.get("confidence_label") for r in recs})
check("the ladder moves rank: for the same issue Confirmed > Likely > Worth checking", ranking.CONF_FACTOR["Confirmed"] > ranking.CONF_FACTOR["Likely"] > ranking.CONF_FACTOR["Worth checking"])
check("no more than three top actions come from one category", max([sum(1 for i in out["top_actions"] if next(r for r in recs if r["id"] == i)["category"] == c) for c in {r["category"] for r in recs}] or [0]) <= 3)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
