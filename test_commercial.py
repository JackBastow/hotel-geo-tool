"""
Commercial priorities (commercial.py): the report leads with the few plays most likely to win bookings, from the hotel's own lost searches, and the generic findings fold into them or drop to low
(Paris Marriott review, Nov 2026). Offline; the evidence below has the shape of the live Marriott check (run 48).
Run: python test_commercial.py
"""
import copy
import sys
import warnings

warnings.filterwarnings("ignore")
import advice
import commercial
import ranking
import report_model

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


UP = {"key": "upscale"}
LUX = {"key": "luxury"}
PAL = {"key": "palace"}


def rival(name, answers, tier, reason):
    return {"name": name, "answers": answers, "of": 3, "reasons": [reason], "themes": {}, "tier": tier}


def market(qid, q, angle, named, of, rivals, kind="niche"):
    return {"qid": qid, "kind": kind, "question": q, "angle": angle, "named": named, "of": of, "status": "not_named" if named == 0 else "sometimes", "rivals": rivals, "consistent": True}


OYSTER = "https://www.oyster.com/paris/hotels/roundups/best-luxury-hotels-in-9th-arrondissement-opera-garnier-paris/"
GAP = {
    "status": "ok", "hotel_tier": "upscale", "chain": True,
    "markets": [
        market("best", "What are the best hotels in Paris?", None, 0, 2, [rival("Hôtel Eiffel Blomet", 2, {"key": None}, "Best value with heated pool")], kind="generic"),
        market("niche_anchor_business0", "Which upscale hotels near Palais Garnier are best for a business trip, with reliable Wi-Fi and meeting space?", "Business travel", 0, 3,
               [rival("InterContinental Paris Le Grand", 3, LUX, "Meeting space steps from the Opéra"), rival("Sofitel Le Scribe Paris Opéra", 2, UP, "Business centre and quiet rooms"),
                rival("Ritz Paris", 1, PAL, "Iconic palace")]),
        market("niche_feat_meeting_rooms", "Which 4-star hotels near Palais Garnier have meeting rooms for a team offsite?", "Meetings and events", 0, 3,
               [rival("InterContinental Paris Le Grand", 3, LUX, "Ballrooms and meeting rooms")]),
        market("niche_anchor_value", "Which upscale hotels near Palais Garnier give the best quality for the price?", "Price level", 0, 3,
               [rival("Hotel Banke Opera", 2, UP, "Good value for a 4-star"), rival("Sofitel Le Scribe Paris Opéra", 1, UP, "Strong reviews")]),
        market("niche_anchor_break0", "Where should I stay for a weekend near Palais Garnier, in an upscale hotel within walking distance?", "City breaks", 2, 3,
               [rival("Sofitel Le Scribe Paris Opéra", 1, UP, "Two minutes from the Opéra")]),
    ],
    "criteria": {
        "niche_anchor_business0": [{"theme": "meetings", "label": "meeting space", "count": 3, "hotel": {"state": "strong", "url": "https://h/events/", "snippet": "Nine meeting rooms"}}],
        "niche_feat_meeting_rooms": [{"theme": "meetings", "label": "meeting space", "count": 2, "hotel": {"state": "strong"}}],
        "niche_anchor_value": [{"theme": "value", "label": "good value", "count": 2, "hotel": {"state": "not_found"}}],
    },
    "articles": [
        {"url": OYSTER, "title": "The Best Luxury Hotels in 9th Arrondissement (Opera Garnier), Paris", "domain": "oyster.com", "kind": "Other", "cited": 3,
         "questions": ["niche_anchor_business0", "niche_anchor_value", "niche_anchor_break0"], "rivals_in": ["Sofitel Le Scribe Paris Opéra", "Hotel de Nell", "Maison Souquet"], "hotel_in": False,
         "sponsored": False, "rival_sentence": "Sofitel Le Scribe Paris Opéra: a historic 5-star hotel steps from the Opéra"},
        {"url": "https://sponsored.example/opera-hotels", "title": "Paid: top Opera hotels", "domain": "sponsored.example", "cited": 4, "questions": ["niche_anchor_business0", "niche_anchor_value"],
         "rivals_in": ["Hotel Banke Opera"], "hotel_in": False, "sponsored": True},
        {"url": "https://once.example/x", "title": "One mention", "domain": "once.example", "cited": 1, "questions": ["niche_anchor_value"], "rivals_in": ["Hotel Banke Opera"], "hotel_in": False, "sponsored": False},
        {"url": "https://generic.example/paris", "title": "Best hotels in Paris", "domain": "generic.example", "cited": 5, "questions": ["best"], "rivals_in": ["Hôtel Eiffel Blomet"], "hotel_in": False},
    ],
}


def rec(rid, source, title, tag="", ev_url=""):
    return advice._rec(rid, "authority", title, "f", "w", [{"url": ev_url, "snippet": "s"}] if ev_url else [], "Do the thing.", "medium", "medium", confidence=advice.INFER, source=source, tag=tag)


RECS = [rec("AG-niche_anchor_business0", "ai", "Not named when asked business", tag="AG1"), rec("AG-best", "ai", "Not named when asked best hotels in Paris", tag="AG2"),
        rec("AG-OUT-1", "ai", "Ask oyster.com whether...", tag="AGO1", ev_url=OYSTER),
        rec("DE-business", "differentiation", "Position the hotel for business travellers and conference enquiries", tag="DE"),
        rec("DE-family", "differentiation", "Position the hotel for families", tag="DE"),
        rec("L1", "location", "Say how far the hotel is from Musée Grévin"), rec("L2", "location", "Say how far the hotel is from Palais Garnier"),
        rec("Q1", "questions", "Make sure your website answers: cancellation")]

recs = copy.deepcopy(RECS)
commercial.apply(recs, GAP, advice._rec, {"INFER": advice.INFER, "EXPER": advice.EXPER})
ranking.annotate(recs, [])
ids = [r["id"] for r in recs]
by = {r["id"]: r for r in recs}

print("1. a page the AI used for several of the hotel's own searches")
src = [r for r in recs if r["id"].startswith("CP-S")]
check("Oyster's Opéra list becomes a play: cited 3 times, for 2 searches the hotel lost (the third it wins is not counted), naming its rivals, not the hotel", len(src) == 1 and "oyster.com" in src[0]["title"] and "2 of the hotel's own searches" in src[0]["title"],
      [r["title"] for r in src])
check("on repeated evidence it is 'Likely' (not a one-answer lead)", src and src[0]["confidence_label"] == "Likely", src and src[0]["confidence_label"])
check("a sponsored page, a page cited once, and a page used only for a town-wide search are not plays", not any(d in " ".join(r["title"] for r in src) for d in ("sponsored.example", "once.example", "generic.example")))
check("a chain is pointed to the brand's PR team", src and "brand's PR" in src[0]["action"])

print("2. the searches the hotel lost, grouped by what the traveller wanted")
srch = [r for r in recs if r["id"].startswith("CP-M")]
titles = " | ".join(r["title"] for r in srch)
check("business-trip and meetings searches each become a play naming the hotels of its level that won", "business trips" in titles and "InterContinental Paris Le Grand" in titles, titles)
check("a palace hotel (another category) is not named as who it competes with", "Ritz" not in titles + " ".join(r["finding"] for r in srch))
check("a search where the hotel IS named sometimes (2 of 3) is not called lost", not any("weekend" in r["title"] for r in srch), titles)
biz = next((r for r in srch if "business trips" in r["title"]), {})
check("where the hotel's pages already state what rivals were praised for (meeting space), the play says the gap is in the sources, and points to them",
      "already state meeting space" in biz.get("action", "") and OYSTER in biz.get("action", ""), biz.get("action"))
val = next((r for r in srch if "value" in r["title"]), {})
check("where they do not (good value), it says so, and only 'where the hotel genuinely offers it'", "do not state good value" in val.get("action", "") and "genuinely offers" in val.get("action", ""), val.get("action"))

print("3. the generic findings fold in or drop")
check("the per-search 'Not named when asked' for a search in a play folds into it", "AG-niche_anchor_business0" not in ids)
check("a town-wide 'best hotels in Paris' finding stays as context, at low priority", by.get("AG-best", {}).get("priority") == "low", by.get("AG-best", {}).get("priority"))
check("the same Oyster page is not suggested twice", "AG-OUT-1" not in ids)
check("'Position the hotel for business travellers' folds into the business play", "DE-business" not in ids and "DE-business" in biz.get("folded", []))
check("'Position the hotel for families', with no lost search behind it, is low priority", by.get("DE-family", {}).get("priority") == "low", by.get("DE-family", {}).get("priority"))
check("'Say how far from Musée Grévin' (no search is about it) is low; 'from Palais Garnier' (the searches are) is not",
      by["L1"]["priority"] == "low" and by["L2"]["priority"] != "low", (by["L1"]["priority"], by["L2"]["priority"]))

print("4. the report leads with them")
cons = {"recommendations": recs, "top_actions": [r["id"] for r in ranking.top_actions(recs)]}
top = report_model.priorities_of(cons, 5)
check("'What to do first' starts with the commercial plays", top and top[0].startswith("CP-"), top)
check("each play carries its evidence: the searches, the answers, the rivals", all(r.get("evidence") and r.get("play") for r in src + srch))
check("without an AI test nothing is added", commercial.apply(copy.deepcopy(RECS), {"status": "unavailable"}, advice._rec, {"INFER": advice.INFER, "EXPER": advice.EXPER}) == copy.deepcopy(RECS))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
