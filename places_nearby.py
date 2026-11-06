"""
Google Places API (New): the hotel's identity and the hotels around it, from Google's own data, used only when GOOGLE_PLACES_API_KEY is set on the host (never in code, never typed into the site).

What it adds to the audit
  identity     the hotel's Google place (place id, official name, address, coordinates) so the audit can check it is looking at the right hotel and has coordinates even when the free geocoder does not answer;
  nearby       lodging within a few kilometres (names, addresses, coordinates, distance) to complete the list of comparable hotels when OpenStreetMap's public servers do not answer.

Cost and terms (check Google's current pricing page before relying on these figures)
  * The field mask asks only for the cheapest set of fields (id, name, address, location, types). Asking for ratings, reviews or the website moves a call into a dearer tier, so those are NOT requested here
    (the website is requested only if GOOGLE_PLACES_WEBSITES=1, and ratings stay in places_check.py).
  * Each audit uses at most two calls (one identity search, one nearby search), counted against a monthly cap (store.SERVICE_CAPS['google_places']) kept below the free allowance.
  * Google's terms limit how long place data may be stored beyond the place id, and require attribution: results carry source='Google Maps Platform (Places API)', and the report says where the data came from.
Nothing here runs without a key; a missing or failing service gives 'not configured' / 'unavailable', never an error.
"""

import math
import os

import requests

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
SOURCE = "Google Maps Platform (Places API)"
BASE_FIELDS = ["places.id", "places.displayName", "places.formattedAddress", "places.location", "places.types"]
MAX_CALLS_PER_AUDIT = 2


def _fields():
    f = list(BASE_FIELDS)
    if os.environ.get("GOOGLE_PLACES_WEBSITES") == "1":
        f.append("places.websiteUri")                  # dearer tier: off unless the operator turns it on
    return ",".join(f)


def has_key(api_key=None):
    return bool(api_key or os.environ.get("GOOGLE_PLACES_API_KEY"))


def _key(api_key=None):
    return api_key or os.environ.get("GOOGLE_PLACES_API_KEY")


def km_between(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def _post(url, body, key, timeout=20, post=requests.post):
    r = post(url, json=body, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": _fields(), "Content-Type": "application/json"}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {(r.text or '')[:160]}")
    return r.json().get("places") or []


def _row(p, lat=None, lon=None):
    loc = p.get("location") or {}
    la, lo = loc.get("latitude"), loc.get("longitude")
    return {"place_id": p.get("id"), "name": (p.get("displayName") or {}).get("text") or "", "address": p.get("formattedAddress") or "", "lat": la, "lon": lo,
            "km": round(km_between(lat, lon, la, lo), 2) if None not in (lat, lon, la, lo) else None, "website": p.get("websiteUri") or "", "types": p.get("types") or [], "source": SOURCE}


def find_hotel(hotel, city, lat=None, lon=None, api_key=None, post=requests.post):
    """-> {"status", "reason", "place": row or None, "calls"}. The best text match for this hotel, biased to its known coordinates so a same-named hotel elsewhere is not taken."""
    k = _key(api_key)
    if not k:
        return {"status": "not_configured", "reason": "No Google Places key is configured.", "place": None, "calls": 0}
    body = {"textQuery": f"{hotel} {city}".strip(), "includedType": "lodging", "maxResultCount": 3}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 3000.0}}
    try:
        rows = [_row(p, lat, lon) for p in _post(SEARCH_URL, body, k, post=post)]
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": f"Google Places did not answer ({str(e)[:120]}).", "place": None, "calls": 1}
    if not rows:
        return {"status": "no_results", "reason": "Google Places found no lodging with that name.", "place": None, "calls": 1}
    return {"status": "ok", "reason": "", "place": rows[0], "calls": 1}


def nearby_hotels(lat, lon, exclude_name="", radius_m=2500, limit=20, api_key=None, post=requests.post):
    """-> {"status", "reason", "hotels": [rows nearest first], "calls"}. Lodging around a point, without the hotel itself."""
    k = _key(api_key)
    if not k:
        return {"status": "not_configured", "reason": "No Google Places key is configured.", "hotels": [], "calls": 0}
    if lat is None or lon is None:
        return {"status": "unavailable", "reason": "No coordinates for the hotel, so nearby hotels were not looked up.", "hotels": [], "calls": 0}
    body = {"includedTypes": ["lodging"], "maxResultCount": min(20, limit), "rankPreference": "DISTANCE", "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius_m)}}}
    try:
        rows = [_row(p, lat, lon) for p in _post(NEARBY_URL, body, k, post=post)]
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": f"Google Places did not answer ({str(e)[:120]}).", "hotels": [], "calls": 1}
    me = "".join(ch for ch in exclude_name.lower() if ch.isalnum())
    rows = [r for r in rows if r["name"] and "".join(ch for ch in r["name"].lower() if ch.isalnum()) != me]
    rows.sort(key=lambda r: r["km"] if r["km"] is not None else 99)
    return {"status": "ok" if rows else "no_results", "reason": "" if rows else "Google Places lists no other lodging near this point.", "hotels": rows[:limit], "calls": 1}


def supplement_osm(ctx, lat, lon, hotel, api_key=None, post=requests.post, min_hotels=6):
    """
    OpenStreetMap's public servers sometimes do not answer, and its list of hotels is often short. When the map context is missing or has fewer than `min_hotels` hotels, add Google's nearby lodging to it (marked
    with its source), so the comparison has hotels to work with. -> (ctx, note). Never raises; the context is returned unchanged when nothing is added.
    """
    have = (ctx or {}).get("hotels") or []
    if len(have) >= min_hotels or not has_key(api_key):
        return ctx, ""
    res = nearby_hotels(lat, lon, exclude_name=hotel, api_key=api_key, post=post)
    if res["status"] != "ok":
        return ctx, res["reason"]
    names = {"".join(ch for ch in h.get("name", "").lower() if ch.isalnum()) for h in have}
    add = [{"name": r["name"], "km": r["km"], "lat": r["lat"], "lon": r["lon"], "osm": "", "tags": ({"website": r["website"]} if r["website"] else {}), "source": SOURCE, "place_id": r["place_id"]}
           for r in res["hotels"] if "".join(ch for ch in r["name"].lower() if ch.isalnum()) not in names]
    new = dict(ctx or {"stations": [], "attractions": [], "airports": [], "venues": [], "origin": {"lat": lat, "lon": lon}})
    new["hotels"] = sorted(have + add, key=lambda h: h.get("km") if h.get("km") is not None else 99)[:25]
    new["places_calls"] = res["calls"]
    return new, f"{len(add)} nearby hotel(s) added from Google Places."
