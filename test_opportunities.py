"""
Offline test: the few biggest AI discovery opportunities (credible searches the hotel is not named for while rivals are, plus independent publications); a gym or a 'wellness offer' is not a spa; the room-rate advice
respects that rates vary; the kinds of action also work for reports made before the field existed; the dashboard filters actions by kind. No network. Run: python test_opportunities.py
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
import consultant
import facility_depth as fd
import guest_questions as gq
import headline
import hotel_class
import opportunities
import report_pdf
import server
from types import SimpleNamespace as NS

headline.attach = lambda r: None
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. a gym or a 'wellness offer' is not a spa")
GYM = [{"url": "https://h.com/experiences/", "text": "Wellness Offer. Wellness Galeries Lafayette & Marriott Opera Ambassador stay. Our fully-equipped gym offers an environment conducive to training. Wellness. " * 3}]
SPA = [{"url": "https://h.com/spa/", "text": "The hotel's spa has treatment rooms for massage and facials, a sauna and a steam room. Treatments from 95 euros. " * 3}]
site = lambda pages: NS(content_pages=pages)      # noqa: E731
check("a page of wellness offers and a gym gives no spa evidence to judge", [f for f in fd.analyse(site(GYM)) if f["key"] == "spa"] == [])
check("a page about the hotel's own spa is judged", any(f["key"] == "spa" for f in fd.analyse(site(SPA))))
import insight_content as ic
import pagetarget
pgs = lambda ps: [(p, p["text"]) for p in ps]      # noqa: E731
src = open("hotel_class.py", encoding="utf8").read()
check("the 'spa hotel' class needs treatments and the hotel's own spa named as a place, and 'wellness' alone no longer counts", 'r"\\bwellness\\b"' not in src.split("_SPA_WORDS")[1].split(")]")[0] and "has_core and has_place" in src)

print("2. the room-rate advice respects that rates vary")
check("the example states what is in every rate and points to the booking terms for what varies", "Included in every rate" in open("insight_content.py", encoding="utf8").read() and "depend on the rate you choose" in open("insight_content.py", encoding="utf8").read())
BASE, HOTEL = "https://www.example-hotel.com/", "Example Hotel Opera"


def page(path, text):
    return {"url": BASE + path, "title": HOTEL, "text": text, "h1": [], "tels": [], "mails": [], "links": [], "signals": {}, "footer_text": "", "ok": True}


PAGES = [page("", f"Welcome to the {HOTEL} in Paris. " * 8), page("rooms/", "Our rooms include complimentary Wi-Fi and bottled water. " * 4), page("dining/", "The brasserie serves lunch and dinner. " * 4), page("info/", "Check-in from 15:00. " * 4)]
meta = [{"url": p["url"], "ok": True, "status": 200, "title": p["title"]} for p in PAGES]
out = consultant.analyse(own_pages=PAGES, pages_meta=meta, base=BASE, hotel=HOTEL, city="Paris", location={"lat": 48.87, "lon": 2.33}, guest={"questions": gq.evaluate(PAGES), "conflicts": [], "own_facts_node": {}, "pages_ok": 4, "pages_attempted": 4},
                         site={"robots": {"present": False, "status": 200}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)
rate = [r for r in out["recommendations"] if "rate_inclusions" in (r.get("question_ids") or [])]
check("the recommendation about what the rate includes says rates vary and to point guests to the booking terms", rate and "Rates vary by date, package, membership and booking channel" in rate[0]["action"], [r["id"] for r in out["recommendations"]])
check("every recommendation carries its kind (visibility, content or accuracy)", all(r.get("track") in ("visibility", "content", "accuracy") for r in out["recommendations"]))

print("3. the biggest AI discovery opportunities")
market = lambda qid, q, named, of, rivals: {"qid": qid, "kind": "niche", "question": q, "angle": "", "named": named, "of": of, "status": "not_named" if not named else "named", "gap": not named, "consistent": True, "priority": "core", "best_position": None, "answer_ids": [], "note": "", "rivals": [{"name": n, "answers": a, "of": of} for n, a in rivals], "other_category": []}   # noqa: E731
REP = {"ai_gap": {"status": "ok", "markets": [market("q1", "Which upscale hotels near Opera Garnier are best for a business trip with meeting space?", 0, 3, [("Hotel A", 3), ("Hotel B", 2)]),
                                              market("q2", "Which hotels in Paris have meeting rooms for a team workshop or a small conference?", 0, 3, [("Hotel A", 3)]),
                                              market("q3", "Which hotels in Paris work well for a family with young children?", 0, 3, [("Hotel F", 3)]),
                                              market("q4", "Which upscale hotels near Louvre give the best quality for the price?", 3, 3, [("Hotel B", 1)])],
                  "observations": {"q1": [{"kind": "assistant", "text": "The assistant named Hotel A in 3 of 3 answers and gave this reason: convenient for business travellers with meeting facilities.", "urls": []},
                                          {"kind": "facility", "text": "Hotel A's pages mention it (conference centre); the hotel's pages do not mention it.", "urls": []},
                                          {"kind": "criterion", "text": "Hotel A were recommended for location. The hotel's own pages already state it clearly (“Traverse City Hotels Waikiki Hotels Mexico City Hotels For Guests”).", "urls": []}]},
                  "articles": [{"url": "https://www.parisjetaime.com/hotels", "title": "Best hotels", "domain": "parisjetaime.com", "cited": 5, "questions": ["q1"], "hotel_in": None, "rivals_in": ["Hotel A"], "sponsored": False, "opportunity": True},
                               {"url": "https://letsgomylove.com/paris", "title": "Romantic Paris", "domain": "letsgomylove.com", "cited": 3, "questions": ["q2"], "hotel_in": None, "rivals_in": ["Hotel B"], "sponsored": True, "opportunity": True}]},
       "consultant": {"hotel_class": {"classes": [{"key": "business", "label": "Business hotel", "reasons": ["meeting rooms are described"]}, {"key": "conference", "label": "Conference hotel", "reasons": ["meeting space for 100 or more"]}]}, "traveller": {"segments": [{"label": "Business travellers", "relevance": "core"}]},
                      "recommendations": [{"id": "FD-events", "ref": "FD-events", "title": "The event space is only partly described", "short_title": "Describe the event space"}, {"id": "SG1", "ref": "SG1", "title": "x", "short_title": "Get listed on the sites AI uses"}]}}
ops = opportunities.build(REP)
keys = [o["key"] for o in ops]
check("the business / conference gap is the first opportunity: 0 of 6 answers, with the rivals that were named instead", ops[0]["key"] == "business" and ops[0]["named"] == 0 and ops[0]["of"] == 6 and ops[0]["rivals"][0]["name"] == "Hotel A", ops[0])
check("families are not listed: nothing says this is a family hotel, so the absence is not a gap", "family" not in keys)
check("a search the hotel IS named for is not a gap", "value" not in keys)
check("independent publications are the other opportunity, with the sites that name rivals and not the hotel, and whether they are sponsored", ops[-1]["key"] == "publications" and {s["domain"] for s in ops[-1]["sources"]} == {"parisjetaime.com", "letsgomylove.com"} and any(s["sponsored"] for s in ops[-1]["sources"]))
check("the reasons the assistant gave are shown, and a menu strip is never used as a difference", "convenient for business travellers" in " ".join(ops[0]["reasons"]) and not any("Traverse City" in d for d in ops[0]["differences"]))
check("the supporting actions are the recommendations that go with it", [s["ref"] for s in ops[0]["supporting"]][:1] == ["FD-events"])
check("a report with no AI comparison gives none, never an error", opportunities.build({}) == [] and opportunities.build({"ai_gap": {"status": "unavailable"}}) == [])

print("4. in the management report")
SAMPLE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
rep = copy.deepcopy(SAMPLE)
rep["ai_gap"], rep["consultant"]["hotel_class"] = REP["ai_gap"], REP["consultant"]["hotel_class"]
import pymupdf
doc = pymupdf.open(stream=report_pdf.build_pdf(rep, "management"), filetype="pdf")
txt = " ".join(" ".join(p.get_text() for p in doc).split())
check("the opportunities open page 2, with what is happening, who appears instead, the reasons given and the sites cited", all(w in txt for w in ("Your biggest AI discovery opportunities", "What is happening", "Who appears instead", "Sites it cited", "Reasons the assistant gave")))
check("a publication is only approached after checking it suits the hotel, and coverage is never paid for undisclosed", "Check it suits this hotel" in txt and "Do not pay for coverage that is not disclosed" in txt)
check("the three kinds of action are filled even for a report made before the field existed", "None found" not in txt.split("Where to focus: three kinds of action")[1][:1500], txt.split("Where to focus: three kinds of action")[1][:400])

print("5. the dashboard")
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "o.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "SECRET_KEY": "k" * 32})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
hid = db.create_hotel("Brooklands Hotel", "brooklandshotelsurrey.com", "Weybridge", "brooklandshotelsurrey.com")
r2 = copy.deepcopy(SAMPLE)
r2["ai_gap"], r2["consultant"]["hotel_class"] = REP["ai_gap"], REP["consultant"]["hotel_class"]
app.extensions["reports"].save(r2)
adm = app.test_client()
adm.post("/admin/login", data={"password": "adm"})
pg = adm.get(f"/admin/hotel/{hid}").get_data(as_text=True)
check("each action shows its kind and can be filtered by it", 'data-track="' in pg and all(w in pg for w in ("AI visibility opportunities", "Website content", "Data accuracy")) and 'data-t="visibility"' in pg)
check("the Overview leads with the biggest AI discovery opportunities", "Your biggest AI discovery opportunities" in pg and "Business travellers and conference enquiries" in pg)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
