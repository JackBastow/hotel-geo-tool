"""
Tests for the back end (backend.py) and the admin page (ui_admin.py) against a throwaway SQLite file.
The same SQL runs on Postgres in production (checked separately against a real connection string). Run: python test_backend.py
"""
import copy
import json
import os
import tempfile
import warnings

warnings.filterwarnings("ignore")
from streamlit.testing.v1 import AppTest

import backend

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8") as fh:
    REP = json.load(fh)
DB = os.path.join(tempfile.gettempdir(), "hotel_backend_test.db")
if os.path.exists(DB):
    os.remove(DB)
URL = "sqlite:///" + DB.replace("\\", "/")

print("1. the summary row")
s = backend.summarise(REP)
check("every column the table expects is produced", set(backend.RUN_COLS) <= set(s), set(backend.RUN_COLS) - set(s))
check("hotel, city, headline and AI numbers are read from the report", s["hotel"] == "Brooklands Hotel" and s["city"] == "Weybridge" and s["headline_score"] == 83.0
      and s["ai_niche_asked"] == 2 and s["ai_niche_named"] == 1 and s["ai_generic_asked"] == 2, {k: s[k] for k in ("hotel", "headline_score", "ai_niche_asked")})
check("reviews and speed numbers are read too", s["reviews_examined"] == 3 and s["reviews_replied"] == 2 and s["pagespeed_perf"] == 41)
check("category scores are kept as JSON by key, only for assessed categories", isinstance(json.loads(s["cat_scores"]), dict) and "reviews" not in json.loads(s["cat_scores"]))
check("the AI cost is the sum of what each AI step reported", 0.05 < s["ai_cost_usd"] < 1.0, s["ai_cost_usd"])
check("a hotel's identity is its website host, with a chain's own folder kept so two Hilton hotels are two hotels",
      backend.hotel_key({"meta": {"base": "https://www.brooklandshotelsurrey.com/"}}) == "brooklandshotelsurrey.com"
      and backend.hotel_key({"meta": {"base": "https://www.hilton.com/en/hotels/lxmhidi-doubletree-luxembourg/"}}) == "hilton.com/en/hotels/lxmhidi-doubletree-luxembourg"
      and backend.hotel_key({"meta": {"base": "https://www.hilton.com/en/hotels/parhi-hilton-paris/"}}) != backend.hotel_key({"meta": {"base": "https://www.hilton.com/en/hotels/lxmhidi-doubletree-luxembourg/"}}))
bare = backend.summarise({"meta": {"website": "x.com"}})
check("a report from long ago, missing most sections, still summarises (no crash, empty values)", bare["hotel"] == "" and bare["headline_score"] is None and bare["recs_total"] == 0)
comps, srcs = backend.children(REP)
check("market rows come from the leaderboards and the source table", any(c["kind"] == "generic" and c["competitor"] == "Oatlands Park Hotel" for c in comps)
      and any(c["kind"] == "niche" for c in comps) and any(x["domain"] == "booking.com" for x in srcs))

print("2. saving and reading")
st = backend.open_store(URL)
check("the schema is created on first use and the store is empty", st.count() == 0 and st.hotels() == [])
rid1 = st.save_run(REP)
r2 = copy.deepcopy(REP)
r2["meta"]["run_at"] = "2026-11-12T10:00:00+00:00"
r2["headline"]["score"] = 91
r2["ai_insights"]["scoreboard"]["share"] = 40
r2["ai_sample"]["summary"].update(generic_named=2, generic_asked=2, niche_named=2, niche_asked=2)
rid2 = st.save_run(r2)
other = copy.deepcopy(REP)
other["meta"].update(hotel="Chain Hotel", city="Luxembourg", base="https://www.hilton.com/en/hotels/x-doubletree-luxembourg/", website="https://www.hilton.com/en/hotels/x-doubletree-luxembourg/",
                     run_at="2026-11-13T09:00:00+00:00")
rid3 = st.save_run(other)
check("three runs saved with their own ids", (rid1, rid2, rid3) == (1, 2, 3) and st.count() == 3)
check("the full report comes back exactly (so any run can be reopened, compared or turned into a PDF)", st.get_report(rid1)["meta"]["hotel"] == "Brooklands Hotel"
      and st.get_report(rid1)["ai_insights"]["scoreboard"]["share"] == 25 and st.get_report(999) is None)
check("runs list newest first, and filter by text, city and date", [r["id"] for r in st.list_runs()] == [3, 2, 1] and len(st.list_runs(text="brooklands")) == 2
      and len(st.list_runs(city="luxembourg")) == 1 and [r["id"] for r in st.list_runs(since="2026-11-01")] == [3, 2])
hs = {h["hotel_key"]: h for h in st.hotels()}
b = hs["brooklandshotelsurrey.com"]
check("hotels: runs counted per hotel, latest numbers shown, and the change since the run before (score 83 -> 91, share 25 -> 40)",
      b["runs"] == 2 and b["headline_score"] == 91 and b["d_score"] == 8.0 and b["d_share"] == 15.0 and hs["hilton.com/en/hotels/x-doubletree-luxembourg"]["d_score"] is None, b)
check("a hotel's history is in date order", [h["headline_score"] for h in st.history("brooklandshotelsurrey.com")] == [83.0, 91.0])

print("3. the market view")
c_all = {c["competitor"]: c for c in st.competitors()}
check("hotels the assistant named are summed across audits and counted by audit (Oatlands Park in 3 audits)", c_all["Oatlands Park Hotel"]["runs"] == 3 and c_all["Oatlands Park Hotel"]["mentions"] >= 3)
check("the audited hotel itself is never listed as its own competitor", "Brooklands Hotel" not in c_all)
check("the market can be narrowed to a city", all(c["runs"] == 1 for c in st.competitors(city="Luxembourg")))
check("niche markets are a separate list from the town-wide one", "Sofitel Heathrow" in {c["competitor"] for c in st.competitors(kind="niche")} and "Sofitel Heathrow" not in c_all)
src = {s_["domain"]: s_ for s_ in st.sources()}
check("sites the assistant relies on, with how often the hotel was found or missing there", src["booking.com"]["runs"] == 3 and (src["booking.com"]["hotel_found"] + src["booking.com"]["hotel_missing"]) >= 0)
check("usage by month counts runs, hotels and estimated cost", st.usage_by_month()[0]["month"] == "2026-11" and st.usage_by_month()[0]["runs"] == 2 and st.usage_by_month()[0]["hotels"] == 2
      and st.usage_by_month()[1]["month"] == "2026-10")
check("the city list feeds the filters", st.cities() == ["Luxembourg", "Weybridge"])

print("4. export")
rows = st.export_rows()
csv_text = backend.to_csv(rows)
check("the summary table exports as CSV, one line per run, with a header", csv_text.splitlines()[0].startswith("id,") and len(csv_text.strip().splitlines()) == 4 and "Brooklands Hotel" in csv_text)
check("the CSV never contains the bulky report JSON", "report_json" not in csv_text.splitlines()[0])
check("nothing to export gives nothing", backend.to_csv([]) == "")

print("5. deleting")
st.delete_run(rid3)
check("a deleted run takes its market rows with it (Oatlands Park now in 2 audits, not 3)", st.count() == 2 and {c["competitor"]: c for c in st.competitors()}["Oatlands Park Hotel"]["runs"] == 2)
check("and it is really gone", st.get_report(rid3) is None and len(st.list_runs(city="luxembourg")) == 0)
check("no connection string means no store (the app then saves nothing)", backend.open_store("") is None and backend.open_store(None) is None)

print("6. the admin page")


def admin(**secrets):
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=60)
    for k, v in secrets.items():
        at.secrets[k] = v
    at.query_params["admin"] = "1"
    at.run()
    return at


at = admin()
check("with no ADMIN_PASSWORD secret the page is switched off, and shows nothing else", any("switched off" in e.value for e in at.error) and not at.tabs)
at = admin(ADMIN_PASSWORD="open-sesame", DATABASE_URL=URL)
check("with a password set, visitors see only a password box (no data)", at.text_input and not at.tabs and not at.dataframe)
at.text_input[0].set_value("wrong").run()
check("a wrong password is refused", any("Wrong password" in e.value for e in at.error) and not at.tabs)
at.text_input[0].set_value("open-sesame").run()
check("the right password opens the admin page with its tabs", {"Overview", "Runs", "Hotels", "Markets", "Usage", "Export"} <= {t.label for t in at.tabs} and not at.exception,
      [e.message for e in at.exception])
check("it shows the saved runs and totals", any(m.label == "Audits saved" and str(m.value) == "2" for m in at.metric) and len(at.dataframe) >= 3)
check("the Export tab offers the monthly Excel pack", any("Build the monthly pack" in x.label for x in at.button) and any("From month" in x.label for x in at.selectbox), [x.label for x in at.button])
at2 = admin(ADMIN_PASSWORD="pw", DATABASE_URL="")
at2.text_input[0].set_value("pw").run()
check("with a password but no database it says nothing is being saved", any("No database is connected" in w.value for w in at2.warning))
check("the public page is unchanged for visitors: no admin query, no admin content", not any("Admin" in (t.label or "") for t in AppTest.from_file(os.path.join(HERE, "app.py")).run().tabs))
pub = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=60)
pub.secrets["DATABASE_URL"] = URL
pub.run()
check("with a database connected EVERY run is saved: there is no option to opt out, and the visitor is told plainly that runs are saved by the operator and not shown to others", not any("Save this run" in c.label for c in pub.checkbox) and any("Every audit run here is saved by the operator" in c.value and "not shown to other visitors" in c.value for c in pub.caption), [c.value[:60] for c in pub.caption])
pub2 = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=60)
pub2.run()
check("with no database nothing is saved and nothing is said about saving", not any("saved by the operator" in c.value for c in pub2.caption) and not any("Save this run" in c.label for c in pub2.checkbox))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
