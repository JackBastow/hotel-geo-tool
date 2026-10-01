#!/usr/bin/env python3
"""
One-button audit: everything that can be checked without an API key.

The point of this module is that the user types a website and presses one
button. Everything else - finding the hotel's name, finding its profiles on
other sites, looking it up in the open datasets, cross-checking the facts -
happens without them going away and gathering URLs by hand.

What it chains together - ALL of it, in this one function, so there is one
report rather than several tabs the user has to visit separately:

  1. site_check.run_site_check   - robots.txt, AI crawlers, sitemap, JSON-LD,
                                   Hotel schema completeness, topic coverage
  2. discover_profiles           - reads the hotel's OWN pages for links out to
                                   its profiles elsewhere (JSON-LD sameAs plus
                                   outbound links), so nobody has to paste them
  3. external_check entities     - OpenStreetMap and Wikidata presence
  4. fact consistency            - own site vs every readable source
  5. tavily_check (optional)     - OTA presence + editorial mentions, via a
                                   search index rather than the OTA sites
                                   themselves (see tavily_check.py for why)
  6. places_check (optional)     - official Google rating, review count,
                                   review snippets
  7. amadeus_check (optional)    - review sentiment by category
  8. AI visibility (opt-in)      - a small live Gemini grounded-search sample,
                                   OFF by default because it is the one thing
                                   here that spends real money
  9. scoring.build_scorecard     - the eight-category weighted model; every
                                   category not backed by a configured key
                                   reports "not assessed", never a wrong number

Everything through step 4 needs no key at all. Steps 5-8 are each entirely
optional and independently gate on whether their key is configured - the
audit runs and reports fine with none of them, all of them, or any mix.

Honest limits, carried through to the output rather than hidden:
  - TripAdvisor's and Booking.com's Terms of Use explicitly prohibit
    automated collection ("except as expressly permitted... in writing" -
    TripAdvisor's, verified 2026-09). This tool does not attempt to get
    around that on any hosting, with any client, however capable - so those
    sites are never read directly, only through Tavily's search index or
    official aggregators like Google Places and Amadeus.
  - Hotels do not link to OTAs from their own sites, so those listings cannot
    be auto-discovered from the site either. Social profiles and restaurant
    booking pages can be, and are.
  - A page existing is not a page answering the question. Topic coverage is a
    candidate list for a human to read, not a verdict.

Usage:
  python full_audit.py --website brooklandshotelsurrey.com \
                       --hotel "Brooklands Hotel" --city "Weybridge, Surrey" \
                       --out audit.json
"""

import argparse
import datetime as dt
import json
import re
import os
import sys
import urllib.parse

import amadeus_check
import audit
import external_check
import places_check
import scoring
import site_check
import tavily_check
from site_check import get, _extract_jsonld


# ------------------------------------------------------------------ discovery

# Where a hotel actually links to from its own site. OTAs are absent by design -
# hotels do not send traffic to Booking.com - so they cannot be discovered here
# and are not pretended to be.
PROFILE_PATTERNS = {
    "Facebook": ["facebook.com"],
    "Instagram": ["instagram.com"],
    "X / Twitter": ["twitter.com", "x.com"],
    "LinkedIn": ["linkedin.com"],
    "YouTube": ["youtube.com", "youtu.be"],
    "TikTok": ["tiktok.com"],
    "Pinterest": ["pinterest."],
    "Google Maps": ["google.com/maps", "goo.gl/maps", "maps.app.goo.gl"],
    "TripAdvisor": ["tripadvisor."],
    "Booking.com": ["booking.com"],
    "Expedia": ["expedia."],
    "Hotels.com": ["hotels.com"],
    "OpenTable": ["opentable."],
    "ResDiary": ["resdiary."],
    "SevenRooms": ["sevenrooms."],
    "Yelp": ["yelp."],
}

# Links that are the platform generally, or one post, rather than the hotel's
# profile. Counting these as "has an Instagram presence" would be wrong.
_NOISE = re.compile(
    r"/(p|reel|share|posts|status|watch|embed|intent|sharer|dialog)/|"
    r"[?&](u|url|text)=|/plugins/", re.I
)


def _classify(url):
    low = url.lower()
    for name, pats in PROFILE_PATTERNS.items():
        if any(p in low for p in pats):
            return name
    return None


def discover_profiles(base, extra_pages=None, progress=None, prefetched=None):
    """
    Read the hotel's own pages and pull out links to its presence elsewhere.

    Two sources, because sites differ: JSON-LD `sameAs` (the explicit,
    machine-readable declaration - the Savoy publishes this) and plain
    outbound links (Brooklands does not publish sameAs but links to Facebook,
    Instagram, Google Maps and OpenTable in its markup).
    """
    found = {}          # platform -> best url
    saw_sameas = False

    pages = [base] + list(extra_pages or [])
    for i, page in enumerate(pages[:4]):
        if prefetched is not None and i < len(prefetched):
            html = prefetched[i]          # already fetched by the orchestrator
        else:
            if progress:
                progress(f"Looking for linked profiles on {page}")
            r = get(page)
            if r is None or r.status_code != 200:
                continue
            html = r.text

        # 1. explicit sameAs in JSON-LD - highest confidence
        sameas = []

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k.lower() == "sameas":
                        sameas.extend(v if isinstance(v, list) else [v])
                    else:
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        for b in _extract_jsonld(html):
            walk(b)
        if sameas:
            saw_sameas = True
        for u in sameas:
            if not isinstance(u, str):
                continue
            plat = _classify(u)
            if plat:
                found.setdefault(plat, {"url": u, "via": "JSON-LD sameAs"})

        # 2. plain outbound links - lower confidence, filtered for noise
        for href in set(re.findall(r'href=["\']([^"\'\s]+)["\']', html, re.I)):
            u = urllib.parse.urljoin(page, href)
            if _NOISE.search(u):
                continue
            plat = _classify(u)
            if plat:
                found.setdefault(plat, {"url": u, "via": "page link"})

    return {
        "profiles": [{"platform": k, **v} for k, v in sorted(found.items())],
        "declares_sameas": saw_sameas,
    }


def infer_hotel_name(site_payload):
    """Best guess at the hotel's name from its own markup, so the user needn't type it."""
    node = site_payload.get("lodging_node") or {}
    if node.get("name"):
        return str(node["name"])
    for p in site_payload.get("pages", []):
        for b in p.get("jsonld", []) or []:
            if isinstance(b, dict) and b.get("@type") in ("Organization", "WebSite") \
                    and b.get("name"):
                return str(b["name"])
    for p in site_payload.get("pages", []):
        if p.get("title"):
            # "Brooklands Hotel | Luxury Hotel in Weybridge" -> "Brooklands Hotel"
            return re.split(r"\s*[|\-–—:]\s*", p["title"])[0].strip()
    return ""


_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")
_MAPS_COORDS = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
_MAPS_PLACE = re.compile(r"/maps/(?:dir//|place/)([^/@?]+)")


def infer_location(site_payload, base, pages_html=None):
    """
    Work out WHERE this hotel is, without asking the user.

    This matters more than it looks. Hotel names repeat across the country:
    searching "Brooklands Hotel" with no location returns a hotel in Blackpool
    from OpenStreetMap and one in Dawlish from Wikidata, neither of which is
    the Weybridge one. Reporting either as "your hotel is listed" would be
    actively misleading, so location is established first and every entity
    match is then checked against it.

    Sources, strongest first:
      1. the hotel's own Hotel/LodgingBusiness address (if it publishes one)
      2. any PostalAddress anywhere in its JSON-LD
      3. a Google Maps link in the page markup - these carry the full address
         AND latitude/longitude, which is the most precise signal available
      4. a UK postcode in the page text
    """
    out = {"city": "", "postcode": "", "lat": None, "lon": None,
           "address": "", "source": ""}

    def take_address(addr, source):
        if not isinstance(addr, dict):
            return False
        city = addr.get("addressLocality") or ""
        region = addr.get("addressRegion") or ""
        pc = addr.get("postalCode") or ""
        if not (city or pc):
            return False
        out["city"] = ", ".join(b for b in (city, region) if b)
        out["postcode"] = pc
        out["address"] = ", ".join(
            str(addr.get(k)) for k in
            ("streetAddress", "addressLocality", "postalCode") if addr.get(k)
        )
        out["source"] = source
        return True

    # 1. the lodging node's own address
    node = site_payload.get("lodging_node") or {}
    if take_address(node.get("address"), "Hotel schema address"):
        return out

    # 2. any PostalAddress anywhere in the site's JSON-LD
    for p in site_payload.get("pages", []):
        for b in p.get("jsonld") or []:
            hit = []

            def walk(o):
                if isinstance(o, dict):
                    if str(o.get("@type", "")).endswith("PostalAddress"):
                        hit.append(o)
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)

            walk(b)
            for h in hit:
                if take_address(h, "PostalAddress in JSON-LD"):
                    return out

    # 3. a Google Maps link - carries the address and usually coordinates
    for html in (pages_html or []):
        for m in re.finditer(r'href=["\']([^"\'\s]*google\.[^"\'\s]*maps[^"\'\s]*)["\']',
                             html, re.I):
            url = urllib.parse.unquote(m.group(1))
            coords = _MAPS_COORDS.search(url)
            place = _MAPS_PLACE.search(url)
            if coords:
                out["lat"], out["lon"] = float(coords.group(1)), float(coords.group(2))
            if place:
                addr = place.group(1).replace("+", " ").strip()
                out["address"] = addr
                pc = _POSTCODE.search(addr.upper())
                if pc:
                    out["postcode"] = f"{pc.group(1)} {pc.group(2)}"
                    # town is usually the token just before the postcode
                    before = addr.upper().split(pc.group(1))[0].strip(" ,")
                    out["city"] = before.split(",")[-1].strip().title()
            if out["lat"] is not None or out["city"]:
                out["source"] = "Google Maps link on the site"
                return out

    # 4. last resort - a postcode anywhere in the markup
    for html in (pages_html or []):
        pc = _POSTCODE.search(re.sub(r"<[^>]+>", " ", html).upper())
        if pc:
            out["postcode"] = f"{pc.group(1)} {pc.group(2)}"
            out["source"] = "postcode found in page text"
            return out

    return out


def infer_city(site_payload):
    """Kept for callers that only want a city string."""
    return infer_location(site_payload, "").get("city", "")


# -------------------------------------------------------------- ai visibility

def _run_ai_visibility_subset(hotel, city, website, api_key, model=None,
                              limit=6, progress=None):
    """
    A deliberately small Gemini grounded-search run, reusing audit.py's
    existing query runner and metrics rather than a second implementation.

    `limit` caps queries PER SET (discovery + branded), so limit=6 is 12
    grounded calls, not 40 - a taste of AI visibility inside the one-button
    audit, not the full benchmark. The AI visibility TAB still exists for a
    full 40-query run with History trending; this is a smaller, cheaper
    sample used only to fill in this one scoring category.
    """
    kwargs = dict(
        hotel=hotel, website=website, city=city, api_key=api_key,
        limit=limit, verbose=False,
        progress=lambda done, total, label: progress(f"AI visibility: {label}")
        if progress else None,
    )
    if model:
        kwargs["model"] = model
    return audit.run_full(**kwargs)


# ------------------------------------------------------------------- findings

# Fields an AI needs to describe a hotel as an entity. Weighted, because a
# missing check-in time matters more than a missing price range.
HIGH_VALUE_SCHEMA = ["checkinTime", "checkoutTime", "address", "telephone",
                     "geo", "amenityFeature", "starRating", "priceRange"]


def build_findings(site, entities, consistency, discovery, location=None):
    """One prioritised list. Worst first. Every item says what to actually do."""
    F = []

    def add(sev, area, title, detail, fix):
        F.append({"severity": sev, "area": area, "title": title,
                  "detail": detail, "fix": fix})

    # --- crawler access: nothing else matters if this is wrong
    blocked = site.get("ai_crawlers_blocked") or []
    if blocked:
        add("critical", "Crawler access",
            f"AI crawlers blocked in robots.txt: {', '.join(blocked)}",
            "These crawlers are refused outright, so the hotel's own site cannot "
            "be used as a source by the assistants that rely on them. This is "
            "almost always accidental - a security plugin or CDN default.",
            "Remove or narrow those Disallow rules in robots.txt.")
    elif not site.get("robots", {}).get("present"):
        add("low", "Crawler access", "No robots.txt found",
            "Not harmful in itself - everything is crawlable by default - but "
            "it also means no sitemap is advertised there.",
            "Add a robots.txt that points to the sitemap.")

    # --- structured data: the single biggest lever after crawler access
    if not site.get("lodging_node_found"):
        types = ", ".join(site.get("schema_types_found") or []) or "none"
        add("critical", "Structured data",
            "No Hotel/LodgingBusiness structured data on the site",
            f"The site's facts exist only as prose, so any machine has to infer "
            f"them. Schema types currently published: {types}. Until this "
            f"exists there is no machine-readable version of the hotel's own "
            f"facts, so every other source is the authority by default.",
            "Add a Hotel or LodgingBusiness JSON-LD block on the homepage with "
            "name, address, geo, telephone, checkinTime, checkoutTime and "
            "amenityFeature.")
    else:
        props = site.get("lodging_properties_present") or {}
        missing = [k for k in HIGH_VALUE_SCHEMA if not props.get(k)]
        if missing:
            add("high", "Structured data",
                f"Hotel schema present but {len(missing)} key field(s) empty",
                "These are the fields an assistant uses to answer factual "
                f"questions: {', '.join(missing)}.",
                "Populate them in the existing JSON-LD block.")

    # --- can we even tell where this hotel is?
    loc = location or {}
    if not (loc.get("postcode") or loc.get("lat") or loc.get("city")):
        add("high", "Structured data",
            "The site never states the hotel's address in a readable form",
            "No address in structured data, no map link, no postcode found in "
            "the markup. If an automated check can't work out where this hotel "
            "is from its own website, neither can an AI assistant - and it "
            "can't be told apart from same-named hotels elsewhere.",
            "Publish a PostalAddress in JSON-LD, with the postcode.")

    # --- sitemap
    if not site.get("sitemap", {}).get("present"):
        add("medium", "Discoverability", "No sitemap found",
            "Crawlers have to find pages by following links, so deep pages may "
            "never be reached.",
            "Publish sitemap.xml and reference it from robots.txt.")

    # --- open data entity presence
    #
    # Three outcomes, kept distinct on purpose. "Couldn't verify" is not the
    # same as "not listed", and reporting an unverified same-name match as
    # found would tell a hotel it is mapped when it isn't.
    for e in entities:
        src = e["source"]
        sev = "high" if src == "OpenStreetMap" else "medium"
        if e.get("found") and e.get("match_confident") is not False:
            if e.get("match_confident") is None:
                add("low", "Entity presence",
                    f"{src} entry found by name, but not verified",
                    e.get("note", ""),
                    "Add an address or a Google Maps link to the hotel's own "
                    "site so this can be confirmed automatically, or check it "
                    "by hand.")
            continue
        add(sev, "Entity presence", f"Not found in {src}",
            e.get("note") or e.get("error", ""),
            f"Add the hotel to {src}. Both accept contributions and both feed "
            "systems that answer travel questions.")

    # --- fact consistency
    sig = [c for c in consistency if c["verdict"] == "significant discrepancy"]
    if sig:
        fields = sorted({c["field"] for c in sig})
        add("high", "Fact consistency",
            f"{len(sig)} significant discrepancy(ies) between sources",
            "Another source states something materially different from the "
            f"hotel's own site. Fields affected: {', '.join(fields)}.",
            "Correct the third-party source, or the hotel's own site if it's "
            "the one that's wrong.")

    # --- social / profile presence
    profiles = discovery.get("profiles") or []
    platforms = {p["platform"] for p in profiles}
    core_social = {"Facebook", "Instagram"}
    if not profiles:
        add("medium", "Linked presence", "No profiles linked from the site",
            "Nothing on the hotel's own pages points to its presence anywhere "
            "else, so the link between the site and those profiles is not "
            "machine-readable.",
            "Link the hotel's own profiles from the site, and declare them in "
            "JSON-LD `sameAs`.")
    elif not discovery.get("declares_sameas"):
        add("medium", "Linked presence",
            "Profiles linked, but not declared in JSON-LD `sameAs`",
            f"Found: {', '.join(sorted(platforms))}. They're present as ordinary "
            "links, which is a weaker, inferred signal than an explicit "
            "declaration that these are the same entity.",
            "Add a `sameAs` array listing these URLs to the Hotel JSON-LD.")
    missing_social = core_social - platforms
    if missing_social and profiles:
        add("low", "Linked presence",
            f"No link to {', '.join(sorted(missing_social))}",
            "Either the hotel has no profile there, or it has one that isn't "
            "linked from the site.",
            "Link it if it exists; this check cannot tell the two apart.")

    # --- topic coverage
    gaps = site.get("topics_no_page_found") or []
    if gaps:
        add("low", "Content coverage",
            f"{len(gaps)} traveller topic(s) with no obvious page",
            f"No page found for: {', '.join(gaps)}. Detection is by URL pattern, "
            "so an unusual slug causes a false negative - check before acting.",
            "Where the facility exists but has no page, give it one. A question "
            "with no page answering it has no source to cite.")

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    F.sort(key=lambda f: order[f["severity"]])
    return F


def score(findings, site):
    """
    0-100, deliberately blunt. It exists to make movement between runs
    visible, not to be precise. The findings list is the real output.
    """
    penalty = {"critical": 30, "high": 15, "medium": 7, "low": 2}
    total = sum(penalty[f["severity"]] for f in findings)
    return max(0, 100 - min(total, 100))


# --------------------------------------------------------------- orchestrator

def run_full_audit(website, hotel="", city="", progress=None, max_pages=12,
                   tavily_api_key=None, places_api_key=None,
                   amadeus_api_key=None, amadeus_api_secret=None,
                   include_ai_visibility=False, gemini_api_key=None,
                   gemini_model=None, ai_visibility_limit=6):
    """
    The one button. Every optional integration below is genuinely optional:
    omit its key and that category reports "not assessed" rather than
    failing the whole audit. This is the single place all eight scoring
    categories are assembled - there is deliberately no other code path that
    produces a partial result, so there is one report, not several tabs.

    AI visibility is the one category that costs real money once configured
    (Gemini grounding), so unlike the others it needs `include_ai_visibility`
    explicitly set True even when a key is present - it never runs by
    accident just because a key happens to be configured.
    """
    def say(msg):
        if progress:
            progress(msg)

    say("Checking the website...")
    site = site_check.run_site_check(website, max_pages=max_pages, progress=progress)

    base = site["meta"]["base"]

    hotel_given, city_given = bool(hotel), bool(city)
    hotel = hotel or infer_hotel_name(site)

    say("Finding linked profiles...")
    topic_pages = [v["urls"][0] for v in (site.get("topic_coverage") or {}).values()
                   if v.get("urls")]
    pages_to_read = [base] + topic_pages[:2]
    pages_html = []
    for p in pages_to_read:
        r = get(p)
        if r is not None and r.status_code == 200:
            pages_html.append(r.text)

    discovery = discover_profiles(base, extra_pages=topic_pages[:2], progress=progress,
                                  prefetched=pages_html)

    # Establish WHERE the hotel is before looking it up anywhere, so a
    # same-named hotel in another town can't be reported as a match.
    say("Working out the hotel's location...")
    location = infer_location(site, base, pages_html=pages_html)
    if city_given:
        location["city"] = city
        location["source"] = "provided by you"
    city = location["city"]

    # Any discovered profile that might carry structured data is worth reading.
    # Most will be blocked; that is reported, not inferred away.
    listing_urls = [p["url"] for p in discovery["profiles"]
                    if p["platform"] in ("TripAdvisor", "Booking.com", "Expedia",
                                         "Hotels.com", "Yelp", "OpenTable")]

    say("Checking open data sources...")
    ext = external_check.run_external_check(
        listing_urls, site.get("lodging_node"), progress=progress,
        hotel=hotel, city=city, location=location,
    )

    # ---- optional integrations. Each is independently skippable, and each
    # is called from exactly here - the single pipeline - not from a
    # separate tab the user has to remember to visit.
    tavily_result = None
    if tavily_check.has_key(tavily_api_key):
        say("Checking editorial coverage and OTA presence (Tavily)...")
        try:
            tavily_result = tavily_check.check_coverage(hotel, city, api_key=tavily_api_key)
        except Exception as e:  # noqa: BLE001 - a failed integration must not fail the audit
            tavily_result = {"configured": True, "error": str(e),
                             "ota_hits": [], "editorial_hits": [], "other_hits": []}

    places_result = None
    if places_check.has_key(places_api_key):
        say("Checking Google rating and reviews...")
        try:
            places_result = places_check.check_hotel(
                hotel, city, lat=location.get("lat"), lon=location.get("lon"),
                api_key=places_api_key)
        except Exception as e:  # noqa: BLE001
            places_result = {"configured": True, "found": False, "error": str(e)}

    amadeus_result = None
    if amadeus_check.has_credentials(amadeus_api_key, amadeus_api_secret):
        say("Checking Amadeus review sentiment...")
        try:
            amadeus_result = amadeus_check.check_hotel(
                hotel, lat=location.get("lat"), lon=location.get("lon"),
                api_key=amadeus_api_key, api_secret=amadeus_api_secret)
        except Exception as e:  # noqa: BLE001
            amadeus_result = {"configured": True, "found": False, "error": str(e)}

    ai_visibility_cat, ai_visibility_raw = None, None
    if include_ai_visibility and gemini_api_key:
        say("Checking AI visibility (spends Gemini quota)...")
        try:
            ai_visibility_raw = _run_ai_visibility_subset(
                hotel, city, website, api_key=gemini_api_key,
                model=gemini_model, limit=ai_visibility_limit, progress=progress)
            ai_visibility_cat = scoring.score_ai_visibility(ai_visibility_raw)
        except Exception as e:  # noqa: BLE001
            ai_visibility_cat = scoring._not_assessed(
                "ai_visibility", f"Configured but the check failed: {e}",
                "Check the Gemini API key and that billing is enabled.")

    findings = build_findings(site, ext["entities"], ext["consistency"], discovery,
                              location=location)

    scorecard = scoring.build_scorecard(
        site, ext["entities"], ext["consistency"], location, discovery,
        ai_visibility=ai_visibility_cat, tavily_result=tavily_result,
        places_result=places_result, amadeus_result=amadeus_result,
    )

    return {
        "meta": {
            "hotel": hotel,
            "city": city,
            "website": website,
            "base": base,
            "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "hotel_name_source": "provided by you" if hotel_given
                                 else "inferred from the site's own markup",
            "location": location,
            "keys_used": {
                "tavily": bool(tavily_result and tavily_result.get("configured")),
                "google_places": bool(places_result and places_result.get("configured")),
                "amadeus": bool(amadeus_result and amadeus_result.get("configured")),
                "ai_visibility": bool(ai_visibility_cat and ai_visibility_cat["assessed"]),
            },
        },
        "score": scorecard["overall"],
        "coverage_pct": scorecard["coverage_pct"],
        "scorecard": scorecard,
        "recommendations": scoring.all_recommendations(scorecard),
        "legacy_score": score(findings, site),
        "findings": findings,
        "site": site,
        "discovery": discovery,
        "entities": ext["entities"],
        "consistency": ext["consistency"],
        "blocked_sources": ext["blocked_sources"],
        "reputation": ext["reputation"],
        "tavily_result": tavily_result,
        "places_result": places_result,
        "amadeus_result": amadeus_result,
        "ai_visibility_raw": ai_visibility_raw,
    }


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--website", required=True)
    p.add_argument("--hotel", default="")
    p.add_argument("--city", default="")
    p.add_argument("--max-pages", type=int, default=12)
    p.add_argument("--out", default="full_audit.json")
    p.add_argument("--include-ai-visibility", action="store_true",
                   help="spends real Gemini quota - off unless asked for")
    p.add_argument("--ai-visibility-limit", type=int, default=6)
    a = p.parse_args()

    # Every integration is optional and picked up from the environment, same
    # as GEMINI_API_KEY already was - no new pattern introduced.
    res = run_full_audit(
        a.website, a.hotel, a.city,
        progress=lambda m: print(f"  {m}"),
        max_pages=a.max_pages,
        tavily_api_key=os.environ.get("TAVILY_API_KEY"),
        places_api_key=os.environ.get("GOOGLE_PLACES_API_KEY"),
        amadeus_api_key=os.environ.get("AMADEUS_API_KEY"),
        amadeus_api_secret=os.environ.get("AMADEUS_API_SECRET"),
        include_ai_visibility=a.include_ai_visibility,
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        ai_visibility_limit=a.ai_visibility_limit,
    )

    sc = res["scorecard"]
    print(f"\nHotel: {res['meta']['hotel']}  ({res['meta']['hotel_name_source']})")
    print(f"City:  {res['meta']['city'] or '(not determined)'}")
    print(f"\n  SCORE {sc['overall']}  across {sc['coverage_pct']}% of the model")
    print(f"  {sc['caveat']}\n")

    print(f"  {'CATEGORY':<28}{'WEIGHT':>8}{'SCORE':>7}   STATUS")
    print("  " + "-" * 66)
    for c in sc["categories"]:
        s = str(c["score"]) if c["assessed"] else "-"
        status = ("partial - see notes" if c.get("partial")
                  else ("assessed" if c["assessed"] else "NOT ASSESSED"))
        print(f"  {c['label']:<28}{c['weight']:>7}%{s:>7}   {status}")

    print("\n  WHY\n")
    for c in sc["categories"]:
        if not c["assessed"]:
            continue
        print(f"  {c['label']} - {c['score']}")
        for e in c["evidence"]:
            print(f"    - {e}")
        print()

    print("  NOT ASSESSED\n")
    for c in sc["categories"]:
        if c["assessed"]:
            continue
        print(f"  {c['label']} ({c['weight']}% of the model)")
        print(f"    {c['detail']}")
        print(f"    To enable: {c.get('how_to_enable', '')}\n")

    print("  WHAT TO DO, WORST FIRST\n")
    for r in res["recommendations"]:
        print(f"  [{r['priority'].upper():<8}] {r['action']}")
        print(f"             ({r['category']}) {r['why']}\n")
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=2)
    print(f"\nWritten: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
