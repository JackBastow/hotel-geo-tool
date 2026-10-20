"""
Location anchors: the named places a traveller would actually search around ('near the Opera Garnier', 'near the Johan Cruijff ArenA', 'near Gare du Nord').

A question like 'best hotels in Paris' is answered with the same palace hotels whatever the hotel is. A question anchored on a real place the hotel is close to tests the market the hotel competes in. Anchors come from, in this order:

  1. the hotel's OWN pages (a named attraction, venue, station or airport with a stated distance: 'the Louvre Museum is 15 minutes away'), which is what the hotel itself says it is near;
  2. Wikipedia's free geosearch around the hotel's coordinates, ranked by how many people read each article (the places people actually know), with districts, streets, metro stops and lists removed;
  3. the open map data the audit already holds.

The coordinates come from the hotel's own markup or, when a page was read as plain text, from one polite search of OpenStreetMap's Nominatim for the hotel's name and town (accepted only if the result is in that town). No key, no cost. Every anchor says where it came from.
"""

import re
import time
import urllib.parse

import evidence
import places

UA = "HotelDiscoverabilityAudit/1.0 (independent hotel visibility audit; respects usage limits)"
WIKI = "https://en.wikipedia.org/w/api.php"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
_BAD_TITLE = re.compile(r"arrondissement|district|quarter|neighbou?rhood|\bmetro\b|m[eé]tro|\bstation\b|\bstreet\b|\bavenue\b|\bboulevard\b|\brue\b|\broad\b|list of|\(disambiguation\)|department|commune|municipality|"
                        r"\bschool\b|\blycée\b|\bcollege\b|university|hospital|embassy|\bhotel\b|\bhôtel\b|county|province|parish|^\d", re.I)
_MIN = re.compile(r"(\d{1,3})\s?[-–]?\s?min", re.I)
_KM = re.compile(r"(\d+(?:[.,]\d+)?)\s?(km|kilomet\w*|miles?|mi)\b", re.I)
_M = re.compile(r"(\d{2,4})\s?(?:m|metres?|meters?)\b(?!\w)", re.I)


def km_from_text(text):
    """A rough distance in km from the words the hotel uses ('15 minutes', '800 m', '1.2 km', '5 minute drive'); minutes are walking unless a drive, taxi or car is named. None when there is no figure."""
    t = text or ""
    m = _KM.search(t)
    if m:
        v = float(m.group(1).replace(",", "."))
        return round(v * 1.609 if m.group(2).lower().startswith("mi") else v, 2)
    m = _M.search(t)
    if m:
        return round(int(m.group(1)) / 1000, 2)
    m = _MIN.search(t)
    if m:
        per_min = 0.5 if re.search(r"drive|car|taxi|by (?:road|bus|metro|train|tram)|ride", t, re.I) else 0.08
        return round(int(m.group(1)) * per_min, 2)
    return None


def from_pages(own_pages, hotel, osm_ctx=None, max_km=2.5):
    """Named places the hotel's own pages say are close: [{name, kind, distance, km, url, source}], nearest first. Attractions and venues first; stations and airports are kept for the questions that need them."""
    out, seen = [], set()
    for p in own_pages or []:
        for kind in ("attraction", "venue", "station", "airport"):
            for m in places.mentions(p.get("text", ""), kind, hotel, osm_ctx):
                if not m.get("distance"):
                    continue
                km = km_from_text(m["distance"])
                key = evidence.fold(m["name"])
                if km is None or km > max_km or key in seen:
                    continue
                seen.add(key)
                out.append({"name": m["name"], "kind": kind, "distance": m["distance"], "km": km, "url": p.get("url", ""), "source": "the hotel's own pages"})
    order = {"attraction": 0, "venue": 0, "station": 1, "airport": 2}
    out.sort(key=lambda a: (order[a["kind"]], a["km"]))
    return out


def geocode(hotel, city, fetch):
    """(lat, lon) for the hotel from one Nominatim search, accepted only if the result is in the hotel's town. None when it cannot be found or placed."""
    q = f"{hotel}, {city}".strip(", ")
    try:
        r = fetch(NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 3, "addressdetails": 1}), headers={"User-Agent": UA}, timeout=10)
        rows = r.json() if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return None
    town = evidence.fold((city or "").split(",")[0])
    for row in rows or []:
        a = row.get("address") or {}
        where = evidence.fold(" ".join(str(a.get(k, "")) for k in ("city", "town", "village", "municipality", "suburb", "county")) + " " + row.get("display_name", ""))
        if town and town in where:
            try:
                return float(row["lat"]), float(row["lon"])
            except (KeyError, ValueError):
                continue
    return None


def wikipedia_nearby(lat, lon, fetch, radius_m=1500, limit=12):
    """The places around a point that people know: [{name, km, views, source}] by pageviews, with districts, streets, metro stops, schools, hotels and lists removed."""
    try:
        r = fetch(WIKI + "?" + urllib.parse.urlencode({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": radius_m, "gslimit": 40, "format": "json"}), headers={"User-Agent": UA}, timeout=10)
        hits = (r.json().get("query") or {}).get("geosearch") or [] if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []
    hits = [h for h in hits if not _BAD_TITLE.search(h.get("title", ""))][:limit * 2]
    if not hits:
        return []
    try:
        titles = "|".join(h["title"] for h in hits[:30])
        r = fetch(WIKI + "?" + urllib.parse.urlencode({"action": "query", "prop": "pageviews", "titles": titles, "pvipdays": 30, "format": "json"}), headers={"User-Agent": UA}, timeout=10)
        pages = (r.json().get("query") or {}).get("pages") or {} if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        pages = {}
    views = {p.get("title"): sum(v for v in (p.get("pageviews") or {}).values() if v) for p in pages.values()}
    out = [{"name": h["title"], "km": round(h["dist"] / 1000, 2), "views": views.get(h["title"], 0), "kind": "attraction", "source": "Wikipedia (places near the hotel's coordinates)"} for h in hits]
    out.sort(key=lambda a: (-a["views"], a["km"]))
    return [a for a in out if a["views"] >= 300][:limit]


def find(own_pages, hotel, city, osm_ctx=None, location=None, fetch=None, deadline_s=12):
    """
    -> {"anchors": [...best first...], "coords": (lat, lon)|None, "coords_source": str}. The hotel's own words come first; Wikipedia's well-known places fill in around them. Never raises.
    """
    own = from_pages(own_pages, hotel, osm_ctx)
    out = {"anchors": [], "coords": None, "coords_source": ""}
    coords = (location or {}).get("lat"), (location or {}).get("lon")
    if all(isinstance(c, (int, float)) for c in coords):
        out["coords"], out["coords_source"] = coords, "the hotel's own pages"
    if fetch is None:
        import netguard
        fetch = netguard.get
    t0 = time.time()
    wiki = []
    try:
        if out["coords"] is None and hotel and city and time.time() - t0 < deadline_s:
            g = geocode(hotel, city, fetch)
            if g:
                out["coords"], out["coords_source"] = g, "OpenStreetMap search (Nominatim)"
        if out["coords"] and time.time() - t0 < deadline_s:
            wiki = wikipedia_nearby(out["coords"][0], out["coords"][1], fetch)
    except Exception:  # noqa: BLE001
        wiki = []
    known = {evidence.fold(a["name"]) for a in own}
    fresh = [w for w in wiki if evidence.fold(w["name"]) not in known and not any(evidence.fold(w["name"]) in k or k in evidence.fold(w["name"]) for k in known)]
    famous = [w for w in fresh if w["views"] >= 2000 and w["km"] <= 0.8]          # a landmark people know, right beside the hotel: what travellers search around
    merged = famous + [a for a in own if a["kind"] in ("attraction", "venue")] + [w for w in fresh if w not in famous]
    merged += [a for a in own if a["kind"] not in ("attraction", "venue")]
    out["anchors"] = merged
    return out


def best(anchors, kinds=("attraction", "venue"), n=1):
    """The anchor(s) to build questions around: the first of the wanted kinds (the hotel's own words, then the best-known place nearby)."""
    return [a for a in anchors or [] if a.get("kind") in kinds][:n]
