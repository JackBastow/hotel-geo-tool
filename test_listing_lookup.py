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
         {"url": "https://www.expedia.co.uk/Paris-Hotels-Hilton-Paris.h2.Hotel-Information", "title": "Hilton Paris"}, {"url": "https://example.com/blog", "title": "Paris Marriott Opera Ambassador Hotel review"}]
hits = {h["platform"]: h for h in ll.hits_from_pages(pages, HOTEL, CITY)}
check("Expedia, Booking.com and Tripadvisor are each found, on their own domain", set(hits) == {"Expedia", "Booking.com", "TripAdvisor"}, set(hits))
check("the Expedia hit is the hotel's page, not the other Paris hotel on the same site", hits["Expedia"]["url"] == EXPEDIA)
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
check("one call with the web-search tool, allowed a search per site, naming every site, and asking only to search", len(fake.calls) == 1 and tool["name"] == "web_search" and tool["max_uses"] == 8
      and all(w in fake.calls[0]["messages"][0]["content"] for w in ("Expedia", "Booking.com", "Hotels.com", "TripAdvisor")))
check("it returns the pages the search returned (the model's own words are not used) and the cost", r["status"] == "ok" and len(r["pages"]) == 5 and 0 < r["cost_usd"] < 0.30, r["cost_usd"])
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

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
