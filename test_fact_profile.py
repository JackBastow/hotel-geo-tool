"""
The verified fact profile (fact_profile.py): one answer per facility, read by every part of the report. Offline: Claude is a stand-in returning fixed JSON.
Cases from real reports (Nov 2026): Brooks Guesthouse, Bath ('we do not have car parking, but a public car park is behind us' was parking to the prompts and the comparison);
a spa at a sister hotel; a quotation that is not on the page.
Run: python test_fact_profile.py
"""
import json
import re
import sys
import warnings

warnings.filterwarnings("ignore")
import fact_profile
import facility_depth
import hotel_class
import insight_content as ic
import report_gate

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


B = "https://www.brooksguesthouse.com/"
PAGES = [
    {"url": B, "ok": True, "title": "Brooks Guesthouse", "h1": ["Brooks Guesthouse"], "text":
     "Brooks Guesthouse is a boutique guesthouse in Bath, a short walk from Royal Victoria Park.\nBreakfast is served in our breakfast room every morning.\n"
     "Free Wi-Fi throughout the house. Parking in Bath can be tricky, so we recommend the park and ride."},
    {"url": B + "faq/", "ok": True, "title": "FAQ", "h1": ["FAQ"], "text":
     "Does Brooks Guesthouse have parking? No sorry we do not have car parking, but a large secure public car park Charlotte Street car park is to the rear of the Guesthouse.\n"
     "Do you have a spa? Guests receive 10% off treatments at our sister hotel's spa, The Spa at Number Five.\n"
     "Are you dog friendly? Yes, dogs are welcome in two of our ground floor rooms for a small charge.\n"
     "We have a lovely garden for guests to relax in. Our car park parking parking parking is mentioned often on this page."},
    {"url": B + "around/", "ok": True, "title": "Around Bath", "h1": ["Around"], "text": "Parking at the Charlotte Street car park costs £12 a day. The Thermae Bath Spa is ten minutes away.\n"
     "Bath is a compact city and most of its sights are within an easy walk of the guesthouse: the Roman Baths, the Abbey, the Royal Crescent and the Circus. "
     "Royal Victoria Park, with its botanical gardens and playground, is just across the road."},
]


class _Resp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 1000, "output_tokens": 200, "server_tool_use": None})()


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.messages = self

    def create(self, **kw):
        self.prompt = kw["messages"][0]["content"]
        return _Resp(json.dumps(self.reply))


REPLY = {"facilities": [
    {"key": "parking", "status": "not_offered", "quote": "No sorry we do not have car parking, but a large secure public car park Charlotte Street car park is to the rear of the Guesthouse.", "url": B + "faq/"},
    {"key": "parking", "status": "nearby", "quote": "Parking at the Charlotte Street car park costs £12 a day.", "url": B + "around/"},
    {"key": "gym", "status": "on_site", "quote": "Free Wi-Fi throughout the house. Parking in Bath can be tricky, so we recommend the park and ride.", "url": B},      # not about a gym: dropped
    {"key": "spa", "status": "partner", "quote": "Guests receive 10% off treatments at our sister hotel's spa, The Spa at Number Five.", "url": B + "faq/"},
    {"key": "pets", "status": "on_site", "quote": "Yes, dogs are welcome in two of our ground floor rooms for a small charge.", "url": B + "faq/"},
    {"key": "wifi", "status": "on_site", "quote": "Free Wi-Fi throughout the house.", "url": B},
    {"key": "restaurant", "status": "on_site", "quote": "Our award-winning restaurant serves dinner nightly.", "url": B},            # not on the page: an invention
    {"key": "garden", "status": "on_site", "quote": "Free Wi-Fi throughout the house.", "url": B},                                    # on the page, but not about a garden
    {"key": "pool", "status": "on_site", "quote": "We have a lovely garden for guests to relax in.", "url": B + "around/"},           # quoted from the wrong page
]}

print("1. verifying Claude's answers against the pages")
prof = fact_profile.build(PAGES, client=_Client(REPLY))
f = prof["facilities"]
check("the profile is built", prof["status"] == "ok", prof)
check("'we do not have car parking, but a public car park is behind us' is parking NOT offered (Brooks Guesthouse)", f.get("parking", {}).get("status") == "not_offered", f.get("parking"))
check("a spa at the sister hotel is a partner's, not the hotel's", f.get("spa", {}).get("status") == "partner")
check("dogs welcome in two rooms is on site", f.get("pets", {}).get("status") == "on_site")
check("an invented quotation is dropped (a restaurant the pages never mention)", "restaurant" not in f)
check("a real quotation about something else is dropped (Wi-Fi given as the garden)", "garden" not in f)
check("a quotation from a different page is dropped", "pool" not in f)
check("a facility keeps every relationship the pages state: parking not offered at the hotel AND a public car park nearby",
      sorted(r["status"] for r in f["parking"]["relations"]) == ["nearby", "not_offered"], f["parking"])
check("what was read is recorded (pages sent, cut short, left out)", prof["pages_sent"] == 3 and "pages_truncated" in prof and "pages_failed" in prof)
check("'not stated' says what it rests on", fact_profile.not_stated_basis(dict(prof, pages_failed=2)) == "not stated on the 3 pages read (2 could not be read)", fact_profile.not_stated_basis(dict(prof, pages_failed=2)))
_c = fact_profile.headline([{"status": "on_site", "quote": "a", "url": "u", "note": ""}, {"status": "not_offered", "quote": "b", "url": "u", "note": ""}])
check("'has it' and a specific 'not offered' is the hotel having it with exceptions (THE NICI: cots, but no interconnecting rooms)", _c["status"] == "on_site" and _c.get("exceptions") and not _c["conflict"], _c)
check("the drops are counted, with reasons", prof["rejected"] == 4 and "quotation not found in the page" in prof["reasons"], prof["reasons"])
_cl = _Client(REPLY)
fact_profile.build(PAGES, client=_cl)
check("the prompt asks about every facility the report uses, and carries the pages", all(f'"{k}"' in _cl.prompt for k in fact_profile.MEANING) and B + "faq/" in _cl.prompt)

print("2. every part of the report reads the same answer")
site = ic.Site(PAGES, B, "Brooks Guesthouse", "Bath")
before = {r["key"]: r["level"] for r in ic.features(site)}
check("without a profile the word rules call parking a facility (the old fault)", before["parking"] in ("some", "strong"), before["parking"])
fact_profile.use(B, prof)
rows = {r["key"]: r for r in ic.features(ic.Site(PAGES, B, "Brooks Guesthouse", "Bath"))}
check("with the profile, parking is not a facility of the hotel, however often the word appears", rows["parking"]["level"] == "none" and rows["parking"]["status"] == "not_offered", rows["parking"])
check("a partner's spa is not the hotel's", rows["spa"]["level"] == "none")
check("dogs welcome is at least 'some', with the quotation as its evidence", rows["pets"]["level"] in ("some", "strong") and rows["pets"]["basis"].startswith("AI reading"))
check("where the profile says nothing, the word rules still decide (the garden)", rows["garden"]["basis"] == "word rules")
check("a Site built on a page inside the hotel's site reads the same profile", ic.features(ic.Site(PAGES, B + "faq/", "Brooks Guesthouse", "Bath"))[8]["level"] == "none")
check("a rival's website is never affected", fact_profile.for_site(ic.Site(PAGES, "https://www.thequeensberry.co.uk/", "The Queensberry", "Bath")) is None)
cls = set(hotel_class.classify(ic.Site(PAGES, B, "Brooks Guesthouse", "Bath"), list(rows.values()), [], hotel="Brooks Guesthouse")["keys"])
check("a partner's spa never makes it a spa hotel", "spa_hotel" not in cls)
check("facility detail is not asked of a spa the hotel does not run", not any(r["key"] == "spa" for r in facility_depth.analyse(ic.Site(PAGES, B, "Brooks Guesthouse", "Bath"))))

print("3. the final check removes what promotes a facility the hotel does not have")
rep = {"meta": {"hotel": "Brooks Guesthouse", "base": B}, "consultant": {"coverage": {"pages_read": 3}, "pages_read": 3,
       "features": [{"key": k, "label": r["label"], "level": r["level"], "pages": r["pages"], "status": r.get("status")} for k, r in rows.items()],
       "recommendations": [{"id": "X1", "title": "Promote your parking to business travellers", "finding": "Parking is a strength for drivers.", "action": "Highlight the parking on the homepage.",
                            "priority": "high", "evidence": []},
                           {"id": "X2", "title": "Describe your dog-friendly rooms", "finding": "Dogs are welcome in two rooms.", "action": "Add the charge and the rules.", "priority": "medium", "evidence": []}],
       "top_actions": ["X1", "X2"]}}
led, ok = report_gate._ledger(rep["consultant"], rep["consultant"]["coverage"])
r1 = report_gate._check_text_vs_ledger(rep["consultant"]["recommendations"][0], led, False)
r2 = report_gate._check_text_vs_ledger(rep["consultant"]["recommendations"][1], led, False)
check("'promote your parking' is dropped when the profile says no parking, even when an absence could not otherwise be believed", r1 and r1[0] == "drop" and r1[1] == "parking", r1)
check("advice about a facility the hotel has stays", r2 is None, r2)

print("4. without a key the word rules stand alone, and say so")
np_ = fact_profile.build(PAGES)
check("no key: not configured, nothing invented", np_["status"] == "not_configured" and np_["facilities"] == {})
fact_profile.use(B, np_)
check("an empty profile leaves the word rules in charge (and a previous audit's answers are not reused)", {r["key"]: r["level"] for r in ic.features(ic.Site(PAGES, B, "Brooks Guesthouse", "Bath"))} == before)

print("5. technical problems go to the operator, not into the hotel's report")
import run_health
_r = {"meta": {"hotel": "Brooks Guesthouse", "location": {"lat": None}}, "fact_profile": prof,
      "guest_questions": {"pages_ok": 3, "pages_attempted": 8, "read_via": "firecrawl", "own_reader_refused": ["403"], "page_reader_note": "The site refused this tool's own reader."},
      "consultant": {"coverage": {"note": "3 pages could be read, which is only part of a hotel's website. The site refused this tool's own reader, so its pages were read through Firecrawl, which returned each page's HTML. Anything reported as missing may be on a page that was not read."},
                     "recommendations": [{"id": "Q1", "finding": "Cancellation could not be checked: the terms page could not be read.", "evidence": [{"snippet": "Our API partners credit card"}]}]},
      "ai_sample": {"status": "unavailable", "reason": "The Anthropic API returned an error (RateLimitError), so the sampled AI answers were not run."}, "step_errors": [{"step": "x", "error": "KeyError"}]}
_s = run_health.scrub(_r)
note = _s["consultant"]["coverage"]["note"]
check("the hotel's report keeps the plain caveat ('only part of the website')", "only part of a hotel's website" in note and "may be on a page that was not read" in note, note)
check("and loses the technical one (reader refused, Firecrawl)", "Firecrawl" not in note and "refused" not in note, note)
check("plain findings stay ('could not be checked: the terms page could not be read')", _s["consultant"]["recommendations"][0]["finding"].startswith("Cancellation could not be checked"))
check("quoted page text is never changed", _s["consultant"]["recommendations"][0]["evidence"][0]["snippet"] == "Our API partners credit card")
check("service errors and failed steps are gone from what the hotel opens", "Anthropic" not in str(_s) and "step_errors" not in _s and "read_via" not in _s["guest_questions"])
check("the stored report is not changed", "Firecrawl" in _r["consultant"]["coverage"]["note"])
_iss = run_health.issues(_r)
_big = [x["what"] for x in _iss if x["level"] == "big"]
check("the operator sees the big problems first: few pages read, no map position, the AI test not run",
      any("pages could be read" in w for w in _big) and any("map" in w for w in _big) and any("AI assistant test" in w for w in _big) and _iss[0]["level"] == "big", _iss)
check("the admin panel says nothing went wrong when nothing did", "Nothing went wrong" in run_health.panel_html({"meta": {"location": {"lat": 1}}, "ai_sample": {"status": "ok"}}))

print("6. from the first live runs (Brooks, The Hoxton)")
_hx = [{"url": "https://thehoxton.com/london/shoreditch/", "text": "Bring your pooch! Our four-legged friends are welcome in all rooms, with a bed and a bowl waiting. " * 3}]
_k, _ = fact_profile.verify([{"key": "pets", "status": "on_site", "quote": "Our four-legged friends are welcome in all rooms, with a bed and a bowl waiting.", "url": _hx[0]["url"]}], _hx)
check("a quotation in the hotel's own words is about the facility ('four-legged friends are welcome': The Hoxton's dogs were refused)", _k.get("pets", {}).get("status") == "on_site", _k)
_qs = [{"id": "pets", "short": "Pets", "state": "answered", "found": [], "not_offered": [{"label": "Pets", "snippet": "Dogs are not allowed in restaurant outlets.", "url": "u"}]},
       {"id": "parking", "short": "Parking", "state": "not_found", "found": []}]
_ch = fact_profile.reconcile_questions(_qs, {"facilities": {"pets": {"status": "on_site", "quote": "Our four-legged friends are welcome in all rooms.", "url": "u"},
                                                             "parking": {"status": "not_offered", "quote": "We do not have car parking.", "url": "u2"}}})
check("a restriction ('not allowed in restaurant outlets') is not 'no pets' when the profile says dogs are welcome", not _qs[0]["not_offered"] and _qs[0]["state"] == "partial" and "pets" in _ch)
check("a question the rules could not answer takes the profile's 'not offered', with its quotation", _qs[1]["state"] == "answered" and _qs[1]["not_offered"][0]["snippet"] == "We do not have car parking.")
_q3 = [{"id": "pets", "short": "Pets", "state": "answered", "found": ["whether pets are allowed"], "snippet": "Dog-Friendly Stays"}]
fact_profile.reconcile_questions(_q3, {"facilities": {"pets": {"status": "not_offered", "quote": "No sorry we only accept Guide dogs.", "url": "u"}}})
check("pages that say both ('Dog-Friendly Stays' and 'we only accept Guide dogs': Brooks) are 'needs checking' with both quotations, never one taken silently",
      _q3[0]["state"] == "needs_checking" and _q3[0]["contradiction"]["says_not"].startswith("No sorry"))
check("and the operator sees it", any("contradict themselves about pets" in x["what"] for x in run_health.issues({"meta": {"location": {"lat": 1}}, "ai_sample": {"status": "ok"},
                                                                                                                       "fact_profile": {"status": "ok"}, "guest_questions": {"questions": _q3}})))
import ai_questions
_b =ai_questions.build({"tier": {"key": "midscale", "label": "Mid-range", "why": "x"}, "classes": ["city_centre", "business"], "strong_features": ["wifi"], "features": ["wifi"]},
                        "Brooks Guesthouse", "Bath", [{"name": "Victoria Park", "kind": "attraction", "distance": "350 meters", "km": 0.35, "source": "the hotel's own pages"}])
check("no written question asks about meeting space or parking the hotel's facts do not give it (Brooks Guesthouse)",
      not any(re.search(r"meeting|parking", q["text"], re.I) for q in _b["questions"]), [q["text"] for q in _b["questions"] if re.search(r"meeting|parking", q["text"], re.I)])

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
