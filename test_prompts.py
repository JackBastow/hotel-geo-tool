"""
Offline test: the hotel chooses its own prompts. A recommended set appears after the first check; the hotel edits and confirms it with a warning about changing it later; checks then ask exactly the confirmed
prompts; changing a confirmed set is a deliberate, warned step. No network. Run: python test_prompts.py
"""
import copy
import json
import os
import re
import tempfile
import warnings

warnings.filterwarnings("ignore")
import audit_service
import backend
import headline
import prompt_sets as ps
import server

headline.attach = lambda r: None
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


Q = [{"id": f"q{i}", "kind": "niche", "angle": a, "text": t, "why": "w", "priority": "core" if i < 9 else "secondary", "style": s}
     for i, (a, t, s) in enumerate([
         ("Price level", "Which 4-star hotels near Palais Garnier give the best quality for the price?", ""),
         ("Price level", "Which 4-star hotels in Paris are good value for money for a weekend?", ""),
         ("Price level", "Where can I find a good-value upscale hotel in Paris this autumn?", ""),
         ("Business travel", "Which 4-star hotels near Palais Garnier are best for a business trip?", ""),
         ("Meetings and events", "Which hotels near Palais Garnier have meeting rooms for a team offsite?", ""),
         ("Parking", "Which 4-star hotels near Palais Garnier have parking for guests?", ""),
         ("Families", "Which hotels in Paris work well for a family with young children?", ""),
         ("Couples", "Which hotels in Paris are best for a romantic weekend for two?", ""),
         ("Neighbourhood", "What are the best upscale hotels in the 9th arrondissement of Paris?", ""),
         ("Short search", "best 4-star hotel near Palais Garnier", "short search"),
         ("Short search", "best hotel in Paris for business travellers", "short search"),
         ("Conversational", "Help me choose, please. Which hotels in Paris suit a conference trip?", "conversational"),
         ("Conversational", "We are travelling at short notice. Which hotels near the Opera have availability?", "conversational"),
         ("Spa and wellness", "Which hotels in Paris have a spa for a relaxing break?", "")], 1)]
print("1. the recommended set")
rec = ps.recommend_set(Q, "Hotel Opera")
check("12 prompts are recommended from a bigger pool", len(rec) == 12 and len({p["text"] for p in rec}) == 12, len(rec))
from collections import Counter
check("the set covers the market: many different angles, no angle takes more than three places (two, unless the pool is thin)", len({p["angle"] for p in rec}) >= 8 and max(Counter(p["angle"] for p in rec).values()) <= 3, Counter(p["angle"] for p in rec))
check("at most two short-search / conversational variants", sum(1 for p in rec if p["style"]) <= 2)
check("core prompts come before the secondary ones", all(p["text"] in [q["text"] for q in Q[:9]] for p in rec[:6]))
check("a prompt that names the hotel is never recommended", not any("opera" in p["text"].lower() and "hotel opera" in p["text"].lower() for p in rec) and ps.recommend_set([{"text": "Is Hotel Opera good?", "kind": "niche"}], "Hotel Opera") == [])

print("2. the rules for a prompt")
H, C = "Hotel Opera", "Paris"
check("too short is refused", ps.check_prompt("hotels?", H, C)[1] != "")
check("naming the hotel is refused, and the reason is given", "Do not name your hotel" in ps.check_prompt("Is Hotel Opera a good place to stay in Paris?", H, C)[1])
check("a prompt with no town or place is refused", "Mention the town" in ps.check_prompt("Which hotels have a spa and a pool for a relaxing break?", H, C)[1])
check("a prompt that mentions the town passes", ps.check_prompt("Which hotels in Paris have a spa and a pool for a relaxing break?", H, C)[1] == "")
check("a place the recommended prompts are built around also passes", ps.check_prompt("Which hotels near Palais Garnier have a quiet bar for a business dinner?", H, C, ps.anchors_from({"prompts": rec}))[1] == "")
_, errs = ps.check_set([{"text": "Which hotels in Paris have a spa and a pool for a relaxing break?"}, {"text": "Which hotels in Paris have a spa and a pool for relaxing breaks?"}], H, C)
check("a near-duplicate is flagged", errs and errs[0]["i"] == 1)

print("3. the flow: draft, confirm, change")
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "p.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "SECRET_KEY": "k" * 32})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
hid = db.create_hotel("Hotel Opera", "hotel-opera.com", "Paris", "hotel-opera.com")
hotel = db.get_hotel(hid)
base = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
rep = copy.deepcopy(base)
rep["meta"].update(base="https://www.hotel-opera.com/", website="hotel-opera.com", hotel="Hotel Opera", run_at="2026-11-01T09:00:00+00:00")
rep["consultant"]["coverage"] = {"pages_read": 8}
rep["question_plan"] = {"questions": Q, "facts": [], "anchors": []}
app.extensions["reports"].save(rep)
st = ps.state(db, hotel)
check("after the first check the hotel has a recommended DRAFT, not yet confirmed", st["draft"] and not st["active"] and len(st["draft"]["prompts"]) == 12)
check("until it is confirmed, the audit uses no hotel-chosen prompts", db.confirmed_prompts_for_key("hotel-opera.com") == [])
who = "gm@hotel-opera.com"
prompts = st["draft"]["prompts"]
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": prompts, "agree": False})
check("confirming without ticking the box is refused", not ok and "Tick the box" in res["error"])
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": prompts[:5], "agree": True})
check("fewer than 8 prompts cannot be confirmed", not ok and "between 8 and 20" in res["error"])
bad = prompts[:11] + [{"text": "Is Hotel Opera any good? Tell me about it in Paris please."}]
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": bad, "agree": True})
check("a prompt that breaks a rule blocks confirmation and is marked by its position", not ok and res["errors"][0]["i"] == 11)
ok, res = ps.handle(db, hotel, who, {"action": "save", "prompts": prompts[:10]})
check("a draft can be saved at any time and is not used", ok and len(ps.state(db, hotel)["draft"]["prompts"]) == 10 and db.confirmed_prompts_for_key("hotel-opera.com") == [])
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": prompts, "agree": True})
a = ps.state(db, hotel)["active"]
check("confirming with the box ticked makes version 1, with who and when", ok and a["version"] == 1 and a["confirmed_by"] == who and a["confirmed_at"] and len(a["prompts"]) == 12, res)
cp = db.confirmed_prompts_for_key("hotel-opera.com")
check("from now on the audit asks exactly these prompts, word for word", [p["text"] for p in cp] == [p["text"] for p in prompts])
ok, res = ps.handle(db, hotel, who, {"action": "start_change"})
check("changing starts a copy; the confirmed set stays in use", ok and ps.state(db, hotel)["draft"]["base_version"] == 1 and len(db.confirmed_prompts_for_key("hotel-opera.com")) == 12)
new = [dict(p) for p in prompts]
new[0]["text"] = "Which upscale hotels in Paris are best for a quiet business trip with good Wi-Fi?"
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": new, "agree": True})
check("confirming a CHANGED set needs the second tick about comparability", not ok and "harder to compare" in res["error"])
ok, res = ps.handle(db, hotel, who, {"action": "confirm", "prompts": new, "agree": True, "agree_change": True})
check("with both ticks it becomes version 2, and the audit now asks the new prompts", ok and ps.state(db, hotel)["active"]["version"] == 2 and db.confirmed_prompts_for_key("hotel-opera.com")[0]["text"] == new[0]["text"], res)
check("version 1 is kept in the history", [s["version"] for s in ps.state(db, hotel)["history"]] == [2, 1])
ps.handle(db, hotel, who, {"action": "start_change"})
ok, res = ps.handle(db, hotel, who, {"action": "discard"})
check("discarding a change leaves the confirmed set as it was", ok and ps.state(db, hotel)["draft"] is None and ps.state(db, hotel)["active"]["version"] == 2)

print("4. the tab")
import prompts_view
html_ = prompts_view.panel({"active": None, "draft": {"prompts": prompts, "version": 0}, "history": []}, hotel, "/x", True)
check("before confirming the tab explains, warns about changing later, and has the confirm button disabled until ticked", all(w in html_ for w in ("Not confirmed yet", "harder to tell whether the hotel is really improving", "Confirm these prompts", "I am happy with these prompts")) and "We recommend 12 prompts" in html_)
html2 = prompts_view.panel(ps.state(db, hotel), hotel, "/x", True, 3)
check("once confirmed it shows the version, who and when, how many checks used it, and a Change button with the warning again", "Confirmed: version 2" in html2 and "3 checks have used it" in html2 and "Change these prompts" in html2)

print("5. who can change them")
db.create_user("gm@hotel-opera.com", "GM", __import__("accounts").hash_password("a-long-password-1"))
db.link_user(db.user_by_email("gm@hotel-opera.com")["id"], hid)
u = app.test_client()
u.post("/portal/signin", data={"email": "gm@hotel-opera.com", "password": "a-long-password-1"})
page = u.get("/portal").get_data(as_text=True)
tok = re.search(r'data-csrf="([^"]+)"', page).group(1)
check("the dashboard has a Prompts tab", 'data-name="prompts"' in page and "Prompts in use" in page or "Review the recommended prompts" in page or "Confirmed: version 2" in page)
check("a change needs the page's token", u.post(f"/portal/api/prompts/{hid}", json={"action": "start_change"}).status_code == 400)
r = u.post(f"/portal/api/prompts/{hid}", json={"action": "start_change"}, headers={"X-CSRF": tok})
check("a hotel user can start a change to their own prompts", r.status_code == 200 and r.get_json()["ok"])
other = db.create_hotel("Other", "other.com", "Lyon", "other.com")
check("but not another hotel's", u.post(f"/portal/api/prompts/{other}", json={"action": "start_change"}, headers={"X-CSRF": tok}).status_code == 401)
check("and not without signing in", app.test_client().post(f"/portal/api/prompts/{hid}", json={"action": "discard"}).status_code == 401)
adm = app.test_client()
adm.post("/admin/login", data={"password": "adm"})
pg = adm.get(f"/admin/hotel/{hid}").get_data(as_text=True)
atok = re.search(r'data-csrf="([^"]+)"', pg).group(1)
check("the operator can edit them too, from the hotel's admin page", adm.post(f"/admin/hotel/{hid}/prompts", json={"action": "discard"}, headers={"X-CSRF": atok}).status_code == 200 and adm.post(f"/admin/hotel/{hid}/prompts", json={"action": "discard"}).status_code == 400)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
