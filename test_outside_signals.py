"""
Offline tests for what is measured when the hotel's own pages cannot be read: the town worked out from the name, Website & Technical from outside signals (with freshness in it),
Social from search, and the lookup's social profiles. No network.
Run: python test_outside_signals.py
"""
import warnings
from unittest import mock

warnings.filterwarnings("ignore")
import full_audit
import identity
import listing_lookup
import scoring
import urlscope

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. the town from the hotel's name")
check("'Hilton Zurich Airport' offers 'zurich' and not the brand or 'airport'", urlscope.place_candidates("Hilton Zurich Airport") == ["zurich"], urlscope.place_candidates("Hilton Zurich Airport"))
check("two-word towns are offered as a pair, after the single words", "new york" in urlscope.place_candidates("Hotel New York Midtown"))
check("a name with no place word offers nothing", urlscope.place_candidates("The Grand Hotel") == [])
calls = []


def fake_place(text):
    calls.append(text)
    return {"zurich": "Zürich"}.get(text, "")


with mock.patch.object(full_audit, "_place_from_text", fake_place), mock.patch("time.sleep", lambda s: None):
    city = full_audit.city_from_candidates(["airport", "zurich", "other"])
check("the first candidate the place search accepts is the town, and the search stops there", city == "Zürich" and calls == ["airport", "zurich"], (city, calls))
with mock.patch.object(full_audit, "_place_from_text", lambda t: ""), mock.patch("time.sleep", lambda s: None):
    check("when none is a town the answer is empty, never a guess", full_audit.city_from_candidates(["a", "b"]) == "")

print("2. Website & Technical from outside signals")
site = {"robots": {"present": True}, "sitemap": {"present": True, "url_count": 40}, "pages": [], "schema_types_found": [], "ai_crawlers_blocked": []}
web = {"pagespeed": {"scores": {"performance": 70, "accessibility": 90, "seo": 100, "best-practices": 90}}}
c = scoring.score_website_unread(site, None, web)
check("with PageSpeed and a sitemap it is assessed, flagged partial, and says what was not inspected", c["assessed"] and c.get("partial") and any("Not inspected" in e for e in c["evidence"]) and any("PageSpeed" in e for e in c["evidence"]))
c2 = scoring.score_website_unread({"robots": {"present": True}, "sitemap": {}, "ai_crawlers_blocked": []}, None, None)
check("with only robots.txt it is not assessed and says why", not c2["assessed"] and "too little" in c2["detail"])
c3 = scoring.score_website_unread({**site, "ai_crawlers_blocked": ["GPTBot"]}, None, web)
check("blocked AI crawlers lower it and raise a critical recommendation", c3["score"] < c["score"] and any(r["code"] == "crawler_block" for r in c3["recommendations"]))
check("freshness is part of Website & Technical and no longer a category of its own", "freshness" not in [k for k, *_r in scoring.CATEGORIES] and abs(sum(w for _k, _l, w, _d in scoring.CATEGORIES) - 100) < 0.01,
      sum(w for _k, _l, w, _d in scoring.CATEGORIES))
fresh_site = {**site, "pages": [{"url": "https://e.com/", "status": 200, "title": "t", "headings": ["h"], "images": [], "schema_types": []}], "sitemap": {"present": True, "url_count": 3, "lastmods": []}}
a = scoring.score_website(fresh_site, None, web)
b = scoring.score_website(fresh_site, None, None)
check("PageSpeed scores move the website score when they are present", a["score"] != b["score"] and any("PageSpeed" in e for e in a["evidence"]))

print("3. Social without the site's own links")
check("not assessed when no search for profiles ran", not scoring.score_social_outside(None, None)["assessed"])
s1 = scoring.score_social_outside(["Facebook", "Instagram", "YouTube"], None)
check("profiles found by search score as presence only, capped, and say activity was not measured", s1["assessed"] and s1["partial"] and s1["score"] <= 60 and any("NOT measured" in e for e in s1["evidence"]))
s0 = scoring.score_social_outside([], None)
check("a search that found none is a low, assessed score with a gentle check-by-hand note, not an accusation", s0["assessed"] and s0["score"] == 0 and any(r["code"] == "social_none_found" for r in s0["recommendations"]))

print("4. the lookup's social profiles")
pages = [{"url": "https://www.facebook.com/hiltonzurichairport", "title": "Hilton Zurich Airport | Facebook"}, {"url": "https://www.instagram.com/someotherhotel/", "title": "Some Other Hotel"},
         {"url": "https://www.linkedin.com/company/hilton", "title": "Hilton"}]
got = listing_lookup.social_from_pages(pages, "Hilton Zurich Airport", "Zurich")
check("only profiles that carry the hotel's name count, one per platform", [g["platform"] for g in got] == ["Facebook"], got)
check("a handle that is the name run together matches", identity.names_hotel("https://www.facebook.com/hiltonzurichairport", "", "", "Hilton Zurich Airport"))
check("a different hotel in the same brand does not", not identity.names_hotel("https://www.facebook.com/hiltonzurichcity", "Hilton Zurich City", "", "Hilton Zurich Airport"))

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
