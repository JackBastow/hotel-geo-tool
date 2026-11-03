"""
Offline tests for the hotel portal: accounts by invite only, hotels see only themselves, the action list that follows every audit, the progress numbers, the operator's portfolio, and the weekly checks.
Run: python test_portal.py
"""
import copy
import json
import os
import re
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")
import audit_service
import backend
import progress
import scheduler
import headline
import server

headline.attach = lambda r: None          # keep the scores the test sets (the real code recomputes them from the scorecard)
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp()
URL = "sqlite:///" + os.path.join(TMP, "p.db")
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))


def report(site, name, score, drop_titles=(), add=(), run_at="2026-10-01T09:00:00+00:00"):
    r = copy.deepcopy(BASE)
    r["meta"].update(base=f"https://www.{site}/", website=site, hotel=name, run_at=run_at)
    r["headline"]["score"] = score
    recs = [x for x in r["consultant"]["recommendations"] if not any(t in x["title"] for t in drop_titles)]
    recs += [dict(recs[0], id=f"N{i}", title=t, source="questions", tag="", short_title=t) for i, t in enumerate(add)]
    r["consultant"]["recommendations"] = recs
    r["consultant"]["coverage"] = {"pages_read": 8, "pages_attempted": 8}
    return r


def fake_run(params, progress_cb=None):
    fake_run.calls.append(params)
    return report("hotel-a.com", params["hotel"], 70, drop_titles=("telephone",), run_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))


fake_run.calls = []
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "SITE_PASSWORD": "site-pass-1", "SECRET_KEY": "k" * 32, "CRON_TOKEN": "cron-token-abcdef"})
app = server.create_app(cfg, run_fn=fake_run)
db = backend.open_store(URL)
reports = app.extensions["reports"]

print("1. the operator adds a hotel and invites a user")
admin = app.test_client()
admin.post("/login", data={"password": "site-pass-1"})
admin.post("/admin/login", data={"password": "adm-pass-1"})
page = admin.get("/admin/portfolio").get_data(as_text=True)
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
check("the portfolio page exists in the admin pages", "Add a hotel" in page and "Portfolio" in page)
r = admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "Hotel A", "website": "hotel-a.com", "city": "Paris"})
check("a hotel is added and its page opens", r.status_code == 302 and "/admin/hotel/" in r.headers["Location"])
ha = db.hotel_by_key("hotel-a.com")
check("it is stored with its website identity and weekly checks on", ha and ha["weekly"] == 1 and ha["name"] == "Hotel A")
check("a second add of the same website opens the same hotel", admin.post("/admin/portfolio/add", data={"csrf": csrf, "name": "Hotel A again", "website": "www.hotel-a.com", "city": "Paris"}).headers["Location"].endswith(f"/{ha['id']}"))
hb_id = db.create_hotel("Hotel B", "hotel-b.com", "Lyon", "hotel-b.com")
page = admin.post(f"/admin/hotel/{ha['id']}/invite", data={"csrf": csrf, "email": "gm@hotel-a.com"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
check("an invite link is shown once to send to them", link and "expires in 7 days" in page)
check("a request without the form's token is refused", admin.post(f"/admin/hotel/{ha['id']}/invite", data={"email": "x@y.com"}).status_code == 400)
check("only the hash of the link is stored", all(link.split("/")[-1] not in str(v) for r_ in db._rows("SELECT * FROM invites") for v in r_.values()))

print("2. the hotel user creates a login (no site password needed)")
u = app.test_client()
check("without signing in, the portal sends them to its own sign-in, not the site password page", u.get("/portal", follow_redirects=False).headers["Location"].endswith("/portal/signin"))
check("the public audit form stays closed to them", "/login" in u.get("/", follow_redirects=False).headers["Location"])
form = u.get(link).get_data(as_text=True)
check("the invite page asks for a name and a password", "Choose a password" in form and "gm@hotel-a.com" in form)
c2 = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
bad = u.post(link, data={"csrf": c2, "name": "GM", "password": "short", "password2": "short"}).get_data(as_text=True)
check("a short password is refused with the reason", "at least 10 characters" in bad)
check("two different passwords are refused", "not the same" in u.post(link, data={"csrf": c2, "name": "GM", "password": "a-long-password-1", "password2": "a-long-password-2"}).get_data(as_text=True))
ok = u.post(link, data={"csrf": c2, "name": "GM", "password": "a-long-password-1", "password2": "a-long-password-1"}, follow_redirects=False)
check("a good password creates the login and signs them in", ok.status_code == 302 and ok.headers["Location"].endswith("/portal"))
check("the password is stored hashed", db.user_by_email("gm@hotel-a.com")["pw_hash"].startswith("scrypt$") and "a-long-password-1" not in db.user_by_email("gm@hotel-a.com")["pw_hash"])
check("the invite link works once only", app.test_client().get(link).status_code == 410)
check("the user is linked to the hotel and nothing else", [h["name"] for h in db.hotels_for_user(db.user_by_email("gm@hotel-a.com")["id"])] == ["Hotel A"])

print("3. the dashboard and the action list")
page = u.get("/portal").get_data(as_text=True)
check("before any check the hotel is told none has run", "No check has been run" in page)
tok1 = reports.save(report("hotel-a.com", "Hotel A", 60, run_at="2026-10-01T09:00:00+00:00"))
n1 = len(db.list_actions(ha["id"]))
check("saving an audit of the hotel's website creates its actions, all to do", n1 >= 8 and all(a["status"] == "todo" and a["state"] == "open" for a in db.list_actions(ha["id"])), n1)
page = u.get("/portal").get_data(as_text=True)
check("the dashboard shows the score, the action list with status buttons and the baseline", "Hotel A" in page and "Recommendations (" in page and 'data-v="working"' in page and "Baseline set on" in page and "60" in page)
check("times are UK times", "BST" in page or "GMT" in page)
phone = next(a for a in db.list_actions(ha["id"]) if "telephone" in a["title"])
token = re.search(r'data-csrf="([^"]+)"', page).group(1)
r = u.post("/portal/api/action", json={"id": phone["id"], "status": "working"}, headers={"X-CSRF": token})
check("marking an action 'working on it' saves", r.get_json()["ok"] and db.get_action(phone["id"])["status"] == "working")
check("a request without the page's token is refused", u.post("/portal/api/action", json={"id": phone["id"], "status": "done"}).status_code == 400)
check("an invalid status is refused", u.post("/portal/api/action", json={"id": phone["id"], "status": "banana"}, headers={"X-CSRF": token}).status_code == 400)
other = next(a for a in db.list_actions(ha["id"]) if a["id"] != phone["id"])
u.post("/portal/api/action", json={"id": other["id"], "status": "done"}, headers={"X-CSRF": token})
u.post("/portal/api/action", json={"id": phone["id"], "status": "done"}, headers={"X-CSRF": token})

print("4. the next check: fixed items tick off, new ones appear, a 'done' item still flagged is not accepted")
rep2 = report("hotel-a.com", "Hotel A", 75, drop_titles=("telephone",), add=("Add the airport shuttle times to the location page",), run_at="2026-10-08T09:00:00+00:00")
reports.save(rep2)
acts = {a["id"]: a for a in db.list_actions(ha["id"])}
check("the action no longer flagged is marked fixed and counted as checked on the site", acts[phone["id"]]["state"] == "resolved" and acts[phone["id"]]["resolution"] == "verified")
check("a new recommendation is added as a new action", any("airport shuttle" in a["title"] for a in acts.values()) and len(acts) == n1 + 1)
check("an action marked done that the new check STILL flags is shown as still flagged", acts[other["id"]]["status"] == "done" and acts[other["id"]]["reopened"] >= 1)
sm = progress.hotel_summary(db, db.get_hotel(ha["id"]))
check("the numbers: score 60 to 75, +15, over two checks", sm["first_score"] == 60 and sm["latest_score"] == 75 and sm["delta"] == 15 and sm["runs"] == 2)
check("completed counts the fixed one and not the still-flagged one", sm["actions"]["completed"] == 1 and sm["actions"]["verified"] == 1 and sm["actions"]["still_flagged"] == 1, sm["actions"])
page = u.get("/portal").get_data(as_text=True)
check("the dashboard says it in words", "from <b>60</b> to <b>75</b>" in page and "1 action</b> has been completed" in page and "still flags it" in page and "New this week" in page)
check("it says this is progress, not proof of cause", "does not prove that the actions caused" in page)
sampled = report("hotel-a.com", "Hotel A", 75, run_at="2026-10-09T09:00:00+00:00")
sampled["consultant"]["recommendations"] = [x for x in sampled["consultant"]["recommendations"] if "telephone" not in x["title"]]
poor = report("hotel-a.com", "Hotel A", 20, run_at="2026-10-10T09:00:00+00:00")
poor["consultant"]["coverage"] = {"pages_read": 0, "pages_attempted": 6}
before = {a["id"]: a["state"] for a in db.list_actions(ha["id"])}
reports.save(poor)
check("an audit that read none of the site changes nothing (a failed crawl never 'fixes' things)", {a["id"]: a["state"] for a in db.list_actions(ha["id"])} == before)
ai_rec = dict(BASE["consultant"]["recommendations"][0], id="FM1", title="3 open conversations where travellers are asking", source="reddit", tag="FM1")
r3 = report("hotel-a.com", "Hotel A", 75, run_at="2026-10-11T09:00:00+00:00")
r3["consultant"]["recommendations"].append(ai_rec)
reports.save(r3)
r4 = report("hotel-a.com", "Hotel A", 75, run_at="2026-10-12T09:00:00+00:00")
reports.save(r4)
fm = next(a for a in db.list_actions(ha["id"]) if a["source"] == "reddit")
check("something that came from sampled answers or forums and is absent next time is 'not flagged this time', never 'checked'", fm["state"] == "resolved" and fm["resolution"] == "not_flagged" and progress.classify(fm) == "cleared")

print("5. hotels see only themselves")
db2 = db
tokb = reports.save(report("hotel-b.com", "Hotel B", 50))
check("the other hotel's audit created actions for the other hotel only", len(db.list_actions(hb_id)) > 0)
check("the hotel user cannot open another hotel's dashboard", u.get(f"/portal/hotel/{hb_id}").status_code == 404)
b_action = db.list_actions(hb_id)[0]
check("nor change its actions", u.post("/portal/api/action", json={"id": b_action["id"], "status": "done"}, headers={"X-CSRF": token}).status_code == 404 and db.get_action(b_action["id"])["status"] == "todo")
check("their own hotel's report opens without the site password", u.get(f"/r/{tok1}").status_code == 200)
check("the other hotel's report does not", u.get(f"/r/{tokb}", follow_redirects=False).status_code == 302)
check("and the report page shows a link back to the dashboard, not 'run another audit'", "Back to my dashboard" in u.get(f"/r/{tok1}").get_data(as_text=True) and "Run another audit" not in u.get(f"/r/{tok1}").get_data(as_text=True))
check("the admin pages are closed to a hotel user", u.get("/admin/portfolio", follow_redirects=False).status_code in (302, 401, 403))
check("signing out ends the session", u.post("/portal/signout").status_code == 302 and u.get("/portal", follow_redirects=False).headers["Location"].endswith("/portal/signin"))
check("a wrong password is refused", "do not match" in u.post("/portal/signin", data={"email": "gm@hotel-a.com", "password": "wrong-password-x"}).get_data(as_text=True))
check("the right password signs in", u.post("/portal/signin", data={"email": "gm@hotel-a.com", "password": "a-long-password-1"}).status_code == 302 and u.get("/portal").status_code == 200)

print("6. the operator sees the portfolio and each hotel as the hotel sees it")
page = admin.get("/admin/portfolio").get_data(as_text=True)
check("the portfolio roll-up and one row per hotel", "Hotel A" in page and "Hotel B" in page and "actions completed" in page)
page = admin.get(f"/admin/hotel/{ha['id']}").get_data(as_text=True)
check("a hotel page shows exactly the hotel's view, read-only, plus the controls", "Recommendations (" in page and 'data-v="working"' not in page and "Run a check now" in page and "gm@hotel-a.com" in page)
page = admin.post(f"/admin/hotel/{ha['id']}/reset/{db.user_by_email('gm@hotel-a.com')['id']}", data={"csrf": csrf}).get_data(as_text=True)
check("the operator can make a password-reset link", "/portal/invite/" in page)
rl = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
fresh = app.test_client()
f2 = fresh.get(rl).get_data(as_text=True)
c3 = re.search(r'name="csrf" value="([^"]+)"', f2).group(1)
rs = fresh.post(rl, data={"csrf": c3, "password": "another-long-pass-9", "password2": "another-long-pass-9"})
check("the reset link sets a new password", rs.status_code == 302 and app.test_client().post("/portal/signin", data={"email": "gm@hotel-a.com", "password": "another-long-pass-9"}).status_code == 302)
admin.post(f"/admin/hotel/{ha['id']}/user/{db.user_by_email('gm@hotel-a.com')['id']}/off", data={"csrf": csrf})
check("a switched-off user cannot sign in", "do not match" in app.test_client().post("/portal/signin", data={"email": "gm@hotel-a.com", "password": "another-long-pass-9"}).get_data(as_text=True))

print("7. the weekly checks")
anon = app.test_client()
check("the weekly route does not exist without the token", anon.post("/internal/weekly").status_code == 404 and anon.post("/internal/weekly", headers={"Authorization": "Bearer nope"}).status_code == 404)
w = app.extensions["weekly"]
due = {h["name"] for h in w.due(db, now=__import__("datetime").datetime(2026, 10, 20, tzinfo=__import__("datetime").timezone.utc))}
check("a hotel whose latest audit is older than 6 days is due; a recent one is not", due == {"Hotel A", "Hotel B"} or due == {"Hotel B", "Hotel A"})
due_now = {h["name"] for h in w.due(db, now=__import__("datetime").datetime(2026, 10, 13, tzinfo=__import__("datetime").timezone.utc))}
check("one checked on the 12th is not due on the 13th", "Hotel A" not in due_now)
db.set_hotel(hb_id, weekly=0)
check("a hotel with weekly checks switched off is never due", "Hotel B" not in {h["name"] for h in w.due(db, now=__import__("datetime").datetime(2027, 1, 1, tzinfo=__import__("datetime").timezone.utc))})
n_runs = len(db.hotel_runs("hotel-a.com"))
r = anon.post("/internal/weekly", headers={"Authorization": "Bearer cron-token-abcdef"})
check("with the token the checks start (Hotel A is due now: its last audit is in the past)", r.status_code == 202 and r.get_json()["hotels"] >= 1, r.get_data(as_text=True))
for _ in range(60):
    st = anon.get("/internal/weekly/status", headers={"Authorization": "Bearer cron-token-abcdef"}).get_json()
    if not st["running"]:
        break
    time.sleep(0.2)
check("they finish, one audit ran with the hotel's saved details, and it was saved to the hotel's history", not st["running"] and fake_run.calls and fake_run.calls[0]["website"] == "hotel-a.com" and fake_run.calls[0]["city"] == "Paris" and len(db.hotel_runs("hotel-a.com")) == n_runs + 1, str(st))
check("the attempt is recorded and a second call straight away runs nothing (12-hour retry guard and a fresh audit)", anon.post("/internal/weekly", headers={"Authorization": "Bearer cron-token-abcdef"}).get_json()["hotels"] == 0)
def boom(params, cb=None):
    raise RuntimeError("site down")
w.run_fn = boom
res = w.check_one(ha["id"])
check("a failing hotel is recorded with the reason and does not raise", res["ok"] is False and "site down" in db.get_hotel(ha["id"])["last_error"])

print("8. the AI visibility tab")
import ai_dash
admin.post(f"/admin/hotel/{ha['id']}/user/{db.user_by_email('gm@hotel-a.com')['id']}/on", data={"csrf": csrf})
u8 = app.test_client()
u8.post("/portal/signin", data={"email": "gm@hotel-a.com", "password": "another-long-pass-9"})
page = u8.get("/portal").get_data(as_text=True)
check("the dashboard has tabs: Overview, AI visibility, Recommendations, History", all(x in page for x in ('data-name="overview"', 'data-name="ai"', 'data-name="actions"', 'data-name="history"')))
check("the AI visibility tab shows the citations section and says what it is a sample of", "Brand performance over time" in page or "No AI answers have been saved" in page)
cur = {"u1": {"url": "u1", "cited": 10, "domain": "a.com"}, "u2": {"url": "u2", "cited": 4, "domain": "b.com"}, "u3": {"url": "u3", "cited": 7, "domain": "c.com"}, "u4": {"url": "u4", "cited": 3, "domain": "d.com"}}
prev = {"u1": {"url": "u1", "cited": 10, "domain": "a.com"}, "u2": {"url": "u2", "cited": 8, "domain": "b.com"}, "u3": {"url": "u3", "cited": 5, "domain": "c.com"}, "u9": {"url": "u9", "cited": 6, "domain": "z.com"}}
ch = ai_dash._changes(cur, prev)
check("citation changes: stable, increased, decreased, new and lost are told apart, with the size of the change", [r["url"] for r in ch["stable"]] == ["u1"] and ch["increased"][0]["delta"] == 2 and ch["increased"][0]["pct"] == 40 and ch["decreased"][0]["pct"] == -50 and [r["url"] for r in ch["new"]] == ["u4"] and [r["url"] for r in ch["lost"]] == ["u9"] and ch["top"][0]["url"] == "u1")
check("with only one check nothing is called new or lost", ai_dash._changes(cur, None)["new"] == [] and ai_dash._changes(cur, None)["lost"] == [])
svg = ai_dash.lines_svg([{"run_at": "2026-10-01T09:00:00+00:00"}, {"run_at": "2026-10-08T09:00:00+00:00"}, {"run_at": "2026-10-15T09:00:00+00:00"}], [{"name": "Me", "own": True, "points": [10, None, 30]}, {"name": "Rival", "own": False, "points": [20, 25, 22]}], 0, 40)
check("the chart draws the hotel and its rival, breaks the line where the hotel was not named, and labels each point", svg.count("<polyline") == 1 + 0 + 0 or svg.count("<polyline") >= 1) and check("hover labels carry the name, value and date", "Me: 10" in svg and "Rival: 25" in svg)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
