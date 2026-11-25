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
check("where the profile says nothing, the word rules can only make it a mention, never a strength (the garden)", rows["garden"]["basis"].startswith("word rules") and rows["garden"]["level"] in ("weak", "none"), rows["garden"])
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

print("7. the Brooks report review: misinformation, strengths, examples, awards, kinds of site")
import ai_facts
import sourcetypes
import source_actions
_cmp = ai_facts.compare([{"topic": "parking", "stance": "has", "value": "", "quote": "Brooks Guesthouse offers free on-site parking"}],
                        {"parking": {"level": "none", "status": "not_offered", "quote": "No sorry we do not have car parking", "quote_url": B + "faq/"}})
check("the assistant saying 'free parking' when the site says none is reported as misinformation, quoting both", _cmp["rows"] and _cmp["rows"][0]["status"] == "differs"
      and "No sorry we do not have car parking" in _cmp["rows"][0]["our_record"] and _cmp["rows"][0]["says"].startswith("Brooks"), _cmp)
_ok = ai_facts.compare([{"topic": "pets", "stance": "lacks", "value": "", "quote": "does not allow dogs"}], {"pets": {"level": "none", "status": "not_offered", "quote": "Pets Not Allowed", "quote_url": "u"}})
check("the assistant agreeing with the site is not misinformation", not _ok["rows"] and _ok["matches"] == 1)
fact_profile.use(B, prof)
_int = {i["key"]: i["level"] for i in ic.intents(ic.Site(PAGES + [{"url": B + "spa-break/", "ok": True, "title": "Spa breaks in Bath", "h1": [], "text":
        "Spa breaks in Bath: our guests love the spa, treatments and wellness of the city. Spa spa spa. Dining in our breakfast room. Fine dining restaurants nearby."}], B, "Brooks Guesthouse", "Bath"))}
check("'Spa and wellness' and 'Food and dining' are not strengths of a guesthouse whose spa is a partner's and which has no restaurant (Brooks)", _int["spa"] == "none" and _int["food"] == "none", _int)
ex = "Included in every rate: [Wi-Fi, water, access to the gym]. Charged on top for everyone: [city tax of €[x] per person per night]. Breakfast, parking, cancellation and late check-out depend on the rate you choose."
g = fact_profile.ground_example(ex, {"wifi": "on_site", "parking": "not_offered"}, "GB")
check("example wording names no facility the hotel lacks (gym, parking) and no city tax in the UK", "gym" not in g and "parking" not in g and "city tax" not in g and "Wi-Fi" in g and "Breakfast" in g, g)
check("prices in examples are in the hotel's currency", "£" in fact_profile.ground_example("Day passes from €[x].", {}, "GB"))
for d, want in [("destinationwellknown.com", "blog"), ("diytravelagent.blog", "blog"), ("visitbath.co.uk", "tourism"), ("timeout.com", "editorial"), ("oyster.com", "review"),
                ("tripadvisor.co.uk", "review"), ("booking.com", "ota"), ("lonelyplanet.com", "editorial"), ("goatsontheroad.com", "blog"), ("random-hotels-site.com", "")]:
    check(f"{d} is {want or 'not identified'}", sourcetypes.web_kind(d) == want, sourcetypes.web_kind(d))
check("an unidentified site is never presented as an editorial publisher or a tourism body", source_actions.LABEL[source_actions.classify("random-hotels-site.com")].endswith("(not identified)"))
print("8. the audit that proves every section agrees with the profile")
import profile_audit
_fp = {"status": "ok", "facilities": {"parking": {"status": "not_offered"}, "spa": {"status": "partner"}, "wifi": {"status": "on_site"}}}
_bad = {"fact_profile": _fp, "consultant": {"features": [{"key": "parking", "level": "strong"}, {"key": "wifi", "level": "strong"}],
        "intents": [{"key": "spa", "label": "Spa and wellness", "level": "strong"}], "understanding": {"strong_signals": ["Spa and wellness"]},
        "recommendations": [{"id": "X1", "title": "Promote your parking", "action": "Highlight the parking on the homepage."}]},
        "question_plan": {"questions": [{"text": "Which hotels in Bath have parking for guests?"}]}}
_au = profile_audit.audit(_bad)
check("the audit finds a facility, a kind of guest, a strong signal, a prompt and a recommendation that disagree with the profile",
      {x["section"] for x in _au["violations"]} >= {"facilities", "kinds of guest", "strong signals", "AI test question", "recommendation"}, _au["violations"])
check("Wi-Fi, which the hotel has, is never a violation", not any(x["facility"] == "wifi" for x in _au["violations"]))
_good = {"fact_profile": _fp, "consultant": {"features": [{"key": "parking", "level": "none"}, {"key": "wifi", "level": "strong"}], "intents": [], "understanding": {}, "recommendations": []},
         "question_plan": {"questions": [{"text": "Which hotels in Bath have fast Wi-Fi?"}]}}
check("a report that agrees with its profile has no violations", profile_audit.audit(_good)["violations"] == [])
check("without a profile the audit says so instead of passing", profile_audit.audit({})["status"] == "no_profile")

print("9. who the hotel is for (positioning), from the same reading")
N = "https://thenici.com/newquay/"
NP = [{"url": N, "ok": True, "title": "THE NICI", "h1": ["THE NICI"], "text":
       "A boutique hotel on the Cornish coast for couples and families, with sea views over Great Western Beach. Newquay Airport is a 15 minute drive away. "
       "Our spa and pool are open to all guests. Airport transfers can be arranged. Families are welcome: cots and extra beds on request. Airport airport airport. " * 2},
      {"url": N + "getting-here/", "ok": True, "title": "Getting here", "h1": [], "text": "By air: Newquay Airport is 15 minutes away by taxi. By train: Newquay station is a 10 minute walk. " * 3}]
NREPLY = {"facilities": [{"key": "spa", "status": "on_site", "quote": "Our spa and pool are open to all guests.", "url": N}],
          "positioning": [{"key": "couples", "status": "core", "quote": "A boutique hotel on the Cornish coast for couples and families, with sea views over Great Western Beach.", "url": N},
                          {"key": "family", "status": "core", "quote": "Families are welcome: cots and extra beds on request.", "url": N},
                          {"key": "beach", "status": "core", "quote": "with sea views over Great Western Beach", "url": N},
                          {"key": "luxury", "status": "core", "quote": "The most luxurious hotel in Cornwall.", "url": N},
                          {"key": "airport", "status": "secondary", "quote": "Our spa and pool are open to all guests.", "url": N}]}
np_ = fact_profile.build(NP, client=_Client(NREPLY))
pos = np_["positioning"]
check("who the hotel is for is read in the same call, each answer quoted", set(pos) == {"couples", "family", "beach"}, pos)
check("an invented quotation is dropped (a luxury claim the pages never make)", "luxury" not in pos)
check("a quotation about something else is dropped (the spa sentence given as 'airport')", "airport" not in pos and np_["positioning_stats"]["rejected"] == 2, np_["positioning_stats"])
fact_profile.use(N, np_)
_ns = ic.Site(NP, N, "THE NICI", "Newquay")
_ni = {i["key"]: i["level"] for i in ic.intents(_ns)}
check("THE NICI is not 'Airport stays' because its pages say how far the airport is (the word appears often, the profile does not confirm it)", _ni["airport"] in ("weak", "none"), _ni["airport"])
check("couples, families and the beach are strong, from the profile's quotations", _ni["couples"] == "strong" and _ni["family"] == "strong" and _ni["beach"] == "strong", _ni)
_nc = hotel_class.classify(_ns, ic.features(_ns), ic.intents(_ns), osm_ctx={"airports": [{"name": "Newquay Airport", "km": 7.4}]}, hotel="THE NICI")["keys"]
check("an airport 7 km away on the map does not make THE NICI an airport hotel", "airport" not in _nc, _nc)
check("a hotel named for the airport still is one", "airport" in hotel_class.classify(ic.Site(NP, "https://hiltonairport.example/", "Hilton Zurich Airport", "Zurich"), [], [],
      osm_ctx={"airports": [{"name": "Zurich Airport", "km": 1.2}]}, hotel="Hilton Zurich Airport")["keys"])
AO = "https://adults.example/"
fact_profile.use(AO, {"status": "ok", "facilities": {}, "positioning": {"family": {"status": "not_for", "quote": "We are an adults-only hotel for guests over 16.", "url": AO}}})
_ai = {i["key"]: i for i in ic.intents(ic.Site([{"url": AO, "ok": True, "title": "x", "h1": [], "text": "Family rooms, family suites, family friendly. Kids club. " * 4}], AO, "X", "Y"))}
check("'adults only' means not for families, whatever the pages' words, with the quotation as the reason", _ai["family"]["level"] == "none" and "adults-only" in _ai["family"]["reason"], _ai["family"])
import profile_audit as _pa
_rp = {"fact_profile": {"status": "ok", "facilities": {}, "positioning": {"couples": {"status": "core"}}},
       "consultant": {"features": [], "intents": [{"key": "airport", "label": "Airport stays", "level": "strong"}, {"key": "couples", "label": "Couples", "level": "strong"}],
                      "hotel_class": {"keys": ["airport"]}, "understanding": {}, "recommendations": []}, "meta": {"hotel": "THE NICI"}}
_v = _pa.audit(_rp)["violations"]
check("the audit flags a kind of guest or hotel type the profile does not confirm ('Airport stays'), and not one it does (couples)",
      any(x["facility"] == "airport" and x["section"] == "kinds of guest" for x in _v) and any(x["section"] == "kind of hotel" for x in _v) and not any(x["facility"] == "couples" for x in _v), _v)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
