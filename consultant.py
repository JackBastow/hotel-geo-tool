"""
The consultant layer: turns what the crawl read into "what AI systems can
understand about this hotel, what they may struggle with, and the few things
most worth fixing".

Pure analysis - no network access. It reuses pages the audit already fetched
(guest_questions' crawl) plus the open-data and discovery results already
collected, so it adds no requests and little time.
"""

import advice
import ranking
import urlscope
import insight_content as ic
import insight_tech as it


TEXT_ONLY_NOTE = "These pages were read through Anthropic's page reader as plain text, because the site refused this tool's own reader. What the pages SAY was checked (guest questions, facts, location, consistency); markup, page titles, image text and other technical details could not be inspected and are not assessed."


def crawl_coverage(pages_read, pages_meta):
    """How much of the site we actually managed to read - every absence-based finding depends on it."""
    attempted = max(len(pages_meta or []), pages_read)
    failed = [r for r in (pages_meta or []) if not r.get("ok")]
    ratio = pages_read / attempted if attempted else 0.0
    reasons = {}
    for r in failed:
        key = (r.get("reason") or "unknown").split("(")[0].strip()[:60] or "unknown"
        reasons[key] = reasons.get(key, 0) + 1
    unreadable = pages_read < 3
    limited = unreadable or pages_read < 8 or ratio < 0.6
    if unreadable:
        found = ("only " + str(attempted) + " page" + ("" if attempted == 1 else "s") + " could be found to read" if attempted <= pages_read
                 else (f"none of the {attempted} page{'' if attempted == 1 else 's'} we tried could be read" if pages_read == 0
                       else f"we could only read {pages_read} of {attempted} pages"))
        note = (f"{found[0].upper() + found[1:]}, which is too few to say what the site does or doesn't contain. "
                "Nothing below claims that information is missing.")
    elif limited:
        note = (f"We could read {pages_read} of {attempted} pages. Anything reported as missing may be on a page we didn't read, so "
                "absence-based findings are marked lower-confidence. Re-running the audit can read a different set of pages.")
    else:
        note = ""
    return {"pages_read": pages_read, "pages_attempted": attempted, "ratio": round(ratio, 2), "unreadable": unreadable,
            "limited": limited, "failure_reasons": reasons, "note": note,
            "failed_pages": [{"url": r["url"], "reason": r.get("reason", ""), "status": r.get("status")} for r in failed[:8]]}


def analyse(*, own_pages, pages_meta, base, hotel, city, location, guest, site, entities, intel,
            osm_ctx, jsonld_example="", web=None, ai=None, reviews=None, text_only=False, ai_insights=None, listing_checks=None):
    s = ic.Site(own_pages, base, hotel, city)
    cov = crawl_coverage(len(s.pages), pages_meta)
    if text_only:
        cov["text_only"] = True
        cov["note"] = (cov["note"] + " " if cov["note"] else "") + TEXT_ONLY_NOTE
    if cov["unreadable"]:
        return _unreadable(s, cov, pages_meta, site, entities, intel, web, ai, reviews, ai_insights, listing_checks)
    feats = ic.features(s)
    intents = ic.intents(s)
    understanding = ic.understanding(s, intents, feats, city)
    loc = ic.location(s, osm_ctx)
    questions = ic.questions(s, guest, intents, feats, loc["items"])
    opps = ic.opportunities(s, intents, feats)
    cons = ic.consistency(s, guest)
    hidden = ic.hidden_strengths(s, feats, pages_meta)
    if text_only:
        sd = {"items": [], "node_count": 0, "hotel_found": None, "unreadable": True,
              "caution": it.CAUTION + " The pages were read as plain text, so any markup they carry could not be inspected."}
    else:
        sd = it.structured_audit(s, location, guest, intents)
    machine = it.machine_readiness(s, pages_meta, site, entities, intel, sd, cons, questions, web)
    if text_only:
        machine = [f for f in machine if f["id"] not in it.HTML_ONLY_FINDINGS]
    profile = it.readiness_profile(s, guest, intents, loc, sd, machine, cons, intel, coverage=cov,
                                   map_failed=(osm_ctx or {}).get("failed_parts", []) if osm_ctx else ["all (no map data)"])
    if text_only:
        for p in profile:
            if p["key"] in ("technical", "structured", "discoverability"):
                p.update(score=None, band="not assessed", assessed=False, drivers=["the pages were read as plain text, so this was not assessed"], evidence=None)
    recs = advice.build(questions=questions, location=loc, consistency=cons, hidden=hidden, structured=sd,
                        machine=machine, intel=intel, jsonld_example=jsonld_example, site=s, coverage=cov, ai=ai, reviews=reviews, text_only=text_only, ai_insights=ai_insights, listing_checks=listing_checks)
    top = advice.top_actions(recs)
    quick = advice.quick_wins(recs, exclude_ids={r["id"] for r in top})
    plan = ranking.plan_30_60_90(recs, {r["id"] for r in top})
    working = what_works(s, guest, intents, feats, loc, sd, machine, cons, intel)
    if cov["limited"]:
        understanding["note"] = cov["note"] + " " + understanding["note"]
    return {
        "version": 1, "pages_read": len(s.pages), "coverage": cov, "understanding": understanding,
        "intents": [{k: v for k, v in r.items()} for r in intents],
        "features": [{"key": f["key"], "label": f["label"], "level": f["level"], "pages": f["pages"]} for f in feats],
        "questions": questions, "location": loc, "consistency": cons, "hidden": hidden,
        "structured": {k: v for k, v in sd.items() if k != "best"}, "machine": machine, "profile": profile,
        "recommendations": recs, "top_actions": [r["id"] for r in top], "quick_wins": [r["id"] for r in quick],
        "required_fixes": [r["id"] for r in recs if r["kind"] == "fix"],
        "opportunity_recs": [r["id"] for r in recs if r["kind"] == "opportunity"],
        "opportunities": opps, "plan": plan, "working": working,
    }


def add_recommendations(c, new, source):
    """
    Add recommendations that arrive after the audit (from an uploaded review pack) to a finished consultant block: rank them with everything else and rebuild the top actions,
    quick wins, fix/opportunity lists and the plan. Earlier recommendations from the same `source` are replaced, so uploading again does not duplicate.
    """
    if not c or "recommendations" not in c:
        return c
    keep = [r for r in c["recommendations"] if r.get("source") != source]
    ranking.annotate(new, c.get("questions") or [])
    for r in new:
        r["ref"], r["expected_outcome"] = r["id"], ranking.expected_outcome(r)
        r["score"] = r["rank"]
    recs = sorted(keep + new, key=lambda r: -r["rank"])
    top = advice.top_actions(recs)
    quick = advice.quick_wins(recs, exclude_ids={r["id"] for r in top})
    c.update(recommendations=recs, top_actions=[r["id"] for r in top], quick_wins=[r["id"] for r in quick], required_fixes=[r["id"] for r in recs if r["kind"] == "fix"],
             opportunity_recs=[r["id"] for r in recs if r["kind"] == "opportunity"], plan=ranking.plan_30_60_90(recs, {r["id"] for r in top}))
    return c


def _unreadable(s, cov, pages_meta, site_payload, entities, intel, web=None, ai=None, reviews=None, ai_insights=None, listing_checks=None):
    """
    Too few pages were read to judge the content. Report that plainly, keep only findings that
    come from what actually happened (what the fetches returned, robots.txt, open-data matches),
    and make no claim that anything is missing from the site.
    """
    sd = {"items": [], "node_count": 0, "hotel_found": None, "unreadable": True, "caution": it.CAUTION}
    machine = [f for f in it.machine_readiness(s, pages_meta, site_payload, entities, intel, {"hotel_found": None, "items": []}, [], [], web)
               if f["bucket"] in ("access", "authority") or f["id"] in ("entity_ok", "entity_missing")]
    reasons = "; ".join(f"{n} x {r}" for r, n in cov["failure_reasons"].items()) or "no reason was reported"
    evd = [{"url": p["url"], "snippet": p["reason"] or f"HTTP {p['status']}"} for p in cov["failed_pages"][:3]]
    rec = advice._rec(
        "READ1", "access", "Check that the website can be read by automated visitors",
        (f"Only {cov['pages_read']} page(s) of the site could be found and read." if cov["pages_attempted"] <= cov["pages_read"]
         else (f"None of the {cov['pages_attempted']} page(s) we tried could be read ({reasons})." if cov["pages_read"] == 0
               else f"We could only read {cov['pages_read']} of {cov['pages_attempted']} pages ({reasons}).")),
        "If our crawler cannot read the site, search engines and AI crawlers may not be able to either - or the site may be refusing automated "
        "visitors on purpose (some firewalls do), in which case the information on it is less reliably discoverable by those systems.",
        evd or [{"url": "", "snippet": "Too few pages could be read to say what the site contains."}],
        ("Ask the brand's web team" if urlscope.normalise(s.base)[1] else "Ask your web supplier") + " whether a firewall, bot-protection rule or very slow hosting is blocking automated visitors, and check that the "
        "main pages show their text without JavaScript. If the blocking is deliberate, this report cannot assess what is inside the site.",
        "high", "medium", page={"url": s.base, "label": "the website"},
        technical="Crawl returned timeouts/refusals. Could be our fetch (rate limits, user agent) as well as the site; "
                  "verify by loading the pages with a plain HTTP client.", confidence=advice.INFER, team="web", source="machine",
        success="A later audit reads most of the site's pages.")
    recs = [rec] + advice._from_machine([f for f in machine if f["status"] == "issue"]) + advice._from_intel(intel) + advice._from_ai(ai) + advice._from_reviews(reviews) + advice._from_ai_insights(ai_insights) + advice._from_listing_checks(listing_checks)
    recs = advice.drop_duplicate_entity(recs)
    ranking.annotate(recs, [])
    for r in recs:
        r["ref"] = r["id"]
        r["expected_outcome"] = ranking.expected_outcome(r)
        r["score"] = r["rank"]
    recs.sort(key=lambda r: -r["rank"])
    top = advice.top_actions(recs)
    profile = [{"key": k, "label": l, "score": None, "band": "not assessed", "drivers": ["the site could not be read well enough"],
                "note": "", "assessed": False} for k, l in (
        ("discoverability", "Discoverability"), ("entity", "Entity clarity"), ("content", "Content completeness"),
        ("location", "Location relevance"), ("intent", "Traveller-intent coverage"), ("technical", "Technical accessibility"),
        ("structured", "Structured data"), ("authority", "External authority / evidence"))]
    return {"version": 1, "pages_read": cov["pages_read"], "coverage": cov,
            "understanding": {"summary": "", "descriptor_found": None, "strong_signals": [], "weak_signals": [], "pages_read": cov["pages_read"],
                              "note": cov["note"]},
            "intents": [], "features": [], "questions": [], "location": {"items": [], "map_data": False, "clear": 0, "note": cov["note"]},
            "consistency": [], "hidden": [], "structured": sd, "machine": machine, "profile": profile, "recommendations": recs,
            "top_actions": [r["id"] for r in top], "quick_wins": [],
            "required_fixes": [r["id"] for r in recs if r["kind"] == "fix"],
            "opportunity_recs": [r["id"] for r in recs if r["kind"] == "opportunity"],
            "opportunities": [], "plan": ranking.plan_30_60_90(recs, {r["id"] for r in top}),
            "working": outside_points(entities, intel), "working_is_outside": True}


def outside_points(entities, intel):
    """What the world outside the hotel's own website says about it - the whole result when the website could not be read."""
    out = []
    for e in entities or []:
        if e.get("source") == "OpenStreetMap" and e.get("found") and e.get("match_confident") is True:
            f = e.get("facts") or {}
            bits = [x for x in (f.get("address"), ("tel " + f["telephone"]) if f.get("telephone") else "") if x]
            out.append({"point": "Listed in OpenStreetMap" + (" at " + "; ".join(bits) if bits else "") +
                                 (f", pointing to {f['url']}" if f.get("url") else "") + ".", "url": e.get("url", "")})
        if e.get("source") == "Wikidata" and e.get("found") and e.get("match_confident") is True:
            out.append({"point": "Has a Wikidata entry (feeds knowledge panels and AI training data).", "url": e.get("url", "")})
    if intel and "error" not in intel:
        found = [r["platform"] for r in (intel.get("identity") or {}).get("footprint", [])
                 if r.get("discovered") and r.get("type") != "map / open data"]      # maps are reported separately above
        if found:
            out.append({"point": f"Listings found on {len(found)} platforms: " + ", ".join(found[:8]) + ". (Found through a search index, not read from the platforms themselves.)", "url": ""})
        md = (intel.get("media") or {}).get("summary") or {}
        if md.get("independent_publishers"):
            out.append({"point": f"{md['independent_publishers']} independent publisher(s) cover the hotel"
                                 f" ({md.get('recent_independent', 0)} in the last 12 months).", "url": ""})
    return out


def what_works(site, guest, intents, feats, loc, sd, machine, cons, intel):
    """What the hotel is already doing well - so the report isn't only problems."""
    out = []
    qs = (guest or {}).get("questions", [])
    ans = [q for q in qs if q["state"] == "answered"]
    if ans:
        out.append({"point": f"{len(ans)} of the {len(qs)} common guest questions are clearly answered "
                             f"({', '.join(q['short'].lower() for q in ans[:5])}).",
                    "url": ans[0].get("source_url", "")})
    strong = [r for r in intents if r["level"] == "strong"]
    if strong:
        out.append({"point": "Strongly signalled traveller types: " + ", ".join(r["label"].lower() for r in strong[:5]) + ".",
                    "url": (strong[0]["evidence"][0]["url"] if strong[0]["evidence"] else "")})
    stated = [i for i in loc["items"] if i["state"] == "stated"]
    if stated:
        out.append({"point": "Location is tied to real places with a distance or time: " +
                             ", ".join((i["place"] or i["label"]) for i in stated[:4]) + ".", "url": stated[0]["evidence"][0]["url"]})
    for f in machine:
        if f["status"] == "ok" and f["id"] in ("robots_ok", "sitemap_ok", "home_title_ok", "home_meta_ok", "entity_ok", "schema_ok", "independent_ok", "alt_ok"):
            detail = (f["detail"] or "").strip()
            if f["id"] in ("robots_ok", "schema_ok") or detail.lower().startswith(f["title"].lower()[:20]):
                detail = ""           # the title already says it
            detail = detail if len(detail) <= 90 else detail[:87].rsplit(" ", 1)[0] + "..."
            out.append({"point": f["title"].rstrip(".") + (f": {detail.rstrip('.')}" if detail else "") + ".", "url": ""})
    if sd.get("hotel_found") and not any(i["status"] == "incorrect" for i in sd["items"]):
        out.append({"point": "The structured data that exists matches the page text.", "url": ""})
    if not cons:
        out.append({"point": "No contradictions were found between the hotel's own pages (times, phone, address, name, hours).", "url": ""})
    return out
