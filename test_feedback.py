"""
Offline tests for the 'useful / wrong' buttons: the route, the limits, the database record, the per-label summary the operator sees, and the buttons in the report. No network.
Run: python test_feedback.py
"""
import copy
import json
import os
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")
import audit_service
import backend
import server

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
recs = (REP.get("consultant") or {}).get("recommendations") or []
check("(setup) the sample report has recommendations to mark", len(recs) >= 2, len(recs))
REF = recs[0]["id"]


def fake_run(params, progress):
    return copy.deepcopy(REP)


DB = os.path.join(tempfile.gettempdir(), "hotel_feedback_test.db")
if os.path.exists(DB):
    os.remove(DB)
URL = "sqlite:///" + DB.replace("\\", "/")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "open-sesame"})
app = server.create_app(cfg, run_fn=fake_run)
c = app.test_client()
jid = c.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).get_json()["job"]
for _ in range(100):
    j = c.get(f"/api/job/{jid}").get_json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.1)
tok = j["token"]

print("1. the buttons are in the report")
page = c.get(f"/r/{tok}").data.decode("utf8")
check("each recommendation card in the action plan carries the two buttons, tied to its reference", 'class="fb"' in page and 'data-v="useful"' in page and 'data-v="wrong"' in page and f'data-ref="{REF}"' in page)
js = open(os.path.join(HERE, "web", "static", "app.js"), encoding="utf8").read()
check("the script posts to /api/feedback with the report's own token and asks for a note only on 'wrong'", "/api/feedback" in js and "window.prompt" in js and "location.pathname.match" in js)

print("2. the route")
ok = c.post("/api/feedback", json={"token": tok, "ref": REF, "verdict": "wrong", "note": "This hotel does have a spa.\x00\x1b"})
check("a mark on a real recommendation of the visitor's own report is saved", ok.status_code == 200 and ok.get_json()["ok"])
check("it also marks one as useful", c.post("/api/feedback", json={"token": tok, "ref": REF, "verdict": "useful"}).status_code == 200)
check("an unknown verdict, a missing reference and a malformed token are refused", c.post("/api/feedback", json={"token": tok, "ref": REF, "verdict": "great"}).status_code == 400
      and c.post("/api/feedback", json={"token": tok, "ref": "", "verdict": "useful"}).status_code == 400 and c.post("/api/feedback", json={"token": "short", "ref": REF, "verdict": "useful"}).status_code == 400)
check("a token that matches no report is 404, so nobody can write feedback onto a report that is not theirs", c.post("/api/feedback", json={"token": "A" * 30, "ref": REF, "verdict": "useful"}).status_code == 404)
spam = server.create_app(cfg, run_fn=fake_run).test_client()
t2 = spam.get("/").status_code
codes = [spam.post("/api/feedback", json={"token": tok, "ref": REF, "verdict": "useful"}).status_code for _ in range(90)]
check("one visitor is limited to a sensible number of marks an hour", 429 in codes and codes.count(200) <= 80, (codes.count(200), codes.count(429)))

print("3. what is stored")
s = backend.open_store(URL)
rows = s.recent_feedback(500)
w = next(r for r in rows if r["verdict"] == "wrong")
check("the mark is stored with the run, the reference, the recommendation's own evidence label and source, and the note with control characters removed", w["ref"] == REF and w["run_id"] and w["label"] in ("Confirmed", "Likely", "Worth checking", None) and w["note"] == "This hotel does have a spa.", str(w))
sm = {d["label"]: d for d in s.feedback_summary()}
lab = w["label"] or "(none)"
check("the summary counts useful and wrong per label and gives the share marked useful", sm[lab]["wrong"] >= 1 and sm[lab]["useful"] >= 1 and sm[lab]["useful_pct"] is not None and 0 <= sm[lab]["useful_pct"] <= 100, str(sm))

print("4. the operator's page")
ca = app.test_client()
ca.post("/admin/login", data={"password": "open-sesame"})
adm = ca.get("/admin/feedback")
check("the admin Feedback page shows how each label was marked and the latest marks", adm.status_code == 200 and b"How each evidence label was marked" in adm.data and b"Most recent" in adm.data)
check("without the password it is closed", app.test_client().get("/admin/feedback").status_code in (302, 403))

print("5. signing in to the admin pages when the site also has a password")
cfg2 = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "open-sesame", "SITE_PASSWORD": "site-gate", "SECRET_KEY": "k" * 32})
a2 = server.create_app(cfg2, run_fn=fake_run)
ca2 = a2.test_client()
check("without the site password the admin sign-in is behind the site's own sign-in", ca2.get("/admin/login").status_code == 302)
ca2.post("/login", data={"password": "site-gate", "next": "/admin"})
r = ca2.post("/admin/login", data={"password": "open-sesame"})
check("the admin sign-in succeeds and does NOT wipe the site sign-in (it used to, which sent you straight back to the site's sign-in and looked like a wrong password)", r.status_code == 302 and "/admin/overview" in r.headers["Location"] and ca2.get("/admin").status_code == 200 and ca2.get("/admin/runs").status_code == 200)
ca2.post("/admin/logout")
check("signing out of the admin pages leaves the site sign-in alone, and closes the admin pages", ca2.get("/").status_code == 200 and ca2.get("/admin").status_code == 302)
c3 = a2.test_client()
c3.post("/login", data={"password": "site-gate"}); c3.post("/admin/login", data={"password": "open-sesame"}); c3.post("/login", data={"password": "site-gate"})
check("signing in to the site again does not sign you out of the admin pages", c3.get("/admin").status_code == 200)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
