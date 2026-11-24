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
import report_gate
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

print("8. listings we found are shown as found; booking sites are never 'publishers'")
import copy
import json
import os
import source_actions
base = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
r8 = copy.deepcopy(base)
r8["meta"]["base"] = "https://thenici.com/newquay/"
r8["ai_insights"] = {**(r8.get("ai_insights") or {}), "pages": [
    {"url": "https://www.booking.com/searchresults.html?ss=Newquay", "domain": "booking.com", "cited": 5, "names_hotel": False, "names_competitor": "Fistral Beach Hotel and Spa"},
    {"url": "https://www.oyorooms.com/gb/newquay", "domain": "oyorooms.com", "cited": 2, "names_hotel": False, "names_competitor": "Fistral Beach Hotel and Spa"},
    {"url": "https://www.expedia.co.uk/Newquay-Hotels.d123", "domain": "expedia.co.uk", "cited": 2, "names_hotel": False, "names_competitor": "Great Western"}]}
r8["ai_gap"] = {"status": "ok", "markets": [], "articles": []}
r8["intel"] = {"identity": {"footprint": [{"platform": "Booking.com", "discovered": True, "url": "https://www.booking.com/hotel/gb/the-nici-newquay.html"},
                                          {"platform": "Expedia", "discovered": False, "url": ""}]}}
rows = {s["domain"]: s for s in source_actions.build(r8, limit=20)}
check("a listing the audit found in search results shows as there, with its link", source_actions.presence_text(rows["booking.com"]).startswith("Yes") and rows["booking.com"]["listing_url"].endswith("the-nici-newquay.html"), rows.get("booking.com"))
check("one our searches did not find says so, without claiming it is not listed", "does not show it is not listed" in source_actions.presence_text(rows["expedia.co.uk"]))
check("OYO is a booking site, not a 'travel publisher'", rows["oyorooms.com"]["type"] in ("comparison", "review"), rows["oyorooms.com"]["type"])
la = next(a for a in strategy_actions.build(r8, {"reasons": ["surf lessons"]}, H) if a["tag"] == "listings")
check("the listings action links to the listing found and asks to check the others", la["steps"][0]["link"]["url"].endswith("the-nici-newquay.html") and any("Check whether you are listed on expedia.co.uk" in s["title"] for s in la["steps"]))

print("9. the right questions for the hotel")
import ai_niche
prof = ai_niche.profile(H, C, [], None, [{"text": "Newquay Airport: 15 minute drive. Our beachfront spa hotel above Great Western Beach.", "url": "u"}], [], [], classes=["resort", "spa_hotel"])
check("a beach hotel 12 km from a regional airport is not an 'airport hotel'", not prof["airport_hotel"] and not any(a["key"] == "airport" for a in prof.get("audiences") or []), (prof["airport_hotel"], prof.get("audiences")))
prof2 = ai_niche.profile("Hilton London Heathrow Airport", "London", [], None, [{"text": "Heathrow Airport: 1 km, a 5 minute walk to Terminal 4.", "url": "u"}], [], [], classes=["airport"])
check("while a hotel at the airport is", prof2["airport_hotel"])
import prompt_analysis
r9 = copy.deepcopy(base)
r9["ai_sample"] = {"status": "ok", "items": [{"id": "q1", "qid": "q1", "kind": "niche", "text": "Which luxury hotels in Newquay have a spa?", "source": "feature", "mentioned": False}]}
r9["benchmark"] = {"prompts": [{"text": "Which luxury hotels in Newquay have a spa?"}], "reused": False}
r9["ai_gap"] = {"status": "ok", "markets": [{"qid": "q1", "kind": "niche", "question": "Which luxury hotels in Newquay have a spa?", "named": 0, "of": 2, "status": "not_named", "rivals": [], "other_category": []}]}
check("on a first check, the questions frozen as the hotel's tracked set count as tracked", "1 of them your tracked prompts" in prompt_analysis.panel(r9))
r9["question_plan"] = {"error": "TimeoutError: x"}
check("a check where the question writer failed says so", "Fewer questions than usual" in prompt_analysis.panel(r9))

print("10. reading pages properly (found in the multi-hotel review)")
h = gq._parse_html("https://x/", "<html><body><main><p>Banner</p></main><div>" + "Our rooms are large and quiet, with sea views and a king bed. " * 10 + "</div><script></script></body></html>")
check("a page whose <main> holds only a banner is read from the whole page", len(h["text"]) > 300 and not h["app_shell"])
inv = "Estate​‌ Rooms﻿ with a king‍ bed"
check("invisible characters some sites scatter through their text are removed", gq._clean(inv) == "Estate Rooms with a king bed")
shell = gq._parse_html("https://x/", '<html><body><div id="root"></div>' + "<script src=a.js></script>" * 3 + "</body></html>")
check("an empty page built by scripts is an app shell", shell["app_shell"])
att = gq._parse_html("https://x/logo-2/", '<html><body class="attachment single-attachment"><img src="logo.png">' + "<script></script>" * 10 + "</body></html>")
check("a WordPress picture page is not called 'built with JavaScript'", not att["app_shell"])
import langid
check("a Swedish site is recognised as Swedish", langid.detect("Välkommen till Skandinaviens största safaripark. Här rör sig visenter och kronvilt fritt genom skog och savann. Bo i hjärtat av naturen och njut av råvaror från skog och hav. Det är en plats som är vår och er, med rum för alla som vill uppleva naturen på riktigt och där du kan vandra.", min_words=30)[0] == "sv")
import consultant


class _S:
    pass


s_ = _S()
s_.content_pages = [{"title": "FISTRAL BEACH NEWQUAY | Fistral Beach Newquay Cornwall", "h1": [], "text": "Rick Stein's restaurant serves fish and chips. Surf competitions all summer.", "url": "u"}]
s_.home = s_.content_pages[0]
check("a website that is not the hotel's (an area guide) is flagged before anything else", consultant.site_identity(s_, "Fistral Beach Hotel and Spa")["priority"] == "critical")
s_.content_pages = [{"title": "Chewton Glen Hotel & Spa | Official Website", "h1": [], "text": "x", "url": "u"}]
s_.home = s_.content_pages[0]
check("while a real hotel site is not", consultant.site_identity(s_, "Chewton Glen") is None)
s_.content_pages = [{"title": "FISTRAL BEACH NEWQUAY | Fistral Beach Newquay Cornwall", "h1": [], "url": "u",
                     "text": "Be sure to check out The Fish House. Check out the surf school. Check out our beach webcam."}]
s_.home = s_.content_pages[0]
check("'be sure to check out The Fish House' is not hotel check-out wording (the real Fistral beach guide)", (consultant.site_identity(s_, "Fistral Beach Hotel and Spa") or {}).get("priority") == "critical")
s_.content_pages = [{"title": "The Headland | Newquay", "h1": [], "url": "u", "text": "Check-in is from 3pm and check out is by 11am. Our rooms overlook the sea. Book your stay today."}]
s_.home = s_.content_pages[0]
check("while a hotel page stating check-in and check-out times is not flagged", consultant.site_identity(s_, "The Headland Hotel") is None)
import report_check
check("the events facility is not reconciled against the location need 'Event venues and business destinations'",
      not __import__("re").search(report_check.FD_TO_REQUIREMENT["events"], "Event venues and business destinations", __import__("re").I)
      and __import__("re").search(report_check.FD_TO_REQUIREMENT["events"], "Meeting facilities", __import__("re").I))

import guest_questions as _gq
_B = "https://fistralbeach.co.uk/"
_fp = [{"url": _B + path, "title": "FISTRAL BEACH NEWQUAY | Fistral Beach Newquay Cornwall", "text": text, "h1": [], "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "", "ok": True}
       for path, text in [("", "Fistral Beach is Newquay's most famous surf beach. Be sure to check out The Fish House and the surf school. " * 4),
                          ("food-and-drink/", "Rick Stein's restaurant serves fish and chips. The Stable offers pizzas and ciders. Check out the Pasty Shack. " * 4),
                          ("surf/", "Surf lessons run all year at Fistral. Boards and wetsuits can be hired by the hour from the beach huts. " * 4)]]
_out = consultant.analyse(own_pages=_fp, pages_meta=[{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in _fp], base=_B, hotel="Fistral Beach Hotel and Spa", city="Newquay",
                          location={"lat": 50.41, "lon": -5.1}, guest={"questions": _gq.evaluate(_fp), "conflicts": [], "own_facts_node": {}, "pages_ok": 3, "pages_attempted": 3},
                          site={"robots": {"present": False, "status": 200}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
check("end to end: a beach guide audited as a hotel gives a full analysis (no crash) led by 'Check this is the hotel's own website'",
      not _out.get("error") and (_out.get("recommendations") or [{}])[0].get("tag") == "site-check" and "ID-site-check" in [(t if isinstance(t, str) else t.get("id")) for t in _out.get("top_actions") or []],
      _out.get("error") or [r.get("id") for r in (_out.get("recommendations") or [])[:3]])
_g = report_gate.check({"consultant": {"error": "KeyError: 'value'"}, "meta": {}, "guest_questions": {"error": "timeout"}})["gate"]
check("a crashed analysis or step is flagged for a person to look at, never silently an empty report",
      any("analysis crashed" in x["what"] for x in _g["needs_review"]) and any("guest questions step failed" in x["what"] for x in _g["needs_review"]), _g.get("needs_review"))

print("11. the operator's quality panel")
import quality_view
g_rep = {"gate": {"checks": [{"name": "listing_claims", "looked_at": 9, "found": 1, "summary": "x"}], "changes": [{"check": "listing_claims", "id": "l", "what": "1 claim reworded"}],
                  "needs_review": [{"what": "Only 3 of 20 pages of the website could be read."}, {"what": "Only 3 of 20 pages of the website could be read."}], "error": "KeyError: 'x'", "summary": "1 check ran."}}
qp = quality_view.panel(g_rep)
check("what needs a person's eye is listed once each, with a check that crashed shown as a bug", qp.count("Only 3 of 20") == 1 and "stopped part-way" in qp and "1 claim reworded" in qp)
check("a report from before the checks existed shows no panel, and a clean one says nothing needs looking at",
      quality_view.panel({}) == "" and "Nothing in the latest report" in quality_view.panel({"gate": {"checks": [], "changes": [], "needs_review": []}}))

print("12. the traveller's country (Brooklands, Nov 2026: 'hotels in Surrey' was answered about Surrey in Canada)")
check("a UK postcode or a map position places the hotel's country when its website ends in .com",
      ai_sample.country_from_location({"postcode": "KT13 0SL"}) == "GB" and ai_sample.country_from_location({"lat": 50.41, "lon": -5.08}) == "GB"
      and ai_sample.country_from_location({"lat": 53.35, "lon": -6.26}) == "IE" and ai_sample.country_from_location({"lat": 56.17, "lon": 14.86}) == "SE" and ai_sample.country_from_location({}) is None)
check("the assistant is told the traveller's country, so an ambiguous place name means the one there", "lives in the United Kingdom" in ai_sample.system_for("GB") and ai_sample.system_for(None) == ai_sample.SYSTEM)
import quality_view as _qv
check("a hotel entered as its web address, or a town naming two places, is flagged", len(_qv.setup_problems("brooklandshotelsurrey", "Surrey/Weybridge", "https://brooklandshotelsurrey.com/")) == 2
      and _qv.setup_problems("Brooklands Hotel", "Weybridge", "https://brooklandshotelsurrey.com/") == [] and "only the brand" in _qv.setup_problems("Hilton", "Barcelona")[0])

print("13. the Overview shows the same scorecard and lists as the management report")
import json as _json, os as _os, re as _re
import dashboard_view, glance
_sr = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tests_data", "sample_report.json"), encoding="utf8"))
_n = glance.ai_named(_sr)
_card = dashboard_view.at_a_glance(_sr)
_sc = glance.scorecard_html(_sr)
check("'Is the hotel named?' and the scorecard give one figure, from the report's one count", bool(_n) and f"{round(100 * _n[0] / _n[1])}%" in _card and f"Named in {_n[0]} of {_n[1]} answers" in _sc, (_n, _re.sub("<[^>]+>", " ", _card)[:200]))
_good, _bad = glance.strengths_weaknesses(_sr)
_sw = glance.strengths_html(_sr)
check("the two lists on the Overview are the management report's lists", (_good or _bad) and all(__import__("html").escape(x) in _sw for x in _good + _bad))
check("the Overview banner shows the readiness score", "AI discoverability readiness" in dashboard_view.readiness_banner(_sr, {"headline_score": 50}))

print("14. is the hotel named? one matcher (code review, Nov 2026)")
_NAMED = [("Fistral Beach Hotel and Spa", "Newquay", "1. Headland Hotel - right above Fistral Beach, great for surfers.", False, "a place with the hotel's name (the beach) is not the hotel"),
          ("Fistral Beach Hotel and Spa", "Newquay", "2. Fistral Beach Hotel - spa with sea views", True, "the hotel written as a hotel is"),
          ("Park Hotel", "London", "1. Hyde Park Hotel", False, "another hotel's longer name is not the hotel"),
          ("Park Hotel", "London", "Stay at the Park Hotel near the station.", True, "the name on its own is"),
          ("THE NICI Newquay", "Newquay", "1. Headland Hotel\n2. The Nici - boutique", True, "the name without the town counts ('The Nici')"),
          ("Eriksberg Hotel & Nature Reserve", "Karlshamn", "Try Eriksberg Hotel, a great base", True, "the part before '&' counts"),
          ("THE PIG at Combe", "Honiton", "The Pig at Combe is lovely", True, "the name with or without 'The' counts"),
          ("The Hoxton, Shoreditch", "London", "Hoxton Hotel in Shoreditch", True, "the part before the comma, written as a hotel, counts"),
          ("Hilton Barcelona", "Barcelona", "The Hilton Diagonal Mar Barcelona is near the beach", False, "the brand alone is not the hotel"),
          ("Hilton Dusseldorf", "Dusseldorf", "Hampton by Hilton Dusseldorf City Centre", False, "'X by Brand' is another hotel of the brand"),
          ("Brooklands Hotel", "Weybridge", "The Brooklands Museum is great", False, "a one-word name used for something else is not the hotel"),
          ("Brooklands Hotel", "Weybridge", "In Weybridge, Brooklands is the stylish choice.", True, "a one-word name with the town in the sentence is"),
          ("Paris Marriott Opera Ambassador Hotel", "Paris", "Marriott Opera Ambassador is near Galeries Lafayette", True, "the name without the town in front counts"),
          ("Hilton Paris Charles de Gaulle Airport", "Paris", "1. **Hilton Paris Charles de Gaulle Airport** - next to Terminal 2", True, "a chain hotel named after an airport is the hotel")]
for _h, _c, _t, _exp, _why in _NAMED:
    check(_why + f" ({_h})", ai_sample.mentioned(_t, _h, _c) == _exp, (_t, ai_sample.mentioned(_t, _h, _c)))
check("'not the best choice' is not a recommendation", not ai_sample.recommended("Chewton Glen is not the best choice for families on a budget.", "Chewton Glen", "New Milton"))
check("the bullets under a hotel are details, not list places", ai_sample.list_position("1. Lime Wood\n - Spa\n - From 400\n2. Chewton Glen", "Chewton Glen") == 2)

print("15. a brand hotel that says no, prices in euros, and no spa (Paris Marriott review, Nov 2026)")
import consultant
import hotel_class
import traveller_ready
_MB = "https://www.marriott.com/en-us/hotels/parmc-paris-marriott-opera-ambassador-hotel/"
_MH = "Paris Marriott Opera Ambassador Hotel"


def _mp(path, title, text):
    return {"url": _MB + path, "title": title, "text": text, "h1": [title], "tels": ["+33 1 44 83 40 40"], "mails": [], "links": [], "signals": {}, "footer_text": "", "ok": True}


_MPAGES = [
    _mp("overview/", _MH, "Paris Marriott Opera Ambassador Hotel is located on Boulevard Haussmann in the Opera district, five minutes from Palais Garnier and Galeries Lafayette. "
        "The hotel has 297 rooms and suites, an Executive Lounge with views over the Paris skyline, and nine meeting rooms with 752 square metres of event space for up to 250 guests. "
        "Built in 1927, the hotel keeps its Art Deco character. Check-in time: 3:00 PM. Check-out time: 12:00 PM. Pets are not allowed. Free Wi-Fi in all rooms. "
        "There is no spa at the hotel, but several day spas are nearby for massage treatments. A 24-hour fitness centre is available to guests. "),
    _mp("faq/", "FAQ", "Frequently asked questions. Does Paris Marriott Opera Ambassador Hotel have EV charging? No, Paris Marriott Opera Ambassador Hotel does not have electric vehicle charging stations. "
        "Is there parking at the hotel? There is no on-site parking. Guests can use the partner car park Indigo Haussmann, 200 metres away, at a daily rate of EUR 35. "
        "Is breakfast included? Breakfast is served daily from 6:30 AM to 10:30 AM in Brasserie Sixtine and costs EUR 39 per person. "),
    _mp("dining/", "Dining", "Brasserie Sixtine serves modern French cuisine. Opening hours: Monday to Friday 12:00 to 14:30 and 17:30 to 22:00; Saturday 17:30 to 22:00; Sunday closed. "
        "Breakfast is served from 6:30 to 10:30 every day. Bar Lindbergh is open daily from 17:00 to 01:00 and serves cocktails and light dishes. "),
    _mp("location/", "Location", "Getting here. Charles de Gaulle International Airport: 30 km. Paris-Orly Airport: 18 km. Auber RER station: 200 m. Gare du Nord: 2 km. "
        "Metro: Chaussée d'Antin La Fayette, 2-minute walk. Taxi from Charles de Gaulle takes about 45 minutes. "),
    _mp("events/", "Meetings and events", "Nine meeting rooms, 752 square metres of event space, the largest room seats 250 theatre style. Contact our events team for a proposal. "),
    _mp("rooms/", "Rooms", "Our 297 rooms and suites offer king or twin beds, rain showers and city views. Suites sleep up to four guests. "),
]
_mq = {q["id"]: q.get("state") for q in gq.evaluate(_MPAGES)}
for _k in ("ev", "parking", "checkin_out", "wifi", "breakfast", "transport"):
    check(f"'{_k}' is answered from the hotel's own words (a clear 'no', a euro price, times on the overview page)", _mq.get(_k) == "answered", _mq.get(_k))
_mguest = {"questions": gq.evaluate(_MPAGES), "conflicts": [], "own_facts_node": {}, "pages_ok": len(_MPAGES), "pages_attempted": len(_MPAGES)}
_mout = consultant.analyse(own_pages=_MPAGES, pages_meta=[{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in _MPAGES], base=_MB, hotel=_MH, city="Paris",
                           location={"lat": 48.8728, "lon": 2.3335}, guest=_mguest, site={"robots": {"present": False, "status": 200}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
_mtext = " ".join(((r.get("title") or "") + " " + (r.get("finding") or "")).lower() for r in _mout.get("recommendations") or [])
for _w in ("ev charging", "electric vehicle", "parking", "check-in", "wi-fi", "spa"):
    check(f"no finding about '{_w}' (each is answered on the pages, or not offered)", _w not in _mtext, [r.get("title") for r in _mout.get("recommendations") or [] if _w in ((r.get("title") or "") + (r.get("finding") or "")).lower()])
_msite = ic.Site(_MPAGES, _MB, _MH, "Paris")
_mfeat = ic.features(_msite)
_mlev = {f["key"]: f["level"] for f in _mfeat}
check("'there is no spa... day spas nearby' does not give the hotel a spa", _mlev.get("spa") not in ("some", "strong"), _mlev.get("spa"))
_mcls = hotel_class.classify(_msite, _mfeat, ic.intents(_msite), hotel=_MH)
check("nor make it a spa hotel", "spa_hotel" not in _mcls["keys"], _mcls["keys"])
_mtr = traveller_ready.assess(_msite, _mfeat, ic.intents(_msite), classes=_mcls["keys"] + ["luxury"])
_mreq = [r.get("id") for s in _mtr["segments"] for r in s.get("requirements") or []]
check("a luxury hotel without a spa of its own is never asked for its spa's details", "spa_facilities" not in _mreq, _mreq)
_spa_site = ic.Site([_mp("spa/", "Spa", "Our spa offers massage and facial treatments, a sauna and a steam room. The spa is open daily from 9am to 8pm for hotel guests and day visitors. " * 2),
                     _mp("overview/", _MH, "Relax in the hotel's spa after a day in Paris. Book a spa treatment at reception. " * 2)], _MB, _MH, "Paris")
_sfeat = ic.features(_spa_site)
check("a hotel that describes its own spa still has one", {f["key"]: f["level"] for f in _sfeat}.get("spa") in ("some", "strong")
      and "spa_hotel" in hotel_class.classify(_spa_site, _sfeat, ic.intents(_spa_site), hotel=_MH)["keys"])
_br = consultant.brand_route([{"id": "M-sitemap_missing", "source": "machine", "title": "Publish a sitemap", "finding": "No sitemap.", "action": "Add one.", "team": "web", "priority": "medium"},
                               {"id": "Q1", "source": "questions", "title": "Make sure your website answers: accessibility", "finding": "", "action": "State it.", "team": "web", "priority": "medium"},
                               {"id": "R1", "source": "reviews", "title": "Reply to reviews", "finding": "", "action": "Reply.", "team": "reputation management", "priority": "medium"}])
check("on a brand's website a site-wide setting is low priority and the brand's", _br[0]["priority"] == "low" and _br[0]["owner"] == "Brand digital team" and "(brand-run page)" in _br[0]["title"])
check("a change to the hotel's own pages goes to the brand's digital team; work outside the website stays with the hotel",
      _br[1]["owner"] == "Brand digital team" and "brand's digital team" in _br[1]["action"] and not _br[2].get("owner"))
_recs = [{"id": "T1", "title": "Say how far the hotel is from Charles de Gaulle Airport", "finding": "The airport is named but no journey time is given.", "action": "State the travel time to the airport.", "priority": "medium"},
         {"id": "T2", "title": "Add the walking time to Gare Saint-Lazare station", "finding": "The station is named without a distance.", "action": "Give the walking time in minutes.", "priority": "low"},
         {"id": "T3", "title": "Answer this clearly: how to get to the hotel from the airport", "finding": "Getting here: airport transfer details.", "action": "Add directions from the airport.", "priority": "low"},
         {"id": "M1", "title": "Describe the meeting rooms' capacities", "finding": "Meeting rooms are named.", "action": "List each room's capacity.", "priority": "medium"}]
_gr = report_gate.check({"meta": {"hotel": _MH, "city": "Paris"}, "consultant": {"recommendations": copy.deepcopy(_recs), "coverage": {"pages_read": 6}, "pages_read": 6}})
_ids = [r["id"] for r in _gr["consultant"]["recommendations"]]
check("airport and station advice from several checks becomes one recommendation that names every place", _ids.count("T1") == 1 and "T2" not in _ids and "T3" not in _ids and "M1" in _ids
      and "Gare Saint-Lazare" in next(r for r in _gr["consultant"]["recommendations"] if r["id"] == "T1")["action"], _ids)

print("16. the page reader keeps the page's structure (Paris Marriott trace, Nov 2026: a page read as one line quoted a breakfast sentence as transport and the pet fee as parking)")
_MHTML = ("<html><head><title>Overview</title></head><body><main><h2>Amenities</h2>"
          "<div><h3>Fitness Center</h3><ul><li>Treadmill(s)</li><li>Free Weights</li></ul><div>Fee</div><div>Complimentary</div></div>"
          "<div><h3>Parking</h3><dl><dt>On-site parking</dt><dd>Not available</dd><dt>Nearby parking</dt><dd>Indigo Haussmann, daily rate EUR 35</dd></dl></div>"
          "<div><h3>Pets</h3><p>Pets welcome. Non-refundable pet fee per stay: EUR 50.00</p></div>"
          "<div><h3>Getting here</h3><table><tr><th>Charles de Gaulle Airport</th><td>30 km</td></tr><tr><th>Auber RER station</th><td>200 m</td></tr></table></div>"
          "<div><h3>Breakfast at Sixtine</h3><p>Breakfast is served daily from 6:30 to 10:30.</p></div>"
          "<div><h3>Sixtine restaurant</h3><p>Mon-Fri 12:00 PM-2:30 PM, 5:30 PM-10:00 PM</p></div></main></body></html>")
_flat = gq._parse_html(_MB + "overview/", _MHTML, lines=False)
_kept = gq._parse_html(_MB + "overview/", _MHTML, lines=True)
check("each heading, list item, definition and table row is a line of its own", _kept["text"].count("\n") >= 12 and "On-site parking: Not available" in _kept["text"] and "Charles de Gaulle Airport · 30 km" in _kept["text"],
      _kept["text"][:300])
check("the old reader made it one line (what went wrong)", "\n" not in _flat["text"])
_kq = {q["id"]: q for q in gq.evaluate([dict(_kept, url=_MB + "overview/", ok=True)])}
_quotes = {f["label"]: f["snippet"] for q in _kq.values() for f in q.get("fact_snippets") or []}
check("no quote runs from one panel into the next", all(not ("Pet" in s and "parking" in s.lower()) and not ("Treadmill" in s) for s in _quotes.values()), _quotes)
check("the parking answer is the parking panel ('Not available' on site, a nearby car park at EUR 35)", _kq["parking"]["state"] in ("answered", "partial")
      and all("pet" not in (f["snippet"] or "").lower() for f in _kq["parking"].get("fact_snippets") or []), _kq["parking"].get("fact_snippets"))
check("breakfast times are the breakfast line, not the restaurant's lunch hours", any("6:30" in (f["snippet"] or "") for f in _kq["breakfast"].get("fact_snippets") or [])
      and all("12:00 PM" not in (f["snippet"] or "") for f in _kq["breakfast"].get("fact_snippets") or []), _kq["breakfast"].get("fact_snippets"))
_NB = "https://thenici.com/newquay/"
_home = {"url": _NB, "ok": True, "is_start": True, "title": "THE NICI Newquay", "h1": [], "text": "Stay with us\nWith complimentary parking and dogs staying free, all the little details are taken care of.\nBook our spa break today."}
_faq = {"url": _NB + "faqs/", "ok": True, "title": "FAQs", "h1": ["FAQs"], "text": "Do you have parking at the hotel?\nYes, we do have parking available for our guests. Parking is charged at £27 per night.\n"
        "What is your cancellation policy?\nShould you wish to cancel treatment, we kindly request 48 hours' notice to avoid a cancellation charge. Cancellations made within 24 hours of arrival for any spa day, "
        "experience, or treatment will be charged in full.\nWhat time is check-in?\nCheck-in is from 3:00pm. Check-out is 11:00am."}
_nq = {q["id"]: q for q in gq.evaluate([_home, _faq])}
check("the price is quoted from the page where it belongs (the FAQ's '27 per night'), not a homepage package's 'complimentary parking'",
      any("27" in f["snippet"] for f in _nq["parking"].get("fact_snippets") or [] if f["label"] == "the price"), _nq["parking"].get("fact_snippets"))
check("a spa treatment's cancellation terms do not answer the room cancellation question (THE NICI: it was 'answered')", _nq["cancellation"]["state"] != "answered"
      and not _nq["cancellation"].get("fact_snippets"), (_nq["cancellation"]["state"], _nq["cancellation"].get("fact_snippets")))
_only_home = {q["id"]: q for q in gq.evaluate([dict(_home, text=_home["text"] + " Our rooms have sea views.")])}
check("with no FAQ, policies or information page read, an unanswered question is 'could not check', not 'not found' (so nothing is recommended)",
      _only_home["cancellation"]["state"] == "couldnt_check" and "no page this belongs on" in (_only_home["cancellation"].get("not_assessed") or ""), _only_home["cancellation"]["state"])
check("with the FAQ read, an unanswered question is a real gap", _nq["wifi"]["state"] == "not_found", _nq["wifi"]["state"])
check("a label on its own line and its value are one line (Marriott: 'Maximum Pet Weight:' then '6.0kgs')", "Maximum Pet Weight: 6.0kgs" in gq.clean_lines("Pet Policy\nMaximum Pet Weight:\n6.0kgs\nCheck-in: 4:00 pm"))
_eg = {q["id"]: q for q in gq.evaluate([{"url": _MB + "overview/", "ok": True, "title": "Overview", "h1": [], "text": "Breakfast at Sixtine\nFor breakfast, guests will enjoy a full American buffet with a live egg-station."}])}
check("a breakfast buffet's 'live egg-station' is not a railway station (Marriott overview: transport was answered by it)", not _eg["transport"].get("fact_snippets"), _eg["transport"].get("fact_snippets"))
_dn = {q["id"]: q for q in gq.evaluate([{"url": _MB + "dining/", "ok": True, "title": "Dining", "h1": [], "text": "Brasserie Sixtine\nMon-Fri 12:00 PM-2:30 PM 5:30 PM-10:00 PM\nSat 5:30 PM-10:00 PM\nSun Closed\n"
                                          "Breakfast\nEnjoy a generous American-style breakfast buffet.\nBreakfast hours: 6:30 AM-10:30 AM"}])}
check("breakfast times are the breakfast hours, not the brasserie's lunch and dinner hours (Marriott dining page, the live false finding)",
      any("6:30 AM" in f["snippet"] for f in _dn["breakfast"].get("fact_snippets") or []) and not any("12:00 PM" in f["snippet"] for f in _dn["breakfast"].get("fact_snippets") or []), _dn["breakfast"].get("fact_snippets"))
_pk = {q["id"]: q for q in gq.evaluate([{"url": _NB + "events/delegate-packages/", "ok": True, "title": "Delegate packages", "h1": [], "text": "Day Delegate Package\n• Use of stationery\n• High-speed Wi-Fi\n• Prices include VAT\nFrom £65 Per Person"}])}
check("one item of a list is not answered by the lines after it (THE NICI: a delegate package's '£65 per person' became the Wi-Fi price)", not _pk["wifi"].get("fact_snippets"), _pk["wifi"].get("fact_snippets"))
check("a list item keeps its bullet when the page is read", gq._parse_html(_NB, "<main><ul><li>High-speed Wi-Fi</li><li>Prices include VAT</li></ul></main>", lines=True)["text"].startswith("• High-speed Wi-Fi"))
_air = places.mentions("Tel: +33 1-4483 4040\nCharles de Gaulle International Airport\nDistance From Property: 30.0 KM\nThe Arc de Triomphe\nPlace Charles de Gaulle, Paris, 75008", "airport")
check("an airport's distance on the line below its name is its distance (Marriott: 'Distance From Property: 30.0 KM'; three findings said it was not stated)",
      [(m["name"], m["distance"]) for m in _air] == [("Charles de Gaulle", "30.0 KM")], [(m["name"], m["distance"], m["sentence"]) for m in _air])
check("a square named after the same person is not the airport ('Place Charles de Gaulle, Paris')", not any("Place Charles" in m["sentence"] for m in _air))
_gym = {q["id"]: q for q in gq.evaluate([{"url": _MB + "overview/", "ok": True, "title": "Overview", "h1": [], "text": "Take advantage of our hotel gym to train on treadmills, do bodybuilding, or fitness."}])}
check("'our gym, to train on treadmills' is not a train (Marriott: transport was answered by the gym)", not _gym["transport"].get("fact_snippets"))
_ZB = "https://www.hilton.com/en/hotels/zrhhitw-hilton-zurich-airport/"
_zs = ic.Site([{"url": _ZB, "ok": True, "title": "Hilton Zurich Airport", "h1": [], "text": "Opfikon Hotels/\nPerfect location, only 5 drive minutes from Zurich International Airport.\nTake the train from Glattbrugg station, a 10 minute walk."}], _ZB, "Hilton Zurich Airport", "Zurich")
_zi = {i["place"]: i for i in ic.location(_zs, {"stations": [{"name": "Opfikon", "km": 1.2}, {"name": "Glattbrugg", "km": 1.0}], "airports": [{"name": "Hotel", "km": 2}, {"name": "Zurich Airport", "km": 3}],
                                                "attractions": [], "venues": []})["items"]}
check("a map entry with a generic name ('Hotel') is no place to measure from; the real airport is used (Hilton Zurich Airport: 'Distance to Hotel')", "Hotel" not in _zi and _zi.get("Zurich Airport", {}).get("state") == "stated", list(_zi))
check("a town's name in a breadcrumb ('Opfikon Hotels/') is not a mention of its station", _zi.get("Opfikon station", {}).get("state") == "not_mentioned", _zi.get("Opfikon station"))
_cg = {q["id"]: q for q in gq.evaluate([{"url": "https://www.chewtonglen.com/visit/getting-here/", "ok": True, "title": "Getting here", "h1": [],
                                         "text": "By car By train By air\nChewton Glen has 12 EV charge points across the estate, 9 in the main car park and 4 in the car park for the Treehouses."}])}
check("'12 EV charge points' answers the EV question (Chewton Glen: 'make sure your website covers EV charging')", _cg["ev"]["state"] == "answered", _cg["ev"]["state"])
_CGB = "https://www.chewtonglen.com/"
_cgs = ic.Site([{"url": _CGB + "visit/getting-here/", "ok": True, "title": "Getting here", "h1": [], "text": "By car By train By air\nChewton Glen sits on Christchurch Road in New Milton."}], _CGB, "Chewton Glen", "New Milton")
check("a station is not 'not stated' when the page's 'By train' tab was not in the text read (Chewton Glen)",
      not [i for i in ic.location(_cgs, {"stations": [{"name": "New Milton", "km": 2.0}], "airports": [], "attractions": [], "venues": []})["items"] if i["category"] == "transport"])
import locate
check("the postcode on a page read as plain text places the hotel (THE NICI: its site refused our reader, so it had no map position and no comparable hotels)",
      locate.postcode_from_pages(["FAQs\nWhere is THE NICI Newquay?\nEnter East Street, Newquay, Cornwall, TR7 1DB into your sat nav."], "Newquay") == "TR7 1DB")
import claude_reader
_md = claude_reader.to_page(_MB, "# Overview\n\n## Parking\n\n- On-site parking: not available\n- Nearby: EUR 35 a day\n\n## Pets\n\nPet fee EUR 50", lines=True)
check("a page that came as markdown keeps its lines too", "On-site parking: not available\nNearby: EUR 35 a day" in _md["text"], _md["text"])

print("17. where the hotel is, and prompts that fit it (Paris Marriott trace: no map position, so no comparable hotels; prompts frozen in October about a spa and the Eiffel Tower)")
import anchors
import ai_questions


class _NR:
    def __init__(self, rows):
        self.status_code, self._rows = 200, rows

    def json(self):
        return self._rows


_asked = []


def _nom(url, **kw):
    _asked.append(url)
    if url.lower().split("q=")[1].startswith("marriott+opera+ambassador%2c+paris"):        # OpenStreetMap knows it only by its shorter name
        return _NR([{"lat": "48.8727", "lon": "2.3367", "type": "hotel", "display_name": "Marriott Opera Ambassador, Boulevard Haussmann, Paris 9e Arrondissement, Paris, France",
                     "address": {"city": "Paris", "country_code": "fr"}}])
    return _NR([])


check("the hotel is found on the map under the shorter name it is known by", anchors.geocode(_MH, "Paris", _nom, sleep=lambda s: None) == (48.8727, 2.3367), _asked)
check("a shorter name must find a place to stay with that name, not anything similar", anchors.geocode("Opera Ambassador Hotel", "Paris", lambda u, **k: _NR([{"lat": "1", "lon": "1", "type": "attraction",
      "display_name": "Opera Ambassador Theatre, Paris", "address": {"city": "Paris"}}]) if "Hotel" not in u else _NR([]), sleep=lambda s: None) is None)
check("a hotel listed on the map without its brand, or with the local word for hotel, is found (Rome: 'Hotel Ambasciatori Palace'; Eriksberg: 'Eriksberg Vilt och Natur')",
      anchors._same_name("Hotel Ambasciatori Palace", "InterContinental Rome Ambasciatori Palace", "Rome") and anchors._same_name("Eriksberg Vilt och Natur", "Eriksberg Hotel & Nature Reserve", "Karlshamn")
      and "ambasciatori palace, Rome" in anchors._queries("InterContinental Rome Ambasciatori Palace", "Rome") and "eriksberg hotell, Karlshamn" in anchors._queries("Eriksberg Hotel & Nature Reserve", "Karlshamn"))
import external_check as _exc
_orig_osm = _exc._osm_search
_exc._osm_search = lambda *a, **k: ([], None)
try:
    _oe = _exc.check_openstreetmap("Eriksberg Hotel & Nature Reserve", "Karlshamn", lat=56.18, lon=15.0, known={"name": "Eriksberg Vilt och Natur", "url": "https://www.openstreetmap.org/way/1"})
finally:
    _exc._osm_search = _orig_osm
check("the map entry the hotel was found by is its OpenStreetMap entry: no 'our search found no entry' (Eriksberg)", _oe["found"] and _oe["match_confident"] is True and "Eriksberg Vilt och Natur" in _oe["match_reason"])
check("but never another hotel in the same town", not anchors._same_name("Hotel Splendide Royal", "InterContinental Rome Ambasciatori Palace", "Rome"))
_facts = [{"text": t} for t in ("price level: upscale", "kind of hotel: business", "close to Louvre Museum (15 minutes)", "offers restaurant (strong evidence on its own pages)",
                                 "its kind and pages support: meetings and events")]
check("a frozen prompt about a facility the hotel does not have no longer fits", "spa" in (ai_questions.misfit("Are there hotels in Paris with a spa where we could unwind together?", _facts, "upscale", "Paris") or ""))
_eiffel = lambda u, **k: _NR([{"lat": "48.8584", "lon": "2.2945"}])      # noqa: E731
check("nor one asking for hotels near a place measured to be far from it (the Eiffel Tower, 3.5 km)", "3.5 km" in (ai_questions.misfit("An upscale hotel in Paris within walking distance of the Eiffel Tower?", _facts, "upscale", "Paris",
      location={"lat": 48.8727, "lon": 2.3367}, fetch=_eiffel) or ""))
check("a place that cannot be measured is no reason to retire a prompt (the places found nearby differ from check to check)",
      ai_questions.misfit("An upscale hotel in Paris within walking distance of the Eiffel Tower?", _facts, "upscale", "Paris") is None)
check("a prompt that rests on the hotel's facts still fits", ai_questions.misfit("Which upscale hotels near Louvre Museum are best for a business trip, with meeting space?", _facts, "upscale", "Paris") is None)
_bench = [{"text": "Which upscale hotels near Louvre Museum give the best quality for the price?"}, {"text": "Are there hotels in Paris with a spa where we could unwind together?"}]
_built = ai_questions.build({"tier": {"key": "upscale", "label": "Upscale", "why": "brand"}, "classes": ["business", "city_centre"], "strong_features": ["restaurant", "meeting_rooms"]}, _MH, "Paris",
                            [{"name": "Louvre Museum", "kind": "attraction", "distance": "15 minutes", "source": "the hotel's own pages"}], benchmark=_bench)
check("the prompt that no longer fits is retired with its reason; the others are asked again word for word", [r["text"] for r in _built["benchmark_retired"]] == [_bench[1]["text"]]
      and any(q["text"] == _bench[0]["text"] and q["source"] == "benchmark" for q in _built["questions"]) and not any(q["text"] == _bench[1]["text"] for q in _built["questions"]), _built["benchmark_retired"])
check("and the renewed set is saved in its place", _bench[0]["text"] in [b["text"] for b in _built["benchmark_prompts"]] and _bench[1]["text"] not in [b["text"] for b in _built["benchmark_prompts"]]
      and not _built["benchmark_reused"])
import competitors as _cmp
_own4 = {"stars": 4, "stars_inferred": "brand level", "rooms": None, "facilities": ["restaurant", "meeting_rooms"]}
check("a brand hotel with no star rating on its pages is compared with hotels of its brand's level, and the reason says it is inferred (Marriott: 'none comparable')",
      _cmp.comparable(_own4, {"stars": 5, "rooms": None, "facilities": ["restaurant", "meeting_rooms"]})[0] >= 3 and "inferred" in " ".join(_cmp.comparable(_own4, {"stars": 4, "rooms": None, "facilities": ["restaurant"]})[1]))
check("a 2-star guest house is not comparable with it", _cmp.comparable(_own4, {"stars": 2, "rooms": None, "facilities": ["restaurant"]})[0] == 0)
_mine = ai_questions.build({"tier": {"key": "upscale", "label": "Upscale", "why": "brand"}, "classes": []}, _MH, "Paris", [], benchmark=[dict(_bench[1], confirmed=True)])
check("a prompt the hotel confirmed itself is its choice, and is never retired automatically", not _mine["benchmark_retired"] and any(q["text"] == _bench[1]["text"] for q in _mine["questions"]))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
