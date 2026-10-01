#!/usr/bin/env python3
"""
Google Places API integration - the fullest Reviews & Reputation signal
available: official star rating, review count, and up to 5 real review
snippets, licensed and served by Google itself.

Costs money past the free monthly allowance, and Google requires billing
enabled on the project even to stay within it (verified 2026-09). This
module never assumes that trade-off has been accepted - it only runs when a
key is explicitly configured, and the field mask is set to request exactly
what's needed (rating, review count, up to 5 reviews) rather than every
field, to stay inside the cheapest tier that includes them.

No key -> "not configured". Never raises for a missing key.

Usage:
  export GOOGLE_PLACES_API_KEY=...
  python places_check.py --hotel "Brooklands Hotel" --lat 51.353 --lon -0.473
"""

import argparse
import json
import os
import sys

import requests

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Exactly the fields needed for Reviews & Reputation - not more, since each
# additional field can move the call into a more expensive SKU tier.
FIELD_MASK = "places.id,places.displayName,places.rating,places.userRatingCount,places.reviews"


class PlacesError(RuntimeError):
    pass


def has_key(api_key=None):
    return bool(api_key or os.environ.get("GOOGLE_PLACES_API_KEY"))


def _key(api_key=None):
    return api_key or os.environ.get("GOOGLE_PLACES_API_KEY")


def find_place(hotel, city="", lat=None, lon=None, api_key=None, timeout=25):
    """Text search biased toward a known location, to avoid a same-named match."""
    k = _key(api_key)
    if not k:
        raise PlacesError("no Google Places API key configured")

    body = {"textQuery": f"{hotel} {city}".strip()}
    if lat is not None and lon is not None:
        body["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 2000.0}
        }
    try:
        r = requests.post(SEARCH_URL, json=body, headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": k,
            "X-Goog-FieldMask": FIELD_MASK,
        }, timeout=timeout)
    except requests.RequestException as e:
        raise PlacesError(f"request failed: {e}")
    if r.status_code == 403:
        raise PlacesError("HTTP 403 - key invalid, or billing not enabled on the project")
    if r.status_code != 200:
        raise PlacesError(f"HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json().get("places", [])
    except ValueError:
        raise PlacesError("response was not JSON")


def check_hotel(hotel, city="", lat=None, lon=None, api_key=None):
    out = {"configured": has_key(api_key), "found": False,
          "rating": None, "review_count": None, "reviews": [], "error": None}
    if not out["configured"]:
        return out
    try:
        places = find_place(hotel, city, lat, lon, api_key=api_key)
    except PlacesError as e:
        out["error"] = str(e)
        return out
    if not places:
        out["error"] = "no matching place found"
        return out

    p = places[0]
    out["found"] = True
    out["place_name"] = (p.get("displayName") or {}).get("text", "")
    out["rating"] = p.get("rating")
    out["review_count"] = p.get("userRatingCount")
    out["reviews"] = [
        {
            "rating": rv.get("rating"),
            "text": ((rv.get("text") or {}).get("text") or "")[:400],
            "relative_time": rv.get("relativePublishTimeDescription", ""),
        }
        for rv in (p.get("reviews") or [])
    ]
    return out


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--city", default="")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    a = p.parse_args()
    if not has_key():
        print("No GOOGLE_PLACES_API_KEY set.")
        return 2
    res = check_hotel(a.hotel, a.city, a.lat, a.lon)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
