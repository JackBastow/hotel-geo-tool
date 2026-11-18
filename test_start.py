"""
Offline test: the Start here screen (start_here.py). Fake data, no network.
Run: python test_start.py
"""
import json
import warnings

warnings.filterwarnings("ignore")
import portal_view
import start_here

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


def act(i, title, pri, effort="low", status="todo", state="open", first=2, done_at="", resolved_at=""):
    return {"id": i, "title": title, "priority": pri, "effort": effort, "status": status, "state": state, "resolution": "", "reopened": 0, "team": "web", "source": "content", "first_run_id": first,
            "done_at": done_at, "resolved_at": resolved_at, "rec_json": json.dumps({"finding": f"Finding {i}", "action": f"Do {i} on the rooms page", "why": "Because.", "evidence": [{"url": "https://h.example/rooms/", "snippet": "Rooms page text"}], "id": f"R{i}", "tag": "t", "source": "content"})}


class DB:
    def competitor_history(self, key, top=5):
        runs = [{"run_id": 1, "run_at": "2026-11-02T08:00:00+00:00"}, {"run_id": 2, "run_at": "2026-11-09T08:00:00+00:00"}]
        pt = lambda a, b: [{"run_id": 1, "coverage_pct": a, "sentiment": None, "avg_rank": None, "mentions": 0, "asked": 20}, {"run_id": 2, "coverage_pct": b, "sentiment": None, "avg_rank": None, "mentions": 0, "asked": 20}]
        return {"runs": runs, "rows": [{"name": "Our Hotel", "is_target": True, "points": pt(10, 15)}, {"name": "Rival One", "is_target": False, "points": pt(40, 45)}, {"name": "New Rival", "is_target": False, "points": pt(0, 20)}]}


hotel = {"id": 1, "name": "Our Hotel", "hotel_key": "h.example", "city": "Zurich", "website": "h.example", "weekly": 1}
sm = {"hotel": hotel, "runs": 2, "first_run_at": "2026-11-02T08:00:00+00:00", "last_run_at": "2026-11-09T08:00:00+00:00", "first_score": 60.0, "latest_score": 66.0, "delta": 6.0,
      "points": [{"run_at": "2026-11-02T08:00:00+00:00", "score": 60.0, "id": 1}, {"run_at": "2026-11-09T08:00:00+00:00", "score": 66.0, "id": 2}], "cov_first": (2, 20), "cov_latest": (3, 20),
      "actions": {"completed": 1, "verified": 0, "cleared_site": 0, "working": 0, "todo": 4, "cleared": 0, "not_relevant": 0, "still_flagged": 0, "total": 5}, "latest_run_id": 2, "completed_points": []}
acts = [act(1, "Low priority thing", "low"), act(2, "Critical fix", "critical", "high"), act(3, "High quick fix", "high", "low"), act(4, "High slow fix", "high", "high"), act(5, "Medium thing", "medium"),
        act(6, "Finished this week", "high", status="done", done_at="2026-11-10T09:00:00+00:00"), act(7, "Finished long ago", "high", status="done", done_at="2026-10-01T09:00:00+00:00")]
runs = [{"id": 2, "run_at": "2026-11-09T08:00:00+00:00", "headline_score": 66.0, "recs_total": 5, "access_token": "tok"}, {"id": 1, "run_at": "2026-11-02T08:00:00+00:00", "headline_score": 60.0, "recs_total": 4, "access_token": "t0"}]

html = start_here.panel(DB(), hotel, sm, acts, runs, True)
check("it shows how visible the hotel is, the score and who is recommended instead", "Named by an AI assistant" in html and "Readiness score" in html and "Recommended instead" in html and "Rival One" in html, html[:300])
check("the weekly view opens on what changed, before the actions", "What changed since the last check" in html and html.index("What changed") < html.index("Do these first"))
check("the score movement is stated with both numbers", "went up by 6" in html and "60 to 66" in html)
check("a rival that is new in the answers is named", "New in the answers" in html and "New Rival" in html)
check("an action finished since the last check is listed, one finished long ago is not", "Finished this week" in html.split("What changed")[1].split("Do these first")[0] and "Finished long ago" not in html)
check("the three first actions are the most serious open ones, quick before slow", [t for t in ("Critical fix", "High quick fix", "High slow fix") if t in html.split("Do these first")[1]] == ["Critical fix", "High quick fix", "High slow fix"] and "Low priority thing" not in html.split("Do these first")[1] and "Medium thing" not in html.split("Do these first")[1])
check("each shows what to do and a Done button at once, numbered, with the reasoning and evidence one click away", html.count('class="act-do"') == 3 and html.count('class="act-n"') == 3 and "Do 2 on the rooms page" in html and "Rooms page text" in html and 'data-v="done"' in html and 'class="rec-d" open' not in html)
check("it says movement is not proof of cause", "not cause" in html)
first = start_here.panel(DB(), hotel, {**sm, "runs": 1}, acts, runs[:1], True)
check("the first check says it is the baseline and puts the actions first, with no change claimed", "This is the first check" in first and "What changed" not in first and first.index("Do these first") < first.index("first check"))
check("a read-only view (the operator's) has no Done buttons", 'data-v="done"' not in start_here.panel(DB(), hotel, sm, acts, runs, False))
check("with no check yet it says so", "has not run yet" in start_here.panel(DB(), hotel, {**sm, "runs": 0}, [], [], True))


class Broken:
    def competitor_history(self, *a, **k):
        raise RuntimeError("db down")


check("a failing history query leaves the tile out but the screen still shows", "Do these first" in start_here.panel(Broken(), hotel, sm, acts, runs, True))
check("safe() never raises on bad input", isinstance(start_here.safe(None, None, None, None, [{"run_at": "x"}], True), str))
d = portal_view.dashboard(sm, acts, runs, editable=True, csrf="c", start=html)
check("the dashboard puts Start here first and keeps every other tab", d.index('data-name="start"') < d.index('data-name="overview"') and all(f'data-name="{k}"' in d for k in ("ai", "strategy", "prompts", "actions", "history")))
check("without it the dashboard is as before", 'data-name="start"' not in portal_view.dashboard(sm, acts, runs, editable=True, csrf="c"))
import dashboard_view
_rep = {"ai_insights": {"brand_ranking": {"rows": [{"name": "Us", "is_target": True, "coverage_pct": 10}, {"name": "Rival A", "is_target": False, "coverage_pct": 40}]}}, "ai_sample": {"summary": {"top_domains": ["booking.com"]}}, "consultant": {}, "scorecard": {}, "headline": {}}
_g = dashboard_view.at_a_glance(_rep)
check("the report overview opens with who is named, who is recommended instead and which sites the answers drew on", "10%" in _g and "Rival A" in _g and "booking.com" in _g)
check("with no AI answers at all the row is left out rather than shown empty", dashboard_view.at_a_glance({"ai_insights": {}, "ai_sample": {}}) == "")

import progress
_a = lambda **k: {"status": "todo", "state": "open", "resolution": "", "reopened": 0, "done_at": "", "resolved_at": "", **k}
check("an action the checks merely stopped flagging is NOT completed: nobody marked it done", progress.classify(_a(state="resolved", resolution="verified")) == "cleared")
check("an action the hotel marked done is completed, whether or not the checks have confirmed it", progress.classify(_a(status="done")) == "completed" and progress.classify(_a(status="done", state="resolved", resolution="verified")) == "completed")
_c = progress.action_counts([_a(state="resolved", resolution="verified"), _a(state="resolved", resolution="verified"), _a(status="done"), _a()])
check("the counts keep the two apart: 1 completed, 2 no longer flagged", _c["completed"] == 1 and _c["cleared_site"] == 2 and _c["total"] == 4, _c)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
