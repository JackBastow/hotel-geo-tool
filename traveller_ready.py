"""
Traveller recommendation readiness: does the hotel's own website give enough SPECIFIC information to be recommended for each kind of traveller?

The earlier traveller-intent view counted how often a word appeared. This asks a different question. For each kind of traveller the hotel actually serves (romantic and spa breaks, families,
business travellers, people choosing by location) there is a short list of things that traveller needs to know before booking, and each is classed from the pages that were read:

  Confirmed            clearly stated, with the page and the words that say it
  Partially confirmed  some of it is stated, the rest is not
  Missing              not found, in pages that were read well enough to say so (the page where it belongs was read)
  Unknown              not enough was read to tell, or the hotel gives no sign it offers the thing, so nothing is recommended

Rules that keep it honest:
  * A segment is only assessed when the site shows the hotel offers what that traveller comes for (a spa, family rooms, meeting rooms, ...). Location applies to every hotel.
  * A requirement that depends on an optional offer (couples' packages, connecting rooms) is never marked Missing: if the site does not mention it, it is Unknown and nothing is recommended.
  * 'Missing' needs the pages to have been read: when the crawl was limited, or a page on that topic was linked but not read, the answer is Unknown, not Missing.
  * Repetition earns nothing. One clear statement confirms a fact; ten mentions of 'romantic' confirm nothing.
  * Every recommendation names the existing page to add to. A new page is only suggested when no existing page covers the topic.
"""

import re
import urllib.parse

import evidence
import lexicon

CONFIRMED, PARTIAL, MISSING, UNKNOWN = "confirmed", "partial", "missing", "unknown"
STATE_LABEL = {CONFIRMED: "Confirmed", PARTIAL: "Partially confirmed", MISSING: "Missing", UNKNOWN: "Unknown"}


def _rx(p):
    return re.compile(p, re.I)


# A requirement is {id, label, facts: {name: regex}, need: how many facts make it Confirmed (default all), optional: depends on an offer the hotel may not make, slugs: where it belongs,
# add: what to state when it is not complete}.
SEGMENTS = [
    {"key": "spa_couples", "label": "Romantic and spa breaks", "goes_to": "couples and spa guests",
     "applies": {"features": ("spa",), "intents": ("spa", "couples")}, "slugs": ("spa", "wellness", "treatments", "romantic", "couples"),
     "requirements": [
         {"id": "spa_facilities", "label": "Spa facilities and who can use them", "context": _rx(r"spa|wellness|treatment|massage|pool|sauna|steam|thermal|hot tub|relax"),
          "facts": {"what the spa has (treatments, pool, sauna, steam room)": _rx(r"treatment|massage|facial|sauna|steam room|hydrotherapy|thermal|jacuzzi|hot tub|relaxation (?:room|area)|swimming pool|\bpool\b"),
                    "who can use it and when (guests, day visitors, opening times)": _rx(r"non[- ]?residents?|day (?:guest|spa|pass|visitor)|day spa|residents? only|hotel guests|complimentary (?:spa )?access|access to the spa|spa access|spa (?:is )?open|opening (?:hours|times)|open (?:daily|from|until)")},
          "need": 2, "add": ["what the spa includes (treatments, pool, sauna)", "who may use the spa (hotel guests, day visitors) and when it is open"]},
         {"id": "couples_packages", "label": "Couples' packages", "optional": True, "requires_first": True, "context": _rx(r"couples?|romantic|honeymoon|anniversary|spa (?:day|package|break)|for two"),
          "facts": {"that a couples' or romantic package exists": _rx(r"(?:couples?|romantic|honeymoon|anniversary|celebration)[^.\n]{0,40}(?:package|break|stay|spa day|escape|getaway|treatment|experience)|(?:package|break|stay|escape)[^.\n]{0,30}for (?:two|couples)"),
                    "what it includes and costs": _rx(r"includ\w+[^.\n]{0,80}(?:treatment|dinner|breakfast|champagne|prosecco|room|spa|access)|from £\s?\d|£\s?\d+\s*(?:per|pp|a night|each)|price from"),
                    "how to book it": _rx(r"book (?:online|now|your)|enquire|call (?:us|\+?\d)|to book|reservations?\b")},
          "need": 3, "add": ["a couples' or romantic package, if the hotel offers one", "what the package includes and its price", "how to book it"]},
         {"id": "dining", "label": "Dining facilities", "context": _rx(r"restaurant|dining|bar|grill|brasserie|bistro|table|menu|afternoon tea|eat"),
          "facts": {"the restaurant or bar": _rx(r"restaurant|brasserie|\bgrill\b|bistro|dining room|\bbar\b|afternoon tea"),
                    "opening times or how to book a table": _rx(r"opening (?:hours|times)|open (?:daily|from|for|until|every)|\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)\s?(?:-|–|to|until)|book (?:a )?table|table reservations?|reserve a table")},
          "need": 2, "add": ["the restaurant and bar", "the restaurant's opening times and how to book a table"]},
         {"id": "accommodation", "label": "Rooms suited to couples", "context": _rx(r"room|suite|bed|bath|stay"),
          "facts": {"named room types": _rx(r"\b(?:superior|deluxe|executive|classic|junior suite|suite|four[- ]poster|double|king|queen)\b"),
                    "the bed set-up or room features (bed size, bath, view, balcony)": _rx(r"\b(?:king|queen|super[- ]king|double)[- ](?:size[d]? )?bed|four[- ]poster|\bbalcon\w+|private terrace|roll[- ]?top|freestanding bath|walk-?in shower|garden view|views? (?:of|over)|spa bath|jacuzzi")},
          "need": 2, "add": ["the room types", "the bed size of each room type and features such as a bath, balcony or view"]},
         {"id": "restrictions", "label": "Restrictions and booking requirements", "context": _rx(r"spa|treatment|package|book|stay|rate|cancel"),
          "facts": {"an age rule or booking requirement (minimum age, advance booking, deposit, cancellation terms)": _rx(r"minimum age|over 1[68]\b|under 1[68]\b|16\+|18\+|adults only|book(?:ing)? (?:in advance|is essential|required)|pre-?book|deposit|cancellation|non[- ]refundable|minimum (?:stay|\d+[- ]night)")},
          "need": 1, "add": ["the minimum age for the spa, whether spa visits must be booked in advance, and cancellation terms"]},
     ]},
    {"key": "families", "label": "Family stays", "goes_to": "families",
     "applies": {"features": ("family",), "intents": ("family",)}, "slugs": ("family", "families", "rooms", "accommodation", "children", "kids"),
     "requirements": [
         {"id": "family_rooms", "label": "Family room availability",
          "facts": {"family rooms or suites": _rx(r"family (?:rooms?|suites?|apartments?)|interconnecting|inter-connecting|adjoining rooms?|sleeps? (?:up to )?[3-9]\b")},
          "need": 1, "add": ["which room types are family rooms and how many people they sleep"]},
         {"id": "occupancy", "label": "Maximum room occupancy", "context": _rx(r"famil|room|suite|sleeps"),
          "facts": {"how many adults and children a room takes": _rx(r"sleeps? (?:up to )?\d|(?:up to|max(?:imum)?\.?(?: occupancy)?(?: of)?)\s*\d\s*(?:guests|people|adults|persons)|occupancy[: ]+\d|\d\s*adults?\s*(?:and|\+|&)\s*\d\s*child|\b\d\s*adults?,?\s*\d\s*child")},
          "need": 1, "add": ["the maximum number of adults and children for each family room category"]},
         {"id": "children_policy", "label": "Children's policies", "context": _rx(r"child|kid|famil|cot|infant|baby|under[- ]\d|aged"),
          "facts": {"the ages and charges for children": _rx(r"children (?:under|aged|of all ages|are welcome|stay free|up to)|child(?:ren)?'?s? (?:policy|rate|price)|under[- ]\d+s?\b|(?:aged?|ages?) \d|stay free"),
                    "cots, extra beds or what is provided for children": _rx(r"\bcots?\b|travel cot|extra bed|rollaway|z[- ]?bed|high chairs?|baby (?:bath|monitor)|child supplement")},
          "need": 2, "add": ["the age children stay free or pay, and what extra beds cost", "whether cots and high chairs are provided"]},
         {"id": "family_facilities", "label": "Facilities for children", "context": _rx(r"child|kid|famil|junior|young"),
          "facts": {"a children's menu or dining": _rx(r"children'?s menu|kids'? menu|kids eat|family dining|high chairs?"),
                    "somewhere for children to play, swim or be entertained": _rx(r"play ?(?:area|ground|room)|kids'? club|children'?s (?:pool|club|area|activities)|games? room|garden|swimming pool|\bpool\b|games|toys|activity pack|treasure hunt")},
          "need": 2, "add": ["whether there is a children's menu", "what children can do at the hotel (pool, garden, play area, activities)"]},
         {"id": "connecting", "label": "Connecting rooms", "optional": True, "requires_first": True, "context": _rx(r"connect|adjoin|interconnect|famil"),
          "facts": {"that connecting rooms exist": _rx(r"connecting rooms?|interconnecting|inter-connecting|adjoining rooms?"),
                    "how to request them": _rx(r"(?:request|ask|book|available|subject to availability)[^.\n]{0,60}(?:connecting|adjoining|interconnecting)|(?:connecting|adjoining|interconnecting)[^.\n]{0,60}(?:request|on request|subject to availability|when booking|please ask|contact)")},
          "need": 2, "add": ["that connecting rooms are available", "how to request connecting rooms and how many there are"]},
     ]},
    {"key": "business", "label": "Business travellers", "goes_to": "business guests",
     "applies": {"features": ("meeting_rooms",), "intents": ("business", "meetings")}, "slugs": ("business", "meeting", "conference", "events", "facilities"),
     "requirements": [
         {"id": "wifi", "label": "Wi-Fi",
          "facts": {"that Wi-Fi is available": _rx(r"wi-?fi|wireless internet|broadband"), "whether it is free (or its speed)": _rx(r"(?:free|complimentary|included)[^.\n]{0,40}wi-?fi|wi-?fi[^.\n]{0,60}(?:free|complimentary|included|£\s?\d|per (?:day|night|hour)|mbps|high[- ]speed|fibre)|high[- ]speed (?:wi-?fi|internet)")},
          "need": 2, "add": ["that Wi-Fi is available", "whether Wi-Fi is free, and its speed"]},
         {"id": "parking", "label": "Parking",
          "facts": {"that parking is available": _rx(r"\bparking\b|car[- ]park"), "its cost (or that it is free)": _rx(r"(?:free|complimentary|no charge)[^.\n]{0,40}parking|parking[^.\n]{0,60}(?:free|complimentary|no charge|£\s?\d|per (?:day|night|24)|charge)|£\s?\d+[^.\n]{0,30}parking"),
                    "how many spaces or where": _rx(r"\b\d{2,4}\s*(?:car )?(?:parking )?spaces|on[- ]site parking|private (?:car )?park|car park (?:is )?(?:located|at|behind|opposite)")},
          "need": 2, "add": ["that parking is available", "whether parking is free or its price per night", "whether parking is on site and whether spaces can be reserved"]},
         {"id": "meetings", "label": "Meeting facilities", "gate": ("features", "meeting_rooms"), "context": _rx(r"meeting|conference|event|private|function|boardroom|delegate|ballroom|suite|banquet|room for"),
          "facts": {"how many people a room holds": _rx(r"\b\d{1,4}\s*(?:delegates|people|persons|guests|pax|theatre|boardroom|cabaret|banquet|classroom|u-shape)\b|capacity"),
                    "equipment and layouts": _rx(r"projector|screen|a/?v\b|audio[- ]visual|video[- ]?conferenc|microphone|flip ?chart|display|theatre[- ]style|boardroom|cabaret|u-shape|classroom"),
                    "packages, catering or who to contact": _rx(r"delegate (?:rate|package)|day delegate|catering|working lunch|refreshments|events? (?:team|manager|enquir)|conference (?:team|enquir)|enquire|\w+@\w+")},
          "need": 3, "add": ["the capacity of each meeting room", "the equipment and layouts available", "delegate packages and whom to contact"]},
         {"id": "transport", "label": "Transport connections",
          "facts": {"the nearest station or airport": _rx(r"station|railway|train|airport|heathrow|gatwick|motorway|junction|\bM\d{1,2}\b|\bA\d{1,3}\b"),
                    "how far or how long it takes": None},
          "need": 2, "add": ["the nearest station or airport", "the walking or driving time to the nearest station and airport"]},
         {"id": "business_amenities", "label": "Business-relevant amenities",
          "facts": {"a desk or workspace in the room": _rx(r"\bdesks?\b|work ?space|work ?station|business centre|business center|study area"),
                    "early breakfast, express check-out or late check-out": _rx(r"early (?:breakfast|check-?in)|express (?:check-?out|check-?in)|late check-?out|grab and go|breakfast (?:from|served from) [4-7]"),
                    "laundry, 24-hour reception or room service": _rx(r"laundry|dry[- ]clean|valet|24[- ]hour reception|24/7|room service|iron(?:ing)? (?:board|facilit)"),
                    "corporate rates": _rx(r"corporate (?:rate|account|booking|offer)|business (?:rate|account)|company rate")},
          "need": 2, "add": ["whether rooms have a desk or workspace", "early breakfast, express or late check-out for business guests", "laundry, 24-hour reception or room service", "corporate rates and how to arrange them"]},
     ]},
]


def _offered(seg, features, intents):
    """Does the site show the hotel offers what this traveller comes for? -> (bool, why)"""
    fe = {f["key"]: f["level"] for f in features or []}
    it = {i["key"]: i["level"] for i in intents or []}
    for k in seg["applies"].get("features", ()):
        if fe.get(k) in ("some", "strong"):
            return True, f"the site describes {lexicon.FEATURES[k][0].lower()}"
    for k in seg["applies"].get("intents", ()):
        if it.get(k) in ("some", "strong"):
            return True, f"the site addresses {lexicon.INTENTS[k][0].lower()}"
    return False, ""


def _topic_pages(site, slugs):
    """Pages that exist on the topic: (read pages whose address or title matches, links to such pages that were not read)."""
    read = [p for p in site.content_pages if any(evidence.fold(s) in evidence.fold(site.path(p) + " " + p.get("title", "")) for s in slugs) and not lexicon.BOOKING_PAGE.search(site.path(p))]
    seen, unread = {site_key for site_key in site.by_key}, []
    for p in site.pages:
        for l in p.get("links", []):
            k = _key(l)
            path = urllib.parse.urlparse(l).path.lower()
            if k not in seen and any(s in path for s in slugs) and not re.search(r"\.(?:jpg|png|pdf|css|js)$", path) and l not in unread and urllib.parse.urlparse(l).netloc.lower().removeprefix("www.") == urllib.parse.urlparse(site.base).netloc.lower().removeprefix("www."):
                unread.append(l)
    return read, unread[:3]


def _key(u):
    import insight_content
    return insight_content._key(u)


def _match(site, rx, pages=None, context=None):
    """First match of `rx` on the content pages: {url, snippet} or None. A sentence that denies the thing ('no pets', 'we do not have a spa') does not count. With `context`, the match must have
    that wording close to it (or in the page's address), so a price or a capacity is only taken as an answer when it is about the right thing."""
    for p in (pages or site.content_pages):
        for m in rx.finditer(p["text"]):
            before = p["text"][max(0, m.start() - 40): m.start()].lower()
            if re.search(r"\b(?:no|not|without|don'?t have|does not have|doesn'?t have)\s*(?:a |an |any )?$", before):
                continue
            if context is not None and not context.search(p["text"][max(0, m.start() - 250): m.end() + 250] + " " + site.path(p)):
                continue
            return {"url": p["url"], "snippet": evidence.clip(p["text"], m.start() - 70, m.end() + 110)}
    return None


def collapsed_sections(page):
    """Does this page have headed sections (tabs, accordions) whose text is not in the page as read? See insight_content.collapsed_sections."""
    import insight_content
    return insight_content.collapsed_sections(page)


def _transport_fact(site):
    """Nearest station or airport named in a sentence that also gives a distance or time."""
    for p in site.content_pages:
        sents = site.sentences(p)
        for i, s in enumerate(sents):
            if re.search(r"station|railway|airport|heathrow|gatwick|motorway|junction", s, re.I) and lexicon.HAS_DISTANCE(s):
                return {"url": p["url"], "snippet": evidence.clip(s, 0, 240)}
    return None


def _assess_requirement(site, req, topic_read, topic_unread, coverage):
    found, missing_facts = {}, []
    scope = req.get("scope")
    pages = [p for p in site.content_pages if any(evidence.fold(sl) in evidence.fold(site.path(p) + " " + p.get("title", "")) for sl in scope)] if scope else None
    ctx = req.get("context")
    first_ok = True
    for i, (name, rxf) in enumerate(req["facts"].items()):
        # an optional offer (a couples' package, connecting rooms) must first be shown to exist; only then are its details looked for
        if i and req.get("requires_first") and not first_ok:
            missing_facts.append(name)
            continue
        m = _transport_fact(site) if rxf is None else _match(site, rxf, pages, ctx if (i or not req.get("requires_first")) else None)
        if i == 0 and req.get("requires_first"):
            first_ok = bool(m)
        if m:
            found[name] = m
        else:
            missing_facts.append(name)
    need = req.get("need", len(req["facts"]))
    n = len(found)
    collapsed = any(collapsed_sections(p) for p in topic_read)
    reliable = ((not coverage.get("limited")) or bool(topic_read)) and not collapsed
    if req.get("requires_first") and not first_ok:
        state = UNKNOWN                          # no sign the hotel offers it: nothing to recommend
    elif n >= need:
        state = CONFIRMED
    elif n > 0:
        state = PARTIAL
    elif req.get("optional"):
        state = UNKNOWN
    elif topic_unread and not topic_read:
        state = UNKNOWN                          # the page where this belongs was linked but not read
    elif reliable:
        state = MISSING
    else:
        state = UNKNOWN
    why = ""
    if state == UNKNOWN:
        if req.get("optional") and n == 0:
            why = "the site gives no sign the hotel offers this, so nothing is recommended"
        elif topic_unread and not topic_read:
            why = "a page on this topic is linked from the site but was not read: " + topic_unread[0]
        elif collapsed:
            why = "the page has sections (such as 'Amenities' or 'Things to know') whose text was not in the page as read, so absence cannot be stated"
        else:
            why = f"only {coverage.get('pages_read', '?')} of {coverage.get('pages_attempted', '?')} pages could be read, so absence cannot be stated"
    elif state == PARTIAL and collapsed:
        why = "the page also has sections whose text was not in the page as read, so the rest may be stated there"
    return {"id": req["id"], "label": req["label"], "state": state, "found": [{"fact": k, **v} for k, v in found.items()], "missing": missing_facts if state in (PARTIAL, MISSING) else [],
            "add": ([a for k, a in zip(req["facts"], req["add"]) if k not in found] if len(req.get("add", [])) == len(req["facts"]) else list(req.get("add", []))) if state in (PARTIAL, MISSING) else [],
            "optional": bool(req.get("optional")), "why": why}


def assess(site, features, intents, coverage=None, location=None):
    """
    -> {"segments": [...], "assessed": [keys], "summary": {...}} for the traveller kinds the hotel serves.
    `site` is insight_content.Site; `features` and `intents` are its rows; `coverage` is consultant.crawl_coverage's result; `location` is insight_content.location's result.
    """
    coverage = coverage or {}
    out, assessed, skipped = [], [], []
    for seg in SEGMENTS:
        ok, why = _offered(seg, features, intents)
        if not ok:
            skipped.append({"key": seg["key"], "label": seg["label"], "why": "the site shows no sign the hotel serves this kind of traveller, so it was not assessed"})
            continue
        topic_read, topic_unread = _topic_pages(site, seg["slugs"])
        reqs = []
        for req in seg["requirements"]:
            gate = req.get("gate")
            if gate:
                fe = {f["key"]: f["level"] for f in features or []}
                if fe.get(gate[1]) not in ("some", "strong"):
                    continue                       # meeting facilities are only assessed when the hotel offers meeting rooms
            reqs.append(_assess_requirement(site, req, topic_read, topic_unread, coverage))
        out.append(_finish(seg, why, reqs, topic_read))
        assessed.append(seg["key"])
    loc = _location_segment(site, location, coverage)
    if loc:
        out.append(loc)
        assessed.append("location")
    return {"segments": out, "assessed": assessed, "skipped": skipped, "summary": summarise(out)}


def _where(site, seg, topic_read, evidence_urls):
    """The existing page to add to: the topic page that was read, else the page where related facts were found, else the FAQ, else none (then a new page is suggested)."""
    if topic_read:
        slugs = [evidence.fold(x) for x in seg.get("slugs", ())]

        def rank(q):
            hay = evidence.fold(site.path(q) + " " + q.get("title", ""))
            return (next((i for i, sl in enumerate(slugs) if sl in hay), len(slugs)), site.depth(q), len(site.path(q)))
        p = sorted(topic_read, key=rank)[0]
        return {"url": p["url"], "label": site.path(p), "reason": "the page that already covers this topic", "new_page": False}
    for u in evidence_urls:
        if u:
            return {"url": u, "label": urllib.parse.urlparse(u).path or "/", "reason": "the page where the related information already is", "new_page": False}
    faq = site.faq_page()
    if faq:
        return {"url": faq["url"], "label": site.path(faq), "reason": "your FAQ page; no more specific page was found", "new_page": False}
    return {"url": "", "label": f"a {seg['label'].lower()} page", "reason": "no existing page covers this topic", "new_page": True}


def _finish(seg, why, reqs, topic_read):
    counts = {s: sum(1 for r in reqs if r["state"] == s) for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN)}
    return {"key": seg["key"], "label": seg["label"], "goes_to": seg["goes_to"], "assessed_because": why, "requirements": reqs, "counts": counts,
            "_topic_read": [p["url"] for p in topic_read]}


def _location_segment(site, location, coverage):
    """Location-based travellers, from the location analysis (places named on the site, with or without a distance, against open map data)."""
    items = [i for i in (location or {}).get("items", []) if i["category"] in ("transport", "airports", "attractions", "venues", "business", "city_centre")]
    if not items and not (location or {}).get("map_data"):
        return None
    cats = [("transport", "Railway stations", ("transport",)), ("airports", "Airports", ("airports",)), ("attractions", "Nearby attractions", ("attractions",)),
            ("venues", "Event venues and business destinations", ("venues", "business", "city_centre"))]
    reqs = []
    for key, label, cs in cats:
        rows = [i for i in items if i["category"] in cs]
        if not rows and key in ("transport", "airports"):
            own = _own_transport(site, key)
            if own:
                reqs.append({"id": f"loc_{key}", "label": label, "state": own["state"], "found": [own["found"]], "missing": [] if own["state"] == CONFIRMED else [own["place"]],
                             "add": [] if own["state"] == CONFIRMED else [f"the walking or driving time to {own['place']}"], "optional": False, "why": ""})
                continue
        if not rows and key == "attractions":
            own = _own_places(site, _ATTRACTION)
            if own:
                reqs.append({"id": "loc_attractions", "label": label, "state": own["state"], "found": [own["found"]], "missing": [] if own["state"] == CONFIRMED else [own["place"]],
                             "add": [] if own["state"] == CONFIRMED else [f"the walking or driving time to {own['place']}"], "optional": False, "why": ""})
                continue
        if not rows:
            if key in ("attractions", "venues"):
                continue                           # no mapped place of this kind nearby: nothing to assess
            reqs.append({"id": f"loc_{key}", "label": label, "state": UNKNOWN, "found": [], "missing": [], "add": [], "optional": False,
                         "why": "open map data did not return a relevant place, and the site names none"})
            continue
        stated = [i for i in rows if i["state"] == "stated"]
        named = [i for i in rows if i["state"] == "mentioned_no_distance"]
        absent = [i for i in rows if i["state"] == "not_mentioned"]
        if stated and not named and not absent:
            state = CONFIRMED
        elif stated or named:
            state = PARTIAL
        elif absent and (not coverage.get("limited")):
            state = MISSING
        else:
            state = UNKNOWN
        found = [{"fact": f"{i['place'] or i['label']} with a distance or time", "url": i["evidence"][0]["url"], "snippet": i["evidence"][0]["snippet"]} for i in stated if i["evidence"]]
        found += [{"fact": f"{i['place'] or i['label']} named without a distance", "url": i["evidence"][0]["url"], "snippet": i["evidence"][0]["snippet"]} for i in named if i["evidence"]]
        add = [f"the walking or driving time to {i['place'] or i['label']}" for i in named + absent][:4] if state in (PARTIAL, MISSING) else []
        reqs.append({"id": f"loc_{key}", "label": label, "state": state, "found": found, "missing": [(i["place"] or i["label"]) for i in named + absent] if state in (PARTIAL, MISSING) else [],
                     "add": add, "optional": False,
                     "why": "" if state != UNKNOWN else f"only {coverage.get('pages_read', '?')} of {coverage.get('pages_attempted', '?')} pages could be read, so absence cannot be stated"})
    # journey times: stated by the site and checked against the straight-line distance from open map data
    checks = _journey_checks(items)
    if checks:
        reqs.append({"id": "loc_journeys", "label": "Journey distances and times that can be checked", "state": CONFIRMED if all(c["plausible"] for c in checks) else PARTIAL,
                     "found": [{"fact": c["text"], "url": c["url"], "snippet": c["snippet"]} for c in checks], "missing": [c["place"] for c in checks if not c["plausible"]],
                     "add": [f"check the stated time to {c['place']}: it is shorter than the straight-line distance allows" for c in checks if not c["plausible"]], "optional": False,
                     "why": ""})
    if not reqs:
        return None
    return {"key": "location", "label": "Location-based travellers", "goes_to": "travellers who choose by location", "assessed_because": "every hotel is found by its location",
            "requirements": reqs, "counts": {s: sum(1 for r in reqs if r["state"] == s) for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN)}, "_topic_read": []}


_AIRPORT = re.compile(r"airport|heathrow|gatwick|stansted|luton|london city|southampton airport|terminal [1-5]", re.I)
_STATION = re.compile(r"\bstation\b|railway|\btrain\b|waterloo|euston|paddington|victoria|kings cross|liverpool street", re.I)


def _own_transport(site, key):
    """Stations or airports the site names itself, when open map data named none: confirmed with a distance or time, partial without one."""
    rx = _AIRPORT if key == "airports" else _STATION
    named = None
    for p in site.content_pages:
        sents = site.sentences(p)
        for i, snt in enumerate(sents):
            if not rx.search(snt):
                continue
            window = " ".join(sents[max(0, i - 1): i + 2])
            place = (rx.search(snt).group(0)).strip().title()
            hit = {"fact": f"{place} with a distance or time", "url": p["url"], "snippet": evidence.clip(snt, 0, 240)}
            if lexicon.HAS_DISTANCE(window):
                return {"state": CONFIRMED, "found": hit, "place": place}
            named = named or {"state": PARTIAL, "found": {**hit, "fact": f"{place} named without a distance"}, "place": place}
    return named


_ATTRACTION = re.compile(r"museum|attraction|castle|gallery|theme park|\bzoo\b|racecourse|race track|circuit|mercedes-benz world|national trust|palace|cathedral|national park|golf (?:club|course)|\bwisley\b|legoland|thorpe park", re.I)


def _place_name(sentence, m):
    """The name of a place around a keyword ('Brooklands Museum', 'Mercedes-Benz World'): the capitalised words next to it. Falls back to the keyword."""
    left = re.findall(r"([A-Z][\w'\u2019&-]*)\s*$", sentence[:m.start()].rstrip())
    words = []
    head = sentence[:m.start()].rstrip().split(" ")
    for w in reversed(head):
        if re.match(r"^[A-Z][\w'\u2019&-]*$", w) and len(words) < 3 and w.lower() not in ("the", "our", "and", "to", "from", "near", "by"):
            words.insert(0, w)
        else:
            break
    tail = sentence[m.end():].lstrip().split(" ")
    after = []
    for w in tail[:2]:
        if re.match(r"^[A-Z][\w'\u2019-]*[,.;]?$", w):
            after.append(w.strip(",.;"))
        else:
            break
    name = " ".join(words + [m.group(0).title()] + after).strip()
    return name if len(name) > len(m.group(0)) else m.group(0).title()


def _own_places(site, rx):
    """Places of a kind the site names itself (attractions), in a sentence that says where they are: confirmed with a distance or time, partial without one."""
    named = None
    for p in site.content_pages:
        if lexicon.LEGAL_PAGE.search(site.path(p)):
            continue
        sents = site.sentences(p)
        for i, snt in enumerate(sents):
            m = rx.search(snt)
            if not m or not lexicon.LOCATION_CUE.search(snt):
                continue
            window = " ".join(sents[max(0, i - 1): i + 2])
            place = _place_name(snt, m)
            hit = {"fact": f"{place} with a distance or time", "url": p["url"], "snippet": evidence.clip(snt, 0, 240)}
            if lexicon.HAS_DISTANCE(window):
                return {"state": CONFIRMED, "found": hit, "place": place}
            named = named or {"state": PARTIAL, "found": {**hit, "fact": f"{place} named without a distance"}, "place": place}
    return named


_WALK = re.compile(r"(\d{1,3})\s*(?:-|–)?\s*min(?:ute)?s?'?\s*(?:walk|on foot)", re.I)
_MILES = re.compile(r"(\d+(?:\.\d+)?)\s*miles?", re.I)
_KM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:km|kilomet)", re.I)


def _journey_checks(items):
    """Stated walking times or distances compared with the straight-line distance from open map data. A walk cannot be shorter than the straight line (about 80 m a minute), so a stated figure
    well below it is flagged for checking. Nothing is calculated or invented: only a stated figure and the map's straight line are compared."""
    out = []
    for i in items:
        km = i.get("open_data_km")
        if i["state"] != "stated" or km is None or not i["evidence"]:
            continue
        snip = i["evidence"][0]["snippet"]
        stated_km = None
        m = _WALK.search(snip)
        if m:
            stated_km, text = int(m.group(1)) * 0.08, f"{i['place']}: {m.group(0)}"
        elif _MILES.search(snip):
            stated_km, text = float(_MILES.search(snip).group(1)) * 1.609, f"{i['place']}: {_MILES.search(snip).group(0)}"
        elif _KM.search(snip):
            stated_km, text = float(_KM.search(snip).group(1)), f"{i['place']}: {_KM.search(snip).group(0)}"
        if stated_km is None or not i["place"]:
            continue
        out.append({"place": i["place"], "text": text, "stated_km": round(stated_km, 2), "map_km": km, "plausible": stated_km >= 0.6 * km, "url": i["evidence"][0]["url"], "snippet": snip})
    return out


def summarise(segments):
    n = {s: 0 for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN)}
    for seg in segments:
        for r in seg["requirements"]:
            n[r["state"]] += 1
    judged = n[CONFIRMED] + n[PARTIAL] + n[MISSING]
    score = round(100 * (n[CONFIRMED] + 0.5 * n[PARTIAL]) / judged) if judged else None
    return {**n, "judged": judged, "score": score}


def finish(result, site):
    """Add, to each segment with something to fix, the existing page to add to. Done after assessment so the page can be chosen from where related facts were found."""
    for seg in result["segments"]:
        topic_urls = set(seg.pop("_topic_read", []))
        topic = [p for p in site.pages if p["url"] in topic_urls]
        urls = [f["url"] for r in seg["requirements"] for f in r["found"] if f.get("url")]
        for r in seg["requirements"]:
            if r["state"] in (PARTIAL, MISSING):
                own = [f["url"] for f in r["found"] if f.get("url")]
                r["where"] = _where(site, SEGMENT_BY_KEY.get(seg["key"], {"label": seg["label"]}), topic, own or urls)
    return result


SEGMENT_BY_KEY = {s["key"]: s for s in SEGMENTS}


def run(site, features, intents, coverage=None, location=None):
    return finish(assess(site, features, intents, coverage, location), site)
