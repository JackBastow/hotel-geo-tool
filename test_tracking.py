"""
Offline tests for measurement over time: honest ranges and bands (trend.py), a benchmark of prompts frozen at a hotel's first audit and asked again word for word, the comparison with the last audit, and the
database records behind it. No network. Run: python test_tracking.py
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
import trend
import ai_niche
import ai_questions as aq

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. honest ranges and bands")
lo, hi = trend.wilson(3, 9)
check("3 of 9 answers: the plausible range is wide, from about an eighth to about two thirds", 0.08 < lo < 0.2 and 0.55 < hi < 0.7, (lo, hi))
check("0 of 10 is 'not appearing' but the range still reaches into the twenties, never 'never'", trend.band(0, 10) == "not appearing" and trend.wilson(0, 10)[1] > 0.2)
check("bands are plain words and never 'always'", [trend.band(k, 12) for k in (0, 2, 6, 11)] == ["not appearing", "rarely", "sometimes", "usually"] and trend.band(0, 0) == "no answers")
check("the sentence carries the count, the band and the range", "named in 3 of 9 answers" in trend.describe(3, 9) and "sometimes" in trend.describe(3, 9) and "plausibly" in trend.describe(3, 9))


def items(text, named, n, kind="niche"):
    return [{"id": f"{abs(hash(text)) % 999}-{i}", "qid": text[:6], "kind": kind, "text": text, "mentioned": i < named, "answer": "x", "domains": [], "pages": [], "id2": 0} for i in range(n)]


now = items("Which 4-star hotels near the Opera suit a business trip?", 6, 6) + items("Best value 4-star near the Opera?", 1, 6) + items("Only asked now?", 3, 3)
before = items("Which 4-star hotels near the Opera suit a business trip?", 0, 6) + items("Best value  4-star near the Opera?", 1, 6) + items("Only asked before?", 2, 3)
cmp_ = trend.compare(now, before)
by = {r["text"]: r for r in cmp_["rows"]}
check("only prompts asked in both audits are compared (wording matched ignoring spacing and case), so a prompt asked once is left out", cmp_["prompts"] == 2 and "Only asked now?" not in by)
check("0 of 6 to 6 of 6 is a clear increase; 1 of 6 to 1 of 6 is no clear change", by["Which 4-star hotels near the Opera suit a business trip?"]["change"] == "more often" and by["Best value 4-star near the Opera?"]["change"] == "no clear change")
check("with so few answers a small change is called no clear change, not a trend", trend._change((3, 6), (2, 6)) == "no clear change" and trend._change((6, 6), (0, 6)) == "more often" and trend._change((0, 6), (6, 6)) == "less often" and trend._change((4, 6), (0, 6)) == "no clear change")
check("ignored: answers about the hotel itself and answers that could not be judged", trend.per_prompt([{"kind": "direct", "text": "t", "mentioned": True}, {"kind": "niche", "text": "t", "mentioned": None}]) == {})

print("2. the benchmark is frozen at the first audit and asked again word for word")
HOTEL, CITY = "Paris Marriott Opera Ambassador Hotel", "Paris"
PAGES = [{"url": "https://www.marriott.com/hotels/paroa/overview/", "text": "Paris Marriott Opera Ambassador Hotel is a 4-star hotel in the heart of Paris. Our meeting rooms host up to 120 delegates for conferences and business events."}]
LEVEL = lambda *keys: [{"key": k, "label": k, "level": "strong"} for k in keys]      # noqa: E731
prof = ai_niche.profile(HOTEL, CITY, [], None, PAGES, LEVEL("meeting_rooms"), LEVEL("meetings", "business"), classes=["business", "city_centre"])
anch = [{"name": "Palais Garnier", "kind": "attraction", "km": 0.18, "views": 52000, "source": "Wikipedia (places near the hotel's coordinates)"}]
first = aq.build(prof, HOTEL, CITY, anch, base_repeats=2)
check("the first audit has no benchmark, so its core questions become it, to be saved", not first["benchmark_reused"] and len(first["benchmark_prompts"]) >= 2 and all(b["text"] for b in first["benchmark_prompts"]))
frozen = first["benchmark_prompts"]
anch2 = [{"name": "Galeries Lafayette", "kind": "attraction", "km": 0.4, "views": 9000, "source": "Wikipedia"}]
second = aq.build(prof, HOTEL, CITY, anch2, base_repeats=2, benchmark=frozen)
core = [q for q in second["questions"] if q["priority"] == "core"]
check("a later audit asks the frozen prompts again, word for word, as its core questions, even though the places nearby were worked out differently", [q["text"] for q in core] == [b["text"] for b in frozen] and second["benchmark_reused"] and not second["benchmark_prompts"], [q["text"] for q in core])
check("fresh questions are added as exploratory ones (secondary), never in place of the benchmark", all(q["priority"] == "secondary" for q in second["questions"] if q not in core) and not any(q["text"] in [b["text"] for b in frozen] for q in second["questions"] if q not in core))
check("benchmark questions carry their own count (3) and say why they are asked", all(q["repeats"] == 3 and "benchmark" in q["why"].lower() for q in core), [(q["repeats"], q["why"][:40]) for q in core])

print("3. the database keeps it, and never overwrites it")
DB = os.path.join(tempfile.gettempdir(), "hotel_tracking_test.db")
if os.path.exists(DB):
    os.remove(DB)
URL = "sqlite:///" + DB.replace("\\", "/")
s = backend.open_store(URL)
check("no benchmark before the first audit", s.get_benchmark("marriott.com/en-us/hotels/x") == [])
check("it is saved once", s.save_benchmark("marriott.com/en-us/hotels/x", frozen) is True and s.get_benchmark("marriott.com/en-us/hotels/x") == frozen)
check("a second save does not overwrite it: that is what makes later audits comparable", s.save_benchmark("marriott.com/en-us/hotels/x", [{"text": "different?", "angle": "x", "why": "y"}]) is False and s.get_benchmark("marriott.com/en-us/hotels/x") == frozen)

HERE = os.path.dirname(os.path.abspath(__file__))
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
r1 = copy.deepcopy(REP)
r1["benchmark"] = {"prompts": frozen, "reused": False}
reports = server.Reports(URL)
tok = reports.save(r1)
check("saving a first report stores its benchmark under the hotel's key", backend.hotel_key(r1) and s.get_benchmark(backend.hotel_key(r1)) == frozen, s.get_benchmark(backend.hotel_key(r1)))
r2 = copy.deepcopy(REP)
r2["meta"]["run_at"] = "2026-11-20T10:00:00+00:00"
r2["benchmark"] = {"prompts": [{"text": "other?", "angle": "x", "why": "y"}], "reused": True}
tok2 = reports.save(r2)
check("a later report that reused the benchmark does not replace it", s.get_benchmark(backend.hotel_key(r2)) == frozen)
prev = reports.previous_full(tok2)
check("the previous audit is available as a whole report for the per-prompt comparison", prev is not None and prev["meta"]["run_at"] == REP["meta"]["run_at"], str((prev or {}).get("meta", {}).get("run_at")))

print("4. the audit loads the benchmark for the hotel and passes it on")
seen = {}
import full_audit
orig = full_audit.run_full_audit
full_audit.run_full_audit = lambda *a, **kw: (seen.update(kw), copy.deepcopy(REP))[1]
try:
    cfg = audit_service.Config({"DATABASE_URL": URL})
    # the hotel key of a chain page is its host plus the hotel's folder
    s.save_benchmark("www.example-chain.com/hotel/42".replace("www.", ""), frozen)
    audit_service.run({"website": "https://www.example-chain.com/hotel/42/index.en.shtml", "hotel": "X", "city": "Y"}, cfg)
finally:
    full_audit.run_full_audit = orig
check("run() passes the stored benchmark for that hotel's address to the audit", seen.get("benchmark") == frozen, str(seen.get("benchmark"))[:120])

print("5. the report shows the comparison")
import report_view
cur = copy.deepcopy(REP)
cur["ai_sample"] = {"status": "ok", "model": "m", "run_at": "2026-11-20", "items": now, "summary": __import__("ai_sample").summarise(now)}
old = copy.deepcopy(REP)
old["ai_sample"] = {"status": "ok", "model": "m", "run_at": "2026-10-20", "items": before, "summary": __import__("ai_sample").summarise(before)}
old["meta"]["run_at"] = "2026-10-20T10:00:00+00:00"
html = report_view.render(cur, token="t" * 32, prev_full=old)
check("the AI tab has a 'Compared with the last audit' section naming the date and calling the clear change", "Compared with the last audit" in html and "2026-10-20" in html and "more often" in html)

print("6. the searches are run as if from the hotel's own country, and nothing breaks if the API refuses that")
import ai_sample
from types import SimpleNamespace as NS


class Bad(Exception):
    status_code = 400


class FakeC:
    def __init__(self, refuse=False):
        self.messages, self.refuse, self.tools = self, refuse, []

    def create(self, **kw):
        self.tools.append(kw["tools"][0])
        if self.refuse and "user_location" in kw["tools"][0]:
            raise Bad("user_location not accepted")
        return NS(content=[NS(type="text", text="1. Hotel Alpha 2. Hotel Beta", citations=None)], stop_reason="end_turn", usage=NS(input_tokens=100, output_tokens=20, server_tool_use=NS(web_search_requests=1)))


q = [{"id": "x", "kind": "niche", "text": "Which hotels near the Opera suit a business trip?", "repeats": 1}]
fc = FakeC()
it, _s, _w = ai_sample.ask_all(HOTEL, CITY, q, client=fc, model="claude-haiku-5-5", country="FR")
check("the search tool is told the country, and each answer records it", fc.tools[0].get("user_location") == {"type": "approximate", "country": "FR"} and it[0]["search_country"] == "FR")
fr = FakeC(refuse=True)
it2, _s, why = ai_sample.ask_all(HOTEL, CITY, q * 1, client=fr, model="claude-haiku-5-5", country="FR")
check("if the API refuses the setting the question is asked again without it, the answer is kept, no error is raised, and the item says no country was applied", len(it2) == 1 and it2[0]["search_country"] is None and "user_location" not in fr.tools[-1] and not why, (why, [list(t) for t in fr.tools]))
it3, _s, _w = ai_sample.ask_all(HOTEL, CITY, q, client=FakeC(), model="claude-haiku-5-5")
check("with no country nothing is added", it3[0]["search_country"] is None)
ex = ai_sample.run_extra(HOTEL, CITY, q, client=FakeC(), model="claude-haiku-5-5", country="FR")
check("the round's envelope carries the country when it was applied", ex["search_country"] == "FR")
import anchors
resp = lambda u, **k: type("R", (), {"status_code": 200, "json": lambda self: [{"lat": "48.87", "lon": "2.33", "display_name": "Hotel, Paris, France", "address": {"city": "Paris", "country_code": "fr"}}]})()
check("the country comes from the one map search that places the hotel", anchors.geocode(HOTEL, CITY, resp, with_country=True) == (48.87, 2.33, "FR"))
import phones
check("or from the website's ending when it has one", phones.region_from_host("www.hotel-example.fr") == "FR" and phones.region_from_host("marriott.com") is None)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
