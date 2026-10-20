"""
Offline tests for ai_gap.py: who the assistant named instead of the hotel, which pages it cited and whether they mention the hotel, rivals' verified websites and the evidence comparison, and the
recommendations that follow. A Paris hotel near the Opera is the fixture. No network: the assistant, the page reader and the fetcher are fakes.
Run: python test_ai_gap.py
"""
import json
from types import SimpleNamespace as NS

import advice
import ai_gap as g
import ai_sample

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
Q1 = "Which luxury hotels near the Opera Garnier in Paris are worth the splurge?"
Q2 = "Where should I stay in Paris for a first visit?"


def item(i, qid, kind, text, answer, pages, mentioned=False):
    return {"id": i, "qid": qid, "kind": kind, "text": text, "answer": answer, "mentioned": mentioned, "recommended": mentioned, "position": 1 if mentioned else None, "domains": [], "pages": pages,
            "angle": "Luxury" if kind == "niche" else None, "why": "Hotel level: luxury." if kind == "niche" else None, "repeat": 1, "repeats": 2, "platform": "Claude (x) with web search"}


ART = "https://www.telegraph.co.uk/travel/best-luxury-hotels-near-opera-garnier-paris/"
SPONS = "https://www.parisluxe-guide.com/sponsored/best-hotels-opera/"
ROBOT = "https://www.condenast-example.com/hotels-opera"
OTA = "https://www.booking.com/district/fr/paris/opera.html"
TRIP = "https://www.tripadvisor.com/Hotels-g187147-Paris.html"
INCL = "https://www.timeout.com/paris/hotels/best-hotels-in-paris"
pg = lambda u, t, cited=True: {"url": u, "title": t, "cited": cited, "cited_text": "Our pick of luxury hotels near the Opera: Hotel A, Hotel B." if cited else ""}      # noqa: E731
P1 = [pg(ART, "The best luxury hotels near Opera Garnier, Paris"), pg(OTA, "Hotels near Opera Garnier"), pg(TRIP, "Paris hotels"), pg(SPONS, "Best hotels Opera (sponsored)"), pg(ROBOT, "Hotels Opera")]
items = [item("n1", "niche_luxury", "niche", Q1, "1. Hotel Alpha Opera 2. Maison Beta Paris 3. Hotel Gamma", P1), item("n1#2", "niche_luxury", "niche", Q1, "1. Maison Beta Paris 2. Hotel Alpha Opera", P1),
         item("g1", "best", "generic", Q2, "1. Hotel Alpha Opera 2. Paris Marriott Opera Ambassador Hotel", [pg(INCL, "Best hotels in Paris")], True), item("g1#2", "best", "generic", Q2, "1. Hotel Alpha Opera", [pg(INCL, "Best hotels in Paris")]),
         item("d1", "about", "direct", "Tell me about " + HOTEL, "A hotel near the Opera.", [])]
ex = {"n1": [{"name": "Hotel Alpha Opera", "rank": 1, "sentiment": "positive", "reason": "steps from the Opera with a rooftop spa", "rating": None},
             {"name": "Maison Beta Paris", "rank": 2, "sentiment": "positive", "reason": "boutique luxury, 5-star", "rating": "9.1 on Booking.com"}, {"name": "Hotel Gamma", "rank": 3, "sentiment": "neutral", "reason": "classic grand hotel", "rating": None}],
      "n1#2": [{"name": "Maison Beta Paris", "rank": 1, "sentiment": "positive", "reason": "", "rating": None}, {"name": "Hotel Alpha Opera", "rank": 2, "sentiment": "positive", "reason": "", "rating": None}],
      "g1": [{"name": "Hotel Alpha Opera", "rank": 1, "sentiment": "positive", "reason": "central", "rating": None}, {"name": "Paris Marriott Opera Ambassador Hotel", "rank": 2, "sentiment": "neutral", "reason": "", "rating": None}],
      "g1#2": [{"name": "Hotel Alpha Opera", "rank": 1, "sentiment": "positive", "reason": "", "rating": None}]}
AI = {"status": "ok", "model": "claude-haiku-5-5", "items": items, "summary": ai_sample.summarise(items), "run_at": "2026-10-20"}
INS = {"status": "ok", "extracted_answers": ex}

print("1. the gap, question by question")
ms = g.markets(items, ex, HOTEL)
by = {m["qid"]: m for m in ms}
check("the direct 'about the hotel' question is not a market", "about" not in by and len(ms) == 2)
n = by["niche_luxury"]
check("never named: status, counts and a gap", n["status"] == "not_named" and n["named"] == 0 and n["of"] == 2 and n["gap"], str(n))
check("rivals are counted as 'answers naming them, of the answers given', most-named first (ties by place in the list)", [(r["name"], r["answers"], r["of"]) for r in n["rivals"]] == [("Hotel Alpha Opera", 2, 2), ("Maison Beta Paris", 2, 2), ("Hotel Gamma", 1, 2)], str(n["rivals"]))
check("the assistant's own reason and rating are kept, attributed to it", n["rivals"][0]["reasons"] == ["steps from the Opera with a rooftop spa"] and n["rivals"][1]["ratings"] == ["9.1 on Booking.com"])
check("'consistent' only when every answer named the same leader and there were two or more", n["consistent"])
c = by["best"]
check("named in one of two answers: 'sometimes', still a gap because a rival led, and not 'consistent'", c["status"] == "sometimes" and c["gap"] and not c["consistent"], str(c["status"]))
check("the hotel itself is never listed among the rivals", all(g.ai_sample.mentioned(r["name"], HOTEL) is False for m in ms for r in m["rivals"]))
one = g.markets([items[0]], {"n1": ex["n1"]}, HOTEL)[0]
check("with a single answer it is never called consistent", not one["consistent"])

print("2. the pages it cited")
pages = g.cited_pages(items, [n, c], "marriott.com", ())
kinds = {p["domain"]: p["kind"] for p in pages}
check("pages are classed (travel media, booking platform, review site, other)", kinds["telegraph.co.uk"] == "Travel media" and kinds["booking.com"] == "Booking and comparison site" and kinds["tripadvisor.com"] == "Review site", str(kinds))
LIST = ("The best luxury hotels near Opera Garnier. Hotel Alpha Opera is our top pick, a short walk from the Opera with a rooftop spa. Maison Beta Paris is a boutique five-star. Hotel Gamma is a grand classic. " * 3)
TEXTS = {ART: LIST, SPONS: "Sponsored content. " + LIST, INCL: LIST + " Paris Marriott Opera Ambassador Hotel is a good business option."}
reads = []


def reader(url):
    reads.append(url)
    if url == ROBOT:
        return {"fetch": {"ok": False, "robots_blocked": True, "error": "robots"}, "page": {}}
    if url in TEXTS:
        return {"fetch": {"ok": True}, "page": {"text": TEXTS[url], "title": "t " + url, "publisher": "Pub", "published": "2026-09-01", "sponsored_cue": url == SPONS, "press_release_cue": False}}
    return {"fetch": {"ok": False, "error": "HTTP 404"}, "page": {}}


rivals_all = ["Hotel Alpha Opera", "Maison Beta Paris", "Hotel Gamma"]
pages_all = g.cited_pages(items, [n, c], "marriott.com", ())
arts = g.articles(pages_all, rivals_all, HOTEL, CITY, reader, 20)
ab = {a["url"]: a for a in arts}
check("review sites and booking platforms are listed but never read", ab[OTA]["read"] == "not_read" and ab[TRIP]["read"] == "not_read" and OTA not in reads and TRIP not in reads, str(reads))
check("a page whose robots.txt forbids reading is not read, and says so", ab[ROBOT]["read"] == "robots" and "robots.txt" in ab[ROBOT]["note"])
a = ab[ART]
check("an editorial list that names rivals and omits the hotel is an outreach opportunity, with the rival sentence as evidence", a["read"] == "ok" and a["opportunity"] and not a["hotel_in"] and a["rivals_in"][:2] == ["Hotel Alpha Opera", "Maison Beta Paris"] and "Alpha" in a["rival_sentence"], str(a))
check("a sponsored page is not an opportunity", not ab[SPONS]["opportunity"] and ab[SPONS]["sponsored"] and "sponsored" in ab[SPONS]["note"])
check("a list that already includes the hotel is not an opportunity (and says the assistant had it available)", ab[INCL]["hotel_in"] and not ab[INCL]["opportunity"])
check("its publication date is kept when the page states it", a["published"] == "2026-09-01")

print("3. rivals' websites are verified before use, and compared")
HOME = {"https://alpha-opera.example/": ("Hotel Alpha Opera Paris", "Hotel Alpha Opera is a five-star hotel in Paris with a rooftop spa, a pool, a restaurant and meeting rooms for 200 guests. Spa treatments, sauna and steam room. " * 4),
        "https://maisonbeta.example/": ("Maison Beta", "A boutique hotel in Lyon with a restaurant. " * 12)}


def fetch(url):
    url = url if url.count("/") >= 3 else url + "/"
    root = url if url in HOME else next((u for u in HOME if url.startswith(u)), None)
    if not root:
        return {"ok": False, "url": url, "text": "", "links": []}
    t, body = HOME[root]
    return {"ok": True, "url": url, "title": t, "h1": [t], "text": body, "links": [], "signals": {}}


osm = {"hotels": [{"name": "Hotel Alpha Opera", "km": 0.2, "tags": {"website": "alpha-opera.example", "tourism": "hotel"}}]}
f1 = g.find_rival_site("Hotel Alpha Opera", CITY, osm, pages_all, fetch, lambda u: True)
check("a website from the map is used once its homepage names the hotel and the town", f1["verified"] and f1["via"] == "the map's website entry" and "names the hotel and the town" in f1["why"], str(f1))
osm2 = {"hotels": [{"name": "Maison Beta Paris", "km": 0.4, "tags": {"website": "maisonbeta.example", "tourism": "hotel"}}]}
f2 = g.find_rival_site("Maison Beta Paris", CITY, osm2, pages_all, fetch, lambda u: True)
check("a website whose homepage does not place the hotel in the town is rejected, with the reason", not f2["verified"] and f2["url"] is None and "does not clearly name this hotel in this town" in f2["why"], str(f2))
f3 = g.find_rival_site("Hotel Alpha Opera", CITY, osm, pages_all, fetch, lambda u: False)
check("a site whose robots.txt forbids reading is not read", not f3["verified"] and "robots.txt" in f3["why"])


class Fake:
    def __init__(self):
        self.messages, self.calls = self, 0

    def create(self, **kw):
        self.calls += 1
        txt = "https://alpha-opera.example/"
        return NS(content=[NS(type="text", text=txt, citations=None)], stop_reason="end_turn", usage=NS(input_tokens=400, output_tokens=30, server_tool_use=NS(web_search_requests=1)))


fk = Fake()
f4 = g.find_rival_site("Hotel Alpha Opera", CITY, None, pages_all, fetch, lambda u: True, client=fk, model="claude-haiku-5-5", budget_left=0.2)
check("with no map entry or cited domain, one web search finds a candidate, which is verified; its cost is counted", f4["verified"] and f4["via"] == "a web search" and fk.calls == 1 and f4["cost"] > 0, str(f4))
fk2 = Fake()
f5 = g.find_rival_site("Hotel Alpha Opera", CITY, None, pages_all, fetch, lambda u: True, client=fk2, model="claude-haiku-5-5", budget_left=0.0)
check("no search is made once the budget is used", fk2.calls == 0 and not f5["verified"])

OWN = [{"url": "https://www.marriott.com/hotels/travel/parom-paris-marriott-opera-ambassador-hotel/", "title": HOTEL, "h1": [HOTEL], "ok": True, "links": [],
        "text": "Paris Marriott Opera Ambassador Hotel is a 4-star hotel near the Opera. Our restaurant serves breakfast. " * 8}]
comp = g.compare(OWN, OWN[0]["url"], HOTEL, [{"name": "Hotel Alpha Opera", "url": "https://alpha-opera.example/"}], fetch, lambda u: True)
check("the rival's pages are read and profiled like the hotel's own", comp["rivals"] and comp["rivals"][0]["name"] == "Hotel Alpha Opera" and "spa" in comp["rivals"][0]["facilities"], str(comp["rivals"]))
check("a facility the rival describes in detail and the hotel does not is reported as an observed difference", any("Hotel Alpha Opera" in d and "spa" in d.lower() and "do not mention it" in d for d in comp["differences"]), str(comp["differences"]))

print("4. the whole run, and what it will and will not say")
res = g.run(AI, INS, {"hotel": HOTEL, "city": CITY, "own_domain": "marriott.com", "brand_domains": (), "own_pages": OWN, "base": OWN[0]["url"], "osm_ctx": osm}, client=Fake(), reader=reader, fetch=fetch, polite_allowed=lambda u: True, model="claude-haiku-5-5")
check("the envelope is ok, names the gap markets and the outreach page, and is JSON-serialisable", res["status"] == "ok" and set(res["gaps"]) == {"niche_luxury", "best"} and ART in res["opportunities"] and json.dumps(res, default=str))
check("only verified rivals are compared, the unverified one says why", [r["name"] for r in res["comparison"]["rivals"]] == ["Hotel Alpha Opera"] and any(not r["verified"] and r["why"] for r in res["rivals"] if r["name"] != "Hotel Alpha Opera"), str(res["rivals"]))
obs = res["observations"]["niche_luxury"]
check("observations name their source: the assistant's words, the cited pages that name a rival and not the hotel, and the facility difference", {o["kind"] for o in obs} >= {"assistant", "source", "facility"}, str(obs))
txt = json.dumps(res).lower()
check("nothing claims a cause or promises a result", not any(w in txt for w in ("because the assistant", "will increase", "guarantee that", "the reason the assistant chose")) and "observations, never proven causes" in " ".join(res["limits"]).lower() or "never proven causes" in " ".join(res["limits"]))
check("the limits are stated", len(res["limits"]) == 4 and "One assistant" in res["limits"][0])
none_gap = g.run({**AI, "items": [item("a", "best", "generic", Q2, "1. " + HOTEL, [], True)]}, {"extracted_answers": {"a": [{"name": HOTEL, "rank": 1, "sentiment": "positive", "reason": "", "rating": None}]}},
                 {"hotel": HOTEL, "city": CITY}, reader=reader, fetch=fetch)
check("when the hotel is always named there is no gap and nothing is fetched", none_gap["status"] == "ok" and not none_gap["gaps"] and "no gap" in none_gap["reason"])
check("without the extraction there is an honest 'unavailable'", g.run(AI, {}, {"hotel": HOTEL, "city": CITY})["status"] == "unavailable")

print("5. recommendations")
recs = advice._from_ai_gap(res)
ids = [r["id"] for r in recs]
inv = next(r for r in recs if r["id"] == "AG-niche_luxury")
check("an investigation for the consistent gap and an outreach for the named article, nothing generic", "AG-niche_luxury" in ids and "AG-OUT-1" in ids and "AG-best" in ids, str(ids))
check("the investigation names the rivals and the counts, in plain words", "Hotel Alpha Opera" in inv["title"] and "Hotel Alpha Opera in 2 of 2" in inv["finding"] and "Every answer named the same leading hotel" in inv["finding"] and "One assistant on one day" in inv["finding"])
check("it is an opportunity-style investigation, an experimental inference, and never says content will fix it", inv["kind_hint"] == "opportunity" and inv["confidence"] == advice.EXPER and "add content" not in inv["action"].lower() and "decide" in inv["action"].lower())
check("it is medium priority when consistent and low when not", inv["priority"] == "medium" and next(r for r in recs if r["id"] == "AG-best")["priority"] == "low")
out = next(r for r in recs if r["id"] == "AG-OUT-1")
check("the outreach names the page, quotes what it says about the rivals, and warns against paid placement", ART in out["evidence"][0]["url"] and "Alpha" in out["evidence"][0]["snippet"] and "Do not pay" in out["action"] and out["team"] == "PR", str(out["action"])[:120])
generic = [{"id": "AI1", "source": "ai"}, {"id": "AI4", "source": "ai"}, {"id": "X-S-editorial_outreach", "source": "intel"}, {"id": "X-S-otas_missing", "source": "intel"}]
kept = [r for r in generic if r["id"] not in ("AI1", "AI4") and not (r["id"].startswith("X-S-editorial_outreach") and any(x["id"].startswith("AG-OUT") for x in recs))]
check("the general 'not named in a sample' notes and the generic outreach are replaced when specific ones exist", [r["id"] for r in kept] == ["X-S-otas_missing"])
check("no recommendation when the analysis is unavailable", advice._from_ai_gap({"status": "unavailable"}) == [] and advice._from_ai_gap(None) == [])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
