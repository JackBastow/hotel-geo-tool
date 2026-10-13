"""
Offline tests for review_replies.py: the indicative reviews-and-replies snapshot. A fake client stands in for the
Anthropic SDK, so nothing here touches the network or spends credit. Run: python test_review_replies.py
"""
import json
from types import SimpleNamespace as NS

import advice
import ranking
import review_replies as rr

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


SEEN = ["https://www.tripadvisor.co.uk/Hotel_Review-g190763-d1650047-Reviews-Brooklands_Hotel-Weybridge_Surrey_England.html",
        "https://www.tripadvisor.com/ShowUserReviews-g190763-d1650047-r965119213-Brooklands_Hotel-Weybridge_Surrey_England.html",
        "https://www.booking.com/reviews/gb/hotel/brooklands-weybridge.en-gb.html"]


def answer(data, stop="end_turn", urls=SEEN, tin=40000, tout=3000, searches=3):
    blocks = [NS(type="web_search_tool_result", content=[NS(url=u, title="t") for u in urls]),
              NS(type="text", text=data if isinstance(data, str) else json.dumps(data), citations=None)]
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=tin, output_tokens=tout, server_tool_use=NS(web_search_requests=searches)))


class Fake:
    def __init__(self, answers, boom=None):
        self.answers, self.calls, self.boom = list(answers), [], boom
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom
        return self.answers.pop(0)


def rev(url=SEEN[0], **kw):
    base = {"platform": "Tripadvisor", "url": url, "review_date": "2026-08", "sentiment": "negative", "owner_replied": True, "reply_by": "General Manager",
            "reply_date": "2026-08", "reply_tone": "specific and engaged", "reply_summary": "Thanks the guest and explains the service charge."}
    base.update(kw)
    return base


print("1. is the cited page one the search actually returned?")
seen = rr.seen_urls(answer({}).content)
check("only pages in the search results count as seen (host + path, case, www, query and trailing slash ignored)",
      rr.was_seen("HTTPS://tripadvisor.co.uk/Hotel_Review-g190763-d1650047-Reviews-Brooklands_Hotel-Weybridge_Surrey_England.html?x=1", seen)
      and not rr.was_seen("https://www.tripadvisor.com/ShowUserReviews-g1-d2-r3-Invented.html", seen) and not rr.was_seen("", seen))
check("a long page address that merely extends a returned one is accepted; a short prefix is not",
      rr.was_seen(SEEN[2] + "#reviews", seen) and not rr.was_seen("https://www.booking.com/", seen))
check("a web-search ERROR object (not a list) yields no pages and no crash", rr.seen_urls([NS(type="web_search_tool_result", content=NS(error_code="too_many_requests"))]) == set())

print("2. reading the model's JSON")
check("JSON inside a code fence with chatter around it is read", rr.parse_json('Here you go:\n```json\n{"a": 1}\n```\nHope that helps')["a"] == 1)
check("no JSON, or broken JSON, gives None rather than a guess", rr.parse_json("I could not find anything.") is None and rr.parse_json('{"a": ') is None and rr.parse_json("") is None)

print("3. a run")
data = {"platforms": [{"platform": "Tripadvisor", "rating": 4.0, "review_count": 4189, "url": SEEN[0]},
                      {"platform": "Booking.com", "rating": 99, "review_count": 1294, "url": SEEN[2]},
                      {"platform": "Invented", "rating": 5.0, "review_count": 10, "url": "https://www.example.com/not-in-results"}],
        "reviews": [rev(), rev(SEEN[1], sentiment="positive", reply_tone="warm template", reply_summary="Thanks them and invites them back."),
                    rev(SEEN[0], sentiment="negative", owner_replied=False, reply_by=None, reply_tone=None, reply_summary=""),
                    rev(SEEN[1], sentiment="mixed", owner_replied=None),
                    rev("https://www.tripadvisor.com/ShowUserReviews-g1-d2-r3-Invented.html", reply_summary="A reply that does not exist"),
                    rev(SEEN[0], sentiment="negative", reply_tone="defensive", reply_by="Jane Smith, owner", reply_summary="Says the guest declined a room move.")],
        "not_found": ["Google reviews: none seen"]}
fake = Fake([answer(data)])
r = rr.run("Brooklands Hotel", "Weybridge", client=fake)
call = fake.calls[0]
check("one request, web search allowed up to six times, the cheap model, a roomy token ceiling, and a prompt that forbids inventing",
      len(fake.calls) == 1 and call["tools"][0]["max_uses"] == 6 and call["model"] == "claude-haiku-5-5" and call["max_tokens"] == 12000
      and "Never invent" in call["system"] and "do not name reviewers or staff" in call["system"])
check("an item whose page was NOT in the search results is dropped and counted (a review and a platform)", r["status"] == "ok" and r["dropped"] == 2 and len(r["items"]) == 5 and len(r["platforms"]) == 2, (r["dropped"], len(r["items"])))
check("an impossible rating (99) is discarded rather than shown", next(p for p in r["platforms"] if p["platform"] == "Booking.com")["rating"] is None)
s = r["summary"]
check("the summary counts what was SEEN: 5 reviews, 4 examined (one 'can't tell'), 3 replied, 3 critical examined with 2 replied",
      (s["reviews_seen"], s["examined"], s["replied"], s["unclear"], s["negative_examined"], s["negative_replied"]) == (5, 4, 3, 1, 3, 2), s)
check("tones are tallied", s["tones"] == {"specific and engaged": 1, "warm template": 1, "defensive": 1}, s["tones"])
check("a reply's author is kept only as a short role string as given (the model was told to use roles)", all(len(i["reply_by"] or "") <= 40 for i in r["items"]))
check("a review with no reply carries no invented reply text, tone or author",
      all(i["reply_summary"] == "" and i["reply_tone"] is None and i["reply_by"] is None for i in r["items"] if not i["owner_replied"]))
check("cost comes from the usage the API reports and the access note says it is not a reply rate", 0.02 < r["cost_usd"] < 0.10 and "not the hotel's reply rate" in r["access"], r["cost_usd"])
check("what the model could not find is passed on", r["not_found"] == ["Google reviews: none seen"])

print("4. failure and edge cases")
r = rr.run("Brooklands Hotel", "Weybridge", client=Fake([answer({"platforms": [], "reviews": [rev("https://example.com/made-up")]})]))
check("when everything cited is invented, nothing is shown and the reason says so", r["status"] == "no_results" and "dropped" in r["reason"] and r["items"] == [])
r = rr.run("Brooklands Hotel", "Weybridge", client=Fake([answer("I could not understand the request.")]))
check("prose instead of JSON is 'unavailable', never shown", r["status"] == "unavailable" and "could not be understood" in r["reason"])
r = rr.run("Brooklands Hotel", "Weybridge", client=Fake([answer('{"platforms": [', stop="max_tokens")]))
check("a truncated answer says it ran out of room", r["status"] == "unavailable" and "ran out of room" in r["reason"])
f2 = Fake([answer("{}", stop="pause_turn", urls=[SEEN[0]]), answer(data, urls=SEEN)])
r = rr.run("Brooklands Hotel", "Weybridge", client=f2)
check("a paused search is continued (and pages seen before the pause still count)", len(f2.calls) == 2 and r["status"] == "ok" and len(r["items"]) == 5)


class E(Exception):
    status_code = 429


r = rr.run("Brooklands Hotel", "Weybridge", client=Fake([], boom=E()))
check("an API failure becomes a stated reason", r["status"] == "unavailable" and "rate limit" in r["reason"])
check("no key, or no town: not run, with the reason", rr.run("Brooklands Hotel", "Weybridge")["status"] == "not_configured" and rr.run("X", "", api_key="k")["status"] == "not_configured")
check("budget used up is stated", "allowance" in rr.budget_exhausted()["reason"])
json.dumps(r)

print("5. what it adds to the plan")
RS = lambda **s: {"status": "ok", "model": "claude-haiku-5-5", "items": [  # noqa: E731
    {"platform": "Tripadvisor", "url": SEEN[0], "review_date": "2026-08", "sentiment": "negative", "owner_replied": False, "reply_tone": None, "reply_summary": "", "reply_by": None}],
    "summary": {"reviews_seen": 6, "examined": 6, "replied": 1, "unclear": 0, "negative_examined": 3, "negative_replied": 0, "tones": {}, "platforms_with_replies": [], **s}}
r1 = advice._from_reviews(RS())
check("critical reviews seen with no reply give ONE low-confidence recommendation that is explicit it is not a reply rate",
      len(r1) == 1 and r1[0]["id"] == "RV1" and r1[0]["confidence"] == advice.EXPER and "not a measure of the hotel's reply rate" in r1[0]["why"], r1)
check("the advice never offers anything for a changed review", "in return for a changed review" in r1[0]["action"] and "Do not offer" in r1[0]["action"])
check("it is ranked by the global model as a required fix of medium weight, owned by reputation management",
      (ranking.annotate(r1, []), r1[0]["kind"] == "fix" and r1[0]["team"] == "reputation management")[1])
check("healthy reply behaviour yields nothing", advice._from_reviews(RS(negative_examined=3, negative_replied=3, replied=5)) == [])
check("no replies at all on 4+ reviews examined is flagged (when criticals do not apply)",
      advice._from_reviews(RS(negative_examined=0, negative_replied=0, replied=0, examined=5))[0]["id"] == "RV1")
r2 = advice._from_reviews(RS(negative_examined=3, negative_replied=3, replied=5, tones={"defensive": 1, "warm template": 4}))
check("a defensive tone gives a low-priority opportunity, described as 'an AI's reading of a small sample'",
      len(r2) == 1 and r2[0]["id"] == "RV2" and r2[0]["priority"] == "low" and "AI's reading" in r2[0]["finding"])
check("nothing for a failed or missing snapshot", advice._from_reviews(None) == [] and advice._from_reviews({"status": "unavailable"}) == [])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
