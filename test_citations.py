"""
Offline tests for three things: what the assistant cites when it names the hotel (ranked by how often each source came up), what that says about booking direct against through an agent and the specific facts to put on
the hotel's own pages, and open forum conversations (Reddit and similar) the hotel can honestly join; plus the more specific, feature-based questions that give the hotel's own market a fair test. No network.
Run: python test_citations.py
"""
import contextlib
import copy
import io
import json
import os
import re
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import advice
import ai_niche
import ai_questions as aq
import citations as ct
import forums as fm

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
OWN = "marriott.com"
BOOK = "https://www.booking.com/hotel/fr/paris-marriott-opera-ambassador.html"
EXP = "https://www.expedia.com/Paris-Hotels-Paris-Marriott-Opera-Ambassador.h1234.Hotel-Information"
OWNP = "https://www.marriott.com/en-us/hotels/paroa-paris-marriott-opera-ambassador-hotel/overview/"
TRIP = "https://www.tripadvisor.com/Hotel_Review-g187147-Paris.html"
BLOG = "https://nomadicmatt.com/travel-blogs/best-hotels-paris/"


def pg(url, cited=True, text="", title="t"):
    return {"url": url, "title": title, "cited": cited, "cited_text": text}


def item(i, mentioned, pages, kind="niche"):
    return {"id": i, "qid": i[:4], "kind": kind, "text": "q " + i, "answer": "a", "mentioned": mentioned, "pages": pages, "domains": [], "recommended": mentioned}


items = [
    item("n1", True, [pg(BOOK, True, "Rated 8.6/10 from 1,240 reviews. Free cancellation. The Palais Garnier is a 4 minute walk."), pg(OWNP, True, "Our hotel"), pg(TRIP, False)]),
    item("n2", True, [pg(BOOK, True, "Rated 8.6/10 from 1,240 reviews. Breakfast from €32. Parking nearby."), pg(EXP, True, "From €240 per night"), pg(BLOG, True, "A top pick")]),
    item("n3", True, [pg(BOOK, True, "Free cancellation."), pg(TRIP, True, "reviews")]),
    item("n4", False, [pg(BOOK, True, "x"), pg(BLOG, True, "y")]),
    item("n5", False, [pg(TRIP, True, "z")]),
    item("d1", True, [pg(BOOK, True, "Rated 8.6/10"), pg(OWNP, True, "Official")], kind="direct"),
]
print("1. the ranking when the hotel is named")
r = ct.ranking(items, OWN, ())
check("it ranks the sources of the answers that NAMED the hotel (3 of 5), most-cited first", r["basis"] == "named" and r["answers"] == 3 and r["rows"][0]["domain"] == "booking.com" and r["rows"][0]["came_up"] == 3 and r["rows"][0]["cited"] == 3, str(r["rows"][:3]))
rows = {x["domain"]: x for x in r["rows"]}
check("each row says how many of those answers it came up in, as a share, and how often it came up where the hotel was NOT named", rows["booking.com"]["of"] == 3 and rows["booking.com"]["share_pct"] == 100 and rows["booking.com"]["elsewhere"] == 1 and rows["tripadvisor.com"]["elsewhere"] == 1 and rows["tripadvisor.com"]["cited"] == 1 and rows["tripadvisor.com"]["came_up"] == 2)
check("the hotel's own website is recognised and counted: 1 of 3 answers", rows["marriott.com"]["is_own"] and rows["marriott.com"]["came_up"] == 1 and r["own_answers"] == 1)
check("booking and comparison sites (the agents that charge commission) are counted: 3 of 3 answers", r["ota_answers"] == 3 and r["ota_share_pct"] == 100 and r["own_share_pct"] == 33)
check("by kind: the answers each KIND of source appeared in", {k["kind"]: k["answers"] for k in r["by_kind"]}["Booking and comparison site"] == 3 and {k["kind"]: k["answers"] for k in r["by_kind"]}["Review site"] == 2)
check("the pages cited are listed under their source with the passage quoted", rows["booking.com"]["pages"][0]["url"] == BOOK and "Rated 8.6" in rows["booking.com"]["pages"][0]["passage"])
check("what is cited when the assistant is asked about the hotel by name is ranked separately", r["direct"]["answers"] == 1 and r["direct"]["rows"][0]["domain"] in ("booking.com", "marriott.com"))
none_named = ct.ranking([i for i in items if not i["mentioned"]], OWN, ())
check("when the hotel is never named the same ranking is given for all answers and says so (basis 'all')", none_named["basis"] == "all" and none_named["rows"] and none_named["answers"] == 2)
check("with nothing to judge the basis is 'none'", ct.ranking([], OWN, ())["basis"] == "none")

print("2. what the assistant took from the agents that the hotel's own pages do not state")
OWNPAGES = [{"url": OWNP, "text": "Welcome to the Paris Marriott Opera Ambassador Hotel. Our 4-star hotel has meeting rooms and a restaurant. Breakfast is served from 6:30. " * 3},
            {"url": OWNP + "rooms/", "text": "Rooms and suites with city views. Complimentary Wi-Fi. " * 3}, {"url": OWNP + "dining/", "text": "Brasserie Sixtine serves lunch and dinner. " * 3}]
d = ct.direct_findings(items, OWNPAGES, OWN, ())
facts = {f["key"]: f for f in d["facts"]}
check("it finds the facts quoted from booking sites: a rating, a price, a cancellation rule, a distance, breakfast, parking", {"rating", "price", "cancellation", "location", "breakfast", "parking"} <= set(facts), list(facts))
check("breakfast is on the hotel's own pages; the rating, the price and the cancellation rule are not", facts["breakfast"]["on_own_site"] and not facts["rating"]["on_own_site"] and not facts["price"]["on_own_site"] and not facts["cancellation"]["on_own_site"], {k: v["on_own_site"] for k, v in facts.items()})
check("the gaps are exactly the quoted facts the own pages do not state, each with the agent's words and page", {"rating", "price", "cancellation"} <= set(d["gaps"]) and "breakfast" not in d["gaps"] and facts["rating"]["from_agents"][0]["domain"] == "booking.com", str(d["gaps"]))
check("no reason to book direct is stated on the own pages read", d["book_direct"]["stated"] is False and d["own_pages_read"] == 3)
d2 = ct.direct_findings(items, OWNPAGES + [{"url": OWNP + "offers/", "text": "Book direct and get our best rate guarantee plus free breakfast."}], OWN, ())
check("a book-direct promise on the own site is found", d2["book_direct"]["stated"] and "best rate" in d2["book_direct"]["evidence"]["snippet"].lower())
check("only passages from booking and comparison sites count (a blog's sentence does not)", all(a["domain"] in ("booking.com", "expedia.com") for f in d["facts"] for a in f["from_agents"]))

print("3. the recommendations")
cit = {**r, "direct_findings": d}
recs = advice._from_direct(cit)
ids = [x["id"] for x in recs]
ds1 = next(x for x in recs if x["id"] == "DS1")
check("agents ahead of the own site: a recommendation with the counts in its title, and one for the missing book-direct reason", ids == ["DS1", "DS2"] and "booking sites in 3 of 3" in ds1["title"] and "own site in 1" in ds1["title"], ids)
check("it names the specific facts to put on the hotel's own pages, and where", all(w in ds1["action"] for w in ("a guest rating or score", "a price or rate", "a cancellation or flexibility rule")) and "page" in ds1["action"], ds1["action"][:300])
check("the evidence quotes the assistant's source and passage, and counts the own site", any("booking.com came up in 3 of 3" in e["snippet"] for e in ds1["evidence"]) and any("took a guest rating" in e["snippet"] for e in ds1["evidence"]) and ds1["evidence"][-1]["snippet"].startswith("The hotel's own website came up in 1"))
txt = json.dumps(recs).lower()
check("it promises nothing: no 'will reduce', no commission saving, no 'more bookings'", not any(w in txt for w in ("will reduce", "will increase", "save you", "more bookings", "guarantee more", "fewer commissions will")) and "does not promise" in txt)
check("when the own site is cited as often as the agents, there is nothing to raise; nor when the hotel was never named", advice._from_direct({**cit, "own_answers": 3}) == [advice._from_direct({**cit, "own_answers": 3})[0]] if False else [x["id"] for x in advice._from_direct({**cit, "own_answers": 3})] == ["DS2"] and advice._from_direct(none_named) == [])
check("these are opportunities, ranked by the model, marked as an inference", all(x["kind_hint"] == "opportunity" and x["confidence"] == advice.INFER for x in recs))

print("4. open forum conversations")
P = lambda url, title, cited_text="", age="": {"url": url, "title": title, "cited": False, "cited_text": cited_text, "age": age}      # noqa: E731
pages = [P("https://www.reddit.com/r/ParisTravelGuide/comments/1abc123/where_to_stay_near_the_opera_garnier_for_a_work_trip/", "Where to stay near the Opera Garnier for a work trip?", "Looking for a 4 star hotel near Opera Garnier with meeting space", "2 weeks ago"),
         P("https://www.reddit.com/r/travel/comments/1old999/best_hotel_in_paris_for_a_week/", "Best hotel in Paris for a week?", "any recommendations for paris", "9 months ago"),
         P("https://www.quora.com/Where-should-I-stay-in-Paris-near-Opera-for-a-business-trip", "Where should I stay in Paris near Opera for a business trip?", "recommend a hotel near the Palais Garnier", "March 3, 2020"),
         P("https://www.tripadvisor.com/ShowTopic-g187147-i4-k1-Where_to_stay.html", "Where to stay in Paris", "recommend", "1 week ago"),
         P("https://www.reddit.com/r/paris/", "Paris subreddit", "", ""),
         P("https://www.reddit.com/r/AskReddit/comments/1xyz222/favourite_pizza_toppings/", "Favourite pizza toppings in Paris", "pizza in paris", "1 week ago"),
         P("https://www.reddit.com/r/hotels/comments/1hot555/paris_marriott_opera_ambassador_review/", "Paris Marriott Opera Ambassador: honest thoughts", "We stayed at the Paris Marriott Opera Ambassador Hotel and", "3 weeks ago")]
cited = ["https://www.reddit.com/r/ParisTravelGuide/comments/1abc123/where_to_stay_near_the_opera_garnier_for_a_work_trip/?utm=x"]
ops, closed = fm.judge(pages, [], HOTEL, CITY, ["Paris", "Palais Garnier", "Opera Garnier"], cited)
by_url = {o["url"]: o for o in ops + closed}
check("a recent Reddit thread asking for a recommendation near the hotel's anchor is an open opportunity, with its forum, title, age and the place it matches", any(o["forum"] == "r/ParisTravelGuide" and o["can_comment"] == "open" and "garnier" in " ".join(o["matches"]) for o in ops), str([(o["forum"], o["can_comment"]) for o in ops]))
check("an AI answer that cited it (the link differs only by tracking) is flagged, and it ranks first", ops[0]["cited_by_ai"] and ops[0]["forum"] == "r/ParisTravelGuide")
check("a Reddit thread older than six months is listed apart as closed: archived, no new comments", any("old999" in o["url"] and o["can_comment"] == "closed" for o in closed) and all("old999" not in o["url"] for o in ops))
check("Quora is included, and a thread with an old date is 'check' rather than assumed open or closed", any("quora.com" in o["url"] for o in ops + closed) and next(o for o in ops if "quora" in o["url"])["can_comment"] in ("check", "likely open"))
check("Tripadvisor, a bare subreddit page and a thread that neither asks for a hotel nor names it are never listed", not any("tripadvisor" in o["url"] or o["url"].endswith("/r/paris/") or "pizza" in o["url"] for o in ops + closed))
check("a thread that already names the hotel is kept and marked", any(o["about_hotel"] for o in ops))
check("Reddit's six-month rule and the 'check' case are stated in words", "six months" in fm.can_comment("reddit.com", None)[1] and fm.can_comment("reddit.com", 8.0)[0] == "closed" and fm.can_comment("reddit.com", 1.0)[0] == "open")


class Fake:
    def __init__(self):
        self.messages, self.tools = self, []

    def create(self, **kw):
        self.tools.append(kw["tools"][0])
        blocks = [NS(type="web_search_tool_result", content=[NS(url=p["url"], title=p["title"], page_age=p["age"]) for p in pages[:3]]),
                  NS(type="text", text="I found these threads: ... (model words are discarded)", citations=[NS(url=pages[0]["url"], title=pages[0]["title"], cited_text=pages[0]["cited_text"])])]
        return NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=900, output_tokens=120, server_tool_use=NS(web_search_requests=3)))


fk = Fake()
res = fm.run(HOTEL, CITY, ["Which 4-star hotels near Palais Garnier suit a business trip?"], ["Palais Garnier"], client=fk, model="claude-haiku-5-5")
check("the search is limited to the open forums and never includes Tripadvisor", fk.tools[0]["allowed_domains"] == fm.FORUMS and "tripadvisor.com" not in fk.tools[0]["allowed_domains"])
check("the result carries threads that were in the search results, the forums searched and the cost; the model's own words are not used", res["status"] == "ok" and res["opportunities"] and res["cost_usd"] > 0 and "tripadvisor" not in " ".join(res["forums"]).lower() and "model words" not in json.dumps(res), str(res)[:200])
check("without a key it is not configured and nothing is searched", fm.run(HOTEL, CITY, [])["status"] == "not_configured")
fr_recs = advice._from_forums({"opportunities": ops, "closed": closed})
check("one recommendation, with the links, that tells the hotel to answer as itself, once, and never to post as a guest or offer anything in return",
      len(fr_recs) == 1 and fr_recs[0]["id"] == "FM1" and any("reddit.com" in e["url"] for e in fr_recs[0]["evidence"]) and "say you work for the hotel" in fr_recs[0]["action"].lower() and "never post as a guest" in fr_recs[0]["action"].lower())
check("no recommendation when only closed or no threads were found", advice._from_forums({"opportunities": [], "closed": closed}) == [] and advice._from_forums(None) == [])

import ranking
_rk = ranking.annotate(copy.deepcopy(recs) + copy.deepcopy(fr_recs), [])
check("all three clear the plan's cutoff (28) so they reach the action plan, and none is called 'Confirmed'", all(x["value"] >= 28 for x in _rk) and all(x["confidence_label"] != "Confirmed" for x in _rk), [(x["id"], x["value"], x["confidence_label"]) for x in _rk])

print("5. more specific questions, each true of the hotel")
LEVEL = lambda *keys: [{"key": k, "label": k, "level": "strong"} for k in keys]      # noqa: E731
PAGES = [{"url": "https://www.marriott.com/hotels/paroa/overview/", "text": "Paris Marriott Opera Ambassador Hotel is a 4-star hotel in the heart of Paris. Meeting rooms host 120 delegates. Parking. Fitness centre. Spa pool."}]
prof = ai_niche.profile(HOTEL, CITY, [], None, PAGES, LEVEL("meeting_rooms", "parking", "gym", "spa", "pool", "restaurant", "pets"), LEVEL("meetings", "business"), classes=["business", "city_centre"])
anch = [{"name": "Palais Garnier", "kind": "attraction", "km": 0.18, "views": 52000, "source": "Wikipedia"}, {"name": "Louvre Museum", "kind": "attraction", "distance": "15 minutes", "km": 1.2, "source": "the hotel's own pages"}]
b = aq.build(prof, HOTEL, CITY, anch, base_repeats=2)
texts = [q["text"] for q in b["questions"]]
check("each facility the pages show strongly becomes a question anchored on the landmark: meeting rooms, parking, a gym, dogs", all(any(w in t for t in texts) for w in ("meeting rooms for a team offsite", "have parking for guests", "have a gym", "welcome dogs")) and all("near Palais Garnier" in t for t in texts if "welcome dogs" in t), texts)
check("a spa, a pool and a good restaurant are NOT asked for a business hotel just because the pages mention them (the kind of hotel does not support it)", not any(w in " ".join(texts) for w in ("have a spa", "swimming pool", "good restaurant")))
check("there are more core questions than before and they stay under the cap; none names the hotel", len([q for q in b["questions"] if q["priority"] == "core"]) <= aq.MAX_CORE and len(b["questions"]) >= 8 and not any("marriott" in t.lower() for t in texts), len(b["questions"]))
check("none is so exact that only this hotel could fit: at most the town or a place, the star level and ONE facility", all(sum(w in t for w in ("meeting rooms", "parking", "gym", "dogs")) <= 1 for t in texts))
check("the facts a question rests on list the strong facilities", any(f["kind"] == "feature" and "meeting rooms" in f["text"] for f in b["facts"]))

print("6. in the report")
import report_view
src = open("test_ai_gap.py", encoding="utf8").read()
src = src[:src.index('print("5. recommendations")')]
ns = {"__name__": "t"}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(src, "test_ai_gap.py", "exec"), ns)
REP = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
REP["ai_gap"], REP["citations"], REP["forums"] = ns["res"], cit, {"status": "ok", "reason": "", "opportunities": ops, "closed": closed, "forums": ["Reddit", "Quora"], "searches": 3, "cost_usd": 0.03}
html = report_view.render(copy.deepcopy(REP), token="t" * 32)
ai = re.search(r'<div class="tab-panel[^"]*" id="tab-ai">(.*?)(?=<div class="tab-panel|$)', html, re.S).group(1)
glance = ai[:ai.index("<details")]
check("the AI tab shows, before any section, what is cited when the hotel is named: bars by kind and the ranked sources", "When the assistant names the hotel, what does it cite?" in glance and "booking.com" in glance and "Came up in" in glance and "3 of 3 answers" in glance)
check("it says plainly how the own site compares with the agents", "own website came up in 1 of 3 answers" in glance and "booking and comparison sites in 3" in glance)
check("the conversations to join are a section with the links and whether each can still be commented on", "Conversations you can join (" in ai and "ParisTravelGuide" in ai and "Can you comment?" in ai and "How to take part without it backfiring" in ai and "reddit.com/r/ParisTravelGuide" in ai)
check("the coverage figure is shown against the aim of around 30%", "Coverage: named in" in glance and "around 30%" in glance)
check("the full ranking, the facts quoted from booking sites and the by-name ranking are one click away", "The full citation ranking" in ai and "Facts the assistant quoted from booking sites" in ai)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
