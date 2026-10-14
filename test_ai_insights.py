"""
Offline tests for ai_insights.py: what the sampled AI answers mean. A fake client stands in for the Anthropic SDK.
Run: python test_ai_insights.py
"""
import json
from types import SimpleNamespace as NS

import ai_insights as ins
import advice
import compare
import ranking

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "DoubleTree by Hilton Luxembourg", "Luxembourg"

ITEMS = [
    {"id": "best", "kind": "generic", "text": "What are the best hotels in Luxembourg?", "mentioned": False, "position": None, "domains": ["tripadvisor.com", "booking.com", "trip.com"],
     "answer": "1. **Le Royal Hotels & Resorts**: 5-star with spa.\n2. **Sofitel Luxembourg Le Grand Ducal**: views and breakfast.\n3. **Park Inn by Radisson**: budget, near the station."},
    {"id": "where", "kind": "generic", "text": "Where should I stay in Luxembourg?", "mentioned": False, "position": None, "domains": ["tripadvisor.com", "visitluxembourg.com"],
     "answer": "1. **Le Royal Hotels & Resorts**: luxury.\n2. **Park Inn by Radisson Luxembourg City**: best value.\n3. **Hotel Grey**: across from the station."},
    {"id": "about", "kind": "direct", "text": "Tell me about DoubleTree by Hilton Luxembourg", "mentioned": True, "position": None, "domains": ["tripadvisor.co.uk", "hilton.com"],
     "answer": "DoubleTree by Hilton Luxembourg is a 4-star hotel in a forest, far from the centre. Free parking. Check-in is 3 pm. Phone +352 43 781. Rooms are spacious but dated."},
    {"id": "similar", "kind": "direct", "text": "Which hotels are similar to DoubleTree by Hilton Luxembourg?", "mentioned": False, "position": None, "domains": ["booking.com"],
     "answer": "1. **Novotel Luxembourg Kirchberg**: business.\n2. **Meliá Luxembourg**: value."},
]
AI = {"status": "ok", "model": "claude-haiku-5-5", "run_at": "2026-10-14", "items": ITEMS,
      "summary": {"asked": 4, "generic_asked": 2, "generic_named": 0, "direct_known": True, "own_site_cited": True, "top_domains": ["tripadvisor.com", "booking.com"]}}

EXTRACTED = {
    "answers": [
        {"id": "best", "hotels": [{"name": "Le Royal Hotels & Resorts", "rank": 1, "reason": "5-star with spa", "rating": None},
                                  {"name": "Sofitel Luxembourg Le Grand Ducal", "rank": 2, "reason": "views and breakfast", "rating": "8.6 on Booking.com"},
                                  {"name": "Park Inn by Radisson", "rank": 3, "reason": "budget, near the station", "rating": None},
                                  {"name": "The Invented Palace", "rank": 4, "reason": "does not appear in the answer", "rating": None}]},
        {"id": "where", "hotels": [{"name": "Le Royal Hotels & Resorts", "rank": 1, "reason": "luxury", "rating": None},
                                   {"name": "Park Inn by Radisson Luxembourg City", "rank": 2, "reason": "best value", "rating": None},
                                   {"name": "Hotel Grey", "rank": 3, "reason": "across from the station", "rating": None}]},
        {"id": "similar", "hotels": [{"name": "Novotel Luxembourg Kirchberg", "rank": 1, "reason": "business", "rating": None},
                                     {"name": "Meliá Luxembourg", "rank": 2, "reason": "value", "rating": None}]},
        {"id": "ghost", "hotels": [{"name": "Not An Answer", "rank": 1, "reason": "x", "rating": None}]}],
    "about": {"tone": "mixed", "strengths": ["spacious rooms"], "weaknesses": ["far from the centre", "dated decor"],
              "claims": [{"type": "parking", "value": "free parking", "answer_id": "about"}, {"type": "check_in", "value": "3 pm", "answer_id": "about"},
                         {"type": "phone", "value": "+352 43 781", "answer_id": "about"}, {"type": "star_rating", "value": "4-star", "answer_id": "about"},
                         {"type": "mystery", "value": "ignored", "answer_id": "about"}]}}


def resp(text, tin=3000, tout=900, searches=0, urls=()):
    blocks = ([NS(type="web_search_tool_result", content=[NS(url=u, title="t") for u in urls])] if urls else []) + [NS(type="text", text=text, citations=None)]
    return NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=tin, output_tokens=tout, server_tool_use=NS(web_search_requests=searches)))


class Fake:
    def __init__(self, answers, boom_on=None):
        self.answers, self.calls, self.boom_on = list(answers), [], boom_on
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom_on and len(self.calls) == self.boom_on[0]:
            raise self.boom_on[1]
        return self.answers.pop(0)


print("1. names and counting")
check("one hotel written two ways has one identity ('Oatlands Park Hotel & Spa' = 'Oatlands Park')", ins.canon("Oatlands Park Hotel & Spa") == ins.canon("Oatlands Park"))
check("a name is real only if it appears in that answer", ins.appears("Le Royal Hotels & Resorts", ITEMS[0]["answer"]) and not ins.appears("The Invented Palace", ITEMS[0]["answer"]))

print("2. the extraction pass keeps only what the answers contain")
fake = Fake([resp(json.dumps(EXTRACTED))])
ex, usage = ins.extract(fake, "claude-haiku-5-5", ITEMS, HOTEL, CITY)
check("the prompt shows the answers and asks for JSON only; effort is low", "Le Royal" in fake.calls[0]["messages"][0]["content"] and fake.calls[0].get("output_config") == {"effort": "low"})
names = [h["name"] for h in ex["answers"]["best"]]
check("a hotel the answer never mentioned is dropped ('The Invented Palace'), real ones kept", "The Invented Palace" not in names and len(names) == 3, names)
check("an answer id that was never asked is ignored", "ghost" not in ex["answers"])
check("only known claim types are kept, with the tone validated", [c["type"] for c in ex["about"]["claims"]] == ["parking", "check_in", "phone", "star_rating"] and ex["about"]["tone"] == "mixed")
check("prose instead of JSON gives None, never a guess", ins.extract(Fake([resp("sorry")]), "claude-haiku-5-5", ITEMS, HOTEL, CITY)[0] is None)

print("3. the leaderboard (plain arithmetic)")
lb = ins.leaderboard(ex, ITEMS, HOTEL)
rows = {r["name"]: r for r in lb["rows"]}
check("Le Royal was named in both generic answers, ranked first both times", rows["Le Royal Hotels & Resorts"]["mentions"] == 2 and rows["Le Royal Hotels & Resorts"]["avg_rank"] == 1.0)
check("'Park Inn by Radisson' and 'Park Inn by Radisson Luxembourg City' are folded into ONE hotel", sum(1 for n in rows if n.startswith("Park Inn")) == 1 and
      next(r for n, r in rows.items() if n.startswith("Park Inn"))["mentions"] == 2)
check("the similar-hotels question is NOT counted in the generic share (only 2 questions)", lb["questions"] == 2 and "Novotel Luxembourg Kirchberg" not in rows)
me = next(r for r in lb["rows"] if r["is_target"])
check("the hotel is in the same table with zeros when never named", me["mentions"] == 0 and me["share"] == 0 and me["avg_rank"] is None)
check("shares add up to about 100% across the other hotels", 95 <= sum(r["share"] for r in lb["rows"]) <= 105, sum(r["share"] for r in lb["rows"]))
check("the competitive set is what the assistant offered as 'similar'", [h["name"] for h in ins.alternatives(ex, HOTEL)] == ["Novotel Luxembourg Kirchberg", "Meliá Luxembourg"])

print("4. sources")
fp = [{"platform": "Booking.com", "discovered": True}, {"platform": "TripAdvisor", "discovered": True}, {"platform": "Trip.com", "discovered": False}]
src = {s["domain"]: s for s in ins.source_table(ITEMS, fp, [{"source": "Wikidata", "found": False}], own_domain="hilton.com")}
check("sources are counted and typed", src["tripadvisor.com"]["answers"] == 2 and src["tripadvisor.com"]["kind"] == "Review site" and src["trip.com"]["kind"] == "Booking and comparison site")
check("'is the hotel there?' comes from this audit's own lookups: found, not found, or not checked",
      src["booking.com"]["hotel_evidenced"] is True and src["trip.com"]["hotel_evidenced"] is False and src["visitluxembourg.com"]["hotel_evidenced"] is None)
check("the hotel's own site is recognised", src["hilton.com"]["kind"] == "The hotel's own website" and src["hilton.com"]["hotel_evidenced"] is True)

print("5. is what it said correct?")
known = {"phones": ["+352 43 781"], "check_in": "15:00", "parking_text": "Self-parking is 15.00 EUR per day", "parking_source": "the hotel's own pages"}
acc = ins.accuracy(ex["about"]["claims"], {**known, "parking_text": "Self-parking is €15.00 per day"})
st = {r["claim"]: r["status"] for r in acc["rows"]}
check("a matching phone number and check-in time are confirmed", st["Phone number"] == "matches" and st["Check-in time"] == "matches", st)
check("'free parking' against a page that states a charge is flagged as differing", st["Parking"] == "differs", st)
check("a star rating we hold nothing on is counted as 'could not check', never as wrong", acc["unchecked"] == 1 and "Star rating" not in st)
acc2 = ins.accuracy([{"type": "check_in", "value": "2 pm"}], {"check_in": "15:00", "hours_source": "the hotel's own pages"})
check("a different time is flagged", acc2["rows"][0]["status"] == "differs")
check("'free parking' against a page that also says parking is free is a match",
      ins.accuracy([{"type": "parking", "value": "free parking"}], {"parking_text": "Free parking is available on site"})["rows"][0]["status"] == "matches")
check("nothing to compare against gives no verdict at all", ins.accuracy([{"type": "phone", "value": "+1 555 0100"}], {})["rows"] == [])

print("6. perception against positioning")
pc = ins.perception({"strengths": ["tranquil woodland setting", "indoor pool"], "weaknesses": ["dated decor"], "claims": [{"value": "16 meeting spaces"}]},
                    ["Families", "Meetings and events", "Spa and wellness", "Dog / pet friendly"])
check("what the site emphasises but the assistant did not say is listed (families, pets) while covered things are not (meetings, spa)",
      pc["not_in_assistant_description"] == ["Families", "Dog / pet friendly"], pc)

print("7. grounded hypotheses")
ledger = ins.build_ledger(lb, list(src.values()), pc, ex["about"], {"platforms": [{"platform": "Tripadvisor", "rating": 3.8, "review_count": 3137}]}, AI, fp,
                          [{"source": "Wikidata", "found": False}], ["Families"])
ids = {e["id"] for e in ledger}
check("the evidence ledger is numbered and built from this audit's own data", "E1" in ids and any("Le Royal" in e["text"] for e in ledger) and any("3.8" in e["text"] for e in ledger)
      and any("Wikidata" in e["text"] for e in ledger))
good = {"summary": "The hotel was not named; competitors had clearer categories.", "hypotheses": [
    {"text": "It may be that competitors are framed around clear categories.", "evidence": ["E1", "E2"], "action": "Check the listing text."},
    {"text": "One difference is something with no evidence behind it.", "evidence": [], "action": None},
    {"text": "It may be that the evidence id is invented.", "evidence": ["E99"], "action": None}]}
fake = Fake([resp(json.dumps(good))])
exp, _u = ins.explain(fake, "claude-haiku-5-5", HOTEL, CITY, ledger, 2, 2)
check("a hypothesis citing no valid evidence id is dropped (2 of 3 dropped)", len(exp["hypotheses"]) == 1 and exp["hypotheses"][0]["evidence"] == ["E1", "E2"])
sent = fake.calls[0]
check("the model is told it cannot see its own reasoning, must use only the evidence, and must not assert facts about competitors",
      "CANNOT see the assistant's reasoning" in sent["system"] and "Use ONLY that evidence" in sent["system"]
      and "Never assert facts about competitors" in sent["messages"][0]["content"])

print("8. the whole run")
fake = Fake([resp(json.dumps(EXTRACTED)), resp(json.dumps(good)), resp("Le Royal suits luxury; DoubleTree by Hilton Luxembourg suits a quiet stay.", searches=2, urls=["https://www.booking.com/x"])])
ctx = {"hotel": HOTEL, "city": CITY, "guest": {"fact_sheet": [{"fact": "Check-in time", "value": "15:00"}, {"fact": "Parking", "value": "Self-parking 15.00 EUR per day"}]},
       "entities": [{"source": "OpenStreetMap", "found": True, "match_confident": True, "facts": {"telephone": "+352 43 781", "address": "Rue Jean Engling, Luxembourg"}}],
       "footprint": fp, "snapshot": None, "strong_intents": ["Families"], "own_domain": "hilton.com"}
r = ins.run(AI, ctx, client=fake)
check("three calls: extraction, explanation (no web search), head-to-head (with web search)", len(fake.calls) == 3 and "tools" not in fake.calls[0] and "tools" not in fake.calls[1] and fake.calls[2]["tools"][0]["name"] == "web_search")
check("scoreboard: 0 of 2 named, top competitor Le Royal, hotel last in the table", r["status"] == "ok" and r["scoreboard"]["named"] == 0 and r["scoreboard"]["top_competitor"] == "Le Royal Hotels & Resorts"
      and r["scoreboard"]["rank_in_table"] == r["scoreboard"]["table_size"], r["scoreboard"])
check("the parking mismatch is found from the hotel's own record, the phone from the map", any(x["claim"] == "Parking" and x["status"] == "differs" for x in r["accuracy"]["rows"])
      and any(x["claim"] == "Phone number" and x["status"] == "matches" for x in r["accuracy"]["rows"]))
check("head to head records both hotels named and its sources", r["head_to_head"]["both_named"] and r["head_to_head"]["domains"] == ["booking.com"])
check("the cost is tiny and summed", 0 < r["cost_usd"] < 0.05, r["cost_usd"])
json.dumps(r)

named_items = [{**i, "answer": i["answer"] + ("\n4. **DoubleTree by Hilton Luxembourg**: a quiet option." if i["kind"] == "generic" else "")} for i in ITEMS]
named_ex = {**EXTRACTED, "answers": [{**a, "hotels": a["hotels"] + ([{"name": "DoubleTree by Hilton Luxembourg", "rank": 4, "reason": "a quiet option", "rating": None}] if a["id"] in ("best", "where") else [])}
                                      for a in EXTRACTED["answers"]]}
fake = Fake([resp(json.dumps(named_ex))])
r = ins.run({**AI, "items": named_items}, ctx, client=fake, do_head_to_head=False)
check("when the hotel IS named in every generic answer there is nothing to explain: one call only, no hypotheses, a real share of the names",
      len(fake.calls) == 1 and "explanation" not in r and r["scoreboard"]["named"] == 2 and r["scoreboard"]["share"] > 0, (len(fake.calls), r["scoreboard"]))

class E(Exception):
    status_code = 429


r = ins.run(AI, ctx, client=Fake([], boom_on=(1, E())))
check("if the extraction fails the source analysis still shows, with the reason", r["status"] == "partial" and "rate limit" in r["reason"] and r["sources"])
r = ins.run(AI, ctx, client=Fake([resp(json.dumps(EXTRACTED)), resp("not json")], boom_on=None), do_head_to_head=False)
check("if the explanation step returns nothing, the arithmetic sections still show and the gap is noted", r["status"] == "ok" and r["leaderboard"] and any("explanation" in n.lower() for n in r["notes"]))
check("no key and no client: only the source analysis, with the reason", ins.run(AI, ctx)["status"] == "partial")
check("no sample, no analysis", ins.run(None, ctx)["status"] == "unavailable")

print("9. what it adds to the plan")
INS = {"status": "ok", "accuracy": {"rows": [{"claim": "Parking", "assistant_says": "free parking", "our_record": "the hotel's page mentions a parking charge", "status": "differs",
                                             "source": "the hotel's own pages"}], "unchecked": 0},
       "sources": [{"domain": "trip.com", "kind": "Booking and comparison site", "answers": 3, "hotel_evidenced": False},
                   {"domain": "tripadvisor.com", "kind": "Review site", "answers": 4, "hotel_evidenced": True}]}
recs = advice._from_ai_insights(INS)
byid = {x["id"]: x for x in recs}
check("a statement that differs from the hotel's own record becomes a medium recommendation, and a source gap a low opportunity", set(byid) == {"AI3", "AI2"} and byid["AI3"]["priority"] == "medium" and byid["AI2"]["priority"] == "low")
ranking.annotate(recs, [])
check("AI3 is a required fix (a wrong price expectation is a guest problem), AI2 an opportunity", byid["AI3"]["kind"] == "fix" and byid["AI2"]["kind"] == "opportunity")
check("both stay honest: one model on one day, and 'not found' may be a search gap", "one model on one day" in byid["AI3"]["why"] and "search gap" in byid["AI2"]["why"])
check("nothing for a matching or missing analysis", advice._from_ai_insights(None) == [] and advice._from_ai_insights({"status": "unavailable"}) == []
      and advice._from_ai_insights({"status": "ok", "accuracy": {"rows": [], "unchecked": 2}, "sources": []}) == [])

print("10. run against run")
mk = lambda named, share, comps, doms: {"meta": {"website": "x.com", "run_at": "2026-10-01"}, "scorecard": {"overall": 50, "coverage_pct": 50, "categories": []},  # noqa: E731
                                          "ai_sample": {"status": "ok", "run_at": "2026-10-01", "summary": {"generic_named": named, "generic_asked": 4, "direct_known": True, "top_domains": doms}},
                                          "ai_insights": {"scoreboard": {"share": share, "avg_rank": 2.0}, "leaderboard": {"rows": [{"name": c, "is_target": False} for c in comps]}}}
tr = compare._ai_trend(mk(1, 5, ["A", "B"], ["booking.com"]), mk(3, 12, ["A", "C"], ["booking.com", "tripadvisor.com"]))
check("this month against last: named 1 -> 3 of 4, new competitor C, dropped B, a newly relied-on source", tr["old"]["named"] == 1 and tr["new"]["named"] == 3 and tr["new_competitors"] == ["C"]
      and tr["dropped_competitors"] == ["B"] and tr["new_sources"] == ["tripadvisor.com"])
check("it says small changes are noise", "noise" in tr["note"])
o_ = mk(1, 5, ["A"], []); n_ = mk(3, 12, ["A"], [])
o_["ai_insights"]["scoreboard"].update(coverage_pct=25, sentiment=0); n_["ai_insights"]["scoreboard"].update(coverage_pct=60, sentiment=50)
tr2 = compare._ai_trend(o_, n_)
check("the trend carries coverage % and net sentiment, so runs that asked a different number of answers can still be compared",
      (tr2["old"]["coverage_pct"], tr2["new"]["coverage_pct"], tr2["old"]["sentiment"], tr2["new"]["sentiment"]) == (25, 60, 0, 50))
check("no trend unless both runs have a sample", compare._ai_trend({"ai_sample": None}, mk(1, 1, [], [])) is None)

print("11. sentiment, batching, brand ranking, pages, repeated answers")
SENT = {"answers": [{"id": "best", "hotels": [{"name": "Le Royal Hotels & Resorts", "rank": 1, "reason": "spa", "rating": None, "sentiment": "positive"},
                                              {"name": "Park Inn by Radisson", "rank": 3, "reason": "budget", "rating": None, "sentiment": "negative"}]},
                    {"id": "where", "hotels": [{"name": "Le Royal Hotels & Resorts", "rank": 1, "reason": "luxury", "rating": None, "sentiment": "positive"},
                                               {"name": "Hotel Grey", "rank": 3, "reason": "station", "rating": None, "sentiment": "banana"}]}],
        "about": {"tone": "mixed", "strengths": [], "weaknesses": [], "claims": []}}
exs, _u = ins.extract(Fake([resp(json.dumps(SENT)), resp(json.dumps({"answers": [], "about": {}}))]), "claude-haiku-5-5", ITEMS, HOTEL, CITY)
check("sentiment is kept per hotel, and an unknown label becomes neutral", exs["answers"]["best"][0]["sentiment"] == "positive" and exs["answers"]["where"][1]["sentiment"] == "neutral")
lbs = ins.leaderboard(exs, ITEMS, HOTEL)
royal = next(r for r in lbs["rows"] if r["name"].startswith("Le Royal"))
check("net sentiment = % positive minus % negative: 2 positive of 2 -> +100; one negative of one -> -100; nothing judged -> None",
      royal["sentiment"] == 100 and next(r for r in lbs["rows"] if r["name"].startswith("Park Inn"))["sentiment"] == -100 and next(r for r in lbs["rows"] if r["is_target"])["sentiment"] is None)
check("coverage % is the share of answers that named the hotel", royal["coverage_pct"] == 100 and next(r for r in lbs["rows"] if r["is_target"])["coverage_pct"] == 0)
many = [{**ITEMS[0], "id": f"q{k}", "kind": "generic"} for k in range(10)] + [ITEMS[2]]
fk = Fake([resp(json.dumps({"answers": [], "about": {"tone": "positive", "strengths": [], "weaknesses": [], "claims": []}})), resp(json.dumps({"answers": [], "about": {}})),
           resp(json.dumps({"answers": [], "about": {}}))])
ins.extract(fk, "claude-haiku-5-5", many, HOTEL, CITY)
check("11 answers go in 2 calls of at most 8, the answers about the hotel first so its description is read once", len(fk.calls) == 2 and "[about]" in fk.calls[0]["messages"][0]["content"]
      and "[about]" not in fk.calls[1]["messages"][0]["content"])
br = ins.brand_ranking([lbs], HOTEL)
check("the brand ranking is the hotel plus the top competitors, each with coverage, position and sentiment, and the hotel is always in it",
      any(r["is_target"] for r in br["rows"]) and br["rows"][0]["name"].startswith("Le Royal") and {"coverage_pct", "avg_rank", "sentiment", "place"} <= set(br["rows"][0]) and len(br["rows"]) <= 6)
pg = [{**ITEMS[0], "pages": [{"url": "https://www.booking.com/hotel/a.html", "title": "Le Royal Hotels - Booking.com", "cited": True, "cited_text": "Le Royal is a 5-star"},
                              {"url": "https://www.hilton.com/en/hotels/x/", "title": "DoubleTree by Hilton Luxembourg", "cited": False, "cited_text": ""}]},
      {**ITEMS[1], "qid": "where", "pages": [{"url": "https://www.booking.com/hotel/a.html", "title": "Le Royal Hotels - Booking.com", "cited": True, "cited_text": "Le Royal"}]}]
pt = ins.page_table(pg, HOTEL, ["Le Royal Hotels & Resorts"], own_domain="hilton.com")
top = pt[0]
check("pages are listed most-cited first with how many questions used them, and which name the hotel or a competitor",
      top["url"].endswith("a.html") and top["cited"] == 2 and top["questions"] == 2 and top["names_competitor"] and not top["names_hotel"]
      and next(p for p in pt if "hilton.com" in p["url"])["names_hotel"] and next(p for p in pt if "hilton.com" in p["url"])["own_site"])
rep_items = [{**ITEMS[0], "id": "best", "qid": "best", "repeat": 1, "mentioned": False}, {**ITEMS[0], "id": "best#2", "qid": "best", "repeat": 2, "mentioned": True, "position": 2}]
qr = ins.question_rows(rep_items, {"answers": {"best": [{"name": "Le Royal Hotels & Resorts"}], "best#2": [{"name": "Hotel Grey"}]}})
check("repeated answers collapse to ONE question row: named in 1 of 2, best position 2, hotels from both answers", len(qr) == 1 and qr[0]["named"] == 1 and qr[0]["of"] == 2
      and qr[0]["position"] == 2 and qr[0]["hotels_named"] == ["Le Royal Hotels & Resorts", "Hotel Grey"] and qr[0]["answer_ids"] == ["best", "best#2"])
fk = Fake([resp(json.dumps(SENT)), resp(json.dumps({"answers": [], "about": {}})), resp(json.dumps({"summary": "s", "hypotheses": []})), resp("x")])
rr = ins.run({**AI, "summary": {**AI["summary"], "repeats": 2}}, ctx, client=fk, do_head_to_head=False)
check("the run carries a brand ranking, the pages, the hotel's coverage %, sentiment and place into the scoreboard",
      rr["brand_ranking"]["rows"] and "pages" in rr and {"coverage_pct", "sentiment", "place", "repeats"} <= set(rr["scoreboard"]) and rr["scoreboard"]["repeats"] == 2, rr["scoreboard"])
json.dumps(rr)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
