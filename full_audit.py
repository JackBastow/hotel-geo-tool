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
import threading

import steps
import reading as _reading
import insight_content as ic_mod
import datetime as dt
import html as html_lib
import json
import re
import os
import sys
import urllib.parse

import requests
from concurrent.futures import ThreadPoolExecutor

import ai_gap
import depth as _depth_mod
import citations as citations_mod
import forums as forums_mod
import ai_questions
import anchors as anchors_mod
import ai_insights
import ai_niche
import ai_sample
import amadeus_check
import booking_check
import competitors as competitors_mod
import evidence
import external_presence
import ai_extract
import netguard
import claude_reader
import review_replies
import audit
import collect
import consultant
import external_check
import fixes
import guest_questions
import listing_facts
import listing_lookup
import reddit_check
import headline
import intel
import places_check
import sources
import scoring
import site_check
import tavily_check
import urlscope
import web_signals
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
    r"/watch(?:\?|$)|[?&](u|url|text)=|/plugins/", re.I
)

# Profile URLs on these platforms are identified by their path alone; anything
# after a "?" is tracking (TikTok's _r/_t, Instagram's igsh, utm_*, fbclid...).
_PATH_ONLY = {"Facebook", "Instagram", "X / Twitter", "LinkedIn", "YouTube",
              "TikTok", "Pinterest"}


def _tidy_profile_url(platform, url):
    """
    Clean a discovered profile link before it is shown or suggested as a
    `sameAs` value. Links scraped out of raw HTML still carry entities
    (&#038; for &) and tracking parameters; pasting those into a hotel's
    structured data would be bad advice. Seen live on a real site, where a
    TikTok link came out as .../@brooklandshotel?_r=1&#038;_t=ZN-94DjKx4BLVb.
    """
    url = html_lib.unescape(str(url)).strip()
    if platform in _PATH_ONLY:
        p = urllib.parse.urlparse(url)
        url = urllib.parse.urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", "", ""))
    return url


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
                found.setdefault(plat, {"url": _tidy_profile_url(plat, u),
                                        "via": "JSON-LD sameAs"})

        # 2. plain outbound links - lower confidence, filtered for noise
        for href in set(re.findall(r'href=["\']([^"\'\s]+)["\']', html, re.I)):
            u = urllib.parse.urljoin(page, href)
            if _NOISE.search(u):
                continue
            plat = _classify(u)
            if plat:
                found.setdefault(plat, {"url": _tidy_profile_url(plat, u),
                                        "via": "page link"})

    return {
        "profiles": [{"platform": k, **v} for k, v in sorted(found.items())],
        "declares_sameas": saw_sameas,
    }


def infer_hotel_name(site_payload):
    """Best guess at the hotel's name from its own markup, so the user needn't type it."""
    node = site_payload.get("lodging_node") or {}
    if node.get("name"):
        return html_lib.unescape(str(node["name"])).strip()
    for p in site_payload.get("pages", []):
        for b in p.get("jsonld", []) or []:
            if isinstance(b, dict) and b.get("@type") in ("Organization", "WebSite") \
                    and b.get("name"):
                return html_lib.unescape(str(b["name"])).strip()
    for p in site_payload.get("pages", []):
        if p.get("title"):
            # "Brooklands Hotel | Luxury Hotel in Weybridge" -> "Brooklands Hotel"
            # (titles arrive HTML-escaped: "Chewton Glen Hotel &amp; Spa")
            return re.split(r"\s*[|\-–—:]\s*", html_lib.unescape(p["title"]))[0].strip()
    return ""


def tidy_typed_name(given, site, base, scope):
    """
    A name typed as one run-together word ('hiltonzurichairport') is replaced by the site's own spelling when that is the same name with spaces
    ('Hilton Zurich Airport'): the direct questions put to an AI assistant are only meaningful with the name people actually use.
    -> (name, changed).
    """
    given = (given or "").strip()
    # a name copied from the address ('Paroa Paris Marriott Opera Ambassador Hotel') carries the chain's property code at the front: the hotel is called without it
    code = urlscope.property_code(base, scope)
    words = given.split()
    if code and len(words) >= 3 and words[0].lower() == code:
        return " ".join(words[1:]), True
    squash = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())      # noqa: E731
    g = squash(given)
    if " " in given or len(g) < 8:
        return given, False
    cands = [infer_hotel_name(site)]
    if scope:
        cands.append(urlscope.name_from_url(base, scope).get("name", ""))
    for c in cands:
        k = squash(c)
        if k and len(k) >= 8 and (k == g or k in g or g in k):
            return c.strip(), True
    return given, False


def _place_from_text(text):
    """Is this word a town or city? Asked of OpenStreetMap's own place search (free), restricted to settlements so 'Zurich Airport' is not taken for a town. '' when it is not, or the service is down."""
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": text, "format": "jsonv2", "limit": 1, "addressdetails": 1, "accept-language": "en", "featureType": "settlement"},
                         headers={"User-Agent": sources.UA}, timeout=12)
        hit = (r.json() or [None])[0] if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return ""
    if not hit or hit.get("category") not in ("place", "boundary") or hit.get("type") not in ("city", "town", "village", "administrative", "suburb", "municipality", "hamlet", "borough"):
        return ""
    return (hit.get("name") or text).strip()


def city_from_candidates(cands, limit=4):
    """The first candidate that is really a town (one question a second to the place search, as its policy asks). '' when none is."""
    import time as _t
    for k, c in enumerate(cands[:limit]):
        if k:
            _t.sleep(1.1)
        place = _place_from_text(c)
        if place:
            return place
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

    # 4. last resort - a valid UK postcode in the text a visitor sees (never in scripts or styles, where strings like 'V8 3OH' are code; never a registered-office address)
    import locate
    pc = locate.postcode_from_pages(pages_html)
    if pc:
        out["postcode"] = pc
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
            (f"Search {src} by hand first (our search is by name and can miss an entry mapped under another name); if the hotel is absent, add it. "
             if src == "OpenStreetMap" else f"Add the hotel to {src}. ") + "Both accept contributions and both feed systems that answer travel questions.")

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
            f"No page address matched {len(gaps)} traveller topic(s)",
            f"No page address matched: {', '.join(gaps)}. This is a guess from "
            "URL wording, not from reading the pages - a page may exist under a "
            "different name, so it is not evidence that the information is missing.",
            "Check by hand. If the facility exists but nothing answers the "
            "question, a guest or AI assistant has no source to quote.")

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


def _page_links(html, base):
    """[{url, anchor}] for every link on a page - used to spot booking engines."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html or "", "html.parser")
        return [{"url": urllib.parse.urljoin(base, a["href"]), "anchor": a.get_text(" ", strip=True)}
                for a in soup.find_all("a", href=True)][:300]
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------- orchestrator

class _NoName(Exception):
    """Internal: the hotel's name is unknown, so the outside-evidence analysis is skipped."""


def run_full_audit(website, hotel="", city="", progress=None, max_pages=12,
                   tavily_api_key=None, places_api_key=None,
                   amadeus_api_key=None, amadeus_api_secret=None,
                   include_ai_visibility=False, gemini_api_key=None,
                   gemini_model=None, ai_visibility_limit=6,
                   gemini_reader_key=None, gemini_reader_model=None,
                   youtube_api_key=None, wider=True, pagespeed_api_key=None, anthropic_api_key=None, anthropic_model=None,
                   anthropic_repeats=None, market_hint=None, custom_prompts=None, benchmark=None, ai_depth="standard", firecrawl_api_key=None, places_nearby_key=None, tripadvisor_api_key=None, profile=None, reading_mode="adaptive"):
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

    `gemini_reader_key` is a DIFFERENT, free use of a Gemini key: it only
    reads text tavily_check.py has already fetched and judges it (sentiment,
    substance, whether it's genuinely about this hotel) via an ungrounded
    call - see gemini_reader.py's module docstring for why that is a
    separate cost profile from AI visibility's grounded search, not a
    relaxed version of the same setting. Configuring this does not enable
    or require `include_ai_visibility`, and vice versa.
    """
    steps.begin()                   # every step that fails from here on is logged and recorded in the report (step_errors)
    urlscope.set_hint(hotel, city)          # a brand site's folder named after the town or the hotel is this hotel's own section (urlscope.normalise)
    def say(msg):
        if progress:
            progress(msg)

    say("Checking the website...")
    site = site_check.run_site_check(website, max_pages=max_pages, progress=progress)

    base = site["meta"]["base"]

    # AI-crawler access, Common Crawl, llms.txt and PageSpeed are slow but independent of everything else, so they run
    # alongside the rest of the audit and are joined just before the analysis.
    web_ex = ThreadPoolExecutor(max_workers=1)
    web_future = web_ex.submit(web_signals.run, base, site.get("robots"), pagespeed_api_key, None)

    if city and urlscope.is_country(city):
        city = ""                       # a country is not a town: work the town out from the hotel's own pages instead of asking assistants about "hotels in France"
    hotel_given, city_given = bool(hotel), bool(city)
    name_respelled = False
    if hotel_given:
        hotel, name_respelled = tidy_typed_name(hotel, site, base, site["meta"].get("scope"))
    hotel = hotel or infer_hotel_name(site)
    # A chain page we could not read still names the hotel in its address: guess from that rather than giving up.
    slug_guess = {"name": "", "city_candidates": []}
    if not hotel and site["meta"].get("scope"):
        slug_guess = urlscope.name_from_url(base, site["meta"]["scope"])
        hotel = slug_guess["name"]
    name_from_address = bool(hotel) and not hotel_given and bool(slug_guess["name"])

    say("Finding linked profiles...")
    topic_pages = [v["urls"][0] for v in (site.get("topic_coverage") or {}).values()
                   if v.get("urls")]
    home_url = site["meta"].get("home_url") or site["meta"].get("entry_url") or base      # the page that answered, which is the address as submitted when it works
    pages_to_read = [home_url] + topic_pages[:2]
    pages_html = []
    with ThreadPoolExecutor(max_workers=3) as _ex:      # three independent fetches, kept in order
        for r in _ex.map(get, pages_to_read):
            if r is not None and r.status_code == 200:
                pages_html.append(r.text)

    discovery = discover_profiles(home_url, extra_pages=topic_pages[:2], progress=progress,
                                  prefetched=pages_html)

    # Establish WHERE the hotel is before looking it up anywhere, so a
    # same-named hotel in another town can't be reported as a match.
    say("Working out the hotel's location...")
    location = infer_location(site, base, pages_html=pages_html)
    if profile and isinstance(profile.get("lat"), (int, float)) and isinstance(profile.get("lon"), (int, float)):
        location = {**(location or {}), "lat": profile["lat"], "lon": profile["lon"]}          # the place the hotel confirmed on the map: nearby places and listings are found from there
    if city_given:
        location["city"] = city
        location["source"] = "provided by you"
    elif not location.get("city"):
        # the town is usually in the hotel's own name or in its address ('Hilton Zurich Airport', .../zrhhitw-hilton-zurich-airport/): ask a place search whether a word of it is a town
        place = city_from_candidates((slug_guess["city_candidates"] if name_from_address else []) + urlscope.place_candidates(hotel) + (urlscope.place_candidates(urlscope.name_from_url(base, site["meta"].get("scope")).get("name", "")) if not name_from_address else []))
        if place:
            location["city"], location["source"] = place, ("inferred from the hotel's name and web address")
    city = location["city"]
    try:
        import locate
        locate.fill_position(location, hotel, city, netguard.get)          # no map position yet: from the postcode (postcodes.io), else the name and town (OpenStreetMap search)
    except Exception as e:  # noqa: BLE001
        steps.failed("Finding the hotel on the map", e, quiet=True)

    # The wider discovery (other sources, media coverage, listings, awards) needs only
    # the name, place and segments - not the guest-question results - so it runs in
    # the background while the website itself is read.
    segment_labels = [tavily_check.SEGMENTS[k][0]
                      for k in tavily_check.detect_segments(site.get("topics_covered"))]
    # A few real questions put to an AI assistant (needs a name and a town; runs beside everything else).
    ai_ex = ai_future = rv_future = ll_future = rd_future = None
    # The country the searches are run as if from: the hotel's own (its website's ending, or where one search of the map places it). No market picker: one sensible default, stated in the report.
    import anchors as _am
    import phones as _ph0
    search_country = _ph0.region_from_host(urllib.parse.urlparse(base).netloc) or ai_sample.country_from_location(location)
    if not search_country and hotel and city and anthropic_api_key:
        try:
            _g = _am.geocode(hotel, city, netguard.get, with_country=True)
            search_country = _g[2] if _g else None
        except Exception as _step_e:  # noqa: BLE001
            steps.failed('Working out the hotel / _g', _step_e)
            search_country = None
    if anthropic_api_key and hotel and city:
        ai_ex = ThreadPoolExecutor(max_workers=4)
        import depth as _depth
        _dl = _depth.limits(ai_depth)
        _rep = {"repeats": max(1, min(5, int(anthropic_repeats)))} if anthropic_repeats is not None else {"repeats": _dl["repeats"]}      # how many times each list question is asked
        ai_future = ai_ex.submit(ai_sample.run, hotel, city, api_key=anthropic_api_key, model=anthropic_model, max_questions=_dl["generic_questions"], budget_usd=_dl["budget_generic"], workers=_dl["workers"],
                                 segments=segment_labels, own_domain=base, country=search_country, **_rep)
        rv_future = ai_ex.submit(review_replies.run, hotel, city, api_key=anthropic_api_key, model=anthropic_model)
        ll_future = ai_ex.submit(listing_lookup.run, hotel, city, api_key=anthropic_api_key, model=anthropic_model)     # finds the hotel's listing on each major site
        rd_future = ai_ex.submit(reddit_check.run, hotel, city, api_key=anthropic_api_key, model=anthropic_model)       # Reddit threads about the hotel and the town
    collect_ex = collect_future = None
    if wider and hotel:
        collect_ex = ThreadPoolExecutor(max_workers=1)
        collect_future = collect_ex.submit(
            collect.collect, hotel, city, base, location=location, segments=segment_labels,
            tavily_key=tavily_api_key, youtube_key=youtube_api_key)

    # Any discovered profile that might carry structured data is worth reading.
    # Most will be blocked; that is reported, not inferred away.
    listing_urls = [p["url"] for p in discovery["profiles"]
                    if p["platform"] in ("TripAdvisor", "Booking.com", "Expedia",
                                         "Hotels.com", "Yelp", "OpenTable")]

    # Read a bounded set of the hotel's own pages to see what a guest (or an
    # AI assistant) can actually learn from them. Failure here must not fail
    # the audit - the rest of the report stands without it.
    say("Checking whether the website answers guests' questions...")
    _second = None
    if firecrawl_api_key:
        import firecrawl_reader
        import polite as _polite
        _second_used = []

        def _second(u):
            """A page our reader could not use (script-built, timed out, refused), read once by Firecrawl, which renders pages; only where robots.txt allows automated reading."""
            if not _polite.allowed(u):
                return None
            _second_used.append(u)
            res = firecrawl_reader.scrape(u, firecrawl_api_key)
            return firecrawl_reader.build_page(u, res) if res.get("ok") else None
    try:
        _brand_site = bool((site.get("meta") or {}).get("scope"))            # a hotel's section of a brand's website: these block or script-build their pages
        _fc_primary = bool(_second) and (_brand_site or (os.environ.get("FIRECRAWL_PRIMARY") or "").strip().lower() in ("1", "true", "yes", "all"))
        if _fc_primary:
            say("Reading the hotel's pages with Firecrawl (renders pages as a browser does)...")
        guest = guest_questions.run(site, base, hotel, location=location, progress=say, fallback=_second, prefer_fallback=_fc_primary,
                                     max_pages=(_reading.FIRST_BATCH if reading_mode == "adaptive" else _reading.STANDARD))
        if _fc_primary:
            guest["read_via"] = guest.get("read_via") or "firecrawl_primary"
        if _second is not None and _second_used:
            guest["firecrawl_pages"] = {"credits": len(_second_used), "pages": _second_used[:10]}
    except Exception as e:  # noqa: BLE001
        steps.failed('Checking whether the website answers guests / guest', e)
        guest = {"error": str(e), "questions": [], "fact_sheet": [], "conflicts": [],
                 "own_facts_node": {}, "pages_attempted": 0, "pages_ok": 0,
                 "pages_failed": [], "evidence_sufficient": False, "sitemap_total": 0}

    # The site refused our reader (a chain's bot protection, say). Fall back to Anthropic's openly identified page reader for the hotel's own
    # pages: only when our reader got fewer than three, only inside the hotel's own folder, and always reported as such.
    if firecrawl_api_key and hotel and guest.get("pages_ok", 0) < 3:
        import firecrawl_reader
        ffb = firecrawl_reader.read_hotel_pages(home_url, api_key=firecrawl_api_key, progress=say)
        if ffb["status"] == "ok" and sum(1 for p in ffb["pages"] if p["ok"]) >= 1:
            refused = guest.get("pages_failed") or []
            guest = guest_questions.run_prefetched(site, base, hotel, ffb["pages"], location=location)
            guest["read_via"] = "firecrawl"
            guest["firecrawl"] = {"credits": ffb["credits"], "status": "ok"}
            guest["html_read"] = any(p.get("html_via") for p in ffb["pages"] if p["ok"])      # the markup came too, so technical checks can run
            guest["own_reader_refused"] = refused[:3]
        else:
            guest["firecrawl"] = {"credits": ffb.get("credits", 0), "status": ffb["status"], "reason": ffb.get("reason", "")}
    if anthropic_api_key and hotel and guest.get("pages_ok", 0) < 3:
        fb = claude_reader.read_hotel_pages(home_url, api_key=anthropic_api_key, model=anthropic_model, progress=say)
        if fb["status"] == "ok" and sum(1 for p in fb["pages"] if p["ok"]) >= 1:
            refused = guest.get("pages_failed") or []
            fc_note = guest.get("firecrawl")             # why Firecrawl did not read it (robots.txt, or it failed): kept, so the report can say so
            guest = guest_questions.run_prefetched(site, base, hotel, fb["pages"], location=location)
            if fc_note:
                guest["firecrawl"] = fc_note
            guest["read_via"] = "anthropic_page_reader"
            guest["reader_cost_usd"] = fb["cost_usd"]
            guest["own_reader_refused"] = refused[:3]
        else:
            guest["page_reader_note"] = fb.get("reason", "")

    # The verified fact profile: one answer per facility (at the hotel / nearby / through a partner / not offered), read by every part of the report (fact_profile.py). Read alongside
    # the guest-question reading below; until it is ready, nothing has asked what the hotel has.
    import fact_profile
    from concurrent.futures import ThreadPoolExecutor as _TPE
    _fp_pool = _TPE(max_workers=1)
    _fp_future = _fp_pool.submit(fact_profile.build, list(guest.get("own_pages") or []), api_key=anthropic_api_key,
                                 model=os.environ.get("ANTHROPIC_EXTRACT_MODEL") or None, failed_pages=len(guest.get("pages_failed") or [])) if anthropic_api_key else None
    # AI reading of the hotel's own pages for what the rule-based check missed. Only quotations that appear word for word on the page are kept (see ai_extract).
    if anthropic_api_key and guest.get("questions"):
        say("Reading the hotel's pages with AI for facts the rules missed (quotations are checked)...")
        try:
            ai_extract.run(guest, guest.get("own_pages") or [], api_key=anthropic_api_key, model=os.environ.get("ANTHROPIC_EXTRACT_MODEL") or None)
        except Exception as e:  # noqa: BLE001 - never fail the audit
            steps.failed('Reading the hotel / ai_extract.run', e)
            guest["ai_extract"] = {"source": ai_extract.SOURCE, "status": "unavailable", "reason": f"The AI reading did not finish ({type(e).__name__}).", "cost_usd": 0.0}

    own_pages = guest.pop("own_pages", [])     # used by the wider analysis, not stored

    try:
        fact_prof = _fp_future.result(timeout=180) if _fp_future else fact_profile._envelope("not_configured", "No Anthropic API key is configured, so facilities were judged by the word rules alone.")
    except Exception as e:  # noqa: BLE001 - never fail the audit; the word rules stand alone
        steps.failed('Fact profile / fact_profile.build', e)
        fact_prof = fact_profile._envelope("unavailable", f"The AI reading of the facilities did not finish ({type(e).__name__}).")
    _fp_pool.shutdown(wait=False)
    _start = ((site.get("meta") or {}).get("home_url") or (site.get("meta") or {}).get("entry_url") or base)
    for _b in {base, _start}:
        fact_profile.use(_b, fact_prof)                 # always set, even empty: a previous audit's answers for this hotel are never reused
    try:
        fact_prof["questions_changed"] = fact_profile.reconcile_questions(guest.get("questions"), fact_prof)      # the guest questions follow the same answers
    except Exception as e:  # noqa: BLE001
        steps.failed("Fact profile / reconcile_questions", e)

    # Adaptive reading: more of the hotel's own pages, only for what is still unverified after the first read, up to reading.LIMIT pages in all (reading.py)
    _followed = {}
    fact_prof["follow_up"] = {"mode": reading_mode, "topics": [], "pages_read": 0}
    if reading_mode == "adaptive" and anthropic_api_key and fact_prof.get("status") == "ok":
        try:
            _feats = ic_mod.features(ic_mod.Site(own_pages, base, hotel, city))
            _topics = _reading.unverified(guest, fact_prof, _feats)
            _room = _reading.LIMIT - len([p for p in own_pages if p.get("ok", True)])
            _cands = [{"url": u} for u in (guest.get("page_candidates") or [])]
            _urls, _followed = _reading.follow_up(_cands, [p.get("url", "") for p in own_pages], _topics, max(0, _room))
            fact_prof["follow_up"].update(topics=_topics, candidates=len(_cands))
            if _urls:
                say(f"Reading {len(_urls)} more page(s) for what is still unverified ({', '.join(_topics[:5])})...")

                def _read_more(u):
                    if _fc_primary and _second:
                        try:
                            pg = _second(u)
                            if pg and pg.get("ok"):
                                return {**pg, "via_second_reader": True}
                        except Exception:  # noqa: BLE001
                            pass
                    return guest_questions.fetch_page(u)
                from concurrent.futures import ThreadPoolExecutor as _TPE2
                with _TPE2(max_workers=4) as _ex:
                    _new = list(_ex.map(_read_more, _urls))
                _ok_new = [p for p in _new if p.get("ok")]
                fact_prof["follow_up"].update(pages_read=len(_ok_new), pages_failed=len(_new) - len(_ok_new))
                if _ok_new:
                    _more = fact_profile.build(_ok_new, api_key=anthropic_api_key, model=os.environ.get("ANTHROPIC_EXTRACT_MODEL") or None)
                    _before = {k for k, v in (fact_prof.get("facilities") or {}).items() if v.get("status")}
                    fact_profile.merge(fact_prof, _more)
                    fact_prof["follow_up"]["newly_verified"] = sorted({k for k, v in fact_prof["facilities"].items() if v.get("status")} - _before)
                    # the guest questions again, on every page now read; what the first reading added is kept
                    _keep = {k: guest.get(k) for k in ("ai_extract", "read_via", "firecrawl", "own_reader_refused", "page_reader_note", "fc_note", "discovery", "page_candidates") if k in guest}
                    _all = [dict(p, ok=p.get("ok", True)) for p in own_pages] + _ok_new
                    guest = guest_questions.run_prefetched(site, base, hotel, _all, location=location)
                    guest.update(_keep)
                    own_pages = guest.pop("own_pages", []) or _all
                    for _b in {base, _start}:
                        fact_profile.use(_b, fact_prof)
                    fact_prof["questions_changed"] = fact_profile.reconcile_questions(guest.get("questions"), fact_prof)
                    if anthropic_api_key:
                        try:
                            ai_extract.run(guest, own_pages, api_key=anthropic_api_key, model=os.environ.get("ANTHROPIC_EXTRACT_MODEL") or None)
                        except Exception:  # noqa: BLE001
                            pass
                        fact_profile.reconcile_questions(guest.get("questions"), fact_prof)
        except Exception as e:  # noqa: BLE001 - the first read stands
            steps.failed("Adaptive reading / follow-up", e)
    guest["page_ledger"] = _reading.ledger([dict(p, ok=p.get("ok", True)) for p in own_pages] + [p for p in (guest.get("pages_meta") or []) if not p.get("ok")],
                                           guest.get("page_candidates"), _followed)

    # Where the hotel is, again, now its pages have been read: the first attempt used the few pages our own reader could fetch, and a site that refuses it (a brand, or THE NICI from the host)
    # left the hotel with no map position, so no comparable hotels, distances or nearby places. The postcode on any page read (FAQ, contact) places it.
    late_position = False
    if location is not None and location.get("lat") is None and own_pages:
        try:
            import locate
            if not location.get("postcode"):
                pc = locate.postcode_from_pages([p.get("text") or "" for p in own_pages if p.get("ok", True)], city)      # own_pages holds only pages that were read (no 'ok' flag)
                if pc:
                    location["postcode"], location["postcode_source"] = pc, "the hotel's own pages"
            locate.fill_position(location, hotel, city, netguard.get)
            late_position = location.get("lat") is not None
        except Exception as e:  # noqa: BLE001
            steps.failed("Finding the hotel on the map from its pages", e, quiet=True)

    # Booking readiness runs in the background from here (a handful of polite requests that can take several seconds on a slow site) and is joined when the report is assembled, so it adds no waiting.
    try:
        _home_links = _page_links(pages_html[0], home_url) if pages_html else []
    except Exception as _step_e:  # noqa: BLE001
        steps.failed('Reading the hotel / _home_links', _step_e)
        _home_links = []
    booking_ex = ThreadPoolExecutor(max_workers=1)
    booking_future = booking_ex.submit(booking_check.run, base, _home_links, own_pages, guest.get("pages_meta", []))

    # The consistency check needs the hotel's OWN facts to compare against.
    # Many sites publish no structured data, which used to mean "nothing to
    # compare". Facts read from the page text (phone, address, times) fill
    # that gap; anything the site does publish as JSON-LD takes precedence.
    own_facts = dict(guest.get("own_facts_node") or {})
    own_facts.update({k: v for k, v in (site.get("lodging_node") or {}).items() if v})
    own_facts_source = ("structured data plus page text" if site.get("lodging_node")
                        else "page text" if own_facts else "none found")

    say("Checking open data sources...")
    import former_names as _former_mod
    try:
        former = _former_mod.find(own_pages, hotel)          # 'previously known as Hotel Victoria': searched for too, and connected to the current name
    except Exception as e:  # noqa: BLE001
        steps.failed('Former names', e)
        former = []
    ext = external_check.run_external_check(
        listing_urls, own_facts or None, progress=progress,
        hotel=hotel, city=city, location=location, former_names=[f["name"] for f in former],
        own_phones=[t for p in (own_pages or []) for t in (p.get("tels") or [])]
        + [m.group() for p in (own_pages or []) for m in __import__("insight_content")._PHONE.finditer((p.get("footer_text") or "") + " " + (p.get("text") or "")[:3000])],
    )

    # ---- join the wider discovery that has been running in the background
    if collect_future is None:
        corpus = {"sources": {}, "queries": [], "candidates": [], "raw_results": [],
                  "notes": ["The wider discovery (media coverage, listings, awards, local context) "
                            + ("was switched off for this run" if hotel else "could not run because the hotel's name is not known")
                            + ", so those checks are not assessed."],
                  "tavily_credits": 0, "reads": {}}
    else:
        say("Finishing the wider source checks (media, listings, awards, local context)...")
        try:
            corpus = collect_future.result(timeout=300)
        except Exception as e:  # noqa: BLE001 - the audit must survive a failed wider pass
            steps.failed('Finishing the wider source checks (media, listings, awards, local context) / corpus', e)
            corpus = {"sources": {}, "queries": [], "candidates": [], "raw_results": [],
                      "notes": [f"The wider discovery pass failed ({type(e).__name__}); the "
                                "media, listing and local-context sections are therefore empty."],
                      "tavily_credits": 0, "reads": {}}
        finally:
            collect_ex.shutdown(wait=False, cancel_futures=True)
        if late_position and ((corpus.get("sources") or {}).get("osm_context") or {}).get("status") != "ok":
            say("Looking up the places around the hotel, now its position is known...")
            try:
                corpus.setdefault("sources", {})["osm_context"] = sources.osm_context(location["lat"], location["lon"], hotel)      # it ran without a position
            except Exception as e:  # noqa: BLE001
                steps.failed("Places around the hotel, after finding it on the map", e, quiet=True)
    places_nearby_info = {"calls": 0}

    def _with_places(ctx):
        """Google's nearby hotels added to the map context when it is missing or short (one call, only with a key); never raises."""
        if not places_nearby_key or places_nearby_info["calls"]:
            return ctx, ""
        try:
            import places_nearby
            new, note = places_nearby.supplement_osm(ctx, location.get("lat"), location.get("lon"), hotel, api_key=places_nearby_key)
            places_nearby_info["calls"] = (new or {}).get("places_calls", 0) if new is not ctx else 0
            places_nearby_info["note"] = note
            return new, note
        except Exception as _step_e:  # noqa: BLE001
            steps.failed('Finishing the wider source checks (media, listings, awards, local context)', _step_e)
            return ctx, ""

    _fc_other = None                  # rival sites and cited pages that refuse our reader are read through Firecrawl (a few pages an audit)
    if firecrawl_api_key:
        import firecrawl_reader
        _fc_other = firecrawl_reader.fallback_fetch(guest_questions.fetch_page, firecrawl_api_key)

    # Comparable hotels: read in the background as soon as the map data is in (a few polite fetches of other hotels' pages, capped at 25 seconds), joined when the report is assembled.
    competitors_ex = competitors_future = None
    try:
        _osm_item = ((corpus.get("sources") or {}).get("osm_context") or {})
        _osm_ctx = (_osm_item.get("items") or [None])[0] if _osm_item.get("status") == "ok" else None
        _osm_ctx, places_note = _with_places(_osm_ctx)
        if own_pages and hotel:
            competitors_ex = ThreadPoolExecutor(max_workers=1)
            competitors_future = competitors_ex.submit(competitors_mod.run, _osm_ctx, own_pages, base, hotel, fetch=_fc_other)
    except Exception as e:  # noqa: BLE001
        steps.failed('Competitors from map data', e)
        competitors_future = None
    wd_entity = next((e for e in ext["entities"]
                      if e.get("source") == "Wikidata" and e.get("found") and e.get("match_confident")), None)
    if wd_entity:
        corpus["sources"]["wikidata_detail"] = sources.wikidata_detail(wd_entity["id"])

    # ---- optional integrations. Each is independently skippable, and each
    # is called from exactly here - the single pipeline - not from a
    # separate tab the user has to remember to visit.
    tavily_result = None
    if tavily_check.has_key(tavily_api_key) and hotel:
        say("Checking editorial coverage, OTA presence and social mentions "
            "(Tavily, multi-angle)...")
        try:
            tavily_result = tavily_check.check_coverage(
                hotel, city, api_key=tavily_api_key,
                topics_covered=site.get("topics_covered"), progress=say,
                own_domain=site["meta"].get("base"),
                gemini_reader_key=gemini_reader_key,
                gemini_reader_model=gemini_reader_model,
                prefetched=(corpus["raw_results"] if corpus.get("raw_results") else None),
                read_cache={c["url"]: (" ".join(c["page"].get("windows") or []) or c["page"].get("text_head", ""))
                            for c in corpus.get("candidates", [])
                            if c["read"]["status"] == "read" and c.get("page")},
            )
        except Exception as e:  # noqa: BLE001 - a failed integration must not fail the audit
            steps.failed('Checking editorial coverage, OTA presence and social mentions / tavily_result', e)
            tavily_result = {"configured": True, "error": str(e), "ota_hits": [],
                             "editorial_hits": [], "social_hits": [], "other_hits": []}

    places_result = None
    if places_check.has_key(places_api_key):
        say("Checking Google rating and reviews...")
        try:
            places_result = places_check.check_hotel(
                hotel, city, lat=location.get("lat"), lon=location.get("lon"),
                api_key=places_api_key)
        except Exception as e:  # noqa: BLE001
            steps.failed('Checking Google rating and reviews / places_result', e)
            places_result = {"configured": True, "found": False, "error": str(e)}

    amadeus_result = None
    if amadeus_check.has_credentials(amadeus_api_key, amadeus_api_secret):
        say("Checking Amadeus review sentiment...")
        try:
            amadeus_result = amadeus_check.check_hotel(
                hotel, lat=location.get("lat"), lon=location.get("lon"),
                api_key=amadeus_api_key, api_secret=amadeus_api_secret)
        except Exception as e:  # noqa: BLE001
            steps.failed('Checking Amadeus review sentiment / amadeus_result', e)
            amadeus_result = {"configured": True, "found": False, "error": str(e)}

    # Questions for the markets this hotel actually competes in (airport, district, price level, what it is known for), from facts now in hand.
    niche_ex = niche_future = market_profile = question_plan = benchmark_info = forum_ex = forum_future = None
    engines_ex = engines_future = engines_stop = None
    engines_result = {}
    custom_qs = ai_niche.custom_questions(custom_prompts)          # the person's own prompts, asked exactly as typed
    if anthropic_api_key and hotel and city:
        nqs = []
        try:
            import insight_content as _ic0
            _osm = ((corpus.get("sources") or {}).get("osm_context") or {})
            _osm_ctx = (_osm.get("items") or [None])[0] if _osm.get("status") == "ok" else None
            _osm_ctx, _pn = _with_places(_osm_ctx)
            _site0 = _ic0.Site(own_pages, base, hotel, city) if own_pages else None
            _host1 = urllib.parse.urlparse(base).netloc.lower()
            _feats0 = _ic0.features(_site0) if _site0 else []
            _ints0 = _ic0.intents(_site0) if _site0 else []
            import hotel_class as _hc0
            _classes0 = _hc0.classify(_site0, _feats0, _ints0, _osm_ctx, hotel)["keys"] if _site0 else None      # the kinds of hotel this is decide which markets are worth asking about
            prof = ai_niche.profile(hotel, city, ext["entities"], _osm_ctx, own_pages, _feats0, _ints0, hint=market_hint, domain=_host1, classes=_classes0)
            market_profile = ai_niche.describe(prof)
            # the questions rest on verified facts and a real place the hotel is close to (the hotel's own pages, then Wikipedia's well-known places around its coordinates)
            _anch = anchors_mod.find(own_pages, hotel, city, _osm_ctx, location)
            search_country = search_country or _anch.get("country")
            try:
                _qclient = ai_sample._make_client(anthropic_api_key, timeout=60.0)
            except Exception as _step_e:  # noqa: BLE001
                steps.failed('Checking Amadeus review sentiment / _qclient', _step_e)
                _qclient = None
            built = ai_questions.build(prof, hotel, city, _anch["anchors"], client=_qclient, base_repeats=(anthropic_repeats or _depth_mod.limits(ai_depth)["repeats"]), features=_feats0, benchmark=benchmark, depth=ai_depth, pages=own_pages, profile=profile,
                                       location=location, fetch=netguard.get)
            nqs = built["questions"]
            benchmark_info = {"prompts": built["benchmark_prompts"] or [{"text": b["text"], "angle": b.get("angle"), "why": b.get("why")} for b in (benchmark or [])], "reused": built["benchmark_reused"],
                              "retired": built.get("benchmark_retired") or []}
            question_plan = {"facts": built["facts"], "rejected": built["rejected"], "anchors": _anch["anchors"][:6], "coords_source": _anch["coords_source"], "cost_usd": built["cost_usd"],
                             "questions": [{"id": q["id"], "text": q["text"], "angle": q.get("angle"), "why": q.get("why"), "priority": q.get("priority"), "style": q.get("style"), "kind": q.get("kind"),
                                            "source": q.get("source")} for q in built["questions"]]}
            market_profile["anchors"] = _anch["anchors"][:4]
        except Exception as _pe:  # noqa: BLE001 - the planner is an extra; the standard questions still run
            steps.failed('Checking Amadeus review sentiment / _qclient', _pe)
            nqs = []
            question_plan = {"error": f"{type(_pe).__name__}: {str(_pe)[:200]}", "questions": [], "facts": [], "anchors": []}
            say(f"Planning the hotel's questions's tracked prompts are still asked.")
        # the hotel's tracked prompts (confirmed, or frozen at its first check) are asked in EVERY check, whatever happened above: without them the trend means nothing
        _retired = {r.get("text") for r in ((benchmark_info or {}).get("retired") or [])}
        benchmark = [b for b in (benchmark or []) if b.get("text") not in _retired]       # a prompt retired above is never put back (Brooks: 'near Victoria Park have parking' was asked again)
        if benchmark and not any(q.get("source") in ("benchmark", "benchmark_new") for q in nqs):
            _rp = min(_depth_mod.limits(ai_depth)["core_cap"], (anthropic_repeats or _depth_mod.limits(ai_depth)["repeats"]) + _depth_mod.limits(ai_depth)["core_extra"])
            _fr = [{"id": f"niche_bench{i}", "kind": "niche", "angle": b.get("angle") or "Tracked prompt", "text": b["text"], "priority": "core", "source": "benchmark", "repeats": _rp,
                    "why": "One of the hotel's tracked prompts, asked in every check so the results can be compared over time."} for i, b in enumerate(benchmark[:ai_questions.TRACKED_MAX], 1) if b.get("text")]
            nqs = _fr + nqs
            if question_plan is not None:
                question_plan["questions"] = [{"id": q["id"], "text": q["text"], "angle": q.get("angle"), "why": q.get("why"), "priority": q.get("priority"), "kind": q.get("kind"), "source": q.get("source")} for q in _fr] + list(question_plan.get("questions") or [])
            benchmark_info = benchmark_info or {"prompts": [{"text": b["text"], "angle": b.get("angle"), "why": b.get("why")} for b in benchmark], "reused": True}
        nqs = nqs + custom_qs
        # Open community conversations (Reddit and similar) where travellers ask for hotels like this one's; searched while the questions are being asked
        try:
            _core_q = [q["text"] for q in nqs if q.get("priority") == "core" and q.get("kind") == "niche"][:6]
            _fprof, _fanch = (locals().get("prof") or {}), ((question_plan or {}).get("anchors") or [])
            forum_ex = ThreadPoolExecutor(max_workers=1)
            forum_future = forum_ex.submit(forums_mod.run, hotel, city, _core_q, forums_mod.place_terms(hotel, city, _fprof, _fanch, profile=profile), topics=forums_mod.topics(hotel, city, _fprof, _fanch, profile=profile), api_key=anthropic_api_key, model=anthropic_model)
        except Exception as _step_e:  # noqa: BLE001
            steps.failed('Planning the questions / _core_q', _step_e)
            forum_future = None
        if nqs and hotel and city:
            # the other assistants (ChatGPT, Gemini, Perplexity) are asked the hotel's tracked prompts while Claude answers its own round (assistants.py; only those with a key)
            try:
                import assistants
                _tracked = [q for q in nqs if q.get("source") == "benchmark"] or [q for q in nqs if q.get("priority") == "core"]
                _seen_t, _tp = set(), []
                for q in _tracked:
                    k_ = q.get("qid") or q.get("id")
                    if k_ not in _seen_t and q.get("text"):
                        _seen_t.add(k_)
                        _tp.append({"id": k_, "text": q["text"], "kind": q.get("kind") or "niche", "angle": q.get("angle")})
                if _tp and any(assistants.key_for(e) for e in assistants.ENGINES):
                    engines_stop = threading.Event()
                    engines_ex = ThreadPoolExecutor(max_workers=1)
                    _host1 = urllib.parse.urlparse(base).netloc.lower()
                    engines_future = engines_ex.submit(assistants.run_all, _tp, hotel, city, own_domain=_host1[4:] if _host1.startswith("www.") else _host1, country=search_country,
                                                       stop_event=engines_stop, progress=say)
            except Exception as e:  # noqa: BLE001
                steps.failed("Asking the other AI assistants", e)
        if nqs:
            try:
                _host0 = urllib.parse.urlparse(base).netloc.lower()
                niche_ex = ThreadPoolExecutor(max_workers=1)
                niche_stop = threading.Event()
                niche_future = niche_ex.submit(ai_sample.run_extra, hotel, city, nqs, stop_event=niche_stop, api_key=anthropic_api_key, model=anthropic_model, budget_usd=_depth_mod.niche_budget(ai_depth, sum(1 for q in nqs if q.get("priority") == "core")), workers=_depth_mod.limits(ai_depth)["workers"], country=search_country,
                                               own_domain=_host0[4:] if _host0.startswith("www.") else _host0, **({} if anthropic_repeats is None else {"repeats": max(1, min(5, int(anthropic_repeats)))}))
            except Exception as _step_e:  # noqa: BLE001
                steps.failed('Planning the questions / _host0', _step_e)
                niche_future = None

    ai_result = review_result = None
    listing_result = {"source": listing_lookup.SOURCE, "status": "not_configured", "reason": "", "pages": [], "cost_usd": 0.0}
    reddit_lookup = None
    if ai_future is None:
        ai_result = ai_sample.run(hotel, city, api_key=anthropic_api_key)      # returns the 'not configured / need a name and town' envelope
        review_result = review_replies.run(hotel, city, api_key=anthropic_api_key)
    if ai_future is not None:
        say("Collecting the sampled AI answers...")
        try:
            ai_result = ai_future.result(timeout=600)
        except Exception as e:  # noqa: BLE001 - an extra; the audit stands without it
            steps.failed('Collecting the sampled AI answers / ai_result', e)
            ai_result = {"source": ai_sample.SOURCE, "status": "unavailable", "items": [], "access": ai_sample.ACCESS,
                         "reason": f"The sampled AI answers did not finish in time ({type(e).__name__}), so they were not assessed."}
        try:
            review_result = rv_future.result(timeout=120)
        except Exception as e:  # noqa: BLE001
            steps.failed('Collecting the sampled AI answers / review_result', e)
            review_result = {"source": review_replies.SOURCE, "status": "unavailable", "items": [], "access": review_replies.ACCESS,
                             "reason": f"The reviews snapshot did not finish in time ({type(e).__name__}), so it was not assessed."}
        try:
            listing_result = ll_future.result(timeout=120)
        except Exception as e:  # noqa: BLE001
            steps.failed('Collecting the sampled AI answers / listing_result', e)
            listing_result = {"source": listing_lookup.SOURCE, "status": "unavailable", "reason": f"The listing lookup did not finish in time ({type(e).__name__}).", "pages": [], "cost_usd": 0.0}
        try:
            reddit_lookup = rd_future.result(timeout=120)
        except Exception as e:  # noqa: BLE001
            steps.failed('Collecting the sampled AI answers / reddit_lookup', e)
            reddit_lookup = {"source": reddit_check.SOURCE, "status": "unavailable", "reason": f"The Reddit search did not finish in time ({type(e).__name__}).", "pages": [], "passages": [], "cost_usd": 0.0}
        finally:
            ai_ex.shutdown(wait=False, cancel_futures=True)
    try:
        reddit_result = reddit_check.build(reddit_lookup, ai_result, hotel, city)
    except Exception as _step_e:  # noqa: BLE001 - an extra; the audit stands without it
        steps.failed('Collecting the sampled AI answers / reddit_result', _step_e)
        reddit_result = None
    # Listings found by the AI web searches (this lookup, the sampled answers and the review pages) join the candidates the footprint is built from, but only where the
    # page is on that platform's domain and its address or title names the hotel. They were not opened.
    try:
        _pool = list(listing_result.get("pages") or [])
        for _it in (ai_result or {}).get("items") or []:
            _pool += [{"url": pg["url"], "title": pg.get("title", "")} for pg in _it.get("pages") or []]
        _pool += [{"url": pl["url"], "title": pl.get("platform", "")} for pl in ((review_result or {}).get("platforms") or []) if pl.get("url")]
        _hits = listing_lookup.hits_from_pages(_pool, hotel, city)
        listing_result["social"] = listing_lookup.social_from_pages(_pool, hotel, city)
        _known = {c["key"] for c in corpus.get("candidates", [])}
        _new = [c for c in listing_lookup.as_candidates(_hits, base) if c["key"] not in _known]
        corpus.setdefault("candidates", []).extend(_new)
        listing_result["added"] = [{"platform": h["platform"], "url": h["url"]} for h in _hits]
        if isinstance(tavily_result, dict) and tavily_result.get("configured") and not tavily_result.get("error"):      # the OTA category counts them too
            _have = {h.get("platform") for h in tavily_result.get("ota_hits") or []}
            for h in _hits:
                _label = tavily_check._classify_domain(h["url"])[1]
                if _label not in _have:
                    _have.add(_label)
                    tavily_result.setdefault("ota_hits", []).append({"platform": _label, "url": h["url"], "title": h.get("title", ""),
                                                                      "snippet": "found by an AI web search; the page was not opened"})
    except Exception as e:  # noqa: BLE001 - an extra; the footprint stands without it
        steps.failed("listings found by AI search", e)

    ai_visibility_cat, ai_visibility_raw = None, None
    if include_ai_visibility and gemini_api_key:
        say("Checking AI visibility (spends Gemini quota)...")
        try:
            ai_visibility_raw = _run_ai_visibility_subset(
                hotel, city, website, api_key=gemini_api_key,
                model=gemini_model, limit=ai_visibility_limit, progress=progress)
            ai_visibility_cat = scoring.score_ai_visibility(ai_visibility_raw)
        except Exception as e:  # noqa: BLE001
            steps.failed('Checking AI visibility (spends Gemini quota) / ai_visibility_raw', e)
            ai_visibility_cat = scoring._not_assessed(
                "ai_visibility", f"Configured but the check failed: {e}",
                "Check the Gemini API key and that billing is enabled.")

    if engines_future is not None:
        try:
            engines_result = engines_future.result(timeout=900)
        except Exception as e:  # noqa: BLE001 - Claude's sample stands without them, and the report says so
            steps.failed("Asking the other AI assistants", e)
            if engines_stop is not None:
                engines_stop.set()
        finally:
            engines_ex.shutdown(wait=False, cancel_futures=True)
    round2_error = ""
    if niche_future is not None:
        try:
            ai_result = ai_sample.merge(ai_result, niche_future.result(timeout=900))      # the hotel's tracked prompts: worth waiting for (a check runs in the background)
        except Exception as e:  # noqa: BLE001 - the standard sample stands without the niche round, and the report says so
            steps.failed('Checking AI visibility (spends Gemini quota) / ai_result', e)
            round2_error = f"The round with the hotel's own prompts did not finish ({type(e).__name__})."
            niche_stop.set()                                     # stop its remaining calls: they would only spend after the report is saved
        finally:
            niche_ex.shutdown(wait=False, cancel_futures=True)
        if round2_error and isinstance(ai_result, dict):
            ai_result["round2_error"] = round2_error
    if market_profile and isinstance(ai_result, dict) and ai_result.get("status") == "ok":
        ai_result["market"] = market_profile                         # how the hotel's market was read, shown beside the answers
    forums_result = None
    if forum_future is not None:
        try:
            forums_result = forum_future.result(timeout=150)
        except Exception as e:  # noqa: BLE001 - an extra
            steps.failed('Checking AI visibility (spends Gemini quota) / forums_result', e)
            forums_result = {"source": forums_mod.SOURCE, "status": "unavailable", "reason": f"The forum search did not finish ({type(e).__name__}).", "opportunities": [], "closed": [], "searches": 0, "cost_usd": 0.0, "forums": []}
        finally:
            forum_ex.shutdown(wait=False, cancel_futures=True)
    citations_result = None
    if isinstance(ai_result, dict) and ai_result.get("status") == "ok":
        try:
            _hh = urllib.parse.urlparse(base).netloc.lower()
            _hh = _hh[4:] if _hh.startswith("www.") else _hh
            _brand = (_hh,) if site["meta"].get("scope") else ()
            citations_result = citations_mod.ranking(ai_result["items"], _hh, _brand)
            citations_result["direct_findings"] = citations_mod.direct_findings(ai_result["items"], own_pages, _hh, _brand)
            if forums_result and forums_result.get("opportunities") is not None:
                _cited = {citations_mod._dom(p["url"]) + urllib.parse.urlparse(p["url"]).path for i in ai_result["items"] for p in (i.get("pages") or []) if p.get("cited") and p.get("url")}
                for o in forums_result["opportunities"] + forums_result.get("closed", []):
                    o["cited_by_ai"] = (citations_mod._dom(o["url"]) + urllib.parse.urlparse(o["url"]).path) in _cited
        except Exception as _step_e:  # noqa: BLE001 - an extra; the sample itself still shows
            steps.failed('Checking AI visibility (spends Gemini quota) / _hh', _step_e)
            citations_result = None
    if ai_visibility_cat is None:
        ai_visibility_cat = scoring.score_ai_sample(ai_result)       # one model's sample: scored, but always labelled low-evidence
    try:
        web = web_future.result(timeout=120)
    except Exception as e:  # noqa: BLE001 - these are extras; the audit stands without them
        steps.failed('Checking AI visibility (spends Gemini quota) / web', e)
        web = {"version": 1, "ai_policy": web_signals.ai_policy(site.get("robots")),
               "llms_txt": {"status": "unavailable", "present": None, "reason": f"Not completed ({type(e).__name__})."},
               "commoncrawl": {"source": "Common Crawl", "status": "unavailable", "items": [],
                               "reason": f"Not completed in time ({type(e).__name__}), so this was not assessed."},
               "pagespeed": {"source": "PageSpeed Insights", "status": "unavailable", "items": [],
                             "reason": f"Not completed in time ({type(e).__name__}), so this was not assessed."}}
    finally:
        web_ex.shutdown(wait=False, cancel_futures=True)
    findings = build_findings(site, ext["entities"], ext["consistency"], discovery,
                              location=location)

    scorecard = scoring.build_scorecard(
        site, ext["entities"], ext["consistency"], location, discovery,
        ai_visibility=ai_visibility_cat, tavily_result=tavily_result,
        places_result=places_result, amadeus_result=amadeus_result,
        guest_result=guest, web=web,
        social_found=([x["platform"] for x in listing_result.get("social", [])] if listing_result.get("status") == "ok" else None),
    )

    # Hotel types suggested by the site's own pages (free - no search needed);
    # used to tailor the manual AI-check prompts.
    segments = [tavily_check.SEGMENTS[s][0]
                for s in tavily_check.detect_segments(site.get("topics_covered"))]

    # Turn the ranked list into an action plan: who, where, an example - and
    # the three to do first. Built from facts the audit actually read.
    recs_all = fixes.enrich(
        scoring.all_recommendations(scorecard),
        {"base": base, "hotel": hotel, "location": location, "guest": guest,
         "discovery": discovery, "entities": ext["entities"], "site": site,
         "tavily": tavily_result},
    )
    top_fixes = fixes.top_fixes(recs_all)

    say("Analysing coverage, traveller fit and recommendations...")
    try:
        if not hotel:        # with no name nothing was searched, so there is no outside evidence to analyse (and none to claim is missing)
            raise _NoName()
        intel_result = intel.build_intel(
            hotel=hotel, city=city, base_url=base, location=location, site=site,
            discovery=discovery, guest=guest, own_pages=own_pages, entities=ext["entities"],
            tavily_result=tavily_result, corpus=corpus, own_facts=own_facts,
            site_links=_page_links(pages_html[0], home_url) if pages_html else [],
            scorecard_recs=recs_all)
    except _NoName:
        intel_result = None
    except Exception as e:  # noqa: BLE001
        steps.failed('Analysing coverage, traveller fit and recommendations / intel_result', e)
        intel_result = {"error": f"{type(e).__name__}: {e}"}

    # What each travel site shows (from quoted passages in public search results) against the hotel's own site, and any listing still carrying a former name.
    ta_result = None
    try:
        _former = ((intel_result or {}).get("identity") or {}).get("former_names") if isinstance(intel_result, dict) and "error" not in intel_result else []
        import tripadvisor_check
        ta_result = None
        _extra = None
        if tripadvisor_api_key and hotel:
            ta_result = tripadvisor_check.lookup(hotel, city, (location or {}).get("lat"), (location or {}).get("lon"), api_key=tripadvisor_api_key,
                                                 site=listing_facts.site_facts(guest, own_pages, hotel, {**(location or {}), "region": city}),
                                                 site_states=__import__("review_pack").site_states_from(guest))
            _extra = tripadvisor_check.as_listing(ta_result) or None
        listing_checks = listing_facts.build(listing_result, hotel, guest, own_pages, _former, {**(location or {}), "region": city}, extra=_extra)
        if listing_checks is not None and ta_result:
            listing_checks["tripadvisor"] = ta_result
    except Exception as _step_e:  # noqa: BLE001 - an extra; the audit stands without it
        steps.failed('Analysing coverage, traveller fit and recommendations / _former', _step_e)
        listing_checks = None

    # Booking readiness (a booking link, its destination, broken links) and external presence (is the right hotel identified on each outside source, do they agree with the website).
    # Both reuse what was collected; the booking check makes at most ten polite requests, in parallel.
    try:
        booking_result = booking_future.result(timeout=45)
    except Exception as e:  # noqa: BLE001 - an extra; the audit stands without it
        steps.failed('Analysing coverage, traveller fit and recommendations / booking_result', e)
        booking_result = {"status": "unavailable", "reason": f"The booking check did not finish ({type(e).__name__}).", "checks": [], "candidates": []}
    finally:
        booking_ex.shutdown(wait=False, cancel_futures=True)
    try:
        _ie = intel_result if isinstance(intel_result, dict) and "error" not in intel_result else {}
        external_result = external_presence.build((_ie.get("identity") or {}).get("footprint"), ext["entities"], ext["consistency"], listing_checks, _ie.get("media"), hotel, city, base,
                                                  [{"url": l["url"], "domain": evidence.domain_of(l["url"])} for l in _home_links],
                                                  own={"postcode": location.get("postcode"), "lat": location.get("lat"), "lon": location.get("lon"),
                                                       "phone": (guest.get("own_facts_node") or {}).get("telephone") or (((guest.get("fact_sheet") or {}) if isinstance(guest.get("fact_sheet"), dict) else {}).get("telephone")),
                                                       "phones": [t for p in (own_pages or []) for t in (p.get("tels") or [])]
                                                       + [m.group() for p in (own_pages or []) for m in __import__("insight_content")._PHONE.finditer((p.get("footer_text") or "") + " " + (p.get("text") or "")[:3000])]})
    except Exception as _step_e:  # noqa: BLE001
        steps.failed('Analysing coverage, traveller fit and recommendations / _ie', _step_e)
        external_result = None

    # What the sampled answers mean: who is recommended instead, which sources were used, is it right, why the hotel may not be named.
    ai_insight_result = None
    if ai_result and ai_result.get("status") == "ok" and anthropic_api_key:
        say("Analysing what the assistant said...")
        try:
            import insight_content as _ic
            strong = [r["label"] for r in _ic.intents(_ic.Site(own_pages, base, hotel, city)) if r["level"] == "strong"] if own_pages else []
            footprint = ((intel_result or {}).get("identity") or {}).get("footprint") if isinstance(intel_result, dict) and "error" not in intel_result else None
            host = urllib.parse.urlparse(base).netloc.lower()
            host = host[4:] if host.startswith("www.") else host
            ai_insight_result = ai_insights.run(
                ai_result, {"hotel": hotel, "city": city, "guest": guest, "entities": ext["entities"], "footprint": footprint, "snapshot": review_result,
                            "strong_intents": strong, "own_domain": host, "brand_domains": (host,) if site["meta"].get("scope") else ()},
                api_key=anthropic_api_key, model=anthropic_model)
        except Exception as e:  # noqa: BLE001 - an extra; the sample itself still shows
            steps.failed('Analysing what the assistant said / strong', e)
            ai_insight_result = {"source": ai_insights.SOURCE, "status": "unavailable", "reason": f"The analysis of the answers failed ({type(e).__name__}).", "cost_usd": 0.0}

    # one count for the whole report: an answer the reading shows naming the hotel is marked as naming it, and the sample's figures are recounted from those marks
    if isinstance(ai_insight_result, dict) and ai_insight_result.get("extracted_answers"):
        try:
            ai_insights.reconcile(ai_result, ai_insight_result["extracted_answers"], hotel)
            import report_model
            report_model.apply({"ai_sample": ai_result, "ai_insights": ai_insight_result})      # the scoreboard and ranking line for the hotel carry the one count from here on
        except Exception as _step_e:  # noqa: BLE001
            steps.failed('Analysing what the assistant said / ai_insights.reconcile', _step_e)
            pass

    # What the answers say about the hotel itself (no parking, has a pool, closed for refurbishment), checked against its own website
    if isinstance(ai_insight_result, dict) and ai_insight_result.get("status") in ("ok", "partial"):
        say("Checking what the assistant said about the hotel against its website...")
        try:
            import ai_facts
            _stars = ((locals().get("prof") or {}).get("stars"))
            fc = ai_facts.run(ai_result, hotel, city, own_pages, base, site_stars=float(_stars) if isinstance(_stars, (int, float)) else None, api_key=anthropic_api_key, model=anthropic_model)
            ai_insight_result["facts_check"] = fc
            ai_insight_result["cost_usd"] = round((ai_insight_result.get("cost_usd") or 0) + (fc.get("cost_usd") or 0), 5)
        except Exception as _step_e:  # noqa: BLE001 - an extra
            steps.failed('Checking what the assistant said about the hotel against its website / _stars', _step_e)
            pass

    # Who the assistant named instead of the hotel, which pages it cited, and what the evidence shows about the difference: the answers already collected, plus a few polite page reads.
    ai_gap_result = None
    if isinstance(ai_insight_result, dict) and ai_insight_result.get("extracted_answers"):
        say("Looking at who the assistant recommended instead, and the pages it cited...")
        try:
            _o = ((corpus.get("sources") or {}).get("osm_context") or {})
            _octx = (_o.get("items") or [None])[0] if _o.get("status") == "ok" else None
            _h = urllib.parse.urlparse(base).netloc.lower()
            _h = _h[4:] if _h.startswith("www.") else _h
            ai_gap_result = ai_gap.run(ai_result, ai_insight_result, {"hotel": hotel, "city": city, "own_domain": _h, "brand_domains": (_h,) if site["meta"].get("scope") else (), "own_pages": own_pages,
                                                                      "base": base, "osm_ctx": _octx, "location": location, "hotel_tier": ((market_profile or {}).get("tier") or {}).get("key")}, api_key=anthropic_api_key, model=anthropic_model, fetch=_fc_other)
        except Exception as e:  # noqa: BLE001 - an extra; the sample and its analysis still show
            steps.failed('Looking at who the assistant recommended instead, and the pages it cited / _o', e)
            ai_gap_result = {"source": ai_gap.SOURCE, "status": "unavailable", "reason": f"The comparison with the hotels named instead did not finish ({type(e).__name__}).", "markets": [], "gaps": [],
                             "articles": [], "opportunities": [], "rivals": [], "comparison": None, "observations": {}, "limits": ai_gap.LIMITS, "cost_usd": 0.0}

    # The consultant layer reads pages the crawl already fetched - no further requests (except the few polite ones of the competitor look, below).
    say("Working out what AI systems can and can't understand about the hotel...")
    competitors_result = None
    try:
        osm_item = ((corpus.get("sources") or {}).get("osm_context") or {})
        osm_ctx = (osm_item.get("items") or [None])[0] if osm_item.get("status") == "ok" else None
        if competitors_future is not None:
            try:
                competitors_result = competitors_future.result(timeout=40)
            except Exception as e:  # noqa: BLE001 - an extra; the audit stands without it
                steps.failed('Working out what AI systems can read / competitors_result', e)
                competitors_result = {"status": "unavailable", "reason": f"The competitor look did not finish ({type(e).__name__}).", "competitors": [], "comparisons": []}
            finally:
                competitors_ex.shutdown(wait=False, cancel_futures=True)
        consult_result = consultant.analyse(
            own_pages=own_pages, pages_meta=guest.get("pages_meta", []), base=base, hotel=hotel, city=city,
            location=location, guest=guest, site=site, entities=ext["entities"], intel=intel_result,
            osm_ctx=osm_ctx, web=web, ai=ai_result, reviews=review_result, ai_insights=ai_insight_result, ai_gap=ai_gap_result, citations=citations_result, forums=forums_result, listing_checks=listing_checks, reddit=reddit_result, booking=booking_result, external=external_result, competitors=competitors_result, text_only=bool(guest.get("read_via")) and not guest.get("html_read"), fc_html=bool(guest.get("html_read")),
            jsonld_example=fixes.hotel_jsonld({"base": base, "hotel": hotel, "location": location, "guest": guest,
                                               "discovery": discovery, "entities": ext["entities"], "site": site,
                                               "tavily": tavily_result}))
    except Exception as e:  # noqa: BLE001 - the audit must survive a failed analysis
        steps.failed('Working out what AI systems can read / competitors_result', e)
        consult_result = {"error": f"{type(e).__name__}: {e}"}
    try:
        _fr = _former_mod.recommendation(former, hotel, ext["entities"])
        if _fr and isinstance(consult_result.get("recommendations"), list):
            consult_result["recommendations"].insert(0, _fr)
            consult_result["former_names"] = former
    except Exception as _step_e:  # noqa: BLE001
        steps.failed('Working out what AI systems can read / _fr', _step_e)
        pass
    try:       # the outside sources were read after the scorecard was made: a hotel found under several names, or contradicted by a listing, cannot keep a perfect consistency score
        _recs = {r.get("id"): r for r in (consult_result.get("recommendations") or [])}
        _names = 2 if "I1" in _recs else 0
        _facts = 0
        if "I2" in _recs:
            import re as _re_i2
            _m = _re_i2.match(r"(\d+)", _recs["I2"].get("title", ""))
            _facts = int(_m.group(1)) if _m else 1
        scoring.apply_identity(scorecard, _names, _facts)
        scoring.apply_listings(scorecard, listing_checks)
    except Exception as _step_e:  # noqa: BLE001 - an adjustment; the scorecard stands as it was
        steps.failed('Working out what AI systems can read / _fr', _step_e)
        pass

    result = {
        "meta": {
            "hotel": hotel,
            "city": city,
            "ai_depth": ai_depth,                 # how thorough the AI test was (deep: a hotel's baseline; standard: the weekly checks)
            "profile": (__import__("hotel_profile").for_report(profile) if profile else None),        # the profile the hotel confirmed, as this check used it
            "website": website,
            "base": base,
            "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "hotel_name_source": ("provided by you, spelled as the site spells it" if name_respelled else "provided by you") if hotel_given
                                 else ("guessed from the web address (the site could not be read)" if name_from_address
                                       else ("inferred from the site's own markup" if hotel else "could not be determined")),
            "location": location,
            "keys_used": {
                "tavily": bool(tavily_result and tavily_result.get("configured")),
                "google_places": bool(places_result and places_result.get("configured")),
                "amadeus": bool(amadeus_result and amadeus_result.get("configured")),
                "ai_visibility": bool(ai_visibility_cat and ai_visibility_cat["assessed"]),
                "pagespeed": web.get("pagespeed", {}).get("status") == "ok",
            },
        },
        "score": scorecard["overall"],
        "coverage_pct": scorecard["coverage_pct"],
        "scorecard": scorecard,
        "recommendations": recs_all,
        "top_fixes": top_fixes,
        "segments": segments,
        "legacy_score": score(findings, site),
        "findings": findings,
        "site": site,
        "discovery": discovery,
        "entities": ext["entities"],
        "consistency": ext["consistency"],
        "blocked_sources": ext["blocked_sources"],
        "reputation": ext["reputation"],
        "guest_questions": guest,
        "fact_profile": fact_prof,
        "own_facts_source": own_facts_source,
        "intel": intel_result,
        "consultant": consult_result,
        "web_signals": web,
        "ai_sample": ai_result,
        "ai_engines": engines_result,             # ChatGPT, Gemini, Perplexity on the tracked prompts (assistants.py); empty when none has a key
        "market_profile": market_profile,
        "question_plan": question_plan,
        "firecrawl_other": {"credits": (_fc_other.state["credits"] if _fc_other else 0), "pages": (_fc_other.state["used"] if _fc_other else [])},
        "tripadvisor_calls": (ta_result or {}).get("calls", 0),
        "places_nearby": {"calls": places_nearby_info.get("calls", 0), "note": places_nearby_info.get("note", "")} if places_nearby_key else None,
        "benchmark": benchmark_info,
        "custom_prompts": [q["text"] for q in custom_qs],
        "ai_insights": ai_insight_result,
        "ai_gap": ai_gap_result,
        "citations": citations_result,
        "forums": forums_result,
        "review_snapshot": review_result,
        "listing_lookup": {k: v for k, v in listing_result.items() if k not in ("pages", "passages")},
        "listing_checks": listing_checks,
        "reddit": reddit_result,
        "booking": booking_result,
        "external": external_result,
        "competitors": competitors_result,
        "tavily_result": tavily_result,
        "places_result": places_result,
        "amadeus_result": amadeus_result,
        "ai_visibility_raw": ai_visibility_raw,
    }
    try:
        result["step_errors"] = steps.collected()
        import report_model
        report_model.apply(result)                  # rep["model"]: the one source of truth for the figures every screen and PDF shows
        import report_gate
        result = report_gate.check(result)          # one pass over the whole report for contradictions and misleading items; it only downgrades, removes or annotates
    except Exception as _step_e:  # noqa: BLE001 - the report must never fail because of its own check
        steps.failed('Report checks', _step_e)
        pass
    return headline.attach(result)


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
