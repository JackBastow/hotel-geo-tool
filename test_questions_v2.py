"""
Offline tests for the question engine (anchors.py, ai_questions.py, and the tier gates in ai_niche): questions rest on verified facts and a real place the hotel is close to, a 4-star hotel is never asked a
'luxury splurge' question, proposals written by Claude are checked by code, and the hotel's core market is asked more often than the rest. Fake web, fake Claude: no network.
Run: python test_questions_v2.py
"""
import json
from types import SimpleNamespace as NS

import ai_niche
import ai_questions as aq
import ai_sample
import anchors as an

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
TEXT = ("Paris Marriott Opera Ambassador Hotel is a 4-star hotel in the heart of Paris. The Louvre Museum is a 15 minute walk from the hotel. Our meeting rooms host up to 120 delegates for conferences and "
        "business events. Enjoy our fitness centre. Luxury service is our promise. Brasserie Sixtine serves breakfast and dinner.")
PAGES = [{"url": "https://www.marriott.com/hotels/paroa/overview/", "text": TEXT}]


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


def web(url, headers=None, timeout=10):
    if "nominatim" in url:
        if "Springfield" in url:
            return Resp([{"lat": "39.8", "lon": "-89.6", "display_name": "Some Hotel, Springfield, USA", "address": {"city": "Springfield"}}])
        return Resp([{"lat": "48.8712", "lon": "2.3318", "display_name": "Paris Marriott Opera Ambassador Hotel, Paris, France", "address": {"city": "Paris"}}])
    if "geosearch" in url:
        return Resp({"query": {"geosearch": [{"title": "Palais Garnier", "dist": 180}, {"title": "9th arrondissement of Paris", "dist": 300}, {"title": "Opéra (Paris Métro)", "dist": 120},
                                                {"title": "Galeries Lafayette", "dist": 450}, {"title": "Opéra-Comique", "dist": 700}, {"title": "Some Obscure Courtyard", "dist": 90}]}})
    if "pageviews" in url:
        return Resp({"query": {"pages": {"1": {"title": "Palais Garnier", "pageviews": {"d1": 30000, "d2": 22000}}, "2": {"title": "Galeries Lafayette", "pageviews": {"d1": 9000}},
                                         "3": {"title": "Opéra-Comique", "pageviews": {"d1": 3000}}, "4": {"title": "Some Obscure Courtyard", "pageviews": {"d1": 40}}}}})
    return Resp({}, 404)


print("1. anchors")
own = an.from_pages(PAGES, HOTEL)
check("a named attraction with a stated distance on the hotel's own pages is an anchor, with a rough distance in km", own and own[0]["name"] == "Louvre Museum" and 1.0 <= own[0]["km"] <= 1.4 and own[0]["source"] == "the hotel's own pages", str(own))
check("distances are read from the hotel's words ('800 m', '1.2 km', '5 minute drive')", an.km_from_text("800 m") == 0.8 and an.km_from_text("1.2 km") == 1.2 and an.km_from_text("5 minute drive") == 2.5 and an.km_from_text("nothing") is None)
wk = an.wikipedia_nearby(48.87, 2.33, web)
names = [w["name"] for w in wk]
check("Wikipedia's places near the hotel are ranked by how many people read them, with districts, metro stops and obscure pages removed", names == ["Palais Garnier", "Galeries Lafayette", "Opéra-Comique"], names)
check("the town the geocoder returns must be the hotel's town", an.geocode(HOTEL, CITY, web) == (48.8712, 2.3318) and an.geocode(HOTEL, "Springfield", lambda u, **k: web(u.replace("Paris", "Springfield"))) is not None and an.geocode(HOTEL, "Lyon", web) is None)
found = an.find(PAGES, HOTEL, CITY, None, {"lat": None, "lon": None}, fetch=web)
check("coordinates come from a search when the pages were read as plain text, and say so", found["coords"] == (48.8712, 2.3318) and "Nominatim" in found["coords_source"], str(found["coords"]))
check("a famous landmark right beside the hotel comes first; the hotel's own named places and the rest follow", found["anchors"][0]["name"] == "Palais Garnier" and "Louvre Museum" in [a["name"] for a in found["anchors"]], [a["name"] for a in found["anchors"]])
check("nothing breaks when the web is down", an.find(PAGES, HOTEL, CITY, None, None, fetch=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))["anchors"][0]["name"] == "Louvre Museum")

print("2. the facts and the questions built on them")
LEVEL = lambda *keys: [{"key": k, "label": k, "level": "strong"} for k in keys]      # noqa: E731
prof = ai_niche.profile(HOTEL, CITY, [], None, PAGES, LEVEL("meeting_rooms", "gym"), LEVEL("meetings", "business", "luxury", "city_break"), classes=["business", "city_centre"])
check("(setup) a 4-star business, city-centre hotel", prof["tier"]["key"] == "upscale" and prof["stars"] == 4)
check("a luxury question is skipped for an upscale hotel, with the reason", "luxury" not in [a["key"] for a in prof["audiences"]] and any(s["key"] == "luxury" and "palace hotels" in s["why"] for s in prof["skipped"]), str(prof["skipped"]))
b = aq.build(prof, HOTEL, CITY, found["anchors"], base_repeats=2)
texts = [q["text"] for q in b["questions"]]
check("the price question is anchored on the landmark and carries the star level", any("4-star" in t and "near Palais Garnier" in t and "quality for the price" in t for t in texts), texts)
check("the business question is anchored too, and asks for what a business traveller needs", any("near Palais Garnier" in t and "business trip" in t and "meeting space" in t for t in texts), texts)
check("a city-centre hotel gets a weekend question around its landmark", any("weekend near Palais Garnier" in t for t in texts), texts)
check("no luxury, palace or splurge question for a 4-star hotel, and no town-wide price question once an anchored one exists", not any(ai_questions_word in t.lower() for t in texts for ai_questions_word in ("luxury", "splurge", "palace")) and sum("quality for the price" in t for t in texts) == 1, texts)
check("no question names the hotel, and every question says why it was asked", all("marriott" not in t.lower() for t in texts) and all(q["why"] for q in b["questions"]))
core = [q for q in b["questions"] if q["priority"] == "core"]
sec = [q for q in b["questions"] if q["priority"] != "core"]
check("the hotel's own market is asked more often than the rest (3 against 2) and the totals are capped", core and all(q["repeats"] == 3 for q in core) and all(q["repeats"] == 2 for q in sec) and len(core) <= aq.MAX_CORE and len(sec) <= aq.MAX_SECONDARY, [(q["angle"], q["repeats"]) for q in b["questions"]])
fl = {f["kind"] for f in b["facts"]}
check("the facts it rests on include the price level, the kind of hotel and the anchors, each with its evidence", {"tier", "class", "anchor"} <= fl and any("Palais Garnier" in f["text"] and "Wikipedia" in f["text"] for f in b["facts"]), str(b["facts"]))
nb = aq.build(prof, HOTEL, CITY, [], base_repeats=2)
check("with no anchor the earlier planner still produces questions", len(nb["questions"]) >= 1 and nb["cost_usd"] == 0.0, str(nb["questions"]))

print("3. proposals written by Claude are checked by code")
GOOD = "Which 4-star hotels near Palais Garnier have meeting rooms for a team offsite in Paris?"
props = [{"text": GOOD, "facts": ["f1", "f3"]},
         {"text": "Is Paris Marriott Opera Ambassador Hotel good for a business trip to Paris?", "facts": ["f1"]},
         {"text": "Which luxury palace hotels in Paris are worth the splurge for a special occasion?", "facts": ["f1"]},
         {"text": "Which Paris hotels have a spa and a pool for a relaxing weekend away?", "facts": ["f1"]},
         {"text": "What are good hotels for a business trip with a big budget?", "facts": ["f1"]},
         {"text": "Which 4-star hotels near Palais Garnier have meeting rooms for a team offsite in Paris today?", "facts": ["f1"]},
         {"text": "Best 4-star hotel in Paris near Palais Garnier for a quiet stay?", "facts": ["f99"]}]
kept, rej = aq.validate(props, b["facts"], HOTEL, CITY, ["Palais Garnier"], "upscale", existing=[])
why = {r["text"][:20]: r["why"] for r in rej}
check("the sound proposal is kept, labelled as proposed, with the facts it rests on", [k["text"] for k in kept] == [GOOD] and kept[0]["source"] == "proposed" and "Written from" in kept[0]["why"], str(kept))
check("one that names the hotel, one with luxury wording, one that brings in a spa the facts do not support, one with no place, a near-duplicate and one citing an unknown fact are all rejected, each with its reason",
      "names the hotel" in why["Is Paris Marriott Opera"[:20]] and "luxury wording" in why["Which luxury palace hotels"[:20]] and "do not support" in why["Which Paris hotels have a spa"[:20]] and "neither the town" in why["What are good hotels for a business"[:20]]
      and "repeats another question" in why["Which 4-star hotels near Palais"[:20]] and "no listed fact" in why["Best 4-star hotel in Paris"[:20]], str(why))


class FakeClaude:
    def __init__(self, text):
        self.messages, self.text, self.calls = self, text, []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="text", text=self.text, citations=None)], stop_reason="end_turn", usage=NS(input_tokens=700, output_tokens=200, server_tool_use=None))


fc = FakeClaude(json.dumps({"prompts": props}))
b2 = aq.build(prof, HOTEL, CITY, found["anchors"], client=fc, model="claude-haiku-5-5", base_repeats=2)
check("through build(): the proposal is added as a core question, the rest rejected, the call has no search tool and costs a fraction of a cent", GOOD in [q["text"] for q in b2["questions"]] and len(b2["rejected"]) == 6 and "tools" not in fc.calls[0] and 0 < b2["cost_usd"] < 0.01, str(b2["rejected"]))
check("an unreadable or failed Claude reply changes nothing", aq.build(prof, HOTEL, CITY, found["anchors"], client=FakeClaude("sorry"), base_repeats=2)["questions"] == b["questions"])

print("4. repeats are honoured when the questions are asked")
ex = ai_sample.expand([{"id": "a", "kind": "niche", "text": "x?", "repeats": 3}, {"id": "b", "kind": "niche", "text": "y?"}, {"id": "c", "kind": "direct", "text": "z?"}], repeats=2)
check("a question's own count wins, the default applies otherwise, and direct questions are asked once", [(e["qid"], e["repeat"], e["repeats"]) for e in ex] == [("a", 1, 3), ("a", 2, 3), ("a", 3, 3), ("b", 1, 2), ("b", 2, 2), ("c", 1, 1)], str([(e["id"], e["repeats"]) for e in ex]))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
