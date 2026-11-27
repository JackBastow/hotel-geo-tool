"""
Report release: ready for the hotel / needs review / blocked (report_release.py), and that the hotel's pages honour it.
Run: python test_release.py
"""
import copy
import json
import os
import re
import tempfile
import warnings

warnings.filterwarnings("ignore")
import backend
import headline
import report_release as rr

FAILS = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))
    if not cond:
        FAILS.append(name)


BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))


def good():
    r = copy.deepcopy(BASE)
    r["gate"] = {"checks": [{"name": "x"}], "changes": [], "needs_review": [], "version": 2}
    r["step_errors"] = []
    r["consultant"]["coverage"] = {"pages_read": 20, "pages_attempted": 22, "ratio": 0.9}
    r["consultant"]["recommendations"] = [x for x in r["consultant"]["recommendations"] if x.get("tag") != "site-check"]
    r.pop("release", None)
    r.pop("identity", None)
    return r


def codes(rep):
    return {x["code"] for x in rep["release"]["reasons"]}


print("1. the three states")
r = rr.assess(good())
check("a report whose validation found nothing is ready", r["release"]["state"] == "ready" and not r["release"]["reasons"], r["release"])

r = good()
r.pop("gate")
rr.assess(r)
check("a report whose validation never ran is blocked", r["release"]["state"] == "blocked" and "validation_missing" in codes(r), r["release"])

r = good()
r["gate"]["error"] = "KeyError: 'x'"
rr.assess(r)
check("a report whose validation crashed part-way is blocked (the issue: it used to be returned with only a note)", r["release"]["state"] == "blocked" and "validation_failed" in codes(r))

r = good()
r["consultant"]["coverage"] = {"unreadable": True, "pages_read": 0, "pages_attempted": 0}
rr.assess(r)
check("a website that could not be read is blocked", r["release"]["state"] == "blocked" and "website_unreadable" in codes(r))

r = good()
r["consultant"]["coverage"] = {"pages_read": 2, "pages_attempted": 20, "ratio": 0.1}
rr.assess(r)
check("two pages of twenty read is blocked; four of ten is only for review", r["release"]["state"] == "blocked" and "website_barely_read" in codes(r))
r = good()
r["consultant"]["coverage"] = {"pages_read": 4, "pages_attempted": 10, "ratio": 0.4}
rr.assess(r)
check("...four of ten is review", r["release"]["state"] == "review" and "website_partly_read" in codes(r), r["release"])

r = good()
r["consultant"]["recommendations"].append({"id": "SC", "tag": "site-check", "title": "x", "source": "x"})
rr.assess(r)
check("a website that may not be the hotel's is blocked", r["release"]["state"] == "blocked" and "wrong_website" in codes(r))

r = good()
r["identity"] = {"canonical": "sauntonsands hotel", "needs_review": "The name looks like the website address."}
rr.assess(r)
check("a hotel name that is still the web address is blocked", r["release"]["state"] == "blocked" and "identity_unresolved" in codes(r))

print("2. the Saunton Sands failure is blocked, and the recalculated report is not")
r = good()
r["meta"].update(hotel="sauntonsands hotel", city="Saunton", website="https://www.sauntonsands.com/")
r["ai_sample"]["items"] = [{"id": "a", "kind": "generic", "text": "q", "answer": "Saunton Sands Hotel is great", "mentioned": False}]
r["ai_insights"] = {"brand_ranking": {"all": [{"name": "sauntonsands hotel", "is_target": True}, {"name": "Saunton Sands Hotel, North Devon", "is_target": False}]}}
rr.assess(r)
check("the hotel listed among its own rivals under another spelling blocks the report", r["release"]["state"] == "blocked" and "hotel_among_rivals" in codes(r), r["release"])
r["ai_insights"]["brand_ranking"]["all"] = [{"name": "Saunton Sands Hotel", "is_target": True}, {"name": "Watersmeet Hotel", "is_target": False}]
r["meta"]["hotel"] = "Saunton Sands Hotel"
rr.assess(r)
check("once the hotel is one row and the rivals are other hotels it is ready", r["release"]["state"] == "ready", r["release"])

r = good()
r["gate"]["ai_diagnosis"] = {"possible_missed": 3, "named": 0}
r["ai_sample"]["items"] = [{"id": "a", "kind": "generic", "text": "q", "answer": "x", "mentioned": False}]
rr.assess(r)
check("a zero with answers that hold words of the hotel's name is blocked", r["release"]["state"] == "blocked" and "ai_names_not_counted" in codes(r))

print("3. review, and approval")
r = good()
r["ai_sample"]["summary"] = {**(r["ai_sample"].get("summary") or {}), "ambiguous_named": 3}
r["ai_sample"]["items"] = [{"id": "a", "kind": "generic", "text": "q", "answer": "x", "mentioned": True}]
rr.assess(r)
check("answers that only named the hotel's group are a review reason", r["release"]["state"] == "review" and "ambiguous_mentions" in codes(r), r["release"])
ok, msg = rr.approve(r, "admin")
check("an admin can approve a report in review, and it then shows as ready", ok and r["release"]["state"] == "ready" and r["release"]["approved"]["codes"] == ["ambiguous_mentions"], (ok, msg))
rr.assess(r)
check("the approval survives re-assessing while the reasons are the same", r["release"]["state"] == "ready")
r["gate"]["needs_review"] = [{"what": "The hotel's tracked prompts were not asked in this check."}]
rr.assess(r)
check("a NEW reason is not covered by the earlier approval", r["release"]["state"] == "review" and "needs_review" in codes(r), r["release"])
b = good()
b.pop("gate")
rr.assess(b)
ok, msg = rr.approve(b, "admin")
check("a blocked report cannot be approved", not ok and b["release"]["state"] == "blocked", msg)

print("4. a check made before release states existed is assessed on the spot, never trusted")
old = good()
old.pop("gate")
check("no stored release: the state is worked out now; a check from before validation existed keeps its history visible but is noted", rr.state_of(old) == "ready" and "release" not in old
      and rr.assess(dict(old), legacy=True)["release"]["reasons"][0]["code"] == "pre_validation")
oldbad = good()
oldbad.pop("gate")
oldbad["consultant"]["coverage"] = {"unreadable": True}
check("...but any other reason still applies to it", rr.state_of(oldbad) == "blocked")
check("a stored state is used as it is", rr.state_of({"release": {"state": "ready"}}) == "ready")
check("a report with nothing in it never raises", rr.assess({})["release"]["state"] == "blocked" and rr.state_of(None) == "blocked")

print("5. stored with the run; the hotel's pages leave out what is not ready")
DB = os.path.join(tempfile.mkdtemp(), "r.db")
st = backend.open_store("sqlite:///" + DB.replace("\\", "/"))
a = good()
rr.assess(a)
a["meta"]["run_at"] = "2026-11-10T10:00:00+00:00"
b = good()
b["meta"]["run_at"] = "2026-11-20T10:00:00+00:00"
b["gate"]["error"] = "boom"
rr.assess(b)
ida, idb = st.save_run(a), st.save_run(b)
key = backend.hotel_key(a)
rows = {r["id"]: r for r in st.hotel_runs(key)}
check("the state is saved in the run's row", rows[ida]["release_state"] == "ready" and rows[idb]["release_state"] == "blocked", {k: v.get("release_state") for k, v in rows.items()})
check("the hotel's own run list leaves out the blocked check, so its dashboard shows the last good one", [r["id"] for r in st.customer_runs(key)] == [ida] and [r["id"] for r in st.hotel_runs(key)] == [idb, ida])
legacy = good()
legacy["meta"]["run_at"] = "2026-11-25T10:00:00+00:00"
idl = st.save_run(legacy)
check("a run with no state yet is shown until it is assessed (so no existing dashboard empties)", idl in [r["id"] for r in st.customer_runs(key)])

print("6. a shared report link")
os.environ.setdefault("STREAMLIT_APP_ENABLED", "1")
import audit_service
import server
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "s.db").replace("\\", "/")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "SITE_PASSWORD": "site-pass-1", "SECRET_KEY": "k" * 32, "CRON_TOKEN": "cron-token-abcdef"})
app = server.create_app(cfg, run_fn=lambda p, progress_cb=None: good())
db2 = backend.open_store(URL)
ok_rep, bad_rep = good(), good()
rr.assess(ok_rep)
bad_rep["gate"]["error"] = "boom"
rr.assess(bad_rep)
bad_rep["meta"]["hotel"] = "Blocked Hotel"
ok_rep["meta"]["hotel"] = "Ready Hotel"
db2.save_run(ok_rep, token="a" * 24)
db2.save_run(bad_rep, token="b" * 24)
cl = app.test_client()
cl.post("/login", data={"password": "site-pass-1"})
ok_page, bad_page = cl.get("/r/" + "a" * 24), cl.get("/r/" + "b" * 24)
check("a ready report opens", ok_page.status_code == 200 and "Ready Hotel" in ok_page.get_data(as_text=True), (ok_page.status_code, ok_page.get_data(as_text=True)[:200]))
txt = bad_page.get_data(as_text=True)
check("a blocked report shows a holding page, with none of the report and none of the reason", "being checked" in txt and "Blocked Hotel" not in txt and "boom" not in txt, txt[:200])
check("its PDF and data download are held too", "being checked" in cl.get("/r/" + "b" * 24 + "/data.json").get_data(as_text=True) and cl.get("/r/" + "b" * 24 + "/management.pdf").mimetype != "application/pdf")
adm = app.test_client()
adm.post("/login", data={"password": "site-pass-1"})
adm.post("/admin/login", data={"password": "adm-pass-1"})
check("an admin signed in can still open it, to review it", "Blocked Hotel" in adm.get("/r/" + "b" * 24).get_data(as_text=True))
scan = json.loads(adm.get("/admin/release/scan.json?scope=all").get_data(as_text=True))
check("the admin scan lists every check's state and the reasons", {x["state"] for x in scan["rows"]} == {"ready", "blocked"} and any("validation" in " ".join(x.get("reasons") or []) for x in scan["rows"]), scan)

print("\nFAILURES:", FAILS or "none")
raise SystemExit(1 if FAILS else 0)
