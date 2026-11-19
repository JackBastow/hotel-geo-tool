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

print("5. the main admin still sees everything, and the two sign-ins are separate")
a = app.test_client()
a.post("/admin/login", data={"password": "adm-pass-1"})
check("the main admin lists the individual hotels and points to the separate admin", "Solo Hotel" in a.get("/admin/individual").get_data(as_text=True) and "/hotels-admin" in a.get("/admin/individual").get_data(as_text=True))
check("but its sign-in does not open the separate admin", a.get("/hotels-admin").status_code == 302)
c.post("/hotels-admin/logout")
check("signing out of the separate admin closes it", c.get("/hotels-admin").status_code == 302 and c.get(f"/r/{runs['Solo Hotel']}").status_code == 302)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
