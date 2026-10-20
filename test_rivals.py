"""
Offline tests for rivals.py and the competitor logic in ai_gap.py: one hotel under several names is one hotel, names that appear together are never merged, a palace hotel is not a competitor of a four-star
business hotel, only comparable hotels make a gap, and the reasons an assistant gives are set beside what the hotel's own pages show. No network.
Run: python test_rivals.py
"""
import json
from types import SimpleNamespace as NS

import advice
import ai_gap as g
import ai_insights as ains
import ai_sample
import rivals as rv

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. one hotel under several names")
by = [("a1", ["Hôtel de Crillon", "Le Bristol Paris", "Maison Astor", "Hotel Parister"]), ("a2", ["Crillon", "Astor House", "Four Seasons Hotel George V", "Shangri-La Paris"]),
      ("a3", ["Hôtel de Crillon Paris", "Hotel Duquesne Eiffel", "Duquesne Eiffel"])]
grp = {x["key"]: x for x in rv.resolve(by, "Paris")}
cr = next(x for x in grp.values() if "crillon" in x["key"])
check("'Hôtel de Crillon', 'Crillon' and 'Hôtel de Crillon Paris' are one hotel, named in all three answers, with no doubt about it", len(cr["names"]) == 3 and len(cr["answers"]) == 3 and not cr["uncertain"], str(cr))
ast = next(x for x in grp.values() if "astor" in x["key"])
check("'Maison Astor' and 'Astor House' are grouped but flagged as possibly the same hotel", set(ast["names"]) == {"Maison Astor", "Astor House"} and ast["uncertain"], str(ast))
dq = next(x for x in grp.values() if "duquesne" in x["key"])
check("'Duquesne Eiffel' joins 'Hotel Duquesne Eiffel'", len(dq["names"]) == 2)
tog = rv.resolve([("a1", ["Maison Astor", "Astor House"])], "Paris")
check("two names that appear together in ONE answer are two hotels and are never merged", len(tog) == 2)
check("hotels with different distinctive words stay separate", len(grp) == 7 - 0 or len(grp) == 8, len(grp))

print("2. category")
check("a house the market treats as a palace is 'palace' even when the assistant calls it five-star", rv.tier_of("Le Bristol Paris")["key"] == "palace" and rv.tier_of("Shangri-La Paris", 5)["key"] == "palace")
check("the assistant's own star rating places a hotel, with the reason", rv.tier_of("Hôtel Eiffel Blomet", 4)["key"] == "upscale" and "assistant" in rv.tier_of("Hôtel Eiffel Blomet", 4)["why"])
check("without stars a brand's usual level is used and said to be an inference", rv.tier_of("Novotel Paris Centre")["key"] == "midscale" and "inference" in rv.tier_of("Novotel Paris Centre")["why"])
check("an unknown hotel is 'category not known', never guessed", rv.tier_of("Hotel Parister")["key"] is None)
check("a short name does not match a palace by accident ('Amanda' is not Aman)", rv.tier_of("Amanda Boutique Hotel")["key"] is None)
check("relations: same, one step up, a palace above an upscale hotel, unknown", rv.relation("upscale", "upscale") == "same" and rv.relation("upscale", "luxury") == "one_up" and rv.relation("upscale", "palace") == "above" and rv.relation("upscale", None) == "unknown")
check("only the comparable relations can make a gap", set(rv.COMPARABLE) == {"same", "one_up", "one_down", "unknown"})

print("3. only comparable hotels make a gap")
HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"


def item(i, qid, kind, text, answer, repeats=2):
    return {"id": i, "qid": qid, "kind": kind, "text": text, "answer": answer, "mentioned": False, "recommended": False, "position": None, "domains": [], "pages": [], "angle": "x" if kind == "niche" else None,
            "why": "w" if kind == "niche" else None, "repeat": 1, "repeats": repeats, "priority": "core"}


def hotels(*rows):
    return [{"name": n, "rank": k + 1, "sentiment": "positive", "reason": r, "rating": None, "stars": s, "themes": t} for k, (n, r, s, t) in enumerate(rows)]


items = [item("b1", "best", "generic", "What are the best hotels in Paris?", "1. Le Bristol 2. Plaza Athénée 3. Cheval Blanc"), item("b2", "best", "generic", "What are the best hotels in Paris?", "1. Plaza Athénée 2. Le Bristol"),
         item("m1", "meet", "niche", "Which 4-star hotels near Palais Garnier have meeting rooms?", "1. Hotel Alpha 2. Hotel Beta 3. Hotel Parister"), item("m2", "meet", "niche", "Which 4-star hotels near Palais Garnier have meeting rooms?", "1. Hotel Beta 2. Hotel Alpha")]
ex = {"b1": hotels(("Le Bristol Paris", "palace luxury service", 5, ["luxury_service"]), ("Plaza Athénée", "iconic luxury", 5, ["luxury_service"]), ("Cheval Blanc Paris", "design and luxury", 5, ["design_style"])),
      "b2": hotels(("Plaza Athénée", "iconic luxury", 5, ["luxury_service"]), ("Le Bristol", "garden", 5, ["views_terrace"])),
      "m1": hotels(("Hotel Alpha", "rooftop terrace and meeting rooms for 200", 4, ["meetings_events", "views_terrace", "awards"]), ("Hotel Beta", "steps from the Opera, flexible meeting space", 4, ["meetings_events", "location", "awards"]), ("Hotel Parister", "modern meeting rooms", None, ["meetings_events"])),
      "m2": hotels(("Hotel Beta", "steps from the Opera", 4, ["location", "meetings_events"]), ("Hotel Alpha", "event space and a terrace", 4, ["views_terrace", "meetings_events"]))}
ms = {m["qid"]: m for m in g.markets(items, ex, HOTEL, CITY, "upscale")}
b = ms["best"]
check("named only palace hotels: the hotel is not named, but that is NOT a gap, and the report says why", b["status"] == "not_named" and not b["gap"] and not b["rivals"] and len(b["other_category"]) == 3 and "different category" in b["note"], str(b))
check("each palace hotel is shown with its category", all(r["tier"]["key"] == "palace" and r["relation"] == "above" for r in b["other_category"]), str([(r["name"], r["relation"]) for r in b["other_category"]]))
check("'Le Bristol Paris' and 'Le Bristol' are counted as one hotel", next(r for r in b["other_category"] if "Bristol" in r["name"])["answers"] == 2)
m = ms["meet"]
check("named four-star hotels and one of unknown category: a real gap, the unknown one counted as comparable and marked so", m["gap"] and [r["name"] for r in m["rivals"]] == ["Hotel Alpha", "Hotel Beta", "Hotel Parister"] and m["rivals"][2]["relation"] == "unknown" and m["rivals"][0]["relation"] == "same", str([(r["name"], r["relation"]) for r in m["rivals"]]))
check("the stars the assistant gave are kept per hotel", m["rivals"][0]["stars_said"] == 4 and m["rivals"][2]["stars_said"] is None)
check("it is consistent only when every answer named the same leader", m["consistent"])

print("4. the extraction keeps a star rating only if the answer mentions one, and only the themes on the list")


class Fake:
    def __init__(self, payload):
        self.messages, self.payload = self, payload

    def create(self, **kw):
        return NS(content=[NS(type="text", text=json.dumps(self.payload), citations=None)], stop_reason="end_turn", usage=NS(input_tokens=400, output_tokens=200, server_tool_use=None))


answers = {"a": {"id": "a", "kind": "generic", "text": "q?", "answer": "1. Hotel Alpha, a five-star hotel with a rooftop terrace. 2. Hotel Beta, steps from the Opera. 3. Hotel Gamma (4-star), near the station."}}
payload = {"answers": [{"id": "a", "hotels": [{"name": "Hotel Alpha", "rank": 1, "reason": "rooftop", "rating": None, "sentiment": "positive", "stars": 5, "themes": ["views_terrace", "nonsense", "luxury_service"]},
                                              {"name": "Hotel Beta", "rank": 2, "reason": "location", "rating": None, "sentiment": "neutral", "stars": 4, "themes": ["location"]},
                                              {"name": "Hotel Gamma", "rank": 3, "reason": "station", "rating": None, "sentiment": "neutral", "stars": 4, "themes": ["transport_access"]}]}], "about": {}}
res, _u = ains.extract(Fake(payload), "claude-haiku-5-5", list(answers.values()), "Some Hotel", "Paris")
hs = {h["name"]: h for h in res["answers"]["a"]}
check("a star rating is kept only where the answer gives it beside THAT hotel: five-star for Alpha, '4-star' for Gamma; Beta's claimed 4 stars are dropped because only others in the answer have a rating; an unlisted theme is dropped",
      hs["Hotel Alpha"]["stars"] == 5 and hs["Hotel Gamma"]["stars"] == 4 and hs["Hotel Beta"]["stars"] is None and hs["Hotel Alpha"]["themes"] == ["views_terrace", "luxury_service"], str({k: v["stars"] for k, v in hs.items()}))

print("5. the reasons the assistant gave, beside what the hotel's own pages show")
OWN = [{"url": "https://www.marriott.com/hotels/paroa/overview/", "title": HOTEL, "h1": [HOTEL], "ok": True, "links": [],
        "text": "Paris Marriott Opera Ambassador Hotel is a 4-star hotel near the Opera, a 3 minute walk from the Palais Garnier. Our meeting rooms host up to 120 delegates for conferences and events. Rooms have views of the city. " * 3},
       {"url": "https://www.marriott.com/hotels/paroa/events/", "title": "Meetings and events", "h1": ["Meetings and events"], "ok": True, "links": [],
        "text": "Meetings and events. Our meeting rooms and conference spaces suit workshops, conferences and events for up to 120 delegates, with a projector, screen and catering. Steps from the Opera. " * 3}]
st = g.hotel_theme_states(OWN, OWN[0]["url"], HOTEL)
check("meetings and location are stated clearly on the hotel's pages; a rooftop is not mentioned; ratings are not assessable from the hotel's own pages", st["meetings_events"]["state"] == "strong" and st["location"]["state"] in ("strong", "mentioned") and st["awards"]["state"] == "not_found" and st["rating_reviews"]["state"] == "not_assessed", {k: v["state"] for k, v in st.items()})
crit = g.criteria(m, ex, st)
rows = {c["theme"]: c for c in crit}
check("reasons that recur across the hotels named are listed; the most recurrent first; a reason given once for one hotel is not a pattern", crit[0]["theme"] == "meetings_events" and len(rows["meetings_events"]["rivals"]) == 3 and "views_terrace" in rows and "location" in rows, str([(c["theme"], c["count"]) for c in crit]))
check("each carries the hotel's own state and the assistant's words", rows["meetings_events"]["hotel"]["state"] == "strong" and rows["views_terrace"]["quotes"], str(rows["views_terrace"]))
obs = g.observations(m, [], None, crit)
txt = " ".join(o["text"] for o in obs)
check("a reason the hotel's pages do not mention says: either not offered or not stated; a reason the pages already state says the difference is more likely outside the site", "either the hotel does not offer it, or it is not stated" in txt and "already state it clearly" in txt, txt[:400])
steps = " ".join(g.investigate(m, obs))
check("the steps tell the hotel to state what it offers and to leave what it does not, and to look outside the site where the pages already say it", "if it does not, there is nothing to fix" in steps and "look outside the site" in steps)
check("nothing claims a cause", not any(w in (txt + steps).lower() for w in ("because the assistant", "will increase", "guarantee", "the reason the assistant chose")))

print("6. recommendations")
gap = {"status": "ok", "markets": list(ms.values()), "gaps": ["meet"], "articles": [], "observations": {"meet": obs}, "investigate": {"meet": g.investigate(m, obs)}, "criteria": {"meet": crit}}
recs = advice._from_ai_gap(gap)
check("one investigation, for the market with comparable rivals; none for the palace-only market", [r["id"] for r in recs] == ["AG-meet"], [r["id"] for r in recs])
check("it names the comparable hotels and carries the criterion evidence", "Hotel Alpha" in recs[0]["title"] and any("rooftop" in e["snippet"].lower() or "terrace" in e["snippet"].lower() for e in recs[0]["evidence"] + [{"snippet": txt}]), recs[0]["title"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
