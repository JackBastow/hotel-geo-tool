"""
Does the website score follow what was actually read, not just which reader was used?
The independent review said a Firecrawl-read site is scored as text-only whatever was retrieved. Checked against stored checks: where THIS tool's own reader was refused (THE NICI: HTTP 403 on the
homepage, its sitemap reported absent although robots.txt lists one), the conservative score is right, because the robots, sitemap and structured-data fields come from our own fetch and are not
real. What was wrong is narrower: when Firecrawl was chosen as the primary page reader but our own reader read the homepage fine, those fields ARE real, and the site was still scored as unread.
Run: python test_firecrawl_scoring.py
"""
import sys

import scoring

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))
    if not cond:
        fails.append(name)


def site(home_ok=True, status=200):
    return {"robots": {"present": True, "status": 200}, "sitemap": {"present": home_ok, "url_count": 40 if home_ok else 0}, "ai_crawlers_blocked": [],
            "pages": [{"url": "https://hotel.example/", "ok": home_ok, "status": status}], "schema_types_found": ["Hotel"] if home_ok else [],
            "lodging_node_found": home_ok, "lodging_properties_present": {"name": True, "address": True, "telephone": True} if home_ok else {}}


GUEST = {"pages_ok": 8, "pages_attempted": 8, "questions": [], "conflicts": [], "own_facts_node": {}}


def website(s, **g):
    sc = scoring.build_scorecard(s, [], [], {}, {"profiles": []}, guest_result={**GUEST, **g})
    return next(c for c in sc["categories"] if c["key"] == "website")


own = website(site())
check("baseline: our own reader read the site, so the full technical score is given", own["assessed"] and own["score"] is not None and not own.get("partial"), own)

prim_ok = website(site(), read_via="firecrawl_primary")
check("Firecrawl chosen as primary reader but our own reader read the homepage: scored like any read site", prim_ok["assessed"] and prim_ok["score"] == own["score"] and not prim_ok.get("partial"), (prim_ok["score"], own["score"]))

prim_blocked = website(site(home_ok=False, status=403), read_via="firecrawl_primary")
unread = scoring.score_website_unread(site(home_ok=False, status=403), {**GUEST, "read_via": "firecrawl_primary"})
check("our own reader refused with HTTP 403 (THE NICI): still scored as the partial, unread view", prim_blocked["score"] == unread["score"] and prim_blocked.get("partial") == unread.get("partial"), (prim_blocked["score"], unread["score"]))

fallback = website(site(), read_via="firecrawl", own_reader_refused=[{"url": "https://hotel.example/x", "reason": "HTTP 403"}])
check("a fallback read after our reader was refused on pages stays on the cautious view, even if the homepage came through",
      fallback["score"] == scoring.score_website_unread(site(), {**GUEST, "read_via": "firecrawl", "own_reader_refused": [1]})["score"], fallback["score"])

html_only = website(site(home_ok=False, status=403), read_via="firecrawl", html_read=True)
check("Firecrawl returning markup does not make our own refused fetch valid: the cautious view stays", html_only["score"] == unread["score"], (html_only["score"], unread["score"]))

check("scoring a site with no read_via is unchanged", website(site())["score"] == own["score"])

print("\nFAILURES:", fails or "none")
sys.exit(1 if fails else 0)
