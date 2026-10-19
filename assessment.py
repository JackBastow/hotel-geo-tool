"""
What was actually assessed, partly assessed and not assessed in one audit, stated from the evidence the audit holds, never from what it set out to do.

A site that refused this tool's own reader and was read through a plain-text page reader gives words and nothing else: its structured data, headings, page titles and images could not be inspected, and a
check that depends on them was not made, whatever the methodology of a normal run would say. This module is the one place that decides that, so the summary, the methodology section and the Tools tab
cannot disagree with each other.

assess(rep) -> {"assessed": [...], "partial": [...], "not_assessed": [...]}, each item {"what": ..., "detail": ...}.
"""


def _item(what, detail=""):
    return {"what": what, "detail": detail}


def assess(rep):
    c = rep.get("consultant") or {}
    cov = c.get("coverage") or {}
    gq = rep.get("guest_questions") or {}
    site = rep.get("site") or {}
    web = rep.get("web_signals") or {}
    text_only = bool(cov.get("text_only") or gq.get("read_via"))
    read, attempted = cov.get("pages_read", 0), cov.get("pages_attempted", 0)
    limited = bool(cov.get("limited"))
    out = {"assessed": [], "partial": [], "not_assessed": []}

    def put(bucket, what, detail=""):
        out[bucket].append(_item(what, detail))

    # ---- the website's text
    if cov.get("unreadable"):
        put("not_assessed", "The website's content", f"only {read} of {attempted} page(s) could be read, too few to say what the site does or does not state")
    elif text_only:
        put("partial", "The website's text", f"{read} of {attempted} page(s) read through a plain-text page reader, because the site refused this tool's own reader. What the pages say was checked; how they are built was not")
    elif limited:
        put("partial", "The website's text", f"{read} of {attempted} pages read; anything reported as missing may be on a page that was not read")
    else:
        put("assessed", "The website's text", f"{read} of {attempted} pages read")

    # ---- the technical checks: these need the page's HTML
    if text_only:
        for what in ("Structured data (Hotel / LodgingBusiness markup)", "Page titles, headings and meta descriptions", "Image alt text", "Canonical addresses and noindex tags", "Crawler-readability of the pages"):
            put("not_assessed", what, "the pages were read as plain text, so their markup could not be inspected")
    elif cov.get("unreadable"):
        put("not_assessed", "Structured data, titles, headings and image text", "too few pages could be read")
    else:
        put("assessed" if not limited else "partial", "Structured data, page titles, headings and image alt text", f"inspected in the HTML of the {read} page(s) read" + ("" if not limited else "; pages not read were not inspected"))

    # ---- robots.txt, sitemap: fetched directly from the site, so they stand on their own
    robots = site.get("robots") or {}
    if robots.get("present"):
        put("assessed", "robots.txt and the AI-crawler policy", "read directly from the site")
    elif robots.get("status") in (401, 403) or robots.get("error"):
        put("not_assessed", "robots.txt and the AI-crawler policy", f"the file could not be read (HTTP {robots.get('status') or 'no answer'}), so nothing is claimed about it")
    else:
        put("assessed", "robots.txt", "none was published; the site sets no crawler rules")
    sm = site.get("sitemap") or {}
    if sm.get("present"):
        put("assessed", "The sitemap", f"{sm.get('url_count', 0)} address(es) read")
    elif robots.get("status") in (401, 403) or robots.get("error") or text_only:
        put("not_assessed", "The sitemap", "it could not be read from this tool, so nothing is claimed about it")
    else:
        put("assessed", "The sitemap", "none was found")

    # ---- Google's own test of the homepage works even when the site refuses this tool
    ps = web.get("pagespeed") or {}
    if ps.get("status") == "ok":
        put("assessed", "Mobile speed and accessibility of the homepage", "Google's PageSpeed test of the live page (one page, one test: scores vary between runs)")
    else:
        put("not_assessed", "Mobile speed and accessibility of the homepage", ps.get("reason") or "Google's PageSpeed test did not return a result")

    # ---- what the pages say
    nq = len(gq.get("questions", []))
    if nq:
        put("partial" if (limited or text_only) else "assessed", "Common guest questions (parking, breakfast, check-in, accessibility...)", f"{nq} questions checked against the text of the pages read")
    trv = c.get("traveller") or {}
    if trv.get("summary", {}).get("judged"):
        put("partial" if (limited or text_only) else "assessed", "Traveller requirements", f"{trv['summary']['judged']} requirement(s) judged across {len(trv.get('segments', []))} traveller segment(s); {trv['summary'].get('unknown', 0)} could not be judged")
    loc = c.get("location") or {}
    if loc.get("map_data"):
        put("assessed", "Location against open map data", "stations, airports and attractions checked against OpenStreetMap")
    else:
        put("partial", "Location", "places were taken from the website's own wording; open map data was not available to verify them")

    # ---- outside sources
    ext = c.get("external") or {}
    if ext.get("rows"):
        sm_ = ext["summary"]
        put("partial", "Outside sources", f"{sm_['verified']} verified against open data with several identifiers, {sm_['identified']} identified in search results but not read, {sm_['unclear']} uncertain, {sm_['not_verified']} not verified")
    bk = c.get("booking") or {}
    if bk.get("status") == "ok":
        put("assessed", "Booking readiness", "the homepage's booking link, its destination and the site's own links")
    else:
        put("not_assessed", "Booking readiness", bk.get("reason") or "the homepage's links could not be read, so the booking route was not checked")
    cp = c.get("competitors") or {}
    if cp.get("status") == "ok":
        put("assessed", "Comparable hotels", f"{len(cp.get('competitors', []))} compared on pages read for both hotels")
    else:
        put("not_assessed", "Comparable hotels", cp.get("reason") or "not compared")

    # ---- measurements that need access this tool does not have
    put("not_assessed", "Guest reviews on the travel platforms", "their terms prohibit automated collection; the hotel's own review export adds this")
    put("not_assessed", "Google Maps and Google Business Profile", "a Google Business Profile is free for the hotel to manage, but Google does not allow its data to be read automatically (the interfaces need the owner's permission or are paid); check it by hand")
    put("not_assessed", "Social media activity", "needs platform access; only the presence of official profiles can be noted")

    # ---- observed AI visibility
    ai = rep.get("ai_sample") or {}
    if ai.get("status") == "ok":
        put("partial", "Observed AI visibility", f"sampled on one assistant only ({ai.get('model', 'Claude')} with web search); ChatGPT, Gemini and Copilot were not tested")
    else:
        put("not_assessed", "Observed AI visibility", ai.get("reason") or "no AI assistant was asked about the hotel")
    return out
