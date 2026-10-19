"""
Named places on a hotel's own pages: railway stations, airports and attractions, found only when they are IDENTIFIABLE.

A word like 'station' or 'gallery' is not a place. 'Charging station' is not a railway station; 'Hotel Info Offers Gallery Location Dining' is a menu, not an attraction; 'Airports' is a heading, not an
airport; 'Hilton Zurich Airport' is the hotel's own name, not the airport it stands beside. A place is accepted only if
  * it has a proper name (capitalised words) and a type word ('Zurich Airport', 'Brooklands Museum', 'Bahnhof Stadelhofen'), or is a well-known airport name;
  * it is not a menu strip, a generic label or the hotel's own name;
  * and a distance or time stated in the same sentence is tied to it, if a distance is to be credited.
Where open map data (OpenStreetMap, already fetched) names the same place, the match is recorded: it validates the name and fixes the type. Without map data the place is accepted as 'named on the
site, not checked against map data'. Nothing is fetched here.
"""

import re

import evidence
from textutil import is_generic_label, looks_like_nav

_TOK = r"[A-ZÀ-Ý][\wÀ-ÿ'’.-]*"
_NAME = rf"(?:{_TOK}(?:\s+(?:de|du|of|von|am|an|im|la|le|el|di|dei|des|der|the)\s+)?\s*){{1,4}}"

# words that make a 'station' or 'airport' something else, or not a place at all
_NOT_STATION_PREFIX = {"charging", "petrol", "gas", "service", "fire", "police", "radio", "weather", "space", "work", "docking", "power", "fuel", "ev", "electric", "nearest", "local", "main", "the", "our",
                       "hotel", "train", "railway", "rail", "metro", "tube", "underground", "central", "airport", "shuttle", "taxi", "valet", "self", "car", "parking", "wi-fi", "wifi", "tv", "gas"}
_NAV_WORDS = {"hotel", "info", "information", "offers", "offer", "gallery", "location", "dining", "rooms", "room", "suites", "contact", "book", "booking", "menu", "login", "honors", "rewards", "search",
              "reviews", "faq", "events", "meetings", "weddings", "spa", "wellness", "careers", "about", "terms", "privacy", "hotels", "destinations", "brands", "stay", "amenities", "facilities", "services",
              "directions", "overview", "deals", "packages", "view", "check", "availability", "reservations", "help", "account", "photos", "sitemap", "language"}

_TABLE_WORDS = {"filters", "filter", "sort", "reset", "apply", "clear", "show", "hide", "select", "results", "search", "name", "banquet", "conference", "theatre", "theater", "classroom", "boardroom", "reception", "capacity", "cabaret", "u-shape", "sqm", "sq", "dimensions", "floor", "ceiling", "height",
                "length", "width", "seats", "layout"}

KNOWN_AIRPORTS = ["Heathrow", "Gatwick", "Stansted", "Luton", "Schiphol", "Charles de Gaulle", "Orly", "Frankfurt", "Munich", "Flughafen Zürich", "Flughafen Zurich", "Kloten", "Fiumicino", "Ciampino",
                  "Barajas", "El Prat", "Dulles", "JFK", "LaGuardia", "Newark", "O'Hare", "Changi", "Narita", "Haneda", "Dubai International", "Hamad International", "Kastrup", "Arlanda", "Gardermoen",
                  "Vaclav Havel", "Ataturk", "Sabiha Gokcen", "Edinburgh", "Manchester", "Birmingham", "Bristol", "Southend", "London City", "Brussels", "Vienna", "Geneva", "Basel"]
_AIRPORT_RX = re.compile(rf"(?P<name>(?:{_TOK}\s+){{1,3}}(?:International\s+|Intl\.?\s+)?(?i:Airport|Flughafen|Aeroport|Aéroport|Aeropuerto|Aeroporto))\b|(?P<name2>(?:Flughafen|Aéroport|Aeroport|Aeropuerto|Aeroporto)\s+{_TOK}(?:\s+{_TOK})?)"
                         rf"|\b(?P<name3>{'|'.join(re.escape(a) for a in KNOWN_AIRPORTS)})\b(?:\s+Airport)?")
_STATION_RX = re.compile(rf"(?P<name>(?:{_TOK}\s+){{1,3}}(?i:(?:Railway|Train|Rail|Metro|Tube|Underground|U-Bahn|S-Bahn|Tram|Bus|Coach)\s+)?(?i:Station|Bahnhof|Hauptbahnhof|Hbf|Stop))\b"
                         rf"|(?P<name2>(?:Bahnhof|Gare(?:\s+de)?|Stazione|Estación(?:\s+de)?)\s+{_TOK}(?:\s+{_TOK})?)"
                         rf"|(?P<name3>{_TOK}\s+(?:HB|Hbf|Hauptbahnhof|Centraal|Central|Termini))\b")
_ATTRACTION_RX = re.compile(rf"(?P<name>(?:{_TOK}\s+){{1,3}}(?i:Museum|Castle|Cathedral|Palace|Zoo|Theme Park|Stadium|Arena|Abbey|Tower|Bridge|Lake|Gardens|Park|Opera House|Old Town|Market|Gallery|Church|Fortress|Temple|Falls|Square|Racecourse|Circuit|Beach|Promenade|Basilica|Monastery|Aquarium|Observatory))\b"
                            rf"|(?P<name2>(?:Museum|Palace|Castle|Lake|Mount|Mt\.?|Fort)\s+(?:of\s+)?{_TOK}(?:\s+{_TOK})?)")
_VENUE_RX = re.compile(rf"(?P<name>(?:{_TOK}\s+){{1,3}}(?:Exhibition Centre|Exhibition Center|Convention Centre|Convention Center|Conference Centre|Congress Centre|Messe|Expo|Arena|Stadium|Business Park))\b")

_DIST = re.compile(r"\b(\d{1,3}(?:[.,]\d)?)\s?[-–]?\s?(?:min(?:ute)?s?|mins)\b(?:\s+(?:by|on|via)\s+\w+|\s+(?:walk|drive|ride|journey|away))?"
                   r"|\b(\d+(?:[.,]\d+)?)\s?(?:km|kilomet(?:re|er)s?|miles?|mi)\b|\b(\d{2,4})\s?(?:m|metres?|meters?)\b(?!\w)"
                   r"|\b(?:walking|driving)\s+distance\b|\bsteps?\s+(?:from|away)\b|\bdirectly\s+(?:at|connected|linked)\b|\bconnected\s+to\b|\bnext\s+to\b|\bopposite\b|\bon\s+site\b", re.I)


def _own_name_run(text, start, name, hotel):
    """True when this candidate is (part of) the hotel's own name: it holds every distinctive word of the hotel's name ('Hilton Zurich Airport'), or the capitalised word right before it is one of them
    ('Hilton' + 'Zurich Airport'). 'from Zurich Airport' is the airport, not the hotel."""
    toks = {t for t in evidence.distinctive_tokens(hotel or "") if len(t) > 2}
    if not toks:
        return False
    cand = set(evidence.fold(name).split())
    if toks <= cand:
        return True
    m = re.search(rf"({_TOK})\s+$", text[:start])
    return bool(m and evidence.fold(m.group(1)) in toks and evidence.fold(m.group(1)) not in cand)


def _clean(name):
    return re.sub(r"\s+", " ", name or "").strip(" .,;:-")


def _ok_name(name, kind, hotel=""):
    """Reject menu strips, generic labels, an own-name run and impossible prefixes."""
    if not name or is_generic_label(name) or looks_like_nav(name):
        return False
    words = re.findall(r"[\wÀ-ÿ'’.-]+", name)
    if len(words) < 2:
        return kind == "airport" and name in KNOWN_AIRPORTS
    first = words[0].lower()
    if any(w.lower() in _TABLE_WORDS for w in words):
        return False                                        # 'Name Banquet Conference Square' is the header row of a meeting-room table
    if kind == "station" and first in _NOT_STATION_PREFIX:
        return False
    if any(w.lower() in _NAV_WORDS for w in words[:-1]):
        return False                                        # 'Hotel Info Offers Gallery' is a menu; 'Hotel' or 'Rooms' inside a name is a nav label
    if kind == "attraction" and first in {"the", "our", "nearby", "local", "visit", "explore", "view", "photo", "see", "all"}:
        return False
    return True


def find(text, kind, hotel=""):
    """
    Named places of one kind in `text` (a sentence or a page): [{name, type, start, end}]. kind: 'station', 'airport', 'attraction' or 'venue'.
    """
    rx = {"station": _STATION_RX, "airport": _AIRPORT_RX, "attraction": _ATTRACTION_RX, "venue": _VENUE_RX}[kind]
    out, seen = [], set()
    for m in rx.finditer(text or ""):
        name = _clean(next((g for g in (m.group("name"), m.groupdict().get("name2"), m.groupdict().get("name3")) if g), ""))
        a = next((m.start(i) for i in (1, 2, 3) if m.group(i)), m.start()) if m.lastindex else m.start()
        lead = name.split()
        while len(lead) > 2 and lead[0].lower() in {"the", "our", "nearby", "local", "visit", "explore", "see", "view"}:      # 'The Johan Cruijff ArenA' at the start of a sentence is the ArenA
            lead = lead[1:]
        name = " ".join(lead)
        if not _ok_name(name, kind, hotel) or _own_name_run(text, m.start(), name, hotel):
            continue
        # the full capitalised run in front of the keyword must not be a menu strip
        run_start = m.start()
        left_words = re.findall(rf"{_TOK}", text[max(0, run_start - 60):run_start])
        if looks_like_nav(" ".join(left_words[-4:] + [name])) and len(left_words) >= 2:
            continue
        typ = "airport" if kind == "airport" else "venue" if kind == "venue" else "attraction" if kind == "attraction" else _station_type(name)
        key = evidence.fold(name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "type": typ, "start": m.start(), "end": m.end()})
    return out


def _station_type(name):
    low = name.lower()
    if re.search(r"\bbus\b|\bcoach\b", low):
        return "bus_station"
    if re.search(r"metro|tube|underground|u-bahn|tram|s-bahn", low):
        return "metro"
    return "railway_station"


def distance_for(sentence, place):
    """
    The distance or time in this sentence that belongs to `place`. 'X miles from Heathrow' ties the figure to the place it precedes; 'Heathrow is X miles away' ties it to the place it follows.
    The nearest figure within 90 characters wins, a figure that leads straight into the place ('17 miles from') ahead of one that merely trails it. '' when there is none.
    """
    best, key = "", None
    for m in _DIST.finditer(sentence or ""):
        before = place["start"] - m.end()
        after = m.start() - place["end"]
        if 0 <= before <= 30 and re.search(r"\b(?:from|to|of|away from)\b", sentence[m.end():place["start"]], re.I):
            k = (0, before)
        elif 0 <= after <= 90:
            k = (1, after)
        elif 0 <= before <= 90:
            k = (2, before)
        else:
            continue
        if key is None or k < key:
            best, key = _clean(m.group(0)), k
    return best


def match_map(place, osm_ctx):
    """Does open map data name the same place? -> {"matched": True|False|None, "type": ..., "km": ...}. None when there is no map data to check against."""
    if not osm_ctx:
        return {"matched": None}
    buckets = {"station": "stations", "airport": "airports", "attraction": "attractions", "venue": "venues"}
    kind = {"railway_station": "station", "metro": "station", "bus_station": "station", "airport": "airport", "attraction": "attraction", "venue": "venue"}.get(place["type"], "attraction")
    pf = {t for t in evidence.distinctive_tokens(place["name"]) if t not in ("station", "airport", "bahnhof", "railway", "museum")} or set(evidence.fold(place["name"]).split())
    for row in osm_ctx.get(buckets[kind], []) or []:
        rf = set(evidence.fold(row.get("name", "")).split())
        if pf and len(pf & rf) / len(pf) >= 0.6:
            return {"matched": True, "type": place["type"], "km": row.get("km"), "map_name": row.get("name")}
    return {"matched": False}


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def mentions(page_text, kind, hotel="", osm_ctx=None):
    """
    Every named place of `kind` on a page, each with the distance stated for it in its own sentence: [{name, type, distance, sentence, map}]. Menu strips and generic labels never appear.
    """
    out = []
    for s in sentences(page_text):
        if looks_like_nav(s) or len(s.split()) < 4:
            continue
        for p in find(s, kind, hotel):
            out.append({"name": p["name"], "type": p["type"], "distance": distance_for(s, p), "sentence": re.sub(r"\s+", " ", s).strip()[:260], "map": match_map(p, osm_ctx)})
    return out
