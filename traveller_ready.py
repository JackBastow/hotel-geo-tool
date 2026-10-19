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
import pagetarget
import places
from textutil import is_negated, looks_like_nav, sentence_of

CONFIRMED, PARTIAL, MISSING, UNKNOWN, NOT_OFFERED = "confirmed", "partial", "missing", "unknown", "not_offered"
STATE_LABEL = {CONFIRMED: "Confirmed", PARTIAL: "Partially confirmed", MISSING: "Missing", UNKNOWN: "Unknown", NOT_OFFERED: "Stated as not available"}


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
         {"id": "dining", "label": "Dining facilities", "context": _rx(r"restaurant|dining|bar\b|grill|brasserie|bistro|table|menu|afternoon tea|eat"),
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
         {"id": "family_rooms", "label": "Family room availability", "optional": True,
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


from textutil import PRICE as PRICE_PATTERN  # noqa: E402

SEGMENTS += [
    {"key": "airport_stay", "label": "Airport and stopover stays", "goes_to": "travellers flying in or out", "airport": True,
     "applies": {"features": (), "intents": ()}, "slugs": ("airport", "transfer", "shuttle", "getting", "location", "transport", "hotel-info", "information"),
     "requirements": [
         {"id": "airport_distance", "label": "Airport distance and journey time", "context": _rx(r"airport|terminal|flughafen"),
          "facts": {"how far the airport or terminal is, or how long the journey takes": _rx(r"\d+\s?(?:min(?:ute)?s?|m\b|metres|km|miles?)[^.\n]{0,45}(?:airport|terminal|flughafen)|(?:airport|terminal|flughafen)[^.\n]{0,70}\d+\s?(?:min(?:ute)?s?|m\b|metres|km|miles?)|walking distance|connected to (?:the )?(?:airport|terminal)|next to (?:the )?(?:airport|terminal)|directly (?:at|connected)")},
          "need": 1, "add": ["the distance or journey time between the hotel and the airport (or terminal), and how guests make it"]},
         {"id": "airport_shuttle", "label": "Shuttle availability, hours and charges", "optional": True, "requires_first": True, "context": _rx(r"shuttle|transfer|courtesy (?:bus|car)|airport (?:bus|car)"),
          "facts": {"that an airport shuttle or transfer exists": _rx(r"airport (?:shuttle|transfer|bus)|shuttle (?:bus|service)?|courtesy (?:bus|car)|(?:free|complimentary) (?:airport )?transfer"),
                    "when it runs": _rx(r"\d{1,2}[:.]\d{2}|(?:every|each) \d+ (?:min|minutes)|24[- ]?(?:hour|h|/7)|operat\w+ (?:from|between|daily)|runs? (?:from|every|daily|between)|on request|hourly"),
                    "what it costs (or that it is free)": _rx(PRICE_PATTERN + r"|\bfree\b|complimentary|no charge|included")},
          "need": 3, "add": ["that a shuttle or transfer is offered", "when the shuttle runs, and how to book it", "what the shuttle costs, or that it is free"]},
         {"id": "airport_early_late", "label": "Early departure and late arrival arrangements",
          "facts": {"early departures (early breakfast, packed breakfast, early check-out)": _rx(r"early (?:check-?in|breakfast|departure|flight|morning)|grab[- ]and[- ]go|packed breakfast|breakfast (?:box|bag)|breakfast (?:from|served from) [3-6]|express check-?out"),
                    "late arrivals (24-hour reception, late check-in, day rooms)": _rx(r"late (?:arrival|check-?in)|24[- ]?(?:hour|h|/7) (?:reception|front desk|check-?in)|day[- ]?(?:use )?rooms?|arrive (?:late|after)")},
          "need": 2, "add": ["what the hotel offers guests leaving early (breakfast, check-out)", "what the hotel offers guests arriving late (24-hour reception, late check-in)"]},
         {"id": "airport_parking", "label": "Parking, including for long stays", "context": _rx(r"park"),
          "facts": {"that parking is available": _rx(r"\bparking\b|car[- ]park|park (?:and|&) fly"),
                    "its price (or that it is free)": _rx(PRICE_PATTERN + r"|(?:free|complimentary|no charge)[^.\n]{0,40}parking|parking[^.\n]{0,60}(?:free|complimentary|no charge|per (?:day|night|24)|daily|/ ?(?:day|night))")},
          "need": 2, "add": ["that parking is available", "what parking costs per day or night, including for a longer stay"]},
         {"id": "airport_public_transport", "label": "Public transport", "context": _rx(r"train|rail|tram|bus|metro|s-bahn|station|bahnhof"),
          "facts": {"the train, tram or bus connection, with how long it takes": _rx(r"(?:train|rail|tram|bus|metro|s-bahn)[^.\n]{0,80}\d+\s?(?:min(?:ute)?s?|stops?)|\d+\s?(?:min(?:ute)?s?)[^.\n]{0,40}(?:by|on|via) (?:train|rail|tram|bus|metro|s-bahn)")},
          "need": 1, "add": ["how guests reach the hotel and the airport by train, tram or bus, and how long it takes"]},
         {"id": "airport_stopover", "label": "Stopover suitability", "optional": True, "requires_first": True,
          "facts": {"that stopovers or day-use rooms are catered for": _rx(r"stopover|layover|transit|day[- ]?(?:use )?rooms?|flight crew|connecting flight|before (?:your|a) flight|short stay"),
                    "how it works (hours, rates or check-in)": _rx(r"\d+\s?(?:hours?|hrs?)|from " + PRICE_PATTERN + r"|rates?|minimum stay|check-?in (?:time|from)")},
          "need": 2, "add": ["that stopovers or day-use rooms are available", "how a stopover works: hours, price, check-in"]},
     ]},
]


def _offered(seg, features, intents):
    """Does the site show the hotel offers what this traveller comes for? -> (bool, why)"""
    if seg.get("airport"):
        return True, "the hotel is an airport hotel"
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


def _denial(site, rx, pages=None, context=None):
    """A sentence that names the thing and says it is NOT offered ('connecting rooms are not available'): {url, snippet} or None. Negative evidence is a statement, not a confirmation."""
    for p in (pages or site.content_pages):
        for m in rx.finditer(p["text"]):
            if is_negated(p["text"], m.start(), m.end()):
                if context is not None and not context.search(p["text"][max(0, m.start() - 250): m.end() + 250] + " " + site.path(p)):
                    continue
                return {"url": p["url"], "snippet": sentence_of(p["text"], m.start(), m.end())}
    return None


def _match(site, rx, pages=None, context=None):
    """First match of `rx` on the content pages: {url, snippet} or None. A sentence that denies the thing ('no pets', 'we do not have a spa') does not count. With `context`, the match must have
    that wording close to it (or in the page's address), so a price or a capacity is only taken as an answer when it is about the right thing."""
    for p in (pages or site.content_pages):
        for m in rx.finditer(p["text"]):
            if is_negated(p["text"], m.start(), m.end()):
                continue                                   # 'not available' / 'cannot be guaranteed' is a denial, never a confirmation
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


def _topic_pages_for(site, req):
    """The pages read that this requirement belongs on, by page type (pagetarget), not by a matching word."""
    topic = REQ_TOPIC.get(req["id"])
    allowed = pagetarget.TOPIC_TYPES.get(topic) or pagetarget.GENERAL
    return [p for p in site.content_pages if pagetarget.classify(site, p) in allowed]


def _assess_requirement(site, req, topic_read, topic_unread, coverage):
    found, missing_facts, denied = {}, [], None
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
            if not m and rxf is not None:
                denied = _denial(site, rxf, pages)
        if m:
            found[name] = m
        else:
            missing_facts.append(name)
    need = req.get("need", len(req["facts"]))
    n = len(found)
    tp = _topic_pages_for(site, req)
    collapsed = any(collapsed_sections(p) for p in tp)
    reliable = bool(tp) and not collapsed and not coverage.get("unreadable")
    if denied and not first_ok:
        state = NOT_OFFERED                      # the site says it is not available: that is the answer, and nothing is recommended
    elif req.get("requires_first") and not first_ok:
        state = UNKNOWN                          # no sign the hotel offers it: nothing to recommend
    elif n >= need:
        state = CONFIRMED
    elif n > 0:
        state = PARTIAL
    elif req.get("optional"):
        state = UNKNOWN
    elif topic_unread and not tp:
        state = UNKNOWN                          # the page where this belongs was linked but not read
    elif reliable:
        state = MISSING                          # a page this belongs on was read, fully, and does not say it
    else:
        state = UNKNOWN
    why = ""
    if state == NOT_OFFERED:
        why = "the site says this is not available"
    elif state == UNKNOWN:
        if req.get("optional") and n == 0:
            why = "the site gives no sign the hotel offers this, so nothing is recommended"
        elif topic_unread and not tp:
            why = "a page on this topic is linked from the site but was not read: " + topic_unread[0]
        elif not tp:
            allowed = pagetarget.TOPIC_TYPES.get(REQ_TOPIC.get(req["id"])) or pagetarget.GENERAL
            why = f"no page this belongs on ({', '.join(pagetarget.LABEL.get(t, t) for t in allowed[:3])}) was among the pages read, so absence cannot be stated"
        elif collapsed:
            why = "the page has sections (such as 'Amenities' or 'Things to know') whose text was not in the page as read, so absence cannot be stated"
        else:
            why = f"only {coverage.get('pages_read', '?')} of {coverage.get('pages_attempted', '?')} pages could be read, so absence cannot be stated"
    elif state == PARTIAL and collapsed:
        why = "the page also has sections whose text was not in the page as read, so the rest may be stated there"
    foundrows = [{"fact": k, **v} for k, v in found.items() if not looks_like_nav(v["snippet"])]
    if state == NOT_OFFERED and denied:
        foundrows = [{"fact": "the site states it is not available", **denied}]
    return {"id": req["id"], "label": req["label"], "state": state, "found": foundrows, "missing": missing_facts if state in (PARTIAL, MISSING) else [],
            "add": ([a for k, a in zip(req["facts"], req["add"]) if k not in found] if len(req.get("add", [])) == len(req["facts"]) else list(req.get("add", []))) if state in (PARTIAL, MISSING) else [],
            "optional": bool(req.get("optional")), "why": why, "inspected": [site.path(p) for p in tp][:5], "readable": not collapsed}


def assess(site, features, intents, coverage=None, location=None, classes=None, class_info=None):
    """
    -> {"segments": [...], "assessed": [keys], "summary": {...}} for the traveller kinds the hotel serves.
    `site` is insight_content.Site; `features` and `intents` are its rows; `coverage` is consultant.crawl_coverage's result; `location` is insight_content.location's result.
    """
    coverage = coverage or {}
    out, assessed, skipped = [], [], []
    import hotel_class
    ints_ = {i["key"]: i["level"] for i in intents or []}
    reasons = {c["key"]: c["reasons"] for c in (class_info or {}).get("classes", [])}
    for seg in SEGMENTS:
        if seg.get("airport") and "airport" not in (classes or ()):
            continue                                   # only an airport hotel is assessed for airport stays
        ok, why = _offered(seg, features, intents)
        if not ok:
            skipped.append({"key": seg["key"], "label": seg["label"], "why": "the site shows no sign the hotel serves this kind of traveller, so it was not assessed"})
            continue
        rel = "core"
        if classes is not None:
            ev_level = ints_.get({"spa_couples": "spa", "families": "family", "business": "business"}.get(seg["key"], ""))
            rel = hotel_class.relevance(classes, seg["key"], ev_level)
            if rel == "skip":
                skipped.append({"key": seg["key"], "label": seg["label"], "why": "the site describes the facilities, but nothing shows the hotel serves, or wants to serve, this market (for example a gym is not a spa), so it was not assessed and no marketing advice is given"})
                continue
        if seg.get("airport") and reasons.get("airport"):
            why = "; ".join(reasons["airport"][:2])
        topic_read, topic_unread = _topic_pages(site, seg["slugs"])
        reqs = []
        for req in seg["requirements"]:
            gate = req.get("gate")
            if gate:
                fe = {f["key"]: f["level"] for f in features or []}
                if fe.get(gate[1]) not in ("some", "strong"):
                    continue                       # meeting facilities are only assessed when the hotel offers meeting rooms
            reqs.append(_assess_requirement(site, req, topic_read, topic_unread, coverage))
        out.append({**_finish(seg, why, reqs, topic_read), "relevance": rel})
        assessed.append(seg["key"])
    loc = _location_segment(site, location, coverage)
    if loc:
        out.append(loc)
        assessed.append("location")
    return {"segments": out, "assessed": assessed, "skipped": skipped, "summary": summarise(out)}


REQ_TOPIC = {"spa_facilities": "spa_detail", "couples_packages": "spa_detail", "dining": "restaurant_detail", "accommodation": "room_configuration", "restrictions": "spa_detail",
             "family_rooms": "family_occupancy", "occupancy": "family_occupancy", "children_policy": "children_policy", "family_facilities": "children_facilities", "connecting": "connecting_rooms",
             "wifi": "wifi", "parking": "parking", "meetings": "meeting_detail", "transport": "transport", "business_amenities": "wifi", "loc_transport": "transport", "loc_airports": "transport",
             "loc_attractions": "location", "loc_venues": "location", "loc_journeys": "location", "airport_distance": "transport", "airport_shuttle": "airport_transfer",
             "airport_early_late": "hotel_info", "airport_parking": "parking", "airport_public_transport": "transport", "airport_stopover": "hotel_info"}


def _where(site, seg, topic_read, evidence_urls, topic=None):
    """The existing page to add to, of a type the information belongs on (pagetarget): never a page chosen only because it mentions the word."""
    if topic:
        w = pagetarget.choose(site, topic, evidence_urls)
        return {"url": w["url"], "label": w["label"], "reason": w["reason"], "new_page": False}
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
    counts = {s: sum(1 for r in reqs if r["state"] == s) for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN, NOT_OFFERED)}
    return {"key": seg["key"], "label": seg["label"], "goes_to": seg["goes_to"], "assessed_because": why, "requirements": reqs, "counts": counts,
            "_topic_read": [p["url"] for p in topic_read]}


def _osm_for(site):
    return getattr(site, "osm_ctx", None)


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
            own = _own_named(site, "station" if key == "transport" else "airport", _osm_for(site))
            if own:
                reqs.append({"id": f"loc_{key}", "label": label, "state": own["state"], "found": [own["found"]], "missing": [] if own["state"] == CONFIRMED else [own["place"]],
                             "add": [] if own["state"] in (CONFIRMED, UNKNOWN) else [f"the walking or driving time to {own['place']}"], "optional": False, "why": own.get("why", "")})
                continue
        if not rows and key == "attractions":
            own = _own_named(site, "attraction", _osm_for(site))
            if own:
                reqs.append({"id": "loc_attractions", "label": label, "state": own["state"], "found": [own["found"]], "missing": [] if own["state"] == CONFIRMED else [own["place"]],
                             "add": [] if own["state"] in (CONFIRMED, UNKNOWN) else [f"the walking or driving time to {own['place']}"], "optional": False, "why": own.get("why", "")})
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
            "requirements": reqs, "counts": {s: sum(1 for r in reqs if r["state"] == s) for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN, NOT_OFFERED)}, "_topic_read": []}


def _own_named(site, kind, osm_ctx=None):
    """
    A named place of one kind ('station', 'airport', 'attraction') that the site itself names, with the distance stated for it in its own sentence (places.py): Confirmed with a distance or time,
    Partial named without one. Menu strips, generic labels ('Airports', 'Charging station') and the hotel's own name never count. -> {state, found, place, map_checked} or None.
    """
    named = None
    for p in site.content_pages:
        if lexicon.LEGAL_PAGE.search(site.path(p)):
            continue
        for m in places.mentions(p["text"], kind, site.hotel, osm_ctx):
            if kind == "station" and m["type"] != "railway_station":
                continue
            hit = {"fact": f"{m['name']} with a distance or time ({m['distance']})" if m["distance"] else f"{m['name']} named without a distance", "url": p["url"], "snippet": m["sentence"][:240]}
            row = {"state": CONFIRMED if m["distance"] else PARTIAL, "found": hit, "place": m["name"], "map_checked": m["map"].get("matched"), "why": ""}
            if m["map"].get("matched") is False:
                row.update(state=UNKNOWN, why=f"'{m['name']}' is named on the site but open map data does not list a place of that name nearby, so it could not be verified")
            if m["distance"]:
                return row
            named = named or row
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
    n = {s: 0 for s in (CONFIRMED, PARTIAL, MISSING, UNKNOWN, NOT_OFFERED)}
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
                r["where"] = _where(site, SEGMENT_BY_KEY.get(seg["key"], {"label": seg["label"]}), topic, own or urls, topic=REQ_TOPIC.get(r["id"]))
    return result


SEGMENT_BY_KEY = {s["key"]: s for s in SEGMENTS}


def run(site, features, intents, coverage=None, location=None, classes=None, class_info=None):
    return finish(assess(site, features, intents, coverage, location, classes, class_info), site)
