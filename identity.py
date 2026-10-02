"""
Hotel identity and distribution (checks 1-5).

Check 1  cross-source identity: do the sources agree on name, place and
         domain; namesakes; former names
Check 2  public listing footprint: "listing discovered" kept apart from
         "listing content assessed"
Check 3  listing consistency, only where a listing page could lawfully be read
Check 4  destination-organisation presence and the practical route to enquire
Check 5  booking and distribution evidence (no availability or rate claims)

Absence from our searches is never reported as absence from a platform: a
search index is not a platform directory.
"""

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import evidence
import sourcetypes

# platform -> domain token. Order is display order.
KEY_PLATFORMS = [
    ("Booking.com", "booking.com"), ("Expedia", "expedia."), ("Hotels.com", "hotels.com"),
    ("TripAdvisor", "tripadvisor."), ("Trivago", "trivago."), ("Agoda", "agoda."),
    ("Trip.com", "trip.com"), ("Kayak", "kayak."), ("lastminute.com", "lastminute.com"),
    ("Secret Escapes", "secretescapes."), ("Guest Reservations", "guestreservations."),
    ("Trustpilot", "trustpilot."),
]
BOOKING_ENGINES = {
    "synxis": "SynXis (Sabre)", "travelclick": "TravelClick / Amadeus", "siteminder": "SiteMinder",
    "cloudbeds": "Cloudbeds", "guestline": "Guestline", "avvio": "Avvio", "mirai": "Mirai",
    "littlehotelier": "Little Hotelier", "roomkey": "RoomKey", "bookassist": "BookAssist",
    "newbook": "NewBook", "freetobook": "Freetobook", "fastbooking": "Fastbooking",
    "reservations.": "reservations subdomain", "book.": "booking subdomain", "booking.": "booking subdomain",
    "secure-hotel": "secure booking", "hotelrunner": "HotelRunner", "d-edge": "D-EDGE",
    "resnexus": "ResNexus", "lodgify": "Lodgify", "beds24": "Beds24", "checkfront": "Checkfront",
    "tablebooking": "table booking", "opentable": "OpenTable", "sevenrooms": "SevenRooms",
    "resdiary": "ResDiary", "designmynight": "DesignMyNight",
}
# up to two lodging words ("Spa Hotel"), then an optional "& Spa" - nothing further, so
# "Brooklands Spa Hotel Spa Days" is read as "Brooklands Spa Hotel"
_LODGING_TAIL = (r"(?:\s+(?:hotel|house|inn|lodge|resort|manor|hall|spa)){0,2}"
                 r"(?:\s+(?:&|and)\s+(?:spa|restaurant|bar|grill))?")


def _variant_rx(hotel):
    toks = evidence.distinctive_tokens(hotel)
    if not toks:
        return None
    return re.compile(r"\b" + r"\s+".join(re.escape(t) for t in toks) + _LODGING_TAIL, re.I)


def name_variants_seen(hotel, corpus, entities, own_name, ledger):
    rx = _variant_rx(hotel)
    if rx is None:
        return []
    seen = defaultdict(lambda: {"count": 0, "sources": []})

    lodging = evidence.LODGING_WORDS

    def note(text, source, url=""):
        for m in rx.finditer(text or ""):
            v = re.sub(r"\s+", " ", m.group(0)).strip(" &,-")
            # drop a dangling connector ("Brooklands Hotel and") but keep "& Spa"
            v = re.sub(r"\s+(?:and|&)$", "", v, flags=re.I).strip(" &,-")
            # a bare distinctive word ("Brooklands") is not a name form of the hotel
            if not any(w in lodging for w in evidence.fold(v).split()):
                continue
            key = evidence.fold(v)
            d = seen[key]
            d.setdefault("display", v)
            d["count"] += 1
            if source not in d["sources"]:
                d["sources"].append(source)

    note(own_name, "hotel's own site")
    for e in entities or []:
        if e.get("found"):
            note((e.get("facts") or {}).get("name") or e.get("label") or "", e["source"])
    for c in corpus.get("candidates", []):
        if c["source_type"] in ("own_website",):
            continue
        t = f"{c['title']} {c['snippet']}"
        if evidence.match_hotel(t, hotel, "", "", "")["level"] in ("high", "medium", "low"):
            note(t, c["label"] or c["domain"], c["url"])
    out = [{"variant": d["display"], "count": d["count"], "sources": d["sources"][:6]}
           for d in seen.values()]
    out.sort(key=lambda r: -r["count"])
    return out[:8]


def former_names(hotel, own_pages, arts, wiki_detail, wayback_items, current_title):
    """Candidate previous names with the basis for each. Inferences, labelled."""
    out = []
    rx = re.compile(r"(?:formerly|previously|originally)(?:\s+(?:known\s+as|called|the|named))?\s+"
                    r"(?:the\s+)?([A-Z][\w'’&.-]*(?:\s+[A-Z&][\w'’&.-]*){0,4})")
    rx2 = re.compile(r"(?:renamed|rebranded|re-?launched)\s+(?:as|to)\s+([A-Z][\w'’&.-]*(?:\s+[A-Z&][\w'’&.-]*){0,4})")
    me = evidence.fold(hotel)

    def add(name, basis, source, url=""):
        f = evidence.fold(name)
        if not f or f == me or me in f or f in me:
            return
        if f in ("the", "a"):
            return
        out.append({"name": name.strip(), "basis": basis, "source": source, "url": url})

    for p in own_pages or []:
        for m in list(rx.finditer(p.get("text", ""))) + list(rx2.finditer(p.get("text", ""))):
            add(m.group(1), "wording on the hotel's own site", "hotel's own site", p["url"])
    for a in arts:
        for w in a["windows"]:
            for m in rx.finditer(w):
                add(m.group(1), "wording in an article naming the hotel", a["publisher"], a["url"])
    for d in (wiki_detail or []):
        for al in d.get("aliases", []) + d.get("official_name", []):
            add(al, "alias/official name recorded in Wikidata", "Wikidata", d.get("url", ""))
    cur = evidence.distinctive_tokens(hotel)
    for w in wayback_items or []:
        t = w.get("title")
        if t and cur and not any(tok in evidence.fold(t).split() for tok in cur):
            out.append({"name": t[:80], "basis": f"the homepage title archived near {w.get('year_asked')} "
                        "does not contain the current name - a possible earlier name (inference)",
                        "source": "Internet Archive", "url": w.get("snapshot_url", "")})
    seen, uniq = set(), []
    for r in out:
        k = evidence.fold(r["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq[:6]


def namesakes(hotel, city, corpus, entities):
    """Same name, probably a different place - listed so nothing is mistaken for this hotel."""
    out = []
    town = evidence.fold((city or "").split(",")[0])
    for e in entities or []:
        for cand in e.get("candidates", []) or []:
            if e["source"] == "OpenStreetMap" and cand.get("confident") is False:
                out.append({"name": cand.get("name", "")[:100], "where": "OpenStreetMap",
                            "why": cand.get("why", ""), "url": ""})
            if e["source"] == "Wikidata" and cand.get("id") and cand.get("id") != e.get("id"):
                out.append({"name": f"{cand.get('label', '')} - {cand.get('description', '')}"[:110],
                            "where": "Wikidata", "why": "a different entity with a similar name",
                            "url": f"https://www.wikidata.org/wiki/{cand['id']}"})
    names = evidence.name_variants(hotel)
    for c in corpus.get("candidates", []):
        t = f"{c['title']} {c['snippet']}"
        m = evidence.match_hotel(t, hotel, city, "", "")
        if m["level"] != "medium" or not town or town in evidence.fold(t):
            continue
        # Only a namesake if the name is followed by a DIFFERENT named place
        # ("Brooklands Hotel, Blackpool"). A page that merely omits the town
        # (Instagram, an awards list) is not evidence of another hotel.
        mm = re.search(r"(?:hotel|inn|spa|house|lodge)\s*[,|–—-]*\s*(?:in\s+|near\s+)?"
                       r"([A-Z][a-z]{3,}(?:\s[A-Z][a-z]{3,})?)", t)
        place = mm.group(1) if mm else None
        if place and evidence.fold(place) not in names and evidence.fold(place) != town                 and place.lower() not in ("review", "reviews", "united", "update", "updated", "from"):
            out.append({"name": c["title"][:100], "where": c["label"] or c["domain"],
                        "why": f"shows the name beside {place}, not {city or 'the town'} - "
                               "probably a different hotel", "url": c["url"]})
    seen, uniq = set(), []
    for r in out:
        k = evidence.fold(r["name"])
        if k and k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq[:8]


# --------------------------------------------------------------- listing footprint

def _names_hotel(c, hotel):
    slug = evidence.fold(re.sub(r"[-_/.]+", " ", urlparse(c["url"]).path))
    t = f"{c['title']} {c['snippet']}"
    m = evidence.match_hotel(t, hotel, "", "", "")
    return (m["level"] in ("high", "medium")
            or any(v in slug for v in evidence.name_variants(hotel)))


def listing_footprint(corpus, hotel, city, entities, own_site_links=()):
    """-> rows. Discovered (a page exists in the index) vs content assessed (we read it)."""
    rows, used = [], set()
    town = evidence.fold((city or "").split(",")[0])
    cands = corpus.get("candidates", [])
    for label, token in KEY_PLATFORMS:
        hits = [c for c in cands if token in c["domain"] + "/" and _names_hotel(c, hotel)]
        # prefer a hit that also carries the town (the same name is shared by many hotels)
        hits.sort(key=lambda c: town in evidence.fold(c["title"] + " " + c["snippet"] + " " + c["url"]),
                  reverse=True)
        if hits:
            c = hits[0]
            used.add(c["key"])
            loc = town in evidence.fold(c["title"] + " " + c["snippet"] + " " + c["url"])
            rows.append({"platform": label, "type": "booking / review platform", "discovered": True,
                         "url": c["url"], "title": c["title"][:100],
                         "location_confirmed": loc,
                         "content_assessed": c["read"]["status"] == "read",
                         "note": ("" if c["read"]["status"] == "read" else
                                  "not read: " + c["read"]["why"])})
        else:
            rows.append({"platform": label, "type": "booking / review platform", "discovered": False,
                         "url": "", "title": "", "location_confirmed": None,
                         "content_assessed": False,
                         "note": "not found by our searches - this does not show the hotel is not listed"})
    for c in cands:
        if c["key"] in used or c["source_type"] not in (
                "booking_platform", "hotel_directory", "hotel_group", "destination_body") \
                or not _names_hotel(c, hotel):
            continue
        loc = town in evidence.fold(c["title"] + " " + c["snippet"] + " " + c["url"])
        rows.append({"platform": c["label"] or c["domain"],
                     "type": {"booking_platform": "booking / deals platform",
                              "hotel_directory": "hotel directory",
                              "hotel_group": "hotel group / collection",
                              "destination_body": "destination / tourism site"}[c["source_type"]],
                     "discovered": True, "url": c["url"], "title": c["title"][:100],
                     "location_confirmed": loc,
                     "content_assessed": c["read"]["status"] == "read",
                     "note": "" if c["read"]["status"] == "read" else "not read: " + c["read"]["why"]})
    # one row per platform: a platform often has several pages for the hotel
    best = {}
    for r in rows:
        k = r["platform"]
        if k not in best or (r["discovered"], bool(r["location_confirmed"]), r["content_assessed"]) >                 (best[k]["discovered"], bool(best[k]["location_confirmed"]), best[k]["content_assessed"]):
            best[k] = r
    rows = list(best.values())
    for e in entities or []:
        if e["source"] in ("OpenStreetMap", "Wikidata"):
            rows.append({"platform": e["source"], "type": "map / open data", "discovered": bool(e.get("found")),
                         "url": e.get("url", ""), "title": (e.get("display_name") or e.get("label") or "")[:100],
                         "location_confirmed": e.get("match_confident"),
                         "content_assessed": bool(e.get("found") and e.get("facts")),
                         "note": (e.get("note") or "")[:140]})
    for lk in own_site_links:
        if "google." in lk["domain"] and "map" in lk["url"]:
            rows.append({"platform": "Google Maps", "type": "map / open data", "discovered": True,
                         "url": lk["url"], "title": "linked from the hotel's own site",
                         "location_confirmed": True, "content_assessed": False,
                         "note": "linked from the hotel's website; the Google listing itself was not read"})
            break
    return rows


# --------------------------------------------------------- listing consistency

_TEL = re.compile(r"(?:\+44|\(?0)\s?\d[\d\s()-]{8,13}\d")
_STAR = re.compile(r"\b([1-5])[- ]?star", re.I)
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def _digits(s):
    return re.sub(r"\D", "", s or "")


def listing_consistency(corpus, hotel, own_facts, own_pages, ledger):
    """
    Differences between the hotel's own facts and listing pages we were allowed
    to read. Both sources are attached to every difference. Nothing is compared
    from pages that were not read.
    """
    rows, compared = [], 0
    own_tel = _digits((own_facts or {}).get("telephone"))
    own_pc = evidence.fold((own_facts or {}).get("address", "")).replace(" ", "")
    own_stars = Counter(m.group(1) for p in own_pages or [] for m in _STAR.finditer(p.get("text", "")))
    own_star = own_stars.most_common(1)[0][0] if own_stars else None
    for c in corpus.get("candidates", []):
        if c["read"]["status"] != "read" or c["match"]["level"] != "high":
            continue
        if c["source_type"] not in ("hotel_directory", "booking_platform", "hotel_group",
                                    "destination_body"):
            continue
        compared += 1
        text = " ".join(c["page"].get("windows") or []) + " " + c["page"].get("text_head", "")
        src = c["label"] or c["domain"]
        tels = {_digits(t) for t in _TEL.findall(text)}
        if own_tel and tels and not any(own_tel[-9:] == t[-9:] for t in tels if len(t) >= 9):
            eid = ledger.add(url=c["url"], source=src, source_type=c["source_type"],
                             extract="Telephone shown: " + ", ".join(sorted(tels))[:120],
                             kind="observed", match="high", via=c["via"])
            rows.append({"field": "Telephone", "own": (own_facts or {}).get("telephone"),
                         "other": ", ".join(sorted(tels))[:60], "source": src, "url": c["url"],
                         "evidence_id": eid})
        pcs = {evidence.fold(p).replace(" ", "") for p in _POSTCODE.findall(text.upper())}
        if own_pc and pcs and not any(p and p in own_pc for p in pcs):
            eid = ledger.add(url=c["url"], source=src, source_type=c["source_type"],
                             extract="Postcode shown: " + ", ".join(sorted(pcs))[:60],
                             kind="observed", match="high", via=c["via"])
            rows.append({"field": "Postcode", "own": (own_facts or {}).get("address"),
                         "other": ", ".join(sorted(pcs)), "source": src, "url": c["url"],
                         "evidence_id": eid})
        stars = {m.group(1) for m in _STAR.finditer(text)}
        if own_star and stars and own_star not in stars:
            eid = ledger.add(url=c["url"], source=src, source_type=c["source_type"],
                             extract=f"Star rating shown: {', '.join(sorted(stars))}-star",
                             kind="observed", match="high", via=c["via"])
            rows.append({"field": "Star rating", "own": f"{own_star}-star (hotel's site)",
                         "other": ", ".join(sorted(stars)) + "-star", "source": src, "url": c["url"],
                         "evidence_id": eid})
    return {"rows": rows, "pages_compared": compared}


# ------------------------------------------------------------------ distribution

def booking_links(pages_html_links):
    """Booking engines/partners linked from the hotel's own pages."""
    out, seen = [], set()
    for lk in pages_html_links or []:
        dom = evidence.domain_of(lk["url"])
        low = (dom + lk["url"]).lower()
        for tok, label in BOOKING_ENGINES.items():
            if tok in low and dom not in seen:
                seen.add(dom)
                out.append({"domain": dom, "engine": label, "url": lk["url"],
                            "anchor": lk.get("anchor", "")[:60]})
                break
    return out
