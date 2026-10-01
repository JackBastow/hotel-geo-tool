"""
Trust, reputation and consistency check (audit spec sections 5 and 6).

No API key needed. Fetches external listing pages (TripAdvisor, Booking.com,
Google Maps, etc.) and reads the same kind of public, sanctioned JSON-LD
structured data that site_check.py already reads from the hotel's own site -
AggregateRating, review counts, address, phone, check-in/out times.

Why JSON-LD and not the rendered page: most listing sites embed this data for
their own SEO, so it's a stable, machine-readable, ToS-safe way to read
review counts and facts without scraping rendered HTML or fighting
JavaScript. It also means the same extraction code as site_check.py applies
here unchanged.

What this cannot do: sites that block simple requests, or that only render
this data client-side with JavaScript, will come back with nothing. That is
reported honestly as "unable to verify" - never inferred as "no reviews" or
"consistent by default". Silence is not evidence.

Where the URLs come from: the AI visibility run already surfaces exactly the
domains worth checking, as a side effect of the "which sources did the
engine cite" data it collects (store.py's cached run history). This module
takes a URL list from any source - auto-suggested from that history, or
pasted in directly.
"""

import re
import time
import urllib.parse

import requests

from site_check import _extract_jsonld, _types, get, UA  # reuse, don't duplicate

# Fields worth comparing across sources. Same shape as site_check's
# LODGING_PROPS but scoped to what's realistic to find on a listing page.
COMPARE_FIELDS = ["name", "telephone", "checkinTime", "checkoutTime", "priceRange"]

# Words that make a Wikidata entity description look like somewhere you sleep,
# used to stop a same-named magazine/theatre/ship being taken for the hotel.
LODGING_WORDS = (
    "hotel", "inn", "resort", "guest house", "guesthouse", "bed and breakfast",
    "lodge", "motel", "hostel", "accommodation", "spa",
)

REPUTATION_DOMAINS_HINT = [
    "tripadvisor", "booking.com", "google.com/maps", "google.com/travel",
    "expedia", "hotels.com",
]


def suggest_urls_from_citations(top_cited_domains, limit=6):
    """
    Turn a list of {"domain": ..., "queries_citing": ...} (from an AI
    visibility run's metrics) into candidate https:// URLs worth checking.
    This is a domain, not a working page - the user may need to search that
    domain for the hotel's specific listing page. Flagged as such in the UI.
    """
    out = []
    for d in top_cited_domains:
        dom = d.get("domain", "")
        if not dom or dom in out:
            continue
        # skip generic aggregators/news sites unlikely to hold structured
        # per-hotel review data worth cross-checking
        out.append(dom)
    return out[:limit]


def _find_node_of_type(jsonld_blocks, type_names):
    wanted = {t.lower() for t in type_names}
    hit = []

    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            ts = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if any(isinstance(x, str) and x.lower() in wanted for x in ts):
                hit.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for b in jsonld_blocks:
        walk(b)
    return hit


def check_url(url):
    """Fetch one external URL and extract whatever structured data exists."""
    out = {"url": url, "ok": False, "status": None, "reachable": False}
    r = get(url)
    if r is None:
        out["error"] = "request failed (timeout, DNS, or connection refused)"
        return out
    out["status"] = r.status_code
    if r.status_code != 200:
        out["error"] = f"HTTP {r.status_code}"
        return out
    out["reachable"] = True
    html = r.text
    jsonld = _extract_jsonld(html)
    if not jsonld:
        out["ok"] = True
        out["note"] = (
            "Page reachable but no JSON-LD found. Either this page doesn't "
            "publish structured data, or it's rendered client-side by "
            "JavaScript - common on TripAdvisor and Booking.com. Not "
            "evidence of anything about the hotel itself."
        )
        return out

    out["ok"] = True
    out["schema_types"] = sorted({t for b in jsonld for t in _types(b)})

    rating_nodes = _find_node_of_type(jsonld, ["AggregateRating"])
    if rating_nodes:
        rn = rating_nodes[0]
        out["rating"] = {
            "ratingValue": rn.get("ratingValue"),
            "reviewCount": rn.get("reviewCount") or rn.get("ratingCount"),
            "bestRating": rn.get("bestRating"),
        }

    lodging_nodes = _find_node_of_type(
        jsonld, ["Hotel", "LodgingBusiness", "Resort", "Place", "LocalBusiness"]
    )
    if lodging_nodes:
        ln = lodging_nodes[0]
        out["facts"] = {k: ln.get(k) for k in COMPARE_FIELDS if ln.get(k)}
        addr = ln.get("address")
        if isinstance(addr, dict):
            out["facts"]["address"] = ", ".join(
                str(addr.get(k, "")) for k in
                ("streetAddress", "addressLocality", "postalCode")
                if addr.get(k)
            )
        # embedded AggregateRating sometimes sits inside the lodging node
        # rather than as a standalone top-level block
        if not rating_nodes and isinstance(ln.get("aggregateRating"), dict):
            ar = ln["aggregateRating"]
            out["rating"] = {
                "ratingValue": ar.get("ratingValue"),
                "reviewCount": ar.get("reviewCount") or ar.get("ratingCount"),
                "bestRating": ar.get("bestRating"),
            }
    return out


def _norm(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def _parse_clock_minutes(s):
    """'3:00 PM' / '15:00' / '3pm' -> minutes since midnight, or None."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


_STREET_ABBREV = {
    "dr": "drive", "rd": "road", "st": "street", "ave": "avenue", "av": "avenue",
    "ln": "lane", "sq": "square", "pl": "place", "ct": "court", "cres": "crescent",
    "gdns": "gardens", "pk": "park", "hwy": "highway", "bldg": "building",
}

# UK postcode, loosely: it only has to be good enough to spot the same one
# written two ways, not to validate deliverability.
_UK_POSTCODE = re.compile(r"\b([a-z]{1,2}\d[a-z\d]?)\s*(\d[a-z]{2})\b", re.I)


def _expand_street(token):
    return _STREET_ABBREV.get(token, token)


def _uk_postcode(s):
    """Normalised UK postcode found in the string, or '' - e.g. 'kt130sl'."""
    m = _UK_POSTCODE.search(s or "")
    return (m.group(1) + m.group(2)).lower() if m else ""


def compare_fact(field, own_value, other_value):
    """Classifies per spec section 5: consistent / minor / significant / unable."""
    a, b = _norm(own_value), _norm(other_value)
    if not a or not b:
        return "unable to verify"
    if a == b:
        return "consistent"
    if field in ("checkinTime", "checkoutTime"):
        # "3:00 PM" must equal "15:00" - compare as actual clock times, not
        # digit strings, or every 12-hour vs 24-hour pair false-flags.
        ma, mb = _parse_clock_minutes(a), _parse_clock_minutes(b)
        if ma is not None and mb is not None:
            return "consistent" if ma == mb else "significant discrepancy"
        return "unable to verify"  # couldn't parse either format confidently
    if field == "telephone":
        # Known limitation: "01932 123456" vs "+44 1932 123456" is the same
        # number in national vs international format but won't digit-match
        # (the +44 replaces the leading 0). Proper handling needs a phone
        # number library; this will over-report "significant discrepancy"
        # for that specific case. Worth eyeballing before treating a phone
        # mismatch here as real.
        da = re.sub(r"[^0-9]", "", a)
        db = re.sub(r"[^0-9]", "", b)
        # tolerate the +44/0 swap: compare the last 9-10 digits (the part
        # that's actually the subscriber number) rather than the full string
        if da and db and da[-9:] == db[-9:]:
            return "consistent"
        return "significant discrepancy"
    if field == "address":
        # Plain token overlap (Jaccard) punishes a SHORTER address for being
        # shorter: "Brooklands Drive, Weybridge" vs "Brooklands Dr, Weybridge,
        # Surrey KT13 0SL" scored 0.29 and came out "significant discrepancy",
        # which is a false flag on what is plainly the same address. Listing
        # sites routinely carry a fuller or more abbreviated form than the
        # hotel's own site, so that case is the norm, not the exception.
        #
        # Postcode first (highest signal), then containment rather than
        # symmetric overlap, after normalising street-type abbreviations.
        pa, pb = _uk_postcode(a), _uk_postcode(b)
        if pa and pb:
            return "consistent" if pa == pb else "significant discrepancy"

        a_tokens = {_expand_street(t) for t in re.findall(r"[a-z0-9]+", a)}
        b_tokens = {_expand_street(t) for t in re.findall(r"[a-z0-9]+", b)}
        if not a_tokens or not b_tokens:
            return "unable to verify"
        # containment: how much of the SHORTER address appears in the longer
        containment = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
        if containment >= 0.8:
            return "consistent"
        if containment >= 0.5:
            return "minor discrepancy"
        return "significant discrepancy"
    return "minor discrepancy"


# --------------------------------------------------------------- open data
#
# The OTA listing sites this module was written for (TripAdvisor, Booking.com,
# hotel brand sites) return 403 or a bot challenge to any automated request -
# verified live Sept 2026: TripAdvisor 403, Hilton 403, Booking.com 202, and
# nothing useful from any of them. That is an access control they have chosen
# to apply, so this module does not try to defeat it by pretending to be a
# browser. It reports them as blocked and gets its entity data from sources
# that publish open data and welcome automated access instead.
#
# These two matter for AI discoverability in their own right:
#   OpenStreetMap - feeds Apple Maps and a long tail of apps and AI tools
#   Wikidata      - feeds Google's Knowledge Graph and is heavily represented
#                   in LLM training data
# A hotel missing from either is a concrete, fixable gap, and both are free
# and need no key.

OSM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
WIKIDATA_ENDPOINT = "https://www.wikidata.org/w/api.php"

# site_check's UA starts "Mozilla/5.0 (compatible; ...)". Wikimedia's user
# agent policy rejects browser-mimicking strings and asks for a tool name and
# a way to make contact - with the shared UA, Wikidata returned 403. This one
# complies rather than works around it. Nominatim asks for the same thing.
OPEN_DATA_UA = (
    "HotelDiscoverabilityAudit/1.0 "
    "(local hotel AI-visibility audit tool; run by the site owner)"
)


def _get_json(url, params):
    """GET an open-data endpoint with a policy-compliant UA. Returns (data, error)."""
    try:
        r = requests.get(url, params=params,
                         headers={"User-Agent": OPEN_DATA_UA,
                                  "Accept": "application/json"},
                         timeout=25)
    except requests.RequestException as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json(), None
    except ValueError:
        return None, "response was not JSON"


def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def check_openstreetmap(hotel, city="", postcode="", lat=None, lon=None):
    """
    Look the hotel up in OpenStreetMap via Nominatim. No key needed.

    Verified against a known location where one is available, because hotel
    names repeat: searching "Brooklands Hotel" with no location returns the
    Blackpool one, which has nothing to do with the Weybridge hotel being
    audited. Reporting that as "your hotel is in OpenStreetMap" would be
    worse than reporting nothing. Match confidence is therefore explicit:
    True (verified), False (a candidate exists but does not match the known
    location), or None (no location available to check it against).
    """
    out = {"source": "OpenStreetMap", "found": False, "facts": {},
           "match_confident": None}
    q = f"{hotel}, {city}".strip(", ")
    hits, err = _get_json(OSM_ENDPOINT, {
        "q": q, "format": "jsonv2", "extratags": 1, "addressdetails": 1, "limit": 3,
    })
    if err:
        out["error"] = err
        return out
    if not hits:
        out["note"] = (
            "Not found in OpenStreetMap. OSM feeds Apple Maps and many apps "
            "and AI tools; an absent hotel is invisible to all of them."
        )
        return out

    # Score every candidate against whatever location we know, strongest
    # signal first: coordinates, then postcode, then city name.
    def verify(h):
        if lat is not None and lon is not None and h.get("lat") and h.get("lon"):
            try:
                km = _haversine_km(lat, lon, float(h["lat"]), float(h["lon"]))
            except (TypeError, ValueError):
                km = None
            if km is not None:
                return (True, f"{km:.1f}km from the location on the hotel's own site") \
                    if km <= 2.0 else \
                    (False, f"{km:.0f}km from the location on the hotel's own site")
        a = h.get("address") or {}
        if postcode:
            hp = _uk_postcode(a.get("postcode", "") or h.get("display_name", ""))
            if hp:
                return (hp == _uk_postcode(postcode),
                        f"postcode {a.get('postcode') or hp}")
        if city:
            city_tokens = {t for t in re.findall(r"[a-z]{3,}", city.lower())}
            hay = " ".join(str(v) for v in a.values()).lower() + " " + \
                  h.get("display_name", "").lower()
            hay_tokens = set(re.findall(r"[a-z]{3,}", hay))
            if city_tokens:
                return (bool(city_tokens & hay_tokens), "matched on town name")
        return (None, "no location available to verify against")

    verified = [(h,) + verify(h) for h in hits]
    best = next((v for v in verified if v[1] is True), None) \
        or next((v for v in verified if v[1] is None), None) \
        or verified[0]
    h, confident, why = best

    et = h.get("extratags") or {}
    addr = h.get("address") or {}
    out["found"] = True
    out["match_confident"] = confident
    out["match_reason"] = why
    out["url"] = f"https://www.openstreetmap.org/{h.get('osm_type')}/{h.get('osm_id')}"
    out["display_name"] = h.get("display_name", "")
    out["facts"] = {k: v for k, v in {
        "name": h.get("name") or (h.get("display_name", "").split(",")[0]),
        "telephone": et.get("phone") or et.get("contact:phone"),
        "url": et.get("website") or et.get("contact:website"),
        "address": ", ".join(
            str(addr[k]) for k in ("road", "town", "city", "postcode") if addr.get(k)
        ),
    }.items() if v}
    out["osm_type"] = h.get("type")
    # Raw address components. When this match is coordinate-verified these are
    # trustworthy place names for the hotel, and are the best way to check a
    # Wikidata hit: a town sits inside a borough and a county that its own
    # address never mentions (Weybridge is in Elmbridge, Surrey), so comparing
    # the user's city string alone produces false negatives.
    out["address_components"] = {k: str(v) for k, v in addr.items()
                                 if isinstance(v, (str, int))}
    out["candidates"] = [
        {"name": c.get("display_name", "")[:120], "confident": conf, "why": w}
        for c, conf, w in verified
    ]

    if confident is False:
        # A real entry, but for a different hotel with the same name. Saying
        # "found" here would tell a hotel it is mapped when it is not.
        out["found"] = False
        out["note"] = (
            f"**Probably NOT this hotel.** OpenStreetMap has a '{hotel}', but "
            f"it is {why}. Hotel names repeat across the country. Treat this "
            "as not mapped unless you confirm otherwise from the candidates."
        )
        out["facts"] = {}
    elif confident is None:
        out["note"] = (
            "Found by name, but there was no address, postcode or map link on "
            "the hotel's own site to check it against - so this may be a "
            "different hotel with the same name. Confirm before relying on it."
        )
        out["facts"] = {}  # never feed an unverified entity into fact comparison
    return out


def check_wikidata(hotel, city="", place_tokens=None):
    """
    Look the hotel up in Wikidata. No key needed.

    Wikidata search matches on NAME only, and hotel names repeat all over the
    country - searching "Brooklands Hotel" returns a hotel in Dawlish, Devon,
    which has nothing to do with the one in Weybridge. A confidently-wrong
    entity match is worse than no match, so every hit is scored against the
    city before being presented as this hotel's entity.
    """
    out = {"source": "Wikidata", "found": False, "facts": {}}
    data, err = _get_json(WIKIDATA_ENDPOINT, {
        "action": "wbsearchentities", "search": hotel, "language": "en",
        "format": "json", "limit": 5,
    })
    if err:
        out["error"] = err
        return out
    hits = (data or {}).get("search", [])
    if not hits:
        out["note"] = (
            "No Wikidata entity. Wikidata feeds Google's Knowledge Graph and is "
            "well represented in LLM training data, so an absent hotel has no "
            "canonical machine-readable identity to attach facts to."
        )
        return out

    # A hit has to look like a HOTEL and sit in the right place. Checking the
    # city alone is not enough: searching "The Savoy" with city "London"
    # matched Q2110467, an 1896 London literary magazine, purely because
    # "london" appeared in its description.
    # The user's city string, plus any wider place names a verified
    # OpenStreetMap match supplied (borough, county, region). Without those,
    # "Weybridge" fails to match the real entity described as "hotel in
    # Elmbridge, Surrey" - a false "not in Wikidata" on a hotel that is.
    city_tokens = {t for t in re.findall(r"[a-z]{3,}", (city or "").lower())}
    city_tokens |= {t.lower() for t in (place_tokens or []) if len(t) >= 3}
    city_tokens -= {"england", "scotland", "wales", "kingdom", "united", "uk",
                    "great", "britain"}  # too broad to distinguish anything

    def score(h):
        desc = (h.get("description") or "").lower()
        desc_tokens = set(re.findall(r"[a-z]{3,}", desc))
        looks_lodging = any(w in desc for w in LODGING_WORDS)
        in_city = bool(city_tokens & desc_tokens)
        # lodging is the harder requirement - a hotel in the wrong town beats
        # a magazine in the right one, and neither is presented as confident.
        return (2 if looks_lodging else 0) + (1 if in_city else 0)

    ranked = sorted(hits, key=score, reverse=True)
    best = ranked[0]
    confident = score(best) == 3  # looks like lodging AND matches the city

    out["found"] = True
    out["id"] = best.get("id")
    out["url"] = f"https://www.wikidata.org/wiki/{best.get('id')}"
    out["label"] = best.get("label", "")
    out["description"] = best.get("description", "")
    out["match_confident"] = confident
    out["candidates"] = [
        {"id": h.get("id"), "label": h.get("label", ""),
         "description": h.get("description", "")}
        for h in hits
    ]
    if confident:
        out["note"] = (
            "Matched by name, and the entity description mentions the city "
            "given - so this is probably the right hotel. Still worth a look."
        )
    elif city_tokens:
        out["note"] = (
            "**Probably NOT this hotel.** Wikidata matched the name, but no "
            f"returned entity both reads as somewhere to stay and mentions "
            f"'{city}'. Names repeat across the country, and unrelated things "
            "share them too. Treat this as 'no Wikidata entity found' unless "
            "you confirm otherwise from the candidates below."
        )
        out["found"] = False  # never let a wrong entity feed the fact comparison
    else:
        out["note"] = (
            "Matched by name only, with no city given to check it against. "
            "Confirm the label and description describe this hotel."
        )
    return out


def run_external_check(urls, own_lodging_node, progress=None, hotel="", city="",
                       location=None):
    """
    own_lodging_node: the "lodging_node" dict from site_check.py's output
    (the hotel's own JSON-LD Hotel/LodgingBusiness node), or None.
    hotel/city: if given, the open-data sources (OpenStreetMap, Wikidata) are
    checked too. These need no URL and are the only sources that reliably
    return anything, so the tab is useful with no listing URLs at all.

    Returns: {"sources": [...], "consistency": [...], "reputation": [...],
              "entities": [...], "blocked_sources": [...]}
    """
    sources = []
    for i, url in enumerate(urls, 1):
        if progress:
            progress(f"Checking {i}/{len(urls)}: {url}")
        sources.append(check_url(url))
        time.sleep(0.5)

    # --- open data sources: no key, no URL, and they actually respond
    entities = []
    if hotel:
        if progress:
            progress("Checking OpenStreetMap...")
        loc = location or {}
        entities.append(check_openstreetmap(
            hotel, city or loc.get("city", ""),
            postcode=loc.get("postcode", ""),
            lat=loc.get("lat"), lon=loc.get("lon"),
        ))
        time.sleep(1.1)  # Nominatim asks for max 1 request/second - respect it

        # Feed the verified OSM place names into the Wikidata check.
        osm = entities[-1]
        place_tokens = []
        if osm.get("match_confident") is True:
            for k, v in (osm.get("address_components") or {}).items():
                if k in ("suburb", "village", "town", "city", "municipality",
                         "county", "state_district", "state", "region"):
                    place_tokens += re.findall(r"[A-Za-z]{3,}", v)

        if progress:
            progress("Checking Wikidata...")
        entities.append(check_wikidata(hotel, city or loc.get("city", ""),
                                       place_tokens=place_tokens))

    # --- sources that refused automated access, reported honestly rather than
    #     silently producing an empty consistency table
    blocked_sources = [
        {"url": s["url"], "domain": _domain(s["url"]),
         "status": s.get("status"), "error": s.get("error")}
        for s in sources
        if not s.get("reachable")
    ]

    reputation = []
    for s in sources:
        if s.get("rating"):
            reputation.append({
                "source": s["url"], "domain": _domain(s["url"]),
                **s["rating"],
            })

    consistency = []
    if own_lodging_node:
        own_facts = dict(own_lodging_node)
        addr = own_facts.get("address")
        if isinstance(addr, dict):
            own_facts["address"] = ", ".join(
                str(addr.get(k, "")) for k in
                ("streetAddress", "addressLocality", "postalCode")
                if addr.get(k)
            )
        # Listing pages and open-data entities compare identically - both are
        # just "somewhere else that states a fact about this hotel".
        comparables = [
            (s["url"], _domain(s["url"]), s.get("facts") or {}) for s in sources
        ] + [
            (e.get("url", ""), e["source"], e.get("facts") or {})
            for e in entities if e.get("found")
        ]

        for src_url, src_label, other_facts in comparables:
            if not other_facts:
                continue
            for field in COMPARE_FIELDS + ["address"]:
                ov = own_facts.get(field)
                nv = other_facts.get(field)
                if ov is None and nv is None:
                    continue
                verdict = compare_fact(field, ov, nv)
                consistency.append({
                    "field": field, "source": src_url, "domain": src_label,
                    "own_site_value": ov or "(not found)",
                    "other_source_value": nv or "(not found)",
                    "verdict": verdict,
                })

    return {
        "sources": sources,
        "consistency": consistency,
        "reputation": reputation,
        "entities": entities,
        "blocked_sources": blocked_sources,
    }


def _domain(url):
    from gemini_client import resolve_domain
    return resolve_domain(url)
