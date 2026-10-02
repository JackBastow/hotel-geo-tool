#!/usr/bin/env python3
"""
Tavily search integration - covers Editorial & Blogs, OTA presence, and
independently-discovered Social mentions.

Why Tavily and not scraping OTA sites directly: TripAdvisor and Booking.com's
Terms of Use explicitly prohibit automated collection ("use... any robot,
spider... to access, retrieve, copy, scrape, aggregate, collect... except as
expressly permitted... in writing" - TripAdvisor ToU, verified 2026-09).
Reading Tavily's search index instead means we never touch those sites
directly - we read what a search engine's index already says about them,
through an API designed to be queried this way.

MULTI-ANGLE, SEGMENT-AWARE SEARCH, NOT ONE QUERY
-------------------------------------------------
An earlier version of this module ran a single generic search and just
sorted the domains it got back into buckets - real, but shallow: it never
looked for what coverage actually matters for THIS hotel, and never read
what anything found actually says.

This version:
  1. Detects which "segments" the hotel plausibly belongs to (wedding venue,
     business/conference hotel, family hotel, pet-friendly, spa/wellness)
     from signals site_check.py already extracted for free - which topic
     pages the hotel's OWN site publishes. No new cost to compute this.
  2. Runs a GENERIC query set every time (reputation, press, social
     mentions) plus SEGMENT queries only for the segments actually detected
     - a wedding venue gets checked against bridal/wedding press, a business
     hotel against business-travel coverage, not both regardless of fit.
  3. For the strongest non-OTA, non-directory hits, actually FETCHES and
     READS the page (not just the search snippet) to judge whether it
     genuinely is about this hotel and how substantial the coverage is,
     rather than counting a domain appearing as equivalent to real coverage.

Cost: this runs several searches per audit instead of one - roughly 4-8
depending on how many segments are detected, each one Tavily search-API
call. Honestly: that trades "free audits per month" for "real depth per
audit" - see store.py's per-service quota tracking, which this still
respects exactly as before.

No key -> every function returns a clearly-marked "not configured" result.
Nothing here ever raises for a missing key; the caller decides what to do.

Usage:
  export TAVILY_API_KEY=...
  python tavily_check.py --hotel "Brooklands Hotel" --city "Weybridge, Surrey"
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import time

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - degrade gracefully if not installed
    BeautifulSoup = None

import gemini_reader

API_URL = "https://api.tavily.com/search"
READ_BUDGET_S = 90  # total time allowed for reading articles in one audit

UA = ("Mozilla/5.0 (compatible; HotelDiscoverabilityAudit/1.0; "
     "hotel AI-visibility audit; contact: site owner)")

# Known OTA / travel-platform domains, for classifying search results. Not
# exhaustive - anything not matched falls into "other".
OTA_DOMAINS = {
    "booking.com": "Booking.com", "expedia.": "Expedia", "expedia.co": "Expedia",
    "tripadvisor.": "TripAdvisor", "hotels.com": "Hotels.com",
    "agoda.com": "Agoda", "trivago.": "Trivago", "kayak.": "Kayak",
    "google.com/travel": "Google Hotels", "google.com/maps": "Google Maps",
    "lastminute.com": "lastminute.com", "laterooms.com": "LateRooms",
    "hotwire.com": "Hotwire", "priceline.com": "Priceline",
    "orbitz.com": "Orbitz", "travelocity.com": "Travelocity",
}

EDITORIAL_HINTS = [
    "cntraveler.com", "condenasttraveller.com", "telegraph.co.uk/travel",
    "theguardian.com/travel", "timeout.com", "independent.co.uk/travel",
    "standard.co.uk/travel", "forbes.com/sites", "travelandleisure.com",
    "lonelyplanet.com", "roughguides.com", "nationalgeographic.com/travel",
    "suitcasemag.com", "wallpaper.com", "harpersbazaar.com",
    "visitengland.com", "visitsurrey.com", "visitbritain.com",
    ".gov.uk/tourism", "eater.com", "bookatable.", "squaremeal.co.uk",
    "brides.com", "hitched.co.uk", "bridebook.co.uk",  # wedding press
    "businesstraveller.com", "meetingsandevents.", "conference-news.",  # business press
]

DIRECTORY_HINTS = ["yell.com", "yelp.", "wikipedia.org", "foursquare.com",
                   "wikidata.org", "openstreetmap.org"]

SOCIAL_DOMAINS = {
    "instagram.com": "Instagram", "tiktok.com": "TikTok",
    "facebook.com": "Facebook", "twitter.com": "X / Twitter",
    "x.com": "X / Twitter", "youtube.com": "YouTube", "reddit.com": "Reddit",
    "pinterest.": "Pinterest",
}

# --------------------------------------------------------- segment detection

# Maps site_check.py's TOPIC_SIGNALS keys to a human label and the extra
# search angle worth running for a hotel that publishes that kind of page.
# This is the whole point of "not one generic search" - what's worth
# checking for a wedding venue is not what's worth checking for a business
# hotel, and we can tell the difference for free from the hotel's own site.
SEGMENTS = {
    "weddings": ("wedding venue", '"{hotel}" wedding blog OR bridal feature OR real wedding'),
    "meetings_events": ("business/conference hotel",
                        '"{hotel}" business travel review OR conference venue feature'),
    "families": ("family hotel", '"{hotel}" family hotel blog review'),
    "pets": ("pet-friendly hotel", '"{hotel}" dog friendly hotel blog'),
    "spa": ("spa/wellness hotel", '"{hotel}" spa review OR wellness retreat feature'),
}

GENERIC_QUERY_TEMPLATES = [
    '"{hotel}" {city} hotel reviews',
    '"{hotel}" {city} news OR award OR "featured in"',
    '"{hotel}" instagram OR tiktok OR facebook review',
]


def detect_segments(topics_covered):
    """
    Which SEGMENTS keys this hotel's own site suggests it belongs to, from
    the topic pages site_check.py already found - free, no extra request.
    """
    covered = set(topics_covered or [])
    return [k for k in SEGMENTS if k in covered]


class TavilyError(RuntimeError):
    pass


def has_key(api_key=None):
    return bool(api_key or os.environ.get("TAVILY_API_KEY"))


def _client_key(api_key=None):
    return api_key or os.environ.get("TAVILY_API_KEY")


def _search(query, api_key=None, max_results=10, timeout=30):
    key = _client_key(api_key)
    if not key:
        raise TavilyError("no Tavily API key configured")
    try:
        r = requests.post(API_URL, json={
            "api_key": key, "query": query, "search_depth": "basic",
            "max_results": max_results, "include_answer": False,
        }, timeout=timeout)
    except requests.RequestException as e:
        raise TavilyError(f"request failed: {e}")
    if r.status_code == 401:
        raise TavilyError("HTTP 401 - API key rejected")
    if r.status_code in (429, 432):
        raise TavilyError(f"HTTP {r.status_code} - rate limited or plan quota used up")
    if r.status_code != 200:
        raise TavilyError(f"HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        raise TavilyError("response was not JSON")


def _classify_domain(url):
    low = url.lower()
    for pat, label in OTA_DOMAINS.items():
        if pat in low:
            return "ota", label
    for pat, label in SOCIAL_DOMAINS.items():
        if pat in low:
            return "social", label
    for pat in EDITORIAL_HINTS:
        if pat in low:
            return "editorial", urllib.parse.urlparse(url).netloc
    for pat in DIRECTORY_HINTS:
        if pat in low:
            return "directory", urllib.parse.urlparse(url).netloc
    return "other", urllib.parse.urlparse(url).netloc


# ------------------------------------------------------------- reading hits

_POSITIVE_WORDS = {"stunning", "excellent", "beautiful", "charming", "best",
                   "lovely", "fantastic", "wonderful", "perfect", "gem",
                   "recommend", "favourite", "favorite", "top", "award-winning"}
_NEGATIVE_WORDS = {"disappointing", "avoid", "overpriced", "dated", "tired",
                   "poor", "worst", "complaint", "issue", "problem"}


def _fetch_text(url, timeout=15):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.text:
        return None
    if BeautifulSoup is None:
        # degrade to a crude tag-strip if bs4 somehow isn't installed - still
        # reads actual body text, just less precisely
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)).strip()[:20000]
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
        tag.decompose()
    article = soup.find("article") or soup.find("main") or soup.body
    text = (article or soup).get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)[:20000]


def _judge(text, hotel, gemini_reader_key=None, gemini_reader_model=None):
    """
    Real judgement from the fetched text, not just "a domain appeared".

    Uses gemini_reader.py's free, UNGROUNDED Gemini call when a key is
    configured - it reads the actual text and judges confirmation,
    substance and sentiment properly, rather than counting keywords. Falls
    back to the rule-based heuristic below when no key is given or the call
    fails, so this never blocks on an optional integration.
    """
    if not text:
        return {"confirmed": None, "substance": "unknown", "sentiment": "unknown",
                "excerpt": "", "via": "none"}

    if gemini_reader.has_key(gemini_reader_key):
        llm_result = gemini_reader.judge(text, hotel, api_key=gemini_reader_key,
                                         model=gemini_reader_model)
        if llm_result is not None:
            return llm_result
        # fall through to the rule-based judgment below on any failure

    low = text.lower()
    name_tokens = [t for t in re.findall(r"[a-z0-9]+", hotel.lower())
                  if t not in {"the", "hotel", "and", "&", "spa", "resort"}]
    confirmed = bool(name_tokens) and all(t in low for t in name_tokens)

    # substance: how much text surrounds the hotel's name, as a rough proxy
    # for "a passing mention in a list" vs "a real feature about this hotel"
    idx = low.find(name_tokens[0]) if name_tokens else -1
    window = text[max(0, idx - 400):idx + 1200] if idx != -1 else text[:800]
    word_count = len(window.split())
    substance = "feature" if word_count > 180 else (
        "substantial mention" if word_count > 60 else "passing mention")

    pos = sum(1 for w in _POSITIVE_WORDS if w in low)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in low)
    sentiment = "positive" if pos > neg else ("negative" if neg > pos else "neutral")

    return {"confirmed": confirmed, "substance": substance, "sentiment": sentiment,
           "excerpt": window[:280].strip(), "via": "rule"}


# ------------------------------------------------------------------- public

def check_coverage(hotel, city="", api_key=None, topics_covered=None,
                   fetch_top_n=6, progress=None, own_domain=None,
                   gemini_reader_key=None, gemini_reader_model=None):
    """
    Multi-angle search across generic + segment-specific queries, then real
    reading of the strongest non-OTA/non-directory hits.

    own_domain excludes the hotel's OWN site from the results entirely - a
    plain search for the hotel's name very often returns its own homepage or
    an "about us" page, and that is not third-party editorial coverage of
    itself. Caught live: without this, brooklandshotelsurrey.com's own pages
    were being fetched, read and counted as "editorial coverage" of
    Brooklands Hotel, which is wrong by definition, not just noise.

    gemini_reader_key, if given, is used ONLY for free, ungrounded reading of
    the fetched article text (see gemini_reader.py) - never for grounded AI
    Visibility search. Passing it here does not enable or imply anything
    about that separate, paid feature.

    Returns a dict that always has "configured": bool, so callers can tell
    "we looked and found nothing" apart from "we never looked".
    """
    out = {"configured": has_key(api_key), "ota_hits": [], "editorial_hits": [],
          "social_hits": [], "other_hits": [], "segments_detected": [],
          "queries_run": [], "error": None}
    if not out["configured"]:
        return out

    segments = detect_segments(topics_covered)
    out["segments_detected"] = [SEGMENTS[s][0] for s in segments]

    queries = [t.format(hotel=hotel, city=city).strip() for t in GENERIC_QUERY_TEMPLATES]
    queries += [SEGMENTS[s][1].format(hotel=hotel) for s in segments]
    out["queries_run"] = queries

    seen_urls = {}
    for q in queries:
        if progress:
            progress(f"Searching: {q}")
        try:
            data = _search(q, api_key=api_key, max_results=8)
        except TavilyError as e:
            out["error"] = str(e)  # last error wins; partial results still used
            continue
        for r in data.get("results", []) or []:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls[url] = r

    def _bare(netloc):
        low = netloc.lower()
        return low[4:] if low.startswith("www.") else low

    own_netloc = _bare(urllib.parse.urlparse(own_domain or "").netloc or (own_domain or ""))

    seen_ota, seen_social, seen_ed = set(), set(), set()
    editorial_candidates = []
    for url, r in seen_urls.items():
        url_netloc = _bare(urllib.parse.urlparse(url).netloc)
        if own_netloc and (url_netloc == own_netloc or url_netloc.endswith("." + own_netloc)):
            continue  # the hotel's own pages are not third-party coverage of themselves
        kind, label = _classify_domain(url)
        entry = {"platform": label, "url": url, "title": r.get("title", ""),
                 "snippet": (r.get("content") or "")[:280]}
        if kind == "ota" and label not in seen_ota:
            seen_ota.add(label)
            out["ota_hits"].append(entry)
        elif kind == "social" and label not in seen_social:
            seen_social.add(label)
            out["social_hits"].append(entry)
        elif kind == "editorial":
            if label not in seen_ed:
                seen_ed.add(label)
            editorial_candidates.append(entry)
        elif kind == "other":
            editorial_candidates.append(entry)  # "other" may still be real coverage

    # Actually read the strongest candidates rather than trust the snippet.
    # A small pause before each LLM-backed read spaces out several calls in
    # quick succession, which otherwise risks the free tier's per-minute cap
    # (undocumented exact figure - see store.py's SERVICE_CAPS comment).
    #
    # Bounded: stop reading once READ_BUDGET_S has passed. Retries on a busy
    # free-tier model can otherwise stretch one audit to many minutes, and a
    # public visitor shouldn't wait on that. Anything not reached is simply
    # left unread - never treated as bad coverage.
    read_start = time.time()
    to_read = editorial_candidates[:fetch_top_n]
    for i, entry in enumerate(to_read):
        if time.time() - read_start > READ_BUDGET_S:
            out["read_budget_hit"] = True
            break
        if progress:
            progress(f"Reading: {entry['url']}")
        if i > 0 and gemini_reader.has_key(gemini_reader_key):
            time.sleep(2)
        text = _fetch_text(entry["url"])
        entry["read"] = _judge(text, hotel, gemini_reader_key=gemini_reader_key,
                               gemini_reader_model=gemini_reader_model)

    # Only candidates we actually tried to read can be called coverage;
    # unread ones (past the cap or the time budget) are kept apart.
    attempted = [e for e in to_read if "read" in e]
    out["editorial_hits"] = [
        e for e in attempted if e["read"].get("confirmed") is not False
    ]
    out["other_hits"] = [e for e in editorial_candidates if e not in out["editorial_hits"]]

    return out


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--city", default="")
    p.add_argument("--topics", default="", help="comma-separated topic keys, "
                   "e.g. weddings,families (normally comes from site_check.py)")
    a = p.parse_args()
    if not has_key():
        print("No TAVILY_API_KEY set.")
        return 2
    topics = [t.strip() for t in a.topics.split(",") if t.strip()]
    res = check_coverage(a.hotel, a.city, topics_covered=topics,
                         progress=lambda m: print(f"  {m}"))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
