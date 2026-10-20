"""
The consultant layer: turns what the crawl read into "what AI systems can
understand about this hotel, what they may struggle with, and the few things
most worth fixing".

Pure analysis - no network access. It reuses pages the audit already fetched
(guest_questions' crawl) plus the open-data and discovery results already
collected, so it adds no requests and little time.
"""

import advice
import hotel_class
import traveller_ready
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
                "Nothing below claims that information is missing, and this describes what this audit's reader received, not a fault in the hotel's website.")
    elif limited and pages_read >= attempted:
        note = (f"{pages_read} page{'' if pages_read == 1 else 's'} could be read, which is only part of a hotel's website. Anything reported as missing may be on a page that was not read, "
                "so findings that say something is missing are marked as inferences, not verified.")
    elif limited:
        note = (f"We could read {pages_read} of {attempted} pages. Anything reported as missing may be on a page we didn't read, so "
                "absence-based findings are marked lower-confidence. Re-running the audit can read a different set of pages.")
    else:
        note = ""
    return {"pages_read": pages_read, "pages_attempted": attempted, "ratio": round(ratio, 2), "unreadable": unreadable,
            "limited": limited, "failure_reasons": reasons, "note": note,
            "failed_pages": [{"url": r["url"], "reason": r.get("reason", ""), "status": r.get("status")} for r in failed[:8]]}


def analyse(*, own_pages, pages_meta, base, hotel, city, location, guest, site, entities, intel,
            osm_ctx, jsonld_example="", web=None, ai=None, reviews=None, text_only=False, ai_insights=None, listing_checks=None, reddit=None, booking=None, external=None, competitors=None, ai_gap=None):
    s = ic.Site(own_pages, base, hotel, city)
    s.osm_ctx = osm_ctx
    cov = crawl_coverage(len(s.pages), pages_meta)
    if text_only:
        cov["text_only"] = True
        cov["note"] = (cov["note"] + " " if cov["note"] else "") + TEXT_ONLY_NOTE
    if cov["unreadable"]:
        return _unreadable(s, cov, pages_meta, site, entities, intel, web, ai, reviews, ai_insights, listing_checks, reddit, booking, external)
    feats = ic.features(s)
    intents = ic.intents(s)
    understanding = ic.understanding(s, intents, feats, city)
    loc = ic.location(s, osm_ctx)
    # what kind of hotel this is decides which traveller segments, questions and opportunities are worth raising at all
    try:
        import ai_niche
        _prof = ai_niche.profile(hotel, city, entities, osm_ctx, own_pages, feats, intents)
    except Exception:  # noqa: BLE001
        _prof = None
    try:
        hclass = hotel_class.classify(s, feats, intents, osm_ctx, hotel, _prof)
    except Exception:  # noqa: BLE001
        hclass = {"classes": [], "keys": []}
    classes = hclass["keys"]
    questions = ic.questions(s, guest, intents, feats, loc["items"], classes=classes)
    opps = ic.opportunities(s, intents, feats, classes=classes)
    cons = ic.consistency(s, guest)
    cons_notes = ic.consistency_notes(s)
    try:
        travel = traveller_ready.run(s, feats, intents, cov, loc, classes=classes, class_info=hclass)
    except Exception as e:  # noqa: BLE001 - an extra; the keyword-based view still works
        travel = {"segments": [], "assessed": [], "skipped": [], "summary": {"judged": 0, "score": None}, "error": f"{type(e).__name__}: {e}"}
    hidden = ic.hidden_strengths(s, feats, pages_meta, classes=classes)
    if text_only:
        sd = {"items": [], "node_count": 0, "hotel_found": None, "unreadable": True,
              "caution": it.CAUTION + " The pages were read as plain text, so any markup they carry could not be inspected."}
    else:
        sd = it.structured_audit(s, location, guest, intents)
    machine = it.machine_readiness(s, pages_meta, site, entities, intel, sd, cons, questions, web)
    if text_only:
        # the site refused this tool's own reader, so what this tool fetched itself (the sitemap, robots.txt) cannot be taken as 'absent': only findings that do not depend on it remain
        machine = [f for f in machine if f["id"] not in it.HTML_ONLY_FINDINGS and f["id"] not in ("sitemap_missing", "robots_block_all", "ai_blocked")]
    profile = it.readiness_profile(s, guest, intents, loc, sd, machine, cons, intel, coverage=cov,
                                   map_failed=(osm_ctx or {}).get("failed_parts", []) if osm_ctx else ["all (no map data)"], traveller=travel, external=external)
    if text_only:
        for p in profile:
            if p["key"] in ("technical", "structured", "discoverability"):
                p.update(score=None, band="not assessed", assessed=False, drivers=["the pages were read as plain text, so this was not assessed"], evidence=None)
    suppressed = []
    recs = advice.build(questions=questions, location=loc, consistency=cons, hidden=hidden, structured=sd,
                        machine=machine, intel=intel, jsonld_example=jsonld_example, site=s, coverage=cov, ai=ai, reviews=reviews, text_only=text_only, ai_insights=ai_insights, ai_gap=ai_gap, listing_checks=listing_checks, reddit=reddit, traveller=travel, booking=booking, external=external, competitors=competitors, suppressed=suppressed)
    recs, dropped = advice.validate(recs, cov, s)
    if (site.get("meta") or {}).get("scope"):
        for r in recs:
            if r["source"] == "machine" and r["id"] in ("M-speed", "M-a11y", "M-cc_refused", "M-home_title", "M-home_meta", "M-meta_missing", "M-h1", "M-alt", "M-canonical_missing", "M-dup_titles", "M-canonical_other", "M-noindex", "M-js_empty"):
                r["kind"], r["priority"], r["impact"] = "opportunity", "low", "low"
                r["title"] = r["title"] + " (brand-run page)"
                r["finding"] += " This page belongs to the brand's website, so the hotel cannot change it itself: pass it to the brand's web team."
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
        "questions": questions, "location": loc, "consistency": cons, "consistency_notes": cons_notes, "traveller": travel, "hotel_class": hclass, "booking": booking, "external": external, "competitors": competitors, "dropped_recommendations": dropped, "could_not_confirm": suppressed, "hidden": hidden,
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


def _unreadable(s, cov, pages_meta, site_payload, entities, intel, web=None, ai=None, reviews=None, ai_insights=None, listing_checks=None, reddit=None, booking=None, external=None):
    """
    Too few pages were read to judge the content. Report that plainly, keep only findings that
    come from what actually happened (what the fetches returned, robots.txt, open-data matches),
    and make no claim that anything is missing from the site.
    """
    sd = {"items": [], "node_count": 0, "hotel_found": None, "unreadable": True, "caution": it.CAUTION}
    machine = [f for f in it.machine_readiness(s, pages_meta, site_payload, entities, intel, {"hotel_found": None, "items": []}, [], [], web)
               if f["bucket"] in ("access", "authority") or f["id"] in ("entity_ok", "entity_missing")]
    reasons = "; ".join(f"{n} x {r}" for r, n in cov["failure_reasons"].items()) or "no reason was reported"
    # Not a recommendation: this audit's own reader may be the cause (an address form the site does not answer, a firewall that turns away automated readers, slow hosting), so nothing is asked of the hotel.
    # It is stated as a limit of the audit, with what the reader received.
    what = (f"only {cov['pages_read']} page(s) could be found and read" if cov["pages_attempted"] <= cov["pages_read"]
            else (f"none of the {cov['pages_attempted']} page(s) tried could be read ({reasons})" if cov["pages_read"] == 0 else f"only {cov['pages_read']} of {cov['pages_attempted']} pages could be read ({reasons})"))
    why = (f"{what[0].upper() + what[1:]}. That describes what this audit's reader received; it can differ from what a visitor's browser gets, so it is not reported as a fault in the hotel's website and nothing is "
           "asked of the hotel. Open the pages in a browser to check; if automated readers are being turned away, a search or AI crawler may be too, which only the site's web team can confirm.")
    could = [{"topic": "The hotel's website pages", "why": why}]
    recs = advice._from_machine([f for f in machine if f["status"] == "issue"]) + advice._from_intel(intel) + advice._from_ai(ai) + advice._from_reviews(reviews) + advice._from_ai_insights(ai_insights) + advice._from_listing_checks(listing_checks) + advice._from_reddit(reddit) + advice._from_booking(booking) + advice._from_external(external)
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
            "top_actions": [r["id"] for r in top], "quick_wins": [], "could_not_confirm": could,
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
