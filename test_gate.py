"""
Offline test: the consistency gate over a whole report (report_gate.py). Planted contradictions must be settled in the open; correct findings must be left alone. No network.
Run: python test_gate.py
"""
import copy
import warnings

warnings.filterwarnings("ignore")
import advice
import report_gate

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


def rec(i, title, finding, action="Update the page with the facts the hotel can stand behind.", kind="fix"):
    return {"id": i, "title": title, "finding": finding, "action": action, "why": "", "kind": kind, "confidence": advice.BEST, "source": "content", "evidence": [{"snippet": "x", "url": "https://h/"}]}


def report():
    recs = [rec("A1", "The spa is not mentioned", "The hotel's pages do not mention the spa."),
            rec("A2", "Spa details are thin", "The spa page states 1 of 6 details: opening hours, prices and treatments are missing."),
            rec("A3", "Promote the pool", "Add a page that promotes the swimming pool to families.", "Add a dedicated page describing the swimming pool."),
            rec("A4", "State whether the hotel has a pool", "The pages are silent.", "State whether the hotel has a swimming pool and its hours."),
            rec("A5", "Restaurant is described", "Dining is described on several pages.", "Keep the menu current.")]
    return {"meta": {"hotel": "Ambassadors Bloomsbury", "base": "https://ambassadors.example/"},
            "consultant": {"coverage": {"pages_read": 8, "limited": False}, "pages_read": 8,
                           "features": [{"key": "spa", "label": "Spa", "level": "strong", "pages": 3}, {"key": "pool", "label": "Swimming pool", "level": "none", "pages": 0}, {"key": "restaurant", "label": "Restaurant / dining", "level": "some", "pages": 2}],
                           "recommendations": recs, "top_actions": ["A1", "A3"], "quick_wins": ["A3"], "required_fixes": ["A1"], "opportunity_recs": [],
                           "plan": {"30": ["A1", "A3"], "60": [], "90": []},
                           "differentiation": {"strengths": [{"key": "spa", "label": "Spa"}], "advantages": [{"key": "spa", "read": 5}], "underexplained": [{"key": "pool", "label": "Pool"}], "opportunities": []}},
            "recommendations": copy.deepcopy(recs), "top_fixes": [{"id": "A1"}, {"id": "A3"}],
            "competitors": {"competitors": [{"name": "Ambassadors Bloomsbury", "url": "https://ambassadors.example/en/", "km": 0.0}, {"name": "Far Hotel", "url": "https://far.example", "km": 40.0}, {"name": "Near Hotel", "url": "https://near.example", "km": 0.4}]},
            "ai_gap": {"comparison": {"rivals": [{"name": "Near Hotel", "pages_read": 2}, {"name": "Other", "pages_read": 1}]}, "markets": [{"of": 10, "named": 0}]},
            "ai_sample": {"summary": {"asked": 3}, "items": [{"kind": "generic", "text": "best hotels in London", "mentioned": False, "answer": "Try the Bloomsbury Ambassadors-style boutique options near the museum."},
                                                              {"kind": "niche", "text": "hotels near Parking Lot Airports Heathrow", "mentioned": False, "answer": "Many options."},
                                                              {"kind": "direct", "text": "Tell me about Ambassadors Bloomsbury", "mentioned": True, "answer": "Ambassadors Bloomsbury is a hotel."}]},
            "custom_prompts": []}


r = report_gate.check(report())
c = r["consultant"]
ids = [x["id"] for x in c["recommendations"]]
by = {x["id"]: x for x in c["recommendations"]}
check("a finding that says the spa is not mentioned, while the pages state it on 3 pages, is downgraded to Worth checking, marked disputed and says why", by["A1"].get("disputed") and by["A1"]["confidence"] == advice.EXPER and "disagree" in by["A1"]["finding"], by["A1"])
check("a finding about thin spa DETAIL is not a contradiction and is left alone", not by["A2"].get("disputed") and by["A2"]["confidence"] == advice.BEST)
check("advice to promote a pool the pages do not show is removed", "A3" not in ids, ids)
check("...and it leaves the top actions, quick wins and plan too", "A3" not in c["top_actions"] and "A3" not in c["quick_wins"] and "A3" not in c["plan"]["30"] and all(t["id"] != "A3" for t in r["top_fixes"]))
check("advice that only asks the hotel to state WHETHER it has a pool is kept", "A4" in ids)
check("a correct finding is untouched", not by["A5"].get("disputed") and by["A5"]["confidence"] == advice.BEST)
check("a removed item is recorded in the dropped list with its reason", any(d["id"] == "A3" for d in c["dropped_recommendations"]))
names = [x["name"] for x in r["competitors"]["competitors"]]
check("the hotel itself and a hotel 40 km away are not comparable hotels; the near one stays", names == ["Near Hotel"], names)
check("the 'compared with N rivals' count is recomputed from the rivals actually read", c["differentiation"]["advantages"][0]["read"] == 2, c["differentiation"]["advantages"])
check("an under-explained facility the pages do not show is removed from the differentiation view", c["differentiation"]["underexplained"] == [])
g = r["gate"]
check("the checks that ran are listed with how many items each looked at", len(g["checks"]) >= 6 and all("looked_at" in x for x in g["checks"]) and "consistency checks ran" in g["summary"], g["checks"])
check("a question with a scrap of page text for a place is reported", any(x["check"] == "prompt_places" for x in g["changes"]), g["changes"])
d = g.get("ai_diagnosis") or {}
check("the hotel was named in 1 of 3 answers, so no zero diagnosis is claimed", d.get("named") == 1 and "reading" not in d, d)
rz = report()
for i in rz["ai_sample"]["items"]:
    i["mentioned"] = False
rz = report_gate.check(rz)
dz = rz["gate"]["ai_diagnosis"]
check("when nothing names the hotel, the report says whether it was recognised by name, and counts answers holding words of its name that were not counted", "by name" in dz["reading"] and dz["possible_missed"] >= 1 and dz["direct_named"] == 0, dz)
check("it never raises on an empty report", report_gate.check({})["gate"]["checks"] is not None and report_gate.check({"consultant": None})["gate"]["summary"])
check("a limited crawl never removes advice on the strength of an absence", all(x["id"] != "A3" or True for x in c["recommendations"]) and "A3" in [x["id"] for x in report_gate.check({**report(), "consultant": {**report()["consultant"], "coverage": {"pages_read": 1, "limited": True}, "pages_read": 1}})["consultant"]["recommendations"]])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
