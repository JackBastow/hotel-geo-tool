"""
The AI sample survives a busy provider (code review, Nov 2026): one failed question no longer ends the sample; a question that failed for a passing reason is asked again; only an error that
will not go away (bad key, no credit) stops the rest; the hotel's tracked prompts go first, are finished even when the extra questions used the budget, and are kept even when the
town-wide round failed. No network: a stand-in client.
Run: python test_ai_resilience.py
"""
import sys
import threading
import warnings

warnings.filterwarnings("ignore")
import ai_sample

ai_sample.time.sleep = lambda s: None          # no real pauses in the test
fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


class Busy(Exception):
    status_code = 529


class NoCredit(Exception):
    status_code = 402


class Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class Resp:
    def __init__(self, text):
        self.content = [Block(text)]
        self.usage = type("U", (), {"input_tokens": 1000, "output_tokens": 100, "server_tool_use": type("S", (), {"web_search_requests": 1})()})()
        self.stop_reason = "end_turn"


class Client:
    """Answers every question; fails the ones listed in `fail_once` the first time, and every question once `fatal_after` calls have been made."""

    def __init__(self, fail_once=(), fatal_after=None):
        self.fail_once, self.fatal_after, self.calls, self.lock, self.seen = set(fail_once), fatal_after, 0, threading.Lock(), []
        self.messages = self

    def create(self, **kw):
        q = kw["messages"][0]["content"]
        with self.lock:
            self.calls += 1
            self.seen.append(q)
            if self.fatal_after is not None and self.calls > self.fatal_after:
                raise NoCredit("credit balance too low")
            if q in self.fail_once:
                self.fail_once.discard(q)
                raise Busy("overloaded")
        return Resp("1. Brooklands Hotel - stylish\n2. Oatlands Park Hotel")


QS = [{"id": f"q{i}", "kind": "niche", "text": f"Question {i} about hotels in Weybridge"} for i in range(6)]

print("1. a busy moment does not end the sample")
c = Client(fail_once={"Question 2 about hotels in Weybridge", "Question 4 about hotels in Weybridge"})
items, spent, why = ai_sample.ask_all("Brooklands Hotel", "Weybridge", QS, client=c, model="claude-haiku-4-5", repeats=1, workers=3)
check("every question is answered, the two that failed once included", len(items) == 6, (len(items), why))
check("and nothing is reported as missing", why == "", why)

print("2. an error that will not go away stops the rest, and says why")
c = Client(fatal_after=2)
items, spent, why = ai_sample.ask_all("Brooklands Hotel", "Weybridge", QS, client=c, model="claude-haiku-4-5", repeats=1, workers=1)
check("it stops after the error instead of asking every question again", len(items) == 2 and c.calls <= 4, (len(items), c.calls))
check("the reason names the cause", "credit" in why.lower(), why)

print("3. the hotel's tracked prompts")
tracked = [{"id": "t1", "kind": "niche", "source": "benchmark", "text": "Tracked prompt about Weybridge hotels"}]
c = Client()
items, spent, why = ai_sample.ask_all("Brooklands Hotel", "Weybridge", QS + tracked, client=c, model="claude-haiku-4-5", repeats=1, workers=1, budget_usd=0.0001)
check("go first, and are asked even when the budget for the others is used", c.seen and c.seen[0] == "Tracked prompt about Weybridge hotels" and any(i.get("source") == "benchmark" for i in items), c.seen[:2])
first_failed = {"status": "unavailable", "reason": "rate limit", "items": []}
extra = {"items": items, "cost_usd": 0.01}
merged = ai_sample.merge(first_failed, extra)
check("are kept when the town-wide round failed", merged.get("status") == "ok" and any(i.get("source") == "benchmark" for i in merged["items"]) and merged.get("partial"), merged.get("status"))
ev = threading.Event()
ev.set()
c = Client()
items, spent, why = ai_sample.ask_all("Brooklands Hotel", "Weybridge", QS, client=c, model="claude-haiku-4-5", repeats=1, workers=1, stop_event=ev)
check("a round the check has stopped makes no more calls", c.calls == 0 and items == [])

print("4. an answer the analysis could not read")
import ai_insights
_items = [{"id": f"g{k}", "kind": "generic", "answer": "1. Brooklands Hotel\n2. Oatlands Park Hotel", "mentioned": True} for k in range(12)]
_calls = {"n": 0}
_orig = ai_insights._extract_batch


def _fake_batch(client, model, batch, hotel, city, diag=None):
    _calls["n"] += 1
    if any(i["id"] == "g0" for i in batch):
        return None, (10, 10)
    return {"answers": [{"id": i["id"], "hotels": [{"name": "Brooklands Hotel", "rank": 1}, {"name": "Oatlands Park Hotel", "rank": 2}]} for i in batch], "about": {}}, (10, 10)


ai_insights._extract_batch = _fake_batch
try:
    _ex, _u = ai_insights.extract(None, "m", _items, "Brooklands Hotel", "Weybridge")
    _lb = ai_insights.leaderboard(_ex, _items, "Brooklands Hotel")
finally:
    ai_insights._extract_batch = _orig
_me = next(r for r in _lb["rows"] if r["is_target"])
check("a batch that could not be read is asked again in smaller groups, so one bad answer costs only itself", _ex["failed_ids"] == ["g0"] and _calls["n"] > 3, (_ex["failed_ids"], _calls["n"]))
check("that answer is left out of the totals, not counted as naming nobody (11 of 11, not 11 of 12)", (_me["mentions"], _me["of"]) == (11, 11), (_me["mentions"], _me["of"]))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
