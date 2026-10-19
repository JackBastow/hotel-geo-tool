"""
What kind of hotel is this? A hotel can be several things at once (an airport hotel that is also a business hotel). The answer decides which traveller segments and which information deserve priority,
and which commercial 'opportunities' are not worth raising at all.

Every class comes from evidence on the hotel's own pages or in its name and open map data, and carries the reasons. Nothing is inferred from a facility that is not the thing itself: a gym is not a spa,
a restaurant is not a wedding venue, a family room is not a family hotel.

  classify(site, features, intents, osm_ctx, hotel, prof) -> {"classes": [{key, label, strength, reasons}], "keys": [...]}
  relevance(classes, segment) -> 'core' | 'secondary' | 'skip'   how much a traveller segment matters to this kind of hotel
"""

import re

import evidence
import pagetarget
import places

LABELS = {"airport": "Airport hotel", "business": "Business hotel", "conference": "Conference hotel", "city_centre": "City-centre hotel", "resort": "Resort", "spa_hotel": "Spa hotel",
          "luxury": "Luxury hotel", "boutique": "Boutique hotel", "family_focused": "Family-focused hotel"}

_AIRPORT_TEXT = re.compile(r"airport hotel|at the airport|inside the airport|within the airport|next to (?:the )?(?:airport|terminal)|connected to (?:the )?(?:airport|terminal)|walking distance (?:to|from) (?:the )?(?:airport|terminal)"
                           r"|(?:\d+|few|five|ten) minutes?(?: walk)? (?:from|to) (?:the )?(?:airport|terminal)|airport (?:shuttle|transfer)s?|park (?:and|&) fly|stopover|layover|flight crew|early (?:flight|departure)", re.I)
_BUSINESS_TEXT = re.compile(r"business (?:travel|guests?|travellers?|traveler|centre|center|stays?|facilities)|corporate|executive lounge|executive floor|meeting rooms?|conference|work ?space|business center", re.I)
_CITY_TEXT = re.compile(r"city[- ]cent(?:re|er)|downtown|town cent(?:re|er)|old town|(?:in|at) the heart of|city centre location", re.I)
_RESORT_TEXT = re.compile(r"\bresort\b|all[- ]inclusive|beachfront|golf course|kids'? club|water ?park|private beach", re.I)
_BOUTIQUE_TEXT = re.compile(r"\bboutique\b", re.I)
_SPA_WORDS = [re.compile(p, re.I) for p in (r"\btreatments?\b", r"\bmassage\b", r"\bsauna\b", r"steam room", r"hydrotherapy", r"\bthermal\b", r"\bwellness\b", r"spa pool", r"\bfacials?\b", r"relaxation (?:room|area)",
                                              r"spa (?:day|break|package|menu|suite)", r"\bjacuzzi\b|hot tub")]
_FAMILY_STRONG = [re.compile(p, re.I) for p in (r"kids'? club|children'?s club", r"children'?s (?:pool|playground|activities|entertainment)", r"play ?(?:ground|area|room)", r"family[- ]friendly (?:hotel|resort)|family hotel",
                                                 r"family (?:entertainment|activities|programme|program)", r"babysitt")]


def _texts(site):
    return [(p, p["text"]) for p in site.content_pages]


def classify(site, features, intents, osm_ctx=None, hotel="", prof=None):
    feats = {f["key"]: f["level"] for f in features or []}
    ints = {i["key"]: i["level"] for i in intents or []}
    name = hotel or site.hotel or ""
    out = []

    def add(key, strength, reasons):
        out.append({"key": key, "label": LABELS[key], "strength": strength, "reasons": reasons[:4]})

    pages = _texts(site)
    # ---- airport
    r, strong = [], False
    if re.search(r"airport|flughafen", name, re.I):
        r.append(f"the hotel's name says airport ('{name}')")
        strong = True
    near = [a for a in (osm_ctx or {}).get("airports", []) if a.get("km") is not None and a["km"] <= 8]
    if near:
        r.append(f"open map data puts {near[0]['name']} {near[0]['km']} km away")
        strong = strong or near[0]["km"] <= 5
    hits = [(p, m.group(0)) for p, t in pages for m in [_AIRPORT_TEXT.search(t)] if m]
    if len({p["url"] for p, _ in hits}) >= 2 or (hits and strong):
        r.append(f"{len({p['url'] for p, _ in hits})} page(s) describe airport proximity or transfers (for example '{hits[0][1]}')")
    named = []
    for p, t in pages[:12]:
        for m in places.mentions(t, "airport", name, osm_ctx):
            if m["distance"] and re.search(r"\b(?:[1-9]|1[0-5])\s?(?:min|minute)|walking distance|\bm\b|\b[0-9](?:\.\d)?\s?km|steps|connected|on site|next to", m["distance"], re.I):
                named.append(m)
    if named:
        r.append(f"the site states it is {named[0]['distance']} from {named[0]['name']}")
    if strong or len(r) >= 2:
        add("airport", "strong" if strong else "some", r)
    # ---- business and conference
    bt = [(p, m.group(0)) for p, t in pages for m in [_BUSINESS_TEXT.search(t)] if m]
    biz_pages = len({p["url"] for p, _ in bt})
    if feats.get("meeting_rooms") in ("some", "strong") and (ints.get("business") in ("some", "strong") or ints.get("meetings") in ("some", "strong") or biz_pages >= 2):
        add("business", "strong" if (feats["meeting_rooms"] == "strong" and biz_pages >= 2) else "some",
            [f"meeting rooms are described ({feats['meeting_rooms']})", f"{biz_pages} page(s) speak to business travel or corporate guests"])
    elif biz_pages >= 3 and ints.get("business") in ("some", "strong"):
        add("business", "some", [f"{biz_pages} page(s) speak to business travel or corporate guests"])
    if feats.get("meeting_rooms") == "strong" and any(re.search(r"\b\d{3,4}\s*(?:delegates|guests|people|pax|theatre)\b|conference (?:centre|center|facilit)", t, re.I) for _p, t in pages):
        add("conference", "some", ["meeting space for 100 or more delegates, or a conference centre, is described"])
    # ---- city centre, resort, boutique
    cc = [(p, m.group(0)) for p, t in pages for m in [_CITY_TEXT.search(t)] if m]
    if re.search(r"city cent(?:re|er)|downtown|old town", name, re.I) or len({p["url"] for p, _ in cc}) >= 2:
        add("city_centre", "some", [f"the pages place the hotel in the city centre ('{cc[0][1]}')" if cc else "the hotel's name says city centre"])
    rt = [(p, m.group(0)) for p, t in pages for m in [_RESORT_TEXT.search(t)] if m]
    if re.search(r"\bresort\b", name, re.I) or len({p["url"] for p, _ in rt}) >= 2:
        add("resort", "strong" if re.search(r"\bresort\b", name, re.I) else "some", [f"'{rt[0][1]}' on the site" if rt else "the hotel's name says resort"])
    bq = [(p, m.group(0)) for p, t in pages for m in [_BOUTIQUE_TEXT.search(t)] if m]
    if re.search(r"boutique", name, re.I) or len(bq) >= 2:
        add("boutique", "some", ["the hotel describes itself as boutique"])
    # ---- spa hotel: a real spa (treatments, sauna, steam, wellness), not a gym or a pool
    spa_hits, spa_pages = set(), set()
    for p, t in pages:
        n = {i for i, rx in enumerate(_SPA_WORDS) if rx.search(t)}
        if n:
            spa_hits |= n
        if len(n) >= 2 or (pagetarget.classify(site, p) == "spa" and re.search(r"\bspa\b|treatment|massage|sauna|steam room|wellness", t, re.I)):
            spa_pages.add(p["url"])
    if len(spa_hits) >= 2 and spa_pages:
        add("spa_hotel", "strong" if len(spa_pages) >= 2 else "some", [f"{len(spa_hits)} spa features (treatments, sauna, steam room, wellness...) described on {len(spa_pages)} page(s)"])
    # ---- luxury, from the tier the audit already works out
    tier = (prof or {}).get("tier") or {}
    if tier.get("key") == "luxury":
        add("luxury", "some", [tier.get("why", "positioned as luxury")])
    # ---- family-focused: a hotel built around families, not one that merely has a family room
    fam = [i for i, rx in enumerate(_FAMILY_STRONG) if any(rx.search(t) for _p, t in pages)]
    fam_pages = [p for p, _t in pages if pagetarget.classify(site, p) == "family" and re.search(r"kids|children|famil", p["text"], re.I)]
    if len(fam) >= 2 or (fam and ints.get("family") == "strong") or re.search(r"family", name, re.I):
        add("family_focused", "some", [f"{len(fam)} family-led features (kids' club, play area, family activities...)"] + ([f"a dedicated family page"] if fam_pages else []))
    return {"classes": out, "keys": [c["key"] for c in out]}


# how much each traveller segment matters to each kind of hotel; 'skip' = no reason to assess or market to it without strong evidence of its own
_RELEVANCE = {
    "spa_couples": {"spa_hotel": "core", "resort": "secondary", "luxury": "secondary", "boutique": "secondary"},
    "families": {"family_focused": "core", "resort": "core"},
    "business": {"business": "core", "conference": "core", "airport": "core", "city_centre": "core"},
    "airport_stay": {"airport": "core"},
    "weddings": {"resort": "core", "luxury": "secondary", "boutique": "secondary", "spa_hotel": "secondary"},
    "location": {"*": "core"},
}


def relevance(keys, segment, evidence_level=None):
    """
    How much a segment matters to a hotel of these classes. A segment that does not suit the hotel's kind is 'secondary' when the site shows it offers the thing (a family room in an airport hotel), and
    'skip' when it does not (a spa break in a hotel with a gym). `evidence_level` ('strong' / 'some' / None) is how strongly the site itself addresses that audience.
    """
    table = _RELEVANCE.get(segment, {})
    if "*" in table:
        return table["*"]
    best = "skip"
    for k in keys or []:
        v = table.get(k)
        if v == "core":
            return "core"
        if v == "secondary":
            best = "secondary"
    if best == "skip" and segment in ("families", "business") and evidence_level in ("some", "strong"):
        return "secondary"                  # a family room or a meeting room is offered, so its details matter a little, though it is not what the hotel is for
    return best
