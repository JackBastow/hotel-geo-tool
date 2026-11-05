"""
Is this string really the name of a place? The question engine builds prompts around places the hotel's own pages say are close ('15 minutes from the Louvre'). Page text is messy: 'Parking Lot Airports Düsseldorf
Airport' and 'Airports Rhine Park' are scraps of sentences and menu items, not places, and a prompt built on one asks the assistant about somewhere that does not exist. Two checks keep them out:

  ok(name)             the words of a place name: capitalised proper nouns, not parking, rooms, Wi-Fi, distances or offers, and not too long;
  clean_airport(name)  an airport name with the leading scraps taken off ('Parking Lot Airports Düsseldorf Airport' -> 'Düsseldorf Airport');
  near(name, titles)   whether a place a page names is also a known place within a few kilometres of the hotel (Wikipedia's titles around its coordinates).
"""

import re

import evidence

BAD_WORDS = {"parking", "lot", "lots", "airports", "rooms", "room", "wifi", "wi-fi", "free", "distance", "minutes", "minute", "min", "walk", "drive", "from", "hotel", "hotels", "guests", "book", "booking", "offer",
             "offers", "car", "spaces", "shuttle", "bus", "transfer", "transfers", "rates", "rate", "price", "prices", "deals", "deal", "package", "packages", "welcome", "enjoy", "located", "near", "close", "just"}
CONNECTORS = {"de", "du", "la", "le", "les", "of", "the", "von", "van", "der", "den", "am", "an", "im", "und", "and", "des", "del", "di", "da", "el", "al", "st", "st."}


def ok(name):
    """True when the words could be a place's name."""
    words = [w for w in re.split(r"[\s,;()]+", (name or "").strip()) if w]
    if not 1 <= len(words) <= 6:
        return False
    if any(w.lower().strip(".") in BAD_WORDS for w in words):
        return False
    real = [w for w in words if w.lower() not in CONNECTORS]
    if not real or sum(1 for w in real if w[:1].isupper() or w[:1].isdigit()) < max(1, len(real) * 0.6):
        return False
    if re.search(r"\d", name) and not re.search(r"[A-Za-z]{4,}", name):
        return False
    return True


def clean_airport(name):
    """'Parking Lot Airports Düsseldorf Airport' -> 'Düsseldorf Airport'; None when nothing sensible is left."""
    words = [w for w in (name or "").split() if w]
    while words and (words[0].lower() in BAD_WORDS or words[0].lower() in ("airport", "airports")):
        words.pop(0)
    out = []
    for w in words:
        if w.lower() in BAD_WORDS and w.lower() not in ("airports",):
            break
        out.append(w)
    words = [w for w in out if w.lower() != "airports"]
    if words and words[-1].lower() == "airport":
        words = words[:-1]
    if not words or not ok(" ".join(words)):
        return None
    return " ".join(words) + " Airport"


def near(name, titles):
    """Does a known place nearby carry this name? `titles` are the titles of Wikipedia articles around the hotel's coordinates."""
    key = evidence.fold(name)
    toks = [t for t in key.split() if t not in {x.lower() for x in CONNECTORS}]
    if not toks:
        return False
    for t in titles or []:
        f = evidence.fold(t)
        if key in f or f in key or all(x in f.split() for x in toks):
            return True
    return False
