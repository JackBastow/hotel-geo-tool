#!/usr/bin/env python3
"""
Tavily search integration - covers Editorial & Blogs and OTA presence.

Why Tavily and not scraping OTA sites directly: TripAdvisor and Booking.com's
Terms of Use explicitly prohibit automated collection ("use... any robot,
spider... to access, retrieve, copy, scrape, aggregate, collect... except as
expressly permitted... in writing" - TripAdvisor ToU, verified 2026-09).
Reading Tavily's search index instead means we never touch those sites
directly - we read what a search engine's index already says about them,
through an API designed to be queried this way.

Two searches per audit:
  1. "{hotel} {city} reviews OR hotel" -> classify result domains into
     OTA / editorial / directory / other, for OTA & Editorial coverage
  2. "{hotel} {city} rating review" -> pull any rating snippets Tavily surfaces

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

import requests

API_URL = "https://api.tavily.com/search"

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

# Editorial / travel-publication signals. A domain matching these reads as
# a credible third-party mention rather than an OTA listing or directory.
EDITORIAL_HINTS = [
    "cntraveler.com", "condenasttraveller.com", "telegraph.co.uk/travel",
    "theguardian.com/travel", "timeout.com", "independent.co.uk/travel",
    "standard.co.uk/travel", "forbes.com/sites", "travelandleisure.com",
    "lonelyplanet.com", "roughguides.com", "nationalgeographic.com/travel",
    "suitcasemag.com", "wallpaper.com", "harpersbazaar.com",
    "visitengland.com", "visitsurrey.com", "visitbritain.com",
    ".gov.uk/tourism", "eater.com", "bookatable.", "squaremeal.co.uk",
]

DIRECTORY_HINTS = ["yell.com", "yelp.", "wikipedia.org", "foursquare.com",
                   "wikidata.org", "openstreetmap.org"]


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
    if r.status_code == 432 or r.status_code == 429:
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
    for pat in EDITORIAL_HINTS:
        if pat in low:
            return "editorial", urllib.parse.urlparse(url).netloc
    for pat in DIRECTORY_HINTS:
        if pat in low:
            return "directory", urllib.parse.urlparse(url).netloc
    return "other", urllib.parse.urlparse(url).netloc


def check_coverage(hotel, city="", api_key=None):
    """
    One search, classified into OTA presence / editorial mentions / other.

    Returns a dict that always has "configured": bool, so callers can tell
    "we looked and found nothing" apart from "we never looked".
    """
    out = {"configured": has_key(api_key), "ota_hits": [], "editorial_hits": [],
          "other_hits": [], "raw_results": [], "error": None}
    if not out["configured"]:
        return out

    query = f'"{hotel}" {city} hotel reviews'.strip()
    try:
        data = _search(query, api_key=api_key, max_results=10)
    except TavilyError as e:
        out["error"] = str(e)
        return out

    results = data.get("results", []) or []
    out["raw_results"] = [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": (r.get("content") or "")[:280]}
        for r in results
    ]

    seen_ota, seen_ed = set(), set()
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        kind, label = _classify_domain(url)
        entry = {"platform": label, "url": url,
                 "title": r.get("title", ""),
                 "snippet": (r.get("content") or "")[:280]}
        if kind == "ota" and label not in seen_ota:
            seen_ota.add(label)
            out["ota_hits"].append(entry)
        elif kind == "editorial" and label not in seen_ed:
            seen_ed.add(label)
            out["editorial_hits"].append(entry)
        elif kind == "other":
            out["other_hits"].append(entry)

    return out


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--city", default="")
    a = p.parse_args()
    if not has_key():
        print("No TAVILY_API_KEY set.")
        return 2
    res = check_coverage(a.hotel, a.city)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
