"""
Regression tests from the second Hilton Zurich Airport review (19 October 2026, report 2): an amenity filter strip quoted as evidence, a meeting-room table header taken as an attraction, a circular and
over-ranked OpenStreetMap action, and technical statements made about pages whose markup was never read. Offline, no network.
Run: python test_hilton2.py
"""
import re
import warnings

warnings.filterwarnings("ignore")
import advice
import assessment
import claude_reader
import guest_questions as gq
import insight_content as ic
import insight_tech
import places
import textutil
import traveller_ready as tr

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


STRIP = ("Airport shuttle Fitness center Business center Pet-friendly rooms Concierge EV charging Executive lounge Cribs Room service Meeting rooms All Amenities Families and kids "
         "Parking Pets Smoking WiFi")
BASE = "https://www.hilton.com/en/hotels/zrhhitw-hilton-zurich-airport/"
HOTEL = "Hilton Zurich Airport"

print("1. an amenity filter strip is removed, and nothing else is")
t = "Welcome. " + STRIP + " This hotel offers a bespoke Family Experience for travellers below the age of 12."
c = textutil.strip_label_runs(t)
check("the strip goes and the sentences around it stay", "Cribs" not in c and "Smoking" not in c and "Welcome." in c and "bespoke Family Experience" in c, c)
real = "Parking is free for guests. Pets are welcome. Wi-Fi is complimentary. The hotel has a spa and a gym, a restaurant and a bar."
check("real sentences that mention several amenities are untouched", textutil.strip_label_runs(real) == real)
check("three labels in a row are not enough to count as a strip", textutil.strip_label_runs("Parking Pets Smoking is not mentioned") == "Parking Pets Smoking is not mentioned")

print("2. a page read as plain text no longer carries the strip")
page = claude_reader.to_page(BASE, "---\ntitle: Hotel\n---\n# Hilton Zurich Airport\n\n" + STRIP + " This hotel offers rooms near the airport. " + "The hotel is close to the terminal. " * 12)
check("the page reader drops it", "Cribs" not in page["text"] and "close to the terminal" in page["text"], page["text"][:200])

print("3. so it cannot be quoted, or confirm a fact")
HOME = {"url": BASE, "title": "Hilton Zurich Airport", "h1": [], "ok": True, "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "",
        "text": "Welcome to Hilton Zurich Airport. " + STRIP + " The hotel stands next to the terminal and welcomes guests all year round. " * 3}
qs = {q["id"]: q for q in gq.evaluate([HOME])}
check("parking is not found on the strength of the strip", qs["parking"]["state"] in ("not_found", "needs_checking") and not qs["parking"].get("fact_snippets"), qs["parking"]["state"])
check("Wi-Fi is not found on the strength of the strip", qs["wifi"]["state"] in ("not_found", "needs_checking"), qs["wifi"]["state"])
site = ic.Site([HOME], BASE, HOTEL, "Zurich")
check("no check reads the strip from the site view either", all("Cribs" not in p["text"] for p in site.pages))

print("4. a parking price must be about parking")
INFO = {"url": BASE + "hotel-info/", "title": "Hotel info", "h1": [], "ok": True, "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "",
        "text": "Parking is available at the airport for guests. Taxis from the terminal cost about CHF 40. Breakfast is CHF 38 per person. " + "The hotel is a short walk from the terminal. " * 5}
req = next(r for s in tr.SEGMENTS for r in s["requirements"] if r["id"] == "airport_parking")
rx = req["facts"]["its price (or that it is free)"]
check("a taxi fare and a breakfast price do not make the parking price known", not any(rx.search(x) for x in ("Taxis from the terminal cost about CHF 40.", "Breakfast is CHF 38 per person.")))
check("a parking price does", rx.search("Self parking is CHF 35 per day.") and rx.search("A car park space costs CHF 35 a day.") and rx.search("Parking is free for guests."))

print("5. a meeting-room table header is not an attraction")
check("'Name Banquet Conference Square' is rejected", places.find("Name Banquet Conference Square feet Theatre", "attraction", HOTEL) == [])
check("a real square is still a place", [p["name"] for p in places.find("The hotel is near Trafalgar Square.", "attraction", "Some Hotel")] == ["Trafalgar Square"])

print("6. an uncertain open-map match is a prompt to check, never a verified finding, and never near the top")
intel = {"ledger": [], "recommendations": [{"id": "S-entity_unverified:OpenStreetMap", "section": "entity", "title": "Confirm the OpenStreetMap entry is this hotel", "problem": "Confirm the OpenStreetMap entry is this hotel",
                                           "why_it_matters": "Matched on name only.", "action": "Confirm the OpenStreetMap entry is this hotel", "priority": "medium", "team": "distribution", "evidence_ids": [],
                                           "basis": "observation", "basis_note": "", "success_check": "The next audit no longer lists it."}]}
r = advice._from_intel(intel)[0]
check("it is an opportunity, low priority, a reasonable inference", r.get("kind_hint") == "opportunity" and r["priority"] == "low" and r["confidence"] == advice.INFER, f"{r.get('kind_hint')} {r['priority']} {r['confidence']}")
check("its evidence says what the match lacked, not the action itself", "could not be matched on anything else" in r["evidence"][0]["snippet"] and r["evidence"][0]["snippet"] != r["action"])

print("7. nothing is said about technical quality, or structured data, when the markup was not read")
import report_pdf_mgmt
src = open("report_pdf_mgmt.py", encoding="utf8").read()
check("the PDF says the technical checks were not made rather than 'no significant technical issue'", "No technical conclusion is drawn" in src and src.index("No technical conclusion") < src.index("No significant technical issue was found"))
isrc = open("insight_tech.py", encoding="utf8").read()
check("entity clarity leaves structured data out for a plain-text read instead of counting it against the hotel", "structured data not assessed (the pages were read as plain text)" in isrc)

print("8. wording, sitemap and the audit's own notes")
rec = {}
advice._name_group(rec, [{"short": "the area around the hotel", "question": "q", "missing": ["x"], "found": [], "id": "area_guide"}], "/location/", "fix")
check("a single-topic title reads as a sentence", rec["short_title"] == "Add the missing details on the area around the hotel to /location/", rec["short_title"])
rep = {"consultant": {"coverage": {"pages_read": 6, "pages_attempted": 6, "text_only": True}}, "guest_questions": {"questions": []}, "site": {"robots": {"present": False, "status": 403}, "sitemap": {"present": True, "url_count": 0}}, "web_signals": {}}
a = assessment.assess(rep)
check("a sitemap with no readable addresses is not 'assessed'", not any(i["what"] == "The sitemap" for i in a["assessed"]) and any(i["what"] == "The sitemap" for i in a["partial"]))
check("the audit's note about pages inspected is shown as a note, not as a quotation", "Audit note:" in open("report_pdf_mgmt.py", encoding="utf8").read())

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
