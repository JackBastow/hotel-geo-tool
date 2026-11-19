"""
Individual hotels: set up like the portfolio's (a login by invite, weekly checks, their own dashboard) but kept out of the Westmont portfolio and its totals, with their own admin page.
Run: python test_groups.py
"""
import copy
import json
import os
import re
import sqlite3
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import analysis
import audit_service
import backend
import headline
import progress
import server

headline.attach = lambda r: None
fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


TMP = tempfile.mkdtemp()
URL = "sqlite:///" + os.path.join(TMP, "g.db")
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))


def report(site, name, score, run_at):
    r = copy.deepcopy(BASE)
    r["meta"].update(base=f"https://www.{site}/", website=site, hotel=name, run_at=run_at)
    r["headline"]["score"] = score
    r["consultant"]["coverage"] = {"pages_read": 8, "pages_attempted": 8}
    return r


print("0. an older database: the hotels already there stay in the portfolio")
old = os.path.join(TMP, "old.db")
con = sqlite3.connect(old)
con.execute("CREATE TABLE hotels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, website TEXT, city TEXT, hotel_key TEXT UNIQUE, tier TEXT, audiences TEXT, weekly INTEGER, active INTEGER, created TEXT, last_attempt TEXT, last_error TEXT)")
con.execute("INSERT INTO hotels (name, website, city, hotel_key, weekly, active) VALUES ('Old Hotel', 'old.example', 'Bath', 'old.example', 1, 1)")
con.commit()
con.close()
odb = backend.open_store("sqlite:///" + old)
check("the new column is added without touching the hotel, which counts as portfolio", [h["name"] for h in odb.list_hotels(grp="portfolio")] == ["Old Hotel"] and odb.list_hotels(grp="individual") == [])

cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "INDIVIDUAL_ADMIN_PASSWORD": "ind-pass-1", "SECRET_KEY": "k" * 32, "REQUIRE_SIGNIN": "1"})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
reports = app.extensions["reports"]

print("1. the operator adds a hotel to each")
admin = app.test_client()
admin.post("/admin/login", data={"password": "adm-pass-1"})
pfp = admin.get("/admin/portfolio").get_data(as_text=True)
check("the main admin menu no longer has an 'Individual hotels' page", "Individual hotels" not in pfp and 'href="/admin/individual"' not in pfp)
check("its old address goes to the separate hotels admin", admin.get("/admin/individual").headers.get("Location", "").endswith("/hotels-admin"))
csrf = re.search(r'name="csrf" value="([^"]+)"', pfp).group(1)
admin.post("/admin/portfolio/add", data={"csrf": csrf, "grp": "individual", "name": "X", "website": "x-hotel.example", "city": "York"})
check("the main admin cannot add an individual hotel, even by editing the form", db.hotel_by_key("x-hotel.example")["grp"] == "portfolio")
ind = app.test_client()
ind.post("/hotels-admin/login", data={"password": "ind-pass-1"})
ic = re.search(r'name="csrf" value="([^"]+)"', ind.get("/hotels-admin").get_data(as_text=True)).group(1)
r = ind.post("/hotels-admin/add", data={"csrf": ic, "name": "Solo Hotel", "website": "solo-hotel.example", "city": "York"})
db.set_hotel(db.hotel_by_key("solo-hotel.example")["id"], setup="")  # behaves as a hotel set up before profiles (test_setup_flow.py covers the new set-up)
db.set_hotel(db.hotel_by_key("x-hotel.example")["id"], setup="")
solo = db.hotel_by_key("solo-hotel.example")
check("an individual hotel is added in the hotels admin and its page opens", r.status_code == 302 and solo and solo["grp"] == "individual" and r.headers["Location"].endswith(f"/hotels-admin/hotel/{solo['id']}"))
check("with weekly checks on, like any hotel", solo["weekly"] == 1)
admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "Westmont One", "website": "westmont-one.example", "city": "Leeds"})
db.set_hotel(db.hotel_by_key("westmont-one.example")["id"], setup="")  # behaves as a hotel set up before profiles (test_setup_flow.py covers the new set-up)
wm = db.hotel_by_key("westmont-one.example")
check("the normal add still goes into the portfolio", wm and wm["grp"] == "portfolio")
reports.save(report("solo-hotel.example", "Solo Hotel", 40, "2026-11-02T05:00:00+00:00"))
reports.save(report("solo-hotel.example", "Solo Hotel", 50, "2026-11-09T05:00:00+00:00"))
reports.save(report("westmont-one.example", "Westmont One", 80, "2026-11-02T05:00:00+00:00"))
reports.save(report("westmont-one.example", "Westmont One", 82, "2026-11-09T05:00:00+00:00"))

print("2. each page shows only its own hotels")
pf = admin.get("/admin/portfolio").get_data(as_text=True)
indp = ind.get("/hotels-admin").get_data(as_text=True)
check("the portfolio lists only portfolio hotels", "Westmont One" in pf and "Solo Hotel" not in pf)
check("the hotels admin lists only individual hotels", "Solo Hotel" in indp and "Westmont One" not in indp)
_rows, tot = progress.portfolio_summary(db)
check("the portfolio's totals leave the individual hotel out", tot["hotels"] == 2 and tot["avg_latest"] == 82, tot)
f = analysis.figures(db, db.runs() if hasattr(db, "runs") else [])
check("so does the Overview", f["tiles"]["hotels"] == 2 and "Solo Hotel" not in [r["hotel"]["name"] for r in f["rows"]])
ov = admin.get("/admin/overview").get_data(as_text=True)
check("and the Overview does not call its audits 'not registered'", "Solo Hotel" not in ov and "not registered" not in ov, ov[ov.find("not registered") - 200:ov.find("not registered") + 50] if "not registered" in ov else "")

print("3. the individual hotel works like any other: page, invite, login")
check("the main admin cannot open it", admin.get(f"/admin/hotel/{solo['id']}").status_code == 404)
hp = ind.get(f"/hotels-admin/hotel/{solo['id']}").get_data(as_text=True)
check("its page has no move between groups", "Move to" not in hp and "/group\"" not in hp)
page = ind.post(f"/hotels-admin/hotel/{solo['id']}/invite", data={"csrf": ic, "email": "owner@solo-hotel.example"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
u = app.test_client()
form = u.get(link).get_data(as_text=True)
c2 = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
u.post(link, data={"csrf": c2, "name": "Owner", "password": "a-long-password-1", "password2": "a-long-password-1"})
mine = u.get("/portal").get_data(as_text=True)
check("its owner signs in with the invite and sees their own hotel", u.get("/portal").status_code == 200 and "Solo Hotel" in mine)
check("and never another hotel", "Westmont One" not in mine and u.get(f"/admin/hotel/{wm['id']}", follow_redirects=False).status_code == 302)

print("4. checks")
W = app.extensions["weekly"]
check("the weekly job still checks individual hotels (their weekly switch decides)", solo["id"] in {h["id"] for h in W.due(db, force_ids={solo["id"], wm["id"]})})
started = []
W.start = lambda force_ids=None: (started.append(set(force_ids or ())), (True, len(force_ids or ())))[1]
ind.post("/hotels-admin/run-all", data={"csrf": ic})
check("'run every hotel now' in the hotels admin runs only the individual hotels", started and started[-1] == {solo["id"]}, started)
admin.post("/admin/portfolio/run-all", data={"csrf": csrf, "grp": "individual"})
check("and in the main admin only the portfolio's, whatever the form says", started[-1] == {wm["id"], db.hotel_by_key("x-hotel.example")["id"]}, started)
check("the main admin has no move route", admin.post(f"/admin/hotel/{solo['id']}/group", data={"csrf": csrf, "grp": "portfolio"}).status_code in (404, 405) and db.get_hotel(solo["id"])["grp"] == "individual")
again = admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "Solo again", "website": "www.solo-hotel.example", "city": "York"})
check("adding an individual hotel's website in the main admin says where it is, adding nothing", again.headers["Location"].endswith("/admin/portfolio?msg=taken")
      and "already registered as an individual hotel" in admin.get(again.headers["Location"]).get_data(as_text=True) and len(db.list_hotels()) == 3)
again = admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "W again", "website": "www.westmont-one.example", "city": "Leeds"})
check("adding a portfolio website again opens it and says so", again.headers["Location"].endswith(f"/admin/hotel/{wm['id']}?msg=exists") and "already registered" in admin.get(again.headers["Location"]).get_data(as_text=True))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
