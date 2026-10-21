"""
Questions for the markets where THIS hotel actually competes, and a reading of what kind of hotel it is.

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


def airport_from_text(texts, max_km=MAX_AIRPORT_KM, hotel=""):
    """An airport the hotel's own pages say is near, with the distance: ('Findel Airport', 9.0) or None."""
    best = None
    for t in texts:
        for m in list(_AIRPORT.finditer(t or "")) + list(_AIRPORT_AFTER.finditer(t or "")):
            words = [w for w in m.group("name").split() if w.lower() not in _DROP_LEAD]
            ht = evidence.fold(hotel).split()
            i = 0
            while i < len(words) and i < len(ht) and evidence.fold(words[i]) == ht[i]:       # "Hilton Zurich Airport is 12 km from..." names the hotel, not the airport: drop the brand words
                i += 1
            if i and i < len(words):
                words = words[i:]
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


def region(entities, city=""):
    """The county or region the map puts the hotel in, when it is not just the town again."""
    for e in entities or []:
        if e.get("source") != "OpenStreetMap" or not e.get("found") or e.get("match_confident") is not True:
            continue
        comp = e.get("address_components") or {}
        v = (comp.get("county") or comp.get("state_district") or "").strip()
        if v and evidence.fold(v) != evidence.fold(city.split(",")[0]) and len(v) > 2 and not v.isdigit():
            return v
    return None


def landmark(osm_ctx, hotel=""):
    """The nearest place people travel to (a mapped attraction with a website, a Wikipedia or Wikidata entry) within 4 km, as {name, km}; None when there is none or its name contains the hotel's own name."""
    core = [t for t in ai_sample._core_tokens(hotel) if len(t) > 3]
    for a in sorted((osm_ctx or {}).get("attractions", []), key=lambda r: r["km"]):
        t = a.get("tags") or {}
        if a["km"] <= 4 and (t.get("website") or t.get("wikidata") or t.get("wikipedia")) and not (core and any(w in evidence.fold(a["name"]) for w in core)):
            return {"name": a["name"], "km": a["km"]}
    return None


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


_VENUE_WORDS = re.compile(r"arena|stadium|stadion|\bdome\b|messe|expo|exhibition|convention|congress|\bRAI\b|concert hall|theatre|theater|racecourse|circuit", re.I)
_NEAR = re.compile(r"(?:\b(?:[1-9]|1\d|20)\s?[-\u2013]?\s?min(?:ute)?s?\b|walking distance|\bsteps?\b|\bnext to\b|\bopposite\b|\badjacent\b|\b(?:[1-2](?:[.,]\d)?|0[.,]\d)\s?km\b|\b\d{2,3}\s?m\b|right (?:by|beside|at))", re.I)


def venue_landmark(own_pages, hotel, osm_ctx=None):
    """
    A stadium, arena, exhibition or concert venue the hotel's OWN pages say is close (a short walk, next to it, within about two kilometres): {name, distance, url} or None. Hotels beside a venue
    are chosen for it ('where to stay for a match or a concert at ...'), which is a far more telling question than a town-wide list. The hotel's own name is never taken as the venue.
    """
    import places
    for p in own_pages or []:
        for kind in ("venue", "attraction"):
            for m in places.mentions(p.get("text", ""), kind, hotel, osm_ctx):
                if _VENUE_WORDS.search(m["name"]) and m.get("distance") and _NEAR.search(m["distance"]):
                    return {"name": m["name"], "distance": m["distance"], "url": p.get("url", ""), "sentence": m["sentence"]}
    return None


def profile(hotel, city, entities, osm_ctx, own_pages, features, intents, hint=None, domain="", classes=None):
    """
    What kind of hotel this is and who it is for, from facts the audit holds: its price tier (stars on its pages, then the brand it belongs to, then its
    own wording), where it sits (an airport, a neighbourhood), and which audiences its pages give evidence for. `features`/`intents` are the rows
    insight_content already computed from the pages. `hint` is what the hotel itself says: {"tier": "luxury|upscale|midscale|budget", "audiences": [keys]}.
    """
    texts = [p.get("text", "") for p in own_pages or []]
    ap = airport_from_text(texts, hotel=hotel)
    ap_src = "the hotel's own pages"
    if ap is None:
        ap = airport_from_map(osm_ctx)
        ap_src = "the map"
    airport = {"name": ap[0], "km": ap[1], "source": ap_src} if ap else None
    stars = stars_from_text(texts)
    level = {r["key"]: r.get("level") for r in intents or []}
    flevel = {r["key"]: r.get("level") for r in features or []}
    prof = {"district": district(entities, city), "region": region(entities, city), "landmark": landmark(osm_ctx, hotel), "airport": airport, "stars": stars,
            "features": [f["key"] for f in features or [] if f.get("level") == "strong"] + [f["key"] for f in features or [] if f.get("level") == "some"],
            "strong_features": [f["key"] for f in features or [] if f.get("level") == "strong"],
            "segments": [r["label"] for r in intents or [] if r.get("level") == "strong"]}
    prof["airport_hotel"] = bool(airport and airport["km"] <= AIRPORT_HOTEL_KM)
    prof["tier"] = tier_of(hotel, domain, stars, level, (hint or {}).get("tier"))
    if classes is not None and (prof["tier"] or {}).get("key") == "luxury" and "luxury" not in classes:
        classes = list(classes) + ["luxury"]
    prof["classes"] = classes                                 # the kinds of hotel the audit decided this is (hotel_class), or None when not worked out
    prof["venue"] = venue_landmark(own_pages, hotel, osm_ctx)
    prof["skipped"] = []
    prof["audiences"] = audiences(prof, level, flevel, (hint or {}).get("audiences"))
    return prof


# ------------------------------------------------------------ tier and audiences

# Brand level is an INFERENCE from the brand's usual market position, used only when the pages state no star rating. Most specific first.
BRAND_TIERS = [
    ("luxury", ("ritz carlton", "four seasons", "mandarin oriental", "waldorf astoria", "st regis", "rosewood", "peninsula", "belmond", "raffles", "fairmont", "park hyatt",
                "conrad", "langham", "corinthia", "dorchester", "bulgari", "lxr", "sofitel legend", "jw marriott", "grand hyatt", "aman")),
    ("budget", ("ibis", "premier inn", "travelodge", "motel one", "b b hotel", "super 8", "days inn", "easyhotel", "campanile", "formule 1", "etap", "red roof")),
    ("midscale", ("hilton garden inn", "hampton", "holiday inn", "courtyard", "fairfield", "novotel", "mercure", "best western", "park inn", "moxy", "leonardo", "aloft")),
    ("upscale", ("doubletree", "hilton", "marriott", "sheraton", "westin", "hyatt", "radisson", "crowne plaza", "renaissance", "sofitel", "pullman", "kimpton", "le meridien",
                 "intercontinental", "melia", "autograph", "curio")),
]
TIER_LABEL = {"luxury": "luxury", "upscale": "upscale", "midscale": "mid-range", "budget": "budget"}
AIRPORT_HOTEL_KM = 15.0


def _fold_words(text):
    return " ".join(re.findall(r"[a-z0-9]+", evidence.fold(text or "")))


def tier_of(hotel, domain, stars, level, stated=None):
    """-> {"key", "label", "why", "source"} or None. The hotel's own statement, then its star rating, then its brand, then its own wording."""
    if stated in TIER_LABEL:
        return {"key": stated, "label": TIER_LABEL[stated], "why": "stated by whoever ran the audit", "source": "stated"}
    if stars:
        key = "luxury" if stars >= 5 else "upscale" if stars == 4 else "midscale" if stars == 3 else "budget"
        return {"key": key, "label": TIER_LABEL[key], "why": f"the hotel's own pages say {stars}-star", "source": "pages"}
    hay = " " + _fold_words(f"{hotel} {domain}") + " "
    for key, brands in BRAND_TIERS:
        hit = next((b for b in brands if f" {b} " in hay), None)
        if hit:
            return {"key": key, "label": TIER_LABEL[key], "why": f"brand level: {hit} is usually {TIER_LABEL[key]} (an inference, no star rating on the pages)", "source": "brand"}
    for key in ("luxury", "budget"):
        if (level or {}).get(key) == "strong":
            return {"key": key, "label": TIER_LABEL[key], "why": f"the hotel's own pages emphasise {key}", "source": "pages"}
    return None


# audience key -> (label, intent keys, feature keys). Listed in the order they are asked about when evidence is equal.
AUDIENCES = [
    ("airport", "Airport and transit stays", ("airport",), ("airport_transfer",)),
    ("business", "Business travellers", ("business",), ()),
    ("meetings", "Meetings and events", ("meetings",), ("meeting_rooms",)),
    ("wellness", "Spa and wellness", ("spa",), ("spa", "pool")),
    ("family", "Families", ("family",), ("family",)),
    ("couples", "Couples and romantic breaks", ("couples",), ()),
    ("weddings", "Weddings", ("weddings",), ("weddings",)),
    ("long_stay", "Long stays", ("long_stay",), ()),
    ("groups", "Groups", ("groups",), ()),
    ("pets", "Pet owners", ("pet",), ("pets",)),
    ("food", "Food and dining", ("food",), ("restaurant", "afternoon_tea")),
    ("city_break", "City breaks", ("city_break",), ()),
    ("heritage", "Character and heritage", (), ("heritage",)),
    ("value", "Value for money", ("budget",), ()),
    ("luxury", "Luxury", ("luxury",), ()),
    ("accessible", "Accessible stays", ("accessible",), ("accessible",)),
    ("ev", "EV drivers", (), ("ev",)),
]
_RANK = {"strong": 2, "some": 1}


# What kind of hotel it takes for a market to be one the hotel competes in. A page that merely mentions spa, 'city' or a restaurant does not make a spa hotel, a city-centre hotel or a dining destination:
# those audiences are asked about only when the hotel's kind (hotel_class) supports them. A fact a hotel simply offers (EV charging, pets, accessible rooms) needs strong evidence on its own pages.
NEEDS_CLASS = {
    "business": {"business", "conference", "airport", "city_centre"}, "meetings": {"business", "conference"}, "wellness": {"spa_hotel", "resort"}, "family": {"family_focused", "resort"},
    "couples": {"spa_hotel", "boutique", "luxury", "resort"}, "weddings": {"resort", "luxury", "boutique", "spa_hotel"}, "food": {"luxury", "boutique", "resort", "spa_hotel"}, "city_break": {"city_centre"},
}
NEEDS_STRONG = {"pets", "ev", "accessible", "long_stay", "groups"}
GATE_WHY = {
    "wellness": "the pages mention a spa or pool, but nothing shows a spa hotel (treatments, sauna, steam room): a gym or a pool does not make one",
    "family": "the pages offer family rooms, but nothing shows a hotel built around families (kids' club, play area)",
    "city_break": "nothing shows the hotel is in the city centre or close to the main sights, so a 'close to the sights' question would not fit it",
    "food": "the restaurant is described, but nothing shows the hotel is known for its dining",
    "couples": "nothing shows a romantic or spa positioning",
    "weddings": "nothing shows the hotel is a wedding venue",
    "business": "nothing shows a business or conference hotel",
    "meetings": "nothing shows a business or conference hotel",
}


def audiences(prof, level, flevel, stated=None):
    """The audiences the hotel plausibly serves, each with the evidence for it, strongest first. Audiences the hotel states for itself come first."""
    out = []
    classes = set(prof.get("classes") or []) if prof.get("classes") is not None else None
    for key, label, ikeys, fkeys in AUDIENCES:
        lv = max([_RANK.get((level or {}).get(k), 0) for k in ikeys] + [_RANK.get((flevel or {}).get(k), 0) for k in fkeys] + [0])
        why = f"the hotel's own pages signal {label.lower()} {'strongly' if lv == 2 else 'somewhat'}"
        if key == "airport":
            ap = prof.get("airport")
            # an airport market only for a hotel that IS near the airport: a page quoting 'Schiphol 18.6 km' does not make an airport hotel
            if ap and ap["km"] <= AIRPORT_HOTEL_KM:
                lv, why = 2, f"{ap['source']} put {ap['name']} {ap['km']:g} km away"
            else:
                if ap and lv and key not in (stated or []):
                    prof.setdefault("skipped", []).append({"key": key, "label": label, "why": f"{ap['name']} is {ap['km']:g} km away (further than {AIRPORT_HOTEL_KM:g} km), too far to be an airport hotel"})
                if key not in (stated or []):
                    continue
        elif key not in (stated or []) and lv:
            tkey = (prof.get("tier") or {}).get("key")
            if key == "luxury" and tkey != "luxury":
                prof.setdefault("skipped", []).append({"key": key, "label": label, "why": f"the hotel is {(prof.get('tier') or {}).get('label', 'not luxury')}, so a luxury question would be answered by palace hotels that are not its competitors"})
                continue
            if key == "value" and tkey not in ("midscale", "budget"):
                prof.setdefault("skipped", []).append({"key": key, "label": label, "why": "the hotel is not mid-range or budget, so 'cheap but clean' is not its market"})
                continue
            if classes is not None and key in NEEDS_CLASS and not (classes & NEEDS_CLASS[key]):
                prof.setdefault("skipped", []).append({"key": key, "label": label, "why": GATE_WHY.get(key, "the hotel's kind does not support it")})
                continue
            if key in NEEDS_STRONG and lv < 2:
                prof.setdefault("skipped", []).append({"key": key, "label": label, "why": "only mentioned in passing on the hotel's pages"})
                continue
        if key in (stated or []):
            out.append({"key": key, "label": label, "level": "stated", "why": "stated by whoever ran the audit as an audience the hotel wants to attract"})
        elif lv:
            out.append({"key": key, "label": label, "level": "strong" if lv == 2 else "some", "why": why})
    order = {k: i for i, (k, *_r) in enumerate(AUDIENCES)}
    out.sort(key=lambda a: ({"stated": 0, "strong": 1, "some": 2}[a["level"]], order[a["key"]]))
    return out


def describe(prof):
    """A plain-language reading of the hotel's market, for the report: {"summary", "tier", "kind", "audiences", "district", "airport"}."""
    if not prof:
        return None
    tier = prof.get("tier")
    kind = "airport hotel" if prof.get("airport_hotel") else "hotel"
    summary = " ".join(x for x in ((tier["label"] + (f" ({prof['stars']}-star)" if prof.get("stars") and tier["source"] != "brand" else "")) if tier else "", kind) if x)
    return {"summary": summary[:1].upper() + summary[1:], "tier": tier, "kind": kind, "audiences": prof.get("audiences", []), "district": prof.get("district"),
            "airport": prof.get("airport"), "stars": prof.get("stars"), "skipped": prof.get("skipped", []), "venue": prof.get("venue")}


# --------------------------------------------------------------- questions

MAX_CUSTOM, CUSTOM_MIN, CUSTOM_MAX = 5, 8, 220


def clean_prompts(raw):
    """The prompts a person typed (a list, or text with one per line): trimmed, 8-220 characters, no control characters, no repeats, at most five."""
    if isinstance(raw, str):
        raw = raw.splitlines()
    out, seen = [], set()
    for p in raw or []:
        t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(p or ""))
        t = re.sub(r"\s+", " ", t).strip().lstrip("-*0123456789.) ").strip()
        key = t.lower()
        if CUSTOM_MIN <= len(t) <= CUSTOM_MAX and key not in seen:
            seen.add(key)
            out.append(t)
    return out[:MAX_CUSTOM]


def custom_questions(prompts):
    """The person's own prompts as questions for the sample, asked exactly as typed (never reworded), each labelled as theirs."""
    return [{"id": f"custom_{i}", "kind": "custom", "angle": "Your prompt", "text": t, "why": "Entered by the person who ran the audit."} for i, t in enumerate(clean_prompts(prompts), 1)]

def _safe(text, hotel):
    """Never contains the hotel's name; a normal-length question."""
    core = [t for t in ai_sample._core_tokens(hotel) if len(t) > 3]
    low = evidence.fold(text)
    return text.endswith("?") and len(text) <= 170 and not (core and all(t in low for t in core))


def _tier_phrase(tier, stars):
    if not tier:
        return ""
    return {"luxury": "luxury ", "upscale": f"{stars}-star " if stars == 4 else "upscale ", "midscale": "mid-range ", "budget": "budget "}[tier["key"]]


def questions(prof, hotel, city, n=8):
    """
    Up to n questions for the markets the hotel competes in: its price level, its location (airport, neighbourhood) and the audiences it serves,
    each worded as a traveller with that need would write it and each tied to a fact we hold. None names the hotel.
    """
    place = (city or "").split(",")[0].strip()
    if not place or not prof:
        return []
    tier, stars = prof.get("tier"), prof.get("stars")
    tp = _tier_phrase(tier, stars)
    ap = prof.get("airport")
    loc = f"near {ap['name']}" if prof.get("airport_hotel") and ap else f"in {place}"
    cands = []
    if tier:
        text = {"luxury": f"Which luxury hotels {loc} are worth the splurge for a special occasion?",
                "upscale": f"Which {tp}hotels {loc} give the best quality for the price?",
                "midscale": f"Which mid-range hotels {loc} are good value for money?",
                "budget": f"Which budget hotels {loc} are clean, comfortable and good value?"}[tier["key"]]
        cands.append(("tier", "Price level", text, f"Hotel level: {tier['label']} ({tier['why']})."))
    have = {a["key"]: a for a in prof.get("audiences") or []}
    district_q = ("district", "Neighbourhood", f"What are the best {tp}hotels in {prof['district']}, {place}?", f"The map places the hotel in {prof['district']}.") if prof.get("district") else None
    templates = {
        "airport": (f"I'm flying out of {ap['name'] if ap else 'the airport'} early tomorrow. Which {tp}hotels nearby have a shuttle and an early breakfast?", "Airport"),
        "business": (f"Which {tp}hotels {loc} are best for business travellers who need good Wi-Fi and a proper desk?", "Business travel"),
        "meetings": (f"Which hotels {loc} have meeting rooms suited to a team workshop or a small conference?", "Meetings and events"),
        "wellness": (f"Which {tp}hotels {loc} have a spa and a pool for a relaxing break?", "Spa and wellness"),
        "family": (f"Which {tp}hotels in {place} work well for a family with young children?", "Families"),
        "couples": (f"Which {tp}hotels in {place} are best for a romantic weekend for two?", "Couples"),
        "weddings": (f"Which hotels in {place} are good for a wedding, with rooms for the guests?", "Weddings"),
        "long_stay": (f"Which hotels or aparthotels in {place} suit a stay of a month or more?", "Long stays"),
        "groups": (f"Which hotels in {place} can handle a group booking of 20 people or more?", "Groups"),
        "pets": (f"Which {tp}hotels in {place} are dog-friendly?", "Pet-friendly"),
        "food": (f"Which hotels in {place} are known for a good restaurant?", "Dining"),
        "city_break": (f"Which {tp}hotels are best for a city break in {place}, close to the main sights?", "City breaks"),
        "heritage": (f"Which historic or characterful hotels are there in {place}?", "Character and heritage"),
        "value": (f"Which hotels in {place} are cheap but still clean and well located?", "Value for money"),
        "luxury": (f"Which luxury hotels in {place} are worth the splurge for a special occasion?", "Luxury"),
        "accessible": (f"Which hotels in {place} have good wheelchair-accessible rooms?", "Accessibility"),
        "ev": (f"Which hotels in {place} have EV charging for guests?", "EV charging"),
    }
    for key in have:
        if key in templates and (key != "airport" or ap):
            text, angle = templates[key]
            cands.append((key, angle, text, f"Audience: {have[key]['label']} ({have[key]['why']})."))
        if key == "airport" and district_q:
            pass
    if district_q:
        cands.insert(1 if tier else 0, district_q)
    vn = prof.get("venue")
    if vn:
        cands.insert(1 if tier else 0, ("venue", "Near a venue", f"Which hotels are best to stay at for an event at {vn['name']}?",
                                          f"The hotel's own pages put {vn['name']} close ({vn['distance']})."))
    lm = prof.get("landmark")
    if lm:
        cands.append(("landmark", "Near a landmark", f"Which hotels are closest to {lm['name']}?", f"The map places {lm['name']} {lm['km']} km from the hotel."))
    rg = prof.get("region")
    if rg and ("wellness" in have or "couples" in have):
        cands.append(("region", "Region", f"Which {tp}hotels in {rg} are best for a romantic spa weekend?" if "wellness" in have else f"Which {tp}hotels in {rg} are best for a romantic weekend away?",
                      f"The map places the hotel in {rg}."))
    out, seen_ids, seen_text = [], set(), set()
    for cid, angle, text, why in cands:
        if len(out) >= n:
            break
        if cid in seen_ids or text in seen_text or not _safe(text, hotel):
            continue
        seen_ids.add(cid)
        seen_text.add(text)
        out.append({"id": f"niche_{cid}", "kind": "niche", "angle": angle, "text": text, "why": why})
    return out
