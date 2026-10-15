"""
Offline tests for listing_facts.py: what the travel sites show against the hotel's own site, and listings that still show a former name.
Run: python test_listing_facts.py
"""
from types import SimpleNamespace as NS

import advice
import ai_sample
import listing_facts as lf
import listing_lookup as ll

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL = "Paris Marriott Opera Ambassador Hotel"
BK = "https://www.booking.com/hotel/fr/paris-marriott-opera-ambassador-hotel.html"
EX = "https://www.expedia.co.uk/Paris-Hotels-Paris-Marriott-Opera-Ambassador.h3309.Hotel-Information"
TA = "https://www.tripadvisor.com/Hotel_Review-g187147-d197578-Reviews-Paris_Marriott_Opera_Ambassador_Hotel-Paris.html"
P = [{"url": BK, "title": "Paris Marriott Opera Ambassador Hotel, Paris - Booking.com", "cited_text": "Check-in from 14:00 hours. Check-out until 12:00. 4-star hotel."},
     {"url": EX, "title": "Paris Marriott Opera Ambassador", "cited_text": "Check-in time starts at 3:00 PM; check-out before noon. Phone: +33 1 40 07 34 34"},
     {"url": TA, "title": "PARIS MARRIOTT OPERA AMBASSADOR HOTEL - Tripadvisor", "cited_text": "Great location near the Opera, friendly staff and a lovely breakfast."},
     {"url": "https://www.booking.com/hotel/fr/hilton-paris-opera.html", "title": "Hilton Paris Opera", "cited_text": "Check-in from 16:00. 5-star."},
     {"url": "https://example.com/blog", "title": "Paris Marriott Opera Ambassador Hotel review", "cited_text": "Check-in at 9:00."}]

print("1. facts read out of the quoted passages")
ls = lf.listing_facts(P, HOTEL)
check("Booking.com's passage gives check-in 14:00, check-out 12:00 and 4 stars", (ls["Booking.com"]["check_in"], ls["Booking.com"]["check_out"], ls["Booking.com"]["stars"]) == ("14:00", "12:00", 4), ls["Booking.com"])
check("Expedia's '3:00 PM' is read as 15:00, and the phone number as digits", ls["Expedia"]["check_in"] == "15:00" and ls["Expedia"]["phone"] == "33140073434", ls["Expedia"])
real = lf.listing_facts([{"url": "https://www.trivago.com/en-US/oar/paris-marriott-opera-ambassador-hotel?search=1", "title": "Paris Marriott Opera Ambassador Hotel, France",
                          "cited_text": "Check-in at Paris Marriott Opera Ambassador Hotel is available from: 15:00. Check-out time is by 12:00."},
                         {"url": "https://www.agoda.com/fr-fr/paris-marriott-opera-ambassador-hotel/hotel/paris-fr.html", "title": "Paris Marriott Opera Ambassador Hotel",
                          "cited_text": "Paris Marriott Opera Ambassador Hotel 4 \u00e9toiles sur 5 16 Boulevard Haussmann, Paris. Check-In \u00e0 partir de: 04:00 PM - Check-Out jusqu'\u00e0: 12:00"},
                         {"url": "https://www.kayak.co.uk/Paris-Hotels-Marriott-Paris-Opera-Ambassador-Hotel.37841.ksp", "title": "Paris Marriott Opera Ambassador Hotel",
                          "cited_text": "Paris Marriott Opera Ambassador Hotel 4 stars 16 boulevard Haussmann, 75009 Paris, France +33 1 44 83 40 40"}], HOTEL)
check("real passages (seen live): a check-in sentence that carries the hotel's name, a French '4 \u00e9toiles' and 'Check-In \u00e0 partir de: 04:00 PM', and a bare international phone number",
      (real["Trivago"]["check_in"], real["Trivago"]["check_out"]) == ("15:00", "12:00") and (real["Agoda"]["stars"], real["Agoda"]["check_in"], real["Agoda"]["check_out"]) == (4, "16:00", "12:00")
      and real["Kayak"]["phone"] == "33144834040" and real["Kayak"]["stars"] == 4, real)
check("a passage that shows no fact gives none (Tripadvisor), never a guess", ls["TripAdvisor"]["check_in"] is None and ls["TripAdvisor"]["stars"] is None)
check("a different hotel on the same site, and a blog that names the hotel, are not used", set(ls) == {"Booking.com", "Expedia", "TripAdvisor"} and ls["Booking.com"]["url"] == BK)
check("each fact keeps the passage it came from", "Check-in from 14:00" in ls["Booking.com"]["quotes"]["check_in"])

print("2. compared with the hotel's own site")
site = {"check_in": "15:00", "check_out": "12:00", "stars": 5, "phone": "33140073434"}
rows = lf.compare(ls, site)
by = {(r["platform"], r["fact"]): r for r in rows}
check("Booking's 14:00 differs from the site's 15:00; its 12:00 matches", by[("Booking.com", "Check-in time")]["status"] == "differs" and by[("Booking.com", "Check-out time")]["status"] == "matches")
check("Booking's 4-star differs from the site's 5-star, and the phone matches on its last digits",
      by[("Booking.com", "Star rating")]["status"] == "differs" and by[("Booking.com", "Star rating")]["listing_says"] == "4-star" and by[("Expedia", "Telephone")]["status"] == "matches")
check("Expedia's 15:00 matches, and 'before noon' is read as 12:00, which matches", by[("Expedia", "Check-in time")]["status"] == "matches" and by[("Expedia", "Check-out time")]["status"] == "matches")
check("a fact only one side states is not a row (that is 'not shown', not a difference)", ("TripAdvisor", "Check-in time") not in by and len(lf.compare(ls, {})) == 0)
check("the site's facts come from its fact sheet and star rating",
      lf.site_facts({"fact_sheet": [{"fact": "Check-in time", "value": "from 15:00"}, {"fact": "Telephone", "value": "+33 1 40 07 34 34"}]}, [{"text": "our 5-star hotel"}])
      == {"check_in": "15:00", "phone": "33140073434", "stars": 5})

print("3. a listing that still shows a former name")
former = [{"name": "Marriott Opera Ambassador", "basis": "wording on the hotel's own site", "source": "x", "url": ""},
          {"name": "Hotel Old Guess", "basis": "the homepage title archived near 2018 does not contain the current name - a possible earlier name (inference)", "source": "Internet Archive", "url": ""}]
pp = P + [{"url": "https://www.hotels.com/ho123/marriott-opera-ambassador-paris", "title": "Marriott Opera Ambassador - Hotels.com", "cited_text": "Marriott Opera Ambassador, Paris"},
          {"url": "https://www.agoda.com/old", "title": "Hotel Old Guess, Paris", "cited_text": "Hotel Old Guess"}]
hits = lf.former_name_hits(pp, [], former, HOTEL)
check("a listing whose title shows the old name and not the current name is flagged, on its platform", [(h["platform"], h["name"]) for h in hits] == [("Hotels.com", "Marriott Opera Ambassador")], hits)
check("a listing that carries the CURRENT name as well is not flagged ('Paris Marriott Opera Ambassador Hotel' contains the former name inside it)", all(h["platform"] != "Booking.com" for h in hits))
check("a name that is only an inference from an archived homepage title is never used to flag anything", all(h["name"] != "Hotel Old Guess" for h in hits))

print("4. the whole block, and the advice")
blk = lf.build({"passages": P, "pages": []}, HOTEL, {"fact_sheet": [{"fact": "Check-in time", "value": "15:00"}, {"fact": "Check-out time", "value": "12:00"}]}, [{"text": "our 5-star hotel"}], [])
check("the block summarises quoted listings, facts compared and differences", blk["summary"]["platforms_quoted"] == 3 and blk["summary"]["compared"] == 5 and blk["summary"]["differs"] == 2, blk["summary"])
check("the block carries no passages or text beyond the quoted figures' short quotes", "passages" not in blk and all(len(r["passage"]) <= 200 for r in blk["rows"]))
check("no quoted passages, no block", lf.build({"passages": []}, HOTEL, {}, [], []) is None and lf.build(None, HOTEL, {}, [], []) is None)
recs = advice._from_listing_checks({**blk, "former_name": hits})
byid = {r["id"]: r for r in recs}
check("differences raise a medium recommendation worded as 'find out which is right', and a former name raises another", set(byid) == {"LC1", "LC2"} and byid["LC1"]["priority"] == "medium"
      and "which figure is correct" in byid["LC1"]["action"] and "may be right" in byid["LC1"]["why"], list(byid))
check("both name the platform and the figures, and cite the quoted page", "Booking.com shows check-in time 14:00" in byid["LC1"]["finding"] and byid["LC1"]["evidence"][0]["url"] == BK and "Hotels.com" in byid["LC2"]["finding"])
check("nothing raised when everything matches and no old name shows", advice._from_listing_checks({"rows": [{"status": "matches"}], "former_name": []}) == [] and advice._from_listing_checks(None) == [])

print("5. the lookup returns the quoted passages")


def resp():
    cites = [NS(url=BK, title="Booking", cited_text="Check-in from 14:00"), NS(url=BK, title="Booking", cited_text="Check-in from 14:00"), NS(url=EX, title="Expedia", cited_text="Check-out before noon")]
    return NS(content=[NS(type="web_search_tool_result", content=[NS(url=BK, title="t"), NS(url=EX, title="t")]), NS(type="text", text="Booking: check-in 14:00.", citations=cites)],
              stop_reason="end_turn", usage=NS(input_tokens=1000, output_tokens=100, server_tool_use=NS(web_search_requests=2)))


class Fake:
    def __init__(self):
        self.calls, self.messages = [], self

    def create(self, **kw):
        self.calls.append(kw)
        return resp()


fk = Fake()
r = ll.run(HOTEL, "Paris", client=fk)
check("the passages the model cited are kept (a repeat of the same passage once), and the request asks for what each listing shows",
      [(p["url"], p["cited_text"]) for p in r["passages"]] == [(BK, "Check-in from 14:00"), (EX, "Check-out before noon")] and "check-in time" in fk.calls[0]["messages"][0]["content"], r["passages"])
check("parse_passages ignores a citation with no passage", ai_sample.parse_passages(NS(content=[NS(type="text", text="x", citations=[NS(url=BK, title="t", cited_text="")])])) == [])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
