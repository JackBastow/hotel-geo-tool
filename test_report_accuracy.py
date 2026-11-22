"""
The false findings and contradictions found in a real report (THE NICI Newquay, reviewed independently), each turned into a check, so none comes back.
Offline: page text is given inline.
Run: python test_report_accuracy.py
"""
import sys
import warnings

warnings.filterwarnings("ignore")
import ai_insights
import ai_sample
import former_names
import guest_questions as gq
import insight_content as ic
import places
import ranking
import report_pdf
import scoring
import strategy_actions
import textutil
import urlscope

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


H, C = "THE NICI Newquay", "Newquay"

print("1. a brand site with several hotels: only this hotel's section is its website")
check("thenici.com/newquay/ is the Newquay hotel's own section, not the whole brand site", urlscope.normalise("https://thenici.com/newquay/", H, C) == ("https://thenici.com/newquay/", "/newquay/"))
check("an inner page of it keeps the same section", urlscope.normalise("https://thenici.com/newquay/faqs/", H, C)[1] == "/newquay/")
check("an ordinary hotel site with an inner page pasted is still the whole site", urlscope.normalise("https://brooklands.example/rooms/", "Brooklands Hotel", "Weybridge") == ("https://brooklands.example/", None))
check("a known chain folder still works as before", urlscope.normalise("https://www.hilton.com/en/hotels/lonhitw-hilton-london/", "Hilton London", "London")[1] == "/en/hotels/lonhitw-hilton-london/")
check("a folder that is not the hotel's town or name is not taken as its section", urlscope.normalise("https://example.com/new-forest/", H, C)[1] is None)

print("2. check-out: the standard time, not the paid late check-out")
txt = "What time is check-out? Check-out is 11:00am. Can I have a late check-out? Late check-out is available up until 12:00pm at a charge of £35."
check("late check-out is an option, not a second check-out time", sorted({t for t, *_ in gq._times_for([{"text": txt, "url": "u"}], gq._CO)}) == ["11:00"])
check("a standard time followed by a late option is still read", sorted({t for t, *_ in gq._times_for([{"text": "Check-out is 11am; late check-out on request.", "url": "u"}], gq._CO)}) == ["11:00"])
check("early check-in is not the check-in time", sorted({t for t, *_ in gq._times_for([{"text": "Early check-in from 1pm for £20. Check-in is from 3pm.", "url": "u"}], gq._CI)}) == ["15:00"])


class FakeSite:
    def __init__(self, pages, hotel=H, city=C):
        self.content_pages, self.pages, self.hotel, self.city, self.base = pages, pages, hotel, city, "https://thenici.com/newquay/"

    def find(self, rx):
        out = []
        for p in self.content_pages:
            for m in rx.finditer(p["text"]):
                out.append({"page": p, "snippet": textutil.sentence_of(p["text"], m.start(), m.end())})
        return out

    def path(self, p):
        return "/"

    def is_home(self, p):
        return True


print("3. addresses: another hotel's or the company's registered office is not the hotel's")
footer = ("THE NICI Newquay East Street, Newquay, TR7 1DB 01841 724555 © 2026 by THE NICI (Newquay) Limited Trading as THE NICI. Registered in England & Wales 15651109 at THE NICI, "
          "West Hill Road, Bournemouth, BH2 5EJ Privacy Policy")
site = FakeSite([{"url": "https://thenici.com/newquay/", "text": footer + " Please use postcode: TR7 1DB", "footer_text": "", "tels": []},
                 {"url": "https://thenici.com/newquay/contact/", "text": "Find us: East Street, Newquay, TR7 1DB.", "footer_text": "", "tels": []}])
out = ic.consistency(site, {"conflicts": []})
types = [o["type"] for o in out]
check("the registered office's postcode in the small print is not a second postcode", "postcode" not in types, out)
check("'Newquay East Street' and 'East Street' are one street", "address" not in types, out)

print("4. offers, origins and plain 'no' answers")
site2 = FakeSite([{"url": "u1", "text": "BLACK FRIDAY: an overnight stay for two, a welcome drink and £50 spa treatment discount. With complimentary parking and dogs staying free.", "footer_text": "", "tels": []},
                  {"url": "u2", "text": "Parking is offered on a first-come basis. Parking is charged at £27 per night.", "footer_text": "", "tels": []}])
check("'complimentary parking' inside a package offer is not the hotel's parking rule", not any(o["type"] == "amenity" for o in ic.consistency(site2, {"conflicts": []})))
s = "With convenient connections from cities including London, Manchester, Edinburgh and beyond, your Cornish escape is closer than you think."
check("a city guests travel FROM is not a place near the hotel", places.is_origin(s, "Edinburgh") and not places.is_origin("Direct flights from London Gatwick land at Newquay Airport.", "Newquay Airport"))
t = "Do the hotels have interconnecting rooms? Unfortunately we don’t offer interconnecting rooms at THE NICI Newquay."
i = t.rfind("interconnecting")
check("'we don't offer interconnecting rooms' is read as a clear no", textutil.is_negated(t, i, i + len("interconnecting")))
check("while 'we have interconnecting rooms' is not", not textutil.is_negated("We have interconnecting rooms on request.", 8, 23))

print("5. a renamed hotel: the former name is found and connected")
fn = former_names.find([{"url": "u", "text": "*Please note this property was previously known as Hotel Victoria, so you may see this name on older maps or GPS listings."},
                        {"url": "v", "text": "This former Victorian hotel... For press enquiries, contact Victoria Rose."}], H)
check("the former name is found, and a description or a person's name is not", [x["name"] for x in fn] == ["Hotel Victoria"], fn)
rec = former_names.recommendation(fn, H, [{"source": "OpenStreetMap", "found": True, "found_as": "Hotel Victoria"}])
check("it becomes a high-priority action, saying where the old name is still listed", rec["priority"] == "high" and "OpenStreetMap still lists it under the old name" in rec["finding"] and len(rec["steps"]) >= 3)

print("6. one count of AI visibility for the whole report")
ai = {"status": "ok", "items": [{"id": f"q{i}", "qid": f"q{i}", "kind": "niche", "text": "x", "mentioned": i < 6, "domains": [], "answer": "a"} for i in range(24)]}
ai["summary"] = ai_sample.summarise(ai["items"])
ext = {"answers": {f"q{i}": [{"name": "The Nici, Newquay", "rank": 2}] for i in range(6, 9)}}
ext["answers"]["q10"] = [{"name": "THE NICI Bournemouth", "rank": 1}]
n = ai_insights.reconcile(ai, ext, H)
check("answers the reading shows naming the hotel are counted, so every page says the same", n == 3 and sum(1 for x in ai["items"] if x["mentioned"]) == 9, n)
check("but a sister hotel of the same brand never is", not ai["items"][10]["mentioned"])

print("7. honest scores and clean PDFs")
ent = scoring.score_entity([{"source": "OpenStreetMap", "found": False}, {"source": "Wikidata", "found": False}], [], {"postcode": "TR7 1DB"})
check("a name search that finds nothing is not scored as a certain zero", ent["score"] > 0, ent["score"])
check("PDF text never shows web markup", str(report_pdf.esc("The Headland &amp; Spa <b>(3 of 3)</b>")) == "The Headland &amp; Spa (3 of 3)")
check("OYO and similar are booking sites (never 'get onto oyorooms.com')", strategy_actions.is_listing_site("oyorooms.com") and strategy_actions.is_listing_site("laterooms.com"))
recs = [{"id": "fix1", "kind": "fix", "priority": "high", "effort": "low", "value": 60, "rank": 90, "source": "consistency"},
        {"id": "opp1", "kind": "opportunity", "priority": "high", "effort": "medium", "value": 70, "rank": 80, "source": "ai_gap", "track": "visibility"}]
plan = ranking.plan_30_60_90(recs, set())
check("the strongest AI-visibility opportunity starts in the first 30 days", "opp1" in plan["30"], plan)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
