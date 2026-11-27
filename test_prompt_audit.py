"""
Prompt audit (prompt_audit.py): what each prompt assumes, whether the hotel's verified facts support it, and whether it is a fair test of organic discovery. A diagnostic: it flags and explains,
changes nothing. Cases are the real prompts that prompted it (Hilton Dusseldorf's airport question, Brooks Guesthouse's parking question, Eriksberg's owner-written prompts).
Run: python test_prompt_audit.py
"""
import copy
import sys

import prompt_audit as pa

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


def report(hotel, city, prompts, facilities=None, tier=None, anchors=None):
    items, ex = [], {}
    for n, (text, other_hotels, named, extra) in enumerate(prompts):
        for r in range(3):
            iid = f"p{n}#{r + 1}"
            items.append({"id": iid, "qid": f"p{n}", "kind": "niche", "text": text, "answer": "x", "mentioned": r < named, "names_hotel": extra.get("names_hotel", False), "source": extra.get("source", "benchmark"),
                          "priority": "core", "angle": extra.get("angle", "Traveller intent"), "why": "w"})
            ex[iid] = ([{"name": hotel}] if r < named else []) + [{"name": o} for o in other_hotels]
    return {"meta": {"hotel": hotel, "city": city}, "ai_sample": {"status": "ok", "items": items}, "ai_insights": {"extracted_answers": ex},
            "fact_profile": {"facilities": facilities or {}}, "market_profile": {"tier": tier, "anchors": anchors or []}, "question_plan": {"anchors": anchors or [], "questions": [], "facts": []}}


def row(rep, text):
    return next(r for r in pa.audit(rep)["prompts"] if r["text"] == text)


print("1. facilities and conditions the wording demands")
AIR = "I'm flying out of Dusseldorf Airport early tomorrow. Which upscale hotels nearby have a shuttle and an early breakfast?"
rep = report("Hilton Dusseldorf", "Dusseldorf", [(AIR, ["Sheraton Airport", "Lindner Airport"], 0, {})], facilities={"airport_transfer": {"state": "unknown"}}, tier={"key": "upscale", "why": "brand"})
r = row(rep, AIR)
req = {x["key"]: x["state"] for x in r["requires"]}
check("the shuttle is not verified, the breakfast cannot be verified by any fact, the upscale level matches", req.get("airport_transfer") == "unverified" and req.get("breakfast") == "unverified" and req.get("tier_upscale") == "verified", req)
check("the prompt is flagged, with the unverified conditions listed", r["flag"] and "an airport shuttle" in r["unverified"] and "an early breakfast" in r["unverified"], r["unverified"])

PARK = "Which hotels near Victoria Park have parking for guests?"
rep = report("Brooks Guesthouse", "Bath", [(PARK, ["A", "B", "C"], 0, {})], facilities={"parking": {"state": "not_offered"}}, anchors=[{"name": "Victoria Park", "km": 0.35, "source": "the hotel's own pages"}])
r = row(rep, PARK)
check("a prompt that asks for parking the profile says the hotel does not have is marked contradicted", any("parking" in c for c in r["contradicted"]), r["contradicted"])
check("the place it names is checked against a measured distance", any(x["key"] == "place" and x["state"] == "verified" for x in r["requires"]), r["requires"])
check("a place with no recorded distance is unverified, not assumed", any(x["state"] == "unverified" for x in row(report("H", "Bath", [("Which hotels are closest to Herschel Museum of Astronomy?", ["A"], 0, {})]), "Which hotels are closest to Herschel Museum of Astronomy?")["requires"] if x["key"] == "place"))

LUX = "Looking for a luxury spa hotel on the Devon coast with a proper restaurant and ocean views"
rep = report("Saunton Sands Hotel", "Saunton", [(LUX, ["Thurlestone Hotel"], 3, {})], facilities={"spa": {"state": "on_site"}, "restaurant": {"state": "on_site"}}, tier={"key": "upscale", "why": "stated"})
r = row(rep, LUX)
check("'luxury' for a hotel whose price level is upscale is flagged as a mismatch; the spa and restaurant are verified", any("luxury" in c for c in r["contradicted"]) and {x["key"]: x["state"] for x in r["requires"]}["spa"] == "verified", r["requires"])

print("2. effectively branded prompts are told apart from distinctive-but-open ones, not rejected")
WINE = "Which places to stay in Blekinge are known for fine dining with a 9,000-bottle wine cellar?"
conv = report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(WINE, [], 3, {})])
r = row(conv, WINE)
check("named in every answer with no other hotel beside it, and worded around an exact figure: effectively branded, with the reason", r["kind"] == "effectively_branded" and r["organic"] == "caution" and "exact figure" in " ".join(r["realism"]), (r["kind"], r["realism"]))
open_ = report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(WINE, ["Brösarps Gästgifveri", "Wanås Restaurant Hotel", "Astensmåla Gård", "Hotel Carlshamn"], 1, {})])
r = row(open_, WINE)
check("the SAME wording, when the assistants name four other hotels for it, is experience-specific and kept as organic: a distinctive experience is not rejected for being distinctive", r["kind"] == "experience_specific" and r["organic"] is True, (r["kind"], r["organic"]))
BEST = "What are the best hotels in Karlshamn?"
r = row(report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(BEST, ["Port Hotel", "Hotel Carlshamn", "Best Western"], 0, {"source": "-"})]), BEST)
check("an ordinary town question is broad discovery and a fair test", r["kind"] == "broad_discovery" and r["organic"] is True and r["scope"] == "town", (r["kind"], r["scope"]))
NAMED = "Is Eriksberg Hotel & Nature Reserve good for a wedding?"
r = row(report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(NAMED, [], 3, {"names_hotel": True})]), NAMED)
check("a prompt that names the hotel is explicitly branded and not a test of organic discovery", r["kind"] == "explicitly_branded" and r["organic"] is False)

print("3. scope, segment and realism")
for text, scope in (("Which hotels in Blekinge are best for a business trip?", "region"), ("Which hotels are closest to Mahraviken?", "place"), (BEST, "town"), ("Which places to stay in southern Sweden are known for coastal hiking trails?", "region")):
    check(f"scope of '{text[:55]}...' is {scope}", pa.scope_of(text, {"meta": {"city": "Karlshamn"}}) == scope, pa.scope_of(text, {"meta": {"city": "Karlshamn"}}))
check("segments come from the wording", pa.segment_of("Which hotels in Karlshamn are best for a team meeting or conference?") == "business" and pa.segment_of("hotel for a wedding with rooms for the guests") == "weddings")
check("a long, stacked question is flagged as unlikely", any("stacks" in f for f in pa.realism("Which luxury hotels near X have a spa, a pool, a gym, meeting rooms and a restaurant for a wedding?")))

print("4. a diagnostic only")
rep = report("Hilton Dusseldorf", "Dusseldorf", [(AIR, ["A"], 0, {})])
before = copy.deepcopy(rep)
pa.audit(rep)
check("the report is not changed by the audit", rep == before)
check("an empty or partial report does not raise", pa.audit({})["summary"]["prompts"] == 0 and pa.audit({"ai_sample": {"items": [{"id": "x", "kind": "niche", "text": "t", "answer": "a"}]}})["summary"]["prompts"] == 1)

print("5. the same answers, grouped; and audiences placed without deciding the operator is wrong")
P1, P2, P3 = "Which hotels in Karlshamn are best for a wedding with rooms for the guests?", WINE, BEST
rep = report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(P1, ["A", "B"], 1, {}), (P2, [], 3, {}), (P3, ["Port Hotel", "B", "C"], 0, {"source": "-"})], facilities={"weddings": {"state": "on_site"}, "restaurant": {"state": "on_site"}})
bd = pa.breakdown(rep)
check("the headline and its groups count the same answers (4 of 9 named across 3 prompts)", bd["headline"] == {"prompts": 3, "named": 4, "asked": 9, "pct": 44} and sum(g["asked"] for g in bd["by_kind"].values()) == 9, bd["headline"])
check("every group says how many distinct prompts stand behind it", all("prompts" in g for g in bd["by_scope"].values()) and sum(g["prompts"] for g in bd["by_kind"].values()) == 3, bd["by_kind"])
check("without the effectively branded prompt the figure drops (the wine-cellar prompt, named 3 of 3, is out)", bd["what_if"]["without_effectively_branded"]["pct"] == 17 and bd["what_if"]["effectively_branded_prompts"] == 1, bd["what_if"])

mp = {"audiences": [{"key": "wellness", "label": "Spa and wellness", "level": "stated"}, {"key": "weddings", "label": "Weddings", "level": "stated"}, {"key": "pets", "label": "Pet owners", "level": "stated"},
                     {"key": "heritage", "label": "Character and heritage", "level": "stated"}, {"key": "family", "label": "Families", "level": "strong", "why": "pages say so"}]}
rep = {"market_profile": mp, "fact_profile": {"facilities": {"spa": {"state": "partner"}, "weddings": {"state": "unknown"}, "pets": {"state": "not_offered"}}}}
st = {a["key"]: a["state"] for a in pa.audience_status(rep)}
check("an audience the operator states and the facts show is verified; one the facts say the hotel cannot serve is contradicted", st["wellness"] == "verified" and st["pets"] == "contradicted", st)
check("an audience the operator states that the site does not show is operator-confirmed, NOT reclassified as aspirational", st["weddings"] == "operator_confirmed" and "aspirational" not in st.values(), st)
check("an audience with no facility to check against is left operator-confirmed too, and strong page evidence is verified", st["heritage"] == "operator_confirmed" and st["family"] == "verified", st)

print("6. the admin page")
import json as _json
import os as _os
import tempfile as _tf
import warnings as _w

_w.filterwarnings("ignore")
_os.environ.setdefault("STREAMLIT_APP_ENABLED", "1")
import audit_service
import backend
import server

_url = "sqlite:///" + _os.path.join(_tf.mkdtemp(), "pa.db").replace("\\", "/")
_cfg = audit_service.Config({"DATABASE_URL": _url, "ADMIN_PASSWORD": "adm-pass-1", "SITE_PASSWORD": "site-pass-1", "SECRET_KEY": "k" * 32, "CRON_TOKEN": "cron-token-abcdef"})
_app = server.create_app(_cfg, run_fn=lambda p, progress_cb=None: {})
_st = backend.open_store(_url)
_rep = report("Eriksberg Hotel & Nature Reserve", "Karlshamn", [(BEST, ["Port Hotel", "B"], 0, {"source": "-"}), (WINE, [], 3, {})])
_rep["meta"].update(run_at="2026-11-24T10:00:00+00:00", website="https://eriksberg.se/")
_rid = _st.save_run(_rep)
_cl = _app.test_client()
_cl.post("/login", data={"password": "site-pass-1"})
check("the page needs an admin sign-in", _cl.get(f"/admin/run/{_rid}/prompt-audit.json").status_code in (302, 401, 403))
_cl.post("/admin/login", data={"password": "adm-pass-1"})
_resp = _cl.get(f"/admin/run/{_rid}/prompt-audit.json")
_d = _json.loads(_resp.get_data(as_text=True)) if _resp.status_code == 200 else {}
check("signed in, it returns the audit, the breakdown and the audiences", _resp.status_code == 200 and _d.get("summary", {}).get("prompts") == 2 and "by_scope" in _d.get("breakdown", {}) and "audiences" in _d, _resp.status_code)
check("and the saved report is unchanged afterwards", _st.get_report(_rid)["ai_sample"]["items"] == _rep["ai_sample"]["items"])

print("\nFAILURES:", fails or "none")
sys.exit(1 if fails else 0)
