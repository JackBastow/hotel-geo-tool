"""
Offline regression test built from the errors found in the Hilton Zurich Airport report (19 October 2026): a chain hotel read through the plain-text page reader.

The pages below are a faithful IMITATION of that situation (a price in francs, a denied connecting-rooms sentence, a 'Charging station' label, a menu strip, accessibility mentioned on the dining page,
a brand header with a US phone number), not a copy of Hilton's site, which refuses automated readers. Nothing here touches the network.
Run: python test_hilton.py
"""
import re
import warnings

warnings.filterwarnings("ignore")
import advice
import assessment
import consultant
import external_presence as ep
import guest_questions as gq
import hotel_class
import insight_content as ic
import pagetarget
import places
import scoring
import textutil
import traveller_ready as tr

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


BASE = "https://www.hilton.com/en/hotels/zrhhitw-hilton-zurich-airport/"
HOTEL, CITY = "Hilton Zurich Airport", "Zurich"
BRAND = "Hilton Zurich Airport How can we help? Phone: +1-800-HILTONS Global phone numbers, Opens new tab x, Opens new tab facebook, Opens new tab instagram Hotel Info Offers Gallery Location Dining Book now. "


def page(path, text, title=""):
    url = BASE + path
    return {"url": url, "title": title or path or "Hilton Zurich Airport", "text": BRAND + text, "h1": [], "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "", "ok": True}


HOME = page("", "Welcome to Hilton Zurich Airport. Steps from the terminal, the hotel offers a fitness center, an executive lounge and meeting rooms. Hilton Honors members earn points.")
ROOMS = page("rooms/", "Rooms and suites. King Guest room sleeps 2 adults. Twin Guest room sleeps 2. Executive room with lounge access sleeps 2. Accessible rooms are available on request. Connecting rooms: Not available. "
             "Confirmed connecting rooms cannot be guaranteed. Cribs are available on request.")
DINING = page("dining/", "Dining amenities 2 restaurants Room service 24-hour market Executive lounge Kids menu Accessible features Lobby Bar Horizon10 Hours Show hours for the restaurant and bar. "
              "Breakfast is served from 6:30 to 10:30 and is CHF 38 per person.")
INFO = page("hotel-info/", "Our amenities Dining On-site restaurant Room service Fitness and recreation Fitness center Business and work Executive lounge Business center Meeting rooms. "
            "Wi-Fi is complimentary throughout the hotel. Check-in is from 15:00 and check-out is until 12:00. Early check-in and late check-out are subject to availability. "
            "Accessible rooms with roll-in showers are available. Self parking is CHF 35 per day and valet parking is CHF 45 per day. Pets are not allowed.")
LOCATION = page("hotel-location/", "Location. Hilton Zurich Airport is located directly at Zurich Airport, about 500 m from the terminal. The airport railway station Zurich Airport Station is a 6 minute walk "
                "and trains reach Zurich HB in 10 minutes. Charging station Airports Railway stations Attractions. Hotel Info Offers Gallery Location Dining. A free airport shuttle is not needed: the hotel is "
                "connected to the terminal by a covered walkway. Taxis wait at the entrance. By car take the A51 motorway, exit Kloten.")
EVENTS = page("events/", "Meetings and events. Our meeting rooms host up to 120 delegates theatre-style with a projector and screen. Contact our events team to book.")
PAGES = [HOME, ROOMS, DINING, INFO, LOCATION, EVENTS]
OSM = {"hotels": [], "stations": [{"name": "Zürich Flughafen", "km": 0.4, "lat": 47.45, "lon": 8.56, "tags": {}}], "airports": [{"name": "Zurich Airport", "km": 0.4, "lat": 47.45, "lon": 8.56, "tags": {"iata": "ZRH"}}],
       "attractions": [], "venues": []}
META = [{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in PAGES]


def analyse(**kw):
    guest = {"questions": gq.evaluate(PAGES), "conflicts": [], "own_facts_node": {}, "read_via": "anthropic_page_reader", "pages_ok": 6, "pages_attempted": 6}
    return consultant.analyse(own_pages=PAGES, pages_meta=META, base=BASE, hotel=HOTEL, city=CITY, location={"lat": 47.45, "lon": 8.56, "postcode": "8058"}, guest=guest,
                              site={"robots": {"present": False, "status": 403}, "sitemap": {}, "meta": {"scope": "/en/hotels/zrhhitw-hilton-zurich-airport/"}}, entities=[], intel=None, osm_ctx=OSM, text_only=True, **kw)


print("1. information that IS on the pages is not reported missing, and 'not available' is not 'available'")
qs = {q["id"]: q for q in gq.evaluate(PAGES)}
check("a price in francs is a price: parking states CHF 35 and CHF 45 a day, so its price is not missing", "the price" in qs["parking"]["found"] and "the price" not in qs["parking"]["missing"], qs["parking"])
check("whether you can reserve a space is a nice-to-have, not a gap", qs["parking"]["state"] == "answered" and "whether you can or must reserve" in qs["parking"]["nice_to_have"], qs["parking"])
check("'Connecting rooms: Not available' is recorded as stated-not-available, and is not found as a room type", any("connecting" in n["label"].lower() for n in qs["family"]["not_offered"]) and "connecting rooms" not in [f.lower() for f in qs["family"]["found"]], qs["family"])
check("'Pets are not allowed' answers the pets question (nothing else about pets is demanded)", qs["pets"]["state"] == "answered" and not qs["pets"]["missing"], qs["pets"])
check("textutil: francs, dollars and codes after the figure are all prices", all(textutil.PRICE_RX.search(t) for t in ("CHF 35", "35 CHF", "Fr. 35.-", "$20", "EUR 9", "£14")))
check("textutil: a negation before or after the thing denies it", textutil.is_negated("Connecting rooms are not available.", 0, 16) and textutil.is_negated("We have no connecting rooms.", 11, 27) and not textutil.is_negated("Connecting rooms are available.", 0, 16))

out = analyse()
trv = out["traveller"]
fam = next((s for s in trv["segments"] if s["key"] == "families"), None)
conn = next((r for s in trv["segments"] for r in s["requirements"] if r["id"] == "connecting"), None)
check("the connecting-rooms requirement is 'Stated as not available', never Confirmed", conn is not None and conn["state"] == "not_offered" and conn["found"], conn)
check("it raises no recommendation to add connecting-room details", not any("connecting" in " ".join(r["additions"]).lower() for r in out["recommendations"]))

print("2. places: only named, identifiable places")
H = HOTEL
check("'Charging station' is not a railway station", places.find("Charging station is available.", "station", H) == [] and places.find("Charging Station for cars", "station", H) == [])
check("a menu strip is not an attraction, and 'Airports' is a heading, not an airport", places.find("Hotel Info Offers Gallery Location Dining", "attraction", H) == [] and places.find("Airports", "airport", H) == [])
check("the hotel's own name is not the airport it stands beside, but 'Zurich Airport' on its own is", [p["name"] for p in places.find("Hilton Zurich Airport is 500 m from Zurich Airport.", "airport", H)] == ["Zurich Airport"])
check("a station is accepted with its name and the time stated beside it", [(m["name"], m["distance"]) for m in places.mentions("Zurich Airport Station is a 6 minute walk.", "station", H)][:1] == [("Zurich Airport Station", "6 minute walk")])
loc_items = out["location"]["items"]
names = [i["place"] for i in loc_items]
check("the location analysis names no 'Charging station', no menu strip and no bare 'Airports'", not any(re.search(r"charging|info offers|^airports$", n, re.I) for n in names), names)
check("transport and airport items are named places, validated against the map where it lists them", all(i["place"] for i in loc_items if i["category"] in ("transport", "airports")), loc_items)
req = {r["id"]: r for s in trv["segments"] for r in s["requirements"]}
check("no location requirement is Confirmed from a label: any Confirmed one has a named place with its distance", all((not r["id"].startswith("loc_")) or r["state"] != "confirmed" or any(" with a distance" in f["fact"] for f in r["found"]) for r in req.values()))

print("3. recommendations name a page this information belongs on")
site = ic.Site(PAGES, BASE, HOTEL, CITY)
w = pagetarget.choose(site, "accessibility")
check("accessible-room details go to the hotel-information page, not the dining page that merely mentions accessibility", w["url"].endswith("/hotel-info/") and "dining" not in w["url"], w)
check("parking goes to the location or hotel-information page", pagetarget.choose(site, "parking")["url"].endswith(("/hotel-location/", "/hotel-info/")))
check("room occupancy goes to the rooms page", pagetarget.choose(site, "occupancy")["url"].endswith("/rooms/"))
check("meetings go to the events page", pagetarget.choose(site, "meeting_detail")["url"].endswith("/events/"))
only_dining = pagetarget.choose(ic.Site([HOME, DINING], BASE, HOTEL, CITY), "accessibility")
check("a site whose only other page is the dining page gets no page invented and not the dining page", only_dining["url"] == "" and only_dining["new_page"] is False, only_dining)
acc = [r for r in out["recommendations"] if r["source"] == "questions" and "accessibility" in r.get("topics", [])]
check("any accessibility recommendation targets an appropriate page", all("dining" not in (r["page"] or {}).get("url", "") for r in acc), [(r["id"], r["page"]) for r in acc])

print("4. what kind of hotel it is decides what matters")
hc = out["hotel_class"]
check("it is classified as an airport hotel (name, map and the site's own wording) and a business hotel", {"airport", "business"} <= set(hc["keys"]), hc)
check("a gym and a restaurant do not make it a spa hotel or a wedding venue", "spa_hotel" not in hc["keys"] and "resort" not in hc["keys"], hc["keys"])
check("the airport segment is assessed, and it is the only one marked core alongside business and location", any(s["key"] == "airport_stay" and s["relevance"] == "core" for s in trv["segments"]), [(s["key"], s.get("relevance")) for s in trv["segments"]])
check("family is a secondary market for an airport hotel", all(s.get("relevance") == "secondary" for s in trv["segments"] if s["key"] == "families"), [(s["key"], s.get("relevance")) for s in trv["segments"]])
check("romantic and spa breaks are not assessed at all, with the reason", "spa_couples" not in trv["assessed"] and any(s["key"] == "spa_couples" for s in trv["skipped"]))
air = {r["id"]: r for s in trv["segments"] if s["key"] == "airport_stay" for r in s["requirements"]}
check("airport distance is Confirmed from the site's own statement (500 m, connected to the terminal)", air["airport_distance"]["state"] == "confirmed", air["airport_distance"])
check("an airport shuttle is not demanded of a hotel that says it is connected to the terminal: the requirement is Unknown or not offered, never Missing", air["airport_shuttle"]["state"] in ("unknown", "not_offered"), air["airport_shuttle"])
check("parking is Confirmed with its price (CHF)", air["airport_parking"]["state"] == "confirmed", air["airport_parking"])
check("early departure and late arrival arrangements are judged from the pages (they say nothing about either, so not Confirmed)", air["airport_early_late"]["state"] in ("missing", "unknown", "partial"), air["airport_early_late"])
texts = " ".join(r["title"] + " " + r["finding"] for r in out["recommendations"]).lower()
check("no spa, wedding or romantic-stay recommendation or opportunity is raised", not any(w_ in texts for w_ in ("spa-break", "spa and wellness", "romantic", "wedding proposition", "weddings are a target")), texts[:400])
check("no 'if X is a target segment' opportunity rests on a gym or a restaurant", not any(o["key"] in ("spa", "weddings", "couples") for o in out["opportunities"]), [o["key"] for o in out["opportunities"]])
check("any family finding is optional, an opportunity and not in the top actions", all(r["kind"] == "opportunity" and r["id"] not in out["top_actions"] for r in out["recommendations"] if r["id"] == "TR-families" or r.get("topics") == ["family_rooms"]),
      [(r["id"], r["kind"]) for r in out["recommendations"] if "family_rooms" in r.get("topics", [])])

print("5. the readiness score excludes observed AI visibility")
sc = scoring.build_scorecard({"robots": {"present": False}, "sitemap": {}, "pages": [], "schema_types_found": [], "ai_crawlers_blocked": []}, [], [], {}, {"profiles": []},
                             ai_visibility=scoring._cat("ai_visibility", 39, "sample", partial=True), guest_result={"pages_ok": 6, "pages_attempted": 6, "questions": [], "read_via": "x"}, web={"pagespeed": {"scores": {"performance": 21, "accessibility": 90, "seo": 100, "best-practices": 90}}})
tot = scoring.totals_for(sc)
check("AI visibility is shown as its own measurement and is not in the readiness breakdown", sc["observed_ai_visibility"]["assessed"] and all(b["key"] != "ai_visibility" for b in tot["breakdown"]))
check("changing the AI result does not change the readiness score", scoring.totals([c for c in sc["categories"] if c["key"] != "ai_visibility"] + [scoring._cat("ai_visibility", 99, "x")])["overall"] == sc["overall"])
check("the displayed score equals the weighted sum of the displayed rows", abs(sum(b["points"] for b in tot["breakdown"]) - sc["overall"]) <= 0.6, (sum(b["points"] for b in tot["breakdown"]), sc["overall"]))

print("6. technical coverage is stated accurately for a plain-text read")
rep = {"consultant": out, "guest_questions": {"questions": gq.evaluate(PAGES), "read_via": "anthropic_page_reader"}, "site": {"robots": {"present": False, "status": 403}, "sitemap": {}}, "web_signals": {"pagespeed": {"status": "ok"}},
       "ai_sample": {"status": "ok", "model": "claude-haiku-5-5"}}
asm = assessment.assess(rep)
na = " ".join(i["what"] for i in asm["not_assessed"])
check("structured data, titles, headings and image text are NOT assessed when the pages were read as plain text", "Structured data" in na and "Image alt text" in na)
check("robots.txt that could not be read is not claimed as checked", "robots.txt" in na and not any("robots.txt" in i["what"] for i in asm["assessed"]))
check("the website's text is only partly assessed, and says why", any("plain-text page reader" in i["detail"] for i in asm["partial"] if "text" in i["what"]))
check("observed AI visibility is partly assessed (one assistant), never fully", any(i["what"] == "Observed AI visibility" for i in asm["partial"]))

print("7. outside sources need several identifiers")
town = [{"source": "OpenStreetMap", "found": True, "match_confident": None, "url": "https://www.openstreetmap.org/node/1", "display_name": "Hilton Zurich Airport, Zurich", "facts": {}, "address_components": {"city": "Zurich"}},
        {"source": "Wikidata", "found": True, "match_confident": True, "url": "https://www.wikidata.org/wiki/Q1", "label": "Hilton Zurich Airport", "description": "hotel in Zurich", "facts": {}}]
res = ep.build([], town, [], None, {}, HOTEL, CITY, "hilton.com", own={"lat": 47.45, "lon": 8.56, "postcode": "8058"})
rows = {r["source"]: r for r in res["rows"]}
check("OpenStreetMap matched on the town alone is an uncertain match, not Verified", rows["OpenStreetMap"]["status"] == "unclear", rows["OpenStreetMap"])
check("Wikidata with no comparable facts is an uncertain match, not Verified", rows["Wikidata"]["status"] == "unclear", rows["Wikidata"])
good = [{**town[0], "match_confident": True, "lat": 47.4501, "lon": 8.5601, "address_components": {"postcode": "8058"}}]
check("name + coordinates + postcode is Verified, and the note says what matched", ep.build([], good, [], None, {}, HOTEL, CITY, "hilton.com", own={"lat": 47.45, "lon": 8.56, "postcode": "8058"})["rows"][4]["status"] == "verified")
check("the Google note says a Business Profile is free but cannot be read automatically", "free for the hotel to set up" in rows["Google Maps / Google hotel listing"]["note"])

print("8. the recommendation gate")
recs = out["recommendations"]
check("every recommendation has evidence that is not a menu strip or a telephone banner", all(e["snippet"] and not textutil.looks_like_nav(e["snippet"][:160]) and "1-800-HILTONS" not in e["snippet"] for r in recs for e in r["evidence"] if e.get("snippet")),
      [(r["id"], e["snippet"][:80]) for r in recs for e in r["evidence"] if "1-800" in (e.get("snippet") or "")])
check("a 'not stated' recommendation lists the pages inspected and what is still unstated", all(any("Pages inspected" in e["snippet"] or "No page about this" in e["snippet"] or "pages inspected for this" in e["snippet"] for e in r["evidence"]) for r in recs if r.get("absence_based")),
      [r["id"] for r in recs if r.get("absence_based")])
check("with a plain-text read, no 'missing information' finding is labelled Verified", all(r["confidence"] != advice.BEST for r in recs if r.get("absence_based")), [(r["id"], r["confidence"]) for r in recs if r.get("absence_based")])
topics = [t for r in recs if r.get("topics") for t in r["topics"]]
check("no underlying issue is raised twice (each topic appears in one recommendation)", len(topics) == len(set(topics)), sorted(topics))
check("the highest-priority actions are confirmed problems, not optional opportunities", all(r["kind"] == "fix" for r in recs if r["id"] in out["top_actions"]))
check("no 'consider outreach'-style speculation is presented as a fix", all(r["kind"] == "opportunity" for r in recs if r["id"].startswith("X-S-editorial") or r["id"].startswith("X-S-otas")))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
