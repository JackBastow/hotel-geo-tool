"""
Offline test: the deeper AI test asks more prompts, of more kinds, more times; the weekly checks keep the lighter test; short-search and conversational variants of the same intents never name the hotel. No network.
Run: python test_depth.py
"""
import warnings

warnings.filterwarnings("ignore")
import ai_niche
import ai_questions as aq
import ai_sample
import audit_service
import depth
import engines
import scheduler

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


PAGES = [{"url": "https://h.com/", "text": "Hotel Opera is a 4-star hotel near the Palais Garnier in Paris. Meeting rooms host 120 delegates. Parking. Fitness centre."}]
L = lambda *k: [{"key": x, "label": x, "level": "strong"} for x in k]      # noqa: E731
prof = ai_niche.profile("Hotel Opera", "Paris", [], None, PAGES, L("meeting_rooms", "parking", "gym"), L("meetings", "business"), classes=["business", "city_centre"])
anch = [{"name": "Palais Garnier", "kind": "attraction", "km": 0.2, "views": 1, "source": "Wikipedia"}, {"name": "Louvre", "kind": "attraction", "km": 1.2, "source": "x"}]
std = aq.build(prof, "Hotel Opera", "Paris", anch, base_repeats=depth.limits("standard")["repeats"], depth="standard")["questions"]
deep = aq.build(prof, "Hotel Opera", "Paris", anch, base_repeats=depth.limits("deep")["repeats"], depth="deep")["questions"]
print("1. more prompts, more kinds, more repeats")
check("the deep test asks more different prompts than the standard one", len(deep) > len(std), (len(std), len(deep)))
check("and many more answers in all (each prompt asked more times)", sum(q["repeats"] for q in deep) >= 2 * sum(q["repeats"] for q in std), (sum(q["repeats"] for q in std), sum(q["repeats"] for q in deep)))
check("the core prompts are asked 5 times in the deep test, 3 in the standard", max(q["repeats"] for q in deep if q["priority"] == "core") == 5 and max(q["repeats"] for q in std if q["priority"] == "core") == 3)
styles = {q.get("style") for q in deep if q.get("style")}
check("the deep test adds other kinds of prompt: short searches and conversational requests", {"short search", "conversational"} <= styles, styles)
check("the standard test has none of those variants", not any(q.get("style") for q in std))
check("no prompt names the hotel", not any("opera" in q["text"].lower() and "hotel opera" in q["text"].lower() for q in deep))
check("the conversational ones repeat an existing intent word for word after a short lead-in", any(q["text"].endswith(next(c["text"] for c in deep if c["priority"] == "core" and c["text"] in q["text"])) for q in deep if q.get("style") == "conversational"))
check("the town-wide prompts also come in more kinds in a deep test (12 against 6)", len(ai_sample.build_questions("Hotel Opera", "Paris", (), 12)) == 12 and len(ai_sample.build_questions("Hotel Opera", "Paris", (), 8)) == 6)
check("the deeper test has a bigger budget and more workers, and reserves more of the month's allowance", depth.limits("deep")["budget_niche"] > depth.limits("standard")["budget_niche"] and depth.limits("deep")["workers"] > depth.limits("standard")["workers"]
      and depth.limits("deep")["reserve_millidollars"] > depth.limits("standard")["reserve_millidollars"])

print("2. who uses which")
cfg = audit_service.Config({"CRON_TOKEN": "x"})
check("manual and demo audits use the deep test; weekly checks use the standard one", cfg.ai_depth == "deep" and cfg.weekly_ai_depth == "standard")
cfg2 = audit_service.Config({"AI_DEPTH": "standard", "WEEKLY_AI_DEPTH": "deep"})
check("both can be changed in the settings", cfg2.ai_depth == "standard" and cfg2.weekly_ai_depth == "deep")
w = scheduler.Weekly(cfg, None, lambda p, cb: None)
check("a weekly check asks for the weekly depth", w.params_for({"website": "a.com", "name": "A", "city": "X", "tier": "", "audiences": ""})["depth"] == "standard")
check("an unknown depth falls back to standard", depth.clean("banana") == "standard")

print("3. the report says what was asked")
ai = {"status": "ok", "model": "claude-haiku-5-5", "items": [{"qid": f"q{i % 3}", "id": f"q{i % 3}#{i}", "kind": "niche", "text": "t", "answer": "a", "mentioned": False, "pages": [], "domains": []} for i in range(9)],
      "summary": {"prompts": 3}, "search_country": "France", "run_at": "2026-11-05"}
row = engines.rows({"ai_sample": ai})[0]
check("the tested-assistant row gives the number of prompts, answers and the repeats", "3 different prompts, 9 answers in all" in row["detail"] and "asked 3 times" in row["detail"], row["detail"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
