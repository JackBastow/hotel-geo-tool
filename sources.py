"""
Free-source adapters. Every adapter returns the same envelope:

    {"source": str, "status": "ok" | "no_results" | "unavailable" | "not_configured",
     "reason": str,           # always filled when status != "ok"
     "items": [...],          # adapter-specific, plain dicts
     "access": str,           # what this source is / what it can and cannot tell us
     }

"unavailable" (the source failed or refused us) is NEVER the same as
"no_results" (we asked and it had nothing). The report treats them
differently: the first is a gap in what we could assess, the second is a
finding.

Nothing here costs money. Sources that need a key use a free key only and are
skipped, with a stated reason, when the operator hasn't configured one.
Access notes (cost, limits, what each returns) are in SOURCES at the bottom
and are printed in the report's methodology section.
"""

import math
import re
import time
import urllib.parse

import requests

import evidence

UA = ("HotelDiscoverabilityAudit/1.0 (independent hotel visibility audit; "
      "contact: j.bastownorris@westmontuk.com)")


def _envelope(source, access, status="ok", reason="", items=None, **extra):
    return {"source": source, "status": status, "reason": reason,
            "items": items or [], "access": access, **extra}


def _get(url, params=None, headers=None, timeout=25, retries=0, retry_wait=6.0,
         method="GET", data=None):
    """-> (json or None, status_code or None, error or None). Never raises."""
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    last_err, code = None, None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, params=params, data=data, headers=hdrs,
                                 timeout=timeout)
        except requests.RequestException as e:
            last_err, code = f"request failed: {type(e).__name__}", None
            time.sleep(retry_wait) if attempt < retries else None
            continue
        code = r.status_code
        if code in (429, 502, 503, 504) and attempt < retries:
            time.sleep(retry_wait)
            continue
        if code != 200:
            return None, code, f"HTTP {code}"
        try:
            return r.json(), code, None
        except ValueError:
            return None, code, "response was not JSON"
    return None, code, last_err or "failed"


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------------ GDELT

GDELT_ACCESS = (
    "GDELT DOC 2.0 - free, no key. Indexes news articles from monitored "
    "publishers and returns links, titles, publishers and dates. It is a news "
    "monitor, not a web search engine: it covers only roughly the last three "
    "months, and only outlets it monitors. Limit: one request per 5 seconds; "
    "it may refuse requests from shared hosting IPs. Absence here proves nothing.")


def gdelt_search(hotel, city="", timespan="3months", max_records=40):
    q = f'"{hotel}"'
    params = {"query": q, "mode": "ArtList", "format": "json",
              "maxrecords": max_records, "sort": "datedesc", "timespan": timespan}
    data, code, err = _get("https://api.gdeltproject.org/api/v2/doc/doc",
                           params=params, retries=1, retry_wait=7.0, timeout=40)
    if err:
        why = ("GDELT rate-limited this request (HTTP 429). It permits one request per "
               "5 seconds and can refuse shared servers. This says nothing about coverage."
               if code == 429 else f"GDELT did not answer ({err}). This says nothing about coverage.")
        return _envelope("GDELT", GDELT_ACCESS, "unavailable", why)
    arts = (data or {}).get("articles") or []
    items = [{
        "url": a.get("url"), "title": a.get("title") or "", "domain": a.get("domain") or "",
        "published": evidence.parse_date(a.get("seendate")),
        "language": a.get("language"), "country": a.get("sourcecountry"),
    } for a in arts if a.get("url")]
    if not items:
        return _envelope("GDELT", GDELT_ACCESS, "no_results",
                         "GDELT returned no articles naming the hotel in the last ~3 months. "
                         "Its coverage is partial, so this is weak evidence of no coverage.")
    return _envelope("GDELT", GDELT_ACCESS, items=items)


# ------------------------------------------------------------------- Wikipedia

WIKI_ACCESS = (
    "Wikipedia and Wikidata public APIs - free, no key. Wikipedia full-text "
    "search finds pages that name the hotel; Wikidata holds names, former "
    "names, inception dates, official websites and owners with references. "
    "Both are community-edited and only cover notable places.")


def wikipedia_mentions(hotel, city="", lang="en", limit=6):
    q = f'"{hotel}"' + (f" {city.split(',')[0].strip()}" if city else "")
    data, code, err = _get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "list": "search", "srsearch": q, "format": "json",
        "srlimit": limit, "srprop": "snippet|timestamp"})
    if err:
        return _envelope("Wikipedia", WIKI_ACCESS, "unavailable", f"Wikipedia did not answer ({err}).")
    items = []
    for h in (data or {}).get("query", {}).get("search", []):
        snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
        items.append({
            "title": h.get("title"), "snippet": snippet,
            "url": f"https://{lang}.wikipedia.org/wiki/" +
                   urllib.parse.quote(h.get("title", "").replace(" ", "_")),
            "page_updated": evidence.parse_date(h.get("timestamp")),
        })
    if not items:
        return _envelope("Wikipedia", WIKI_ACCESS, "no_results",
                         "No Wikipedia article text names this hotel.")
    return _envelope("Wikipedia", WIKI_ACCESS, items=items)


def wikidata_detail(qid):
    """Names, former names, inception, website, owner for one confirmed entity."""
    data, code, err = _get("https://www.wikidata.org/w/api.php", {
        "action": "wbgetentities", "ids": qid, "format": "json",
        "props": "labels|aliases|descriptions|claims|sitelinks", "languages": "en"})
    if err:
        return _envelope("Wikidata", WIKI_ACCESS, "unavailable", f"Wikidata did not answer ({err}).")
    ent = ((data or {}).get("entities") or {}).get(qid) or {}
    claims = ent.get("claims") or {}

    def vals(pid):
        out = []
        for c in claims.get(pid, []):
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(v, dict) and "time" in v:
                out.append(v["time"].lstrip("+")[:10])
            elif isinstance(v, dict) and "text" in v:
                out.append(v["text"])
            elif isinstance(v, dict) and "id" in v:
                out.append(v["id"])
            elif isinstance(v, str):
                out.append(v)
        return out

    detail = {
        "id": qid, "url": f"https://www.wikidata.org/wiki/{qid}",
        "label": ((ent.get("labels") or {}).get("en") or {}).get("value", ""),
        "description": ((ent.get("descriptions") or {}).get("en") or {}).get("value", ""),
        "aliases": [a.get("value") for a in (ent.get("aliases") or {}).get("en", [])],
        "inception": vals("P571"), "official_website": vals("P856"),
        "official_name": vals("P1448"), "owner_ids": vals("P127"),
        "parent_ids": vals("P749"), "star_rating_ids": vals("P1108"),
        "has_wikipedia": bool((ent.get("sitelinks") or {}).get("enwiki")),
    }
    return _envelope("Wikidata", WIKI_ACCESS, items=[detail])


# --------------------------------------------------------------------- Overpass

OSM_ACCESS = (
    "OpenStreetMap via the public Overpass API - free, no key, ODbL licence. "
    "Gives nearby hotels, transport and attractions with coordinates. Distances "
    "reported here are straight-line, not travel times. Public instance policy: "
    "identify the tool, one query at a time, back off on 429/504.")

# Only the main public instance: the community mirrors tried (kumi.systems,
# private.coffee) timed out on every request when tested, and a hanging
# fallback just doubles the wait.
OVERPASS = ["https://overpass-api.de/api/interpreter"]


def _center(el):
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def osm_context(lat, lon, hotel_name=""):
    """Nearby hotels, stations, attractions around a verified point."""
    if lat is None or lon is None:
        return _envelope("OpenStreetMap context", OSM_ACCESS, "unavailable",
                         "No verified coordinates for the hotel, so local context was not looked up.")
    # Several small queries, not one big one: the public Overpass servers
    # reject or time out heavy requests, and a partial answer that says what
    # is missing beats a blanket failure. A hard deadline keeps one slow
    # server from stretching the whole audit.
    around = lambda r, flt: f"nwr(around:{r},{lat},{lon}){flt};"
    parts = {
        "stations": around(4000, '[railway~"^(station|halt)$"][name]'),
        "hotels": around(2500, '[tourism~"^(hotel|guest_house|hostel|motel|apartment)$"]'),
        "attractions": (around(7000, '[tourism~"^(attraction|museum|theme_park|gallery|zoo)$"][name]')
                        + around(7000, '[historic~"^(castle|manor)$"][name]')),
        "venues": around(6000, '[amenity~"^(conference_centre|events_venue)$"][name]'),
        "airports": around(30000, '[aeroway=aerodrome][iata]'),
    }
    elements, failed, deadline = [], [], time.time() + 70
    for name, body in parts.items():
        if time.time() > deadline:
            failed.append(name)
            continue
        q = f"[out:json][timeout:15];({body});out center tags 80;"
        data, err = None, "not tried"
        for ep in OVERPASS:
            data, code, err = _get(ep, method="POST", data={"data": q}, timeout=(6, 28))
            if code == 429 and time.time() < deadline - 10:
                time.sleep(6)
                data, code, err = _get(ep, method="POST", data={"data": q}, timeout=(6, 28))
            # Overpass answers HTTP 200 with a "remark" and no elements when it
            # ran out of time/memory. That is a failure, not "nothing nearby".
            if data is not None and data.get("remark") and not data.get("elements"):
                err, data = f"server remark: {str(data['remark'])[:60]}", None
            if data is not None or time.time() > deadline:
                break
        if data is None:
            failed.append(name)
        else:
            elements += data.get("elements", [])
        time.sleep(1.2)
    if len(failed) == len(parts):
        return _envelope("OpenStreetMap context", OSM_ACCESS, "unavailable",
                         "The public Overpass servers did not answer. Local context was not "
                         "assessed - this does not mean nothing is nearby.")
    data = {"elements": elements}
    me = evidence.fold(hotel_name)
    hotels, stations, attractions, airports, venues = [], [], [], [], []
    for el in data.get("elements", []):
        t = el.get("tags") or {}
        name = t.get("name")
        la, lo = _center(el)
        if la is None or not name:
            continue
        km = round(haversine_km(lat, lon, la, lo), 2)
        row = {"name": name, "km": km, "osm": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
               "tags": {k: t[k] for k in ("stars", "website", "wheelchair", "rooms", "operator",
                                           "brand", "tourism", "railway", "historic", "leisure",
                                           "amenity", "wikidata", "iata", "network",
                                           "wikipedia", "opening_hours") if k in t}}
        if t.get("aeroway"):
            airports.append(row)
        elif t.get("railway") in ("station", "halt"):
            stations.append(row)
        elif t.get("tourism") in ("hotel", "guest_house", "hostel", "motel", "apartment"):
            if evidence.fold(name) != me:
                hotels.append(row)
        elif t.get("amenity") in ("conference_centre", "events_venue"):
            venues.append(row)
        else:
            attractions.append(row)

    def top(rows, n):
        return sorted(rows, key=lambda r: r["km"])[:n]
    ctx = {"hotels": top(hotels, 25), "stations": top(stations, 5),
           "attractions": top(attractions, 12), "airports": top(airports, 3),
           "venues": top(venues, 6), "origin": {"lat": lat, "lon": lon}}
    if not any(ctx[k] for k in ("hotels", "stations", "attractions", "airports", "venues")):
        if failed:
            return _envelope("OpenStreetMap context", OSM_ACCESS, "unavailable",
                             f"Nothing came back, and {', '.join(failed)} could not be retrieved - "
                             "so this does not show that nothing is nearby.")
        return _envelope("OpenStreetMap context", OSM_ACCESS, "no_results",
                         "OpenStreetMap lists no named stations, attractions or hotels near this point.")
    ctx["failed_parts"] = failed
    return _envelope("OpenStreetMap context", OSM_ACCESS, items=[ctx],
                     reason=(f"Partial: {', '.join(failed)} could not be retrieved from the "
                             "public servers." if failed else ""))


# ---------------------------------------------------------------------- Wayback

WAYBACK_ACCESS = (
    "Internet Archive Wayback availability API - free, no key. Shows whether "
    "and when the hotel's own site was archived; page titles from old "
    "snapshots can reveal previous names. Archive coverage is patchy.")


def wayback_titles(domain, years=(2013, 2017, 2021)):
    """Titles of the homepage as archived near each year - a cheap rebrand signal."""
    items = []
    unavailable = 0
    for y in years:
        data, code, err = _get("https://archive.org/wayback/available",
                               {"url": domain, "timestamp": f"{y}0601"}, timeout=15)
        if err:
            unavailable += 1
            continue
        snap = ((data or {}).get("archived_snapshots") or {}).get("closest")
        if not snap or not snap.get("available"):
            continue
        items.append({"year_asked": y, "timestamp": snap.get("timestamp"),
                      "snapshot_url": snap.get("url"), "title": None})
    if unavailable == len(years):
        return _envelope("Wayback Machine", WAYBACK_ACCESS, "unavailable",
                         "The Internet Archive did not answer; site history was not assessed.")
    if not items:
        return _envelope("Wayback Machine", WAYBACK_ACCESS, "no_results",
                         "No archived snapshots of this domain were found.")
    # de-duplicate snapshots that resolve to the same capture
    seen, uniq = set(), []
    for it in items:
        if it["timestamp"] not in seen:
            seen.add(it["timestamp"])
            uniq.append(it)
    # the archived page's <title> is the cheap rebrand signal; "id_" asks for
    # the original page without the archive's own toolbar markup
    for it in uniq:
        raw = re.sub(r"/web/(\d+)/", r"/web/\1id_/", it["snapshot_url"] or "")
        try:
            r = requests.get(raw, headers={"User-Agent": UA}, timeout=(5, 12))
            if r.status_code == 200:
                m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:60000], re.I | re.S)
                if m:
                    it["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
        except requests.RequestException:
            pass
    return _envelope("Wayback Machine", WAYBACK_ACCESS, items=uniq)


# -------------------------------------------------------------------------- FSA

FSA_ACCESS = (
    "UK Food Standards Agency hygiene ratings - free, no key, UK only. Official "
    "inspection results for restaurants, bars and kitchens, often including a "
    "hotel's own restaurant. Covers food hygiene only, not guest experience.")


FHRS_DESCRIPTOR = {"5": "Very good", "4": "Good", "3": "Generally satisfactory",
                   "2": "Improvement necessary", "1": "Major improvement necessary",
                   "0": "Urgent improvement necessary"}


def fsa_ratings(hotel, postcode="", country_hint_uk=True):
    if not country_hint_uk:
        return _envelope("FSA hygiene ratings", FSA_ACCESS, "unavailable",
                         "Only available for UK establishments.")
    name_tok = (evidence.distinctive_tokens(hotel) or [hotel.split()[0]])[0]
    params = {"name": name_tok, "pageSize": 20}
    if postcode:
        params["address"] = postcode.split()[0] if " " in postcode else postcode[:4]
    data, code, err = _get("https://api.ratings.food.gov.uk/Establishments", params,
                           headers={"x-api-version": "2"})
    if err:
        return _envelope("FSA hygiene ratings", FSA_ACCESS, "unavailable",
                         f"The FSA service did not answer ({err}).")
    pc = evidence.fold(postcode).replace(" ", "")
    variants = evidence.name_variants(hotel)
    items = []
    for e in (data or {}).get("establishments", []):
        btype = (e.get("BusinessType") or "")
        ep = evidence.fold(e.get("PostCode", "")).replace(" ", "")
        same_pc = bool(pc) and ep == pc
        bn = evidence.fold(e.get("BusinessName", ""))
        full_name = any(v in bn for v in variants)
        lodging = bool(re.search(r"hotel|guest|b ?& ?b|bed", btype, re.I))
        # An FSA record belongs to this hotel only on the exact postcode, or when
        # the full hotel name appears in a lodging-type record. A shared first
        # word ("Brooklands College", "Tesco Brooklands") is not enough.
        if not (same_pc or (full_name and lodging)):
            continue
        if same_pc and not (full_name or lodging):
            continue
        rv = e.get("RatingValue")
        items.append({
            "name": e.get("BusinessName"), "type": btype, "rating": rv,
            "descriptor": FHRS_DESCRIPTOR.get(str(rv)),
            "rating_date": evidence.parse_date(e.get("RatingDate")),
            "postcode": e.get("PostCode"), "same_postcode": same_pc,
            "authority": e.get("LocalAuthorityName"),
            "url": f"https://ratings.food.gov.uk/business/{e.get('FHRSID')}",
        })
    if not items:
        return _envelope("FSA hygiene ratings", FSA_ACCESS, "no_results",
                         "No matching food-hygiene record was found for this name and postcode.")
    return _envelope("FSA hygiene ratings", FSA_ACCESS, items=items)


# ---------------------------------------------------------------------- YouTube

YOUTUBE_ACCESS = (
    "YouTube Data API v3 - free quota (10,000 units/day; a search costs 100), "
    "needs an operator API key, no billing account. Returns public video "
    "titles, channels and dates. It does not tell us views-to-sentiment or "
    "what the videos say. Skipped when no key is configured.")


def youtube_search(hotel, city="", api_key=None, max_results=8):
    if not api_key:
        return _envelope("YouTube", YOUTUBE_ACCESS, "not_configured",
                         "No YouTube API key is configured, so video evidence was not assessed.")
    q = f'"{hotel}" {city.split(",")[0].strip()}'.strip()
    data, code, err = _get("https://www.googleapis.com/youtube/v3/search", {
        "part": "snippet", "q": q, "type": "video", "maxResults": max_results, "key": api_key})
    if err:
        why = {403: "The YouTube key was rejected or its daily quota is used up.",
               400: "The YouTube request was rejected (check the key and that the API is enabled)."
               }.get(code, f"YouTube did not answer ({err}).")
        return _envelope("YouTube", YOUTUBE_ACCESS, "unavailable", why)
    items = []
    for it in (data or {}).get("items", []):
        sn = it.get("snippet") or {}
        vid = (it.get("id") or {}).get("videoId")
        if not vid:
            continue
        items.append({"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                      "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                      "published": evidence.parse_date(sn.get("publishedAt")),
                      "description": (sn.get("description") or "")[:300]})
    if not items:
        return _envelope("YouTube", YOUTUBE_ACCESS, "no_results", "YouTube found no matching videos.")
    return _envelope("YouTube", YOUTUBE_ACCESS, items=items)


# --------------------------------------------------------------- access summary

SOURCES = [
    {"name": "Tavily Search", "cost": "Free plan: 1,000 credits/month, no card",
     "needs": "Operator key", "returns": "Search results with titles, URLs, snippets and (news mode) publication dates",
     "limits": "Credits per month; results are a search index, not a complete crawl"},
    {"name": "GDELT DOC 2.0", "cost": "Free", "needs": "Nothing",
     "returns": "Monitored-news article links, titles, publishers, dates, languages",
     "limits": "~3-month window; 1 request per 5 s; may refuse shared server IPs; partial publisher coverage"},
    {"name": "Wikipedia / Wikidata", "cost": "Free", "needs": "Nothing",
     "returns": "Articles naming the hotel; entity names, aliases, inception, website, owner",
     "limits": "Only notable places are present"},
    {"name": "OpenStreetMap (Overpass + Nominatim)", "cost": "Free (ODbL)", "needs": "Nothing",
     "returns": "Hotel records, nearby hotels, stations, attractions, venues with coordinates",
     "limits": "Public servers - one query at a time; straight-line distances only; volunteer-maintained"},
    {"name": "Internet Archive (Wayback)", "cost": "Free", "needs": "Nothing",
     "returns": "Archived snapshots of the hotel's site by date", "limits": "Patchy coverage"},
    {"name": "UK FSA hygiene ratings", "cost": "Free", "needs": "Nothing",
     "returns": "Official food-hygiene inspection results", "limits": "UK only; food hygiene only"},
    {"name": "YouTube Data API v3", "cost": "Free quota (10,000 units/day); no billing", "needs": "Operator key",
     "returns": "Public video titles, channels, dates", "limits": "Optional; skipped without a key"},
    {"name": "Public pages found via the above", "cost": "Free", "needs": "Nothing",
     "returns": "Article text, publisher, date, language - read only where robots.txt allows",
     "limits": "Paywalled or blocking pages are reported as 'not read'"},
]
EXCLUDED_SOURCES = [
    {"name": "TripAdvisor, Booking.com, Expedia reviews/pages", "why": "Terms of Use prohibit automated collection"},
    {"name": "Google Places / Google reviews API", "why": "Requires a billing-enabled Google Cloud account"},
    {"name": "Gemini Google-Search grounding", "why": "Not on the free tier; billing required"},
    {"name": "Amadeus self-service APIs", "why": "Portal decommissioned 2026-07-17"},
    {"name": "Common Crawl", "why": "Presence in a crawl is not evidence that any AI knows or recommends the hotel"},
    {"name": "Google News / Bing / DuckDuckGo result pages", "why": "Automated querying of consumer search pages is against their terms"},
]
