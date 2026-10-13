"""
Questions for the markets where THIS hotel actually competes.

"Best hotels in Rome" cannot surface a mid-range hotel among hundreds, so asking only that proves nothing. A hotel competes in
narrower markets: near an airport, in a district, at a price level, for something it is known for (a spa, a restaurant, pets,
meetings). This module reads the facts the audit already holds - the hotel's own pages, its map entry, and what the map says is
nearby - works out which of those markets the hotel plausibly belongs to, and writes a few ordinary traveller questions for them.

Rules:
  * Questions NEVER contain the hotel's name (we are testing whether the assistant volunteers it) and are not so exact that
    only this hotel could fit (no street names, no unique features).
  * Every question carries WHY it was asked, drawn from a fact we hold, so the reader can see it is not arbitrary.
  * Nothing is invented: an angle is used only when the evidence for it is in hand; no evidence, no question for that angle.
"""

import re

import ai_sample
import evidence

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_STAR = re.compile(r"\b([1-5]|one|two|three|four|five)[\s-]?star\b", re.I)
_AIRPORT = re.compile(
    r"(?P<name>[A-Z][\w'’.-]+(?:\s+(?:(?:da|de|di|del|della|of|la|le|von|van)\s+)?[A-Z][\w'’.-]+){0,3})\s+(?:International\s+|Int\.\s+)?[Aa]irport\b[^.\d\n]{0,30}?"
    r"(?P<d>\d+(?:[.,]\d+)?)\s*(?P<u>km|kilomet\w+|miles?|mi\b|minutes?|mins?)")
_AIRPORT_AFTER = re.compile(
    r"(?P<d>\d+(?:[.,]\d+)?)\s*(?P<u>km|kilomet\w+|miles?|mi\b|minutes?|mins?)\s+(?:drive\s+|away\s+|by \w+\s+)?(?:from|to)\s+(?:the\s+)?"
    r"(?P<name>[A-Z][\w'’.-]+(?:\s+(?:(?:da|de|di|del|della|of|la|le|von|van)\s+)?[A-Z][\w'’.-]+){0,3})\s+(?:International\s+|Int\.\s+)?[Aa]irport\b")
_DROP_LEAD = {"from", "at", "to", "the", "and", "near", "by", "or", "our", "is", "of", "in", "a"}
MAX_AIRPORT_KM = 25.0

# what a hotel is known for, most distinctive first. (label, phrase for the question, why-label)
FEATURES = [
    ("spa", "Which hotels in {city} have a good spa and wellness area?", "Spa"),
    ("weddings", "Which hotels in {city} are good wedding venues?", "Weddings"),
    ("heritage", "Which historic or characterful hotels are there in {city}?", "Character and heritage"),
    ("afternoon_tea", "Which hotels in {city} are known for afternoon tea?", "Afternoon tea"),
    ("pool", "Which hotels in {city} have a swimming pool?", "Pool"),
    ("meeting_rooms", "Which hotels in {city} are good for business meetings and conferences?", "Meetings and conferences"),
    ("pets", "Which hotels in {city} are pet-friendly?", "Pet-friendly"),
    ("ev", "Which hotels in {city} have EV charging for guests?", "EV charging"),
    ("family", "Which hotels in {city} are best for families with young children?", "Families"),
    ("garden", "Which hotels in {city} have a garden or grounds to relax in?", "Gardens and grounds"),
    ("restaurant", "Which hotels in {city} are known for a good restaurant?", "Dining"),
]


# ------------------------------------------------------------------- facts

def stars_from_text(texts):
    """The star rating the hotel's own pages claim: the figure mentioned most often (None when none is stated)."""
    counts = {}
    for t in texts:
        for m in _STAR.finditer(t or ""):
            v = m.group(1).lower()
            n = int(v) if v.isdigit() else _WORDS.get(v)
            if n:
                counts[n] = counts.get(n, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def airport_from_text(texts, max_km=MAX_AIRPORT_KM):
    """An airport the hotel's own pages say is near, with the distance: ('Findel Airport', 9.0) or None."""
    best = None
    for t in texts:
        for m in list(_AIRPORT.finditer(t or "")) + list(_AIRPORT_AFTER.finditer(t or "")):
            words = [w for w in m.group("name").split() if w.lower() not in _DROP_LEAD]
            if not words:
                continue
            d = float(m.group("d").replace(",", "."))
            unit = m.group("u").lower()
            km = d * 1.609 if unit.startswith("mi") and not unit.startswith("min") else (d * 0.8 if unit.startswith("min") else d)
            if km <= max_km and (best is None or km < best[1]):
                best = (" ".join(words) + " Airport", round(km, 1))
    return best


def airport_from_map(osm_ctx, max_km=MAX_AIRPORT_KM):
    """The nearest named airport the map shows around the hotel, if any."""
    cands = [a for a in (osm_ctx or {}).get("airports", []) if a.get("name") and a.get("km") is not None and a["km"] <= max_km]
    if not cands:
        return None
    a = min(cands, key=lambda x: x["km"])
    return (a["name"], round(float(a["km"]), 1))


def district(entities, city=""):
    """The neighbourhood the map puts the hotel in (a suburb or quarter), when it is not just the town again."""
    for e in entities or []:
        if e.get("source") != "OpenStreetMap" or not e.get("found") or e.get("match_confident") is not True:
            continue
        comp = e.get("address_components") or {}
        for key in ("neighbourhood", "quarter", "suburb", "city_district", "borough"):
            v = (comp.get(key) or "").strip()
            if v and evidence.fold(v) != evidence.fold(city.split(",")[0]) and not v.isdigit() and len(v) > 2:
                return v
    return None


def profile(hotel, city, entities, osm_ctx, own_pages, features, intents):
    """The facts that say where the hotel competes. `features`/`intents` are the rows insight_content already computed from the pages."""
    texts = [p.get("text", "") for p in own_pages or []]
    ap = airport_from_text(texts)
    ap_src = "the hotel's own pages"
    if ap is None:
        ap = airport_from_map(osm_ctx)
        ap_src = "the map"
    return {"district": district(entities, city), "airport": ({"name": ap[0], "km": ap[1], "source": ap_src} if ap else None),
            "stars": stars_from_text(texts),
            "features": [f["key"] for f in features or [] if f.get("level") == "strong"] + [f["key"] for f in features or [] if f.get("level") == "some"],
            "segments": [r["label"] for r in intents or [] if r.get("level") == "strong"]}


# --------------------------------------------------------------- questions

def _safe(text, hotel):
    """Never contains the hotel's name; a normal-length question."""
    core = [t for t in ai_sample._core_tokens(hotel) if len(t) > 3]
    low = evidence.fold(text)
    return text.endswith("?") and len(text) <= 150 and not (core and all(t in low for t in core))


def questions(prof, hotel, city, n=3):
    """Up to n niche questions, each tied to a fact we hold. Order: airport, neighbourhood, price level, then what it is known for."""
    place = (city or "").split(",")[0].strip()
    if not place or not prof:
        return []
    cands = []
    ap = prof.get("airport")
    if ap:
        cands.append(("airport", "Airport", f"Which hotels near {ap['name']} would you recommend, for example before an early flight?",
                      f"{ap['source'].capitalize()} put {ap['name']} {ap['km']:g} km away, so the hotel competes as an airport hotel."))
    if prof.get("district"):
        d = prof["district"]
        cands.append(("district", "Neighbourhood", f"What are the best hotels in {d}, {place}?", f"The map places the hotel in {d}."))
    if prof.get("stars"):
        s = prof["stars"]
        cands.append(("price", "Price level", f"Which {s}-star hotels in {place} offer good value for money?", f"The hotel's own pages describe it as {s}-star."))
    have = set(prof.get("features") or [])
    for key, tmpl, label in FEATURES:
        if key in have:
            cands.append((f"feature_{key}", label, tmpl.format(city=place), f"The hotel's own pages signal {label.lower()} strongly."))
    out, seen = [], set()
    for cid, angle, text, why in cands:
        if len(out) >= n:
            break
        if cid in seen or not _safe(text, hotel):
            continue
        seen.add(cid)
        out.append({"id": f"niche_{cid}", "kind": "niche", "angle": angle, "text": text, "why": why})
    return out
