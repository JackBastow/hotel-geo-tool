"""
Offline test: the booking-platform check compares the NAME each platform shows, the postcode, the phone and the check-in/out times with the hotel's own site; a difference lowers the OTA score and becomes a
recommendation; agreement across enough details lifts it (never above 90); nothing is guessed when a platform shows nothing. No network. Run: python test_ota_names.py
"""
import copy
import json
import warnings

warnings.filterwarnings("ignore")
import advice
import listing_facts as lf
import scoring

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL = "Hilton Paris Charles de Gaulle Airport"
print("1. the name a platform shows")
check("the platform's own name, prices and the town are removed from a title", lf.shown_name("Hilton Paris Charles de Gaulle Airport, Roissy-en-France (France) - Booking.com") == HOTEL)
check("an identical name is the same, whatever the capitals, accents or punctuation", lf.name_verdict(HOTEL, HOTEL)[0] == "same" and lf.name_verdict(HOTEL.upper(), HOTEL)[0] == "same")
check("an extra 'Hotel' on the end is NOT the same: it is a close wording difference, and says so", lf.name_verdict("Hilton Paris Charles de Gaulle Airport Hotel", HOTEL)[0] == "close")
check("'CDG' and 'Charles de Gaulle' are the same airport written two ways", lf.name_verdict("Hilton Paris CDG Airport", HOTEL)[0] == "same")
v, why = lf.name_verdict("Hilton Hotel Paris Airport", HOTEL)
check("a name that drops identifying words is different, and says which words", v == "differs" and "charles" in why, (v, why))
BH, PL = "Brooklands Hotel", "Surrey/Weybridge"
sn = lambda t: lf.shown_name(t, BH, PL)      # noqa: E731
check("'Brooklands Hotel & Spa' and 'Hotel Brooklands' are close but not the same, and the difference is stated", lf.name_verdict(sn("Brooklands Hotel & Spa - Booking.com"), BH, PL) == ("close", "the listing adds and, spa") and lf.name_verdict(sn("Hotel Brooklands - Trivago"), BH, PL)[0] == "close")
check("'Brooklands Hotel', in capitals, with the town added is the same", lf.name_verdict(sn("BROOKLANDS HOTEL - Tripadvisor"), BH, PL)[0] == "same" and lf.name_verdict(sn("Brooklands Hotel Surrey: Reviews & 2026 prices | Trip.com"), BH, PL)[0] == "same")
check("a title that holds no name at all ('rate per night') is not shown, never a difference", sn("Hotels in Weybridge - rate per night - Kayak") == "")
check("an added identifying word is a different name", lf.name_verdict(sn("Brooklands Country Club Hotel - Hotels.com"), BH, PL)[0] == "differs")
check("a different property's name is flagged as different", lf.name_verdict("Brooklands Hotel", HOTEL)[0] == "differs")

print("2. passages in, comparison rows out")
P = [{"url": "https://www.booking.com/hotel/fr/hilton-paris-cdg.html", "title": "Hilton Paris Charles de Gaulle Airport, Roissy - Booking.com", "cited_text": "Hilton Paris Charles de Gaulle Airport, Tremblay-en-France 95700. Check-in from 15:00. Tel +33 1 49 19 77 77."},
     {"url": "https://www.expedia.co.uk/Roissy-Hotels-Hilton.h1.Hotel-Information", "title": "Hilton Hotel Paris Airport - Expedia", "cited_text": "Hilton Hotel Paris Airport, 95700. Check-in time starts at 2:00 PM."},
     {"url": "https://www.tripadvisor.co.uk/Hotel_Review-Brooklands.html", "title": "Brooklands Hotel - Tripadvisor", "cited_text": "Brooklands Hotel, KT13 0SL"}]
SITE = {"name": HOTEL, "check_in": "15:00", "phone": "33149197777", "postcode": "95700"}
listings = lf.listing_facts(P, HOTEL, SITE)
check("a platform whose page is about another hotel is not used", "TripAdvisor" not in listings, list(listings))
check("the name each platform shows is captured", listings["Booking.com"]["name"] == HOTEL and listings["Expedia"]["name"] == "Hilton Hotel Paris Airport")
rows = lf.compare(listings, SITE)
by = {(r["platform"], r["fact"]): r for r in rows}
check("Booking.com's name matches and its check-in matches", by[("Booking.com", "Hotel name")]["status"] == "matches" and by[("Booking.com", "Check-in time")]["status"] == "matches")
check("Expedia's shortened name and later check-in time are differences, with the difference in words", by[("Expedia", "Hotel name")]["status"] == "differs" and by[("Expedia", "Hotel name")]["level"] == "differs" and "charles" in by[("Expedia", "Hotel name")]["note"] and by[("Expedia", "Check-in time")]["status"] == "differs")
lc = {"rows": rows, "listings": {}, "former_name": [], "names": [{"platform": p, "shown_name": l["name"], "status": by[(p, "Hotel name")]["status"], "url": l["url"]} for p, l in listings.items()]}
recs = advice._from_listing_checks(lc)
check("the differences become one recommendation that names them", recs and "hotel name" in recs[0]["finding"] and "Expedia" in recs[0]["finding"], recs[0]["finding"] if recs else "")

print("3. the OTA score")
base = json.load(open("tests_data/sample_report.json", encoding="utf8"))["scorecard"]
for c in base["categories"]:
    if c["key"] == "otas":
        c["score"] = 75


def sc():
    return copy.deepcopy(base)


s1 = sc()
d = scoring.apply_listings(s1, lc)
ota = next(c for c in s1["categories"] if c["key"] == "otas")
check("differences lower the OTA score (10 points each) and the evidence says why", d < 0 and ota["score"] == 75 - 10 * len([r for r in rows if r["status"] == "differs"]) and "Lowered from 75" in ota["evidence"][-1], (ota["score"], ota["evidence"][-1]))
check("the overall score is worked out again", s1["overall"] != base["overall"])
sc_close = sc()
scoring.apply_listings(sc_close, {"rows": [{"platform": "A", "fact": "Hotel name", "status": "differs", "level": "close", "listing_says": "x", "site_says": "y", "url": "u", "passage": ""}]})
check("a wording-only difference costs 3 points, not 10", next(c for c in sc_close["categories"] if c["key"] == "otas")["score"] == 72)
good = [{"platform": p, "fact": f, "listing_says": "x", "site_says": "x", "status": "matches", "url": "u", "passage": ""} for p in ("Booking.com", "Expedia") for f in ("Hotel name", "Check-in time", "Telephone")]
s2 = sc()
scoring.apply_listings(s2, {"rows": good})
check("six agreeing details on two platforms raise it, to 90 at the most", next(c for c in s2["categories"] if c["key"] == "otas")["score"] == 90)
s3 = sc()
check("too few comparisons change nothing", scoring.apply_listings(s3, {"rows": good[:2]}) == 0 and next(c for c in s3["categories"] if c["key"] == "otas")["score"] == 75)
s4 = sc()
check("no listing data changes nothing", scoring.apply_listings(s4, None) == 0 and scoring.apply_listings(s4, {"rows": []}) == 0)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
