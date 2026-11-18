"""
The two doors of the live site, end to end against a real (SQLite) database:
  1. the admin pages: a one-off "Quick audit" of any hotel is saved and opens as a report, but it is NOT added to the portfolio and is never picked up by the weekly checks;
  2. the hotel sign-in: an invited hotel user sees only their own hotel, cannot start audits and cannot open a one-off report.
Run: python test_oneoff.py
"""
import copy
import json
import os
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")
import accounts
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
URL = "sqlite:///" + os.path.join(TMP, "o.db")
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))


def fake_run(params, progress_cb=None):
    r = copy.deepcopy(BASE)
    site = params["website"]
    r["meta"].update(base=f"https://www.{site}/", website=site, hotel=params["hotel"] or site, run_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
    return r


cfg = audit_service.Config({"RENDER": "true", "DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "SECRET_KEY": "k" * 32, "CRON_TOKEN": "cron-token-abcdef"})
app = server.create_app(cfg, run_fn=fake_run)
db = backend.open_store(URL)
hid = db.create_hotel("Portfolio Hotel", "portfolio-hotel.com", "Paris", "portfolio-hotel.com")


def run_audit(client, site, hotel):
    r = client.post("/api/audit", json={"website": site, "hotel": hotel, "city": "Zurich"})
    if r.status_code != 200:
        return r.status_code, None
    jid = r.get_json()["job"]
    for _ in range(200):
        j = client.get(f"/api/job/{jid}").get_json()
        if j.get("status") in ("done", "error"):
            return 200, j.get("token")
        time.sleep(0.05)
    return 200, None


print("1. the admin runs a one-off Quick audit")
admin = app.test_client()
admin.post("/admin/login", data={"password": "adm-pass-1"})
check("the Quick audit page opens for the admin", admin.get("/admin/audit").status_code == 200)
code, tok = run_audit(admin, "oneoff-hotel.ch", "One Off Hotel")
check("the audit runs and produces a report", code == 200 and bool(tok), code)
check("the admin can open the report", tok and admin.get(f"/r/{tok}").status_code == 200)
check("it is saved in the run history", any(r["hotel_key"] == "oneoff-hotel.ch" for r in db.list_runs()))
check("it is NOT added to the portfolio", db.hotel_by_key("oneoff-hotel.ch") is None and [h["hotel_key"] for h in db.list_hotels()] == ["portfolio-hotel.com"])
due = app.extensions["weekly"].due()
check("the weekly checks never pick it up (only portfolio hotels are ever due)", all(h["hotel_key"] != "oneoff-hotel.ch" for h in due) and any(h["id"] == hid for h in due))
check("it does not appear on the Portfolio page", "oneoff-hotel.ch" not in admin.get("/admin/portfolio").get_data(as_text=True) and "One Off Hotel" not in admin.get("/admin/portfolio").get_data(as_text=True))

print("2. an invited hotel user of a portfolio hotel")
uid = db.create_user("gm@portfolio-hotel.com", "GM", accounts.hash_password("a-long-password-1"))
db.link_user(uid, hid)
hotel = app.test_client()
r = hotel.post("/portal/signin", data={"email": "gm@portfolio-hotel.com", "password": "a-long-password-1"})
check("signs in with their own email and password and lands on their dashboard", r.status_code == 302 and r.headers["Location"].endswith("/portal"))
check("the bare address takes them to their dashboard", hotel.get("/").headers["Location"].endswith("/portal"))
check("they cannot start an audit", hotel.post("/api/audit", json={"website": "anything.com"}).status_code == 401)
check("they cannot open the Quick audit page", hotel.get("/admin/audit").status_code == 302)
check("they cannot open a one-off report", tok and hotel.get(f"/r/{tok}").status_code == 302)
check("they cannot open the admin pages", hotel.get("/admin/portfolio").status_code == 302)
wrong = app.test_client().post("/portal/signin", data={"email": "gm@portfolio-hotel.com", "password": "wrong-password"})
check("a wrong password does not get in", wrong.status_code == 200 and b"do not match" in wrong.data)

print("3. nobody signed in")
anon = app.test_client()
check("the bare address shows the hotel sign-in", anon.get("/").headers["Location"].endswith("/portal/signin"))
check("cannot run an audit", anon.post("/api/audit", json={"website": "x.com"}).status_code == 401)
check("cannot open a report", tok and anon.get(f"/r/{tok}").status_code == 302)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
