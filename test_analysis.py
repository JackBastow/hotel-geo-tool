"""
Offline test: the admin Overview is an analysis of the portfolio (hotels, checks, score movement, actions, AI visibility growth, who is moving, who needs attention), not a list of runs. No network.
Run: python test_analysis.py
"""
import datetime as dt
import json
import os
import re
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


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "a.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "SECRET_KEY": "k" * 32})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
reports = app.extensions["reports"]
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
now = dt.datetime.now(dt.timezone.utc)


def rep(site, name, score, named, asked, days_ago, drop=()):
    import copy
    r = copy.deepcopy(BASE)
    r["meta"].update(base=f"https://www.{site}/", website=site, hotel=name, run_at=(now - dt.timedelta(days=days_ago)).isoformat(timespec="seconds"))
    r["headline"]["score"] = score
    r["consultant"]["recommendations"] = [x for x in r["consultant"]["recommendations"] if not any(t in x["title"] for t in drop)]
    r["consultant"]["coverage"] = {"pages_read": 8}
    r["ai_sample"]["summary"].update(generic_named=named, generic_asked=asked, niche_named=0, niche_asked=0)
    return r


H = {}
for site, name in (("a.com", "Alpha"), ("b.com", "Bravo"), ("c.com", "Charlie"), ("d.com", "Delta")):
    H[site] = db.create_hotel(name, site, "X", site)
reports.save(rep("a.com", "Alpha", 50, 2, 20, 40))
reports.save(rep("a.com", "Alpha", 70, 8, 20, 5, drop=("telephone", "hygiene")))
reports.save(rep("b.com", "Bravo", 80, 6, 20, 30))
reports.save(rep("b.com", "Bravo", 70, 4, 20, 3))
reports.save(rep("c.com", "Charlie", 60, 5, 20, 20))                          # one check, 20 days ago: needs attention
reports.save(rep("z.com", "Not registered", 55, 1, 10, 2))
f = analysis.figures(db, db.list_runs(limit=100))
rows = {r["hotel"]["name"]: r for r in f["rows"]}
print("1. the figures")
check("hotels and checks are counted: 4 hotels, 5 checks of them (the unregistered audit is reported separately)", f["tiles"]["hotels"] == 4 and f["tiles"]["checks"] == 5 and f["other_audits"] == 1, f["tiles"])
check("score movement per hotel: Alpha +20, Bravo -10, Charlie and Delta not measured", rows["Alpha"]["delta"] == 20 and rows["Bravo"]["delta"] == -10 and rows["Charlie"]["delta"] is None)
check("AI visibility growth is in points of coverage: Alpha 10% to 40% = +30, Bravo 30% to 20% = -10", rows["Alpha"]["growth"] == 30 and rows["Bravo"]["growth"] == -10 and rows["Charlie"]["growth"] is None, (rows["Alpha"]["cov0"], rows["Alpha"]["cov1"], rows["Alpha"]["growth"]))
check("actions completed are counted per hotel (Alpha's checks fixed some)", rows["Alpha"]["actions"]["completed"] >= 1 and rows["Bravo"]["actions"]["completed"] == 0)
check("the average movement and the improving / slipping counts", f["tiles"]["up"] == 1 and f["tiles"]["down"] == 1 and f["tiles"]["avg_move"] == 5.0, f["tiles"])
att = {r["hotel"]["name"]: why for r, why in f["attention"]}
check("hotels needing attention: Delta never checked, Charlie not checked for 14+ days, Bravo's score is down 10", att.get("Delta") == "Never checked" and "20 days" in att.get("Charlie", "") and "down 10" in att.get("Bravo", ""), att)
check("checks per week are counted from all the hotels' checks", sum(p["score"] for p in f["weeks"]) == 5)

print("2. the page")
adm = app.test_client()
adm.post("/admin/login", data={"password": "adm"})
pg = adm.get("/admin").get_data(as_text=True)
text = re.sub(r"<[^>]+>", " ", pg)
check("the Overview is an analysis: tiles, hotel by hotel, who is moving, activity", all(w in pg for w in ("Hotel by hotel", "Who is moving", "Activity and spread", "Checks run", "Actions completed")))
check("it has the charts asked for: most actions, biggest AI visibility growth, score gains and drops, checks per week, hotels by score, needing attention", all(w in pg for w in ("Most actions completed (top 5)", "Biggest growth in AI visibility (top 5)", "Biggest readiness score gains", "Biggest score drops", "Checks run per week", "Hotels by readiness score", "need attention")))
check("the list of runs with their times is gone from the Overview (the Runs tab has it)", "Latest audits" not in pg and "Run (UK time)" not in pg)
check("the Runs tab still has them", "Run (UK time)" in adm.get("/admin/runs").get_data(as_text=True))
check("the best hotel is on the AI visibility growth chart", "Alpha" in pg and "10% to 40%" in pg)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
