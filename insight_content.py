"""
What the hotel's own pages let a machine understand - and where they don't.

Pure analysis over pages the crawl already read; no requests. Each function
returns plain dicts whose findings carry the page URL and the text that
produced them, so nothing is asserted that the report can't show.

The six analyses:
  understanding()      what the pages would lead a machine to conclude
  intents()            which traveller searches the content supports, and why
  questions()          traveller questions the pages leave unclear
  location()           how well the site ties the hotel to places that matter
  consistency()        contradictions between the hotel's own pages
  hidden_strengths()   real features that are easy to miss
"""

import datetime as dt
import re
import urllib.parse
from collections import Counter, defaultdict

import evidence
import lexicon

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


# ------------------------------------------------------------------- the site

def _key(u):
    p = urllib.parse.urlparse(u or "")
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{p.path.rstrip('/') or '/'}".lower()


class Site:
    """A thin, read-only view over the crawled pages."""

    def __init__(self, own_pages, base, hotel="", city=""):
        self.pages = [p for p in own_pages or [] if p.get("text")]
        self.base, self.hotel, self.city = base, hotel, city
        # Terms, privacy and similar pages answer policy questions (cancellation, pets) but are not
        # evidence of what the hotel offers, and they carry the operating company's address and phone.
        self.content_pages = [p for p in self.pages if not lexicon.LEGAL_PAGE.search(urllib.parse.urlparse(p["url"]).path)]
        self.home_key = _key(base)
        self.by_key = {_key(p["url"]): p for p in self.pages}
        self.home = self.by_key.get(self.home_key)
        self._inbound = defaultdict(set)
        for p in self.pages:
            for l in p.get("links", []):
                k = _key(l)
                if k in self.by_key and k != _key(p["url"]):
                    self._inbound[k].add(_key(p["url"]))

    def path(self, p):
        return urllib.parse.urlparse(p["url"]).path or "/"

    def is_home(self, p):
        return _key(p["url"]) == self.home_key

    def is_faq(self, p):
        return bool(re.search(r"faq|frequently|questions", self.path(p), re.I))

    def depth(self, p):
        return len([s for s in self.path(p).split("/") if s])

    def inbound(self, p):
        return len(self._inbound.get(_key(p["url"]), ()))

    def linked_from_home(self, p):
        return bool(self.home and _key(p["url"]) in {_key(l) for l in self.home.get("links", [])})

    def label(self, p):
        return self.path(p) if not self.is_home(p) else "the homepage"

    def prominent(self, p, pattern):
        """In the page's title, main heading or meta description, or on the homepage."""
        sig = p.get("signals") or {}
        head = " ".join([p.get("title", "")] + list(p.get("h1", [])) + [sig.get("meta_description", "")])
        return bool(pattern.search(head)) or (self.is_home(p) and bool(pattern.search(p["text"][:2500])))

    def find(self, pattern, min_hits=1, include_legal=False):
        """-> [{page, n, snippet, prominent}] for pages where `pattern` matches."""
        out = []
        for p in (self.pages if include_legal else self.content_pages):
            ms = list(pattern.finditer(p["text"]))
            if len(ms) < min_hits:
                continue
            m = ms[0]
            out.append({"page": p, "n": len(ms), "prominent": self.prominent(p, pattern),
                        "snippet": evidence.clip(p["text"], m.start() - 70, m.end() + 120)})
        return out

    def sentences(self, p):
        return [s for s in SENT_SPLIT.split(p["text"]) if s]

    def best_page(self, slug_words, avoid_home=True):
        """The crawled page whose address/title best matches the topic, or None."""
        best, best_s = None, (0, 0)
        for p in self.content_pages:
            if avoid_home and self.is_home(p):
                continue
            if lexicon.BOOKING_PAGE.search(self.path(p)):
                continue    # a booking page is a tool, not a place to publish guest information
            hay = evidence.fold(self.path(p) + " " + p.get("title", ""))
            s = sum(2 for w in slug_words if evidence.fold(w) in hay)
            if s and (s, -self.depth(p)) > best_s:      # on a tie the shallower (more general) page wins
                best, best_s = p, (s, -self.depth(p))
        return best

    def faq_page(self):
        return next((p for p in self.pages if self.is_faq(p)), None)


def strength(site, found, dedicated_slugs=()):
    """strong / some / weak / none from where and how often something is said."""
    if not found:
        return "none"
    pages = len(found)
    prominent = any(f["prominent"] for f in found)
    dedicated = any(f["n"] >= 3 and any(w in site.path(f["page"]).lower() for w in dedicated_slugs)
                    for f in found)
    if pages >= 3 or dedicated or (prominent and pages >= 2):
        return "strong"
    if pages == 2 or (pages == 1 and (found[0]["n"] >= 3 or prominent)):
        return "some"
    return "weak"


def _where(site, found, limit=3):
    names = []
    for f in sorted(found, key=lambda f: (-f["prominent"], -f["n"]))[:limit]:
        names.append(site.label(f["page"]))
    return ", ".join(names)


# ------------------------------------------------------------------- intents

def intents(site):
    out = []
    for key, (label, pat, slugs) in lexicon.INTENTS.items():
        found = site.find(pat)
        st = strength(site, found, slugs)
        if st == "none":
            out.append({"key": key, "label": label, "level": "none", "pages": 0, "reason": "",
                        "evidence": []})
            continue
        top = sorted(found, key=lambda f: (-f["prominent"], -f["n"]))[0]
        if st == "weak":
            reason = (f"Only one passing mention, on {site.label(top['page'])}: "
                      f"“{top['snippet'][:200]}”")
        else:
            bits = [f"Mentioned on {len(found)} page{'s' if len(found) > 1 else ''} ({_where(site, found)})"]
            if any(f["prominent"] for f in found):
                bits.append("and it appears in a page title, heading, description or the homepage")
            reason = " ".join(bits) + f". Example: “{top['snippet'][:190]}”"
        out.append({"key": key, "label": label, "level": st, "pages": len(found), "reason": reason,
                    "evidence": [{"url": f["page"]["url"], "snippet": f["snippet"]} for f in found[:3]]})
    return out


# ----------------------------------------------------------- understanding

DESCRIPTORS = re.compile(
    r"\b(boutique|luxury|country house|country-house|spa|business|family[- ]run|family|city[- ]centre|"
    r"airport|historic|art[- ]deco|contemporary|coastal|seaside|golf|resort|town ?house|manor|"
    r"design|independent|four[- ]star|five[- ]star|4[- ]star|5[- ]star|budget)\s+"
    r"(hotel|resort|inn|house|retreat|lodge|apartments?)\b", re.I)


def understanding(site, intent_rows, feature_rows, city):
    """
    A cautious one-sentence reading of the property, built only from phrases
    found on the pages, plus strong and weak signals.
    """
    home = site.home or (site.pages[0] if site.pages else None)
    desc = None
    if home:
        sig = home.get("signals") or {}
        for blob in (home.get("title", ""), sig.get("meta_description", ""), " ".join(home.get("h1", [])),
                     home["text"][:900]):
            m = DESCRIPTORS.search(blob)
            if m:
                desc = f"{m.group(1).lower()} {m.group(2).lower()}"
                break
    strong = [r for r in intent_rows if r["level"] == "strong"]
    some = [r for r in intent_rows if r["level"] == "some"]
    # the three the pages emphasise most: prominent placement first, then how many pages say it
    rank = lambda r: (-sum(1 for e in r.get("evidence", []) if e), -r["pages"])  # noqa: E731
    lead = [r["label"].lower() for r in sorted(strong, key=rank)[:3]] or [r["label"].lower() for r in sorted(some, key=rank)[:3]]
    place = (city or "").split(",")[0].strip()
    noun = desc or "hotel"
    article = "an" if noun[:1] in "aeiou" else "a"
    if not site.pages:
        summary = ""
    else:
        summary = f"{article.capitalize()} {noun}" + (f" in {place}" if place else "")
        if lead:
            summary += ", mainly associated on its own pages with " + (
                ", ".join(lead[:-1]) + " and " + lead[-1] if len(lead) > 1 else lead[0])
        summary += "."
    covered = {"restaurant": "food", "spa": "spa", "meeting_rooms": "meetings", "weddings": "weddings", "pets": "pet",
               "family": "family", "accessible": "accessible", "afternoon_tea": "food"}
    intent_levels = {r["key"]: r["level"] for r in intent_rows}
    strong_f = [f["label"] for f in feature_rows if f["level"] == "strong" and f["key"] not in ("wifi", "bar")
                and intent_levels.get(covered.get(f["key"], ""), "none") != "strong"]
    strong_signals = list(dict.fromkeys([r["label"] for r in strong] + strong_f))[:10]
    weak = []
    for r in intent_rows:
        if r["level"] == "weak":
            weak.append({"label": r["label"], "why": "mentioned once, in passing"})
    for r in intent_rows:
        if r["level"] == "none" and r["key"] in lexicon.CORE_UNCLEAR:
            weak.append({"label": r["label"], "why": "not stated on the pages read"})
    for f in feature_rows:
        if f["level"] == "weak" and f["key"] not in ("wifi", "bar") and f["label"] not in [w["label"] for w in weak]                 and intent_levels.get(covered.get(f["key"], ""), "none") == "none":
            weak.append({"label": f["label"], "why": "mentioned once, in passing"})
    return {"summary": summary, "descriptor_found": desc, "strong_signals": strong_signals,
            "weak_signals": weak[:10], "pages_read": len(site.pages),
            "note": ("Built only from wording on the pages we read - it describes what a machine could "
                     "pick up from the website, not what the hotel is really like. Where something is "
                     "absent here it may simply be unstated.")}


def features(site):
    out = []
    for key, (label, pat) in lexicon.FEATURES.items():
        found = []
        for f in site.find(pat):
            # skip a negated mention ("no gym", "we do not have a pool")
            ms = pat.search(f["page"]["text"])
            ctx = f["page"]["text"][max(0, ms.start() - 40): ms.start()].lower() if ms else ""
            if re.search(r"\b(?:no|not|without|don'?t have|does not have|doesn'?t have)\s*(?:a |an |any )?$", ctx):
                continue
            found.append(f)
        out.append({"key": key, "label": label, "level": strength(site, found), "found": found,
                    "pages": len(found)})
    return out


# ----------------------------------------------------------------- questions

_TIMERANGE = re.compile(r"\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)?\s?(?:-|–|—|to|until)\s?\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)\b", re.I)


def _facts_present(site, patterns):
    """Which of {name: regex} appear anywhere, with the first page and text matched."""
    got = {}
    for name, pat in patterns.items():
        for p in site.content_pages:     # a privacy policy saying "up to 50 guests" is not an answer
            m = pat.search(p["text"])
            if m:
                got[name] = {"url": p["url"], "snippet": evidence.clip(p["text"], m.start() - 90, m.end() + 140)}
                break
    return got


def _where_to_add(site, slugs, fallback):
    page = site.best_page(slugs)
    faq = site.faq_page()
    if page:
        w = {"url": page["url"], "label": site.path(page), "reason": "the page that already covers this topic"}
    elif faq:
        w = {"url": faq["url"], "label": site.path(faq), "reason": "your FAQ page - no more specific page was found"}
    else:
        w = {"url": "", "label": fallback, "reason": "no existing page covers this topic"}
    w["also"] = ([{"url": faq["url"], "label": site.path(faq)}] if faq and (not page or faq is not page) else [])
    return w


SHORT = {"meeting_detail": "Meeting rooms", "wedding_detail": "Weddings", "spa_detail": "Spa", "pool_detail": "Pool",
         "restaurant_detail": "Restaurant", "connecting_rooms": "Family rooms", "room_count": "Number of rooms", "balconies": "Balconies"}

EXTENDED = [
    # key, question, applies_if feature/intent key, required facts {label: regex}, page slugs, fallback, priority-hint
    {"id": "meeting_detail", "q": "How many people can the meeting rooms hold, and what equipment is there?",
     "applies": ("intent", "meetings"), "slugs": ("meeting", "conference", "events", "business"),
     "fallback": "a Meetings & Events page",
     "facts": {
         "capacity (how many people)": re.compile(r"\b\d{1,4}\s*(?:delegates|people|persons|guests|pax|theatre|boardroom|cabaret|banquet|classroom|u-shape)\b|capacity", re.I),
         "room layouts": re.compile(r"theatre|boardroom|cabaret|u-shape|classroom|banquet|hollow square", re.I),
         "AV equipment": re.compile(r"projector|screen|a/?v\b|audio[- ]visual|video[- ]?conferenc|microphone|flip ?chart|display", re.I),
         "catering": re.compile(r"catering|lunch|refreshments?|coffee|buffet|working lunch|private dining", re.I),
         "who to contact": re.compile(r"events? (?:team|manager|co-?ordinator|enquir)|conference (?:team|enquir)|enquire|@", re.I)},
     "example": "Meeting rooms: Boardroom (up to 12), Garden Room (theatre 60, cabaret 40). Every room has a screen, "
                "Wi-Fi and a flip chart. Catering from [£x] per delegate. Contact the events team on [phone/email]."},
    {"id": "wedding_detail", "q": "How many guests can a wedding hold, and is the hotel licensed for ceremonies?",
     "applies": ("intent", "weddings"), "slugs": ("wedding",), "fallback": "a Weddings page",
     "facts": {
         "guest numbers": re.compile(r"\b\d{2,4}\s*(?:day|evening)?\s*guests\b|up to \d{2,4}|capacity", re.I),
         "licensed for civil ceremonies": re.compile(r"licen[cs]ed|civil ceremon|civil partnership", re.I),
         "bedrooms for guests": re.compile(r"\b\d{2,3}\s*(?:bedrooms|rooms|suites)\b|accommodat", re.I),
         "packages or prices": re.compile(r"package|from £\s?\d|per (?:head|person)|brochure", re.I)},
     "fallback_in": None,
     "example": "Weddings: licensed for civil ceremonies for up to [x] guests, with [x] evening guests. [x] bedrooms "
                "on site. Packages from [£x] per head - request the brochure or call [phone]."},
    {"id": "spa_detail", "q": "What are the spa's opening hours, prices and age rules for day guests?",
     "applies": ("feature", "spa"), "slugs": ("spa", "wellness", "treatments"), "fallback": "a Spa page",
     "facts": {
         "opening hours": _TIMERANGE,
         "prices": re.compile(r"£\s?\d|from £|per person", re.I),
         "age or booking rules": re.compile(r"over 1[68]|under 1[68]|age|minimum age|book(?:ing)? (?:in advance|is essential)|pre-?book", re.I)},
     "example": "Spa open daily [9am-8pm]. Day guest passes from [£x]. Guests must be [16+]. Book ahead on [phone/link]."},
    {"id": "pool_detail", "q": "Is the pool heated, indoor or outdoor, and when is it open?",
     "applies": ("feature", "pool"), "slugs": ("pool", "spa", "leisure", "facilities"), "fallback": "your Facilities page",
     "facts": {
         "heated or not": re.compile(r"heated|unheated|temperature|\d{2}\s?°", re.I),
         "indoor or outdoor": re.compile(r"indoor|outdoor|open[- ]air", re.I),
         "opening hours": _TIMERANGE},
     "example": "Our indoor pool is heated to [x]°C and open [7am-9pm] daily. Children under [x] must be accompanied."},
    {"id": "restaurant_detail", "q": "When is the restaurant open, and can it cater for dietary needs?",
     "applies": ("feature", "restaurant"), "slugs": ("restaurant", "dining", "eat", "menu"), "fallback": "a Dining page",
     "facts": {
         "opening times": _TIMERANGE,
         "booking": re.compile(r"book(?:ing)?\b|reserv|table", re.I),
         "dietary options": re.compile(r"vegan|vegetarian|gluten|allerg|dietary|halal|kosher", re.I)},
     "example": "[Restaurant name] is open [12-2.30pm and 6-9.30pm] daily. Book online or call [phone]. Vegetarian, vegan and "
                "gluten-free dishes are always available - tell us about allergies when booking."},
    {"id": "connecting_rooms", "q": "Does the hotel have connecting or family rooms, and how many people do they sleep?",
     "applies": ("intent", "family"), "slugs": ("family", "rooms", "accommodation"), "fallback": "your Rooms page",
     "facts": {"connecting or family rooms": re.compile(r"connecting|interconnecting|adjoining|family (?:rooms?|suites?)", re.I),
               "how many people they sleep": re.compile(r"sleeps? (?:up to )?\d|(?:up to |max(?:imum)? )\d\s*(?:guests|people|adults)|\d adults?", re.I)},
     "example": "Family rooms sleep up to [4] (2 adults + 2 children). [x] connecting rooms are available - ask when booking. "
                "Cots and high chairs are free."},
]


def _applies(rule, intent_rows, feature_rows):
    kind, key = rule
    rows = intent_rows if kind == "intent" else feature_rows
    r = next((x for x in rows if x["key"] == key), None)
    return bool(r) and r["level"] in ("some", "strong")


def questions(site, guest, intent_rows, feature_rows, location_items):
    """
    Traveller questions the pages leave unclear. Only questions that apply to
    this hotel (it says it has the thing) or that every guest asks (parking,
    check-in...) are raised, and only when the pages really leave them open.
    """
    out = []
    # --- the ten standard guest questions, already evaluated by the crawl
    for q in (guest or {}).get("questions", []):
        if q["state"] not in ("not_found", "needs_checking", "partial"):
            continue
        if q["state"] == "needs_checking" and not q.get("missing"):
            continue    # every fact is stated somewhere; it just isn't on a page about the topic - not a gap
        slugs = {"parking": ("parking", "getting here", "directions", "location", "contact"),
                 "breakfast": ("breakfast", "dining", "restaurant"),
                 "checkin_out": ("check", "faq", "policies", "information"),
                 "pets": ("pet", "dog", "faq", "policies"),
                 "accessibility": ("access", "faq"),
                 "family": ("family", "rooms"),
                 "transport": ("getting here", "directions", "location", "transport", "contact"),
                 "wifi": ("wifi", "faq"), "ev": ("parking", "getting here", "directions", "contact"),
                 "cancellation": ("cancel", "policies", "terms", "faq")}.get(q["id"], ("faq",))
        state = {"partial": "partial", "needs_checking": "unclear", "not_found": "missing"}[q["state"]]
        where = _where_to_add(site, slugs, "your FAQ or a Guest information page")
        # if a page already says part of the answer, that is where the rest belongs
        src = site.by_key.get(_key(q.get("source_url", "")))
        if src is not None and not site.is_home(src) and q["state"] in ("partial", "needs_checking"):
            where = {"url": src["url"], "label": site.path(src), "reason": "the page that already answers part of this",
                     "also": where["also"] if where["url"] != src["url"] else []}
        out.append({"id": q["id"], "question": q["label"], "short": q["short"], "state": state, "source": "standard",
                    "high_value": q.get("high_value", False),
                    "found": q.get("found", []), "missing": q.get("missing", []),
                    "evidence": ([{"url": q["source_url"], "snippet": q["snippet"]}] if q.get("source_url") else []),
                    "where": where, "example": q.get("template", ""), "note": q.get("note", "")})
    # --- extended questions: only where the hotel itself signals it offers the thing
    standard_ids = {q["id"] for q in out}
    for rule in EXTENDED:
        if not _applies(rule["applies"], intent_rows, feature_rows):
            continue
        if rule["id"] == "connecting_rooms" and "family" in standard_ids:
            continue    # the standard family question already covers this
        present = _facts_present(site, rule["facts"])
        missing = [k for k in rule["facts"] if k not in present]
        if not missing:
            continue
        relevant = next((p for p in site.pages if rule["slugs"] and any(
            w in site.path(p).lower() for w in rule["slugs"])), None)
        ev_rows = [{"url": v["url"], "snippet": v["snippet"]} for v in list(present.values())[:2]]
        state = "partial" if present else "unclear"
        out.append({"id": rule["id"], "question": rule["q"], "short": SHORT.get(rule["id"], rule["id"]), "state": state, "source": "extended",
                    "high_value": False, "found": list(present), "missing": missing, "evidence": ev_rows,
                    "where": _where_to_add(site, rule["slugs"], rule["fallback"]),
                    "example": rule["example"], "note": "" if relevant else
                    "no dedicated page for this topic was found among the pages read"})
    # --- a few facts every hotel could state
    rooms = _facts_present(site, {"rooms": re.compile(
        r"(?:hotel|property|we)\s+(?:has|have|offers?|boasts?|features?)\s+(?:a total of\s+)?\d{2,3}\s+(?:\w+\s+){0,2}(?:bedrooms|rooms|suites)"
        r"|\b\d{2,3}[- ](?:bedroom|bedroomed|room)\s+(?:hotel|property)|\b\d{2,3}\s+(?:individually|beautifully|stylish|luxurious)?\s*"
        r"(?:\w+\s+)?(?:bedrooms|guest rooms|suites)\b", re.I)})
    if site.pages and not rooms:
        out.append({"id": "room_count", "question": "How many rooms does the hotel have?", "short": "Number of rooms", "state": "missing",
                    "source": "extended", "high_value": False, "found": [], "missing": ["total number of rooms"],
                    "evidence": [], "where": _where_to_add(site, ("about us", "our hotel"), "your About page or the homepage"),
                    "example": "Our [x] bedrooms range from [Classic doubles] to [suites].", "note": ""})
    # --- balconies: only if the site mentions them but no rooms page connects them to room types
    bal = [f for f in site.find(re.compile(r"balcon(?:y|ies)", re.I))]
    if bal and not any(re.search(r"room|suite|accommodation", site.path(f["page"]), re.I) for f in bal):
        out.append({"id": "balconies", "question": "Which rooms have a balcony?", "short": "Balconies", "state": "unclear", "source": "extended",
                    "high_value": False, "found": ["balconies are mentioned"], "missing": ["which room types have one"],
                    "evidence": [{"url": f["page"]["url"], "snippet": f["snippet"]} for f in bal[:2]],
                    "where": _where_to_add(site, ("rooms", "suites", "accommodation"), "your Rooms page"),
                    "example": "Balcony: Deluxe Doubles and all suites. Classic rooms do not have a balcony.",
                    "note": ""})
    # --- location questions raised by the location analysis
    # a station already described with a distance means the hotel has made its rail link clear;
    # naming every other nearby station would be noise
    rail_clear = any(i["category"] == "transport" and i["state"] == "stated" for i in location_items)
    for it in location_items:
        if it["category"] == "transport" and rail_clear and it["state"] == "not_mentioned":
            continue
        if it["state"] in ("mentioned_no_distance", "not_mentioned") and it["category"] in ("transport", "airports"):
            nm = it["place"] or it["label"].lower()
            out.append({"id": f"loc_{it['category']}_{evidence.fold(nm)[:20].replace(' ', '_')}",
                        "question": f"How far is the hotel from {nm}?", "short": f"Distance to {nm}",
                        "state": "unclear" if it["state"] == "mentioned_no_distance" else "missing", "source": "location",
                        "high_value": it["category"] == "transport", "found": ["it is mentioned"] if it["state"] == "mentioned_no_distance" else [],
                        "missing": ["distance or travel time"], "evidence": it["evidence"],
                        "where": _where_to_add(site, ("getting here", "location", "directions", "contact"), "a Location / Getting here page"),
                        "example": it["example"], "note": it.get("hint", "")})
    return out


# ----------------------------------------------------------------- location

def _generic_places(site):
    """Station / airport names written on the pages, when no map data names them."""
    names = Counter()
    for p in site.content_pages:
        for m in re.finditer(r"\b([A-Z][A-Za-z'’-]+(?:\s(?:and|&)\s[A-Z][A-Za-z'’-]+|\s[A-Z][A-Za-z'’-]+){0,2})\s+"
                             r"(?:Railway |Train |Tube |Underground |DLR )?(Station)\b", p["text"]):
            nm = m.group(1).strip()
            if nm.lower() not in {"fire", "police", "petrol", "bus", "service", "train", "railway", "the", "our", "nearest", "local", "main"}:
                names[nm + " station"] += 1
    return [n for n, _ in names.most_common(2)]


def _destination(place):
    t = place.get("tags", {})
    return bool(t.get("website") or t.get("wikidata") or t.get("wikipedia")
                or t.get("tourism") in ("museum", "theme_park", "zoo", "gallery"))


def _exhibits(attractions):
    """
    OpenStreetMap maps individual aircraft, locomotives and galleries INSIDE a museum as
    'attractions'. A place is treated as an exhibit when a museum or theme park lies within
    400 m of it (needs coordinates) or its name reads like a single artefact.
    """
    bigs = [x for x in attractions if x.get("lat") is not None and x.get("tags", {}).get("tourism") in ("museum", "theme_park", "zoo")]
    out = set()
    for a_ in attractions:
        nm = a_["name"]
        if re.search(r"['‘’\"].+['‘’\"]|(?:vickers|vc10|spitfire|hurricane|lancaster|concorde|locomotive|mk ?\d)", nm, re.I):
            out.add(nm)
            continue
        if a_.get("lat") is None or a_.get("tags", {}).get("tourism") in ("museum", "theme_park", "zoo"):
            continue
        for b_ in bigs:
            if b_["name"] != nm and sources_km(a_, b_) < 0.4:
                out.add(nm)
                break
    return out


def sources_km(a_, b_):
    import sources
    return sources.haversine_km(a_["lat"], a_["lon"], b_["lat"], b_["lon"])


def location(site, osm_ctx):
    """
    How clearly the pages relate the hotel to places that matter. A distance is
    only suggested from open map data, labelled straight-line and unverified;
    no travel time is ever invented.
    """
    ctx = osm_ctx or {}
    items = []
    named = []   # (category, label, display name, search variants, km)
    for s in ctx.get("stations", [])[:2]:
        if s["km"] <= 4:
            base = re.sub(r"\s+(?:railway )?station$", "", s["name"], flags=re.I)
            named.append(("transport", "Rail and public transport", f"{base} station", [s["name"], base], s["km"]))
    if not ctx.get("stations"):
        for nm in _generic_places(site):
            base = nm.replace(" station", "")
            named.append(("transport", "Rail and public transport", nm, [nm, base], None))
    for a in ctx.get("airports", [])[:1]:
        if a["km"] <= 40:
            named.append(("airports", "Airports", a["name"], [a["name"], re.sub(r"\s+airport$", "", a["name"], flags=re.I)], a["km"]))
    exhibits = _exhibits(ctx.get("attractions", []))
    for a in [x for x in ctx.get("attractions", []) if _destination(x) and x["name"] not in exhibits][:3]:
        if a["km"] <= 8:
            named.append(("attractions", "Attractions", a["name"], [a["name"]], a["km"]))
    for v in ctx.get("venues", [])[:2]:
        if v["km"] <= 6:
            named.append(("venues", "Conference and event venues", v["name"], [v["name"]], v["km"]))

    covered_cats = set()
    for cat, label, name, variants, km in named:
        sentences = []
        for p in site.content_pages:
            sents = site.sentences(p)
            for i, s in enumerate(sents):
                if any(v and len(v) > 3 and v.lower() in s.lower() for v in variants):
                    window = " ".join(sents[max(0, i - 1): i + 2])
                    sentences.append((p, s, lexicon.HAS_DISTANCE(window)))
        if sentences:
            stated = [x for x in sentences if x[2]]
            use = stated[0] if stated else sentences[0]
            state = "stated" if stated else "mentioned_no_distance"
            evd = [{"url": use[0]["url"], "snippet": evidence.clip(use[1], 0, 240)}]
        else:
            state, evd = "not_mentioned", []
        km_txt = f"about {km} km" if km is not None else None
        hint = (f"Open map data puts it {km_txt} away in a straight line - check the real route and time before publishing."
                if km_txt else "")
        if state == "mentioned_no_distance":
            suggestion = (f"The website mentions {name} but doesn't say how far away it is. State the walking or driving time.")
        elif state == "not_mentioned":
            suggestion = (f"The website doesn't mention {name}, which open map data places {km_txt} from the hotel (straight line). "
                          "If it is a useful connection for guests, say how to get there.")
        else:
            suggestion = f"{name} is described with a distance - good."
        if state == "not_mentioned" and cat in ("attractions", "venues"):
            continue   # a nearby attraction or venue nobody mentions isn't a finding; only transport and airports are
        items.append({"category": cat, "label": label, "place": name, "state": state, "evidence": evd,
                      "open_data_km": km, "hint": hint, "suggestion": suggestion,
                      "example": f"“{name} is a [X]-minute walk from the hotel.” (replace [X] after checking the route)"
                                 if cat in ("transport", "venues") else
                                 f"“The hotel is [X] minutes by [car/taxi] from {name}.” (replace [X] after checking)"})
        covered_cats.add(cat)

    # categories described without a named place we know about: only report what the site raises itself
    for cat, (label, pat) in lexicon.LOCATION_CATEGORIES.items():
        if cat in covered_cats:
            continue
        hits = []
        for p in site.content_pages:
            sents = site.sentences(p)
            for i, s in enumerate(sents):
                if pat.search(s) and lexicon.LOCATION_CUE.search(s):
                    hits.append((p, s, lexicon.HAS_DISTANCE(" ".join(sents[max(0, i - 1): i + 2]))))
        if not hits:
            continue
        stated = [h for h in hits if h[2]]
        use = stated[0] if stated else hits[0]
        items.append({"category": cat, "label": label, "place": "", "state": "stated" if stated else "mentioned_no_distance",
                      "evidence": [{"url": use[0]["url"], "snippet": evidence.clip(use[1], 0, 240)}],
                      "open_data_km": None, "hint": "",
                      "suggestion": ("Described with a distance - good." if stated else
                                     f"{label} is mentioned but without a distance or travel time. Say how far it is, once you've checked."),
                      "example": f"“[Place] is a [X]-minute walk from the hotel.” (replace after checking)"})
    clear = sum(1 for i in items if i["state"] == "stated")
    return {"items": items, "map_data": bool(ctx), "clear": clear,
            "note": ("Distances come from the hotel's own wording. Where open map data is used it is a straight-line "
                     "figure, shown only as a hint - travel times are never calculated or invented." if ctx else
                     "Open map data could not be retrieved this run, so only places named on the website itself were checked.")}


# ----------------------------------------------------------------- consistency

def _digits(s):
    return re.sub(r"\D", "", s or "")


_PHONE = re.compile(r"(?:\+44\s?\(?0?\)?\s?|0)\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4}")
_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s?(\d[A-Z]{2})\b")
_ROAD = re.compile(r"\b(\d+[A-Za-z]?\s+)?([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|Way|Close|Gardens|Place|Square|Hill|Terrace|Crescent)\b")
_ABBR = {"rd": "road", "st": "street", "dr": "drive", "ln": "lane", "ave": "avenue"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def _norm_phone(s):
    d = _digits(s)
    if d.startswith("44"):
        d = "0" + d[2:]
    return d[-10:] if len(d) >= 10 else d


def consistency(site, guest, today=None):
    """Contradictions between the hotel's own pages. Each lists every page involved."""
    today = today or dt.date.today()
    out = []

    # --- check-in / check-out: the crawl already compared these across pages
    for c in (guest or {}).get("conflicts", []):
        out.append({"type": "times", "title": f"{c['fact']} differs between pages", "severity": "high",
                    "values": [{"value": v["value"], "url": v["source_url"]} for v in c["values"]],
                    "detail": c["note"], "fix": f"Decide the correct {c['fact'].lower()} and update every page and the structured data to match."})

    # --- phone numbers
    nums = defaultdict(list)
    for p in site.content_pages:
        found = {_norm_phone(t) for t in p.get("tels", []) if len(_digits(t)) >= 9}
        found |= {_norm_phone(m.group()) for m in _PHONE.finditer(p.get("footer_text", "") + " " + p["text"][:1500])}
        for n in found:
            if len(n) >= 9:
                nums[n].append(p["url"])
    if len(nums) > 1:
        out.append({"type": "phone", "title": f"{len(nums)} different telephone numbers appear on the site", "severity": "medium",
                    "values": [{"value": n, "url": u[0], "pages": len(u)} for n, u in sorted(nums.items(), key=lambda kv: -len(kv[1]))],
                    "detail": "This may be intentional (for example a separate events or spa line). If it isn't, a guest - or an AI "
                              "assistant quoting your number - may use the wrong one.",
                    "fix": "Label any deliberate second number (“Events: ...”), and make the main reservations number identical everywhere."})

    # --- hotel name forms
    from identity import _variant_rx
    rxn = _variant_rx(site.hotel) if site.hotel else None
    if rxn is not None:
        forms = defaultdict(lambda: {"pages": set(), "display": ""})
        for p in site.content_pages:
            blob = " ".join([p.get("title", "")] + list(p.get("h1", [])) + [p.get("footer_text", ""), p["text"][:3000]])
            for m in rxn.finditer(blob):
                v = re.sub(r"\s+(?:and|&)$", "", re.sub(r"\s+", " ", m.group(0)).strip(" &,-"), flags=re.I)
                if not any(w in evidence.LODGING_WORDS for w in evidence.fold(v).split()):
                    continue
                if evidence.fold(v).split()[-1] in ("restaurant", "bar", "grill"):
                    continue    # "Brooklands Hotel & Restaurant" labels a venue, it is not another name
                f = forms[evidence.fold(v)]
                f["display"] = f["display"] or v
                f["pages"].add(p["url"])
        sig = [(k, v) for k, v in forms.items() if len(v["pages"]) >= 2]
        if len(sig) > 1:
            out.append({"type": "name", "title": "The hotel is called more than one thing across its own pages", "severity": "medium",
                        "values": [{"value": v["display"], "url": sorted(v["pages"])[0], "pages": len(v["pages"])}
                                   for k, v in sorted(sig, key=lambda kv: -len(kv[1]["pages"]))],
                        "detail": "Both forms are used on several pages. Search engines and AI systems may treat them as different names.",
                        "fix": "Choose one trading name for the hotel (and a separate, clearly named label for the spa or restaurant), then use it in titles, headings and the footer."})

    # --- postcode / address
    pcs = defaultdict(set)
    streets = defaultdict(set)
    for p in site.content_pages:
        blob = p.get("footer_text", "") + " " + p["text"]
        for m in _POSTCODE.finditer(blob):
            pcs[f"{m.group(1)} {m.group(2)}"].add(p["url"])
            near = blob[max(0, m.start() - 110): m.start()]
            for r in _ROAD.finditer(near):
                nm = re.sub(r"^(?:hotel|the)\s+", "", r.group(2).lower())
                typ = _ABBR.get(r.group(3).lower(), r.group(3).lower())
                streets[(nm, typ)].add(p["url"])
    if len(pcs) > 1:
        out.append({"type": "postcode", "title": "More than one postcode appears on the site", "severity": "medium",
                    "values": [{"value": k, "url": sorted(u)[0], "pages": len(u)} for k, u in pcs.items()],
                    "detail": "One may be a neighbouring business or an old address. Mixed postcodes can send a map or an assistant to the wrong place.",
                    "fix": "Check each page; keep the hotel's real postcode and remove or label any other."})
    names_only = {k[0] for k in streets}
    if len(names_only) > 1:
        out.append({"type": "address", "title": "Different street names appear beside the postcode", "severity": "low",
                    "values": [{"value": f"{k[0].title()} {k[1].title()}", "url": sorted(u)[0], "pages": len(u)} for k, u in streets.items()],
                    "detail": "The address is written in more than one way. This is often harmless, but check it isn't a second address.",
                    "fix": "Write the address in exactly one format everywhere (footer, contact page, structured data)."})

    # --- room counts
    rc = defaultdict(set)
    for p in site.content_pages:
        for m in re.finditer(r"(?:hotel|property|we)\s+(?:has|have|offers?|boasts?|features?)\s+(?:a total of\s+)?(\d{2,3})\s+(?:\w+\s+){0,2}(?:bedrooms|rooms|suites)"
                             r"|\b(\d{2,3})[- ](?:bedroom|bedroomed|room)\s+(?:hotel|property)", p["text"], re.I):
            rc[int(m.group(1) or m.group(2))].add(p["url"])
    if len(rc) > 1:
        out.append({"type": "rooms", "title": "The number of rooms is stated differently on different pages", "severity": "medium",
                    "values": [{"value": f"{n} rooms", "url": sorted(u)[0], "pages": len(u)} for n, u in sorted(rc.items())],
                    "detail": "Scale is a basic fact a guest or an AI assistant will quote.",
                    "fix": "State the same number of rooms everywhere (or say 'over x')."})

    # --- opening hours per venue
    import guest_questions as gq
    hours = defaultdict(lambda: defaultdict(set))
    rx_h = re.compile(r"\b(restaurant|bar|spa|gym|pool|breakfast|reception|bistro|lounge|brasserie)\b[^.\n]{0,90}?"
                      r"(\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm))\s?(?:-|–|—|to|until)\s?(\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm))", re.I)
    for p in site.content_pages:
        for m in rx_h.finditer(p["text"]):
            ctx = p["text"][max(0, m.start() - 40): m.end() + 40].lower()
            if re.search(r"mon|tue|wed|thu|fri|sat|sun|weekday|weekend|bank holiday|christmas|summer|winter", ctx):
                continue    # day- or season-specific hours are legitimately different
            a, b = gq.parse_time(m.group(2)), gq.parse_time(m.group(3))
            if a and b:
                hours[m.group(1).lower()][f"{a}-{b}"].add(p["url"])
    for venue, rng in hours.items():
        if len(rng) > 1:
            out.append({"type": "hours", "title": f"The {venue}'s opening hours differ between pages", "severity": "medium",
                        "values": [{"value": r, "url": sorted(u)[0], "pages": len(u)} for r, u in rng.items()],
                        "detail": "If the hours genuinely differ by day or season, say so on every page; otherwise one is wrong.",
                        "fix": f"Give the {venue}'s hours in one place and repeat them identically elsewhere (with days/seasons if they vary)."})

    # --- expired offers
    for p in site.content_pages:
        if not re.search(r"offer|package|deal|special|promo|christmas|festive|event", site.path(p) + " " + p.get("title", ""), re.I) and not site.is_home(p):
            continue
        for m in re.finditer(r"(?:valid|available|book(?:ing)?|until|till|ends?|expires?|offer ends|through|before|by)\s+(?:on |from |until |to )?"
                             r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)", p["text"], re.I):
            day, mon, yr = m.group(1), MONTHS[m.group(2).lower()], int(m.group(3))
            try:
                end = dt.date(yr, mon, int(day)) if day else (dt.date(yr + (mon == 12), (mon % 12) + 1, 1) - dt.timedelta(days=1))
            except ValueError:
                continue
            if end < today - dt.timedelta(days=1):
                out.append({"type": "old_offer", "title": "An offer or date on the site has already passed", "severity": "medium",
                            "values": [{"value": evidence.clip(p["text"], m.start() - 60, m.end() + 80), "url": p["url"], "pages": 1}],
                            "detail": f"The page says “{m.group(0)}”, which ended {end.isoformat()}. Out-of-date offers make a hotel look unmaintained and can be quoted back to guests.",
                            "fix": "Remove or update the offer; if it's an annual event, change the year."})
                break

    # --- opposing amenity statements
    OPP = {
        "Parking": (re.compile(r"free (?:on-?site )?(?:car )?parking|complimentary (?:car )?parking|parking is free", re.I),
                    re.compile(r"parking[^.\n]{0,40}£\s?\d|£\s?\d[^.\n]{0,30}parking|chargeable parking|parking (?:is )?chargeable|parking (?:charge|fee)s?", re.I), "free", "charged"),
        "Wi-Fi": (re.compile(r"free (?:high[- ]speed )?wi-?fi|complimentary wi-?fi", re.I),
                  re.compile(r"wi-?fi[^.\n]{0,30}(?:£\s?\d|chargeable|charge|fee)", re.I), "free", "charged"),
        "Breakfast": (re.compile(r"breakfast (?:is )?included|including breakfast|complimentary breakfast", re.I),
                      re.compile(r"breakfast (?:is )?(?:available )?(?:at an additional|extra|optional)|additional (?:cost for )?breakfast", re.I), "included", "extra cost"),
        "Pets": (re.compile(r"dogs? (?:are )?welcome|pets? (?:are )?welcome|dog[- ]friendly|pet[- ]friendly", re.I),
                 re.compile(r"no (?:dogs|pets)|(?:dogs|pets) (?:are )?not (?:allowed|permitted|accepted)|unable to (?:accept|accommodate) (?:dogs|pets)|can'?t accommodate (?:dogs|pets)", re.I), "allowed", "not allowed"),
        "Pool heating": (re.compile(r"heated (?:indoor |outdoor )?(?:swimming )?pool", re.I),
                         re.compile(r"unheated|not heated", re.I), "heated", "unheated"),
    }
    for amenity, (yes, no, yl, nl) in OPP.items():
        ys = site.find(yes)
        ns = site.find(no)
        if ys and ns:
            out.append({"type": "amenity", "title": f"{amenity} is described in opposite ways", "severity": "medium" if amenity == "Pets" else "low",
                        "values": [{"value": f"{yl}: " + ys[0]["snippet"][:140], "url": ys[0]["page"]["url"], "pages": len(ys)},
                                   {"value": f"{nl}: " + ns[0]["snippet"][:140], "url": ns[0]["page"]["url"], "pages": len(ns)}],
                        "detail": "This is often legitimate (it can differ for residents and visitors, by room type or by season), but unexplained it can read as a contradiction.",
                        "fix": f"State the {amenity.lower()} rule once, completely (including any exceptions), and make every other page agree."})
    return out


# -------------------------------------------------------------- hidden strengths

_PDF_TOPICS = [("meeting", "meeting rooms"), ("conference", "meeting rooms"), ("event", "meeting rooms"), ("wedding", "weddings"),
               ("menu", "restaurant"), ("spa", "spa"), ("access", "accessible"), ("capacity", "meeting rooms"),
               ("brochure", None), ("fact", None), ("rates", None), ("tariff", None), ("floor", "meeting rooms")]


def hidden_strengths(site, feature_rows, pages_meta=None):
    out = []
    faq = site.faq_page()
    worth_finding = {"ev", "meeting_rooms", "spa", "pool", "weddings", "accessible", "family", "pets", "airport_transfer",
                     "afternoon_tea", "restaurant", "gym", "parking", "heritage"}
    for f in feature_rows:
        if f["level"] == "none" or f["key"] not in worth_finding:
            continue
        found = f["found"]
        pages = [x["page"] for x in found]
        on_home = any(site.is_home(p) for p in pages)
        on_faq = any(site.is_faq(p) for p in pages)
        if f["level"] == "weak" and not on_home and not on_faq:
            x = found[0]
            out.append({"kind": "once", "key": f["key"], "label": f["label"], "pages": [x["page"]["url"]],
                        "evidence": [{"url": x["page"]["url"], "snippet": x["snippet"]}],
                        "finding": f"{f['label']} is mentioned only once ({site.label(x['page'])}), and not on the homepage or in the FAQ.",
                        "suggestion": f"Repeat the key facts about {f['label'].lower()} on the homepage or a facilities page"
                                      + (" and in your FAQ." if faq else ", and add it to an FAQ.")})
        elif len(pages) >= 1 and all(site.depth(p) >= 3 and not site.linked_from_home(p) for p in pages) and not on_home:
            x = found[0]
            out.append({"kind": "deep", "key": f["key"], "label": f["label"], "pages": [p["url"] for p in pages[:3]],
                        "evidence": [{"url": x["page"]["url"], "snippet": x["snippet"]}],
                        "finding": f"{f['label']} appears only on a page buried {site.depth(x['page'])} levels deep that the homepage doesn't link to ({site.label(x['page'])}).",
                        "suggestion": f"Link to it from the homepage or main menu so guests (and crawlers) can reach it in one step."})
    # PDFs that hold information the pages don't - grouped, so 22 menu PDFs are ONE finding
    groups = {}
    seen = set()
    for p in site.content_pages:
        for pdf in (p.get("signals") or {}).get("pdfs", []):
            name = urllib.parse.unquote(pdf["url"].rsplit("/", 1)[-1]).lower() + " " + (pdf["anchor"] or "").lower()
            topic = next(((w, t) for w, t in _PDF_TOPICS if w in name), None)
            if not topic or pdf["url"] in seen:
                continue
            seen.add(pdf["url"])
            g = groups.setdefault("menu" if topic[0] == "menu" else topic[1] or topic[0], {"pdfs": [], "pages": {}, "topic": topic})
            g["pdfs"].append(pdf)
            g["pages"].setdefault(p["url"], p)
    for key, g in groups.items():
        names = [(x["anchor"] or x["url"].rsplit("/", 1)[-1])[:40] for x in g["pdfs"]]
        pages = list(g["pages"].values())
        is_menu = key == "menu"
        subject = "menus" if is_menu else f"{key}"
        out.append({"kind": "pdf", "key": key, "label": subject, "pages": [p["url"] for p in pages[:3]], "menu": is_menu,
                    "evidence": [{"url": g["pdfs"][0]["url"], "snippet": f"{len(g['pdfs'])} PDF(s) linked from " + ", ".join(site.label(p) for p in pages[:3])
                                  + ": " + ", ".join(names[:5])}],
                    "finding": (f"{len(g['pdfs'])} {'menu' if is_menu else 'document'}{'' if len(g['pdfs']) == 1 else 's'} {'is' if len(g['pdfs']) == 1 else 'are'} published as PDF{'' if len(g['pdfs']) == 1 else 's'} rather than page text "
                                f"({', '.join(names[:3])}{'...' if len(names) > 3 else ''}), linked from {', '.join(site.label(p) for p in pages[:3])}."),
                    "suggestion": ("Keep the PDFs for guests to download, but also write the essentials as page text: opening times, a few signature dishes and "
                                   "dietary options. PDFs are less reliably indexed and quoted than normal page text." if is_menu else
                                   "Put the key facts (capacities, prices, hours, contacts) on a normal web page. PDFs are less reliably indexed and quoted than normal page text; "
                                   "keep the PDF as a download, not the only source.")})
    # image-heavy pages that may keep their facts in pictures
    for p in site.pages:
        sig = p.get("signals") or {}
        imgs = (sig.get("images") or {}).get("total", 0)
        if imgs >= 6 and sig.get("word_count", 999) < 120 and not site.is_home(p):
            names = " ".join(f["src"].lower() for f in (sig.get("images") or {}).get("files", []))
            if re.search(r"menu|rates|tariff|capacity|floor|plan|price|brochure", names + " " + site.path(p)):
                out.append({"kind": "image", "key": "image", "label": site.label(p), "pages": [p["url"]],
                            "evidence": [{"url": p["url"], "snippet": f"{imgs} images but only {sig.get('word_count')} words of text; image files include: "
                                          + ", ".join(f["src"] for f in (sig.get("images") or {}).get("files", [])[:4])}],
                            "finding": f"{site.label(p)} is mostly images with very little text - menus, prices or plans may exist only as pictures, which are less reliably discoverable and accessible than text.",
                            "suggestion": "Write the same information out as text beside the images."})
    # relevant pages nobody links to
    for p in site.pages:
        if site.is_home(p) or lexicon.BOOKING_PAGE.search(site.path(p)) \
                or not re.search(r"meeting|conference|wedding|spa|famil|dining|restaurant|offers?|access", site.path(p), re.I):
            continue
        if site.inbound(p) == 0 and not site.linked_from_home(p):
            out.append({"kind": "poorly_linked", "key": "link", "label": site.label(p), "pages": [p["url"]],
                        "evidence": [{"url": p["url"], "snippet": "No other page we read links to this one."}],
                        "finding": f"{site.label(p)} exists but none of the {len(site.pages)} pages we read link to it.",
                        "suggestion": "Link to it from the homepage or the main menu and from related pages. (We read a sample of the site, so check your navigation first.)"})
    return out


# ------------------------------------------------------------ commercial opportunities

# intent -> (the proposition, how to say the audience, its verb, the facilities that would support it)
OPPORTUNITY_ASSETS = {
    "couples": ("romantic-stay", "couples looking for a romantic break", "are", ("spa", "restaurant", "afternoon_tea", "garden", "heritage")),
    "family": ("family-stay", "families", "are", ("family", "pool", "garden", "restaurant")),
    "business": ("business-stay", "business travellers", "are", ("meeting_rooms", "wifi", "parking", "airport_transfer")),
    "weddings": ("wedding", "weddings", "are", ("weddings", "garden", "heritage", "restaurant")),
    "spa": ("spa-break", "spa and wellness breaks", "are", ("spa", "pool", "gym", "restaurant")),
    "pet": ("dog-friendly-stay", "guests travelling with dogs", "are", ("pets", "garden")),
}


def opportunities(site, intent_rows, feature_rows):
    """
    Where the hotel has real supporting assets that its pages don't connect into a clear proposition
    for a traveller type. These are COMMERCIAL OPPORTUNITIES, not defects: whether to pursue one
    depends on which segments the hotel wants. The wording says so.
    """
    levels = {r["key"]: r for r in intent_rows}
    feats = {f["key"]: f for f in feature_rows}
    out = []
    for key, (noun, who, verb, asset_keys) in OPPORTUNITY_ASSETS.items():
        row = levels.get(key)
        if not row or row["level"] == "strong":
            continue
        assets = [feats[a] for a in asset_keys if a in feats and feats[a]["level"] in ("some", "strong")]
        if len(assets) < 2 and not (assets and row["level"] == "weak"):
            continue
        names = [a["label"].lower() for a in assets][:4]
        listed = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        ev = []
        for a in assets[:3]:
            f = a["found"][0] if a.get("found") else None
            if f:
                ev.append({"url": f["page"]["url"], "snippet": f["snippet"]})
        state = {"none": "does not currently speak to this audience",
                 "weak": "mentions this audience only once, in passing",
                 "some": "touches on this audience but does not make it a clear offer"}[row["level"]]
        out.append({
            "key": key, "label": row["label"], "level": row["level"], "assets": [a["label"] for a in assets],
            "statement": (f"If {who} {verb} a target segment, the hotel has {listed}, but its website {state} and does not connect "
                          f"those assets into a clear {noun} proposition."),
            "suggestion": (f"Only if you want to attract this audience: bring the {listed} together on one page written for them, "
                           "with specifics (what is included, who it suits, how to book)."),
            "evidence": ev, "caveat": "Not a defect. Worth acting on only if this is a segment the hotel wants."})
    out.sort(key=lambda o: ({"none": 0, "weak": 1, "some": 2}[o["level"]], -len(o["assets"])))
    return out[:5]
