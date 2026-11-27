"""
Is THIS hotel named in a piece of text? One matcher for the whole tool: the AI answers, the hotels an answer lists, the rival lists and the gap analysis all call `mentioned()`.

The rules come from real errors (code review, Nov 2026):
  - the name is found as whole words, never inside another word or another hotel's name: 'Park Hotel' is not named by '1. Hyde Park Hotel';
  - a name that is also a place is not the hotel unless it is written as one: 'Fistral Beach Hotel and Spa' is not named by 'right above Fistral Beach' (the beach), but is by
    'Fistral Beach Hotel';
  - the shorter forms people and assistants use count: 'The Nici' for 'THE NICI Newquay' (the town dropped), 'Eriksberg Hotel' for 'Eriksberg Hotel & Nature Reserve' (the part
    before '&'), 'Pig at Combe' for 'THE PIG at Combe' (without 'The'), 'The Hoxton' for 'The Hoxton, Shoreditch' (the part before the comma), 'Marriott Opera Ambassador' for
    'Paris Marriott Opera Ambassador Hotel' (the town in front dropped);
  - a shorter form that is only a big chain's brand ('Hilton' from 'Hilton Barcelona') never counts on its own;
  - 'Hampton by Hilton Dusseldorf' is another hotel of the brand, not 'Hilton Dusseldorf';
  - a one-word name needs a hotel word beside it ('Brooklands Hotel'), or the town in the same sentence ('The Brooklands Museum' is not the hotel).
"""

import re

import evidence

GENERIC = {"hotel", "hotels", "the", "by", "and", "spa", "resort", "resorts", "at", "of", "&", "inn", "suites", "collection", "a", "in", "on"}
LODGING = r"(?:hotel|hotels|spa|resort|inn|suites|lodge|guest ?house|b and b|aparthotel|apartments|hostel|motel)"
# words that make a name a PLACE when no hotel word goes with it
PLACE_WORDS = {"beach", "park", "bay", "lake", "loch", "castle", "hill", "hills", "square", "street", "road", "gardens", "garden", "quay", "harbour", "harbor", "river", "forest",
               "island", "isle", "cove", "head", "point", "village", "green", "common", "bridge", "station", "airport", "cathedral", "abbey", "palace", "market", "wharf",
               "marina", "sands", "pier", "valley", "moor", "heath", "downs", "lane", "falls", "mountain", "port", "estate", "reserve", "centre", "center", "city"}
# big chains only: a small group's short name ('The Nici', 'The Hoxton') is how the hotel is known and is kept
BRANDS = {"hilton", "marriott", "hyatt", "sheraton", "radisson", "novotel", "ibis", "mercure", "premier inn", "holiday inn", "travelodge", "doubletree", "hampton", "crowne plaza",
          "intercontinental", "westin", "kimpton", "accor", "ihg", "best western", "ramada", "jurys", "malmaison", "hotel du vin", "moxy", "aloft", "courtyard", "renaissance",
          "sofitel", "pullman", "scandic", "clarion", "comfort", "nh", "melia", "rocco forte", "four seasons", "ritz carlton", "fairmont", "shangri la", "mandarin oriental",
          "peninsula", "qhotels", "leonardo", "motel one", "citizenm", "z hotels", "zedwell"}
# words that may stand right before the hotel's name without making it part of a longer name ('Try Brooklands Hotel', 'The Park Hotel')
_STARTERS = {"the", "a", "an", "at", "in", "stay", "try", "book", "consider", "visit", "choose", "check", "or", "and", "also", "if", "for", "near", "then", "both", "like",
             "including", "while", "unlike", "but", "alternatively", "options", "option", "pick", "recommended", "recommend", "top", "best", "luxury", "boutique", "historic",
             "nearby", "next", "from", "with", "of", "to", "is", "my", "our", "your", "their", "its", "his", "her", "first", "second", "third", "finally", "another", "other"}


def _core(folded):
    return [t for t in folded.split() if t and t not in GENERIC]


def _town_tokens(city):
    return evidence.fold((city or "").split(",")[0]).split()


def variants(hotel, city=""):
    """-> the folded forms of the hotel's name that count as naming it, longest first."""
    h = evidence.fold(hotel)
    if not h:
        return []
    raw = str(hotel or "")
    town = _town_tokens(city)
    forms = {h}
    first = evidence.fold(re.split(r"\s*[,|(]\s*|\s+[-–—]\s+|\s*&\s*", raw)[0])      # before a comma, '&', '|', '(' or a dash
    if first:
        forms.add(first)
    if " and " in h:
        forms.add(h.split(" and ")[0])
    for f in list(forms):
        if f.startswith("the "):
            forms.add(f[4:])
    for f in list(forms):
        toks = f.split()
        while town and len(toks) > len(town) and toks[-len(town):] == town:          # 'the nici newquay' -> 'the nici'
            toks = toks[:-len(town)]
        while town and len(toks) > len(town) and toks[:len(town)] == town:           # 'paris marriott opera ambassador hotel' -> 'marriott opera ambassador hotel'
            toks = toks[len(town):]
        if toks and toks[-1] in ("in", "at"):
            toks = toks[:-1]
        if toks:
            forms.add(" ".join(toks))
    out = []
    for f in forms:
        bare = f[4:] if f.startswith("the ") else f
        core = _core(f)
        if not core:
            continue
        if f != h and (bare in BRANDS or " ".join(core) in BRANDS or all(w in BRANDS for w in core)):   # 'doubletree by hilton' is brand words only
            continue                                        # a shorter form that is only the brand ('hilton') is not this hotel
        if f != h and len(core) == 1 and core[0] in town:
            continue                                        # a shorter form that is only the town
        out.append(f)
    return sorted(set(out), key=len, reverse=True)


def _patterns(form):
    """-> regexes (on folded text) for one form of the name."""
    core = _core(form)
    has_lodging = re.search(r"\b" + LODGING + r"\b", form) is not None or any(w in BRANDS for w in form.split())   # 'Hilton ... Airport' is a hotel, not the airport
    joined = " ".join(core)
    then_lodging = r"\s+" + LODGING + r"\b"
    pats = []
    if len(core) >= 2:
        place_like = core[-1] in PLACE_WORDS or joined in PLACE_WORDS            # 'fistral beach' on its own is the beach
        pats.append(r"\b" + re.escape(form) + (then_lodging if (place_like and not has_lodging) else r"\b"))
        if joined != form:
            brand_led = any(w in BRANDS for w in core)
            pats.append(r"\b" + re.escape(joined) + (then_lodging if (place_like and not brand_led) else r"\b"))
        return pats
    word = core[0]
    if has_lodging or form.startswith("the "):
        pats.append(r"\b" + re.escape(form) + r"\b")       # 'brooklands hotel', 'the nici'
    pats.append(r"\b(?:the\s+)?" + re.escape(word) + then_lodging)
    return pats


def _prefix_is_name(raw, start):
    """True when the word right before position `start` in the ORIGINAL text is a capitalised word that makes the match part of a longer name ('Hyde' in 'Hyde Park Hotel')."""
    m = re.search(r"([A-Z][\w'’\-]*)[ \t]+$", raw[:start])
    if not m:
        return False
    w = re.sub(r"['’]s$", "", m.group(1).lower())
    return w not in _STARTERS


def _bare_word_with_town(t, word, town):
    if not town:
        return False
    place = " ".join(town)
    return any(re.search(r"\b" + re.escape(word) + r"\b", s) and place in s for s in re.split(r"(?<=[.!?\n])\s+", t))


# a sister hotel in the same building or brand family is another hotel: 'Holiday Inn Express Amsterdam Arena Towers' is not 'Holiday Inn Amsterdam - Arena Towers'
SUB_BRANDS = ("express", "studios", "aparthotel", "extended stay", "garden inn", "home2", "homewood", "residence inn", "staybridge", "candlewood", "element", "aloft", "moxy",
              "fairfield", "springhill", "towneplace", "tru", "hampton")          # separate brands only: an entry that drops '& Suites' is still the same hotel


def sister_brand(a, b):
    """Do two hotel names differ by a sub-brand word (one is the Express, the Suites, the Garden Inn of the other)? -> the word, or ''."""
    fa, fb = f" {_fold_name(a)} ", f" {_fold_name(b)} "
    for w in SUB_BRANDS:
        if (f" {w} " in fa) != (f" {w} " in fb):
            return w
    return ""


def _fold_name(s):
    import evidence
    return re.sub(r"[^a-z0-9]+", " ", evidence.fold(s or "")).strip()


class GroupName(str):
    """A hotel whose name is shared by several hotels of one group ('The Hoxton, Shoreditch': The Hoxton also has Holborn, Brooklyn...). It behaves as the plain name everywhere; mentioned() reads
    `.qualifier` and counts the bare group name ('The Hoxton') as naming THIS hotel only with support in the same passage."""

    def __new__(cls, name, qualifier):
        o = super().__new__(cls, name)
        o.qualifier = [str(q) for q in qualifier]
        return o


def _group_state(text, hotel, city=""):
    """'confirmed' | 'ambiguous' | 'no' for a hotel with a group name. Confirmed: the name with its place ('The Hoxton, Shoreditch'), or the bare group name with the place in the same passage (160
    characters either side). Another place straight after it ('The Hoxton, Holborn') is another hotel. Otherwise the bare name alone is ambiguous: it may be this hotel or a sister hotel."""
    raw = str(text)
    t, idx = evidence.fold_map(raw)
    qual = [evidence.fold(q) for q in hotel.qualifier if q]
    plain = str(hotel)
    bare = evidence.fold(re.split(r"\s*[,|(]\s*|\s+[-\u2013\u2014]\s+|\s*&\s*", plain)[0])
    bare_forms = {bare, bare[4:] if bare.startswith("the ") else bare}
    state = "no"
    for form in variants(plain, city):
        is_bare = form in bare_forms
        for pat in _patterns(form):
            for m in re.finditer(pat, t):
                if t[max(0, m.start() - 3):m.start()] == "by ":
                    continue
                start_raw = idx[m.start()] if m.start() < len(idx) else len(raw)
                if _prefix_is_name(raw, start_raw):
                    continue
                if not is_bare:
                    return "confirmed"
                window = t[max(0, m.start() - 160):m.end() + 160]
                if any(re.search(r"\b" + re.escape(q) + r"\b", window) for q in qual):
                    return "confirmed"
                end_raw = (idx[m.end() - 1] + 1) if 0 < m.end() <= len(idx) else len(raw)
                nxt = re.match(r"[ \t]*(?:,|-|\u2013|\u2014|\()?[ \t]*([A-Z][\w'\u2019\-]*)", raw[end_raw:end_raw + 60])
                if nxt:
                    w = evidence.fold(nxt.group(1))
                    if w and w not in GENERIC and w not in _STARTERS and w not in qual and not re.fullmatch(LODGING, w):
                        continue                         # 'The Hoxton, Holborn' / 'The Hoxton Holborn': another hotel of the group
                state = "ambiguous"
    return state


def ambiguous(text, hotel, city=""):
    """True when the text names the hotel's group but nothing says which of the group's hotels (see GroupName); False for any other hotel."""
    return bool(text) and bool(getattr(hotel, "qualifier", None)) and _group_state(text, hotel, city) == "ambiguous"


def mentioned(text, hotel, city=""):
    """Is THIS hotel named in `text`? (whole words, its usual shorter forms, never a place or another hotel's longer name)."""
    if not text or not hotel:
        return False
    if getattr(hotel, "qualifier", None):
        return _group_state(text, hotel, city) == "confirmed"
    raw = str(text)
    t, idx = evidence.fold_map(raw)
    town = _town_tokens(city)
    for form in variants(hotel, city):
        for pat in _patterns(form):
            for m in re.finditer(pat, t):
                if t[max(0, m.start() - 3):m.start()] == "by ":
                    continue                                # 'Hampton by Hilton Dusseldorf': the brand line of another hotel
                start_raw = idx[m.start()] if m.start() < len(idx) else len(raw)
                if _prefix_is_name(raw, start_raw):
                    continue                                # '1. Hyde Park Hotel' is not 'Park Hotel'
                return True
    core = _core(evidence.fold(hotel))
    if len(core) == 1 and core[0] not in PLACE_WORDS:
        return _bare_word_with_town(t, core[0], town)       # a one-word name ('Brooklands') counts with the town in the same sentence
    return False
