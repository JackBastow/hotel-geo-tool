"""Offline tests for ai_check.py and compare.py. Run: python test_phase3.py"""
import copy
import datetime as dt

import ai_check
import compare

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. prompt pack")
ps = ai_check.build_prompts("Brooklands Hotel", "Weybridge, Surrey", ["wedding venue", "spa/wellness hotel"])
kinds = {p["kind"] for p in ps}
check("both kinds of prompt", kinds == {"accuracy", "discovery"})
check("accuracy prompts name the hotel",
      all("Brooklands Hotel" in p["prompt"] for p in ps if p["kind"] == "accuracy"))
check("discovery prompts NEVER name the hotel (that is the whole test)",
      all("Brooklands" not in p["prompt"] for p in ps if p["kind"] == "discovery"))
check("segment-specific prompts added", {"dis_wedding", "dis_spa"} <= {p["id"] for p in ps})
check("no pets prompt when no pet segment", "dis_pets" not in {p["id"] for p in ps})
check("unique ids", len({p["id"] for p in ps}) == len(ps))
no_city = ai_check.build_prompts("The Savoy", "")
check("no city -> no discovery prompts (they need a place), accuracy still given",
      {p["kind"] for p in no_city} == {"accuracy"})

print("2. recording is validated (the form AND uploaded files)")
good = {"assistant": "ChatGPT", "date": "2026-10-02", "prompt_id": "dis_best",
        "prompt": "x", "web_search": "yes", "mention": "mentioned", "facts": "not_stated",
        "sources": "see https://www.tripadvisor.co.uk/a and https://brooklandshotelsurrey.com/faq."}
r = ai_check.clean_record(good)
check("valid record accepted", r["assistant"] == "ChatGPT")
check("sources parsed to URLs, trailing punctuation stripped",
      r["sources"] == ["https://www.tripadvisor.co.uk/a", "https://brooklandshotelsurrey.com/faq"],
      r["sources"])
check("kind inferred from the prompt id", r["kind"] == "discovery")
for bad_field, bad_val in [("assistant", "Skynet"), ("mention", "loved"),
                           ("facts", "maybe"), ("web_search", "sometimes")]:
    try:
        ai_check.clean_record({**good, bad_field: bad_val})
        check(f"rejects invalid {bad_field}", False)
    except ValueError:
        check(f"rejects invalid {bad_field}", True)
check("bad date falls back to today, not an error",
      ai_check.clean_record({**good, "date": "not-a-date"})["date"] == dt.date.today().isoformat())
check("javascript: and other non-http sources are dropped",
      ai_check.clean_record({**good, "sources": "javascript:alert(1) ftp://x.com/a"})["sources"] == [])
check("overlong text is truncated",
      len(ai_check.clean_record({**good, "notes": "x" * 5000})["notes"]) == 1000)
recs, dropped = ai_check.clean_records([good, {"assistant": "nope"}, "garbage", None])
check("a mixed list keeps the valid and counts the rest", len(recs) == 1 and dropped == 3,
      (len(recs), dropped))

print("3. the summary counts, and refuses to over-claim")
def rec(kind, mention, facts="not_stated", assistant="ChatGPT", web="yes", src=""):
    return ai_check.clean_record({"assistant": assistant, "date": "2026-10-02", "kind": kind,
                                  "prompt_id": "dis_x" if kind == "discovery" else "acc_x",
                                  "web_search": web, "mention": mention, "facts": facts,
                                  "sources": src})
rs = [rec("discovery", "not_mentioned"), rec("discovery", "mentioned"),
      rec("discovery", "recommended", assistant="Gemini"),
      rec("accuracy", "mentioned", "some_wrong",
          src="https://www.booking.com/x https://brooklandshotelsurrey.com/p"),
      rec("accuracy", "mentioned", "all_correct", src="https://www.booking.com/y")]
s = ai_check.summarise(rs, "brooklandshotelsurrey.com")
check("discovery: 2 of 3 mentioned, 1 recommended",
      (s["discovery_mentioned"], s["n_discovery"], s["discovery_recommended"]) == (2, 3, 1), s)
check("accuracy: one wrong", len(s["accuracy_wrong"]) == 1)
check("booking.com cited in 2 answers, the hotel's own site in 1",
      dict(s["cited_domains"])["booking.com"] == 2 and s["own_cited"] == 1, s["cited_domains"])
check("per-assistant breakdown", s["by_assistant"]["Gemini"]["mentioned"] == 1)
check("5 samples is the minimum - no 'too few' warning",
      not any("too few" in c for c in s["caveats"]))
s1 = ai_check.summarise(rs[:2], "brooklandshotelsurrey.com")
check("2 samples -> says it is too few", any("too few" in c for c in s1["caveats"]))
mixed = [rec("discovery", "mentioned", web="yes"), rec("discovery", "mentioned", web="no")]
check("mixed web-search settings are called out",
      any("web search on and some off" in c for c in ai_check.summarise(mixed)["caveats"]))
check("empty list does not crash", ai_check.summarise([], "x.com")["n"] == 0)

print("4. comparing reports")
def report(overall, cov, cats, run_at="2026-09-01T10:00:00+00:00", site="brooklandshotelsurrey.com",
           guest=None, recs=None, facts=None):
    return {"meta": {"website": site, "run_at": run_at},
            "scorecard": {"overall": overall, "coverage_pct": cov, "categories": [
                {"key": k, "label": k.title(), "assessed": v is not None, "score": v}
                for k, v in cats.items()]},
            "guest_questions": {"questions": [{"id": i, "short": i.title(), "state": s}
                                              for i, s in (guest or {}).items()],
                                "fact_sheet": [{"fact": k, "value": v}
                                               for k, v in (facts or {}).items()]},
            "recommendations": [{"code": c, "action": a} for c, a in (recs or {}).items()]}

old = report(59, 30.0, {"website": 50, "freshness": 99, "entity": 75},
             guest={"parking": "partial", "pets": "not_found", "wifi": "answered",
                    "ev": "couldnt_check"},
             recs={"no_hotel_schema": "Add schema", "guest_partial:parking": "Parking: add price"},
             facts={"Check-in time": "14:00"})
new = report(66, 30.0, {"website": 62, "freshness": 98, "entity": 75},
             run_at="2026-10-02T10:00:00+00:00",
             guest={"parking": "answered", "pets": "not_found", "wifi": "partial", "ev": "not_found"},
             recs={"no_hotel_schema": "Add schema", "social_sameas": "Declare sameAs"},
             facts={"Check-in time": "15:00"})
c = compare.compare_reports(old, new)
check("same site recognised", c["same_site"])
check("overall like-for-like and +7", c["overall"]["like_for_like"] and c["overall"]["delta"] == 7)
rowd = {r["key"]: r for r in c["categories"]}
check("website improved by 12", rowd["website"]["status"] == "improved" and rowd["website"]["delta"] == 12)
check("a 1-point wobble is 'about the same', not 'declined'",
      rowd["freshness"]["status"] == "about the same")
gd = {g["id"]: g for g in c["guest"]}
check("parking improved", gd["parking"]["status"] == "improved")
check("wifi declined", gd["wifi"]["status"] == "declined")
check("unchanged stays 'same'", gd["pets"]["status"] == "same")
check("couldn't-check is never counted as a change",
      gd["ev"]["status"].startswith("can't compare"), gd["ev"])
check("resolved recommendation found", "Parking: add price" in c["recs"]["resolved"])
check("new recommendation found", "Declare sameAs" in c["recs"]["new"])
check("still-open recommendation found", "Add schema" in c["recs"]["still_open"])
check("changed fact reported", c["facts"] == [{"fact": "Check-in time", "old": "14:00", "new": "15:00"}],
      c["facts"])

print("5. comparability and safety")
new_cov = report(80, 60.0, {"website": 50, "freshness": 99, "entity": 75, "otas": 70})
c2 = compare.compare_reports(old, new_cov)
check("changed coverage -> overall is flagged NOT like-for-like", not c2["overall"]["like_for_like"])
check("...with a plain-English warning", any("like-for-like" in w for w in c2["warnings"]))
check("a newly assessed category is reported as such",
      {r["key"]: r for r in c2["categories"]}["otas"]["status"] == "newly assessed")
c3 = compare.compare_reports(old, report(60, 30.0, {"website": 50}, site="other-hotel.com"))
check("different website is warned about", not c3["same_site"] and
      any("different websites" in w for w in c3["warnings"]))
legacy = {"meta": {"website": "brooklandshotelsurrey.com", "run_at": "2026-08-01"},
          "scorecard": {"overall": 50, "coverage_pct": 30.0, "categories": [
              {"key": "website", "label": "Website", "assessed": True, "score": 40}]},
          "recommendations": [{"action": "Add pages for: pool"}]}
c4 = compare.compare_reports(legacy, new)
check("an older report with no guest data or codes still compares", c4["categories"] != [])
uncoded = report(63, 30.0, {"website": 50}, recs={None: "Add schema", None: "Declare sameAs"})
uncoded["recommendations"] = [{"action": "Add schema"}, {"action": "Declare sameAs"}]
coded = report(63, 30.0, {"website": 50},
               recs={"no_hotel_schema": "Add schema", "social_sameas": "Declare sameAs"})
c6 = compare.compare_reports(uncoded, coded)
check("an old report with no codes does not show every item as both fixed and new",
      c6["recs"]["resolved"] == [] and c6["recs"]["new"] == []
      and len(c6["recs"]["still_open"]) == 2, c6["recs"])
check("...so an identical re-run reports nothing improved or worse",
      c6["headline"] == {"improved": 0, "declined": 0}, c6["headline"])
for name, junk in [("a list", [1, 2]), ("no scorecard", {"meta": {}}),
                   ("scorecard wrong type", {"meta": {}, "scorecard": "x"}), ("None", None)]:
    try:
        compare.compare_reports(junk, new)
        check(f"rejects {name}", False)
    except ValueError as e:
        check(f"rejects {name} with a readable message", len(str(e)) > 20)
hostile = copy.deepcopy(old)
hostile["scorecard"]["overall"] = "<script>"
hostile["scorecard"]["categories"][0]["score"] = {"a": 1}
try:
    c5 = compare.compare_reports(hostile, new)
    check("wrong-typed numbers are ignored, not crashed on", c5["overall"].get("delta") is None)
except Exception as e:  # noqa: BLE001
    check("wrong-typed numbers are ignored, not crashed on", False, repr(e))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
