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

cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "SECRET_KEY": "k" * 32, "REQUIRE_SIGNIN": "1"})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
reports = app.extensions["reports"]

print("1. the operator adds a hotel to each")
admin = app.test_client()
admin.post("/admin/login", data={"password": "adm-pass-1"})
page = admin.get("/admin/individual").get_data(as_text=True)
check("there is an 'Individual hotels' page in the admin menu, saying what it is", "Individual hotels" in page and "not</b> part of the Westmont portfolio" in page and "Add an individual hotel" in page)
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
check("its add form puts the hotel in the individual group", 'name="grp" value="individual"' in page)
r = admin.post("/admin/portfolio/add", data={"csrf": csrf, "grp": "individual", "name": "Solo Hotel", "website": "solo-hotel.example", "city": "York"})
solo = db.hotel_by_key("solo-hotel.example")
check("an individual hotel is added and its page opens", r.status_code == 302 and solo and solo["grp"] == "individual" and r.headers["Location"].endswith(f"/admin/hotel/{solo['id']}"))
check("with weekly checks on, like any hotel", solo["weekly"] == 1)
admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "Westmont One", "website": "westmont-one.example", "city": "Leeds"})
wm = db.hotel_by_key("westmont-one.example")
check("the normal add (no group given) still goes into the portfolio", wm and wm["grp"] == "portfolio")
reports.save(report("solo-hotel.example", "Solo Hotel", 40, "2026-11-02T05:00:00+00:00"))
reports.save(report("solo-hotel.example", "Solo Hotel", 50, "2026-11-09T05:00:00+00:00"))
reports.save(report("westmont-one.example", "Westmont One", 80, "2026-11-02T05:00:00+00:00"))
reports.save(report("westmont-one.example", "Westmont One", 82, "2026-11-09T05:00:00+00:00"))

print("2. each page shows only its own hotels")
pf = admin.get("/admin/portfolio").get_data(as_text=True)
ind = admin.get("/admin/individual").get_data(as_text=True)
check("the portfolio lists only portfolio hotels", "Westmont One" in pf and "Solo Hotel" not in pf)
check("the individual page lists only individual hotels", "Solo Hotel" in ind and "Westmont One" not in ind)
_rows, tot = progress.portfolio_summary(db)
check("the portfolio's totals leave the individual hotel out", tot["hotels"] == 1 and tot["avg_latest"] == 82, tot)
f = analysis.figures(db, db.runs() if hasattr(db, "runs") else [])
check("so does the Overview", f["tiles"]["hotels"] == 1 and [r["hotel"]["name"] for r in f["rows"]] == ["Westmont One"])
ov = admin.get("/admin/overview").get_data(as_text=True)
check("and the Overview does not call its audits 'not registered'", "Solo Hotel" not in ov and "not registered" not in ov, ov[ov.find("not registered") - 200:ov.find("not registered") + 50] if "not registered" in ov else "")

print("3. the individual hotel works like any other: page, invite, login")
hp = admin.get(f"/admin/hotel/{solo['id']}").get_data(as_text=True)
check("its page says where it is and offers a move to the portfolio", "In: <b><a href=\"/admin/individual\">Individual hotels</a>" in hp and "Move to Portfolio" in hp and "data-confirm=" in hp)
check("and the admin menu highlights Individual hotels, not Portfolio", '<a href="/admin/individual" class="on">' in hp and '<a href="/admin/portfolio" class="">' in hp, re.findall(r'<a[^>]*admin/(?:individual|portfolio)[^>]*>', hp)[:3])
page = admin.post(f"/admin/hotel/{solo['id']}/invite", data={"csrf": csrf, "email": "owner@solo-hotel.example"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
u = app.test_client()
form = u.get(link).get_data(as_text=True)
c2 = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
u.post(link, data={"csrf": c2, "name": "Owner", "password": "a-long-password-1", "password2": "a-long-password-1"})
mine = u.get("/portal").get_data(as_text=True)
check("its owner signs in with the invite and sees their own hotel", u.get("/portal").status_code == 200 and "Solo Hotel" in mine)
check("and never another hotel", "Westmont One" not in mine and u.get(f"/admin/hotel/{wm['id']}", follow_redirects=False).status_code == 302)

print("4. checks and moves")
W = app.extensions["weekly"]
check("the weekly job still checks individual hotels (their weekly switch decides)", solo["id"] in {h["id"] for h in W.due(db, force_ids={solo["id"], wm["id"]})})
started = []
W.start = lambda force_ids=None: (started.append(set(force_ids or ())), (True, len(force_ids or ())))[1]
admin.post("/admin/portfolio/run-all", data={"csrf": csrf, "grp": "individual"})
check("'run every hotel now' on the individual page runs only the individual hotels", started and started[-1] == {solo["id"]}, started)
admin.post("/admin/portfolio/run-all", data={"csrf": csrf})
check("and on the portfolio page only the portfolio's", started[-1] == {wm["id"]}, started)
r = admin.post(f"/admin/hotel/{solo['id']}/group", data={"csrf": csrf, "grp": "portfolio"})
check("an individual hotel can be moved into the portfolio, keeping everything", db.get_hotel(solo["id"])["grp"] == "portfolio" and len(db.users_for_hotel(solo["id"])) == 1
      and progress.portfolio_summary(db)[1]["hotels"] == 2)
admin.post(f"/admin/hotel/{solo['id']}/group", data={"csrf": csrf, "grp": "nonsense"})
check("an unknown group is never stored", db.get_hotel(solo["id"])["grp"] == "portfolio")
check("a move needs the form's token", admin.post(f"/admin/hotel/{solo['id']}/group", data={"grp": "individual"}).status_code == 400)
check("and only the admin can do it", u.post(f"/admin/hotel/{solo['id']}/group", data={"csrf": c2, "grp": "individual"}, follow_redirects=False).status_code in (302, 401, 403))
again = admin.post("/admin/portfolio/add", data={"csrf": csrf, "grp": "individual", "name": "Solo again", "website": "www.solo-hotel.example", "city": "York"})
check("adding a website that is already registered opens it and says so, adding nothing", again.headers["Location"].endswith(f"/admin/hotel/{solo['id']}?msg=exists")
      and "already registered" in admin.get(again.headers["Location"]).get_data(as_text=True) and len(db.list_hotels()) == 2)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
