"""
Every Claude answer is metered where it is received (code review, Nov 2026: about 15% of the spend was never recorded). Offline: a stand-in client and a stand-in store.
Run: python test_costs.py
"""
import sys
import types
import warnings

warnings.filterwarnings("ignore")
import ai_sample
import costs

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


recorded = []
fake_store = types.SimpleNamespace(record_usage=lambda calls, audits=1, service="gemini": recorded.append((service, calls, audits)))
sys.modules["store"] = fake_store

NS = types.SimpleNamespace


class Fake:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        return NS(content=[NS(type="text", text="An answer.", citations=None)], stop_reason="end_turn",
                  usage=NS(input_tokens=20000, output_tokens=1000, server_tool_use=NS(web_search_requests=2)))


c = costs.metered(Fake())
one = ai_sample.cost_usd("claude-haiku-5-5", 20000, 1000, 2)
for _ in range(10):
    c.messages.create(model="claude-haiku-5-5", max_tokens=100, messages=[])
costs.flush()
total_milli = sum(n for s, n, _a in recorded if s == "claude")
check("ten answers are priced and recorded to the month's spend", abs(total_milli - round(10 * one * 1000)) <= 1, (total_milli, 10 * one * 1000))
check("the spend is recorded without counting extra audits", all(a == 0 for _s, _n, a in recorded))
check("a metered client is not metered twice", costs.metered(c) is c)
check("the shared client maker meters every answer", "costs.metered" in open("ai_sample.py", encoding="utf8").read())
rep = {"ai_sample": {"cost_usd": 0.1}, "ai_gap": {"cost_usd": 0.05}, "forums": {"cost_usd": 0.02}, "reddit": {"cost_usd": 0.01}, "question_plan": {"cost_usd": 0.01},
       "guest_questions": {"reader_cost_usd": 0.03, "ai_extract": {"cost_usd": 0.04}}, "listing_lookup": {"cost_usd": 0.02}, "ai_insights": {"cost_usd": 0.02}, "review_snapshot": {"cost_usd": 0.01}}
check("a check's own cost includes every part (gap analysis, forums, Reddit, page reading, question writer)", costs.report_usd(rep) == 0.31, costs.report_usd(rep))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
