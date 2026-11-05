"""
Offline test: a facility the website mentions but barely describes (event space with no sizes, capacities or events hosted) becomes a specific recommendation; a well-described one does not; the example wording
uses only placeholders and the room names the pages really give. No network. Run: python test_facility.py
"""
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import advice
import consultant
import facility_depth as fd
import guest_questions as gq
import ranking

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


BASE, HOTEL, CITY = "https://www.example-hotel.com/", "Example Hotel Opera", "Paris"


def page(path, text):
    return {"url": BASE + path, "title": HOTEL, "text": text, "h1": [], "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "", "ok": True}


HOME = page("", f"Welcome to the {HOTEL} in the heart of Paris, close to the Opera. Book direct. " * 6)
THIN = page("meetings-events/", "Meetings and events. Our event space is perfect for your next occasion. Contact us to find out more about our meeting rooms. " * 3)
RICH = page("meetings-events/", "Meetings and events. The Garnier Ballroom is 240 m² and seats 180 guests banquet style, 250 theatre. The Opera Suite holds 40 boardroom. We host weddings, galas, conferences and product launches. "
                                "Screens, microphones and Wi-Fi are included. Catering menus and coffee breaks are available. Contact our events team to request a capacity chart. " * 2)


FILL = [page("rooms/", "Our rooms and suites offer king beds and city views, and sleep up to 3 guests. Complimentary Wi-Fi is included in every rate. Call reservations on +33 1 44 83 40 40. " * 3),
        page("dining/", "The brasserie serves lunch and dinner every day. Breakfast is served from 6:30 to 10:30. Reserve a table on +33 1 44 83 40 40. " * 3)]


def run(events_page):
    pages = [HOME, FILL[0], FILL[1], events_page]
    meta = [{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in pages]
    guest = {"questions": gq.evaluate(pages), "conflicts": [], "own_facts_node": {}, "pages_ok": 4, "pages_attempted": 4}
    return consultant.analyse(own_pages=pages, pages_meta=meta, base=BASE, hotel=HOTEL, city=CITY, location={"lat": 48.87, "lon": 2.33}, guest=guest, site={"robots": {"present": False, "status": 200}, "sitemap": {}},
                              entities=[], intel=None, osm_ctx=None)


print("1. what the check finds")
thin = fd.analyse(NS(content_pages=[THIN]))
rich = fd.analyse(NS(content_pages=[RICH]))
ev_thin, ev_rich = thin[0], rich[0]
check("an event space with no size, capacity, layouts or events hosted is thin: 0 of 8 details stated", ev_thin["key"] == "events" and len(ev_thin["found"]) == 0 and ev_thin["thin"] and ev_thin["total"] == 8, str(ev_thin["found"]))
check("one that states size, capacity, layouts, events hosted, named rooms, equipment, catering and how to enquire is not thin", len(ev_rich["found"]) == 8 and not ev_rich["thin"], [m["key"] for m in ev_rich["missing"]])
check("each detail found carries the words the page uses, as proof", all(d["quote"] and d["match"] for d in ev_rich["found"]) and any("240" in d["quote"] for d in ev_rich["found"] if d["key"] == "size"))
check("the room names on the page are listed (without 'The')", ev_rich["names"] == ["Garnier Ballroom", "Opera Suite"], ev_rich["names"])
check("a passing single mention is not treated as a facility the hotel promotes", fd.analyse(NS(content_pages=[page("about/", "We have a nice meeting room.")])) == [])

print("2. the recommendation")
recs = advice._from_facility_depth(thin)
check("a thin event space gives one recommendation, naming what is missing", len(recs) == 1 and recs[0]["id"] == "FD-events" and "sizes" in recs[0]["title"] and "The size of each space" in recs[0]["finding"], recs[0]["title"] if recs else "")
r = recs[0]
check("it quotes what the page does say and lists the pages inspected", any("event space" in e["snippet"].lower() for e in r["evidence"]) and any(e["snippet"].startswith("Pages inspected") for e in r["evidence"]))
check("the action names the details to state: size in m² and sq ft, capacity per layout, kinds of events, equipment, catering, how to enquire", all(w in r["action"] for w in ("m² and sq ft", "capacity for each layout", "weddings", "catering", "enquire")))
check("the example wording is a template: placeholders for every fact the pages do not give", "[x] m²" in r["example"] and "theatre [n]" in r["example"] and "[events email and phone]" in r["example"])
rr = advice._from_facility_depth(rich)
check("a well-described event space gives no recommendation", rr == [])
check("example wording uses the real room names when the page has some", "Garnier Ballroom" in advice._from_facility_depth([{**ev_rich, "thin": True, "found": ev_rich["found"][:2], "missing": ev_rich["missing"] or [{"key": "size", "label": "The size of each space", "example": "x"}]}])[0]["example"])
rk = ranking.annotate([dict(recs[0])], [])[0]
check("it ranks high enough to reach the action plan, as a fix", rk["value"] >= 28 and rk["kind"] == "fix" and rk["priority"] in ("high", "medium", "critical"), (rk["value"], rk["kind"]))

print("3. end to end through the analysis")
out_thin, out_rich = run(THIN), run(RICH)
ids_thin = [x["id"] for x in out_thin["recommendations"]]
check("the analysis of the thin site contains the recommendation, with the evidence label from the ranking", "FD-events" in ids_thin and next(x for x in out_thin["recommendations"] if x["id"] == "FD-events").get("confidence_label") in ("Confirmed", "Likely"), ids_thin)
check("the analysis of the well-described site does not", "FD-events" not in [x["id"] for x in out_rich["recommendations"]])
check("the findings travel with the report, for the strengths and weaknesses list", out_thin["facility_depth"] and out_thin["facility_depth"][0]["key"] == "events")

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
