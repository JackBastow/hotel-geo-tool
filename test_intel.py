"""
Offline tests for the discovery & reputation layer: matching, source failures,
sample-size honesty, duplicate/syndicated articles, unsupported recommendations.
Run: python test_intel.py
"""
from unittest import mock

import collect
import evidence
import identity
import intel
import langid
import media
import polite
import recommend
import sourcetypes
import sources
import targets

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Brooklands Hotel", "Weybridge, Surrey"

# ------------------------------------------------------------------ 1. matching
print("1. hotel matching - the biggest accuracy risk")
m = evidence.match_hotel("We stayed at the Brooklands Hotel in Weybridge, Surrey last spring.", HOTEL, CITY)
check("full name + town -> high", m["level"] == "high", m)
m = evidence.match_hotel("The Brooklands Hotel has a lovely spa and a good bar.", HOTEL, CITY)
check("full name, no town -> medium (could be another hotel)", m["level"] == "medium", m)
m = evidence.match_hotel("Brooklands Museum is home to Concorde and a motor racing circuit.", HOTEL, CITY)
check("the circuit/museum is NOT the hotel", m["level"] in ("none", "low"), m)
m = evidence.match_hotel("Brooklands Hotel & Spa - Weybridge KT13 0SL", HOTEL, CITY, postcode="KT13 0SL")
check("'& Spa' variant of the name matches", m["level"] == "high", m)
m = evidence.match_hotel("Brooklands Hotel, Blackpool: sea views and a ballroom", HOTEL, CITY)
check("same name, other town -> only medium, never high", m["level"] == "medium", m)
m = evidence.match_hotel("Great hotel with friendly staff.", HOTEL, CITY)
check("no name -> none", m["level"] == "none")
check("a name made only of lodging words has no usable variants",
      evidence.name_variants("The Hotel") == set())
m = evidence.match_hotel("BROOKLANDS HOTEL review", HOTEL, CITY, own_domain="https://brooklandshotelsurrey.com",
                         links=["https://www.brooklandshotelsurrey.com/rooms"])
check("a link to the hotel's own domain raises confidence", m["level"] == "high", m)
w, n = evidence.mention_windows("x " * 200 + "Brooklands Hotel is nice. " + "y " * 400 + "Brooklands Hotel again.", HOTEL)
check("mention windows found, non-overlapping", n == 2 and len(w) == 2 and all("Brooklands Hotel" in x for x in w), (n, w))
check("extract shows original wording, not folded", "Brooklands Hotel" in
      evidence.match_hotel("Stay at the Brooklands Hotel, Weybridge.", HOTEL, CITY)["extract"])

# -------------------------------------------------------------------- 2. parsing
print("2. page reading")
html = """<html lang="en"><head><title>A stay at Brooklands</title>
<meta property="article:published_time" content="2025-03-09T10:00:00Z">
<meta property="og:site_name" content="Visit Surrey"></head><body>
<article><h2>Teaser</h2><p>Short card.</p></article>
<article><p>""" + ("A long review of the Brooklands Hotel in Weybridge. " * 30) + """</p>
<h2>Rooms</h2><p>Spacious.</p><h2>Spa</h2><p>Lovely.</p></article></body></html>"""
pg = polite.parse_page(html, "https://example.com/p")
check("the biggest <article> is used, not the teaser card", "long review" in pg["text"].lower())
check("publication date and publisher read from metadata", pg["published"] == "2025-03-09" and pg["publisher"] == "Visit Surrey")
check("page language read", pg["lang_attr"] == "en")
check("headed sections of the article body are captured for roundups",
      [s["heading"] for s in pg["sections"]] == ["Rooms", "Spa"], pg["sections"])
sp = polite.parse_page("<html><body><article>Sponsored content. " + "word " * 120 + "</article></body></html>")
check("sponsored wording is detected and its text kept", sp["sponsored_cue"] and "sponsored" in sp["sponsored_cue_text"].lower())
check("no date is invented when the page has none", sp["published"] is None)
check("unreadable input returns {} not an exception", polite.parse_page("", "x") == {})
with mock.patch.object(polite, "_robots_for") as rf:
    rf.return_value.can_fetch.return_value = False
    f = polite.fetch("https://blocked.example/a")
check("robots.txt refusal is reported, not worked around", f["robots_blocked"] and not f["ok"])
check("langid: English", langid.detect("the hotel is in the centre of the town and we had a lovely stay with our "
                                       "family and the staff were very helpful for all of the weekend we were there")[0] == "en")
check("langid: short text -> unknown, not a guess", langid.detect("Hotel nice")[0] is None)

# ------------------------------------------------------------- 3. classification
print("3. classification")
check("booking platform", sourcetypes.classify_domain("https://www.booking.com/hotel/x.html")[0] == "booking_platform")
check("deal marketplace is not 'independent'", sourcetypes.classify_domain("https://www.spaseekers.com/x")[0] == "booking_platform")
check("wedding directory is a directory", sourcetypes.classify_domain("https://www.hitched.co.uk/x")[0] == "hotel_directory")
check("tourism board", sourcetypes.classify_domain("https://www.visitsurrey.com/x")[0] == "destination_body")
check("own site", sourcetypes.classify_domain("https://hotel.com/a", "https://www.hotel.com/")[0] == "own_website")
check("TripAdvisor is never read", not sourcetypes.may_read("https://www.tripadvisor.co.uk/Hotel_Review-x"))
check("'Best Western' is a brand, not a roundup",
      sourcetypes.classify_page("https://v.com/x", "Best Western The Ship Hotel Weybridge")["type"] != "roundup")
check("'10 Best Wedding Venues' is a roundup",
      sourcetypes.classify_page("https://v.com/x", "The 10 Best Wedding Venues in Weybridge")["type"] == "roundup")
check("sponsored wins over review",
      sourcetypes.classify_page("https://v.com/x", "Hotel review", cues={"sponsored_cue": True})["type"] == "sponsored")
check("press release recognised",
      sourcetypes.classify_page("https://v.com/press-release/x", "Hotel opens spa")["type"] == "press_release")
check("two Reach plc titles are ONE publisher",
      sourcetypes.publisher_key("getsurrey.co.uk") == sourcetypes.publisher_key("mirror.co.uk") == "Reach plc")
check("an unknown domain is its own publisher", sourcetypes.publisher_key("www.smallblog.co.uk") == "smallblog.co.uk")

# --------------------------------------------------------------- 4. media analysis
print("4. media: duplicates, independence, freshness, awards, ratings")


def cand(url, title, text, ptype="news", level="high", pub=None, date=None, source_type="other",
         roles=("news_recent",), mentions=3, snippet=""):
    dom = evidence.domain_of(url)
    return {"url": url, "key": url, "title": title, "snippet": snippet, "roles": list(roles),
            "source_type": source_type, "label": dom, "domain": dom, "via": "tavily",
            "published_search": date,
            "read": {"status": "read", "why": "", "robots_blocked": False},
            "match": {"level": level, "why": "x", "extract": ""},
            "page": {"title": title, "publisher": pub, "published": date,
                     "page_type": {"type": ptype, "basis": "t", "confidence": "medium", "cue_text": None},
                     "mentions": mentions, "windows": [text], "text_len": 5000, "text_head": text,
                     "lang": "en", "fingerprint": text.lower(), "links_to_hotel": False}}


PR = "Brooklands Hotel in Weybridge has unveiled a new spa after a major refurbishment, opening this spring."
corpus = {"queries": [{"role": "x", "query": "q", "error": None, "credits": 1, "n_results": 5}],
          "reads": {"ok": 6}, "tavily_credits": 9, "notes": [], "sources": {},
          "candidates": [
              cand("https://getsurrey.co.uk/a", "Brooklands Hotel unveils new spa", PR, date="2026-03-01"),
              cand("https://mirror.co.uk/b", "Brooklands Hotel unveils new spa", PR, date="2026-03-02"),
              cand("https://smallblog.co.uk/c", "Brooklands Hotel unveils new spa", PR, date="2026-03-03"),
              cand("https://travelmag.com/d", "Review: Brooklands Hotel", "Brooklands Hotel in Weybridge is a quiet, "
                   "romantic art-deco spa hotel. The AA rosette restaurant is superb.", ptype="review", date="2026-08-01"),
              cand("https://oldblog.com/e", "Our stay", "Brooklands Hotel, Weybridge: a family hotel, lively bar.",
                   ptype="review", date="2016-05-01"),
              cand("https://adblog.com/f", "Review", "Brooklands Hotel Weybridge.", ptype="sponsored", date="2026-05-01"),
              cand("https://rejected.com/g", "Brooklands circuit", "The motor circuit at Brooklands.", level="low"),
          ]}
L = evidence.Ledger(HOTEL, CITY)
arts, rejected, unread = media.build_articles(corpus, HOTEL, L)
check("look-alike page rejected and listed", len(arts) == 6 and len(rejected) == 1 and rejected[0]["domain"] == "rejected.com")
clusters = media.cluster(arts)
cov = media.summarise_coverage(arts, clusters)
check("three copies of one press release are ONE story", cov["stories"] == 4 and cov["duplicates_removed"] == 2, cov)
check("shared press copy and sponsored pieces are not 'independent'; only the 2 genuine reviews are",
      cov["independent_publishers"] == 2 and cov["syndicated_stories"] == 1, cov)
check("freshness: 2026 piece recent, 2016 piece old",
      {a["publisher"]: a["freshness"] for a in arts}["travelmag.com"] == "recent"
      and {a["publisher"]: a["freshness"] for a in arts}["oldblog.com"] == "old")
check("every article is registered as evidence with a URL and extract",
      all(L.get(a["id"]) and L.get(a["id"])["url"] and L.get(a["id"])["extract"] for a in arts))
undated = media.build_articles({"candidates": [cand("https://x.com/u", "t", PR, date=None)]}, HOTEL,
                               evidence.Ledger())[0][0]
check("an undated page is 'unknown', never guessed", undated["freshness"] == "unknown" and undated["date"] is None)

own = [{"url": "https://hotel.com/about", "title": "About", "text":
        "Our award-winning spa. Proud to hold 2 AA Rosettes (2025). A quiet, peaceful garden retreat, wedding venue."}]
awards = media.find_awards(own, arts, corpus, HOTEL, L)
aa = next(a for a in awards if a["issuer"] == "The AA")
check("an award on the hotel's own site stays 'claimed' without issuer confirmation",
      "claimed by the hotel" in aa["status"], aa["status"])
check("an unnamed 'award-winning' claim is flagged unverifiable",
      any(a["issuer"] == "(issuer not named)" and "unverifiable" in a["status"] for a in awards))
corp2 = dict(corpus, candidates=corpus["candidates"] + [
    cand("https://www.theaa.com/hotel-services/x", "AA hotel listing", "Brooklands Hotel, Weybridge: 2 AA Rosettes 2025",
         source_type="awards_body")])
aa2 = next(a for a in media.find_awards(own, arts, corp2, HOTEL, evidence.Ledger()) if a["issuer"] == "The AA")
check("a page on the issuer's domain naming the hotel confirms the claim", aa2["issuer_confirmed"] is True, aa2["status"])

th = media.theme_scan(arts, own)
tmap = {t["theme"]: t for t in th["themes"]}
check("themes come from windows around the hotel only", tmap["romantic"]["independent_publishers"] == 1)
check("a theme only the hotel claims is reported as claimed-only", "countryside / gardens" in th["own_only"])
check("quiet vs lively across DIFFERENT sources is reported as a disagreement",
      any(set(d["themes"]) == {"quiet / peaceful", "lively / social"} for d in th["disagreements"]), th["disagreements"])

rc = {"candidates": [
    cand("https://hitched.co.uk/x", "Venues", "Brooklands Hotel 5.0 (13) · Weybridge, Surrey. A modern chic venue.",
         source_type="hotel_directory"),
    cand("https://tp.com/y", "Hotels", "Oatlands Park Hotel 9.3 Free WiFi ... Brooklands Hotel is nearby. 1 / 10 results",
         source_type="booking_platform"),
    cand("https://trustpilot.com/z", "Brooklands Hotel", "Brooklands Hotel is rated \"Poor\" with 2.5 / 5 on Trustpilot",
         source_type="booking_platform", level="medium")]}
rs = media.rating_signals(rc, HOTEL, CITY, evidence.Ledger())
check("a rating beside the hotel's name and town is captured and verified",
      any(r["source"].startswith("hitched") and r["value"] == 5.0 and r["count"] == 13 and r["verified_location"] for r in rs), rs)
check("a stray number elsewhere on a multi-hotel page is NOT taken as the hotel's rating",
      not any(r["source"] == "tp.com" for r in rs), rs)
check("a rating whose snippet names no town is marked unverified (may be another hotel)",
      any("trustpilot" in r["source"] and not r["verified_location"] for r in rs), rs)

# --------------------------------------------------------------- 5. source failures
print("5. source failures are 'unavailable', never 'no results'")


class Resp:
    def __init__(self, code, js=None, text=""):
        self.status_code, self._js, self.text, self.content = code, js, text, text.encode()
        self.headers = {}

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


with mock.patch("sources.requests.request", return_value=Resp(429, text="slow down")), \
        mock.patch("sources.time.sleep"):
    g = sources.gdelt_search(HOTEL, CITY)
check("GDELT HTTP 429 -> unavailable, with the reason", g["status"] == "unavailable" and "429" in g["reason"], g)
with mock.patch("sources.requests.request", return_value=Resp(200, {"articles": []})):
    g = sources.gdelt_search(HOTEL, CITY)
check("GDELT with zero articles -> no_results (a finding, with a caveat)", g["status"] == "no_results" and "weak evidence" in g["reason"])
with mock.patch("sources.requests.request", return_value=Resp(200, {"remark": "runtime error: timeout", "elements": []})), \
        mock.patch("sources.time.sleep"):
    o = sources.osm_context(51.35, -0.47, HOTEL)
check("Overpass 200-with-remark -> unavailable, NOT 'nothing nearby'", o["status"] == "unavailable", o)
with mock.patch("sources.requests.request", return_value=Resp(200, {"elements": [
        {"type": "node", "id": 1, "lat": 51.36, "lon": -0.47, "tags": {"name": "Weybridge", "railway": "station"}}]})), \
        mock.patch("sources.time.sleep"):
    o = sources.osm_context(51.35, -0.47, HOTEL)
check("Overpass station parsed with a straight-line distance", o["status"] == "ok" and o["items"][0]["stations"][0]["km"] > 0)
check("OSM context with no coordinates -> unavailable with reason", sources.osm_context(None, None)["status"] == "unavailable")
fsa_payload = {"establishments": [
    {"BusinessName": "Brooklands College Canteen", "BusinessType": "Restaurant/Cafe/Canteen", "RatingValue": "5",
     "PostCode": "KT13 8TT", "RatingDate": "2026-02-06T00:00:00", "FHRSID": 1, "LocalAuthorityName": "Elmbridge"},
    {"BusinessName": "Brooklands Hotel", "BusinessType": "Hotel/bed & breakfast/guest house", "RatingValue": "2",
     "PostCode": "KT13 0SL", "RatingDate": "2026-08-11T00:00:00", "FHRSID": 2, "LocalAuthorityName": "Elmbridge"}]}
with mock.patch("sources.requests.request", return_value=Resp(200, fsa_payload)):
    f = sources.fsa_ratings(HOTEL, "KT13 0SL", True)
check("FSA: only the exact hotel record is used, not a college that shares the first word",
      len(f["items"]) == 1 and f["items"][0]["name"] == "Brooklands Hotel" and f["items"][0]["descriptor"] == "Improvement necessary", f)
check("FSA outside the UK -> unavailable, not 'no record'", sources.fsa_ratings(HOTEL, "", False)["status"] == "unavailable")
check("YouTube without a key -> not_configured (a stated gap)", sources.youtube_search(HOTEL, CITY, None)["status"] == "not_configured")

# -------------------------------------------------------- 6. collection without search
print("6. collection without a search key")
with mock.patch.object(collect, "sources") as srcs:
    for name in ("gdelt_search", "wikipedia_mentions", "osm_context", "wayback_titles", "fsa_ratings", "youtube_search"):
        getattr(srcs, name).return_value = {"source": name, "status": "no_results", "reason": "r", "items": [], "access": ""}
    c = collect.collect(HOTEL, CITY, "https://brooklandshotelsurrey.com/", tavily_key=None, location={})
check("no key -> no searches, and a note says exactly what that costs", c["queries"] == [] and
      any("could not be discovered" in n for n in c["notes"]) and c["tavily_credits"] == 0, c["notes"])
plan = collect.search_plan(HOTEL, CITY, ["spa/wellness hotel"])
check("search plan is bounded and purposeful", 8 <= len(plan) <= 14 and all(q[1] for q in plan), len(plan))
check("every search names the hotel in quotes (no loose generic queries about the hotel)",
      all(f'"{HOTEL}"' in q or r in ("destination", "roundup") for r, q, _ in plan))
check("URL canonicalisation merges tracking variants",
      collect.canonical_url("https://www.x.com/a/?utm_source=z#top") == collect.canonical_url("https://x.com/a"))

# ----------------------------------------------------- 7. targets and pitch angles
print("7. media targets and pitch angles")
guide = cand("https://thelocal.co.uk/best-hotels-weybridge", "The best hotels in Weybridge", "Weybridge hotels guide",
             ptype="roundup", level="none", roles=("roundup",), date="2026-06-01")
guide["page"]["sections"] = [
    {"heading": "1. The Oatlands Park Hotel", "text": "A grand hotel in Weybridge with a spa and weddings."},
    {"heading": "2. Best Western Ship Hotel", "text": "A coaching inn in Weybridge."},
    {"heading": "Location & Contact Details", "text": "x"},
    {"heading": "Guest House", "text": "x"},
    {"heading": "Where is the hotel located?", "text": "x"}]
mine = cand("https://thelocal.co.uk/spas", "Best spa hotels in Weybridge", PR, ptype="roundup", level="high", roles=("roundup",))
wf = cand("https://www.visitsurrey.com/ship", "Best Western The Ship Hotel Weybridge", "Ship hotel page", ptype="other",
          level="none", roles=("roundup",))
brand = cand("https://www.quora.com/q", "Is Weybridge worth visiting?", "x", ptype="other", level="none", roles=("roundup",))
listing = cand("https://www.momondo.co.uk/h", "Hotels in Weybridge from £73", "x", ptype="roundup", level="none",
               roles=("roundup",), source_type="hotel_directory")
osm_ctx = {"hotels": [{"name": "Oatlands Park Hotel", "km": 3.1, "tags": {"stars": "4"}, "osm": ""}]}
tg = targets.comparison_and_targets({"candidates": [guide, mine, wf, brand, listing]}, [], HOTEL, CITY, osm_ctx,
                                    {"wellness / spa": 3}, [], [], evidence.Ledger())
names = [c["hotel"] for c in tg["comparison"]]
check("comparison hotels are real properties (page sections like 'Guest House' are rejected)",
      names and all(n not in ("Guest House", "Location & Contact Details") for n in names), names)
check("comparison validity is explained (mapped within a distance)",
      any("OpenStreetMap" in e["why"] for r in tg["roundups"] for e in r["entries"] if e["valid_comparison"]))
check("a guide that already lists the hotel is not a target", all("spas" not in t["url"] for t in tg["targets"]))
check("'Best Western' hotel page, Quora and a price-comparison site are not targets",
      all(not any(x in t["url"] for x in ("visitsurrey.com/ship", "quora", "momondo")) for t in tg["targets"]), tg["targets"])
t0 = next(t for t in tg["targets"] if "best-hotels-weybridge" in t["url"])
check("a target carries its supporting page, date and a stated reason",
      t0["url"] and t0["date"] == "2026-06-01" and t0["why_relevant"] and t0["evidence_id"])
ang = targets.pitch_angles(own + [{"url": "https://hotel.com/history", "title": "History", "text":
                                   "The hotel is a Grade II listed building, built in 1932 beside the historic circuit."}],
                           evidence.Ledger())
check("a pitch angle rests on a real quoted fact with a source URL",
      ang and all(a["fact"] and a["source_url"] and a["missing_evidence"] for a in ang))
check("angles say they are candidates, not proven news", all("candidate" in a["status"] for a in ang))
check("no facts on the hotel's pages -> NO invented angles", targets.pitch_angles([{"url": "u", "title": "", "text": "Welcome."}],
                                                                                   evidence.Ledger()) == [])

# ------------------------------------------------- 8. the whole report, 30 checks
print("8. assembled report and recommendations")
GUEST = {"questions": [{"id": "pets", "short": "Pets", "state": "partial"},
                       {"id": "ev", "short": "EV charging", "state": "not_found"}]}
ENT = [{"source": "OpenStreetMap", "found": True, "match_confident": True, "url": "https://osm/1",
        "display_name": "Brooklands Hotel, Weybridge", "facts": {"name": "Brooklands Hotel", "address": "Weybridge"}},
       {"source": "Wikidata", "found": True, "match_confident": True, "id": "Q1", "url": "https://wd/Q1",
        "label": "Brooklands Hotel", "description": "hotel in Weybridge"}]
corpus["sources"] = {"osm_context": {"source": "OSM", "status": "unavailable", "reason": "Overpass down", "items": [], "access": ""},
                     "fsa": {"source": "FSA", "status": "ok", "reason": "", "access": "", "items": [
                         {"name": HOTEL, "type": "Hotel", "rating": "2", "descriptor": "Improvement necessary",
                          "rating_date": "2026-08-11", "postcode": "KT13 0SL", "same_postcode": True, "url": "https://fsa/1"}]}}
res = intel.build_intel(hotel=HOTEL, city=CITY, base_url="https://brooklandshotelsurrey.com/", location={"city": "Weybridge"},
                        site={"robots": {"present": True}}, discovery={"profiles": []}, guest=GUEST, own_pages=own,
                        entities=ENT, tavily_result={}, corpus=corpus, site_links=[], own_facts={"name": HOTEL},
                        scorecard_recs=[])
ch = {c["n"]: c for c in res["checks"]}
check("all 30 checks are reported", sorted(ch) == list(range(1, 31)))
check("every check has a valid status", all(c["status"] in ("assessed", "partial", "not_assessed") for c in ch.values()))
check("review text checks 8-13 are NOT assessed, each with a specific reason",
      all(ch[n]["status"] == "not_assessed" and len(ch[n]["reason"]) > 40 for n in range(8, 14)))
check("review sample is stated as 0 accessible guest reviews", "0 guest reviews" in ch[6]["summary"])
check("local context marked unavailable rather than 'nothing nearby'", ch[29]["status"] in ("partial", "not_assessed")
      and "Overpass" in (ch[29]["reason"] or ch[29]["summary"]))
ledger_ids = {e["id"] for e in res["ledger"]}
check("every recommendation's evidence ids exist in the ledger",
      all(e in ledger_ids for r in res["recommendations"] for e in r["evidence_ids"]))
req = ("problem", "why_it_matters", "action", "team", "priority", "priority_why", "success_check", "basis", "evidence_ids")
check("every recommendation carries all required fields", all(all(k in r and r[k] != "" for k in req if k != "evidence_ids")
                                                              for r in res["recommendations"]))
check("teams are from the allowed set", all(r["team"] in recommend.TEAMS for r in res["recommendations"]))
check("basis is one of documented guidance / hypothesis / observation",
      all(r["basis"] in ("documented guidance", "hypothesis", "observation") for r in res["recommendations"]))
allText = " ".join((r["title"] + r["problem"] + r["action"] + r["why_it_matters"]).lower() for r in res["recommendations"])
check("no recommendation promises or guarantees an AI recommendation", "guarantee" not in allText and "will rank" not in allText)
check("no recommendation advises incentivised/fake reviews or keyword stuffing",
      not any(p in allText for p in ("ask guests for", "offer a discount for", "buy reviews", "stuff", "5-star reviews")))
fsa_rec = next(r for r in res["recommendations"] if r["id"].startswith("F1"))
check("a real FSA rating below 4 produces an operations recommendation citing the register",
      fsa_rec["team"] == "operations" and fsa_rec["evidence_ids"] and "Improvement necessary" in fsa_rec["problem"])
a2 = next(r for r in res["recommendations"] if r["id"].startswith("A2"))
check("the award recommendation reads correctly ('the AA', not 'the The AA') and is a hypothesis, not a fact",
      "The The" not in a2["title"] and "the The" not in a2["title"] and a2["title"] == "Confirm and link the AA recognition" and a2["basis"] == "hypothesis")
check("the guest-review blind spot is itself a recommendation, labelled documented guidance",
      any(r["id"] == "V3" and r["basis"] == "documented guidance" for r in res["recommendations"]))
check("five priority actions, spread across sections", len(res["priority_actions"]) == 5 and len(
    {next(r for r in res["recommendations"] if r["id"] == i)["section"] for i in res["priority_actions"]}) >= 3)

# nothing searched: unsupported claims must not appear
empty = intel.build_intel(hotel=HOTEL, city=CITY, base_url="https://x.com/", location={}, site={}, discovery={"profiles": []},
                          guest=GUEST, own_pages=[], entities=[], tavily_result=None,
                          corpus={"sources": {}, "queries": [], "candidates": [], "reads": {}, "notes": ["No Tavily key"],
                                  "tavily_credits": 0}, site_links=[], own_facts={}, scorecard_recs=[])
ec = {c["n"]: c for c in empty["checks"]}
check("no search -> media coverage 'not assessed', not 'zero coverage'", ec[15]["status"] == "not_assessed")
check("no search -> no media recommendation claiming there is no coverage",
      not any(r["id"].startswith("M1") for r in empty["recommendations"]))
check("no search -> research directions offered, clearly labelled, no named outlets",
      empty["media"]["research_directions"] and not empty["media"]["targets"])
check("no pitch angle is invented from nothing", ec[23]["status"] == "not_assessed" and not empty["media"]["angles"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)

