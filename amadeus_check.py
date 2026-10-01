#!/usr/bin/env python3
"""
Amadeus Hotel Ratings integration - covers part of Reviews & Reputation.

STATUS (verified 2026-10-01): Amadeus decommissioned their free self-service
developer portal on 2026-07-17. developers.amadeus.com now serves only the
"Amadeus Enterprise API Portal" - access is a sales/request-access process,
not a free signup. It is NOT currently a realistic free option to point a
new user at. See scoring.py's score_reviews() for the user-facing wording.

Whether the test.api.amadeus.com endpoints below still respond at all for
credentials issued before the shutdown is UNVERIFIED - only the signup page
has been confirmed dead, not the API itself. This module is left in place,
unchanged and untested against a live call, for anyone who already holds
valid credentials to try; treat its behaviour as unconfirmed until it's
actually been run against a live key again.

Amadeus aggregates guest-review sentiment into per-category scores (sleep
quality, service, facilities, room comfort, value for money, location) rather
than exposing raw review text - a structured, legitimately-licensed signal
rather than anything scraped.

Two-step API: an OAuth2 client-credentials token, then a lookup. Amadeus
identifies hotels by its own hotel ID, not a name search, so this first finds
the hotel via Hotel Search (by geocode) and then requests its ratings.

No key/secret -> every function returns "not configured". Never raises for
missing credentials; the caller decides what to do.

Usage:
  export AMADEUS_API_KEY=...
  export AMADEUS_API_SECRET=...
  python amadeus_check.py --hotel "Brooklands Hotel" --lat 51.353 --lon -0.473
"""

import argparse
import json
import os
import sys
import time

import requests

# Test environment by default - free, no card, per Amadeus's own self-service
# tier. Switch to api.amadeus.com only once the user has a production key.
TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
HOTEL_SEARCH_URL = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-geocode"
RATINGS_URL = "https://test.api.amadeus.com/v2/e-reputation/hotel-sentiments"


class AmadeusError(RuntimeError):
    pass


def has_credentials(api_key=None, api_secret=None):
    return bool((api_key or os.environ.get("AMADEUS_API_KEY"))
               and (api_secret or os.environ.get("AMADEUS_API_SECRET")))


def _get_token(api_key=None, api_secret=None, timeout=25):
    key = api_key or os.environ.get("AMADEUS_API_KEY")
    secret = api_secret or os.environ.get("AMADEUS_API_SECRET")
    if not (key and secret):
        raise AmadeusError("no Amadeus API key/secret configured")
    try:
        r = requests.post(TOKEN_URL, data={
            "grant_type": "client_credentials", "client_id": key, "client_secret": secret,
        }, timeout=timeout)
    except requests.RequestException as e:
        raise AmadeusError(f"token request failed: {e}")
    if r.status_code != 200:
        raise AmadeusError(f"token request HTTP {r.status_code}: {r.text[:250]}")
    try:
        return r.json()["access_token"]
    except (ValueError, KeyError):
        raise AmadeusError("token response missing access_token")


def find_hotel_id(lat, lon, token, radius_km=1, timeout=25):
    """Amadeus's own hotel ID for the nearest match to a known lat/lon."""
    try:
        r = requests.get(HOTEL_SEARCH_URL, params={
            "latitude": lat, "longitude": lon, "radius": radius_km, "radiusUnit": "KM",
        }, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    except requests.RequestException as e:
        raise AmadeusError(f"hotel search failed: {e}")
    if r.status_code != 200:
        raise AmadeusError(f"hotel search HTTP {r.status_code}: {r.text[:250]}")
    hotels = (r.json() or {}).get("data", []) or []
    return hotels[0] if hotels else None


def check_ratings(hotel_id, token, timeout=25):
    try:
        r = requests.get(RATINGS_URL, params={"hotelIds": hotel_id},
                         headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    except requests.RequestException as e:
        raise AmadeusError(f"ratings request failed: {e}")
    if r.status_code == 404:
        return None  # no sentiment data for this property - not an error
    if r.status_code != 200:
        raise AmadeusError(f"ratings HTTP {r.status_code}: {r.text[:250]}")
    data = (r.json() or {}).get("data", []) or []
    return data[0] if data else None


def check_hotel(hotel, lat=None, lon=None, api_key=None, api_secret=None):
    """
    Full flow: token -> find hotel by coordinates -> pull sentiment.

    lat/lon should come from a verified location (e.g. the coordinate-checked
    OpenStreetMap match), not a name search, since Amadeus has no name search
    of its own and a wrong hotel ID would silently score a different property.
    """
    out = {"configured": has_credentials(api_key, api_secret), "found": False,
          "categories": {}, "overall_sentiment": None, "error": None}
    if not out["configured"]:
        return out
    if lat is None or lon is None:
        out["error"] = ("no verified coordinates available - Amadeus has no "
                        "hotel name search, so a lookup needs a known location "
                        "to avoid scoring the wrong property")
        return out

    try:
        token = _get_token(api_key, api_secret)
        hit = find_hotel_id(lat, lon, token)
        if not hit:
            out["error"] = "no Amadeus hotel ID found near this location"
            return out
        out["amadeus_hotel_id"] = hit.get("hotelId")
        out["amadeus_name"] = hit.get("name")

        sentiment = check_ratings(hit.get("hotelId"), token)
        if sentiment is None:
            out["error"] = "no sentiment data published for this property"
            return out

        out["found"] = True
        out["overall_sentiment"] = sentiment.get("overallRating")
        out["num_reviews"] = sentiment.get("numberOfReviews")
        # Category scores are 0-100, one per traveller concern.
        skip = {"hotelId", "type", "overallRating", "numberOfReviews", "numberOfRatings"}
        out["categories"] = {
            k: v for k, v in sentiment.items() if k not in skip and isinstance(v, (int, float))
        }
    except AmadeusError as e:
        out["error"] = str(e)
    return out


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    a = p.parse_args()
    if not has_credentials():
        print("No AMADEUS_API_KEY / AMADEUS_API_SECRET set.")
        return 2
    res = check_hotel(a.hotel, a.lat, a.lon)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
