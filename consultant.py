"""
The consultant layer: turns what the crawl read into "what AI systems can
understand about this hotel, what they may struggle with, and the few things
most worth fixing".

Pure analysis - no network access. It reuses pages the audit already fetched
(guest_questions' crawl) plus the open-data and discovery results already
collected, so it adds no requests and little time.
"""

import re

import evidence
import advice
import hotel_class
import traveller_ready
import ranking
import urlscope
import insight_content as ic
import insight_tech as it


TEXT_ONLY_NOTE = "These pages were read through a fallback page reader (Firecrawl or Anthropic's) as plain text, because the site refused this tool's own reader. What the pages SAY was checked (guest questions, facts, location, consistency); markup, page titles, image text and other technical details could not be inspected and are not assessed."
FC_HTML_NOTE = "The site refused this tool's own reader, so its pages were read through Firecrawl, which returned each page's HTML. Titles, headings, markup and structured data were checked from that. The sitemap, robots.txt, error codes, speed and script-built content depend on how this tool's own reader is treated, so they are not judged."


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


_LODGING_TITLE = re.compile(r"\b(?:hotel|hôtel|hotell|inn|lodge|resort|b\s?&\s?b|bed and breakfast|guest ?house|hostel|motel|suites|manor|country house|apartments?|aparthotel|retreat|spa|castle|hall|rooms)\b", re.I)
_LODGING_TEXT = re.compile(r"\b(?:our (?:rooms|suites|bedrooms)|book (?:your|a) (?:stay|room)|check-(?:in|out)\b|check[\s]?(?:in|out)(?=\s*(?:times?\b|is\b|from\b|by\b|until\b|before\b|after\b|:|\d))|per night|bedrooms?|en[\s-]?suite|accommodation|overnight stay|rum|övernattning|chambres?|zimmer|habitaciones)\b", re.I)


def site_identity(s, hotel):
    """
    Does this website look like the hotel's own? -> a top recommendation saying it may not be, or None. A site whose homepage title names no kind of place to stay and whose pages say nothing
    about rooms, stays or check-in is probably not the hotel's (an area guide, a beach, a restaurant): everything else in the report would describe the wrong business.
    """
    if not s.content_pages:
        return None
    home = s.home or s.content_pages[0]
    title = " ".join([home.get("title") or ""] + list(home.get("h1") or []))
    words = [w for w in evidence.fold(hotel or "").split() if len(w) > 2 and w not in ("the", "and", "hotel", "spa", "resort")]
    name_in_title = bool(words) and all(w in evidence.fold(title) for w in words)
    lodging_title = bool(_LODGING_TITLE.search(title))
    lodging_hits = sum(len(_LODGING_TEXT.findall(p.get("text") or "")) for p in s.content_pages)
    if lodging_title or lodging_hits >= 4 or (name_in_title and lodging_hits >= 2):
        return None
    return {"id": "ID-site-check", "title": "Check this is the hotel's own website", "source": "identity", "tag": "site-check", "category": "understanding", "priority": "critical", "effort": "low",
            "team": "web", "kind": "fix", "track": "accuracy", "confidence_label": "Worth checking", "confidence": "Experimental", "impact": "high",
            "value": 95.0, "rank": 95.0, "score": 95.0, "question_ids": [], "topics": [],       # set by hand: it is added after the ranking, and must lead the report
            "finding": f"The website read for {hotel} may not be the hotel's own: its homepage title (“{(home.get('title') or '')[:90]}”) names no hotel or place to stay, and the pages read say almost nothing about rooms, stays or check-in.",
            "why": "If this is another business's website (an area guide, a beach, a restaurant), every finding in this report describes that business, not the hotel.",
            "action": "Check the website address used for this hotel and run the check again with the hotel's own site.",
            "steps": [{"title": "Open the address used for this check and confirm it is the hotel's own website"}, {"title": "If it is not, correct the website address (in the hotel's settings or when adding the hotel) and run the check again"}],
            "evidence": [{"url": home.get("url", ""), "snippet": (home.get("title") or "")[:160]}]}


BRAND_SITE_WIDE = ("M-speed", "M-a11y", "M-cc_refused", "M-home_title", "M-home_meta", "M-meta_missing", "M-h1", "M-alt", "M-canonical_missing", "M-dup_titles", "M-canonical_other", "M-noindex",
                   "M-js_empty", "M-sitemap_missing", "M-robots_missing", "M-robots_block_all", "M-ai_blocked", "M-llms_missing", "M-cc_policy", "M-cc_none", "M-http_errors", "M-slow_pages")
BRAND_OWNER = "Brand digital team"
BRAND_NOTE = (" On a brand-run website the hotel usually cannot edit the pages itself: send this to the brand's digital team with the evidence below, "
              "or use the property content tool the brand provides, where there is one.")


def brand_route(recs):
    """
    A hotel's section of a brand's website (Marriott, Hilton...): say who makes each change (Paris Marriott review). Site-wide settings (sitemap, robots.txt, page speed, titles...) belong to the whole
    brand website: low priority, labelled 'brand-run page'. Changes to the hotel's own pages are kept, routed to the brand's digital team. Changes outside the website stay with the hotel.
    """
    for r in recs or []:
        if r.get("source") == "machine" and r.get("id") in BRAND_SITE_WIDE:
            r["kind"], r["priority"], r["impact"] = "opportunity", "low", "low"
            if "(brand-run page)" not in (r.get("title") or ""):
                r["title"] = (r.get("title") or "") + " (brand-run page)"
            if "brand's web team" not in (r.get("finding") or ""):
                r["finding"] = (r.get("finding") or "") + " This setting belongs to the brand's whole website, so the hotel cannot change it itself: pass it to the brand's web team."
            r["owner"], r["brand_run"] = BRAND_OWNER, True
        elif r.get("team") == "web" or r.get("source") in ("questions", "hidden", "structured"):
            r["owner"], r["brand_run"] = BRAND_OWNER, True
            if BRAND_NOTE.strip() not in (r.get("action") or ""):
                r["action"] = (r.get("action") or "").rstrip() + BRAND_NOTE
    return recs


def analyse(*, own_pages, pages_meta, base, hotel, city, location, guest, site, entities, intel,
            osm_ctx, jsonld_example="", web=None, ai=None, reviews=None, text_only=False, ai_insights=None, listing_checks=None, reddit=None, booking=None, external=None, competitors=None, ai_gap=None, citations=None, forums=None, fc_html=False):
    s = ic.Site(own_pages, base, hotel, city)
    s.osm_ctx = osm_ctx
    cov = crawl_coverage(len(s.pages), pages_meta)
    if fc_html:
        cov["read_via_html"] = True
        cov["note"] = (cov["note"] + " " if cov["note"] else "") + FC_HTML_NOTE
    if text_only:
        cov["text_only"] = True
        cov["note"] = (cov["note"] + " " if cov["note"] else "") + TEXT_ONLY_NOTE
    if cov["unreadable"]:
        return _unreadable(s, cov, pages_meta, site, entities, intel, web, ai, reviews, ai_insights, listing_checks, reddit, booking, external)
    site_check_warn = site_identity(s, hotel)            # is this website the hotel's own at all? (an area guide or a beach's site audited as a hotel's gives nonsense)
    if site_check_warn:
        cov["note"] = (cov.get("note", "") + " " + site_check_warn["finding"]).strip()
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
    # a site in another language: the checks that look for English wording ('check-in', 'breakfast', 'connecting rooms') cannot say something is missing, so they are not assessed rather than wrong
    import langid
    site_lang, _lc = langid.detect(" ".join((p.get("text") or "")[:3000] for p in s.content_pages[:8]), min_words=60)
    non_english = bool(site_lang and site_lang != "en")
    ai_read = ((guest or {}).get("ai_extract") or {}).get("status") == "ok"          # the AI reading of the pages ran: it reads any language
    if non_english:
        lang_name = langid.name(site_lang)
        if not ai_read:
            questions = [q for q in questions if q.get("state") in ("answered", "stated", "complete")]
        travel = {"segments": [], "assessed": [], "skipped": [{"key": "all", "label": "Traveller requirements", "why": f"the site is in {lang_name}; these checks read English wording, so they were not assessed"}],
                  "summary": traveller_ready.summarise([])}
        cov["note"] = (cov.get("note", "") + (f" The site is written in {lang_name}. Guest questions were read by AI in {lang_name}: what it found is quoted; what neither it nor the "
                       "word checks found is listed as worth checking, not as missing. Traveller needs and facility details read English, so they were not assessed."
                       if ai_read else f" The site is written in {lang_name}. The checks that look for specific wording (guest questions, traveller needs, facility details) read English, so "
                       "they were not assessed here rather than reported as missing.")).strip()
    hidden = ic.hidden_strengths(s, feats, pages_meta, classes=classes)
    if non_english:
        hidden = [h for h in hidden if h.get("kind") not in ("once",)]
    if (cov.get("ratio") or 0) < 0.6:
        hidden = [h for h in hidden if h.get("kind") not in ("poorly_linked", "once", "deep")]      # 'no page links to it' / 'mentioned only once' cannot be said after reading less than most of the site
    if text_only or fc_html:
        sd = {"items": [], "node_count": 0, "hotel_found": None, "unreadable": True,
              "caution": it.CAUTION + (" The pages were read as plain text, so any markup they carry could not be inspected." if text_only else
                                       " The site refused this tool's own reader; the copy that came through the fallback reader may not carry the page's scripts, where structured data lives, so it was not judged either way.")}
    else:
        sd = it.structured_audit(s, location, guest, intents)
    machine = it.machine_readiness(s, pages_meta, site, entities, intel, sd, cons, questions, web)
    if text_only:
        # the site refused this tool's own reader, so what this tool fetched itself (the sitemap, robots.txt) cannot be taken as 'absent': only findings that do not depend on it remain
        machine = [f for f in machine if f["id"] not in it.HTML_ONLY_FINDINGS and f["id"] not in ("sitemap_missing", "robots_block_all", "ai_blocked")]
    if fc_html:
        # the site refused this tool's own reader; the page markup came through the fallback reader, but what depends on how OUR reader was treated, or on pages that run scripts, is not judged
        machine = [f for f in machine if f["id"] not in ("sitemap_missing", "robots_block_all", "ai_blocked", "js_booking", "js_empty", "http_errors", "slow_pages", "refused")]
    profile = it.readiness_profile(s, guest, intents, loc, sd, machine, cons, intel, coverage=cov,
                                   map_failed=(osm_ctx or {}).get("failed_parts", []) if osm_ctx else ["all (no map data)"], traveller=travel, external=external)
    if fc_html and not text_only:
        for p in profile:
            if p["key"] == "structured":
                p.update(score=None, band="not assessed", assessed=False, drivers=["the site refused this tool's own reader, so its structured data could not be inspected reliably"], evidence=None)
    if text_only:
        for p in profile:
            if p["key"] in ("technical", "structured", "discoverability"):
                p.update(score=None, band="not assessed", assessed=False, drivers=["the pages were read as plain text, so this was not assessed"], evidence=None)
    suppressed = []
    try:
        import facility_depth
        facility = [] if non_english else facility_depth.analyse(s)          # facility details are found by English wording
    except Exception:  # noqa: BLE001 - an extra check; the rest of the analysis stands
        facility = []
    try:
        import differentiation
        import rival_analysis
        import source_actions
        pseudo = {"meta": {"base": base, "hotel": hotel, "city": city}, "consultant": {"features": feats, "intents": intents, "facility_depth": facility, "traveller": travel if isinstance(travel, dict) else {}, "hotel_class": hclass,
                                                                                    "opportunities": opps}, "ai_gap": ai_gap, "ai_insights": ai_insights}
        diff = differentiation.build(pseudo)
        rivals_view = rival_analysis.build(pseudo)
        src_actions = source_actions.build(pseudo)
    except Exception:  # noqa: BLE001 - an extra layer: the rest of the analysis stands
        diff, rivals_view, src_actions = None, [], []
    recs = advice.build(differentiation=diff, source_actions=src_actions, facility=facility, questions=questions, location=loc, consistency=cons, hidden=hidden, structured=sd,
                        machine=machine, intel=intel, jsonld_example=jsonld_example, site=s, coverage=cov, ai=ai, reviews=reviews, text_only=text_only, ai_insights=ai_insights, ai_gap=ai_gap, citations=citations, forums=forums, listing_checks=listing_checks, reddit=reddit, traveller=travel, booking=booking, external=external, competitors=competitors, suppressed=suppressed)
    recs, dropped = advice.validate(recs, cov, s)
    if non_english and ai_read:
        for r in recs:
            if r.get("source") == "questions":
                r["confidence"], r["confidence_label"] = advice.EXPER, "Worth checking"
                if "AI reading" not in (r.get("finding") or ""):
                    r["finding"] = (r.get("finding") or "") + f" The site is in {lang_name}: neither the AI reading of its pages nor the word checks found this, so check the pages before acting."
                if r.get("priority") in ("critical", "high"):
                    r["priority"] = "medium"
    if site_check_warn:
        recs.insert(0, site_check_warn)
    if (site.get("meta") or {}).get("scope"):
        brand_route(recs)
    try:
        import report_check
        reconciled = report_check.reconcile(recs, facility, travel if isinstance(travel, dict) else None, profile, external)
    except Exception:  # noqa: BLE001 - a check on the checks must never stop the report
        reconciled = []
    RATE_NOTE = (" Rates vary by date, package, membership and booking channel, so state what is included in every rate and point guests to the terms shown when they book for anything that varies, "
                 "rather than listing everything for every rate.")
    for r in recs:
        if "rate_inclusions" in (r.get("question_ids") or []) and RATE_NOTE.strip() not in r.get("action", ""):
            r["action"] = r["action"].rstrip() + RATE_NOTE
        r["track"] = advice.track_of(r)
    ranking.fill_missing(recs)                          # warnings added after the ranking (wrong website, former name) get the fields every later step sorts by
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
        "opportunities": opps, "plan": plan, "working": working, "facility_depth": facility, "reconciled": reconciled, "differentiation": diff, "rival_analysis": rivals_view, "source_actions": src_actions,
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
               if (f["bucket"] in ("access", "authority") or f["id"] in ("entity_ok", "entity_missing")) and f["id"] not in ("sitemap_missing", "robots_block_all", "ai_blocked", "refused", "http_errors", "slow_pages")]
    # (a site our reader could not read says nothing about its sitemap or how it treats crawlers: those are never claimed from an unreadable site)
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
