"""
The hotel's TripAdvisor listing, read from TripAdvisor's OWN official Content API (never by reading its web pages), used only when TRIPADVISOR_API_KEY (or TRIPADVISOR_KEY) is set on the host (never in code, never typed into the site).

What it adds
  * the name, address, postcode and telephone number TripAdvisor shows, compared with the hotel's own website by the same rules as every other listing (listing_facts.compare);
  * the rating, review count and ranking TripAdvisor shows, with a link back to the listing.

How it stays honest
  * the listing is only used when it is clearly THIS hotel: the name matches (same or close words) AND the town, postcode or telephone number agrees; otherwise the result says it could not be confirmed and nothing is compared;
  * a missing field is 'not shown', never a difference;
  * one search, one details and one recent-reviews call an audit, counted against a monthly cap (store.SERVICE_CAPS['tripadvisor']) kept below the free allowance;
  * TripAdvisor's terms ask for attribution and a link back, so the result carries the source name and the listing's web address, and the report names TripAdvisor as the source. Check their current terms before relying on
    how long data may be kept.
No key -> 'not configured'. The key is sent in the request's query string as TripAdvisor requires, so it is never put in a message, a log line or the saved report.
"""

import os
import re

import requests

import listing_facts

SOURCE = "TripAdvisor Content API"
BASE = "https://api.content.tripadvisor.com/api/v1"
PLATFORM = "TripAdvisor"


def has_key(api_key=None):
    return bool(api_key or os.environ.get("TRIPADVISOR_API_KEY") or os.environ.get("TRIPADVISOR_KEY"))


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _call(path, params, key, get=requests.get, timeout=15):
    r = get(f"{BASE}{path}", params={**params, "key": key}, headers={"accept": "application/json"}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")        # the response text can echo the request, so it is never kept
    return r.json()


def _same_hotel(cand, hotel, city, site):
    """The candidate must be this hotel: close name AND (town, postcode or telephone). -> (ok, why)"""
    verdict, _why = listing_facts.name_verdict(cand.get("name") or "", hotel, city)
    if verdict == "differs":
        return False, "the name is different"
    addr = cand.get("address_obj") or {}
    blob = " ".join(str(addr.get(k) or "") for k in ("street1", "street2", "city", "state", "country", "postalcode", "address_string")).lower()
    town = (city or "").split(",")[0].strip().lower()
    pc = (site or {}).get("postcode") or ""
    ph = _digits((site or {}).get("phone") or "")
    if pc and re.sub(r"\s+", "", pc.lower()) in re.sub(r"\s+", "", blob):
        return True, ""
    if len(ph) >= 9 and ph[-9:] in _digits(cand.get("phone") or ""):
        return True, ""
    if town and town in blob:
        return True, ""
    return False, "the town, postcode and telephone number could not be matched"


def lookup(hotel, city, lat=None, lon=None, api_key=None, site=None, get=requests.get, site_states=None):
    """-> {"source", "status": ok|not_configured|unavailable|not_found|unconfirmed, "reason", "listing": {...} or None, "calls"}. Never raises."""
    def out(status, reason="", listing=None, calls=0):
        return {"source": SOURCE, "status": status, "reason": reason, "listing": listing, "calls": calls}
    key = api_key or os.environ.get("TRIPADVISOR_API_KEY") or os.environ.get("TRIPADVISOR_KEY")
    if not key:
        return out("not_configured", "No TripAdvisor key is configured, so this listing was not read from TripAdvisor.")
    calls = 0
    try:
        params = {"searchQuery": hotel, "category": "hotels", "language": "en"}
        if lat is not None and lon is not None:
            params["latLong"] = f"{lat},{lon}"
        elif city:
            params["address"] = city
        calls += 1
        found = (_call("/location/search", params, key, get=get) or {}).get("data") or []
        if not found:
            return out("not_found", "TripAdvisor's search found no hotel with that name.", None, calls)
        chosen, why = None, ""
        for cand in found[:5]:
            ok, why = _same_hotel(cand, hotel, city, site)
            if ok:
                chosen = cand
                break
        if not chosen:
            return out("unconfirmed", f"TripAdvisor returned hotels, but none could be confirmed as this one ({why}), so nothing was compared.", None, calls)
        calls += 1
        d = _call(f"/location/{chosen['location_id']}/details", {"language": "en", "currency": "USD"}, key, get=get) or {}
    except Exception as e:  # noqa: BLE001
        return out("unavailable", f"TripAdvisor did not answer ({str(e)[:60]}).", None, calls)
    addr = d.get("address_obj") or chosen.get("address_obj") or {}
    rank = (d.get("ranking_data") or {}).get("ranking_string") or ""
    listing = {"location_id": str(chosen.get("location_id")), "name": d.get("name") or chosen.get("name") or "", "url": d.get("web_url") or "", "phone": _digits(d.get("phone") or ""),
               "postcode": addr.get("postalcode") or "", "address": addr.get("address_string") or "", "rating": _num(d.get("rating")), "reviews": _int(d.get("num_reviews")), "ranking": rank,
               "attribution": "Data from TripAdvisor"}
    rows, why = recent_reviews(listing["location_id"], key, get=get)
    calls += 1
    listing["recent"] = themes_from(rows, hotel, site_states) if rows else None
    if not rows and why:
        listing["recent_note"] = "TripAdvisor's API did not return recent reviews for this listing."
    return out("ok", "", listing, calls)


def recent_reviews(location_id, key, get=requests.get, limit=5):
    """The few most recent reviews TripAdvisor's API returns for the listing, as plain rows for review_pack. Reviewer names and profiles are never read. -> (rows, error)"""
    import datetime as dt
    try:
        data = (_call(f"/location/{location_id}/reviews", {"language": "en", "limit": limit}, key, get=get) or {}).get("data") or []
    except Exception as e:  # noqa: BLE001
        return [], f"{str(e)[:40]}"
    rows = []
    for r in data[:limit]:
        d = None
        try:
            d = dt.date.fromisoformat(str(r.get("published_date") or "")[:10])
        except ValueError:
            pass
        rating = _num(r.get("rating"))
        txt = " ".join(x for x in (str(r.get("title") or "").strip(), str(r.get("text") or "").strip()) if x)
        if rating is not None or txt:
            rows.append({"platform": PLATFORM, "date": d, "rating": rating, "text": txt, "positive": "", "negative": "", "reply": "", "reply_date": None})
    return rows, ""


def themes_from(rows, hotel="", site_states=None):
    """What the few recent reviews praise and criticise, by topic, set against what the hotel's own site states. Counts and topics only: no review text, no names. None when there are none."""
    import review_pack
    a = review_pack.analyse(rows, hotel, site_states)
    if not a:
        return None
    p = a["public"]
    return {"reviews": p["reviews"], "avg_rating": p["avg_rating"], "last_date": str(p["last_date"]) if p.get("last_date") else None, "praised": p["praised"][:5], "criticised": p["criticised"][:5],
            "note": f"Based on the {p['reviews']} most recent review(s) TripAdvisor's API returned, not on all of the hotel's reviews: a handful cannot show a pattern. Use it as a prompt to check, and use the hotel's own review export for the full picture."}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def as_listing(res):
    """The official data in the shape listing_facts uses for a platform, with the facts it could read (name, postcode, telephone). {} when there is nothing confirmed."""
    li = (res or {}).get("listing")
    if not li:
        return {}
    quote = f"TripAdvisor Content API: {li['name']}, {li['address']}".strip(", ")
    out = {"url": li["url"] or "https://www.tripadvisor.com/", "title": li["name"], "check_in": None, "check_out": None, "stars": None, "phone": li["phone"] or None, "name": li["name"] or None,
           "postcode": li["postcode"] or None, "quotes": {k: quote for k in ("name", "postcode", "phone")}, "official_api": True}
    return {PLATFORM: out}
