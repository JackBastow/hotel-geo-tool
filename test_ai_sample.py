"""
Offline tests for ai_sample.py (the sampled AI answers). A fake client stands in for the Anthropic SDK:
nothing here calls the network or spends any credit. Run: python test_ai_sample.py
"""
from types import SimpleNamespace as NS

import ai_sample as ai

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "DoubleTree by Hilton Luxembourg", "Luxembourg"


def resp(text, urls=(), searches=2, tin=12000, tout=400, cites=()):
    blocks = []
    if urls:
        blocks.append(NS(type="web_search_tool_result", content=[NS(url=u, title="t") for u in urls]))
    blocks.append(NS(type="text", text=text, citations=[NS(url=u, title="t") for u in cites]))
    return NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=tin, output_tokens=tout, server_tool_use=NS(web_search_requests=searches)))


class Fake:
    def __init__(self, answers, raise_on=None):
        self.answers, self.calls, self.raise_on = list(answers), [], raise_on
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.raise_on is not None and len(self.calls) == self.raise_on[0]:
            raise self.raise_on[1]
        return self.answers.pop(0)


print("1. the questions")
qs = ai.build_questions(HOTEL, CITY, ["Business travel"])
check("six standard questions: two town-wide ones (the big names are not the test), then four about the hotel itself; the narrower market questions come from ai_niche",
      [q["kind"] for q in qs] == ["generic"] * 2 + ["direct"] * 4 and all(HOTEL in q["text"] for q in qs[2:]), [q["kind"] for q in qs])
check("the direct questions cover what it is, its facilities, what guests say, and who it is compared with",
      [q["id"] for q in qs[2:]] == ["about", "facilities", "reviews", "similar"])
check("the town-wide questions are the plain ones: best hotels, and where to stay", [q["id"] for q in qs[:2]] == ["best", "where"] and "best hotels" in qs[0]["text"])
check("without a town no question is built (nothing sensible to ask)", ai.build_questions(HOTEL, "") == [])
check("a lower cap drops generic questions first and keeps the direct ones",
      [q["kind"] for q in ai.build_questions(HOTEL, CITY, ["x"], 5)] == ["generic"] + ["direct"] * 4 and [q["kind"] for q in ai.build_questions(HOTEL, CITY, [], 4)] == ["direct"] * 4)

print("2. is the hotel named?")
check("full name is recognised", ai.mentioned("1. DoubleTree by Hilton Luxembourg - near the airport", HOTEL, CITY))
check("accents and case do not matter", ai.mentioned("the DOUBLETREE BY HILTON LUXEMBOURG hotel", HOTEL, CITY))
check("a different hotel by the same brand is NOT a mention", not ai.mentioned("Hilton Luxembourg Grand and DoubleTree by Hilton Paris are good", HOTEL, CITY))
check("a bare one-word name needs the place or 'hotel' beside it",
      ai.mentioned("Brooklands Hotel in Weybridge is lovely.", "Brooklands Hotel", "Weybridge") and not ai.mentioned("Brooklands is a racing circuit.", "Brooklands", "Weybridge"))
check("a landmark that shares the hotel's one distinctive word is NOT the hotel ('Brooklands Museum' is not 'Brooklands Hotel')",
      not ai.mentioned("The location is convenient for Brooklands Museum and Mercedes-Benz World.", "Brooklands Hotel", "Weybridge")
      and ai.mentioned("Brooklands Hotel & Spa is the highest rated.", "Brooklands Hotel", "Weybridge")
      and ai.mentioned("Brooklands spa guests enjoy the pool.", "Brooklands Hotel", "Weybridge"))
check("it is not fooled when the museum is listed in a bullet", ai.list_position("- Weybridge Museum\n- Brooklands Museum\n- Brooklands Hotel", "Brooklands Hotel") == 3)
ans = "Top picks:\n1. Le Royal\n2. Sofitel Kirchberg\n3. DoubleTree by Hilton Luxembourg - good value\n"
check("the place in a list is found", ai.list_position(ans, HOTEL) == 3 and ai.list_position("no list here", HOTEL) is None)

print("3. a run")
gen = [resp("Top hotels: Le Royal, Sofitel.", ["https://www.tripadvisor.com/x", "https://www.booking.com/y"]),
       resp("Try Le Royal.", ["https://www.booking.com/z"]),
       ]
dr = [resp("DoubleTree by Hilton Luxembourg is a business hotel in Dommeldange with a spa.", ["https://www.hilton.com/en/hotels/x/"], cites=["https://www.hilton.com/en/hotels/x/"]),
      resp("DoubleTree by Hilton Luxembourg has a gym and a restaurant.", ["https://www.hilton.com/en/hotels/x/"]),
      resp("Guests like the location; some complain about noise.", ["https://www.tripadvisor.com/r"]),
      resp("Similar: Sofitel Kirchberg and Meliá.", ["https://www.booking.com/s"])]
fake = Fake(gen + dr)
r = ai.run(HOTEL, CITY, client=fake, segments=["Business travel"], own_domain="https://www.hilton.com/en/hotels/x/", workers=1, repeats=1)
check("it asks every question once, each with the web-search tool allowing three searches, a token cap and the cheap model",
      len(fake.calls) == 6 and all(c["tools"][0]["name"] == "web_search" and c["tools"][0]["max_uses"] == 3 and c["max_tokens"] == 1500 and c["model"] == "claude-haiku-5-5" for c in fake.calls))
check("effort is set low for the model that supports it", all(c.get("output_config") == {"effort": "low"} for c in fake.calls))
s_ = r["summary"]
check("generic answers that never name the hotel are counted honestly (0 of 2), while the direct ones are known (2 of 4 name it)",
      r["status"] == "ok" and s_["generic_asked"] == 2 and s_["generic_named"] == 0 and s_["direct_known"] is True and s_["direct_asked"] == 4 and s_["direct_named"] == 2, s_)
check("the hotel's own website being cited is noticed", s_["own_site_cited"] and any(i.get("own_site_cited") for i in r["items"]))
check("the sources the assistant relied on are listed, most used first", s_["top_domains"][0] == "booking.com" and "tripadvisor.com" in s_["top_domains"], s_["top_domains"])
check("cost is estimated from the usage the API reports (tokens plus $0.01 a search) and stays well inside the per-audit budget",
      0.10 < r["cost_usd"] < 0.30 and abs(r["cost_usd"] - sum(i["cost_usd"] for i in r["items"])) < 1e-6, r["cost_usd"])
check("it is labelled as a sample with the model, and the wording denies being a ranking", r["model"] == "claude-haiku-5-5" and "not a ranking" in r["access"])
fake = Fake(gen + dr)
r = ai.run(HOTEL, CITY, client=fake, segments=["Business travel"], workers=3, repeats=1)
check("running three at a time returns the same set of answers, in question order", len(r["items"]) == 6 and [i["id"] for i in r["items"]][:2] == ["best", "where"])

print("4. cost and failure control")
check("an unknown model is priced as the dearest, never under-counted", ai.cost_usd("some-new-model", 1_000_000, 0, 0) == 4.0)
fake = Fake([resp("x" * 50, searches=2, tin=2_000_000)] * 8)
r = ai.run(HOTEL, CITY, client=fake, budget_usd=0.10, workers=1, repeats=1)
check("when the per-audit budget is passed it stops asking (1 call), and says so", len(fake.calls) == 1 and r["partial"] and "budget" in r["reason"], (len(fake.calls), r["reason"]))
check("no key: not configured, with the reason", ai.run(HOTEL, CITY)["status"] == "not_configured" and "No Anthropic API key" in ai.run(HOTEL, CITY)["reason"])
check("no town: not run, with the reason", ai.run(HOTEL, "", api_key="k")["status"] == "not_configured")


class StatusErr(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.status_code = code


for code, want in ((401, "rejected the API key"), (429, "rate limit"), (400, "may not be available"), (402, "no credit")):
    r = ai.run(HOTEL, CITY, client=Fake([], raise_on=(1, StatusErr(code))), workers=1, repeats=1)
    check(f"HTTP {code} becomes a stated reason and never raises", r["status"] == "unavailable" and want in r["reason"], r["reason"])
ff = Fake([resp("Le Royal is great."), resp("x")], raise_on=(2, StatusErr(429)))
r = ai.run(HOTEL, CITY, client=ff, workers=1, repeats=1)
check("a failure part-way keeps what was already answered and stops asking (no hammering a rate limit)",
      r["status"] == "ok" and r["partial"] and len(r["items"]) == 1 and "rate limit" in r["reason"] and len(ff.calls) == 2, len(ff.calls))
r = ai.run(HOTEL, CITY, client=Fake([NS(content=[], stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1, server_tool_use=NS(web_search_requests=0)))] * 8), workers=1, repeats=1)
check("an empty answer is recorded as no answer, not as 'hotel not named'", r["status"] == "ok" and all(i["mentioned"] is None for i in r["items"]) and r["summary"]["generic_asked"] == 0)
err_content = NS(content=[NS(type="web_search_tool_result", content=NS(error_code="max_uses_exceeded")), NS(type="text", text="Le Royal.", citations=None)],
                 stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1, server_tool_use=None))
check("a web-search error object (not a list) is tolerated", ai.parse_response(err_content)[0] == "Le Royal." and ai.parse_response(err_content)[1] == [])

print("5. repeats and page-level citations")
qs0 = [{"id": "best", "kind": "generic", "text": "a"}, {"id": "n1", "kind": "niche", "text": "b"}, {"id": "about", "kind": "direct", "text": "c"}]
ex_ = ai.expand(qs0, 2)
check("town-wide and niche questions are asked twice, questions about the hotel once; every answer has its own id and keeps its question id",
      [i["id"] for i in ex_] == ["best", "best#2", "n1", "n1#2", "about"] and [i["qid"] for i in ex_] == ["best", "best", "n1", "n1", "about"] and ex_[1]["repeat"] == 2)
fake = Fake([resp("Le Royal.", ["https://www.booking.com/a"]), resp("DoubleTree by Hilton Luxembourg and Le Royal.", ["https://www.booking.com/a"])] + [resp("x")] * 20)
r = ai.run(HOTEL, CITY, client=fake, segments=[], workers=1)
gen_ = [i for i in r["items"] if i["kind"] == "generic"]
check("by default each town-wide question is answered twice, and the summary counts questions and answers separately",
      r["summary"]["repeats"] == 2 and r["summary"]["generic_asked"] == 2 * r["summary"]["generic_questions"] and gen_[0]["qid"] == gen_[1]["qid"] and gen_[1]["id"].endswith("#2"), r["summary"])
g = ai.by_question(r["items"])[0]
check("by_question puts the repeats together: named in 1 of 2 answers", g["of"] == 2 and g["named"] == 1)
cites = NS(content=[NS(type="web_search_tool_result", content=[NS(url="https://a.com/1", title="A"), NS(url="https://b.com/2", title="B")]),
                    NS(type="text", text="Le Royal.", citations=[NS(url="https://b.com/2", title="B", cited_text="Le Royal is   a 5-star hotel")])],
           stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1, server_tool_use=None))
pgs = ai.parse_sources(cites)
check("the exact pages are kept, the one the answer cites first, with the short passage it used", [p["url"] for p in pgs] == ["https://b.com/2", "https://a.com/1"]
      and pgs[0]["cited"] and pgs[0]["cited_text"] == "Le Royal is a 5-star hotel" and not pgs[1]["cited"])
check("every item records its pages", all("pages" in i for i in r["items"]))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
