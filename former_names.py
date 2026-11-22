"""
A hotel's former names, as its own pages state them ('previously known as Hotel Victoria', 'the former Hotel Victoria', 'formerly The Grand').

Why: a renamed or rebranded hotel can still appear under its old name on maps, in directories, in Wikidata and in what AI assistants have read. That is one of the most valuable identity
checks there is, and it was being missed (the report compared a postcode with another hotel's instead). The names found here are searched for in the open-data checks too, and the report says
plainly that the old and the new name need connecting.

A rule, not understanding: only a capitalised name directly after one of these phrases, that contains a word for a place to stay, is taken; the hotel's own current name never is.
"""

import re

import evidence

_CUE = re.compile(r"\b(?i:previously (?:known as|called|named)|formerly (?:known as |called |named )?|the former|this former|once known as|renamed from|was (?:originally )?(?:called|named)|"
                  r"former(?:ly)? the|old name(?:,|:)? |rebranded from)\s+(?i:the\s+)?((?:[A-Z][\w'’&.-]*\s+){0,4}[A-Z][\w'’&.-]*)", re.UNICODE)
_LODGING = {"hotel", "inn", "lodge", "house", "resort", "manor", "hall", "court", "arms", "suites", "spa", "hostel", "guesthouse", "towers", "palace", "grand", "park", "castle", "rooms"}


def find(pages, hotel):
    """-> [{name, url, quote}] for the former names the hotel's own pages state, most often stated first."""
    cur = evidence.fold(hotel or "")
    seen = {}
    for p in pages or []:
        text = p.get("text") or ""
        for m in _CUE.finditer(text):
            name = re.sub(r"\s+(?:in|on|at|of|near|by|and|so|which|that)$", "", m.group(1).strip(" .,;:’'")).strip()
            words = evidence.fold(name).split()
            if not words or not (set(words) & _LODGING) or len(words) > 5 or evidence.fold(name) in cur or cur in evidence.fold(name):
                continue
            if words in (["victorian", "hotel"], ["victorian"]):
                continue                                          # 'this former Victorian hotel' describes the building, it is not a name
            k = evidence.fold(name)
            if k not in seen:
                seen[k] = {"name": name, "url": p.get("url", ""), "quote": evidence.clip(text, m.start() - 40, m.end() + 80), "n": 0}
            seen[k]["n"] += 1
    return [{k: v for k, v in x.items() if k != "n"} for x in sorted(seen.values(), key=lambda x: -x["n"])][:3]


def recommendation(former, hotel, entities=None):
    """One action: connect the former name to the current one wherever the hotel is listed. Evidence: the hotel's own words; what the open-data checks found under each name."""
    if not former:
        return None
    names = ", ".join(f["name"] for f in former)
    under_old = [e for e in entities or [] if e.get("found_as") and e.get("found_as") != hotel]
    finding = (f"The hotel's own pages say it was previously known as {names}"
               + (f", and {', '.join(e['source'] for e in under_old)} still list{'s' if len(under_old) == 1 else ''} it under the old name." if under_old else "."))
    return {"id": "ID-former-name", "title": f"Connect your former name ({names}) to {hotel} everywhere you are listed", "source": "identity", "tag": "former-name", "category": "understanding",
            "priority": "high", "effort": "medium", "team": "marketing", "kind": "accuracy", "track": "accuracy", "confidence_label": "Confirmed" if under_old else "Likely",
            "finding": finding,
            "why": "Maps, directories, Wikidata and AI assistants may still know the hotel by its old name. Unless the two names are connected, an assistant can treat them as two different "
                   "hotels, recommend the old one, or describe what it used to be.",
            "action": f"Update the name on every listing you control, and make sure the main reference sources say '{hotel} (formerly {former[0]['name']})'.",
            "steps": [{"title": "Search for the old name on maps and listings", "detail": f"Google Business Profile, Apple Maps, OpenStreetMap, Tripadvisor, Booking.com and local directories: search for '{former[0]['name']}'."},
                      {"title": "Change the name where you control the listing; ask the platform to merge or rename it where you do not", "detail": "Keep the address and phone identical, so they are recognised as the same place."},
                      {"title": f"On your own site, say it once plainly: '{hotel}, formerly {former[0]['name']}'", "detail": "On the about or FAQ page, so readers (and AI) can connect the two."},
                      {"title": "Check Wikidata and OpenStreetMap", "detail": "Add the old name as an alternative name ('also known as' on Wikidata, old_name on OpenStreetMap)."}],
            "evidence": [{"url": f["url"], "snippet": f["quote"]} for f in former[:2]],
            "success_check": "Searching for the old name leads to the hotel under its current name."}
