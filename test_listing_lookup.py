"""
Offline tests for listing_lookup.py and the looser listing-name matching: a hotel that IS listed on Expedia must not be reported as
"not found". A fake client stands in for the Anthropic SDK. Run: python test_listing_lookup.py
"""
from types import SimpleNamespace as NS

import identity
import listing_lookup as ll

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
EXPEDIA = "https://www.expedia.co.uk/Paris-Hotels-Paris-Marriott-Opera-Ambassador.h3309.Hotel-Information?msockid=03f2"
BOOKING = "https://www.booking.com/hotel/fr/marriott-opera-ambassador.en-gb.html"

print("1. does an address or title belong to the hotel?")
check("the Expedia page in the screenshot is the hotel even though its address has no word 'Hotel' after 'Ambassador' and its title is generic",
      identity.names_hotel(EXPEDIA, "Hotel Information", "", HOTEL))
check("a title that carries the full name is enough", identity.names_hotel("https://x.com/p/1", "Paris Marriott Opera Ambassador Hotel from £120 - Expedia", "", HOTEL))
check("a different hotel in the same town is not the hotel", not identity.names_hotel("https://www.expedia.co.uk/Paris-Hotels-Hilton-Paris-Opera.h1.Hotel-Information", "Hilton Paris Opera", "", HOTEL))
check("one distinctive word alone never counts ('Ambassador')", not identity.names_hotel("https://www.expedia.co.uk/Paris-Hotels-Ambassador-Hotel.h1.Hotel-Information", "", "", HOTEL))
check("two-word names need the words together, not scattered", not identity.names_hotel("https://x.com/opera-hotel-near-the-marriott", "Opera hotel", "", "Marriott Opera"))

print("2. picking the listing out of search results")
pages = [{"url": "https://www.tripadvisor.co.uk/Hotel_Review-g187147-d1-Reviews-Paris_Marriott_Opera_Ambassador_Hotel-Paris.html", "title": "Paris Marriott Opera Ambassador Hotel - Tripadvisor"},
         {"url": EXPEDIA, "title": "Paris Marriott Opera Ambassador Hotel"}, {"url": BOOKING, "title": "Paris Marriott Opera Ambassador Hotel, Paris - Booking.com"},
         {"url": "https://www.expedia.co.uk/Paris-Hotels-Hilton-Paris.h2.Hotel-Information", "title": "Hilton Paris"}, {"url": "https://example.com/blog", "title": "Paris Marriott Opera Ambassador Hotel review"},
         {"url": "https://www.top-paris-hotels.com/en/property/marriott-opera-ambassador.html", "title": "Hotel Marriott Opera Ambassador Paris, France - book now"}]
hits = {h["platform"]: h for h in ll.hits_from_pages(pages, HOTEL, CITY)}
check("Expedia, Booking.com and Tripadvisor are each found, on their own domain", set(hits) == {"Expedia", "Booking.com", "TripAdvisor"}, set(hits))
check("the Expedia hit is the hotel's page, not the other Paris hotel on the same site", hits["Expedia"]["url"] == EXPEDIA)
check("an address that merely CONTAINS a platform's name is not the platform ('top-paris-hotels.com' is not Hotels.com; 'expedia-aarp.com' is not 'expedia.')",
      not identity.on_platform("top-paris-hotels.com", "hotels.com") and identity.on_platform("www.hotels.com", "hotels.com") and identity.on_platform("fi.kayak.com", "kayak.")
      and identity.on_platform("expedia.co.uk", "expedia.") and not identity.on_platform("expedia-aarp.com", "expedia.") and not identity.on_platform("mytrivago.example.com", "trivago."))
check("Hotels.com is not 'found' from a look-alike site that names the hotel", "Hotels.com" not in hits and all("top-paris" not in h["url"] for h in hits.values()))
check("a post or guide on a platform's site (Trip.com 'moments') is not the hotel's listing, and a hotel page is preferred",
      ll.hits_from_pages([{"url": "https://us.trip.com/moments/detail/paris-308-1", "title": "Paris Marriott Opera Ambassador Hotel"},
                          {"url": "https://www.trip.com/hotels/paris-hotel-detail-1/paris-marriott-opera-ambassador-hotel/", "title": "Paris Marriott Opera Ambassador Hotel"}], HOTEL, CITY)[0]["url"].endswith("-hotel/"))
check("a blog that names the hotel is not mistaken for a platform listing", all("example.com" not in h["url"] for h in hits.values()))
check("the town in the title or address is noted as location confirmed", hits["Booking.com"]["location_confirmed"] and hits["TripAdvisor"]["location_confirmed"])
check("platforms already found are not looked for again", "Expedia" not in {h["platform"] for h in ll.hits_from_pages(pages, HOTEL, CITY, have=("Expedia",))})
two = [{"url": "https://www.expedia.com/Hotels-Ambassador-Opera.h1.Hotel-Information", "title": "Hotel Ambassador Opera"},
       {"url": "https://www.expedia.co.uk/Hotels-Ambassador-Opera.h2.Hotel-Information", "title": "Hotel Ambassador Opera, Paris"}]
check("when a platform has several pages for the hotel the one with the town is preferred", ll.hits_from_pages(two, "Hotel Ambassador Opera", CITY)[0]["url"] == two[1]["url"])

print("3. the lookup itself")


def resp(urls, text="done", searches=7, tin=20000, tout=300):
    blocks = [NS(type="web_search_tool_result", content=[NS(url=u, title=t) for u, t in urls]), NS(type="text", text=text, citations=None)]
    return NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=tin, output_tokens=tout, server_tool_use=NS(web_search_requests=searches)))


class Fake:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0)


fake = Fake([resp([(p["url"], p["title"]) for p in pages])])
r = ll.run(HOTEL, CITY, client=fake)
tool = fake.calls[0]["tools"][0]
check("one call with the web-search tool, allowed a search per site, naming every site, and asking only to search", len(fake.calls) == 1 and tool["name"] == "web_search" and tool["max_uses"] == 9
      and all(w in fake.calls[0]["messages"][0]["content"] for w in ("Expedia", "Booking.com", "Hotels.com", "TripAdvisor")))
check("it returns the pages the search returned (the model's own words are not used) and the cost", r["status"] == "ok" and len(r["pages"]) == 6 and 0 < r["cost_usd"] < 0.30, r["cost_usd"])
check("the platforms already found are left out of the request", "Expedia" not in Fake([resp([])]).calls and
      "Expedia" not in (lambda f: (ll.run(HOTEL, CITY, client=f, have=("Expedia",)), f.calls[0]["messages"][0]["content"])[1])(Fake([resp([])])))
check("no key and no client: not run, with the reason; no town: not run", ll.run(HOTEL, CITY)["status"] == "not_configured" and ll.run(HOTEL, "", api_key="k")["status"] == "not_configured")


class Boom:
    messages = None

    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise RuntimeError("down")


check("a failure never raises: it is reported and the audit goes on", ll.run(HOTEL, CITY, client=Boom())["status"] == "unavailable")

print("4. the footprint no longer says 'not found' for a listed hotel")
cands = ll.as_candidates(ll.hits_from_pages(pages, HOTEL, CITY), "https://www.marriott.com/")
corpus = {"candidates": cands}
rows = {x["platform"]: x for x in identity.listing_footprint(corpus, HOTEL, CITY, [])}
check("Expedia is discovered, with its page, location confirmed, and honestly marked as not read", rows["Expedia"]["discovered"] and rows["Expedia"]["url"] == EXPEDIA
      and not rows["Expedia"]["content_assessed"] and "not opened" in rows["Expedia"]["note"], rows["Expedia"])
check("a platform with no listing found still says 'not found by our searches' and never 'not listed'", not rows["Hotels.com"]["discovered"] and "does not show the hotel is not listed" in rows["Hotels.com"]["note"])

print("5. OpenStreetMap: found under the name a mapper would write")
import external_check as ec
import time as _t
_t.sleep = lambda *_a: None
calls = []
ENTRY = {"name": "Marriott Opera Ambassador", "display_name": "Marriott Opera Ambassador, Boulevard Haussmann, Paris, France", "category": "tourism", "type": "hotel",
         "lat": "48.8731", "lon": "2.3354", "osm_type": "node", "osm_id": 1, "address": {"road": "Boulevard Haussmann", "city": "Paris"}, "extratags": {}}


def fake_get(url, params):
    calls.append(params)
    if params.get("q", "").lower().startswith("paris marriott"):
        return [], None                                  # the booking-site name finds nothing, as it did live
    if "marriott opera ambassador" in params.get("q", "").lower():
        return [ENTRY, {"name": "Rue de l'Opera", "display_name": "Rue de l'Opera, Paris", "category": "highway", "type": "residential", "lat": "48.87", "lon": "2.33"}], None
    return [], None


ec._get_json = fake_get
r = ec.check_openstreetmap(HOTEL, CITY, lat=48.8731, lon=2.3354)
check("a hotel mapped as 'Marriott Opera Ambassador' is found even though the booking sites call it 'Paris Marriott Opera Ambassador Hotel'",
      r["found"] and r["match_confident"] is True and "0.0km" in r["match_reason"] and len(calls) >= 3, (r.get("note"), len(calls)))
check("the variants drop the town and the word 'hotel', never reduce the name to one word", all(len(q.replace(",", " ").split()) >= 2 for q in ec._osm_name_variants(HOTEL, CITY)) and "marriott opera ambassador, Paris" in ec._osm_name_variants(HOTEL, CITY))
check("a result whose own name shares no distinctive word with the hotel (a street) is never taken as its entry", not ec._osm_name_ok({"name": "Rue de l'Opera", "display_name": "Rue de l'Opera, Paris"}, HOTEL, CITY)
      and ec._osm_name_ok(ENTRY, HOTEL, CITY))
ec._get_json = lambda url, params: ([], None)
r = ec.check_openstreetmap(HOTEL, CITY)
check("when every variant finds nothing it says so, and tells the reader to search by hand before adding anything", not r["found"] and "by hand" in r["note"])
ec._get_json = lambda url, params: (None, "HTTP 429")
r = ec.check_openstreetmap(HOTEL, CITY)
check("a lookup that failed is an error, not 'missing' (so no advice to add the hotel)", r.get("error") == "HTTP 429" and not r["found"])

print("6. a name copied from a chain's address (seen live: 'Paroa Paris Marriott Opera Ambassador Hotel')")
import full_audit as _fa
import urlscope as _us
MU = "https://www.marriott.com/en-us/hotels/paroa-paris-marriott-opera-ambassador-hotel/overview/"
msc = _us.normalise(MU)[1]
check("the property code at the front of a Marriott or Hilton address is found, and the name from the address leaves it out",
      _us.property_code(MU, msc) == "paroa" and _us.name_from_url(MU, msc)["name"] == "Paris Marriott Opera Ambassador Hotel" and _us.property_code("https://www.hilton.com/en/hotels/zrhhitw-hilton-zurich-airport/", "/en/hotels/zrhhitw-hilton-zurich-airport/") == "zrhhitw"
      and _us.property_code("https://www.brooklandshotelsurrey.com/", "/") == "")
check("a typed name that starts with that code is cleaned to the hotel's real name, so listings and AI answers are matched on it",
      _fa.tidy_typed_name("Paroa Paris Marriott Opera Ambassador Hotel", {"pages": []}, MU, msc) == ("Paris Marriott Opera Ambassador Hotel", True)
      and _fa.tidy_typed_name("Paris Marriott Opera Ambassador Hotel", {"pages": []}, MU, msc) == ("Paris Marriott Opera Ambassador Hotel", False))
check("and if the name is still typed with an extra word at the front, a listing without it is still the hotel (four or more distinctive words)",
      identity.names_hotel(EXPEDIA, "Hotel Information", "", "Paroa Paris Marriott Opera Ambassador Hotel") and identity.names_hotel(EXPEDIA, "Hotel Information", "", "Paris Marriott Opera Ambassador Hotel Annex")
      and not identity.names_hotel("https://www.expedia.co.uk/Paris-Hotels-Ambassador.h1.Hotel-Information", "Ambassador", "", "Paroa Paris Marriott Opera Ambassador Hotel"))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
