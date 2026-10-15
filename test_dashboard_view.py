"""
Offline tests for charts.py (SVG charts) and dashboard_view.py (the Overview and the Action plan). Run: python test_dashboard_view.py
"""
import copy
import json
import os
import re

import charts
import dashboard_view as dv

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))

print("1. charts")
d = charts.donut([{"label": "Answered", "value": 6, "colour": "#0a0"}, {"label": "Partly", "value": 3, "colour": "#fa0"}, {"label": "Not found", "value": 1, "colour": "#f00"}, {"label": "Couldn't check", "value": 0, "colour": "#999"}], top="6/10", bottom="answered")
check("a donut draws a ring segment for each part that has a value, a legend with every part's count, and the number in the middle", d.count("<circle") == 4 and "Couldn&#x27;t check <b>0</b>" in d and "6/10" in d, d[:200])
check("a donut with nothing in it draws only the empty track", charts.donut([{"label": "x", "value": 0, "colour": "#000"}]).count("<circle") == 1)
rd = charts.radar([{"label": "Website", "value": 50}, {"label": "Social", "value": 45}, {"label": "Entity", "value": 100}, {"label": "Reviews", "value": None}])
check("a radar draws a point for every assessed area and none for an area that was not assessed (never a zero)", rd.count("<circle") == 3 and "Reviews" not in rd and "<polygon" in rd)
check("a radar needs three assessed areas, otherwise it draws nothing", charts.radar([{"label": "a", "value": 1}, {"label": "b", "value": 2}, {"label": "c", "value": None}]) == "")
b = charts.bars([{"label": "A <b>hotel</b>", "value": 50, "hot": True}, {"label": "Not assessed", "value": None}, {"label": "Other", "value": 80, "note": "n"}], suffix="%")
check("bars escape their labels, show 'n/a' for no value, and mark the hotel itself", "&lt;b&gt;hotel&lt;/b&gt;" in b and "<b>hotel</b>" not in b and 'class="ch-val na">n/a' in b and "ch-row hot" in b and "50%" in b)
mx = charts.matrix([{"n": 1, "title": "Fix <x>", "impact": "high", "effort": "low", "kind": "fix"}, {"n": 2, "title": "Big", "impact": "low", "effort": "high", "kind": "opportunity"}, {"n": 3, "title": "Odd", "impact": "weird", "effort": "none", "kind": "fix"}])
check("the priority map puts each item in its impact and effort cell, the quick-win corner is marked, and odd values fall in the middle",
      mx.count("mx-dot") == 3 and re.search(r'mx-cell win"><a class="mx-dot fix" href="#rec-1"', mx) and "&lt;x&gt;" in mx and 'href="#rec-3"' in mx)
check("a change since the last audit is a plain chip, green when it moved the right way, and empty when there is nothing to compare", "+4" in charts.delta(74, 70) and "up" in charts.delta(74, 70) and "down" in charts.delta(70, 74)
      and charts.delta(None, 70) == "" and charts.delta(70, None) == "" and "no change" in charts.delta(70, 70) and "down" in charts.delta(5, 2, better="down"))
check("the score ring shows a dash, not a zero, when there is no score", "&mdash;" in charts.ring(None) and ">74<" in charts.ring(74))

print("2. the Overview")
ov = dv.overview(REP, prev={"headline_score": 70, "ai_coverage_pct": 25, "ai_sentiment": 40})
check("it opens with the readiness score, its coverage and what was not measured, and the change since the last audit", "AI discoverability readiness" in ov and "Not measured" in ov and "AI Visibility" in ov and "+13" in ov)
ks = dv.kpis(REP, {"ai_coverage_pct": 25})
check("the headline numbers are AI coverage, place among hotels named, guest questions answered and reviews (here the replies seen in the public-search sample)",
      [k["label"] for k in ks] == ["Named by an AI assistant", "Place among hotels it names", "Guest questions answered", "Replies seen on reviews"], [k["label"] for k in ks])
check("AI coverage is 50% from 2 of 4 sampled answers, and shows +25 points against the last audit", ks[0]["value"] == "50" and "2 of 4" in ks[0]["sub"] and "+25" in ks[0]["delta"], ks[0])
check("guest questions: 5 answered of 10, with how many are partial and not found", ks[2]["value"] == "5" and ks[2]["unit"] == "of 10" and "4 partly" in ks[2]["sub"] and "1 not found" in ks[2]["sub"], ks[2])
bare_rv = copy.deepcopy(REP)
bare_rv["review_snapshot"] = None
check("with no review snapshot and no export the last tile invites one, marked as a prompt", dv.kpis(bare_rv)[3].get("cta") and dv.kpis(bare_rv)[3]["goto"] == "reputation")
packed = copy.deepcopy(REP)
packed["review_pack"] = {"reviews": 120, "reply_rate": 64, "critical_unanswered": 3}
check("with a review export the tile shows the reply rate, the number of reviews and the unanswered critical ones", dv.kpis(packed, {"pack_reply_rate": 50})[3]["value"] == "64" and "120 reviews" in dv.kpis(packed)[3]["sub"] and "+14" in dv.kpis(packed, {"pack_reply_rate": 50})[3]["delta"])
check("every headline tile jumps to the tab that explains it", all(f'data-goto="{g}"' in ov for g in ("ai", "site", "reputation")))
check("the top three priorities are shown first, each with why, the exact action, priority, effort and owner", ov.count('class="prio ') == 3 and ov.count("What to do") == 3 and "Effort:" in ov)
check("the charts are there: score by area (radar and bars), guest questions (donut), who the AI names (bars, the hotel highlighted)",
      "ch-radar" in ov and "ch-donut" in ov and "Who the AI assistant names" in ov and "ch-row hot" in ov)
check("an area that was not assessed reads n/a in the bars, never zero", "AI Visibility</div><div class=\"ch-track\"></div><div class=\"ch-val na\">n/a" in ov)
_tones = [i["tone"] for i in dv.insights(REP)]
check("'what stands out' leads with the risks, then the cautions, and ends with what is already working", {"bad", "warn", "good"} <= set(_tones) and _tones == sorted(_tones, key={"bad": 0, "warn": 1, "info": 2, "good": 3}.get), _tones)
check("the priority map is there with the quick-win corner", 'class="matrix"' in ov and "mx-cell win" in ov)

print("3. what stands out")
ins = dv.insights(REP)
titles = " | ".join(i["title"] for i in ins)
check("it reports the AI coverage honestly (one model, one day), the own-site share, and what the listing check found", "named the hotel in 50%" in titles and "behind 1 of 4 AI answers" in titles and "Booking.com shows a different check-in time" in titles, titles)
check("a former name still on a listing is a red item, and guest-question gaps are counted", any(i["tone"] == "bad" and "former name" in i["title"] for i in ins) and "guest questions are only partly answered" in titles)
check("every item names the tab it leads to", all(i["goto"] in dv.GOTO for i in ins))
none = copy.deepcopy(REP)
none["ai_insights"], none["ai_sample"], none["listing_checks"], none["consultant"]["working"] = None, None, None, []
check("with no AI sample the report says it was not run rather than inventing a figure", dv.kpis(none)[0]["value"] == "Not run" and "named the hotel" not in " ".join(i["title"] for i in dv.insights(none)))

print("4. the Action plan")
ap = dv.action_plan(REP)
n_recs = len(REP["consultant"]["recommendations"])
check("every recommendation is a numbered card, in the same numbers the priority map uses", ap.count('class="rec ') == n_recs and f'id="rec-{n_recs}"' in ap and 'id="rec-1"' in ap)
check("the cards are grouped: start here, fix next, opportunities", ap.index("Start here") < ap.index("Fix next") < ap.index("Opportunities, if the segment matters"))
check("each card carries why, the exact action, priority, effort, owner and confidence, and its full detail is one click away", "Confidence:" in ap and "Owner:" in ap and "Evidence, example wording and full detail" in ap and "What we found." in ap)
check("it can be filtered by start-here, fixes, opportunities and by team", all(f in ap for f in ('data-f="all"', 'data-f="start"', 'data-f="kind:fix"', 'data-f="kind:opportunity"', 'data-f="team:web"')))
check("the 30/60/90 plan is three columns of linked items", ap.count("plan-col") >= 3 and "First 30 days" in ap and "Days 61 to 90" in ap)
check("it says plainly that nothing here is a guarantee about what an assistant will recommend", "Nothing here is a guarantee" in ap)
check("a report with no consultant analysis says so", "did not run" in dv.action_plan({"consultant": {}}))
hostile = copy.deepcopy(REP)
hostile["consultant"]["recommendations"][0]["title"] = "<script>alert(1)</script> bad"
hostile["consultant"]["recommendations"][0]["why"] = '"><img src=x onerror=alert(1)>'
out = dv.action_plan(hostile) + dv.overview(hostile)
check("text from a recommendation cannot become markup", "<script>alert(1)" not in out and "<img src=x" not in out and "&lt;script&gt;" in out)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
