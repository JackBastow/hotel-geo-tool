"""Offline tests for fixes.py and the recommendation codes. Run: python test_fixes.py"""
import json
import re

import fixes
import guest_questions as gq
import scoring

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


def page(url, text, title=""):
    return {"url": url, "ok": True, "reason": "", "title": title, "h1": [],
            "text": text + " Lorem ipsum dolor sit amet. " * 12, "footer_text": "",
            "tels": ["+44 1932 335700"], "mails": [], "links": []}


# a deliberately bad hotel, so that as many recommendation types as possible fire
pages = [page("https://h.com/", "Welcome."),
         page("https://h.com/faqs/", "Is parking available? Parking is available at £14 "
              "per night. Is the hotel dog-friendly? Unfortunately we can't accommodate "
              "dogs. Is Wi-Fi available? Yes, complimentary Wi-Fi.", "FAQs"),
         page("https://h.com/a/", ""), page("https://h.com/b/", "")]
qs = gq.evaluate(pages, True)
guest = {"questions": qs, "pages_ok": 4, "pages_attempted": 4, "pages_failed": [],
         "sitemap_total": 80, "evidence_sufficient": True, "fact_sheet": [],
         "conflicts": [], "own_facts_node": {"telephone": "+44 1932 335700",
                                            "checkinTime": "15:00", "checkoutTime": "11:00"}}
site = {"ai_crawlers_blocked": ["GPTBot", "ClaudeBot"], "lodging_node_found": False,
        "schema_types_found": ["Organization"], "sitemap": {"present": False},
        "robots": {"url": "https://h.com/robots.txt"}, "topics_covered": [],
        "topics_no_page_found": []}
entities = [{"source": "OpenStreetMap", "found": False, "note": "x"},
            {"source": "Wikidata", "found": False, "note": "y"}]
disc = {"profiles": [{"platform": "Instagram", "url": "https://instagram.com/h"},
                     {"platform": "Facebook", "url": "https://facebook.com/h"}],
        "declares_sameas": False}
loc = {"city": "Weybridge", "postcode": "KT13 0SL", "lat": 51.35, "lon": -0.47,
       "address": "The Hotel, Brooklands Dr, Weybridge KT13 0SL", "source": "map"}
tav = {"configured": True, "error": None, "ota_hits": [], "social_hits": [],
       "segments_detected": ["spa/wellness hotel"],
       "editorial_hits": [{"platform": "blog.example", "url": "https://blog.example/r",
                           "read": {"confirmed": True, "substance": "feature",
                                    "sentiment": "negative", "via": "rule", "excerpt": "x"}}]}

sc = scoring.build_scorecard(site, entities, [], loc, disc, tavily_result=tav,
                             guest_result=guest)
recs = scoring.all_recommendations(sc)
ctx = {"base": "https://h.com/", "hotel": "The Hotel", "location": loc, "guest": guest,
       "discovery": disc, "entities": entities, "site": site, "tavily": tav}

print("1. every recommendation is tagged and can be enriched")
check("there are recommendations to test", len(recs) >= 8, len(recs))
check("every recommendation has a code", all(r.get("code") for r in recs),
      [r["action"] for r in recs if not r.get("code")])
enriched = fixes.enrich(recs, ctx)
check("enrich keeps all of them", len(enriched) == len(recs))
check("every one has an owner, page, example key and effort",
      all(r["owner"] and r["page"] and "example" in r and r["effort"] for r in enriched),
      [(r["code"], r.get("owner"), r.get("page")) for r in enriched
       if not (r["owner"] and r["page"])])

print("2. the generated JSON-LD is real")
ex = fixes.hotel_jsonld(ctx)
body = re.search(r"<script[^>]*>(.*?)</script>", ex, re.S).group(1)
d = json.loads(body)
check("parses as JSON", d["@type"] == "Hotel")
check("uses the real name, phone, postcode and times",
      d["name"] == "The Hotel" and d["telephone"] == "+44 1932 335700"
      and d["address"]["postalCode"] == "KT13 0SL" and d["checkinTime"] == "15:00"
      and d["checkoutTime"] == "11:00", d)
check("street was split out of the map address", d["address"]["streetAddress"] == "Brooklands Dr",
      d["address"])
check("geo coordinates included", d["geo"]["latitude"] == 51.35)
check("sameAs lists the real profiles",
      set(d["sameAs"]) >= {"https://instagram.com/h", "https://facebook.com/h"}, d.get("sameAs"))
check("things it cannot know stay as visible [placeholders]",
      "[" in d["priceRange"] and "[" in d["address"]["addressCountry"])
check("states the pets answer only because the site said it", d.get("petsAllowed") is False)
check("states free Wi-Fi only because the site said it",
      any(a["name"] == "Free Wi-Fi" for a in d.get("amenityFeature", [])))
bare = fixes.hotel_jsonld({"base": "https://x.com/", "hotel": "", "location": {}, "guest": {}})
check("with no facts at all, everything is a placeholder, nothing invented",
      '"[Hotel name]"' in bare and "[Postcode]" in bare)

print("3. the examples point at the right place")
by = {r["code"]: r for r in enriched}
check("crawler fix names the blocked bots and the robots.txt page",
      "GPTBot" in by["crawler_block"]["example"]
      and by["crawler_block"]["page"].endswith("robots.txt"))
check("partial-answer fix uses that question's model answer and its own page",
      all(not r["code"].startswith("guest_partial") or
          r["page"].startswith("https://h.com/") for r in enriched))
check("negative coverage fix links the actual article",
      by["editorial_negative"]["page"] == "https://blog.example/r")
check("Wikidata fix warns it may not be possible",
      "may not be possible" in by["entity_missing:Wikidata"]["example"])
check("OpenStreetMap fix is something anyone can do",
      "Anyone" in by["entity_missing:OpenStreetMap"]["owner"])

print("4. choosing the top three")
top = fixes.top_fixes(enriched)
check("at most three", len(top) == 3, len(top))
check("the most severe comes first", top[0]["priority"] == "critical", top[0]["priority"])
ranks = [fixes.PRIORITY_RANK[r["priority"]] for r in top]
check("never a lower priority ahead of a higher one", ranks == sorted(ranks), ranks)
check("no duplicates", len({r["code"] for r in top}) == 3)
check("'go and check' items are not headline fixes when something actionable exists",
      all(r["code"].split(":")[0] not in fixes.CHECK_ONLY for r in top),
      [r["code"] for r in top])

mk = lambda code, pri, cat, w: {"code": code, "priority": pri, "category_key": cat,
                                "category_weight": w, "action": code}
pool = [mk("a1", "medium", "website", 12.5), mk("a2", "medium", "website", 12.5),
        mk("a3", "medium", "website", 12.5), mk("b1", "medium", "social", 7.5),
        mk("c1", "medium", "editorial", 15)]
picked = [r["code"] for r in fixes.top_fixes(pool)]
check("within a tier, different categories are preferred over three of one",
      len({r for r in picked}) == 3 and set(picked) == {"c1", "a1", "b1"}, picked)
pool = [mk("lowx", "low", "social", 7.5), mk("crit", "critical", "website", 12.5)]
check("a lower tier never jumps ahead of a higher one",
      [r["code"] for r in fixes.top_fixes(pool)] == ["crit", "lowx"])
check("fewer than three is fine", len(fixes.top_fixes([mk("only", "high", "x", 1)])) == 1)
only_checks = [mk("guest_not_found", "medium", "website", 12.5)]
check("check-only items are used if they are all there is",
      len(fixes.top_fixes(only_checks)) == 1)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
