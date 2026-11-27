"""
Reading the hotels out of the sampled answers (ai_insights.extract): what happens when a reply is cut off, is not valid JSON, leaves an answer out, or the API fails.
Nine of fourteen stored checks lost whole groups of eight answers to one unreadable reply, with nothing recorded about why. The extraction now asks again in smaller groups, keeps what a
damaged reply still holds, bounds its repeat calls, and records what happened.
Run: python test_extraction.py
"""
import json
import re
import sys
from types import SimpleNamespace as NS

import ai_insights

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))
    if not cond:
        fails.append(name)


def items(n, kind="generic"):
    return [{"id": f"a{k}", "kind": kind, "text": f"q{k}", "answer": "1. Brooklands Hotel\n2. Oatlands Park Hotel", "mentioned": True} for k in range(n)]


def answer_json(i):
    return {"id": i, "hotels": [{"name": "Brooklands Hotel", "rank": 1, "reason": "well placed", "sentiment": "positive"}, {"name": "Oatlands Park Hotel", "rank": 2, "reason": "ok", "sentiment": "neutral"}]}


def reply(text, stop="end_turn", out=500):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop, usage=NS(input_tokens=4000, output_tokens=out))


class Fake:
    """A client whose reply for each call is decided by `rule(ids, call_number)` -> a reply object, or raises."""

    def __init__(self, rule):
        self.rule, self.calls, self.seen = rule, 0, []
        self.messages = NS(create=self.create)

    def create(self, **kw):
        self.calls += 1
        ids = re.findall(r"^\[([^\]]+)\] \(", kw["messages"][0]["content"], re.M)
        self.seen.append(ids)
        return self.rule(ids, self.calls)


def good(ids):
    return reply(json.dumps({"answers": [answer_json(i) for i in ids], "about": {}}))


print("1. a reply cut off at the output limit still gives the answers written before the cut")


def cut_off(ids, n):
    if n == 1:
        full = json.dumps({"answers": [answer_json(i) for i in ids], "about": {}})
        cut = full[: full.index(json.dumps(answer_json(ids[5]))) + 40]          # stops inside the sixth answer
        return reply(cut, stop="max_tokens", out=6000)
    return good(ids)


c = Fake(cut_off)
log = {}
ex, _u = ai_insights.extract(c, "m", items(8), "Brooklands Hotel", "Weybridge", log=log)
check("all eight answers end up read (five from the cut-off reply, three asked again)", ex and len(ex["answers"]) == 8 and ex["failed_ids"] == [], (len(ex["answers"]) if ex else None, ex and ex["failed_ids"]))
check("only the answers lost to the cut were asked for again", c.calls == 2 and c.seen[1] == ["a5", "a6", "a7"], c.seen)
check("the record says the reply was cut off, that it was salvaged and what was recovered on the second ask",
      log["cut_off_replies"] == 1 and log["salvaged_replies"] == 1 and log["recovered_on_retry"] == 3 and log["unprocessed"] == 0 and log["calls_detail"][0]["stop_reason"] == "max_tokens", log)

print("2. one malformed answer no longer discards its seven neighbours")


def poison(ids, n):
    return reply("Sorry, I could not do that {not json") if "a3" in ids else good(ids)


c = Fake(poison)
log = {}
ex, _u = ai_insights.extract(c, "m", items(8), "Brooklands Hotel", "Weybridge", log=log)
check("seven answers read, only the malformed one left unprocessed", ex and len(ex["answers"]) == 7 and ex["failed_ids"] == ["a3"], ex and ex["failed_ids"])
check("it says why", "not valid JSON" in " ".join(ex["failed"].values()) and log["reasons"] and log["unreadable_replies"] >= 1, log.get("reasons"))
check("the number of calls is small (1 + a halving search)", c.calls <= 8, c.calls)

print("3. the repeat calls are bounded")
c = Fake(lambda ids, n: reply("no json at all"))
log = {}
ex, _u = ai_insights.extract(c, "m", items(24), "Brooklands Hotel", "Weybridge", retry_calls=5, log=log)
check("nothing readable: no result, never more than the three first calls plus five repeats", ex is None and c.calls == 3 + 5, c.calls)
check("the log still records the attempt and the limit", log["retry_calls"] == 5 and log["unprocessed"] == 24 and "limit" in " ".join(log["reasons"]), log)

print("4. an answer left out of an otherwise good reply is asked for alone")


def skips(ids, n):
    if n == 1:
        return good([i for i in ids if i != "a2"])
    return good(ids)


c = Fake(skips)
ex, _u = ai_insights.extract(c, "m", items(8), "Brooklands Hotel", "Weybridge")
check("a2 is asked for on its own and recovered", ex and len(ex["answers"]) == 8 and c.seen[1] == ["a2"] and ex["failed_ids"] == [], c.seen)

print("5. the API failing")


def boom(ids, n):
    raise RuntimeError("credit balance too low")


raised = None
try:
    ai_insights.extract(Fake(boom), "m", items(8), "Brooklands Hotel", "Weybridge")
except RuntimeError as e:
    raised = e
check("a failure before anything worked is raised, so the caller can say 'no credit' (unchanged)", raised is not None)


def later(ids, n):
    if n == 3:
        raise RuntimeError("overloaded")
    return reply("not json") if (n == 2) else good(ids)


c = Fake(later)
ex, _u = ai_insights.extract(c, "m", items(16), "Brooklands Hotel", "Weybridge")
check("a failure after other calls worked is recorded, not raised", ex is not None and 8 <= len(ex["answers"]) <= 16 and ex["extraction"]["unprocessed"] == 16 - len(ex["answers"]), ex and ex["extraction"])

print("6. the hotel's own description is kept when the reply holding it is cut off")
direct = [{"id": "about", "kind": "direct", "text": "Tell me about it", "answer": "Brooklands Hotel is lovely.", "mentioned": True}] + items(3)


def about_cut(ids, n):
    full = {"answers": [answer_json(i) for i in ids if i != "about"] + [{"id": "about", "hotels": []}], "about": {"tone": "positive", "strengths": ["location"], "weaknesses": [], "claims": []}}
    if n == 1:
        t = json.dumps(full)
        return reply(t[: t.index('"about": {"tone"')], stop="max_tokens", out=6000)          # the description comes last and is the part lost
    return reply(json.dumps({"answers": [], "about": {"tone": "positive", "strengths": ["location"], "weaknesses": [], "claims": []}}))


c = Fake(about_cut)
ex, _u = ai_insights.extract(c, "m", direct, "Brooklands Hotel", "Weybridge")
check("the answers are kept and the description is asked for again and recovered", ex and len(ex["answers"]) >= 3 and ex["about"]["strengths"] == ["location"] and c.calls == 2, (ex and ex["about"], c.calls))

print("7. a report whose competitor extraction is largely missing is not presented as a reliable market view")
import report_model

ins = {"extracted_answers": {f"a{k}": [] for k in range(4)}, "unanalysed": 24}
rep = {"ai_sample": {"status": "ok", "items": items(28)}, "ai_insights": ins}
st = report_model.rankings_state(rep)
check("4 of 28 answers analysed: the rankings are not reliable, and it says how many", st["reliable"] is False and st["analysed"] == 4 and st["eligible"] == 28 and "4 of 28" in st["note"], st)
rep["ai_insights"]["extracted_answers"] = {f"a{k}": [] for k in range(26)}
check("26 of 28 analysed: reliable", report_model.rankings_state(rep)["reliable"] is True, report_model.rankings_state(rep))
check("a report with no analysis at all says there is none rather than reliable", report_model.rankings_state({"ai_sample": {"status": "ok", "items": items(5)}})["reliable"] is False)

print("8. the rival rows are withheld from a report that cannot support them, and kept aside")


def ranked(n_read):
    ib = {"rows": [{"name": "Brooks Guesthouse", "is_target": True, "mentions": 1, "of": 28, "coverage_pct": 4, "place": 2}, {"name": "The Gainsborough Bath Spa", "is_target": False, "mentions": 4, "of": 4, "coverage_pct": 100, "place": 1}]}
    ib["all"] = list(ib["rows"])
    lb = {"rows": [dict(r) for r in ib["rows"]], "questions": 4}
    return {"meta": {"hotel": "Brooks Guesthouse"}, "ai_sample": {"status": "ok", "items": items(28), "summary": {}},
            "ai_insights": {"extracted_answers": {f"a{k}": [] for k in range(n_read)}, "brand_ranking": ib, "leaderboard": lb, "niche": None,
                            "scoreboard": {"top_competitor": "The Gainsborough Bath Spa", "rank_in_table": 2, "table_size": 2, "place": 2, "coverage_pct": 4}}}


bad = report_model.apply(ranked(4))
ib = bad["ai_insights"]["brand_ranking"]
check("4 of 28 read: only the hotel's own row remains in every ranking", [r["name"] for r in ib["rows"]] == ["Brooks Guesthouse"] and [r["name"] for r in ib["all"]] == ["Brooks Guesthouse"]
      and [r["name"] for r in bad["ai_insights"]["leaderboard"]["rows"]] == ["Brooks Guesthouse"], ib)
check("...with the reason, the rows kept aside, and no top competitor claimed", "4 of 28" in ib["withheld"] and ib["withheld_rows"]["rows"][0]["name"] == "The Gainsborough Bath Spa"
      and bad["ai_insights"]["scoreboard"]["top_competitor"] is None and bad["ai_insights"]["rankings_withheld"], bad["ai_insights"])
check("calling it again changes nothing", [r["name"] for r in report_model.apply(bad)["ai_insights"]["brand_ranking"]["rows"]] == ["Brooks Guesthouse"])
good_ = report_model.apply(ranked(26))
check("26 of 28 read: the rankings stand untouched", len(good_["ai_insights"]["brand_ranking"]["rows"]) == 2 and "withheld" not in good_["ai_insights"]["brand_ranking"], good_["ai_insights"]["brand_ranking"])
old = ranked(0)
del old["ai_insights"]["extracted_answers"]
check("a check saved before the analysed answers were kept is not judged: its rankings stand", len(report_model.apply(old)["ai_insights"]["brand_ranking"]["rows"]) == 2)

print("\nFAILURES:", fails or "none")
sys.exit(1 if fails else 0)
