"""
Offline test: scraps of page text are never used as place names in prompts ('Parking Lot Airports Düsseldorf Airport', 'Airports Rhine Park'); a real nearby place is kept; a place the page names that is not
a known place near the hotel is dropped. No network. Run: python test_placenames.py
"""
import warnings

warnings.filterwarnings("ignore")
import ai_niche
import anchors
import placenames as pn

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. what is a place name")
check("'Airports Rhine Park' and 'Parking Lot ...' are not places", not pn.ok("Airports Rhine Park") and not pn.ok("Parking Lot Airports Düsseldorf Airport") and not pn.ok("Free Wi-Fi Rooms"))
check("real names are", pn.ok("Palais Garnier") and pn.ok("Louvre Museum") and pn.ok("Königsallee") and pn.ok("Museum of Modern Art") and pn.ok("Place de la Concorde"))
check("an airport name loses the scraps in front of it", pn.clean_airport("Parking Lot Airports Düsseldorf Airport") == "Düsseldorf Airport" and pn.clean_airport("Düsseldorf Airport") == "Düsseldorf Airport" and pn.clean_airport("Parking Lot Airport") is None)
check("a place is 'near' only when a known place around the hotel carries its name", pn.near("Königsallee", ["Königsallee", "Rheinturm"]) and pn.near("Rheinturm", ["Rheinturm (Düsseldorf)"]) and not pn.near("Rhine Park", ["Königsallee", "Rheinturm"]))

print("2. the airport in the profile")
PAGES = [{"url": "https://h.com/", "text": "Parking Lot Airports Düsseldorf Airport is 8 km away. Hilton Düsseldorf is a 5-star hotel in Düsseldorf."}]
ap = ai_niche.airport_from_text([p["text"] for p in PAGES], hotel="Hilton Düsseldorf")
check("the airport from the page text is the real name, not the scrap", ap and ap[0] == "Düsseldorf Airport", ap)
prof = ai_niche.profile("Hilton Düsseldorf", "Düsseldorf", [], {"airports": [{"name": "Düsseldorf Airport", "km": 7.4}]}, PAGES, [], [])
check("when the map knows the airport, the map's name is used", prof["airport"]["name"] == "Düsseldorf Airport" and prof["airport"]["source"] == "the map")

print("3. places the hotel's page names")
txt = [{"url": "https://h.com/", "text": "We are 10 minutes from the Louvre Museum and 3 minutes from Rhine Park. Airports Rhine Park is a short walk away.", "ok": True}]
own = anchors.from_pages(txt, "Hilton Düsseldorf")
check("scraps are dropped at the source", all(pn.ok(a["name"]) for a in own), [a["name"] for a in own])


def fetch(url, **kw):
    class R:
        status_code = 200

        def json(self):
            if "geosearch" in url and "gsradius=5000" in url:
                return {"query": {"geosearch": [{"title": "Louvre", "dist": 900}, {"title": "Palais Garnier", "dist": 1300}]}}
            return {"query": {"geosearch": []}}
    return R()


out = anchors.find(txt, "Hilton Düsseldorf", "Düsseldorf", location={"lat": 51.24, "lon": 6.77}, fetch=fetch)
names = [a["name"] for a in out["anchors"]]
check("a place the page names is kept when it is a known place near the hotel, and dropped when it is not", "Louvre Museum" in names and not any("Rhine Park" in n for n in names), names)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
