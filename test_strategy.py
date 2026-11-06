"""
Offline test: the hotel differentiation engine (verified strengths, advantages over comparable hotels, under-explained strengths, the traveller searches where they could matter), why rivals are recommended instead, the
sites to get listed on by kind of site, and the specific prompts built from verified attributes. Every claim carries its label; nothing is claimed without evidence. No network. Run: python test_strategy.py
"""
import copy
import json
import os
import re
import tempfile
import warnings

warnings.filterwarnings("ignore")
import advice
import audit_service
import backend
import differentiation
import headline
import query_matrix
import ranking
import report_pdf
import rival_analysis
import server
import source_actions

headline.attach = lambda r: None
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


def market(qid, q, named, of, rivals):
    return {"qid": qid, "kind": "niche", "question": q, "angle": "", "named": named, "of": of, "status": "not_named" if not named else "named", "gap": not named, "consistent": True, "priority": "core",
            "best_position": None, "answer_ids": [], "note": "", "other_category": [], "rivals": [{"name": n, "answers": a, "of": of, "relation": "same", "themes": ["location", "business"], "reasons": [r] if r else []} for n, a, r in rivals]}


REP = {"meta": {"hotel": "Hotel Opera", "city": "Paris", "base": "https://www.hotel-opera.com/"},
       "question_plan": {"anchors": [{"name": "Galeries Lafayette", "kind": "attraction", "km": 0.15, "views": 9000, "source": "Wikipedia"}, {"name": "Palais Garnier", "kind": "attraction", "km": 0.3, "views": 30000, "source": "Wikipedia"}]},
       "ai_sample": {"market": {"tier": {"key": "upscale", "label": "upscale"}, "stars": 4}},
       "consultant": {"features": [{"key": "meeting_rooms", "label": "Meeting rooms", "level": "strong", "pages": 4}, {"key": "gym", "label": "Gym", "level": "strong", "pages": 3}, {"key": "spa", "label": "Spa", "level": "some", "pages": 1},
                                   {"key": "pool", "label": "Pool", "level": "none", "pages": 0}],
                      "intents": [{"key": "business", "level": "strong"}],
                      "facility_depth": [{"key": "events", "label": "Meeting and event space", "found": [{"key": "capacity", "label": "x", "quote": "seats 180 guests", "match": "180 guests"}, {"key": "size", "label": "y", "quote": "q", "match": "240 m2"}],
                                          "missing": [{"label": "Catering"}], "total": 8, "thin": False, "quote": "q", "disputed": False},
                                         {"key": "restaurant", "label": "Restaurant and bar", "found": [{"key": "cuisine", "label": "x", "quote": "q", "match": "m"}], "missing": [{"label": "Opening hours"}, {"label": "Menu"}], "total": 6, "thin": True, "quote": "q", "disputed": False}],
                      "traveller": {"segments": [{"label": "Business travellers", "relevance": "core"}]}, "hotel_class": {"classes": [{"key": "business", "label": "Business hotel", "reasons": []}]},
                      "opportunities": [], "recommendations": []},
       "ai_insights": {"perception": {"site_emphasises": ["Weddings"], "not_in_assistant_description": ["Weddings"]},
                       "pages": [{"url": "https://www.parisjetaime.com/hotels", "domain": "parisjetaime.com", "title": "Hotels", "cited": 16, "names_hotel": False, "names_competitor": "Hotel A", "own_site": False},
                                 {"url": "https://www.cvent.com/venues/paris", "domain": "cvent.com", "title": "Venues", "cited": 11, "names_hotel": False, "names_competitor": "Hotel B", "own_site": False},
                                 {"url": "https://www.tripadvisor.com/x", "domain": "tripadvisor.com", "title": "Reviews", "cited": 27, "names_hotel": True, "names_competitor": "Hotel A", "own_site": False},
                                 {"url": "https://www.hotel-opera.com/", "domain": "hotel-opera.com", "title": "Official", "cited": 3, "names_hotel": True, "names_competitor": None, "own_site": True},
                                 {"url": "https://www.timeout.com/paris/best-hotels", "domain": "timeout.com", "title": "Best hotels", "cited": 9, "names_hotel": False, "names_competitor": "Hotel A", "own_site": False}]},
       "ai_gap": {"status": "ok", "markets": [market("q1", "Which upscale hotels near Palais Garnier are best for a business trip with meeting space?", 0, 4, [("Hotel A", 4, "convenient for business travellers with meeting facilities"), ("Hotel B", 2, None)]),
                                              market("q2", "Which hotels in Paris have meeting rooms for a team workshop?", 1, 4, [("Hotel A", 3, "close to the Opera and transport"), ("Hotel D", 1, None)])],
                  "comparison": {"own": {"levels": {"meeting_rooms": "strong", "gym": "strong", "spa": "some", "pool": "none"}},
                                 "rivals": [{"name": "Hotel A", "pages_read": 2, "levels": {"meeting_rooms": "none", "gym": "strong", "spa": "none", "pool": "none"}, "facilities": []},
                                            {"name": "Hotel B", "pages_read": 1, "levels": {"meeting_rooms": "some", "gym": "none", "spa": "none", "pool": "none"}, "facilities": []},
                                            {"name": "Hotel C", "pages_read": 0, "levels": {"meeting_rooms": "none"}, "facilities": []}]},
                  "criteria": {"q1": [{"theme": "location", "label": "Location", "rivals": ["Hotel A"], "hotel": {"state": "strong"}}, {"theme": "business", "label": "Business facilities", "rivals": ["Hotel A"], "hotel": {"state": "mentioned"}}]},
                  "articles": [{"url": "https://www.parisjetaime.com/hotels", "domain": "parisjetaime.com", "title": "Hotels", "cited": 16, "questions": ["q1"], "hotel_in": None, "rivals_in": ["Hotel A"], "contact_url": "https://www.parisjetaime.com/contact", "affiliate": False, "sponsored": False},
                               {"url": "https://www.timeout.com/paris/best-hotels", "domain": "timeout.com", "title": "Best hotels", "cited": 9, "questions": ["q1"], "hotel_in": None, "rivals_in": ["Hotel A"], "contact_url": "", "affiliate": True, "sponsored": False}]}}

print("1. what makes the hotel different")
d = differentiation.build(REP)
check("a verified strength needs a facility stated clearly on several pages: meeting rooms and the gym, not the spa (one page) or the pool", [s["key"] for s in d["strengths"]] == ["meeting_rooms", "gym"] and "stated on 4 pages" in d["strengths"][0]["proof"] and d["strengths"][0]["confidence"] == "Confirmed", d["strengths"])
adv = {a["key"]: a for a in d["advantages"]}
check("an advantage is a facility the hotel states and comparable hotels' pages (that were read) do not: meeting rooms and the spa over Hotel A, the gym only over Hotel B (Hotel A states one too); a hotel whose pages were not read is not counted", set(adv) == {"meeting_rooms", "spa", "gym"} and adv["gym"]["lacking"] == ["Hotel B"] and "Hotel C" not in adv["meeting_rooms"]["lacking"], {k: v["lacking"] for k, v in adv.items()})
check("it says a silent page does not prove the rival lacks the facility, and is labelled Likely, never proven", "does not prove" in adv["meeting_rooms"]["proof"] and adv["meeting_rooms"]["confidence"] == "Likely")
under = {u["key"]: u for u in d["underexplained"]}
check("under-explained: a thinly described restaurant, and a strength the site emphasises that the assistant did not pick up (a hypothesis)", "restaurant" in under and "perception:Weddings" in under and under["perception:Weddings"]["confidence"] == "Worth checking", list(under))
opp = {(o["theme"], o["kind"]): o for o in d["opportunities"]}
check("each is tied to a kind of search, with what the assistant did for it in this sample: business, named in 1 of 8", ("business", "advantage") in opp and "1 of 8" in opp[("business", "advantage")]["ai_result"] and opp[("business", "advantage")]["gap"], list(opp))
check("the limits are stated: one assistant, one day, a silent page is not proof", "does not prove" in d["limits"] and "one assistant" in d["limits"])
check("no evidence, no claims: an empty report gives empty sections, never an error", differentiation.build({})["opportunities"] == [] and differentiation.build({"consultant": {}})["strengths"] == [])
rec = advice._from_differentiation(d)
check("a recommendation per kind of traveller with a gap, as an opportunity, labelled by its evidence, promising nothing", rec and rec[0]["id"].startswith("DE-") and "not a promise" in rec[0]["why"] and rec[0]["kind_hint"] == "opportunity")
rk = ranking.annotate([dict(rec[0])], [])[0]
check("it reaches the action plan, and a Likely advantage is not labelled Confirmed", rk["value"] >= 28 and rk["confidence_label"] in ("Likely", "Worth checking"), (rk["value"], rk["confidence_label"]))
check("it is an AI visibility action", advice.track_of(rec[0]) == "visibility")

print("2. why rivals are recommended instead")
rs = rival_analysis.build(REP)
a = next(r for r in rs if r["name"] == "Hotel A")
check("Hotel A is explained: how often, the assistant's reason, the sites that named it and not this hotel, and how this hotel's pages compare", a["answers"] == 7 and "convenient for business travellers" in a["statement"] and "parisjetaime.com" in a["sources"] and "mentions it only in passing" in a["statement"], a["statement"])
check("two kinds of evidence agree (reason and cited sites), so it is Supported; Hotel D, with none, is a Hypothesis", a["label"] == "Supported" and next(r for r in rival_analysis.build(REP, limit=5) if r["name"] == "Hotel D")["label"] == "Hypothesis")
check("only comparable hotels are analysed, and a report with no AI comparison gives none", rival_analysis.build({}) == [] and rival_analysis.build({"ai_gap": {"status": "unavailable"}}) == [])

print("3. where to get listed")
sa = {s["domain"]: s for s in source_actions.build(REP)}
check("each site is classified by kind: a tourism office, a venue directory, a publisher", sa["parisjetaime.com"]["type"] == "tourism" and sa["cvent.com"]["type"] == "conference" and sa["timeout.com"]["type"] == "publisher", {k: v["type"] for k, v in sa.items()})
check("the hotel's own site is excluded, and a site where the hotel appears and nobody is ahead is left out", "hotel-opera.com" not in sa)
check("the route to inclusion is stated: a contact page, a commission/affiliate site, or none found", "contact page" in sa["parisjetaime.com"]["route"] and "affiliate" in sa["timeout.com"]["route"] and "no submission route" in sa["cvent.com"]["route"], {k: v["route"] for k, v in sa.items()})
check("the action depends on the kind of site, and never suggests paying for coverage", "submissions" in sa["parisjetaime.com"]["action"] and "event-space information" in sa["cvent.com"]["action"] and "Do not pay for undisclosed coverage" in sa["timeout.com"]["action"])
check("the reason to be there is the hotel's own advantage, or 'do not approach until there is one'", "meeting rooms" in sa["parisjetaime.com"]["why_now"].lower())
check("the recommendation to get listed names each site, its kind and its route, and says it guarantees nothing", "guarantee" in advice._from_source_gaps(REP["ai_insights"], list(sa.values()))[0]["action"].lower() and "contact page" in json.dumps(advice._from_source_gaps(REP["ai_insights"], list(sa.values()))[0]["evidence"]))

print("4. more specific prompts from verified attributes")
sug = query_matrix.suggest(REP, existing=["Which upscale hotels near Palais Garnier are best for a business trip?"])
txts = [s["text"] for s in sug]
check("prompts combine a place near the hotel with a verified facility, traveller or requirement", any("corporate workshop for 180 people" in t for t in txts) and any("Galeries Lafayette" in t and "gym" in t for t in txts) and any("first-time visitors" in t for t in txts), txts)
check("each rests on at least two verified attributes, named", all(len(s["rests_on"]) >= 2 for s in sug))
check("none names the hotel, and each mentions the town or a place near it", not any("hotel opera" in t.lower() for t in txts) and all(re.search(r"Paris|Galeries Lafayette|Palais Garnier", t) for t in txts))
check("a pool or spa the hotel does not state strongly is never suggested", not any("pool" in t.lower() or " spa" in t.lower() for t in txts), txts)
check("a prompt already in the set is not suggested again", len(query_matrix.suggest(REP, existing=txts)) == 0 or not set(txts) & {s["text"] for s in query_matrix.suggest(REP, existing=txts)})

print("5. in the report and on the dashboard")
SAMPLE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
rep = copy.deepcopy(SAMPLE)
for k in ("ai_gap", "ai_insights", "question_plan"):
    rep[k] = REP[k]
rep["consultant"].update({"features": REP["consultant"]["features"], "facility_depth": REP["consultant"]["facility_depth"], "intents": REP["consultant"]["intents"]})
import pymupdf
txt = " ".join(" ".join(p.get_text() for p in pymupdf.open(stream=report_pdf.build_pdf(rep, "management"), filetype="pdf")).split())
check("the management report has what makes the hotel different, why rivals are recommended, and where to get listed", all(w in txt for w in ("What makes this hotel different", "Verified strength", "Why comparable hotels are recommended instead", "Where to get listed: the sites AI relies on", "Route to inclusion")), [w for w in ("What makes this hotel different", "Why comparable hotels are recommended instead", "Where to get listed", "Route to inclusion") if w not in txt])
check("it says listing is no guarantee", "does not guarantee that any AI assistant will recommend the hotel" in txt)
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "s.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "SECRET_KEY": "k" * 32})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
hid = db.create_hotel("Hotel Opera", "hotel-opera.com", "Paris", "hotel-opera.com")
r2 = copy.deepcopy(rep)
r2["meta"].update(base="https://www.hotel-opera.com/", website="hotel-opera.com", hotel="Hotel Opera", city="Paris")
r2["consultant"]["coverage"] = {"pages_read": 8}
r2["question_plan"] = {**REP["question_plan"], "questions": [{"id": f"q{i}", "kind": "niche", "angle": a_, "text": t_, "why": "w", "priority": "core"} for i, (a_, t_) in enumerate([
    ("Price level", "Which upscale hotels near Palais Garnier give the best quality for the price?"), ("Business travel", "Which upscale hotels near Palais Garnier are best for a business trip?"),
    ("Meetings", "Which hotels in Paris have meeting rooms for a team workshop?"), ("Couples", "Which hotels in Paris are best for a romantic weekend for two?"), ("Families", "Which hotels in Paris work well for a family with young children?"),
    ("Neighbourhood", "What are the best upscale hotels in the 9th arrondissement of Paris?"), ("Parking", "Which upscale hotels near Palais Garnier have parking for guests?"), ("City breaks", "Which upscale hotels are best for a city break in Paris?"),
    ("Value", "Which hotels in Paris are good value but still well located?"), ("Dining", "Which hotels in Paris are known for a good restaurant?")], 1)]}
app.extensions["reports"].save(r2)
adm = app.test_client()
adm.post("/admin/login", data={"password": "adm"})
pg = adm.get(f"/admin/hotel/{hid}").get_data(as_text=True)
check("the dashboard has a Strategy tab with the four parts", 'data-name="strategy"' in pg and all(w in pg for w in ("What makes this hotel different", "Why rivals are recommended instead", "Where to get listed: the sites AI relies on", "Supported")))
check("the Prompts tab offers the more specific prompts, each with what it rests on and an Add button", "More specific prompts we could test" in pg and "psugadd" in pg and "Rests on:" in pg)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
