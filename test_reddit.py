"""
Offline tests for reddit_check.py: the Reddit section of the report (threads found by search, the sampled AI answers that cite Reddit), its honesty rules, and the advice it raises.
A fake client stands in for the Anthropic SDK. Run: python test_reddit.py
"""
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import advice
import reddit_check as rc

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Brooklands Hotel", "Weybridge"
T_HOTEL = "https://www.reddit.com/r/surrey/comments/abc123/brooklands_hotel_weybridge_any_good/"
T_TOWN = "https://www.reddit.com/r/surrey/comments/def456/where_to_stay_in_weybridge/"
T_NEG = "https://www.reddit.com/r/uktravel/comments/ghi789/brooklands_hotel_experience/"
T_NOT_THREAD = "https://www.reddit.com/r/surrey/"
OTHER = "https://www.example.com/brooklands-hotel"


def resp(pages, cites=(), searches=3):
    blocks = [NS(type="web_search_tool_result", content=[NS(url=u, title=t) for u, t in pages]),
              NS(type="text", text="done", citations=[NS(url=u, title=t, cited_text=c) for u, t, c in cites] or None)]
    return NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=8000, output_tokens=300, server_tool_use=NS(web_search_requests=searches)))


class Fake:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0)


print("1. tone is a plain, labelled reading")
check("praise words give positive, complaint words critical, both mixed, neither no clear tone",
      rc.tone_of("lovely clean room, friendly staff") == "positive" and rc.tone_of("dirty and noisy, avoid") == "critical"
      and rc.tone_of("great breakfast but the room was dirty and noisy and rude staff") in ("mixed", "critical") and rc.tone_of("we stayed two nights") == "no clear tone")

print("2. the search call")
pages = [(T_HOTEL, "Brooklands Hotel Weybridge - any good? : r/surrey"), (T_TOWN, "Where to stay in Weybridge : r/surrey"), (T_NEG, "Brooklands Hotel experience : r/uktravel"), (T_NOT_THREAD, "r/surrey"), (OTHER, "Brooklands Hotel")]
cites = [(T_HOTEL, "Brooklands Hotel", "Stayed at the Brooklands Hotel, lovely staff and a really clean, comfortable room. Would recommend."),
         (T_NEG, "Brooklands Hotel", "The Brooklands Hotel was awful: dirty bathroom, noisy at night, avoid.")]
fake = Fake([resp(pages, cites)])
r = rc.run(HOTEL, CITY, client=fake)
tool = fake.calls[0]["tools"][0]
check("one call, with the web-search tool restricted to reddit.com and a small search limit", len(fake.calls) == 1 and tool["name"] == "web_search" and tool["allowed_domains"] == ["reddit.com"] and tool["max_uses"] == rc.MAX_SEARCHES)
check("it returns the pages found and a cost, and the model's own words are not used", r["status"] == "ok" and len(r["pages"]) == 5 and 0 < r["cost_usd"] < 0.30, r["cost_usd"])
check("no key and no client: not run, with the reason; no town: not run", rc.run(HOTEL, CITY)["status"] == "not_configured" and rc.run(HOTEL, "", api_key="k")["status"] == "not_configured")


class Boom:
    messages = None

    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise RuntimeError("down")


check("a failed call is reported as unavailable, never raised", rc.run(HOTEL, CITY, client=Boom())["status"] == "unavailable")

print("3. the section")
sec = rc.build(r, None, HOTEL, CITY)
ht = {t["url"]: t for t in sec["hotel_threads"]}
check("threads that name the hotel are separated from town threads, and a subreddit page or another site is not a thread",
      set(ht) == {T_HOTEL, T_NEG} and [t["url"] for t in sec["town_threads"]] == [T_TOWN], (set(ht), [t["url"] for t in sec["town_threads"]]))
check("tone is read only for threads that name the hotel, from the quoted passage", ht[T_HOTEL]["tone"] == "positive" and ht[T_NEG]["tone"] == "critical" and sec["town_threads"][0]["tone"] is None)
check("the summary counts them and names the subreddits", sec["summary"]["hotel_mentioned"] is True and sec["summary"]["hotel_threads"] == 2 and sec["summary"]["town_threads"] == 1 and "surrey" in sec["summary"]["subreddits"])
none_found = rc.build(resp([(T_TOWN, "Where to stay in Weybridge : r/surrey")]) and rc._envelope("ok", pages=[{"url": T_TOWN, "title": "Where to stay in Weybridge : r/surrey", "cited": False, "cited_text": ""}]), None, HOTEL, CITY)
check("a search that found no thread about the hotel says False (not found in these searches), not that nobody talks about it", none_found["summary"]["hotel_mentioned"] is False)
no_search = rc.build(rc._envelope("not_configured", "No key."), None, HOTEL, CITY)
check("with no search and no AI answers the section is not run, with the reason, and claims nothing", no_search["status"] == "not_configured" and no_search["summary"]["hotel_mentioned"] is None and no_search["reason"] == "No key.")

print("4. the sampled AI answers")
ai = {"items": [{"answer": "a", "domains": ["reddit.com", "booking.com"], "pages": [{"url": T_TOWN, "title": "Where to stay in Weybridge : r/surrey", "cited": True, "cited_text": "The Ship is nice"}]},
                {"answer": "b", "domains": ["booking.com"], "pages": []}, {"answer": "c", "domains": ["old.reddit.com"], "pages": []}, {"answer": "", "domains": ["reddit.com"], "pages": []}]}
only_ai = rc.build(rc._envelope("not_configured", "No key."), ai, HOTEL, CITY)
check("without a search, the AI answers alone still show how many cited Reddit and which thread (answers with no text are not counted)",
      only_ai["status"] == "ok" and only_ai["summary"]["ai_cited_reddit"] == 2 and only_ai["summary"]["ai_answers"] == 3 and len(only_ai["ai_threads"]) == 1 and only_ai["summary"]["hotel_mentioned"] is None)

print("5. the advice")
full = rc.build(rc._envelope("ok", pages=[{"url": T_TOWN, "title": "Where to stay in Weybridge : r/surrey", "cited": False, "cited_text": ""}]), ai, HOTEL, CITY)
codes = {x["id"] for x in advice._from_reddit(full)}
check("not named in where-to-stay threads, and Reddit cited without the hotel, are both raised", codes == {"RD1", "RD3"}, codes)
codes2 = {x["id"] for x in advice._from_reddit(sec)}
check("a critical thread about the hotel raises RD2, and being named raises no 'not named' finding", "RD2" in codes2 and "RD1" not in codes2, codes2)
recs = advice._from_reddit(full) + advice._from_reddit(sec)
text = " ".join(x["action"] + x["finding"] for x in recs).lower()
check("the advice is to take part openly and never to seed posts, buy votes, or ask for removal; the finding says it is a sample of public search",
      "openly" in text and "do not post as a guest" in text and "ask anyone to vote" in text and "sample" in text)
check("nothing is raised when the section did not run", advice._from_reddit(no_search) == [] and advice._from_reddit(None) == [])

print("6. the report")
import copy
import json
import os

import htmlst
import report_view
import ui_consult
from htmlst import st

html_card = htmlst.build(lambda: ui_consult.reddit_card(sec))
check("the Reddit tab shows the counts, the threads with their tone and links, the honesty caption and the how-to-take-part advice",
      "Threads naming the hotel" in html_card and "r/surrey" in html_card and "critical" in html_card and 'href="https://www.reddit.com/r/surrey/comments/abc123' in html_card
      and "cannot be read directly" in html_card and "never post as a guest" in html_card.lower())
html_off = htmlst.build(lambda: ui_consult.reddit_card(no_search))
check("when it did not run the tab says why instead of showing zeros", "No key." in html_off and "Threads naming the hotel" not in html_off)
REP = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
REP["reddit"] = full
page = report_view.render(copy.deepcopy(REP), token="t" * 32)
check("a whole report renders with a Reddit sub-tab", ">Reddit<" in page and "Reddit threads the AI assistant cited" in page)
import dashboard_view
ov = dashboard_view.overview(copy.deepcopy(REP), None)
check("the overview raises the Reddit finding", "cited Reddit in 2 of 3 sampled answers" in ov, ov[:0])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
