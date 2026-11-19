"""
The separate individual-hotels admin at /hotels-admin: its own address and password, and it can only see and manage the individual hotels.
Run: python test_hotels_admin.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import audit_service
import backend
import headline
import server

headline.attach = lambda r: None
fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


TMP = tempfile.mkdtemp()
URL = "sqlite:///" + os.path.join(TMP, "h.db")
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))


def report(site, name, run_at):
    r = copy.deepcopy(BASE)
    r["meta"].update(base=f"https://www.{site}/", website=site, hotel=name, run_at=run_at)
    return r


print("0. without its password set, the separate admin does not exist")
app0 = server.create_app(audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "SECRET_KEY": "k" * 32, "RENDER": "true"}), run_fn=lambda p, cb=None: None)
c0 = app0.test_client()
check("its pages answer 'not found'", c0.get("/hotels-admin/login").status_code == 404 and c0.post("/hotels-admin/login", data={"password": ""}).status_code == 404)

cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "INDIVIDUAL_ADMIN_PASSWORD": "ind-pass-1", "SECRET_KEY": "k" * 32, "RENDER": "true"})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
reports = app.extensions["reports"]
pf_id = db.create_hotel("Westmont One", "westmont-one.example", "Leeds", "westmont-one.example")
solo_id = db.create_hotel("Solo Hotel", "solo-hotel.example", "York", "solo-hotel.example", grp="individual")
t_pf = reports.save(report("westmont-one.example", "Westmont One", "2026-11-02T05:00:00+00:00"))
t_solo = reports.save(report("solo-hotel.example", "Solo Hotel", "2026-11-02T05:00:00+00:00"))
runs = {"Westmont One": db.hotel_runs("westmont-one.example")[0]["access_token"], "Solo Hotel": db.hotel_runs("solo-hotel.example")[0]["access_token"]}

print("1. its own sign-in")
c = app.test_client()
check("its pages need its own sign-in", c.get("/hotels-admin").status_code == 302 and "/hotels-admin/login" in c.get("/hotels-admin").headers["Location"])
lp = c.get("/hotels-admin/login").get_data(as_text=True)
check("the sign-in page has no Westmont branding", "Westmont" not in lp and "westmont.png" not in lp)
check("the main admin password does not open it", "Wrong password" in c.post("/hotels-admin/login", data={"password": "adm-pass-1"}).get_data(as_text=True))
r = c.post("/hotels-admin/login", data={"password": "ind-pass-1"})
check("its own password does", r.status_code == 302 and r.headers["Location"].endswith("/hotels-admin"))

print("2. it sees and manages only the individual hotels")
home = c.get("/hotels-admin").get_data(as_text=True)
check("the list shows the individual hotel and not the portfolio's", "Solo Hotel" in home and "Westmont One" not in home)
check("and says nothing about Westmont", "Westmont" not in home and "westmont.png" not in home)
check("the main admin pages stay closed to it", all(c.get(p).status_code == 302 for p in ("/admin", "/admin/portfolio", "/admin/individual", f"/admin/hotel/{solo_id}", "/admin/runs", "/admin/audit")))
check("a portfolio hotel's page is 'not found'", c.get(f"/hotels-admin/hotel/{pf_id}").status_code == 404)
hp = c.get(f"/hotels-admin/hotel/{solo_id}").get_data(as_text=True)
check("an individual hotel's page opens, with its controls, and no move to the portfolio", "Make an invite link" in hp and "Run a check now" in hp and "Move to" not in hp and "Westmont" not in hp)
check("its links stay inside the separate admin", f'action="/hotels-admin/hotel/{solo_id}/invite"' in hp and "/admin/hotel/" not in hp.replace("/hotels-admin/hotel/", ""))
csrf = re.search(r'name="csrf" value="([^"]+)"', hp).group(1)
page = c.post(f"/hotels-admin/hotel/{solo_id}/invite", data={"csrf": csrf, "email": "owner@solo-hotel.example"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page)
check("it can make an invite link", bool(link))
check("but not for a portfolio hotel", c.post(f"/hotels-admin/hotel/{pf_id}/invite", data={"csrf": csrf, "email": "x@y.example"}).status_code == 404 and not db.open_invites(pf_id))
for path in ("weekly", "run", "reset-prompts"):
    check(f"nor '{path}' on a portfolio hotel", c.post(f"/hotels-admin/hotel/{pf_id}/{path}", data={"csrf": csrf}).status_code == 404)
check("nor its live status or prompts", c.get(f"/hotels-admin/hotel/{pf_id}/status").status_code == 404
      and c.post(f"/hotels-admin/hotel/{pf_id}/prompts", json={}, headers={"X-CSRF": csrf}).status_code == 404)
check("there is no move route here", c.post(f"/hotels-admin/hotel/{solo_id}/group", data={"csrf": csrf, "grp": "portfolio"}).status_code in (404, 405) and db.get_hotel(solo_id)["grp"] == "individual")
check("a form without its token is refused", c.post(f"/hotels-admin/hotel/{solo_id}/weekly", data={}).status_code == 400)

print("3. adding hotels")
r = c.post("/hotels-admin/add", data={"csrf": csrf, "name": "New Inn", "website": "new-inn.example", "city": "Ripon", "grp": "portfolio"})
db.set_hotel(db.hotel_by_key("new-inn.example")["id"], setup="")  # behaves as a hotel set up before profiles (test_setup_flow.py covers the new set-up)
ni = db.hotel_by_key("new-inn.example")
check("a hotel added here is always individual, whatever the form says", ni and ni["grp"] == "individual" and r.headers["Location"].endswith(f"/hotels-admin/hotel/{ni['id']}"))
r = c.post("/hotels-admin/add", data={"csrf": csrf, "name": "Copy", "website": "westmont-one.example", "city": "Leeds"})
check("a website already in the portfolio is not added, opened or named", r.headers["Location"].endswith("/hotels-admin?msg=taken") and "Westmont One" not in c.get(r.headers["Location"]).get_data(as_text=True)
      and db.get_hotel(pf_id)["grp"] == "portfolio")
started = []
W = app.extensions["weekly"]
W.start = lambda force_ids=None: (started.append(set(force_ids or ())), (True, len(force_ids or ())))[1]
c.post("/hotels-admin/run-all", data={"csrf": csrf, "grp": "portfolio"})
check("'run every hotel' runs only individual hotels", started and started[-1] == {solo_id, ni["id"]}, started)

print("4. reports")
check("it can open an individual hotel's report", c.get(f"/r/{runs['Solo Hotel']}").status_code == 200)
check("but not a portfolio hotel's", c.get(f"/r/{runs['Westmont One']}").status_code == 302)

print("4b. correcting a hotel's town")
import prompt_sets
solo = db.get_hotel(solo_id)
old_town = (db.get_report(db.hotel_runs("solo-hotel.example")[0]["id"])["meta"].get("city") or "")
c.get(f"/hotels-admin/hotel/{solo_id}")                       # the page builds a recommended set from the saved check
check("the hotel page shows its name and town, editable", 'name="city" value="York"' in c.get(f"/hotels-admin/hotel/{solo_id}").get_data(as_text=True))
check("(a set was built from the check)", prompt_sets.state(db, solo)["draft"] is not None)
page = c.post(f"/hotels-admin/hotel/{solo_id}/details", data={"csrf": csrf, "name": "Solo Hotel & Spa", "city": "Karlshamn"}).get_data(as_text=True)
solo = db.get_hotel(solo_id)
check("the name and town are saved", solo["name"] == "Solo Hotel & Spa" and solo["city"] == "Karlshamn" and "The town is now <b>Karlshamn</b>" in page)
check("the old town's recommended prompts are dropped, and not rebuilt from the check about the old town", prompt_sets.state(db, solo)["draft"] is None, (old_town, prompt_sets.state(db, solo)["draft"]))
check("a country is refused", "is a country" in c.post(f"/hotels-admin/hotel/{solo_id}/details", data={"csrf": csrf, "name": "Solo Hotel & Spa", "city": "Sweden"}).get_data(as_text=True) and db.get_hotel(solo_id)["city"] == "Karlshamn")
check("and a portfolio hotel cannot be renamed from here", c.post(f"/hotels-admin/hotel/{pf_id}/details", data={"csrf": csrf, "name": "X", "city": "Y"}).status_code == 404 and db.get_hotel(pf_id)["name"] == "Westmont One")

print("4c. deleting a check that should never have counted")
reports.save(report("solo-hotel.example", "Solo Hotel", "2026-11-19T16:30:00+00:00"))
hr = db.hotel_runs("solo-hotel.example")
old_id, new_id = hr[-1]["id"], hr[0]["id"]
acts = db.list_actions(solo_id)
check("(the checks raised actions)", len(acts) > 2, len(acts))
mine = acts[0]
db.update_action(mine["id"], status="working")
hp = c.get(f"/hotels-admin/hotel/{solo_id}").get_data(as_text=True)
check("the hotel page lists its checks with a delete button", f"/hotels-admin/hotel/{solo_id}/delete-run/{old_id}" in hp and "Delete a check" in hp)
check("a check of another hotel cannot be deleted from here", c.post(f"/hotels-admin/hotel/{solo_id}/delete-run/{db.hotel_runs('westmont-one.example')[0]['id']}", data={"csrf": csrf}).status_code == 404
      and db.hotel_runs("westmont-one.example"))
check("nor from a portfolio hotel's address", c.post(f"/hotels-admin/hotel/{pf_id}/delete-run/{old_id}", data={"csrf": csrf}).status_code == 404)
W.active = lambda h_: h_ == solo_id
check("not while a check is running for the hotel", "A check is running" in c.post(f"/hotels-admin/hotel/{solo_id}/delete-run/{old_id}", data={"csrf": csrf}).get_data(as_text=True) and len(db.hotel_runs("solo-hotel.example")) == 2)
W.active = lambda h_: False
page = c.post(f"/hotels-admin/hotel/{solo_id}/delete-run/{old_id}", data={"csrf": csrf}).get_data(as_text=True)
left = db.hotel_runs("solo-hotel.example")
check("the old check is gone and the new one stays", [r["id"] for r in left] == [new_id] and "Check deleted" in page and "1 check left" in page)
after = db.list_actions(solo_id)
check("what the hotel is working on stays", any(a["id"] == mine["id"] for a in after))
check("the hotel still has its actions from the check that remains", len(after) > 1, len(after))
check("a form without its token is refused", c.post(f"/hotels-admin/hotel/{solo_id}/delete-run/{new_id}", data={}).status_code == 400 and db.hotel_runs("solo-hotel.example"))
runs["Solo Hotel"] = left[0]["access_token"]

print("5. the main admin is the portfolio only, and the two sign-ins are separate")
a = app.test_client()
a.post("/admin/login", data={"password": "adm-pass-1"})
check("the main admin no longer lists the individual hotels", "Solo Hotel" not in a.get("/admin/portfolio").get_data(as_text=True) and "Individual hotels" not in a.get("/admin/portfolio").get_data(as_text=True))
check("but its sign-in does not open the separate admin", a.get("/hotels-admin").status_code == 302)
c.post("/hotels-admin/logout")
check("signing out of the separate admin closes it", c.get("/hotels-admin").status_code == 302 and c.get(f"/r/{runs['Solo Hotel']}").status_code == 302)

print("6. signing in elsewhere in the same browser does not break pages already open")
b = app.test_client()
b.post("/hotels-admin/login", data={"password": "ind-pass-1"})
tok_open = re.search(r'name="csrf" value="([^"]+)"', b.get(f"/hotels-admin/hotel/{solo_id}").get_data(as_text=True)).group(1)      # the hotel page, open in one tab
b.post("/admin/login", data={"password": "adm-pass-1"})                                                                              # the main admin, signed in to in another tab
b.post("/admin/logout")
started.clear()
r = b.post(f"/hotels-admin/hotel/{solo_id}/run", data={"csrf": tok_open})
check("a button on the page opened before still works", r.status_code == 302 and started and started[-1] == {solo_id}, (r.status_code, started))
r = b.post(f"/hotels-admin/hotel/{solo_id}/run", data={"csrf": "not-the-token"})
txt = r.get_data(as_text=True)
check("a truly out-of-date form says so plainly, and changes nothing", r.status_code == 400 and "That page was out of date" in txt and "Nothing was changed" in txt and "Bad Request" not in txt)
check("an out-of-date request from a script gets a short JSON reply", b.post(f"/hotels-admin/hotel/{solo_id}/prompts", json={}, headers={"X-CSRF": "x"}).get_json() == {"ok": False, "error": "Please reload the page and try again."})

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
