"""
Small text helpers shared by the checks that read a hotel's pages, so the same mistake is not fixed in one place and left in another.

  PRICE          a price in any common currency ('CHF 35', '35.- CHF', 'Fr. 35', '£14', '$20', '€9'), not just pounds and euros
  is_negated()   does the sentence around a match say the thing is NOT offered ('connecting rooms are not available')? That is negative evidence, never confirmation
  looks_like_nav()  is this text a navigation or menu strip rather than a sentence ('Hotel Info Offers Gallery Location Dining')? Such text is never evidence
  boilerplate()  sentences that repeat on most pages of one site (menus, footers, brand banners), so they are not taken as what a particular page says
"""

import re

# A price: a currency sign or code beside digits, in either order.
_CODES = r"(?:CHF|SFr|Fr|USD|GBP|EUR|SEK|NOK|DKK|AED|JPY|AUD|CAD|NZD|SGD|HKD|ZAR|THB|PLN|CZK|HUF|TRY|INR|CNY|RUB|BRL|MXN|KRW|ISK|RON|BGN|HRK)"
PRICE = (rf"(?:[£€$¥]\s?\d|\b{_CODES}\.?\s?-?\d|\d[\d.,']*(?:\.-|,-)?\s?{_CODES}\b)")
PRICE_RX = re.compile(PRICE, re.I)

# Words that turn a mention into a denial. Looked for in the same sentence, within a short distance of the thing mentioned.
_NEG = re.compile(
    r"\bnot\s+(?:be\s+)?(?:currently\s+)?(?:available|offered|provided|possible|permitted|allowed|accepted|guaranteed|confirmed|supported|included|needed|required|necessary|operated|running)\b|\bno\s+need\b"
    r"|\bunavailable\b|\bnot\s+(?:able|possible)\b|\bunable\s+to\b|\bcannot\b|\bcan[’']?t\b|\bcould\s+not\b"
    r"|\b(?:do|does|did)\s+not\s+(?:offer|have|provide|allow|accept|guarantee|take|permit)\b|\b(?:don|doesn)[’']?t\s+(?:offer|have|provide|allow|accept|guarantee|take)\b"
    r"|\bno\s+(?:\w+\s+){0,2}(?:available|offered|provided)\b|\bsold\s+out\b|\bnot\s+offer(?:ed)?\b|\bwithout\b|\bunfortunately\b|\bnot\s+guaranteed\b|\bsubject\s+to\s+availability\b(?=.{0,40}\bnot\b)"
    r"|\bonly\s+(?:on\s+request\s+and\s+)?not\b", re.I)
_PRE_NO = re.compile(r"\b(?:no|not|without|never|neither|nor|zero)\s+(?:a\s+|an\s+|any\s+|the\s+)?(?:\w+\s+){0,2}$", re.I)
_SENT_END = ".!?\n;|"


def _sentence_bounds(text, start, end):
    a = max(text.rfind(c, 0, start) for c in _SENT_END) + 1
    ends = [i for i in (text.find(c, end) for c in _SENT_END) if i != -1]
    b = min(ends) if ends else len(text)
    return a, b


def is_negated(text, start, end, window=70):
    """
    True when the sentence around text[start:end] denies it: a negation just before it ('no connecting rooms', 'without parking') or a denial close after it ('connecting rooms are not
    available', 'cannot be guaranteed'). A rule, not understanding: it is meant to stop 'not available' being read as 'available', and it errs towards treating a doubtful sentence as a denial.
    """
    a, b = _sentence_bounds(text, start, end)
    before = text[max(a, start - 40):start]
    after = text[end:min(b, end + window)]
    if _PRE_NO.search(before):
        return True
    return bool(_NEG.search(after))


def sentence_of(text, start, end, limit=300):
    a, b = _sentence_bounds(text, start, end)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "..."


# ------------------------------------------------------------ navigation text

_NAV_WORDS = {"home", "info", "information", "offers", "offer", "gallery", "photos", "location", "dining", "rooms", "room", "suites", "contact", "contacts", "book", "booking", "menu", "login", "sign",
              "in", "up", "honors", "rewards", "search", "language", "english", "deutsch", "francais", "español", "italiano", "reviews", "faq", "faqs", "events", "meetings", "weddings", "spa", "wellness",
              "careers", "about", "us", "terms", "privacy", "cookies", "cookie", "sitemap", "hotels", "destinations", "brands", "explore", "stay", "stays", "amenities", "facilities", "services", "directions",
              "map", "overview", "special", "deals", "packages", "more", "view", "all", "check", "availability", "reservations", "reserve", "find", "a", "hotel", "help", "support", "account", "my", "trips"}


def looks_like_nav(text):
    """
    Is this a menu or navigation strip rather than a sentence? Several short capitalised words in a row, made mostly of site-menu words, with no verb-like connective and no sentence punctuation:
    'Hotel Info Offers Gallery Location Dining'. A real name ('Zurich Airport', 'Brooklands Museum') has few menu words, so it is not caught.
    """
    t = re.sub(r"\s+", " ", text or "").strip(" -|>/•·")
    toks = re.findall(r"[A-Za-zÀ-ÿ']+", t)
    if len(toks) < 3:
        return bool(toks) and all(w.lower() in _NAV_WORDS for w in toks) and len(toks) >= 2
    menu = sum(1 for w in toks if w.lower() in _NAV_WORDS)
    title = sum(1 for w in toks if w[:1].isupper())
    punct = bool(re.search(r"[.!?:;,]", t))
    return menu / len(toks) >= 0.5 and title / len(toks) >= 0.7 and not punct


# A page's amenity filter or feature menu ('Airport shuttle Fitness center Business center Pet-friendly rooms Concierge EV charging ... Parking Pets Smoking WiFi') is a list of labels, not a statement:
# it says nothing about price, hours or policy, and a chain's filter can list what the brand offers in general. Four or more such labels in a row are removed from the text every check reads.
_LABELS = (r"Airport shuttle|Shuttle|Fitness cent(?:er|re)|Business cent(?:er|re)|Pet[- ]friendly rooms?|Concierge|EV charging|Executive lounge|Cribs?|Room service|Meeting rooms?|All Amenities"
           r"|Families and kids|Family rooms?|Parking|Valet parking|Self[- ]parking|Pets|Smoking|Non[- ]smoking|Wi-?Fi|Free Wi-?Fi|Pool|Swimming pool|Spa|Restaurants?|Bars?|Gym|Laundry|Babysitting"
           r"|Accessible rooms?|Breakfast|Air conditioning|Kids club|Housekeeping|Currency exchange|Ice machine|Vending|Elevators?|Lifts?|Terrace|Garden")
_LABEL_RUN = re.compile(rf"(?:\b(?:{_LABELS})\b[ \t]+){{3,}}\b(?:{_LABELS})\b")


def strip_label_runs(text):
    """The text without amenity-filter strips (four or more feature labels in a row, each capitalised as a label is). Anything else is left exactly as it was."""
    if not text:
        return text
    return _LABEL_RUN.sub(" ", text)


def address_text(v):
    """An address as one line of text, whatever shape it arrives in: a string, a schema.org PostalAddress record, or a list of either."""
    if not v:
        return ""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip()
    if isinstance(v, (list, tuple)):
        return address_text(v[0]) if v else ""
    if isinstance(v, dict):
        c = v.get("addressCountry")
        c = c.get("name") if isinstance(c, dict) else c
        parts = [v.get("streetAddress"), v.get("addressLocality"), v.get("addressRegion"), v.get("postalCode"), c]
        return ", ".join(re.sub(r"\s+", " ", str(p)).strip() for p in parts if p and not isinstance(p, (dict, list)))
    return str(v)


def is_generic_label(text):
    """A bare category word used as a label ('Airports', 'Railway stations', 'Charging station') is not a named place."""
    t = re.sub(r"\s+", " ", text or "").strip(" -|>/•·:").lower()
    generic = {"airport", "airports", "station", "stations", "railway station", "railway stations", "train station", "train stations", "charging station", "charging stations", "bus station",
               "bus stop", "attractions", "attraction", "museum", "museums", "gallery", "galleries", "shuttle", "transport", "transportation", "public transport", "getting here", "directions",
               "location", "nearby", "around the hotel", "points of interest", "ev charging station", "petrol station", "gas station", "service station", "fire station", "police station"}
    return t in generic


# -------------------------------------------------------------------- boilerplate

_SPLIT = re.compile(r"(?<=[.!?])\s+|\s{2,}|\s[|•·]\s")


def _all_units(text):
    """Every sentence-sized unit of the text, in order, however short (so nothing is lost when site-wide units are taken out)."""
    return [re.sub(r"\s+", " ", u).strip() for u in _SPLIT.split(text or "") if u.strip()]


def _units(text):
    """The units long enough to be a menu line or banner worth recognising as repeated (25 characters or more)."""
    return [u for u in _all_units(text) if len(u) >= 25]


def boilerplate(pages, min_pages=4, share=0.5):
    """
    The sentences (and menu strips) that appear on at least half of a site's pages (and at least `min_pages`): site-wide menus, footers, brand banners, cookie notices. They say nothing about one page,
    so a fact is not credited to a page because of them and they are never quoted as evidence. -> set of normalised units; empty for a small set of pages.
    """
    if len(pages or []) < min_pages:
        return set()
    from collections import Counter
    c = Counter()
    for p in pages:
        for u in set(_units(p.get("text", ""))):
            c[u.lower()] += 1
    need = max(min_pages, int(len(pages) * share + 0.999))
    return {u for u, n in c.items() if n >= need}


def strip_boilerplate(text, bp):
    """The text without its site-wide units (every other unit, short or long, is kept in order; the text is returned as it was when nothing repeats)."""
    if not bp or not text:
        return text
    keep = [u for u in _all_units(text) if u.lower() not in bp]
    return " ".join(keep) if keep else text
