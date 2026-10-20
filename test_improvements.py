"""
Offline tests for the report-quality improvements: scoring transparency, false-positive removal (awards, phone numbers, name forms, image text, missing-versus-unreadable), traveller requirement
checks, external presence, booking readiness, comparable hotels, structured data, the AI test log, and the recommendation gate. Synthetic sites only: no network, no keys.
Run: python test_improvements.py
"""
import copy
import json
import warnings

warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

import advice
import ai_sample
import booking_check
import competitors
import consultant
import external_presence as ep
import guest_questions as gq
import insight_content as ic
import media
import pagesignals
import ranking
import scoring
import traveller_ready as tr

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


BASE = "https://www.testhotel.com/"
HOTEL, CITY = "Test Hotel", "Leeds"
LONG = " ".join(["The hotel is a lovely place to stay with comfortable rooms and a warm welcome for every guest."] * 6)


def page(path, text, *, title="", h1=(), tels=(), links=(), footer="", **sig):
    url = BASE.rstrip("/") + path
    s = {"meta_description": "x", "canonical": url, "noindex": False, "structured": [], "images": {"total": 0, "no_alt": 0, "files": []}, "pdfs": [], "word_count": len(text.split()),
         "js_shell": False, "faq_like_items": 0, "breadcrumb": False, "h1_count": len(h1) or 1, "headings": [], "jsonld_errors": 0, "og": {}}
    s.update(sig)
    return {"url": url, "title": title or "Page", "text": text, "h1": list(h1), "tels": list(tels), "mails": [], "links": [BASE.rstrip("/") + l if l.startswith("/") else l for l in links],
            "signals": s, "footer_text": footer, "ok": True}


# ================================================================ 1. scoring transparency
print("1. the overall score is calculated and explained correctly")
cats = [{"key": "website", "label": "Website & Technical", "score": 60, "weight": 17.5, "assessed": True}, {"key": "entity", "label": "Entity Consistency", "score": 100, "weight": 5.0, "assessed": True},
        {"key": "social", "label": "Social & UGC", "score": 40, "weight": 7.5, "assessed": True, "partial": True},
        {"key": "ai_visibility", "label": "AI Visibility", "score": None, "weight": 25.0, "assessed": False}, {"key": "reviews", "label": "Reviews & Reputation", "score": None, "weight": 15.0, "assessed": False}]
t = scoring.totals(cats)
expected = (60 * 17.5 + 100 * 5 + 40 * 7.5) / (17.5 + 5 + 7.5)
check("overall = sum(score x weight) / sum(weights) over the assessed categories only", t["overall"] == round(expected) and abs(sum(b["points"] for b in t["breakdown"]) - expected) < 0.3, (t["overall"], expected))
check("categories that were not measured are left out, never counted as zero", len(t["breakdown"]) == 3 and t["coverage_pct"] == 30.0 and "Reviews & Reputation" in t["method"] and "left out of the sum rather than counted as zero" in t["method"])
cats_ai = cats[:3] + [{"key": "ai_visibility", "label": "Observed AI visibility", "score": 10, "weight": 0.0, "assessed": True, "separate": True}]
check("observed AI visibility never enters the readiness calculation, even when it was measured and scored", scoring.totals(cats_ai)["overall"] == scoring.totals(cats[:3])["overall"] and all(b["key"] != "ai_visibility" for b in scoring.totals(cats_ai)["breakdown"]))
check("the readiness weights add up to 100 and AI visibility has none", abs(sum(scoring.WEIGHTS[k] for k in scoring.WEIGHTS if k != "freshness") - 100) < 0.01 and scoring.WEIGHTS["ai_visibility"] == 0)
check("the plain average is shown only to explain the difference, and differs from the weighted score here", t["simple_average"] == 67 and "plain average" in t["method"] and t["overall"] != t["simple_average"], t)
check("each row carries its weight, its share of the measured weight and why it has that weight", all(b["share_pct"] and b["why"] for b in t["breakdown"]) and abs(sum(b["share_pct"] for b in t["breakdown"]) - 100) < 0.3)
site0 = {"robots": {"present": True}, "sitemap": {}, "pages": [], "schema_types_found": [], "ai_crawlers_blocked": []}
sc = scoring.build_scorecard(site0, [], [], {}, {"profiles": []}, guest_result={"pages_ok": 6, "pages_attempted": 6, "questions": [], "conflicts": [], "own_facts_node": {}})
check("the scorecard itself carries the breakdown and the method, and its overall equals the breakdown's total",
      sc.get("breakdown") is not None and sc["method"] and sc["overall"] == scoring.totals(sc["categories"])["overall"])
import headline
h = headline.build({"scorecard": sc, "guest_questions": {}, "site": {}, "entities": [], "consistency": [], "tavily_result": {}})
check("the headline says readiness is not observed AI visibility", "observed ai visibility" in h["readiness_vs_visibility"].lower() and "not part of this number" in h["readiness_vs_visibility"])
ai_cat = scoring.build_scorecard(site0, [], [], {}, {"profiles": []}, guest_result={"pages_ok": 6, "pages_attempted": 6})
check("AI visibility is a separate, unmeasured category when nothing was asked (never folded into readiness)", next(c for c in ai_cat["categories"] if c["key"] == "ai_visibility")["assessed"] is False)

# ================================================================ 2. false positives
print("2. recommendations only when the evidence relates to the hotel")
tea = ("Our 1907 bar & grill serves hand-blended whole leaf, plastic free tea from an independent award winning British tea brand. Wild Idol alcohol free sparkling wine is served in our bar.")
check("'award winning' in a sentence about a tea supplier is not an award claim by the hotel",
      media._award_hits(tea, "Brooklands Hotel", "/sustainability-policy/") == [] and media._award_hits(tea, "Brooklands Hotel", "/about-us/") == [])
check("'our award-winning spa' IS the hotel's claim", len(media._award_hits("Relax in our award-winning spa, open daily.", "Test Hotel", "/spa/")) == 1)
check("a named scheme on the hotel's own page is a claim ('AA 3 rosettes')", len(media._award_hits("The restaurant holds 3 AA rosettes.", "Test Hotel", "/eat/")) == 1)
check("unclear wording on a policy page is dropped, but on the About page it is kept", media._award_hits("Winner of Best Hotel 2024.", "Test Hotel", "/sustainability-policy/") == [] and len(media._award_hits("Winner of Best Hotel 2024.", "Test Hotel", "/about-us/")) == 1)
check("wording about a coffee roaster partner is not the hotel's", media._award_hits("We serve coffee from a family roaster, an award-winning supplier.", "Test Hotel", "/about-us/") == [])

home = page("/", "Test Hotel Leeds. Reservations: 0113 111 2222. " + LONG, title="Test Hotel", h1=["Test Hotel"], tels=["0113 111 2222"])
events = page("/weddings/", "Weddings at Test Hotel. Call our wedding team on 0113 555 4444. " + LONG, title="Weddings", tels=["0113 555 4444"])
cons = ic.consistency(ic.Site([home, events], BASE, HOTEL, CITY), {})
check("a second number on the wedding page is a department line, not an inconsistency", not any(c["type"] == "phone" for c in cons))
a = page("/contact/", "Call us on 0113 111 2222." + LONG, title="Contact", tels=["0113 111 2222"])
b = page("/rooms/", "Book on 0113 888 9999. " + LONG, title="Rooms", tels=["0113 888 9999"])
check("two unlabelled numbers on ordinary pages ARE raised", any(c["type"] == "phone" for c in ic.consistency(ic.Site([home, a, b], BASE, HOTEL, CITY), {})))

soup = BeautifulSoup('<img src="data:image/gif;base64,R0lGODlhBAADAIAAAAAAAAAAACH5BAEAAAAALAAAAAAEAAMAAAIDhI9WADs=" data-src="/img/room-1.jpg"><img src="/img/room-2.jpg" alt="King room with a view">'
                     '<img src="https://www.facebook.com/tr?id=1" width="1" height="1"><img src="data:image/gif;base64,AAAA"><img src="/icons/phone.svg"><img src="/img/logo.png"><img src="/img/spa-pool.jpg">', "html.parser")
im = pagesignals.image_summary(soup, "https://x.com/rooms/deluxe/")
check("a lazy-load placeholder uses the real file, and tracking pixels, base64 placeholders, icons and logos are not content images",
      im["total"] == 7 and im["content"] == 3 and im["skipped"]["tracking"] == 1 and im["skipped"]["placeholders"] == 1 and im["skipped"]["decorative"] == 2, im)
check("of the content images, those without alt text on room and spa pictures are the key ones", im["no_alt"] == 2 and im["key_no_alt"] == 2 and {f["kind"] for f in im["key_files"]} == {"room", "spa"}, im)
import insight_tech as it
pm = [{"url": BASE + "rooms/", "ok": True, "images_total": 40, "images_content": 12, "images_no_alt": 12, "images_key": 12, "images_key_no_alt": 12, "images_key_kinds": {"room": 9, "spa": 3}, "images_skipped": {"placeholders": 25, "tracking": 3, "decorative": 0}}]
rp = page("/rooms/", "Rooms. " + LONG, title="Rooms", images={"total": 40, "content": 12, "no_alt": 12, "key": 12, "key_no_alt": 12, "key_files": [{"src": "dbl.jpg", "kind": "room"}], "skipped": {}, "files": []})
finds = it.machine_readiness(ic.Site([home, rp], BASE, HOTEL, CITY), pm, {"robots": {"present": True}, "sitemap": {"present": True}}, [], None, {"items": [], "hotel_found": False}, [], [], None)
alt = next((f for f in finds if f["id"] == "alt"), None)
check("the alt-text finding counts content images only, names the pages, and says what was left out", alt is not None and "12 of 12" in alt["title"] and "28 placeholder, tracking or decorative" in alt["detail"] and "room (9)" in alt["detail"] and "spa and pool (3)" in alt["detail"] and alt["evidence"][0]["url"].endswith("/rooms/"), alt and alt["detail"])
pm2 = [{"url": BASE + "rooms/", "ok": True, "images_total": 1200, "images_content": 6, "images_no_alt": 0, "images_key": 6, "images_key_no_alt": 0, "images_skipped": {"placeholders": 1194, "tracking": 0, "decorative": 0}}]
finds2 = it.machine_readiness(ic.Site([home], BASE, HOTEL, CITY), pm2, {"robots": {"present": True}, "sitemap": {"present": True}}, [], None, {"items": [], "hotel_found": False}, [], [], None)
check("1,194 base64 placeholders do not make 1,200 images 'missing alt text'", not any(f["id"] == "alt" and f["status"] == "issue" for f in finds2))

# ================================================================ 3. traveller requirements
print("3. traveller recommendation readiness is judged by requirement, from evidence")
spa_page = page("/spa/", "The Spa has a sauna, steam room and treatments. Open daily 9am-8pm. Day guests welcome with a day pass; hotel guests have complimentary access. Guests must be over 16. Book in advance. " + LONG, title="Spa")
rooms_page = page("/rooms/", "Our Classic Double has a king-size bed and a balcony. " + LONG, title="Rooms")
fam_page = page("/rooms/family/", "Family rooms are available. Cots and extra beds are provided; children under 12 stay free. We have a children's menu and a garden. " + LONG, title="Family rooms")
meet_page = page("/meetings/", "Meeting rooms for conferences: the Boardroom holds up to 12 delegates, the Hall 120 theatre-style. Projector and screen in every room. Contact our events team. " + LONG, title="Meetings")
faq_page = page("/faq/", "Free Wi-Fi throughout. Parking is free for guests, 40 spaces on site. " + LONG, title="FAQ")
contact = page("/contact/", "Leeds station is a 6 minute walk. Leeds Bradford Airport is 14 miles away, 30 minutes by car. " + LONG, title="Contact")
pages = [home, spa_page, rooms_page, fam_page, meet_page, faq_page, contact]
s1 = ic.Site(pages, BASE, HOTEL, CITY)
cov_ok = consultant.crawl_coverage(len(pages), [{"url": p["url"], "ok": True} for p in pages])
res = tr.run(s1, ic.features(s1), ic.intents(s1), cov_ok, ic.location(s1, None))
by = {s["key"]: {r["id"]: r for r in s["requirements"]} for s in res["segments"]}
check("segments are assessed only where the site shows the hotel offers what that traveller comes for", {"spa_couples", "families", "business"} <= set(res["assessed"]), res["assessed"])
check("spa facilities with access conditions are Confirmed, quoting the page", by["spa_couples"]["spa_facilities"]["state"] == "confirmed" and by["spa_couples"]["spa_facilities"]["found"][0]["url"].endswith("/spa/"))
check("an optional offer the site never mentions (couples' packages) is Unknown and never Missing", by["spa_couples"]["couples_packages"]["state"] == "unknown" and by["families"]["connecting"]["state"] == "unknown")
check("family occupancy is judged Missing when the pages read give no sleeps/occupancy", by["families"]["occupancy"]["state"] == "missing", by["families"]["occupancy"]["state"])
check("what is missing names the exact information and the existing page to add it to, never a new page", by["families"]["occupancy"]["add"] and by["families"]["occupancy"]["where"]["url"].endswith("/rooms/family/") and not by["families"]["occupancy"]["where"]["new_page"])
check("business: Wi-Fi, parking, meeting rooms and transport are Confirmed from the pages", all(by["business"][k]["state"] == "confirmed" for k in ("wifi", "parking", "meetings", "transport")), {k: v["state"] for k, v in by["business"].items()})
check("location: the station and airport are Confirmed with their times", by["location"]["loc_transport"]["state"] == "confirmed" and by["location"]["loc_airports"]["state"] == "confirmed")
repeat = page("/romantic/", "Romantic romantic romantic romantic couples romantic honeymoon romantic. " * 20, title="Romantic")
res_r = tr.run(ic.Site([home, repeat, spa_page], BASE, HOTEL, CITY), ic.features(ic.Site([home, repeat, spa_page], BASE, HOTEL, CITY)), ic.intents(ic.Site([home, repeat, spa_page], BASE, HOTEL, CITY)), cov_ok, None)
rr = {r["id"]: r for s in res_r["segments"] if s["key"] == "spa_couples" for r in s["requirements"]}
check("repeating 'romantic' confirms nothing: couples' packages stay Unknown", rr["couples_packages"]["state"] == "unknown")
check("a segment with no sign of the offer is not assessed at all (no family rooms: no family segment)", "families" not in tr.run(ic.Site([home, contact], BASE, HOTEL, CITY), ic.features(ic.Site([home, contact], BASE, HOTEL, CITY)), ic.intents(ic.Site([home, contact], BASE, HOTEL, CITY)), cov_ok, None)["assessed"])
collapsed_fam = page("/rooms/family/", "Bright Family Rooms with flexible beds. Amenities Things to know Share this page Take a tour Book now", title="Family rooms")
sc_ = ic.Site([home, collapsed_fam, spa_page, faq_page], BASE, HOTEL, CITY)
res_c = tr.run(sc_, ic.features(sc_), ic.intents(sc_), cov_ok, None)
fo = {r["id"]: r for s in res_c["segments"] if s["key"] == "families" for r in s["requirements"]}
check("a page whose 'Amenities / Things to know' sections have no text in the page as read makes absence Unknown, not Missing", fo["occupancy"]["state"] == "unknown" and "sections" in fo["occupancy"]["why"], fo["occupancy"])
cov_lim = consultant.crawl_coverage(3, [{"url": f"{BASE}p{i}/", "ok": i < 3} for i in range(20)])
res_l = tr.run(ic.Site([home, spa_page, rooms_page], BASE, HOTEL, CITY), ic.features(ic.Site([home, spa_page, rooms_page], BASE, HOTEL, CITY)), ic.intents(ic.Site([home, spa_page, rooms_page], BASE, HOTEL, CITY)), cov_lim, None)
check("with only 3 of 20 pages read, nothing is claimed Missing", all(r["state"] != "missing" for s in res_l["segments"] for r in s["requirements"]))
recs_t = advice._from_traveller(res, cov_ok)
fam_rec = next(r for r in recs_t if r["id"] == "TR-families")
check("the recommendation names exactly what to add, on which existing page, with evidence and an owner", "maximum number of adults and children" in " ".join(fam_rec["additions"]) and fam_rec["page"]["url"].endswith("/rooms/family/") and fam_rec["evidence"] and fam_rec["team"] == "operations")
check("no recommendation is made for Unknown requirements", all("couples" not in " ".join(r["additions"]).lower() for r in recs_t))
journey = [{"category": "attractions", "label": "Attractions", "place": "Royal Armouries", "state": "stated", "open_data_km": 3.0, "evidence": [{"url": BASE, "snippet": "Royal Armouries is a 5 minute walk from the hotel"}]}]
jc = tr._journey_checks(journey)
check("a stated walking time that is impossibly short against the map's straight line is flagged for checking", jc and jc[0]["plausible"] is False, jc)

# ================================================================ 4. external presence
print("4. external sources: identified, verified, contradicting, or not verified")
fp = [{"platform": "Booking.com", "discovered": True, "url": "https://www.booking.com/hotel/gb/test-hotel.html", "title": "Test Hotel, Leeds - Booking.com", "location_confirmed": True},
      {"platform": "Expedia", "discovered": True, "url": "https://www.expedia.co.uk/Leeds-Hotels-Best.guide", "title": "Best hotels in Leeds", "location_confirmed": True},
      {"platform": "TripAdvisor", "discovered": False, "url": "", "title": "", "location_confirmed": None}]
lc = {"rows": [{"platform": "Booking.com", "fact": "Check-in time", "listing_says": "14:00", "site_says": "15:00", "status": "differs", "url": "https://www.booking.com/hotel/gb/test-hotel.html", "passage": "from 14:00"}]}
ents = [{"source": "OpenStreetMap", "found": True, "match_confident": True, "url": "https://www.openstreetmap.org/way/1", "display_name": "Test Hotel, Leeds", "lat": 53.8001, "lon": -1.5001,
         "address_components": {"postcode": "LS1 1AA"}, "facts": {"name": "Test Hotel", "url": "https://other-site.com/"}, "match_reason": "0.1km"},
        {"source": "Wikidata", "found": False}]
OWN = {"lat": 53.8, "lon": -1.5, "postcode": "LS1 1AA", "phone": "0113 111 2222"}
crows = [{"field": "name", "domain": "OpenStreetMap", "own_site_value": "Test Hotel", "other_source_value": "Test Hotel", "verdict": "consistent"},
         {"field": "telephone", "domain": "OpenStreetMap", "own_site_value": "0113 111 2222", "other_source_value": "0113 999 0000", "verdict": "significant discrepancy"}]
media_ = {"articles": [{"publisher": "Good Travel", "publisher_key": "gt", "source_type": "news_or_magazine", "type": "review", "substance": "feature", "match": "high", "freshness": "recent", "url": "https://gt.example/a", "title": "t"},
                       {"publisher": "Paid", "publisher_key": "pd", "source_type": "blog", "type": "sponsored", "substance": "feature", "match": "high", "freshness": "recent", "url": "https://pd.example/a", "title": "t"}]}
x = ep.build(fp, ents, crows, lc, media_, HOTEL, CITY, "testhotel.com", own=OWN)
rows = {r["source"]: r for r in x["rows"]}
check("a listing whose own fact differs from the website contradicts it (check-in 14:00 against 15:00)", rows["Booking.com"]["status"] == "contradicts" and "14:00" in rows["Booking.com"]["contradictions"][0])
check("a guide or list page is never taken as the hotel's own listing", rows["Expedia"]["status"] == "unclear" and rows["Expedia"]["identified"] is False)
check("a platform not found is Not verified (never 'missing')", rows["Tripadvisor"]["status"] == "not_verified" and "does not show the hotel is not listed" in rows["Tripadvisor"]["note"])
check("Google cannot be checked reliably and says so", rows["Google Maps / Google hotel listing"]["status"] == "not_verified" and "does not allow automated reading" in rows["Google Maps / Google hotel listing"]["note"])
# an entry is only Verified on several identifiers: the name plus coordinates, postcode, website or telephone. The same town is not enough.
town_only = [{"source": "OpenStreetMap", "found": True, "match_confident": None, "url": "https://www.openstreetmap.org/way/2", "display_name": "Test Hotel, Leeds", "facts": {}, "address_components": {"city": "Leeds"}}]
check("an open-data entry matched only on the town is an uncertain match, never Verified", ep.build([], town_only, [], None, {}, HOTEL, CITY, "testhotel.com", own=OWN)["rows"][4]["status"] == "unclear")
good = [{"source": "OpenStreetMap", "found": True, "match_confident": True, "url": "https://www.openstreetmap.org/way/3", "display_name": "Test Hotel, Leeds", "lat": 53.8002, "lon": -1.5002, "address_components": {"postcode": "LS1 1AA"},
         "facts": {"url": "https://www.testhotel.com/", "telephone": "+44 113 111 2222"}}]
vg = ep.build([], good, [], None, {}, HOTEL, CITY, "testhotel.com", own=OWN)["rows"][4]
check("name + coordinates + postcode + website + telephone make it Verified, and the note lists what matched", vg["status"] == "verified" and all(w in vg["note"] for w in ("coordinates", "postcode", "official website", "telephone")), vg["note"])
far = [{**good[0], "lat": 53.9, "lon": -1.7, "address_components": {"postcode": "M1 1AA"}, "facts": {}}]
check("same name but 15 km away and a different postcode is not a match", ep.build([], far, [], None, {}, HOTEL, CITY, "testhotel.com", own=OWN)["rows"][4]["status"] == "unclear")
wd = [{"source": "Wikidata", "found": True, "match_confident": True, "url": "https://www.wikidata.org/wiki/Q1", "label": "Test Hotel", "description": "hotel in Leeds", "facts": {}}]
check("a Wikidata entry with only a name and a town in its description is an uncertain match", ep.build([], wd, [], None, {}, HOTEL, CITY, "testhotel.com", own=OWN)["rows"][5]["status"] == "unclear")
wd2 = [{**wd[0], "lat": 53.8001, "lon": -1.5001, "facts": {"url": "https://testhotel.com"}}]
check("with coordinates and the official website recorded, Wikidata can be Verified", ep.build([], wd2, [], None, {}, HOTEL, CITY, "testhotel.com", own=OWN)["rows"][5]["status"] == "verified")
check("the Google note says a Business Profile is free but cannot be read automatically", "free for the hotel to set up" in ep.build([], [], [], None, {}, HOTEL, CITY, "testhotel.com")["rows"][0]["note"] and "has no free listing service" not in ep.build([], [], [], None, {}, HOTEL, CITY, "testhotel.com")["rows"][0]["note"])
check("open data is Verified by reading it, and a different website link and a different phone number are contradictions", rows["OpenStreetMap"]["read"] and rows["OpenStreetMap"]["status"] == "contradicts" and any("other-site.com" in c for c in rows["OpenStreetMap"]["contradictions"]) and any("telephone" in c for c in rows["OpenStreetMap"]["contradictions"]))
check("an open-data source with no entry is Not verified, not 'wrong'", rows["Wikidata"]["status"] == "not_verified")
check("sponsored coverage counts for nothing; the rest is weighed by quality", x["publications"]["sponsored_excluded"] == 1 and x["publications"]["publishers"] == 1)
many = {"articles": [{"publisher": f"Blog {i}", "publisher_key": f"b{i}", "source_type": "blog", "type": "roundup", "substance": "passing mention", "match": "medium", "freshness": "old", "url": f"https://b{i}.example/", "title": "t"} for i in range(8)]}
few = {"articles": [{"publisher": "Good Travel", "publisher_key": "gt", "source_type": "news_or_magazine", "type": "review", "substance": "feature", "match": "high", "freshness": "recent", "url": "https://gt.example/a", "title": "t"}]}
sm, sf = ep.authority_score(ep.build([], [], [], None, many, HOTEL, CITY, "testhotel.com")), ep.authority_score(ep.build([], [], [], None, few, HOTEL, CITY, "testhotel.com"))
check("eight weak roundup mentions score below one substantial independent feature (quality over count)", sm < sf + 10, (sm, sf))
check("the external score is capped, and contradictions subtract", ep.authority_score(x) < 70 and ep.authority_score(x) < ep.authority_score(ep.build(fp, ents, [], None, media_, HOTEL, CITY, "testhotel.com")))
check("no score at all when nothing was checked", ep.authority_score(None) is None)
recs_e = advice._from_external(x)
check("open-data contradictions become a recommendation with evidence; a Not-verified source raises none", any(r["id"] == "EX1" and r["evidence"] for r in recs_e) and not any("Tripadvisor" in r["title"] for r in recs_e))

# ================================================================ 5. booking readiness
print("5. booking readiness")
links_ok = [{"url": "https://www.testhotel.com/rooms/", "anchor": "Rooms"}, {"url": "https://book.synxis.com/rez.aspx?hotel=1", "anchor": "Book now"}, {"url": "tel:+441131112222", "anchor": "Call"},
            {"url": "https://www.testhotel.com/old-page/", "anchor": "Offers"}, {"url": "https://www.testhotel.com/gone/", "anchor": "Gone"}]


def fake_fetch(url):
    if "synxis" in url:
        return {"status": 200, "final": url, "state": "ok"}
    if "gone" in url:
        return {"status": 404, "final": url, "state": "broken"}
    return {"status": 200, "final": url, "state": "ok"}


bk = booking_check.run("https://www.testhotel.com/", links_ok, [home, rooms_page], [{"url": "https://www.testhotel.com/", "ok": True, "status": 200, "is_start": True}], fetch=fake_fetch)
ck = {c["id"]: c for c in bk["checks"]}
check("a booking engine linked from the homepage is identified by its label and domain", ck["link"]["state"] == "pass" and "synxis" in ck["link"]["url"].lower() or "SynXis" in ck["link"]["detail"])
check("the destination answering is verified, and a broken own link is found", ck["destination"]["state"] == "pass" and ck["links"]["state"] == "fail" and any("/gone/" in b["url"] for b in bk["broken_links"]))
refused = booking_check.run("https://www.testhotel.com/", links_ok[:2], [home], [], fetch=lambda u: {"status": 403, "final": u, "state": "refused"})
check("a destination that refuses the automated check is Not verified, never broken", {c["id"]: c for c in refused["checks"]}["destination"]["state"] == "not_verified")
dead = booking_check.run("https://www.testhotel.com/", links_ok[:2], [home], [], fetch=lambda u: {"status": 404, "final": u, "state": "broken"})
check("a 404 booking destination is a Problem, with a high-priority recommendation", {c["id"]: c for c in dead["checks"]}["destination"]["state"] == "fail" and any(r["id"] == "BK2" for r in advice._from_booking(dead)))
none = booking_check.run("https://www.testhotel.com/", [{"url": "https://www.testhotel.com/rooms/", "anchor": "Rooms"}], [home], [], fetch=fake_fetch)
check("no booking link on the homepage is reported as not identifiable (a script may add it), with an inference-level recommendation",
      {c["id"]: c for c in none["checks"]}["link"]["state"] == "fail" and next(r for r in advice._from_booking(none) if r["id"] == "BK1")["confidence"] == advice.INFER)
panel_links = [{"url": "https://www.testhotel.com/#book", "anchor": "Book now"}, {"url": "https://be.synxis.com/?Hotel=1", "anchor": "Book a stay"}]
bk_panel = booking_check.run("https://www.testhotel.com/", panel_links, [home], [], fetch=fake_fetch)
check("a '#book' control on the homepage itself is a booking panel; the real destination (the engine) is the one checked",
      "SynXis" in {c["id"]: c for c in bk_panel["checks"]}["link"]["detail"] and "booking panel" in {c["id"]: c for c in bk_panel["checks"]}["link"]["detail"] and {c["id"]: c for c in bk_panel["checks"]}["destination"]["state"] == "pass")
check("a table-booking link is kept apart from a room booking", not booking_check.candidates([{"url": "https://www.opentable.com/r/test", "anchor": "Book a table"}], BASE)[0]["room_booking"])
check("it does not read rooms, prices or availability, and says so", any("Rooms, prices and availability were not looked at" in l for l in bk["limits"]))
check("no homepage links at all: not checked, with a reason", booking_check.run(BASE, [], [], [])["status"] == "unavailable")

# ================================================================ 6. comparable hotels
print("6. comparable hotels: only comparable, only where both were read")
own_pages = [page("/", "Test Hotel is a 4-star hotel with 60 bedrooms. Spa, restaurant and meeting rooms. " + LONG, title="Test Hotel", links=["/spa/"]),
             page("/spa/", "The spa has a sauna and steam room. Open daily 9am-8pm. " + LONG, title="Spa")]
osm = {"hotels": [{"name": "Rival One", "km": 0.8, "tags": {"website": "https://rival1.example/", "tourism": "hotel", "stars": "4"}},
                  {"name": "Rival Two", "km": 1.0, "tags": {"website": "https://rival2.example/", "tourism": "hotel"}},
                  {"name": "Budget Inn", "km": 0.2, "tags": {"website": "https://budget.example/", "tourism": "hotel", "stars": "2"}},
                  {"name": "No Site Hotel", "km": 0.3, "tags": {"tourism": "hotel"}},
                  {"name": "Same Site", "km": 0.4, "tags": {"website": "https://www.testhotel.com/", "tourism": "hotel"}}]}
RIVAL1 = {"https://rival1.example/": "Rival One is a 4-star hotel with 70 bedrooms. Our spa has a sauna, steam room, treatments and a pool; open daily 9am-9pm, day guests from £45 per person, over 16s only, book in advance. Restaurant and meeting rooms. Spa page: see /spa/.",
          "https://rival2.example/": "Rival Two is a 3-star B&B with 12 rooms.", "https://budget.example/": "Budget Inn, a 2-star hotel with 30 rooms, no spa."}


def fake_page(url):
    text = RIVAL1.get(url)
    if text is None:
        return {"url": url, "ok": False, "text": "", "links": []}
    return {"url": url, "ok": True, "title": "x", "h1": [], "text": text + " " + LONG, "footer_text": "", "tels": [], "links": [url + "spa/"] if "rival1" in url else [], "signals": {}}


cp = competitors.run(osm, own_pages, "https://www.testhotel.com/", "Test Hotel", fetch=fake_page, polite_allowed=lambda u: True)
check("the nearest hotel (a 2-star inn) is not chosen just for being close; a comparable 4-star is", cp["status"] == "ok" and [c["name"] for c in cp["competitors"]] == ["Rival One"], cp.get("competitors"))
check("hotels without a website, or on the same website, are not candidates", {c["name"] for c in competitors.pick(osm, "testhotel.com")} == {"Rival One", "Rival Two", "Budget Inn"})
spa_cmp = next((c for c in cp["comparisons"] if c["topic"] == "spa_detail"), None)
check("the spa is compared only because the audited hotel offers it and Rival One was read and offers it", spa_cmp is not None and spa_cmp["verified"] and spa_cmp["rivals"][0]["name"] == "Rival One")
check("Rival One states more of what travellers need about its spa (prices, age rules), so the hotel is behind on those details", spa_cmp["behind"] and "prices" in spa_cmp["missing"] and "Your hotel offers the spa" in spa_cmp["statement"], spa_cmp)
check("no comparison is made for facilities the audited hotel does not offer (no weddings, no pool on its pages)", all(c["topic"] not in ("wedding_detail", "pool_detail") for c in cp["comparisons"]))
recs_c = advice._from_competitors(cp, ic.Site(own_pages, BASE, HOTEL, CITY))
check("the opportunity says what to add, on the existing spa page, labelled an inference", recs_c and recs_c[0]["page"]["url"].endswith("/spa/") and recs_c[0]["confidence"] == advice.INFER and recs_c[0]["evidence"])
check("no map data: no comparison and an honest reason", competitors.run(None, own_pages, BASE, "Test Hotel")["status"] == "unavailable")
check("no comparable hotel: 'none' with the reason, and no claim", competitors.run({"hotels": [osm["hotels"][1]]}, own_pages, BASE, "Test Hotel", fetch=fake_page, polite_allowed=lambda u: True)["status"] == "none")
check("a rival whose robots.txt refuses is not read", competitors.run(osm, own_pages, BASE, "Test Hotel", fetch=fake_page, polite_allowed=lambda u: False)["status"] == "none")

# ================================================================ 7. structured data
print("7. structured data")
sd_pages = [home, rooms_page]
sd_none = it.structured_audit(ic.Site(sd_pages, BASE, HOTEL, CITY), None, {}, [])
check("no Hotel markup: the finding says how many pages were inspected and which, and that a tag manager would not show", "page(s) inspected" in sd_none["items"][0]["detail"] and "tag manager" in sd_none["items"][0]["detail"])
local = page("/", "Test Hotel. " + LONG, title="Test Hotel", structured=[{"types": ["LocalBusiness"], "keys": ["name", "telephone"], "name": "Test Hotel", "url": "", "telephone": "0113 111 2222", "address": {}, "geo": {}, "image": "", "description": "",
                                                                         "checkinTime": "", "checkoutTime": "", "priceRange": "", "sameAs": [], "amenities": [], "aggregateRating": None, "n_questions": 0}])
sd_local = it.structured_audit(ic.Site([local], BASE, HOTEL, CITY), None, {}, [])
check("a generic LocalBusiness block is 'could be improved': it should say Hotel", sd_local["items"][0]["status"] == "could_improve" and sd_local["generic_only"] and "generic" in sd_local["items"][0]["detail"])
recs_sd = advice._from_structured(sd_none, "<script>{}</script>", ic.Site(sd_pages, BASE, HOTEL, CITY))
sd1 = next(r for r in recs_sd if r["id"] == "SD1")
check("the developer recommendation lists the properties, the example, the validators and the 'no guarantee' caution", all(w in sd1["action"] for w in ("JSON-LD", "checkinTime", "validator.schema.org", "rich-results")) and sd1["example"] and "no evidence" in sd1["why"])
sd1["effort"] = "low"
ranking.annotate([sd1], [])
check("a missing Hotel block is a medium-priority, low-effort fix that ranks among the top actions", sd1["priority"] == "medium" and sd1["rank"] > 50)
import fixes
ld = fixes.hotel_jsonld({"base": BASE, "hotel": HOTEL, "location": {"city": CITY, "postcode": ""}, "guest": {}, "discovery": {}, "entities": []})
check("the example invents nothing: unknown values are left in [brackets]", "[Street address]" in ld and "[Postcode]" in ld and "[+44" in ld and "aggregateRating" not in ld)

# ================================================================ 8. AI test log
print("8. AI visibility: only what was genuinely tested")
items = [{"id": "best", "qid": "best", "kind": "generic", "text": "What are the best hotels in Leeds?", "answer": "1. Test Hotel - great for families\n2. Other Hotel", "mentioned": True, "recommended": True, "position": 1, "own_site_cited": True,
          "platform": "Claude (claude-haiku-5-5) with web search", "tested_on": "2026-10-16", "domains": ["testhotel.com"]},
         {"id": "niche_spa", "qid": "niche_spa", "kind": "niche", "text": "Which hotels in Leeds have a spa?", "answer": "Try Other Hotel.", "mentioned": False, "recommended": False, "position": None, "own_site_cited": False,
          "platform": "Claude (claude-haiku-5-5) with web search", "tested_on": "2026-10-16", "domains": []},
         {"id": "about", "qid": "about", "kind": "direct", "text": "Tell me about Test Hotel in Leeds.", "answer": "Test Hotel is a hotel.", "mentioned": True, "recommended": False, "position": None, "own_site_cited": True,
          "platform": "Claude (claude-haiku-5-5) with web search", "tested_on": "2026-10-16", "domains": ["testhotel.com"]}]
ai = {"status": "ok", "model": "claude-haiku-5-5", "items": items, "run_at": "2026-10-16", "summary": ai_sample.summarise(items)}
log = ai_sample.test_log(ai)
check("the log has a row per answer with platform, appeared, recommended, position, official site cited and date", len(log["rows"]) == 3 and set(log["rows"][0]) >= {"platform", "appeared", "recommended", "position", "official_site_cited", "date", "prompt"})
check("it counts only prompts that do not name the hotel, and says only Claude was tested", log["summary"]["prompts"] == 2 and log["summary"]["appeared"] == 1 and log["summary"]["recommended"] == 1 and "ChatGPT" in log["not_tested"] and "Claude" in log["platform"])
check("with no sample there is no log at all (nothing is invented)", ai_sample.test_log(None) is None and ai_sample.test_log({"status": "not_configured"}) is None)
ck = ai_sample.manual_checklist(ai, HOTEL)
check("a checklist for ChatGPT, Gemini and Copilot uses the non-branded prompts only", ck["assistants"] == ["ChatGPT", "Google Gemini", "Microsoft Copilot"] and "Tell me about Test Hotel in Leeds." not in ck["prompts"] and len(ck["prompts"]) == 2)
check("'recommended' is not the same as named: a negative mention is not a recommendation", ai_sample.recommended("I would avoid Test Hotel, reviews are poor.", "Test Hotel", "Leeds") is False and ai_sample.recommended("1. Test Hotel\n2. X", "Test Hotel", "Leeds"))
import ai_niche
prof = ai_niche.profile(HOTEL, CITY, [{"source": "OpenStreetMap", "found": True, "match_confident": True, "address_components": {"county": "West Yorkshire", "city": "Leeds"}}],
                        {"attractions": [{"name": "Royal Armouries", "km": 1.5, "tags": {"website": "x", "tourism": "museum"}}], "stations": [], "airports": []}, [page("/", "A 4-star hotel. " + LONG)], ic.features(ic.Site([home], BASE, HOTEL, CITY)),
                        [{"key": "spa", "label": "Spa", "level": "strong"}, {"key": "couples", "label": "Couples", "level": "some"}], hint={"audiences": ["wellness", "couples"]})
qs = ai_niche.questions(prof, HOTEL, CITY, n=8)
check("targeted prompts include a nearby landmark and the region, and none names the hotel", any("Royal Armouries" in q["text"] for q in qs) and any("West Yorkshire" in q["text"] for q in qs) and not any("test hotel" in q["text"].lower() for q in qs), [q["text"] for q in qs])

# ================================================================ 9. the recommendation gate
print("9. every recommendation has evidence, a specific action and is not a slogan")
good = {"id": "A", "title": "State the maximum occupancy of each family room", "source": "traveller", "evidence": [{"url": BASE, "snippet": "Family rooms are available"}], "action": "Add the maximum number of adults and children to the family rooms page."}
noev = {**good, "id": "B", "title": "Another thing entirely about parking", "evidence": []}
slogan = {**good, "id": "C", "title": "Strengthen your digital presence", "action": "Improve your online visibility across all channels and strengthen your digital presence."}
dup = {**good, "id": "D"}
vague = {**good, "id": "E", "title": "Something about breakfast times", "action": "Fix it."}
kept, dropped = advice.validate([good, noev, slogan, dup, vague])
check("only the evidenced, specific, original recommendation survives", [r["id"] for r in kept] == ["A"], [r["id"] for r in kept])
check("each withheld one says why", {d["id"]: d["reason"] for d in dropped} == {"B": "no supporting evidence", "C": "generic wording", "D": "repeats A", "E": "no specific action"}, dropped)
rr = {"id": "R", "source": "machine", "tag": "x", "confidence": advice.BEST, "effort": "low", "team": "web", "category": "content", "kind": "fix", "title": "t", "evidence": [{"url": "https://h.example/p", "snippet": "a passage the audit checked"}], "question_ids": []}
ri = {**rr, "id": "I", "confidence": advice.INFER, "evidence": []}
rx = {**rr, "id": "X", "source": "ai", "confidence": advice.EXPER}
rq = {**rr, "id": "Q", "evidence": [{"url": "https://h.example/p", "snippet": "Pages inspected for this: /rooms/"}]}
ranking.annotate([rr, ri, rx, rq], [])
check("the three-rung ladder: a checked quotation is Confirmed, an inference without a quotation is Likely, a sample or experimental lead is Worth checking, and an audit note is not a quotation",
      rr["confidence_label"] == "Confirmed" and ri["confidence_label"] == "Likely" and rx["confidence_label"] == "Worth checking" and rq["confidence_label"] == "Likely" and rr["value"] > ri["value"] > rx["value"])
check("every recommendation has an owner", rr["owner"] == "Web")

# ================================================================ 10. the whole pipeline on a synthetic site, and the PDF
print("10. the pipeline and the PDF with the new sections")
meta = [{"url": p["url"], "ok": True, "title": p["title"], "meta_description": "x", "h1_count": 1, "pdfs": [], "status": 200} for p in pages]
out = consultant.analyse(own_pages=pages, pages_meta=meta, base=BASE, hotel=HOTEL, city=CITY, location={"lat": 53.8, "lon": -1.5}, guest={"questions": gq.evaluate(pages), "conflicts": [], "own_facts_node": {}},
                         site={"robots": {"present": True}, "sitemap": {"present": True, "url_count": 5}}, entities=[{"source": "OpenStreetMap", "found": True, "match_confident": True}], intel=None, osm_ctx=None,
                         booking=bk, external=x, competitors=cp)
check("the consultant result carries the traveller, booking, external and competitor sections and the dropped list", all(k in out for k in ("traveller", "booking", "external", "competitors", "dropped_recommendations", "consistency_notes")))
check("every recommendation that survived has evidence, an action, a confidence label and an owner", all(r["evidence"] and len(r["action"]) >= 25 and r.get("confidence_label") and r.get("owner") for r in out["recommendations"]))
check("the external presence feeds the profile's authority component, and it is not a count of mentions", any(p["key"] == "authority" and "verified" in p["label"].lower() for p in out["profile"]))
check("the intent component now counts requirements, not words", any(p["key"] == "intent" and p["label"] == "Traveller recommendation readiness" for p in out["profile"]))
try:
    import report_pdf
    import report_view
    rep = json.load(open("tests_data/sample_report.json", encoding="utf8"))
    rep["consultant"] = out
    rep["ai_sample"] = ai
    rep["scorecard"] = scoring.build_scorecard(site0, [], [], {}, {"profiles": []}, guest_result={"pages_ok": 6, "pages_attempted": 6})
    headline.attach(rep)
    pdf_m, pdf_a = report_pdf.build_pdf(rep, "management"), report_pdf.build_pdf(rep, "appendix")
    check("the management and appendix PDFs build with the new sections", pdf_m[:5] == b"%PDF-" and pdf_a[:5] == b"%PDF-")
    import pymupdf
    mt = " ".join(p.get_text() for p in pymupdf.open(stream=pdf_m, filetype="pdf"))
    at = " ".join(p.get_text() for p in pymupdf.open(stream=pdf_a, filetype="pdf"))
    flat = " ".join(mt.split())
    check("the seven management sections are there, in order", all(flat.find(h_) >= 0 for h_ in ("Executive summary", "Discoverability and technical readiness", "Traveller recommendation readiness", "External presence and reputation",
                                                                                                "Commercial opportunities", "Prioritised action plan", "Methodology and limitations")))
    check("it says only one assistant was sampled and which were not tested", "Sampled on one assistant only" in flat and "NOT tested" in flat)
    check("the appendix carries the evidence, the AI test log and the hand-testing checklist", all(w in " ".join(at.split()) for w in ("Traveller requirements: the evidence for each", "External presence: each source", "AI recommendation tests: the log", "Checklist to test by hand")))
    html = report_view.render(rep, token="t" * 32)
    check("the web report shows the new cards", all(w in html for w in ("Traveller recommendation readiness", "The hotel on outside sources", "Booking readiness", "Do AI assistants name this hotel?", "How the readiness score is calculated")))
except Exception as e:  # noqa: BLE001
    check("the PDF and web report build with the new sections", False, repr(e))

try:
    import report_pdf_consult, report_pdf_mgmt, ui_consult, external_presence
    miss = [k for k in external_presence.LABEL if not (k in report_pdf_mgmt.EXT_COL and k in report_pdf_consult.EXT_COL and k in ui_consult.EXT_ICON)]
    check("every external-presence status can be drawn in the web report and both PDFs (an unmapped one crashed the page)", not miss, str(miss))
except Exception as e:  # noqa: BLE001
    check("status maps", False, repr(e))


print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
