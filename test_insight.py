"""
Offline tests for the consultant layer: AI understanding, intents, unanswered
questions, location, consistency, hidden strengths, structured data, machine
readiness, readiness profile and the recommendation engine.

The principle under test: every recommendation comes from a finding with
evidence, in plain language, and a healthy site gets (almost) no advice.
Run: python test_insight.py
"""
import datetime as dt
import json

import advice
import consultant
import guest_questions as gq
import insight_content as ic
import insight_tech as it

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


BASE = "https://www.testhotel.com/"
HOTEL, CITY = "Test Hotel", "Leeds"


def page(path, text, *, title="", h1=(), tels=(), links=(), footer="", **sig):
    url = BASE.rstrip("/") + path
    s = {"meta_description": "", "canonical": url, "noindex": False, "structured": [], "images": {"total": 0, "no_alt": 0, "files": []},
         "pdfs": [], "word_count": len(text.split()), "js_shell": False, "faq_like_items": 0, "breadcrumb": False,
         "h1_count": len(h1) or 1, "headings": [], "jsonld_errors": 0, "og": {}}
    s.update(sig)
    return {"url": url, "title": title or "Page", "text": text, "h1": list(h1), "tels": list(tels), "mails": [],
            "links": [BASE.rstrip("/") + l for l in links], "signals": s, "footer_text": footer, "ok": True}


def guest_for(pages, conflicts=()):
    ev = gq.evaluate(pages)
    return {"questions": ev, "conflicts": list(conflicts), "own_facts_node": {}}


LONG = " ".join(["The hotel is a lovely place to stay with comfortable rooms and a warm welcome for every guest."] * 6)
HOME = page("/", "Test Hotel is a boutique hotel in Leeds city centre. " + LONG + " Our restaurant serves dinner nightly. "
            "Leeds station is a 6 minute walk from the hotel. Free parking for guests. Check-in is from 3pm and check-out is by 11am.",
            title="Test Hotel | Boutique hotel in Leeds", h1=["Test Hotel"], tels=["0113 111 2222"],
            links=["/meetings/", "/faq/", "/rooms/"], meta_description="A boutique hotel in Leeds city centre.")
MEET = page("/meetings/", "Our meeting rooms and conference suite host delegates. " + LONG, title="Meetings", h1=["Meetings"])
FAQ = page("/faq/", "Frequently asked questions. Is there parking? Yes, free parking for guests. " + LONG, title="FAQ", h1=["FAQ"],
           faq_like_items=4, headings=["Is there parking?", "What time is check-in?", "Are dogs allowed?"])
ROOMS = page("/rooms/", "Our rooms are comfortable. " + LONG, title="Rooms", h1=["Rooms"])
TERMS = page("/terms-conditions/", "Terms. Company registered at 1 Corporate Way, London W1S 4HQ. Call 020 7000 1111. "
             "We welcome children and corporate guests. Sustainable policy and carbon neutral. " + LONG, title="Terms", h1=["Terms"])
PAGES = [HOME, MEET, FAQ, ROOMS, TERMS]

print("1. policy pages are not evidence of what the hotel offers")
site = ic.Site(PAGES, BASE, HOTEL, CITY)
check("legal pages are excluded from content evidence", TERMS not in site.content_pages and len(site.content_pages) == 4)
fam = next(r for r in ic.intents(site) if r["key"] == "family")
sus = next(r for r in ic.intents(site) if r["key"] == "sustainable")
check("'children' and 'carbon neutral' in the terms page do not make Families or Sustainability a signal",
      fam["level"] == "none" and sus["level"] == "none", (fam["level"], sus["level"]))

print("2. AI understanding and intents - only from what is on the pages")
feats = ic.features(site)
intents = ic.intents(site)
u = ic.understanding(site, intents, feats, CITY)
check("the summary names the descriptor the homepage actually uses", "boutique hotel in Leeds" in u["summary"], u["summary"])
check("meetings are 'some/strong' with a reason that quotes the page",
      next(r for r in intents if r["key"] == "meetings")["level"] in ("some", "strong")
      and "“" in next(r for r in intents if r["key"] == "meetings")["reason"])
check("an intent with no evidence is 'none' - nothing is invented for it",
      next(r for r in intents if r["key"] == "beach")["level"] == "none" and next(r for r in intents if r["key"] == "beach")["reason"] == "")
check("core travellers with no evidence are listed as 'not stated', not as claims",
      any(w["why"] == "not stated on the pages read" for w in u["weak_signals"]))
check("an empty crawl gives no summary at all", ic.understanding(ic.Site([], BASE, HOTEL, CITY), [], [], CITY)["summary"] == "")
check("the summary carries an honest note about what it is", "not what the hotel is really like" in u["note"])

print("3. questions AI may struggle to answer")
g = guest_for(PAGES)
qs = ic.questions(site, g, intents, feats, [])
byid = {q["id"]: q for q in qs}
check("parking is answered (free, for guests) so it is NOT flagged", "parking" not in byid or byid["parking"]["state"] == "partial", byid.get("parking"))
check("meeting rooms exist but no capacity/AV is stated -> flagged with the exact missing items",
      "meeting_detail" in byid and "capacity (how many people)" in byid["meeting_detail"]["missing"], byid.get("meeting_detail"))
check("the answer is placed on the page that already covers the topic", byid["meeting_detail"]["where"]["label"] == "/meetings/")
check("a flagged question carries a worked example", byid["meeting_detail"]["example"])
check("no wedding question when the site never mentions weddings", "wedding_detail" not in byid)
check("no spa question when there is no spa", "spa_detail" not in byid and "pool_detail" not in byid)
check("rooms count is flagged when the site never states it", "room_count" in byid)
fullmeet = page("/meetings/", "Meeting rooms for delegates. Boardroom holds 12 delegates, theatre style 60 people. Every room has a projector and screen. "
                "Lunch and coffee catering. Contact the events team to enquire. " + LONG, title="Meetings")
q2 = ic.questions(ic.Site([HOME, fullmeet, FAQ, ROOMS], BASE, HOTEL, CITY), guest_for([HOME, fullmeet, FAQ, ROOMS]), intents, feats, [])
check("when capacity, layouts, AV, catering and contact are all stated there is nothing to flag",
      not any(q["id"] == "meeting_detail" for q in q2))

print("4. location - no invented distances")
osm = {"stations": [{"name": "Leeds", "km": 0.5, "tags": {}}, {"name": "Burley Park", "km": 2.1, "tags": {}}],
       "attractions": [{"name": "Royal Armouries", "km": 1.2, "lat": 53.79, "lon": -1.53, "tags": {"tourism": "museum", "website": "x"}},
                       {"name": "Armoury Cannon", "km": 1.25, "lat": 53.7903, "lon": -1.5301, "tags": {"wikidata": "Q9"}}],
       "airports": [], "venues": [], "hotels": []}
home2 = page("/", HOME["text"].replace("Leeds station is a 6 minute walk from the hotel.", "We are close to Leeds station and the Royal Armouries."),
             title=HOME["title"], h1=["Test Hotel"], links=["/meetings/", "/faq/"])
site2 = ic.Site([home2, MEET, FAQ, ROOMS], BASE, HOTEL, CITY)
loc = ic.location(site2, osm)
st = {(i["place"] or i["label"]): i for i in loc["items"]}
check("a station mentioned without a distance is flagged", st["Leeds station"]["state"] == "mentioned_no_distance", st.get("Leeds station"))
check("the straight-line figure is offered only as a labelled hint", "straight line" in st["Leeds station"]["hint"])
check("no travel time is ever invented (only an [X] placeholder)",
      not any(re.search(r"\b\d+[- ]minute", i["suggestion"] + i["hint"]) for i in loc["items"]) if (re := __import__("re")) else True)
check("an artefact inside a museum is not treated as an attraction", "Armoury Cannon" not in st)
check("an unmentioned minor station is not raised", "Burley Park station" not in st or st["Burley Park station"]["state"] != "mentioned_no_distance")
loc_ok = ic.location(ic.Site(PAGES, BASE, HOTEL, CITY), osm)
check("a station already described with a distance is 'stated' and is not nagged about other stations",
      any(i["state"] == "stated" for i in loc_ok["items"]) and
      not any(q["id"].startswith("loc_transport") for q in ic.questions(ic.Site(PAGES, BASE, HOTEL, CITY), g, intents, feats, loc_ok["items"])))
beach = page("/menu/", "Try our Beach Bar cocktail menu and the Sunset Beach sundae. " + LONG, title="Menu")
check("the word 'beach' on a menu is not a beach location signal",
      not any(i["category"] == "beach" for i in ic.location(ic.Site([HOME, beach], BASE, HOTEL, CITY), None)["items"]))
check("with no map data the report says so", "could not be retrieved" in ic.location(site2, None)["note"])

print("5. consistency inside the hotel's own pages")
call = page("/contact/", "Reservations: 0113 111 2222. Events line 0113 999 8888. " + LONG, title="Contact", tels=["0113 999 8888"])
cons = ic.consistency(ic.Site(PAGES + [call], BASE, HOTEL, CITY), guest_for(PAGES))
kinds = {c["type"] for c in cons}
check("two different telephone numbers are surfaced, with the pages", "phone" in kinds)
check("the operating company's phone and postcode on the terms page are NOT counted",
      "postcode" not in kinds and not any("20 7000" in v["value"] or "2070001111" in v["value"] for c in cons if c["type"] == "phone" for v in c["values"]))
conflict = {"fact": "Check-in time", "values": [{"value": "14:00", "source_url": BASE + "a"}, {"value": "15:00", "source_url": BASE + "b"}],
            "note": "different pages give different times"}
check("conflicting check-in times from the crawl are carried through as high severity",
      any(c["type"] == "times" and c["severity"] == "high" for c in ic.consistency(site, {"conflicts": [conflict]})))
names = [page("/a/", "Test Hotel & Spa welcomes you. " + LONG, title="Test Hotel & Spa", h1=["Test Hotel & Spa"]),
         page("/b/", "Test Hotel & Spa is lovely. " + LONG, title="Test Hotel & Spa", h1=["Test Hotel & Spa"]),
         page("/c/", "Test Hotel is lovely. " + LONG, title="Test Hotel", h1=["Test Hotel"]),
         page("/d/", "Test Hotel is great. " + LONG, title="Test Hotel", h1=["Test Hotel"])]
check("two name forms each used on several pages are flagged",
      any(c["type"] == "name" for c in ic.consistency(ic.Site(names, BASE, HOTEL, CITY), {})))
venue = [page("/a/", "Test Hotel & Restaurant. " + LONG, title="Test Hotel & Restaurant"), page("/b/", "Test Hotel & Restaurant. " + LONG, title="Test Hotel & Restaurant"),
         page("/c/", "Test Hotel. " + LONG, title="Test Hotel"), page("/d/", "Test Hotel. " + LONG, title="Test Hotel")]
check("'& Restaurant' labels a venue and is not reported as a second hotel name",
      not any(c["type"] == "name" for c in ic.consistency(ic.Site(venue, BASE, HOTEL, CITY), {})))
offers = page("/offers/", "Spring offer: book by 31 March 2023 for 20% off. " + LONG, title="Offers")
old = ic.consistency(ic.Site([HOME, offers], BASE, HOTEL, CITY), {}, today=dt.date(2026, 10, 5))
check("an offer whose date has passed is found, quoting the page", any(c["type"] == "old_offer" and "31 March 2023" in c["values"][0]["value"] for c in old), old)
check("a future offer is not flagged", not any(c["type"] == "old_offer" for c in ic.consistency(ic.Site([HOME, offers], BASE, HOTEL, CITY), {}, today=dt.date(2023, 1, 1))))
amen = [page("/a/", "Free on-site parking for all guests. " + LONG), page("/b/", "Parking is chargeable at £15 per night. " + LONG)]
am = [c for c in ic.consistency(ic.Site(amen, BASE, HOTEL, CITY), {}) if c["type"] == "amenity"]
check("opposite parking statements are flagged but as LOW (often resident vs visitor)", am and am[0]["severity"] == "low" and "residents" in am[0]["detail"])
bk = [page("/a/", "Breakfast is included in the room rate. " + LONG), page("/b/", "Non-resident breakfast £18.50 per person. " + LONG)]
check("a non-resident breakfast price is NOT a contradiction of 'breakfast included'",
      not any(c["type"] == "amenity" and "Breakfast" in c["title"] for c in ic.consistency(ic.Site(bk, BASE, HOTEL, CITY), {})))
hrs = [page("/a/", "The restaurant is open 6pm - 9pm. " + LONG), page("/b/", "Restaurant open 7pm - 10pm. " + LONG)]
check("different opening hours for the same venue are flagged", any(c["type"] == "hours" for c in ic.consistency(ic.Site(hrs, BASE, HOTEL, CITY), {})))
hrs2 = [page("/a/", "The restaurant is open 6pm - 9pm Monday to Friday. " + LONG), page("/b/", "Restaurant open 7pm - 10pm on weekends. " + LONG)]
check("day-specific hours are NOT flagged as a contradiction", not any(c["type"] == "hours" for c in ic.consistency(ic.Site(hrs2, BASE, HOTEL, CITY), {})))

print("6. hidden strengths")
menus = page("/dining/", "Our restaurant is open daily. " + LONG, title="Dining",
             pdfs=[{"url": BASE + f"menu{i}.pdf", "anchor": f"Menu {i}"} for i in range(8)])
meetpdf = page("/events/", "We host events. " + LONG, title="Events", pdfs=[{"url": BASE + "files/meeting-room-capacity.pdf", "anchor": "Capacity chart"}])
hs = ic.hidden_strengths(ic.Site([HOME, menus, meetpdf, FAQ], BASE, HOTEL, CITY), ic.features(ic.Site([HOME, menus, meetpdf, FAQ], BASE, HOTEL, CITY)))
menu_f = [h for h in hs if h["kind"] == "pdf" and h.get("menu")]
check("eight menu PDFs are ONE finding, not eight", len(menu_f) == 1 and "8 menus" in menu_f[0]["finding"], [h["finding"][:60] for h in hs])
check("a capacity chart that lives only in a PDF is its own finding", any(h["kind"] == "pdf" and not h.get("menu") for h in hs))
ev = page("/ev/", "We have EV charging points in the car park. " + LONG, title="Getting here")
hs2 = ic.hidden_strengths(ic.Site([HOME, ev, FAQ], BASE, HOTEL, CITY), ic.features(ic.Site([HOME, ev, FAQ], BASE, HOTEL, CITY)))
check("EV charging mentioned once, off the homepage and FAQ, is surfaced", any(h["kind"] == "once" and "EV" in h["label"] for h in hs2), [h["label"] for h in hs2])
check("a negated mention ('no gym') is not claimed as a feature",
      next(f for f in ic.features(ic.Site([page("/x/", "We have no gym on site. " + LONG)], BASE, HOTEL, CITY)) if f["key"] == "gym")["level"] == "none")
imgs = page("/rates/", "Rates", title="Rates", images={"total": 9, "no_alt": 9, "files": [{"src": "rates-table.jpg", "alt": ""}]}, word_count=20)
check("an image-only rates page is flagged as possibly holding facts in pictures",
      any(h["kind"] == "image" for h in ic.hidden_strengths(ic.Site([HOME, imgs], BASE, HOTEL, CITY), [])))

print("7. structured data - what it SAYS, not whether it exists")
node = {"types": ["Hotel"], "keys": ["name", "telephone", "address", "geo"], "name": "Test Hotel", "url": BASE, "telephone": "0113 000 0000",
        "address": {"streetAddress": "1 High St", "addressLocality": "Leeds", "postalCode": "LS1 1AA"}, "geo": {"latitude": "x", "longitude": "y"},
        "checkinTime": None, "checkoutTime": None, "priceRange": None, "starRating": False, "sameAs": [], "amenities": [],
        "aggregateRating": None, "image": False, "description": False, "n_questions": 0}
hp = page("/", HOME["text"], title=HOME["title"], tels=["0113 111 2222"], structured=[node])
sd = it.structured_audit(ic.Site([hp, FAQ], BASE, HOTEL, CITY), {"lat": 53.8, "lon": -1.5}, g, intents)
it_ = {i["item"]: i for i in sd["items"]}
check("a wrong telephone and non-numeric coordinates are caught as INCORRECT", it_["Is the markup correct?"]["status"] == "incorrect"
      and "0113 000 0000" in it_["Is the markup correct?"]["detail"] and "not numbers" in it_["Is the markup correct?"]["detail"], it_["Is the markup correct?"]["detail"])
check("missing image/description are reported as 'could improve'", it_["Hotel details"]["status"] == "could_improve")
sd0 = it.structured_audit(ic.Site(PAGES, BASE, HOTEL, CITY), None, g, intents)
check("no Hotel markup at all is 'missing'", next(i for i in sd0["items"] if i["item"].startswith("Hotel"))["status"] == "missing")
check("existing FAQ text without FAQ markup is 'could improve' and carries the caution about rich results",
      any(i["item"] == "FAQPage" and i["status"] == "could_improve" and "rich results" in i["advice"] for i in sd0["items"]))
check("self-published ratings are NEVER recommended", all(not i["advice"] or "independent" in i["advice"] for i in sd0["items"] if i["item"].startswith("Aggregate")))
check("the schema caution is always attached", "no evidence that adding it" in sd0["caution"])
bad = page("/", HOME["text"], title=HOME["title"], jsonld_errors=2)
check("unreadable JSON-LD is reported", any(i["item"] == "Valid JSON-LD" for i in it.structured_audit(ic.Site([bad], BASE, HOTEL, CITY), None, {}, intents)["items"]))

print("8. machine readiness - four separate buckets")
pm = [{"url": BASE + "rooms/", "ok": False, "reason": "HTTP 404", "status": 404, "title": ""},
      {"url": BASE + "spa/", "ok": True, "reason": "", "status": 200, "title": "Spa", "meta_description": "", "noindex": True, "h1_count": 1, "pdfs": [], "images_total": 20, "images_no_alt": 18, "js_shell": True},
      {"url": BASE + "book/", "ok": False, "reason": "no readable text (probably built with JavaScript)", "status": 200, "title": "Book", "js_shell": True},
      {"url": BASE + "a/", "ok": True, "title": "Same title", "meta_description": "", "h1_count": 1, "pdfs": []},
      {"url": BASE + "b/", "ok": True, "title": "Same title", "meta_description": "", "h1_count": 1, "pdfs": []}]
mach = it.machine_readiness(ic.Site(PAGES, BASE, HOTEL, CITY), pm, {"robots": {"present": True, "blocks_all": True}, "sitemap": {}, "ai_crawlers_blocked": ["GPTBot"]},
                            [], None, sd0, [], [])
ids = {f["id"]: f for f in mach}
check("robots blocking everything is critical", ids["robots_block_all"]["severity"] == "critical")
check("blocked AI crawlers are described as a choice, with the consequence", "choice" in ids["ai_blocked"]["consequence"])
check("a missing sitemap is reported", "sitemap_missing" in ids)
check("a JavaScript-only BOOKING page is informational, not a high-severity fault",
      ids.get("js_booking", {}).get("severity") == "low" and "js_empty" in ids and "/book/" not in ids["js_empty"]["detail"], ids.get("js_booking"))
check("noindex pages are high severity", ids["noindex"]["severity"] == "high")
check("broken pages are listed with their status codes", "404" in ids["http_errors"]["detail"])
check("duplicate titles are found", "dup_titles" in ids)
check("missing alt text is reported with the honest 'some may be decorative' caveat",
      "alt" in ids and "decorative" in ids["alt"]["detail"])
check("findings fall into exactly the four buckets",
      {f["bucket"] for f in mach} <= {"access", "understanding", "content", "authority"})
check("every finding states a consequence in plain words (the 'so what')",
      all(f["consequence"] for f in mach if f["status"] == "issue"))
check("the JavaScript finding says the crawl does not run JavaScript", "do not run JavaScript" in ids["js_empty"]["consequence"])

print("9. readiness profile - components, no single GEO number")
prof = it.readiness_profile(site, g, intents, loc_ok, sd0, mach, cons, None)
check("eight components", len(prof) == 8)
check("each component explains what drove it", all(p["drivers"] for p in prof))
check("components that cannot be measured are 'not assessed', not zero-scored",
      next(p for p in prof if p["key"] == "authority")["assessed"] is False)
check("there is deliberately no blended overall score", all("overall" not in p for p in prof))

print("10. recommendations - evidence in, advice out")
res = consultant.analyse(own_pages=PAGES, pages_meta=pm, base=BASE, hotel=HOTEL, city=CITY, location={"lat": 53.8, "lon": -1.5}, guest=g,
                         site={"robots": {"present": True}, "sitemap": {"present": True, "url_count": 5}}, entities=[], intel=None, osm_ctx=osm)
recs = res["recommendations"]
req = ("finding", "why", "evidence", "action", "priority", "effort", "confidence", "technical", "impact")
check("every recommendation has finding, why, evidence, action, priority, effort, impact and confidence",
      all(all(r.get(k) for k in req) for r in recs), [r["id"] for r in recs if not all(r.get(k) for k in req)])
check("every recommendation cites at least one piece of evidence", all(r["evidence"] and (r["evidence"][0]["snippet"] or r["evidence"][0]["url"]) for r in recs))
GENERIC = ("improve your website content", "add more structured data", "improve third-party presence", "optimise for ai search", "create faqs",
           "optimize for ai")
txt = " ".join((r["title"] + r["action"]).lower() for r in recs)
check("none of the banned generic recommendations appears", not any(p in txt for p in GENERIC))
check("no recommendation promises a ranking or an AI recommendation",
      not any(p in " ".join((r["why"] + r["action"] + r["finding"]).lower() for r in recs) for p in ("will boost", "guarantee", "llms prefer", "will make chatgpt", "will rank")))
check("page-level advice names the page and lists the exact additions",
      any(r["page"] and r["page"].get("label", "").startswith("/") and r["additions"] for r in recs))
check("priority and effort are from the allowed vocabularies",
      all(r["priority"] in ("critical", "high", "medium", "low") and r["effort"] in ("low", "medium", "high") for r in recs))
top = [r for r in recs if r["id"] in res["top_actions"]]
check("at most seven top actions", 1 <= len(res["top_actions"]) <= 7)
check("no more than three top actions come from any one kind of problem", max([sum(1 for r in top if r["category"] == c) for c in {r['category'] for r in top}] or [0]) <= 3)
check("quick wins are all low effort and none repeats a top action", all(r["effort"] == "low" for r in recs if r["id"] in res["quick_wins"])
      and not set(res["quick_wins"]) & set(res["top_actions"]))
check("the confidence label is one of the three honest levels",
      all(r["confidence"] in (advice.BEST, advice.INFER, advice.EXPER) for r in recs))
check("the report records what is already working", res["working"])
json.dumps(res, default=str)
check("the whole result is JSON-serialisable", True)

# a healthy site earns (almost) no advice
healthy_hotel = {"types": ["Hotel"], "keys": ["name"], "name": HOTEL, "url": BASE, "telephone": "0113 111 2222",
                 "address": {"streetAddress": "1 High St", "addressLocality": "Leeds", "postalCode": "LS1 1AA", "addressCountry": "GB"},
                 "geo": {"latitude": 53.8, "longitude": -1.5}, "checkinTime": "15:00", "checkoutTime": "11:00", "priceRange": None,
                 "starRating": False, "sameAs": ["https://facebook.com/x"], "amenities": [{"name": "Wi-Fi"}], "aggregateRating": None,
                 "image": True, "description": True, "n_questions": 0}
FULL = page("/", HOME["text"] + " Parking is free for guests and cannot be reserved. Breakfast is served 7am-10am and costs £12. "
            "Dogs are welcome for £10 a night. The hotel has step-free access and an accessible bedroom with a wet room and lift. "
            "We have family rooms that sleep 4 and connecting rooms. EV charging: 2 fast chargers, free for guests. Wi-Fi is free. "
            "Cancel free up to 24 hours before arrival; after that the first night is charged and not refunded. The hotel has 80 bedrooms. "
            "From the M1 junction 46 follow the A58 into Leeds; for sat-nav use LS1 1AA. Leeds station is a 6 minute walk. "
            "The restaurant is open 6pm - 9pm, book a table online, and caters for vegetarian, vegan and gluten-free diets.",
            title="Test Hotel | Boutique hotel in Leeds", h1=["Test Hotel"], tels=["0113 111 2222"], links=["/faq/"],
            meta_description="A boutique hotel in Leeds city centre.", structured=[healthy_hotel])
FILLER = [page(f"/info{i}/", f"Information page number {i}. " + LONG, title=f"Info {i} | Test Hotel Leeds", h1=[f"Info {i}"], meta_description="x", links=["/"]) for i in range(7)]
QUIET_PAGES = [FULL, page("/faq/", "Check-in is from 3pm and check-out by 11am. " + LONG, title="FAQ, Test Hotel Leeds", meta_description="x", links=["/"])] + FILLER
quiet = consultant.analyse(own_pages=QUIET_PAGES,
                           pages_meta=[{"url": p["url"], "ok": True, "title": p["title"], "meta_description": "x", "h1_count": 1, "pdfs": [], "images_total": 4, "images_no_alt": 0}
                                       for p in QUIET_PAGES],
                           base=BASE, hotel=HOTEL, city=CITY, location={"lat": 53.8, "lon": -1.5},
                           guest=guest_for(QUIET_PAGES),
                           site={"robots": {"present": True}, "sitemap": {"present": True, "url_count": 5}},
                           entities=[{"source": "OpenStreetMap", "found": True, "match_confident": True}], intel=None, osm_ctx=None)
bad_recs = [r for r in quiet["recommendations"] if r["priority"] in ("critical", "high")]
check("a well-built site gets no critical or high-priority advice", not bad_recs,
      [(q["id"], q["state"], q["missing"], q["found"]) for q in quiet["questions"]])
check("a well-built site is told what it is doing well", len(quiet["working"]) >= 3)

print("11. honesty about how much of the site was read")
import media  # noqa: E402
FAILED = [{"url": BASE + f"p{i}/", "ok": False, "reason": "timed out (time budget reached)", "status": None, "title": ""} for i in range(20)]
OKROWS = [{"url": p["url"], "ok": True, "title": p["title"], "meta_description": "x", "h1_count": 1, "pdfs": []} for p in PAGES]
part = consultant.analyse(own_pages=PAGES, pages_meta=OKROWS + FAILED, base=BASE, hotel=HOTEL, city=CITY, location={}, guest=g,
                          site={"robots": {"present": True}, "sitemap": {"present": True}}, entities=[], intel=None, osm_ctx=osm)
check("a partial read is flagged as limited, with the counts", part["coverage"]["limited"] and part["coverage"]["pages_read"] == 5
      and part["coverage"]["pages_attempted"] == 25, part["coverage"])
absence = [r for r in part["recommendations"] if r["source"] in ("questions", "location", "hidden")]
check("absence-based advice is capped at medium priority when much of the site wasn't read",
      absence and all(r["priority"] not in ("high", "critical") for r in absence), [(r["id"], r["priority"]) for r in absence])
check("...is marked lower-confidence and says why", all(r["confidence"] == advice.INFER and "pages could be read" in r["finding"] for r in absence))
check("the understanding note carries the caveat", "5 of 25 pages" in part["understanding"]["note"])
GONE = consultant.analyse(own_pages=[page("/", HOME["text"], title="x")], pages_meta=[{"url": BASE, "ok": True, "title": "x"}] + FAILED, base=BASE,
                          hotel=HOTEL, city=CITY, location={}, guest={"questions": [], "conflicts": [], "own_facts_node": {}},
                          site={"robots": {"present": False}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
check("with almost nothing read the site is declared unreadable", GONE["coverage"]["unreadable"])
check("...and NOTHING is claimed missing: no questions, no structured-data absence, no intents",
      not GONE["questions"] and not GONE["intents"] and not GONE["structured"]["items"] and not GONE["understanding"]["summary"])
check("...but the report explains what happened and what to check", any(r["id"] == "READ1" for r in GONE["recommendations"])
      and "timed out" in " ".join(f for r in GONE["recommendations"] if r["id"] == "READ1" for f in [r["finding"]]))
check("...and every readiness component is 'not assessed', not zero-scored", all(not p["assessed"] for p in GONE["profile"]))
check("...and no recommendation says the hotel's markup, pages or answers are missing",
      not any(w in (r["title"] + r["finding"]).lower() for r in GONE["recommendations"] for w in ("no hotel", "markup", "unanswered")))
check("a one-page crawl says the page count honestly ('only 1 page could be found'), not 'read 1 of 1'",
      "Only 1 page could be found to read" in consultant.crawl_coverage(1, [{"url": BASE, "ok": True}])["note"]
      and "We could only read 1 of 21 pages" in GONE["coverage"]["note"], GONE["coverage"]["note"])
_orig_from_intel = advice._from_intel
advice._from_intel = lambda intel: [
    advice._rec("M-entity_missing", "entity", "Get the hotel recognised in open map and knowledge data", "f", "w", [], "a", "medium", "low"),
    advice._rec("X-S-entity_missing:OpenStreetMap", "entity", "Add the hotel to OpenStreetMap", "f", "w", [], "a", "medium", "low")]
try:
    dd = advice.build(questions=[], location={"items": []}, consistency=[], hidden=[], structured={"items": []}, machine=[], intel=None,
                      jsonld_example=None, site=ic.Site([], BASE, HOTEL, CITY), coverage={})
finally:
    advice._from_intel = _orig_from_intel
dids = [r["id"] for r in dd]
check("the same entity finding is not listed twice (generic one dropped when the source-specific one exists)",
      "X-S-entity_missing:OpenStreetMap" in dids and "M-entity_missing" not in dids, dids)
_orig2 = advice._from_intel
advice._from_intel = lambda intel: [
    advice._rec("X-S-entity_missing:OpenStreetMap", "entity", "Add the hotel to OpenStreetMap", "f", "w", [], "a", "medium", "low")]
try:
    GONE2 = consultant.analyse(own_pages=[page("/", HOME["text"], title="x")], pages_meta=[{"url": BASE, "ok": True, "title": "x"}], base=BASE,
                               hotel=HOTEL, city=CITY, location={}, guest={"questions": [], "conflicts": [], "own_facts_node": {}},
                               site={"robots": {"present": False}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
finally:
    advice._from_intel = _orig2
ids2 = [r["id"] for r in GONE2["recommendations"]]
check("the unreadable-site path also never lists the entity finding twice", ids2.count("M-entity_missing") + sum(i.startswith("X-S-entity_missing") for i in ids2) <= 1, ids2)
check("a one-page site's READ1 says 'only 1 page', not 'read 1 of 1'",
      "Only 1 page(s) of the site could be found and read" in next(r for r in GONE2["recommendations"] if r["id"] == "READ1")["finding"])
json.dumps(GONE, default=str)
check("an unreadable-site result is still JSON-serialisable", True)
grouped = [r for r in res["recommendations"] if r["id"].startswith("Q")]
check("grouped question titles use readable short names, not lower-cased question text",
      all("?" not in r["title"] for r in grouped if r["title"].startswith("Fill the gaps")) and any(
          r["title"].startswith("Fill the gaps") and "Parking" in r["title"] for r in grouped), [r["title"] for r in grouped])
listing = {"candidates": [{"url": "https://luxe.com/w", "title": "Leeds hotels", "snippet": "", "roles": [], "source_type": "booking_platform", "label": "Luxe",
           "domain": "luxe.com", "via": "tavily", "published_search": None, "read": {"status": "not_read"},
           "match": {"level": "none"}, "page": {}}]}
listing["candidates"][0]["snippet"] = ("Grand Park Hotel 9.3 Free WiFi Breakfast. Test Hotel is nearby. Another Inn 8.1/10 great. Test Hotel 4.5 / 5 (120 reviews) Leeds")
rs2 = media.rating_signals(listing, HOTEL, CITY, evidence_ledger := __import__("evidence").Ledger())
check("a score that follows ANOTHER hotel's name is not attributed to this hotel; the one beside our name is",
      [(r["value"], r["scale"]) for r in rs2] == [(4.5, 5)], [(r["value"], r["scale"], r["text"][:40]) for r in rs2])

print("12. crawl efficiency and tidy-ups found by running on real hotels")
import site_check  # noqa: E402
import full_audit  # noqa: E402
from unittest import mock  # noqa: E402


class FakeResp:
    def __init__(self, code):
        self.status_code, self.text, self.url, self.headers = code, "<html></html>", "https://cache.test/p", {"Content-Type": "text/html"}


with mock.patch.object(site_check.requests, "get", return_value=FakeResp(200)) as rg:
    a1 = site_check.get("https://cache.test/page-a")
    a2 = site_check.get("https://cache.test/page-a")
check("the same page is fetched once per audit, not once per module (slow sites run out of time otherwise)", rg.call_count == 1 and a1 is a2)
with mock.patch.object(site_check.requests, "get", return_value=FakeResp(404)) as rg2:
    site_check.get("https://cache.test/missing")
    site_check.get("https://cache.test/missing")
check("an error response is NOT cached (a transient failure must be retried)", rg2.call_count == 2)
check("an HTML-escaped site title becomes a clean hotel name",
      full_audit.infer_hotel_name({"pages": [{"title": "Chewton Glen Hotel &amp; Spa | Luxury hotel in Hampshire"}]}) == "Chewton Glen Hotel & Spa")
bk = page("/dining/the-dining-room/booking/", "Book a table at the dining room. " + LONG, title="Book a table | Dining")
din = page("/dining/", "Our dining room and restaurant. " + LONG, title="Dining")
sb = ic.Site([HOME, bk, din], BASE, HOTEL, CITY)
check("an answer is never directed to a booking page", sb.best_page(("dining", "restaurant")).url if False else sb.best_page(("dining", "restaurant"))["url"].endswith("/dining/"))
wf = page("/", HOME["text"] + " Free Wi-Fi throughout. Wi-Fi is available in every room. Our bar serves cocktails. The bar is open late. " + LONG, title=HOME["title"], links=["/dining/"])
wf2 = page("/rooms/", "Wi-Fi in all rooms. Bar and lounge. " + LONG, title="Rooms")
wf3 = page("/about/", "Wi-Fi everywhere. The bar. " + LONG, title="About")
sw = ic.Site([wf, wf2, wf3], BASE, HOTEL, CITY)
fw = ic.features(sw)
check("Wi-Fi and 'bar' are not presented as strong, distinguishing signals",
      not any(x in ic.understanding(sw, ic.intents(sw), fw, CITY)["strong_signals"] for x in ("Wi-Fi", "Bar / lounge")))

print("13. one global judgement: serious risks outrank technical tidying")
import headline as hl  # noqa: E402
import ranking  # noqa: E402
rep_fix = json.load(open("tests_data/sample_report.json", encoding="utf8"))
real_intel = rep_fix["intel"]
site13 = [HOME, MEET, FAQ, ROOMS] + [page(f"/x{i}/", f"Page {i}. " + LONG, title=f"X{i}", meta_description="m", links=["/"]) for i in range(6)]
pm13 = [{"url": p["url"], "ok": True, "title": p["title"], "meta_description": "m", "h1_count": 1, "pdfs": []} for p in site13]
g13 = guest_for(site13)
res13 = consultant.analyse(own_pages=site13, pages_meta=pm13, base=BASE, hotel=HOTEL, city=CITY, location={}, guest=g13,
                           site={"robots": {"present": True}, "sitemap": {"present": True, "url_count": 9}}, entities=[], intel=real_intel, osm_ctx=None)
r13 = {r["id"]: r for r in res13["recommendations"]}
fsa = next((r for r in res13["recommendations"] if r["id"].startswith("X-F1")), None)
check("the 2/5 hygiene rating is among the recommendations", fsa is not None)
check("...and it IS in the top actions (the previous ranking left it out)", fsa and fsa["id"] in res13["top_actions"], res13["top_actions"])
sd1 = next((r for r in res13["recommendations"] if r["id"] == "SD1"), None)
check("a risk that guests can see outranks missing structured data", fsa and sd1 and fsa["rank"] > sd1["rank"], (fsa and fsa["rank"], sd1 and sd1["rank"]))
check("structured-data advice stays modest: it is not a top action when real fixes exist", sd1 is None or sd1["id"] not in res13["top_actions"])
check("every recommendation shows the factors behind its rank",
      all({"risk", "traveller", "visibility", "confidence"} <= set(r["factors"]) and r["value"] > 0 and r["rank"] > 0 for r in res13["recommendations"]))
check("the top actions are all REQUIRED FIXES", all(r13[i]["kind"] == "fix" for i in res13["top_actions"]))
check("segment-detail gaps are classed as opportunities, not fixes",
      all(r["kind"] == "opportunity" for r in res13["recommendations"] if r["id"].startswith("Q") and r["title"].startswith("If this is a target")))
check("an opportunity is never one of the top actions", not any(r13[i]["kind"] == "opportunity" for i in res13["top_actions"]))
check("top actions are capped at seven and sorted by rank", len(res13["top_actions"]) <= 7 and
      [r13[i]["rank"] for i in res13["top_actions"]] == sorted([r13[i]["rank"] for i in res13["top_actions"]], reverse=True))
check("every top action carries an expected outcome and a reference",
      all(r13[i]["expected_outcome"] and r13[i]["ref"] for i in res13["top_actions"]))
planned = [i for k in ("30", "60", "90") for i in res13["plan"][k]]
check("the 30/60/90 plan lists each recommendation at most once", len(planned) == len(set(planned)))
# a pure unit check on the model
mk = lambda src, tag, eff="low", conf=advice.BEST, cat="understanding": {"id": tag, "source": src, "tag": tag, "effort": eff, "confidence": conf,  # noqa: E731
                                                                         "category": cat, "question_ids": []}
fsa_u, sd_u = mk("intel", "F1", "medium"), mk("structured", "SD1")
ranking.annotate([fsa_u, sd_u], [])
check("model: hygiene (risk 5, traveller 5) scores far above markup (risk 1)", fsa_u["value"] > sd_u["value"] * 2, (fsa_u["value"], sd_u["value"]))
inf_u, bes_u = mk("consistency", "phone", conf=advice.INFER), mk("consistency", "phone")
ranking.annotate([inf_u, bes_u], [])
check("model: lower confidence lowers the value", inf_u["value"] < bes_u["value"])
blk = mk("machine", "robots_block_all")
ranking.annotate([blk], [])
check("model: 'critical' is reserved for blocking crawlers entirely", blk["priority"] == "critical" and fsa_u["priority"] == "high")

i3 = next((r for r in real_intel["recommendations"] if r["id"] == "I3"), None)
check("a finding that rests only on a search NOT finding something is low-confidence and cannot reach the top actions",
      all(r13[i]["confidence"] != advice.BEST for i in res13["top_actions"] if r13[i]["id"].startswith("X-I3")) and not any(
          r13[i]["id"].startswith("X-I3") for i in res13["top_actions"]), res13["top_actions"])

print("14. fixes versus commercial opportunities")
weak_home = page("/", "Test Hotel is a boutique hotel in Leeds. Our spa and restaurant are lovely. Romantic evenings are possible. " + LONG,
                 title="Test Hotel | Boutique hotel in Leeds", h1=["Test Hotel"], links=["/spa/"])
spa13 = page("/spa/", "Our spa has a sauna and treatment rooms. The restaurant serves afternoon tea. " + LONG, title="Spa")
sx = ic.Site([weak_home, spa13, FAQ], BASE, HOTEL, CITY)
ox = ic.opportunities(sx, ic.intents(sx), ic.features(sx))
check("a weak segment with real supporting assets is offered as an OPPORTUNITY", ox and ox[0]["key"] == "couples", [o["key"] for o in ox])
check("it is phrased conditionally, never as a defect", ox[0]["statement"].startswith("If ") and "target segment" in ox[0]["statement"]
      and "Not a defect" in ox[0]["caveat"])
check("it names the assets it rests on", "spa" in ox[0]["statement"].lower() and "restaurant" in ox[0]["statement"].lower())
check("a segment with no supporting assets is not suggested at all", not any(o["key"] == "weddings" for o in ox))

print("15. the headline is honest about coverage")
mkrep = lambda cov, overall=83: {"scorecard": {"overall": overall, "coverage_pct": cov, "categories": [  # noqa: E731
    {"key": "ai_visibility", "label": "AI Visibility", "weight": 25.0, "assessed": False, "score": None, "detail": "x"},
    {"key": "reviews", "label": "Reviews & Reputation", "weight": 15.0, "assessed": False, "score": None, "detail": "x"},
    {"key": "website", "label": "Website & Technical", "weight": 12.5, "assessed": True, "score": 83, "detail": "x"}]},
    "guest_questions": {"pages_ok": 5, "pages_attempted": 25}, "site": {}, "entities": [], "tavily_result": {}}
h60 = hl.build(mkrep(60.0))
check("60% coverage is labelled PROVISIONAL, with the coverage shown beside the score", h60["status"] == "provisional" and h60["score"] == 83
      and h60["coverage_pct"] == 60.0 and "60% of the full model" in h60["explanation"])
check("the explanation names what was not measured", "AI Visibility" in h60["explanation"] and "Reviews" in h60["explanation"])
check("it says the number is not a measure of how visible the hotel is to AI", "not as a measure of how visible it is to AI" in h60["explanation"])
h20 = hl.build(mkrep(20.0))
check("below 30% coverage NO single score is given", h20["status"] == "withheld" and h20["score"] is None)
hu = hl.build({**mkrep(60.0), "consultant": {"coverage": {"unreadable": True, "limited": True, "pages_read": 1}}})
check("an UNREADABLE website gets no headline score, even when other sources give 60% coverage",
      hu["status"] == "withheld" and hu["score"] is None and "could be read" in hu["explanation"])
hlim = hl.build({**mkrep(80.0), "consultant": {"coverage": {"unreadable": False, "limited": True, "pages_read": 5}}})
check("a limited crawl keeps the score provisional even at high coverage", hlim["status"] == "provisional" and hlim["score"] == 83)
check("the title never calls it 'AI visibility'", "readiness" in h60["title"].lower() and "visibility" not in h60["title"].lower())
hc = hl.build(mkrep(60.0))["category_evidence"]
check("a category read from only 5 pages is flagged as LOW evidence even if its score is high", hc["website"]["level"] == "low")
rr = hl.attach(mkrep(60.0))
check("evidence strength is attached to each assessed category and never to an unassessed one",
      rr["scorecard"]["categories"][2].get("evidence_level") == "low" and "evidence_level" not in rr["scorecard"]["categories"][0])

print("16. a score and the evidence behind it are separate")
osm_fail = {"stations": [{"name": "Leeds", "km": 0.4, "tags": {}}], "attractions": [], "airports": [], "venues": [], "hotels": [], "failed_parts": ["attractions", "airports"]}
site16 = [home2] + [page(f"/y{i}/", f"Page {i}. " + LONG, title=f"Y{i}", links=["/"]) for i in range(11)]
res16 = consultant.analyse(own_pages=site16, pages_meta=[{"url": p["url"], "ok": True, "title": p["title"], "meta_description": "m", "h1_count": 1, "pdfs": []} for p in site16],
                           base=BASE, hotel=HOTEL, city=CITY, location={}, guest=guest_for(site16), site={"robots": {"present": True}, "sitemap": {"present": True}},
                           entities=[], intel=None, osm_ctx=osm_fail)
locp = next(p for p in res16["profile"] if p["key"] == "location")
check("location with ONE place assessed and map data incomplete is LOW evidence", locp["evidence"]["level"] == "low", locp)
check("...and a thin score is marked provisional, never 'strong'", locp["band"] == "provisional" and "incomplete" in locp["evidence"]["why"])
check("every assessed component states its evidence strength",
      all(p["evidence"]["level"] in ("high", "medium", "low") and p["evidence"]["why"] for p in res16["profile"] if p["assessed"]))

print("17. careful language - no claim the audit can't prove")
BANNED = ("or guesses", "skips the hotel", "can't see pictures", "invisible to", "will repeat the wrong", "every machine", "becomes the authority",
          "cannot draw on", "won't be found", "llms prefer", "will boost", "guarantee")
texts = []
for src in (res13, res16, res, quiet):
    for r in src["recommendations"]:
        texts.append(" ".join([r["title"], r["finding"], r["why"], r["action"], r["technical"], r["expected_outcome"]]).lower())
    texts += [f["consequence"].lower() + " " + f["detail"].lower() for f in src["machine"]]
    texts += [i["advice"].lower() + " " + i["detail"].lower() for i in src["structured"]["items"]]
hit = sorted({b for b in BANNED for t in texts if b in t and not ("guarantee" in b and "no recommendation" in t)})
check("none of the overstated phrases appears in any recommendation or finding", not hit, hit)
check("the question rationale is appropriately cautious",
      advice.WHY_QUESTION.startswith("Guests look for this") and "less able to answer the question accurately or confidently" in advice.WHY_QUESTION)
alt = next(f for f in mach if f["id"] == "alt")
check("the image claim uses the careful wording",
      "less reliably discoverable, indexable and accessible than clear text and descriptive alt text" in alt["consequence"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
