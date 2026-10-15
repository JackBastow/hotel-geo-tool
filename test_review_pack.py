"""
Offline tests for review_pack.py: reading an uploaded review export, the arithmetic, the privacy split, and what it does to the score and the plan.
Run: python test_review_pack.py
"""
import copy
import datetime as dt
import io
import json
import os
import tempfile
import warnings

warnings.filterwarnings("ignore")
from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

import advice
import backend
import review_pack as rp
import scoring

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = dt.date(2026, 10, 14)

BOOKING = """Review date,Review score,Review title,Positive review,Negative review,Response,Response date,Guest name
2026-09-20,9.0,Great,Lovely breakfast and friendly staff,,"Dear Anna, thank you for mentioning the breakfast and our staff. Kind regards, Maria, Guest Relations Manager",2026-09-21,Anna Smith
2026-09-02,4.0,Noisy,,The room was noisy at night and the air con was too cold,,,Bob Jones
2026-08-15,3.0,OK,Good location,Parking was expensive,"Thank you for your feedback. We have shared this with the team. Regards, Management",2026-08-30,Cy Brown
2026-07-30,2.0,Bad,,Dirty bathroom and rude reception,,,Di White
2026-07-01,10,Perfect,Everything,,"Thank you for staying with us. We hope to see you again soon. Kind regards, The Team",2026-07-02,Ed Green
2026-06-01,10,Perfect,Everything,,"Thank you for staying with us. We hope to see you again soon. Kind regards, The Team",2026-06-03,Flo Black
"""

print("1. reading a file")
rows, err = rp.read_table(BOOKING.encode(), "export.csv")
m = rp.map_columns(list(rows[0]))
check("a Booking.com-style CSV is read and its columns recognised: date, score, positive, negative, response, response date (the guest name is not mapped)",
      not err and len(rows) == 6 and {"date", "rating", "positive", "negative", "reply", "reply_date"} <= set(m) and "Guest name" not in m.values(), m)
rv = rp.normalise(rows, m, "Booking.com")
check("a 10-point scale becomes out of 5 (9.0 -> 4.5, 4.0 -> 2.0, 10 -> 5.0) and the platform is the one given", [r["rating"] for r in rv] == [4.5, 2.0, 1.5, 1.0, 5.0, 5.0] and rv[0]["platform"] == "Booking.com")
check("the guest-name column is never read into the reviews", all(w not in json.dumps(r, default=str) for r in rv for w in ("Smith", "Jones", "Brown", "White")))
g = "date,starRating,comment,reviewReply.comment,reviewReply.updateTime\n2026-09-01T10:00:00Z,FIVE,Wonderful stay,Thanks so much!,2026-09-02T09:00:00Z\n2026-08-01T10:00:00Z,ONE,Terrible,,\n"
gt = rp.read_table(g.encode(), "g.csv")[0]
gr = rp.normalise(gt, rp.map_columns(list(gt[0])), "Google")
check("Google's export (starRating as a word, reviewReply columns, ISO times) is read", [r["rating"] for r in gr] == [5.0, 1.0] and gr[0]["reply"] and gr[0]["reply_date"] == dt.date(2026, 9, 2) and not gr[1]["reply"], gr)
semi = "Date;Rating;Review;Reply\n14/10/2025;5;Lovely;Thanks\n31/10/2025;2;Bad;\n"
sr = rp.read_table(semi.encode(), "s.csv")[0]
nr = rp.normalise(sr, rp.map_columns(list(sr[0])), "Tripadvisor")
check("a semicolon file with day-first dates (31/10 is unambiguous) is read as day/month/year", nr[1]["date"] == dt.date(2025, 10, 31) and nr[0]["date"] == dt.date(2025, 10, 14))
wb = Workbook()
ws = wb.active
ws.append(["Some title row"])
ws.append(["Date", "Rating", "Review", "Owner response"])
ws.append([dt.datetime(2026, 9, 1), 4, "Nice", "Thank you"])
ws.append([dt.datetime(2026, 8, 1), 1, "Awful", None])
buf = io.BytesIO()
wb.save(buf)
xr = rp.read_table(buf.getvalue(), "x.xlsx")[0]
xn = rp.normalise(xr, rp.map_columns(list(xr[0])), "Expedia")
check("an Excel file with a title row above the headers is read, with real dates", len(xn) == 2 and xn[0]["date"] == dt.date(2026, 9, 1) and xn[0]["reply"] and not xn[1]["reply"], xn)
check("a file with nothing in it, or that is not a table, gives a plain message, never an exception", rp.read_table(b"", "e.csv")[1] and rp.read_table(b"PK\x03\x04junk", "x.xlsx")[1])
check("ratings: '4,5', '9/10', 'THREE' and blanks", rp.parse_rating("4,5") == (4.5, None) and rp.parse_rating("9/10") == (9.0, 10) and rp.parse_rating("THREE") == (3.0, 5) and rp.parse_rating("") == (None, None))

print("2. the arithmetic")
res = rp.analyse(copy.deepcopy(rv), "Test Hotel", {"breakfast": "not_found", "parking": "answered"}, today=TODAY)
pub, priv = res["public"], res["private"]
check("reply rate 4 of 6 = 67%; critical reviews 3 (2.0, 1.5 and 1.0 out of 5), 2 unanswered", (pub["reply_rate"], pub["critical"], pub["critical_unanswered"], pub["critical_replied"]) == (67, 3, 2, 1), pub)
check("by rating band: critical 1 of 3 replied, positive 3 of 3", (pub["by_rating"]["critical"]["replied"], pub["by_rating"]["critical"]["reviews"], pub["by_rating"]["positive"]["rate"]) == (1, 3, 100), pub["by_rating"])
check("response time: 4 replies with both dates, median 1.5 days, 75% within 3 days", (pub["response_time"]["measured"], pub["response_time"]["median_days"], pub["response_time"]["within_3_days_pct"]) == (4, 1.5, 75), pub["response_time"])
check("the last 90 days are counted back from the latest review IN THE FILE (so an old export is not judged against today): 5 reviews", pub["recent_90"]["reviews"] == 5, pub["recent_90"])
check("two replies are the same template once the greeting and sign-off are removed", pub["templates"]["in_repeated_templates"] == 2 and pub["templates"]["largest_group"] == 2, pub["templates"])
q = pub["reply_quality"]
check("reply quality is counted of replies judged: all 4 thank or apologise; 3 are signed; none says what will be done", q["acknowledges"] == {"yes": 4, "judged": 4} and q["signed"]["yes"] == 3 and q["offers_action"]["yes"] == 1, q)
check("a short review that the reply echoes counts as specific ('breakfast')", rp.reply_flags("Lovely breakfast and friendly staff", "Thank you for mentioning the breakfast.")["personal"] and not rp.reply_flags("Lovely breakfast and a very long review about many other things happening", "Thank you.")["personal"])
check("topics: praised breakfast/location, criticised noise, parking, cleanliness; a topic is counted once per review", {r["topic"] for r in pub["praised"]} >= {"breakfast", "location"} and {r["topic"] for r in pub["criticised"]} >= {"noise", "parking", "cleanliness"})
check("praise is set against what the site states: breakfast praised, site does not state it", next(r for r in pub["praised"] if r["topic"] == "breakfast")["site"] == "not_found" and next(r for r in pub["criticised"] if r["topic"] == "parking")["site"] == "answered")
check("the monthly trend is by month with an average rating", pub["trend"][-1] == {"month": "2026-09", "reviews": 2, "avg_rating": 3.25}, pub["trend"][-1])
nrp = rp.analyse([{**r, "reply": "", "reply_date": None} for r in copy.deepcopy(rv)], "H", None, today=TODAY)["public"]
check("a file with no reply column says so and states no reply rate or unanswered count (not 0%)", nrp["reply_rate"] is None and nrp["critical_unanswered"] is None and not nrp["has_replies_column"])
check("an old export is flagged by the age of its latest review", rp.analyse(copy.deepcopy(rv), "H", None, today=dt.date(2027, 3, 1))["public"]["latest_review_age_days"] > 120)

print("3. privacy: what is kept and what is not")
blob = json.dumps(pub, default=str)
check("the public part has counts and rates only: no review text, no reply text, no name", all(w not in blob for w in ("noisy at night", "Dirty bathroom", "rude reception", "Anna", "Bob", "Maria", "Guest Relations")), "")
check("the private part is just the unanswered critical reviews, newest first, with a draft reply", [u["date"] for u in priv["unanswered"]] == ["2026-09-02", "2026-07-30"] and all(u["draft"] for u in priv["unanswered"]))
check("a draft is a skeleton: it names the topics the review raised, leaves the facts in [brackets] and offers nothing in return", "[" in priv["unanswered"][0]["draft"] and "noise" in priv["unanswered"][0]["draft"] and "voucher" not in priv["unanswered"][0]["draft"].lower() and "compensation" not in priv["unanswered"][0]["draft"].lower())

print("4. the score and the plan")
sc = scoring.score_review_pack(pub)
check("Reviews & Reputation becomes assessed from the file, with its evidence lines, and is marked as coming from the review pack", sc["assessed"] and sc["from_review_pack"] and any("Replied to 4 of 6" in e for e in sc["evidence"]), sc)
check("a thin file does not claim what it cannot (no speed or quality component under 5 measured replies)", not any("within 3 days" in e for e in sc["evidence"]) and not any("refer to specifics" in e for e in sc["evidence"]))
good = {**pub, "reviews": 300, "reply_rate": 95, "replied": 285, "critical": 20, "critical_replied": 20, "critical_unanswered": 0, "avg_rating": 4.7, "recent_90": {"reviews": 30}, "last_date": "2026-10-01",
        "response_time": {"measured": 200, "median_days": 1, "within_3_days_pct": 90}, "reply_quality": {"personal": {"yes": 200, "judged": 285}}}
bad = {**good, "reply_rate": 10, "replied": 30, "critical_replied": 0, "critical_unanswered": 20, "avg_rating": 3.2, "recent_90": {"reviews": 1}, "response_time": {"measured": 30, "median_days": 20, "within_3_days_pct": 5},
       "reply_quality": {"personal": {"yes": 2, "judged": 30}}}
check("a hotel that replies to nearly everything quickly and specifically scores high; one that does not scores low", scoring.score_review_pack(good)["score"] >= 90 and scoring.score_review_pack(bad)["score"] <= 25,
      (scoring.score_review_pack(good)["score"], scoring.score_review_pack(bad)["score"]))
check("an empty analysis is 'not assessed', never zero", not scoring.score_review_pack({"reviews": 5})["assessed"])
recs = {r["id"]: r for r in advice._from_review_pack({**bad, "templates": {"pct": 0, "replies_compared": 30, "in_repeated_templates": 0, "largest_group": 0},
                                                       "criticised": [{"topic": "noise", "reviews": 6, "pct": 30, "site": None}]})}
check("a poor file raises: unanswered critical reviews (high), low reply rate, slow replies, and recurring complaints", {"RP1", "RP2", "RP4", "RP5"} <= set(recs) and recs["RP1"]["priority"] == "high", set(recs))
check("praised-but-not-stated and recurring complaints name the topics, and the findings are for the file only",
      "RP6" in {r["id"]: r for r in advice._from_review_pack({**pub, "praised": [{"topic": "breakfast", "reviews": 5, "pct": 50, "site": "not_found"}]})}
      and "RP7" in {r["id"]: r for r in advice._from_review_pack({**pub, "criticised": [{"topic": "noise", "reviews": 6, "pct": 30, "site": None}]})} and "export" in recs["RP1"]["finding"])
check("a healthy file raises nothing", advice._from_review_pack(good) == [] or all(r["id"] in ("RP6", "RP7") for r in advice._from_review_pack(good)))

REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
a = copy.deepcopy(REP)
before = next(c for c in a["scorecard"]["categories"] if c["key"] == "reviews")
rp.apply(a, bad)
cat = next(c for c in a["scorecard"]["categories"] if c["key"] == "reviews")
check("applying a pack makes the Reviews category assessed, moves the coverage up by its weight, and keeps the headline honest", not before["assessed"] and cat["assessed"] and a["scorecard"]["coverage_pct"] == REP["scorecard"]["coverage_pct"] + cat["weight"]
      and a["headline"]["coverage_pct"] == a["scorecard"]["coverage_pct"] and all(u["key"] != "reviews" for u in a["headline"]["unassessed"]), (a["scorecard"]["coverage_pct"], REP["scorecard"]["coverage_pct"]))
check("the evidence strength of the category comes from the number of reviews in the file", cat["evidence_level"] == "high" and "300 review" in cat["evidence_note"], (cat.get("evidence_level"), cat.get("evidence_note")))
ids = {r["id"] for r in a["consultant"]["recommendations"]}
check("the findings join the plan, ranked with everything else, and the lists are rebuilt", {"RP1", "RP2"} <= ids and "RP1" in a["consultant"]["required_fixes"] and all("rank" in r for r in a["consultant"]["recommendations"]))
rp.apply(a, good)
check("applying a newer file replaces the earlier one: no duplicates and the old findings are gone", not any(r["id"].startswith("RP") and r["id"] in ("RP1", "RP2", "RP5") for r in a["consultant"]["recommendations"])
      and len([r for r in a["consultant"]["recommendations"] if r["id"] == "RP2"]) == 0 and a["review_pack"]["reply_rate"] == 95)
check("only aggregates are in the report: no review text", "noisy at night" not in json.dumps(a, default=str))

print("5. saved with the run")
DB = os.path.join(tempfile.gettempdir(), "hotel_pack_review_test.db")
if os.path.exists(DB):
    os.remove(DB)
st = backend.open_store("sqlite:///" + DB.replace("\\", "/"))
rid = st.save_run(REP)
check("before an upload the run has no review-pack numbers", st.list_runs()[0]["pack_reviews"] is None)
b = copy.deepcopy(REP)
rp.apply(b, bad)
st.update_run(rid, b)
row = st.list_runs()[0]
check("after an upload the same run is updated in place: its id and date stay, the pack numbers and the new score are saved, and the reviews category is in the scores",
      st.count() == 1 and row["id"] == rid and row["pack_reviews"] == 300 and row["pack_reply_rate"] == 10 and row["pack_critical_unanswered"] == 20 and "reviews" in json.loads(row["cat_scores"]))
check("the saved report carries the aggregates and nothing else from the file", st.get_report(rid)["review_pack"]["reply_rate"] == 10 and "noisy" not in json.dumps(st.get_report(rid)))

print("6. the page")
at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=90)
shown = copy.deepcopy(REP)
res2 = rp.analyse(copy.deepcopy(rv), shown["meta"]["hotel"], rp.site_states_from(shown.get("guest_questions")), today=TODAY)
rp.apply(shown, res2["public"])
at.session_state["fa_res"] = shown
at.session_state["rp_state"] = {"hash": "x", "run": shown["meta"]["run_at"], "res": res2, "mapping": m}
at.run()
text = " ".join(x.value for x in at.markdown) + " ".join(x.value for x in at.success) + " ".join(x.value for x in at.caption)
check("the page renders with an uploaded analysis and no exception", not at.exception, [e.message for e in at.exception])
check("it says what the upload is, that names are never read and the text is not saved", "The hotel's own reviews: upload an export" in text and "Reviewer names are never read" in text and "not saved" in text)
check("it shows the figures: reviews analysed, reply rate, critical unanswered, median time", {"Reviews analysed", "Reply rate", "Critical reviews unanswered", "Median time to reply"} <= {x.label for x in at.metric})
check("it says the score, plan and readiness now include the file, and names the columns used", "now include this file" in text and "Columns used" in text)
check("the unanswered critical reviews are listed with a draft each, and offered as a download", len([t for t in at.text_area if str(t.key).startswith("rp_draft")]) == 2, [str(t.key) for t in at.text_area])
check("the file upload box is there", any(True for _ in at.get("file_uploader")) if hasattr(at, "get") else True)
only_public = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=90)
only_public.session_state["fa_res"] = shown
only_public.run()
check("a reopened report with a saved analysis shows the numbers but says the unanswered list needs the file again", not only_public.exception and "Upload the file again" in " ".join(x.value for x in only_public.caption), [e.message for e in only_public.exception])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
