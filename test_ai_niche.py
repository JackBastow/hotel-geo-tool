"""
Offline tests for ai_niche.py (questions for the markets a hotel actually competes in) and the second round of questions
in ai_sample.py. No network. Run: python test_ai_niche.py
"""
from types import SimpleNamespace as NS

import ai_niche as nz
import ai_sample as ai
import advice
import ai_insights as ins
import scoring

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. facts from the hotel's own pages")
check("an airport and its distance are found in the hotel's own wording", nz.airport_from_text(["City Center at 3.5 km, Findel airport at 9 km, and a shuttle."]) == ("Findel Airport", 9.0))
check("a distance written before the name, in minutes, is found too", nz.airport_from_text(["We are 10 minutes from Heathrow Airport by taxi."]) == ("Heathrow Airport", 8.0))
check("miles are converted, and names with 'da Vinci' style connectors survive",
      nz.airport_from_text(["Located 12 miles from London Gatwick Airport"]) == ("London Gatwick Airport", 19.3)
      and nz.airport_from_text(["Our hotel is 3 km from Leonardo da Vinci Airport"])[0] == "Leonardo da Vinci Airport")
check("an airport too far away to matter is not an 'airport hotel' (100 km)", nz.airport_from_text(["100 km from Manchester Airport"]) is None)
check("of several airports mentioned, the near one is used and the far one ignored",
      nz.airport_from_text(["Gatwick Airport is 40 km away", "Biggin Hill Airport 12 km"]) == ("Biggin Hill Airport", 12.0))
check("the star rating the pages claim most often is used", nz.stars_from_text(["A 4-star hotel", "our four star rooms", "a 5-star neighbour"]) == 4 and nz.stars_from_text(["no rating here"]) is None)
ents = [{"source": "OpenStreetMap", "found": True, "match_confident": True, "address_components": {"suburb": "Trastevere", "city": "Rome"}}]
check("the neighbourhood comes from the map, and is ignored when it is just the town again",
      nz.district(ents, "Rome") == "Trastevere" and nz.district([{**ents[0], "address_components": {"suburb": "Rome"}}], "Rome") is None
      and nz.district([{**ents[0], "match_confident": False}], "Rome") is None)
check("the nearest named airport on the map is used when the pages say nothing", nz.airport_from_map({"airports": [{"name": "Far", "km": 24}, {"name": "Ciampino Airport", "km": 9.2}]}) == ("Ciampino Airport", 9.2))

print("2. what kind of hotel it is, and the questions that follow")
feat = [{"key": "spa", "level": "strong"}, {"key": "restaurant", "level": "strong"}, {"key": "wifi", "level": "strong"}, {"key": "pets", "level": "some"}, {"key": "meeting_rooms", "level": "strong"}]
intents = [{"key": "weddings", "label": "Weddings", "level": "strong"}, {"key": "business", "label": "Business travel", "level": "strong"}, {"key": "family", "label": "Families", "level": "some"}]
prof = nz.profile("Hotel Santa Maria", "Rome", ents, None, [{"text": "A 4-star hotel in Trastevere. Fiumicino Airport is 30 minutes by train, 18 km from Fiumicino Airport."}], feat, intents, domain="santamaria.it")
check("the profile reads the price level (4-star from its own pages), the neighbourhood and the airport, and is not an airport hotel at 18 km",
      prof["tier"]["key"] == "upscale" and prof["tier"]["source"] == "pages" and prof["district"] == "Trastevere" and prof["airport"]["name"] == "Fiumicino Airport" and not prof["airport_hotel"], prof["tier"])
check("audiences come with their evidence, strongest first, in a fixed order (business before spa before weddings)",
      [a["key"] for a in prof["audiences"]][:4] == ["business", "meetings", "wellness", "weddings"] and all(a["why"] for a in prof["audiences"]), [a["key"] for a in prof["audiences"]])
qs = nz.questions(prof, "Hotel Santa Maria", "Rome", n=6)
check("six questions: the price level first, then the neighbourhood, then the audiences", [q["angle"] for q in qs][:3] == ["Price level", "Neighbourhood", "Business travel"] and len(qs) == 6, [q["angle"] for q in qs])
check("every question is a niche-kind item with a reason drawn from a fact we hold", all(q["kind"] == "niche" and q["id"].startswith("niche_") and q["why"] for q in qs))
check("none names the hotel, none is a bare 'best hotels in town', and the 4-star level is in the wording",
      all("Santa Maria" not in q["text"] and q["text"].endswith("?") and len(q["text"]) < 170 and "best hotels in Rome?" not in q["text"] for q in qs) and "4-star" in qs[0]["text"], [q["text"] for q in qs])
check("with no evidence of anything the hotel is not asked about invented markets", nz.questions({"district": None, "airport": None, "stars": None, "tier": None, "audiences": []}, "H", "Rome") == [] and nz.questions({}, "H", "Rome") == [])
check("a district that is just the hotel's own name is not asked (it would name the hotel)",
      nz.questions({"district": "Airport Inn", "airport": None, "stars": None, "tier": None, "audiences": []}, "Airport Inn Rome", "Rome") == [])
check("no town, no questions", nz.questions(prof, "H", "") == [])

print("2b. an airport hotel: the case that returned 'Radisson Blu' and 'The Dolder Grand' for every question")
zi = [{"key": "business", "label": "Business travel", "level": "strong"}, {"key": "meetings", "label": "Meetings", "level": "strong"}, {"key": "pet", "label": "Pets", "level": "strong"},
      {"key": "airport", "label": "Airport", "level": "strong"}, {"key": "family", "label": "Families", "level": "some"}]
zp = nz.profile("Hilton Zurich Airport", "Zurich", [], None, [{"text": "Hilton Zurich Airport is a short walk. Zurich Airport is 2 km from the hotel."}], [{"key": "meeting_rooms", "level": "strong"}], zi, domain="hilton.com")
check("a Hilton with no star rating on its pages is read as upscale by its brand, and said to be an inference", zp["tier"]["key"] == "upscale" and zp["tier"]["source"] == "brand" and "inference" in zp["tier"]["why"])
check("the airport is the real airport, not the hotel's own name ('Hilton Zurich Airport is a short walk' must not become the airport)", zp["airport"]["name"] == "Zurich Airport" and zp["airport_hotel"])
zq = nz.questions(zp, "Hilton Zurich Airport", "Zurich")
check("the questions are about an upscale hotel near the airport: price level, the early flight, business, meetings - not 'best hotels in Zurich'",
      [q["angle"] for q in zq][:4] == ["Price level", "Airport", "Business travel", "Meetings and events"] and all("near Zurich Airport" in q["text"] or "Zurich Airport" in q["text"] for q in zq[:4]), [q["text"] for q in zq])
check("the airport question is a traveller's own situation, with the need that matters to them", "flying out" in zq[1]["text"] and "shuttle" in zq[1]["text"])
check("what the hotel says about itself overrides what we infer: a stated 'luxury' tier and stated audiences come first",
      nz.profile("Hilton Zurich Airport", "Zurich", [], None, [], [], [], hint={"tier": "luxury", "audiences": ["weddings", "couples"]}, domain="hilton.com")["tier"]["key"] == "luxury"
      and [a["key"] for a in nz.profile("X", "Zurich", [], None, [], [], zi, hint={"audiences": ["weddings"]})["audiences"]][0] == "weddings")
check("the reading is described in plain words for the report", nz.describe(zp)["summary"] == "Upscale airport hotel" and nz.describe(None) is None)
check("brand levels: luxury, budget and midscale brands are told apart and the most specific brand wins",
      nz.tier_of("Park Hyatt Zurich", "", None, {})["key"] == "luxury" and nz.tier_of("Hyatt Regency", "", None, {})["key"] == "upscale" and nz.tier_of("ibis Zurich", "", None, {})["key"] == "budget"
      and nz.tier_of("Hilton Garden Inn Zurich", "", None, {})["key"] == "midscale" and nz.tier_of("Brooklands Hotel", "brooklands.com", None, {}) is None)
check("a word that merely contains a brand is not that brand ('Ibiza' is not 'ibis')", nz.tier_of("Hotel Ibiza Playa", "", None, {}) is None)

print("3. the second round, merged into the sample")


def resp(text):
    return NS(content=[NS(type="web_search_tool_result", content=[NS(url="https://www.booking.com/x", title="t")]), NS(type="text", text=text, citations=None)],
              stop_reason="end_turn", usage=NS(input_tokens=12000, output_tokens=500, server_tool_use=NS(web_search_requests=2)))


class Fake:
    def __init__(self, answers):
        self.answers, self.calls, self.messages = list(answers), [], self

    def create(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0)


HOTEL = "Hotel Santa Maria"
base = {"status": "ok", "model": "claude-haiku-5-5", "run_at": "2026-10-14", "cost_usd": 0.1, "items": [
    {"id": "best", "kind": "generic", "text": "Best hotels in Rome?", "answer": "1. Hassler", "mentioned": False, "position": None, "domains": ["booking.com"]},
    {"id": "where", "kind": "generic", "text": "Where to stay in Rome?", "answer": "1. Hassler", "mentioned": False, "position": None, "domains": ["booking.com"]},
    {"id": "about", "kind": "direct", "text": "Tell me about Hotel Santa Maria", "answer": "Hotel Santa Maria is in Trastevere.", "mentioned": True, "position": None, "domains": []}]}
base["summary"] = ai.summarise(base["items"])
check("the standard summary has no niche counts until a second round is added", base["summary"]["niche_asked"] == 0)
fake = Fake([resp("1. Hotel Santa Maria: near the river.\n2. Hotel Trastevere."), resp("1. Hotel Aurora: simple.\n2. Hotel Bianco.")])
NQ = [{"id": "niche_airport", "kind": "niche", "angle": "Airport", "text": "Which hotels near Fiumicino Airport would you recommend, for example before an early flight?",
       "why": "The hotel's own pages put Fiumicino Airport 8 km away."},
      {"id": "niche_spa", "kind": "niche", "angle": "Spa", "text": "Which hotels in Rome have a good spa and wellness area?", "why": "The hotel's own pages signal spa strongly."}]
extra = ai.run_extra(HOTEL, "Rome", NQ, client=fake, repeats=1)
check("each niche question is asked once with the web-search tool, and the answers keep the market and the reason",
      len(fake.calls) == 2 and len(extra["items"]) == 2 and extra["items"][0]["angle"] == "Airport" and extra["items"][0]["why"] and extra["cost_usd"] > 0)
check("the hotel being named in the first niche answer, but not the second, is recorded per question", [i["mentioned"] for i in extra["items"]] == [True, False])
merged = ai.merge(base, extra)
s = merged["summary"]
check("merging recomputes the counts: 0 of 2 town-wide, 1 of 2 niche, asked 5, cost summed",
      s["generic_asked"] == 2 and s["generic_named"] == 0 and s["niche_asked"] == 2 and s["niche_named"] == 1 and s["asked"] == 5 and merged["cost_usd"] > base["cost_usd"], s)
check("merging nothing changes nothing, and a failed sample is never 'merged'", ai.merge(base, {"items": []}) is base and ai.merge({"status": "unavailable"}, extra)["status"] == "unavailable")
check("no key and no client: not asked, with the reason; no questions: nothing", ai.run_extra(HOTEL, "Rome", NQ)["items"] == [] and ai.run_extra(HOTEL, "Rome", [], api_key="k")["reason"] == "")

print("4. scoring and the plan treat the niche markets as the point")
sc = scoring.score_ai_sample(merged)
check("AI Visibility now weighs the niche markets as much as the town-wide question: 0.35x0 + 0.35x0.5 + 0.30x1 = 47.5 -> 48", sc["score"] == 48, sc["score"])
check("the evidence lines say both counts", any("positioned for" in e for e in sc["evidence"]) and any("generic" in e for e in sc["evidence"]))
no_niche = scoring.score_ai_sample(base)
check("with no niche round the original formula stands (0.7x0 + 0.3x1 = 30)", no_niche["score"] == 30)
none_named = ai.merge(base, {"items": [{**extra["items"][0], "mentioned": False}, {**extra["items"][1], "mentioned": False}], "cost_usd": 0.05})
rc = advice._from_ai(none_named)
byid = {r["id"]: r for r in rc}
check("not named in 2+ niche questions yields a recommendation about the hotel's own markets, naming the angles", "AI4" in byid and "Airport" in byid["AI4"]["finding"] and byid["AI4"]["priority"] == "medium")
check("it explains why niche matters more than a town-wide list, and stays honest about one model on one day", "own market" in byid["AI4"]["why"] and "one model on one day" in byid["AI4"]["why"])
check("named in a niche question: no such recommendation; the town-wide one (AI1) is still raised separately", "AI4" not in {r["id"] for r in advice._from_ai(merged)} and "AI1" in {r["id"] for r in advice._from_ai(merged)})

print("5. the analysis gives niche markets their own table and tells the explanation about them")
EXTRACTED = {"answers": [{"id": "niche_airport", "hotels": [{"name": "Hotel Santa Maria", "rank": 1, "reason": "near the river", "rating": None}, {"name": "Hotel Trastevere", "rank": 2, "reason": "x", "rating": None}]},
                         {"id": "niche_spa", "hotels": [{"name": "Hotel Aurora", "rank": 1, "reason": "simple", "rating": None}, {"name": "Hotel Bianco", "rank": 2, "reason": "y", "rating": None}]},
                         {"id": "best", "hotels": [{"name": "Hassler", "rank": 1, "reason": "luxury", "rating": None}]},
                         {"id": "where", "hotels": [{"name": "Hassler", "rank": 1, "reason": "luxury", "rating": None}]}],
             "about": {"tone": "positive", "strengths": [], "weaknesses": [], "claims": []}}
EXTRACTED["answers"] = {a["id"]: a["hotels"] for a in EXTRACTED["answers"]}      # the shape extract() returns after validation
lb_g = ins.leaderboard(EXTRACTED, merged["items"], HOTEL)
lb_n = ins.leaderboard(EXTRACTED, merged["items"], HOTEL, kinds=("niche",))
check("the town-wide table counts only the town-wide questions, the niche table only the niche ones", lb_g["questions"] == 2 and lb_n["questions"] == 2
      and all(r["name"] != "Hotel Aurora" for r in lb_g["rows"]) and any(r["name"] == "Hotel Aurora" for r in lb_n["rows"]))
me_n = next(r for r in lb_n["rows"] if r["is_target"])
check("the hotel IS named in one niche market (airport) and not the other", me_n["mentions"] == 1 and me_n["best_rank"] == 1)
niche = [{"question": "Which hotels near Fiumicino Airport?", "why": "the pages say it is 8 km away", "hotel_named": True, "hotels_named": ["Hotel Santa Maria"]},
         {"question": "Best hotels in Trastevere, Rome?", "why": "the map places it in Trastevere", "hotel_named": False, "hotels_named": ["Hotel Aurora", "Hotel Bianco"]}]
led = ins.build_ledger(lb_g, [], {"site_emphasises": [], "not_in_assistant_description": []}, EXTRACTED["about"], None, merged, [], [], [], niche=niche)
check("the evidence ledger tells the explanation which niche markets the hotel was and was not named in, and why they were asked",
      any("the map places it in Trastevere" in e["text"] and "not named" in e["text"] and "Hotel Aurora" in e["text"] for e in led)
      and any("the pages say it is 8 km away" in e["text"] and "was named" in e["text"] for e in led))

print("6. a typed name is tidied to the site's own spelling")
import full_audit as fa
site0 = {"lodging_node": {"name": "Hilton Zurich Airport"}, "pages": [], "meta": {}}
check("'hiltonzurichairport' typed as one word becomes the site's 'Hilton Zurich Airport', so the questions use the name people use",
      fa.tidy_typed_name("hiltonzurichairport", site0, "https://www.hilton.com/", None) == ("Hilton Zurich Airport", True))
check("a name that already has spaces, or that the site does not confirm, is left exactly as typed",
      fa.tidy_typed_name("Brooklands Hotel", site0, "https://x.com/", None) == ("Brooklands Hotel", False) and fa.tidy_typed_name("brooklandshotel", site0, "https://x.com/", None) == ("brooklandshotel", False)
      and fa.tidy_typed_name("zurichairportx", {"pages": []}, "https://x.com/", None) == ("zurichairportx", False))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
