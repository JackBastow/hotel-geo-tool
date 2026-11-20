"""
Strategy actions (getting onto the outside sources AI reads, with steps), their own section in the Actions tab, the tab order, and forum searches shaped by the hotel's profile.
Run: python test_strategy_actions.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import forums
import hotel_profile
import portal_view
import strategy_actions

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
PROFILE = {**hotel_profile.empty(), "status": "confirmed", "town": "Karlshamn", "region": "Blekinge", "area": "southern Sweden", "attractions": ["Blekinge archipelago"],
           "kinds": ["destination", "coastal"], "reasons": ["wildlife safaris", "an award-winning game restaurant"], "audiences": ["couples", "meetings", "weddings", "food"]}


def report():
    r = copy.deepcopy(BASE)
    r["meta"].update(base="https://www.hilton-cdg.example/", hotel="Hilton Paris CDG", city="Paris")
    r["ai_insights"] = {**(r.get("ai_insights") or {}), "pages": [
        {"url": "https://www.timeout.example/paris/best-airport-hotels", "domain": "timeout.example", "cited": 3, "names_hotel": False, "names_competitor": "Pullman Paris CDG"},
        {"url": "https://www.marriott.com/en-us/hotels/parcy-paris-marriott-cdg/", "domain": "marriott.com", "cited": 4, "names_hotel": False, "names_competitor": "Paris Marriott CDG"},
        {"url": "https://www.pullman-cdg.example/", "domain": "pullman-cdg.example", "cited": 2, "names_hotel": False, "names_competitor": "Pullman Paris CDG"},
        {"url": "https://www.hilton-cdg.example/rooms", "domain": "hilton-cdg.example", "cited": 5, "names_hotel": True, "own_site": True},
        {"url": "https://www.booking.com/city/fr/roissy-en-france.html", "domain": "booking.com", "cited": 6, "names_hotel": False, "names_competitor": "Pullman Paris CDG"},
        {"url": "https://www.trip.com/hotels/list?city=paris", "domain": "trip.com", "cited": 2, "names_hotel": False, "names_competitor": "Pullman Paris CDG"},
        {"url": "https://www.zenhotels.com/hotels/paris", "domain": "zenhotels.com", "cited": 1, "names_hotel": False, "names_competitor": "Pullman Paris CDG"},
        {"url": "https://www.bestairporthotels.example/paris", "domain": "bestairporthotels.example", "cited": 2, "names_hotel": False, "names_competitor": "Pullman Paris CDG"}]}
    r["ai_gap"] = {"status": "ok", "markets": [], "rivals": [{"name": "Pullman Paris CDG", "url": "https://www.pullman-cdg.example/"}],
                   "articles": [{"url": "https://www.timeout.example/paris/best-airport-hotels", "domain": "timeout.example", "cited": 3, "read": "ok", "hotel_in": False, "rivals_in": ["Pullman Paris CDG"],
                                 "questions": [], "contact_url": "https://www.timeout.example/contact"}]}
    return r


print("1. strategy actions")
acts = strategy_actions.build(report(), PROFILE, "Hilton Paris CDG")
titles = [a["title"] for a in acts]
check("a site the assistant used, featuring a rival and not the hotel, becomes 'Get onto' it", "Get featured on timeout.example" in titles, titles)
check("never another hotel group's own website (a Hilton cannot get onto marriott.com)", not any("marriott.com" in t for t in titles))
check("never a rival hotel's own site, nor the hotel's own", not any("pullman-cdg" in t or "hilton-cdg" in t for t in titles))
seen = next(a for a in acts if a["title"] == "Get featured on timeout.example")
check("each has steps: who to contact (the contact page when found), what to send, how to follow up", len(seen["steps"]) == 3 and "https://www.timeout.example/contact" in seen["steps"][0] and "wildlife safaris" in seen["steps"][1])
check("and says what it rests on", "Pullman Paris CDG" in seen["finding"] and seen["confidence_label"] == "Seen in the latest check" and seen["source"] == "strategy")
check("a booking or review site is never claimed as missing: a results page that does not name the hotel says nothing about its listing", not any(re.search(r"booking\.com|trip\.com|zenhotels", t) and ("Get" in t or "Check whether" in t) for t in titles), titles)
lst = next((a for a in acts if a["tag"] == "listings"), None)
check("they become one action about making those listings work, naming the sites the assistant read", lst and all(d in lst["finding"] for d in ("booking.com", "trip.com", "zenhotels.com")) and "does not say whether you are listed" in lst["why"])
check("a site we did not read is 'check whether you are featured', with searching for the hotel as the first step", any(a["title"] == "Check whether you are featured on bestairporthotels.example" and a["steps"][0].startswith("Search bestairporthotels.example") for a in acts), titles)
check("the Competitors tab says 'not checked' for booking sites, never 'No'", "Not checked (we do not read booking or review sites)" in __import__("strategy_view").sources_html(report()))
sugg = [a for a in acts if a["confidence_label"] == "Suggested from your profile"]
st = " | ".join(a["title"] for a in sugg)
check("the profile adds the kinds of source that matter for its market, labelled as suggestions", "tourism board for Blekinge" in st and "nature and short breaks in southern Sweden" in st and "conference venue directories" in st, st)
check("a few, not a flood", len(sugg) <= 4)
check("without a profile there are no suggestions, only what was seen", all(a["confidence_label"] == "Seen in the latest check" for a in strategy_actions.build(report(), None, "X")))
import source_actions
check("the Competitors tab's 'where to get listed' leaves out chain and rival websites too", not any(s["domain"] in ("marriott.com", "pullman-cdg.example") for s in source_actions.build(report(), limit=20)))

print("2. in the Actions tab, in a section of their own")


def act(i, title, source, rec):
    return {"id": i, "title": title, "source": source, "status": "todo", "state": "open", "priority": "medium", "effort": "", "team": "marketing", "first_run_id": 1, "last_run_id": 1, "reopened": 0,
            "resolution": "", "done_at": "", "resolved_at": "", "rec_json": json.dumps(rec), "kind": "", "category": ""}


sm = {"latest_run_id": 1, "runs": 1}
board = portal_view.action_board(sm, [act(1, "Add a FAQ page", "site", {"action": "Write it"}), act(2, "Get featured on timeout.example", "strategy", seen)], True, strategy_context="<p>context here</p>")
check("the Actions tab has Fixes and Strategy sections", "Fixes (1)" in board and "Strategy (1)" in board and board.index("Add a FAQ page") < board.index('id="act-strategy"') < board.index("Get featured on timeout.example"))
check("a strategy action shows its steps", '<ol class="steps-mini">' in board and "Send a short note" in board)
check("with the market context and the honesty note in the section", "context here" in board and "never suggested as a source" in board)

import backend, progress, tempfile as _tf
_db = backend.open_store("sqlite:///" + os.path.join(_tf.mkdtemp(), "s.db"))
_r1 = report()
_r1["consultant"] = {**(_r1.get("consultant") or {}), "coverage": {"pages_read": 8, "pages_attempted": 8}}
_hid = _db.create_hotel("Hilton Paris CDG", "hilton-cdg.example", "Paris", backend.hotel_key(_r1))
_db.set_hotel(_hid, profile_json=json.dumps(PROFILE))
_rid = _db.save_run(_r1)
_h = _db.get_hotel(_hid)
progress.sync(_db, _h, _r1, _rid)
_s1 = [a for a in _db.list_actions(_hid) if a["source"] == "strategy"]
check("a check adds the strategy actions to the hotel's action list", len(_s1) >= 3 and all(a["state"] == "open" for a in _s1), len(_s1))
_r2 = copy.deepcopy(_r1)
_r2["ai_insights"]["pages"] = []
_r2["ai_gap"]["articles"] = []
_rid2 = _db.save_run(_r2)
progress.sync(_db, _h, _r2, _rid2)
check("a later check that does not cite those sites does not close them: they stay until the hotel acts", all(a["state"] == "open" for a in _db.list_actions(_hid) if a["source"] == "strategy"))
_bad = _db.insert_action(_hid, {"title": "Get onto booking.com", "source": "strategy", "akey": "strategy|booking.com|get onto booking com", "status": "todo", "state": "open", "rec_json": "{}", "reopened": 0, "resolution": "", "note": ""})
_kept = _db.insert_action(_hid, {"title": "Get onto trip.com", "source": "strategy", "akey": "strategy|trip.com|get onto trip com", "status": "working", "state": "open", "rec_json": "{}", "reopened": 0, "resolution": "", "note": ""})
progress._STRATEGY_TRIED.clear()
progress.ensure_strategy(_db, _db.get_hotel(_hid))
_ids = {a["id"] for a in _db.list_actions(_hid)}
check("saved strategy actions from before this fix are replaced if nobody touched them, and kept if the hotel is working on them", _bad not in _ids and _kept in _ids)

print("3. the dashboard tabs")
dash = portal_view.dashboard({"hotel": {"name": "H", "city": "C", "website": "w", "weekly": 1}, "last_run_at": None, "actions": {"todo": 1, "working": 0, "still_flagged": 0, "completed": 0, "total": 1, "verified": 0, "cleared_site": 0},
                              "points": [], "completed_points": [], "latest_score": None, "delta": None, "first_run_at": None, "cov_first": None, "cov_latest": None, "runs": 0, "latest_run_id": 1},
                             [act(1, "Add a FAQ page", "site", {})], [], start="<p>s</p>", settings_url="/s")
names = [n for n in re.findall(r'class="tab[^"]*" data-tab="tab-[a-z]+" data-name="([a-z]+)"', dash)]
check("in the order: Start here, Overview, AI visibility, Actions, Competitors, then the rest", names[:5] == ["start", "overview", "ai", "actions", "competitors"] and "strategy" not in names, names)
check("and it is called Actions, not Recommendations", ">Actions (1)<" in dash and "Recommendations (" not in dash)

print("4. forum searches shaped by the profile")
t = forums.topics("Eriksberg Hotel & Nature Reserve", "Karlshamn", {}, [], profile=PROFILE)
check("the trips the hotel is chosen for, at the level people plan them, come first", t[0] == "a nature or wildlife weekend in southern Sweden" and any("Blekinge archipelago" in x for x in t) and any("wildlife safaris" in x for x in t), t)
check("the town is still searched too", "best hotels in Karlshamn" in t and len(t) <= 8, t)
check("without a profile, the town topics as before", forums.topics("X", "Karlshamn", {}, [])[0] == "best hotels in Karlshamn")
pt = forums.place_terms("Eriksberg Hotel & Nature Reserve", "Karlshamn", {}, [], profile=PROFILE)
check("a thread about the region, wider area or the places guests come for counts as the hotel's market", all(x in pt for x in ("Blekinge", "southern Sweden", "Blekinge archipelago")), pt)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
