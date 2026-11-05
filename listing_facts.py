"""
What each travel site SHOWS about the hotel, compared with what the hotel's own site says, and whether a listing still carries an old name.

Where the facts come from: the listing lookup (listing_lookup.py) asks an AI model with web search to find the hotel on each platform and to quote what
each listing says. We do not use the model's words. We use only the PASSAGES the search service returned and the model cited, and read the check-in time,
check-out time, star rating, phone number and name out of those passages with plain rules. A fact is therefore as good as the quoted passage, and a
fact that is not in any quoted passage is simply "not shown", never guessed. Nothing is opened or read on the platforms themselves (their terms
prohibit automated reading), so a difference is "worth checking": the listing may be right and the hotel's own site out of date, or the reverse.

Former names: a listing whose title or quoted passage carries a name the hotel is known to have used (from its own pages or Wikidata, not from
a guess) and not the current name is flagged, because after a rebrand the old name lingers in listings and in AI answers.
"""

import re

import evidence
import identity
import phones
from ai_insights import _time
from guest_questions import _TIME

SOURCE = "Listing facts (from quoted passages in public search results)"
# Only the 'check-in ... TIME' direction is used: the reverse ('TIME ... check-in') reads "3:00 PM; check-out before noon" as a 3 PM check-out.
# The gap allows for "Check-in at <the hotel's own name> is available from: 15:00".
_CIX = [re.compile(rf"check[\s\-]?in(?:(?!check)[^.\n]){{0,100}}?(?P<t>{_TIME})", re.I)]
_COX = [re.compile(rf"check[\s\-]?out(?:(?!check)[^.\n]){{0,100}}?(?P<t>{_TIME})", re.I)]
_NOON = re.compile(r"check[\s\-]?out(?:(?!check)[^.\n]){0,30}?\b(noon|midday)\b", re.I)
_STARS = re.compile(r"\b([1-5])(?:\.0)?[\s-]*(?:star|stars|★|\*)(?![a-z])", re.I)
_STARS_WORD = re.compile(r"\b(one|two|three|four|five)[\s-]star\b|\b([1-5])\s*(?:\u00e9toiles|etoiles|sterne|estrellas|stelle|estrelas)\b", re.I)
_PHONE = re.compile(r"(?:tel(?:ephone)?|phone|call|t:)\D{0,12}(\+?\d[\d\s().-]{7,}\d)|(\+\d{1,3}[\s.-]?\d(?:[\s.-]?\d){7,12})", re.I)
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
PLATFORM_LABELS = [label for label, _t in identity.KEY_PLATFORMS]
_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s?(\d[A-Z]{2})\b")
_POSTAL5 = re.compile(r"\b(\d{5})\b")
_TITLE_SPLIT = re.compile(r"\s[-|\u2013\u2014]\s|\s\|\s|,\s|\s\(")
_TITLE_NOISE = re.compile(r"\b(?:updated\s+)?20\d\d\s+prices?\b|\bfrom\s+[£€$]\s?\d+\b|\breviews?\b|\bphotos?\b|\bdeals?\b|\bbooking\.com\b|\btripadvisor\b|\bexpedia\b|\bhotels\.com\b|\btrivago\b|\bagoda\b|\bkayak\b|\btrip\.com\b|\blastminute\.com\b|\bbook now\b|\bsave\b", re.I)


def _words(text):
    """Lower-case words with accents and punctuation removed and '&' read as 'and': the plain wording of a name."""
    t = evidence.fold(text).replace("&", " and ")
    return re.findall(r"[a-z0-9]+", t)


def _place_words(place):
    return set(_words(place or "")) | {"england", "uk", "united", "kingdom", "france", "scotland", "wales"}


def shown_name(title, hotel="", place=""):
    """
    The hotel's name as a platform's page title shows it. The title is cut at its separators, the piece that is most like the hotel's name is kept, and the platform's own name, prices, years, 'reviews' and the town
    are taken off. When no piece looks like the hotel's name at all (a title such as 'rate per night'), nothing is returned: a name that cannot be read is 'not shown', never a difference.
    """
    parts = [p for p in re.split(r"\s[-|\u2013\u2014]\s|\s\|\s|:\s|,\s|\s\(", title or "") if p.strip()]
    want = set(evidence.distinctive_tokens(hotel)) if hotel else set()
    best, best_score = None, 0
    for p in parts[:4]:
        cleaned = " ".join(_TITLE_NOISE.sub(" ", p).split()).strip(" -|:,&")
        cleaned = re.sub(r"\b20\d\d\b", " ", cleaned)
        words = _words(cleaned)
        while words and words[-1] in _place_words(place):               # 'Brooklands Hotel Surrey' -> the town or county is not part of the name
            words.pop()
        cleaned = " ".join(cleaned.split()[: len(words)]) if words else ""
        score = len(want & set(_words(cleaned))) if want else (1 if cleaned else 0)
        if score > best_score:
            best, best_score = cleaned.strip(" -|:,&"), score
    return best or ""


GENERIC_NAME = {"hotel", "hotels", "spa", "resort", "the", "and", "inn", "suites", "suite", "lodge", "apartments", "house"}


def name_verdict(shown, hotel, place=""):
    """
    ('same' | 'close' | 'differs', why) for the name a platform shows against the hotel's own.
      same     the same words, ignoring capitals, accents and punctuation ('&' = 'and'), and the town
      close    the same identifying words, but with extra or missing 'Hotel', 'Spa', 'and', 'The', or in another order ('Brooklands Hotel & Spa', 'Hotel Brooklands')
      differs  an identifying word is added or missing ('Brooklands Country Club Hotel')
    """
    pw = _place_words(place)
    sa, sb = [w for w in _words(hotel) if w not in pw], [w for w in _words(shown) if w not in pw]
    for k, code in __import__("forums").AIRPORT_CODE.items():              # 'CDG' and 'Charles de Gaulle' are the same airport written two ways
        kt = _words(k)
        c = code.lower()
        for lst, other in ((sb, sa), (sa, sb)):
            if c in lst and all(w in other for w in kt):
                i = lst.index(c)
                lst[i:i + 1] = kt
    if not sa or not sb:
        return "same", ""
    if sa == sb:
        return "same", ""
    ca, cb = {w for w in sa if w not in GENERIC_NAME}, {w for w in sb if w not in GENERIC_NAME}
    only_site, only_listing = [w for w in sa if w not in sb], [w for w in sb if w not in sa]
    bits = (["the listing adds " + ", ".join(only_listing)] if only_listing else []) + (["the listing leaves out " + ", ".join(only_site)] if only_site else [])
    why = "; ".join(bits) or "the words are in a different order"
    return ("close" if ca == cb else "differs"), why


def _postcode(text):
    m = _UK_POSTCODE.search((text or "").upper())
    return (m.group(1) + m.group(2)) if m else None


def _platform_of(url):
    host = re.sub(r"^https?://(www\.)?", "", (url or "").lower()).split("/")[0]
    for label, token in identity.KEY_PLATFORMS:
        if identity.on_platform(host, token):
            return label
    return None


def _time_in(patterns, text):
    for rx in patterns:
        m = rx.search(text or "")
        if m:
            t = _time(m.group("t"))
            if t:
                return t
    return None


def listing_facts(passages, hotel, site=None):
    """
    passages: [{url, title, cited_text}] cited by the model. -> {platform: {"url", "title", "check_in", "check_out", "stars", "phone", "quotes": {fact: passage}}}
    Only passages from a page on the platform whose address, title or passage names the hotel are used.
    """
    out = {}
    for p in passages or []:
        plat = _platform_of(p.get("url"))
        text = p.get("cited_text") or ""
        if not plat:
            continue
        if not identity.names_hotel(p["url"], p.get("title", ""), text, hotel):
            # a platform that shows a DIFFERENT name for the hotel is still the hotel when the passage carries its postcode or its telephone number: that is exactly the inconsistency worth reporting
            pc = (site or {}).get("postcode") or ""
            ph = (site or {}).get("phone") or ""
            blob = f"{p.get('title', '')} {text}"
            if not ((pc and pc.upper().replace(" ", "") in blob.upper().replace(" ", "")) or (len(ph) >= 9 and ph[-9:] in re.sub(r"\D", "", blob))):
                continue
        r = out.setdefault(plat, {"url": p["url"], "title": p.get("title", ""), "check_in": None, "check_out": None, "stars": None, "phone": None, "name": None, "postcode": None, "quotes": {}})
        nm_ = shown_name(p.get("title", ""), hotel, (site or {}).get("place", ""))
        if not r["name"] and nm_:
            r["name"], r["quotes"]["name"] = nm_, (p.get("title") or "")[:200]
        pc = _postcode(text) or _postcode(p.get("title", ""))
        if pc and not r["postcode"]:
            r["postcode"], r["quotes"]["postcode"] = pc, text[:200]
        for fact, val in (("check_in", _time_in(_CIX, text)), ("check_out", _time_in(_COX, text) or ("12:00" if _NOON.search(text) else None))):
            if val and not r[fact]:
                r[fact], r["quotes"][fact] = val, text[:200]
        m = _STARS.search(text) or _STARS_WORD.search(text)
        if m and not r["stars"]:
            g = (m.group(1) or m.group(2)).lower()
            r["stars"], r["quotes"]["stars"] = int(g) if g.isdigit() else _NUM[g], text[:200]
        m = _PHONE.search(text)
        if m and not r["phone"]:
            r["phone"], r["quotes"]["phone"] = re.sub(r"\D", "", m.group(1) or m.group(2)), text[:200]
    return out


def site_facts(guest, own_pages, hotel="", location=None):
    """What the hotel's own pages state: check-in and check-out time, telephone, star rating."""
    import ai_niche
    sheet = {r["fact"]: r for r in (guest or {}).get("fact_sheet", []) if isinstance(r, dict)}
    k = {}
    for key, fact in (("check_in", "Check-in time"), ("check_out", "Check-out time")):
        if sheet.get(fact) and sheet[fact].get("value"):
            k[key] = _time(sheet[fact]["value"])
    tel = (sheet.get("Telephone") or {}).get("value")
    if tel:
        k["phone"] = re.sub(r"\D", "", str(tel))
    stars = ai_niche.stars_from_text([p.get("text", "") for p in own_pages or []])
    if stars:
        k["stars"] = stars
    addr = (sheet.get("Address") or {}).get("value") or ""
    pc = (_postcode(addr) or _postcode((location or {}).get("postcode") or "") or _postcode((location or {}).get("address") or "")
          or (re.search(r"\b(\d{5})\b", addr) or re.search(r"\b(\d{5})\b", str((location or {}).get("postcode") or "")) or [None, None])[1])
    if pc:
        k["postcode"] = pc
    if hotel:
        k["name"] = hotel
    k["place"] = " ".join(x for x in ((location or {}).get("city"), (location or {}).get("region")) if x)
    return k


LABEL = {"name": "Hotel name", "postcode": "Postcode", "check_in": "Check-in time", "check_out": "Check-out time", "stars": "Star rating", "phone": "Telephone"}


def compare(listings, site):
    """Rows for every fact a listing shows that the hotel's own site also states. Never a row for a fact only one side has: that is 'not shown', not a difference."""
    rows = []
    for plat, l in listings.items():
        for fact in ("name", "postcode", "check_in", "check_out", "stars", "phone"):
            lv, sv = l.get(fact), site.get(fact)
            if lv is None or sv is None:
                continue
            if fact == "name":
                verdict, why = name_verdict(lv, sv, site.get("place", ""))
                rows.append({"platform": plat, "fact": LABEL[fact], "listing_says": lv, "site_says": sv, "status": "matches" if verdict == "same" else "differs", "level": verdict, "note": why,
                             "url": l["url"], "passage": l["quotes"].get(fact, "")})
                continue
            if fact == "phone":
                verdict, _why = phones.compare(sv, lv)
                if verdict == "not_comparable":
                    continue                       # a chain's freephone line, or digits that are not a number: neither confirms nor contradicts the hotel's own number
                same = verdict == "same"
            else:
                same = lv == sv
            rows.append({"platform": plat, "fact": LABEL[fact], "listing_says": (f"{lv}-star" if fact == "stars" else lv), "site_says": (f"{sv}-star" if fact == "stars" else sv),
                         "status": "matches" if same else "differs", "url": l["url"], "passage": l["quotes"].get(fact, "")})
    return rows


def former_name_hits(passages, listings_pages, former, hotel):
    """
    former: identity.former_names rows. Only names taken from the hotel's own pages, an article naming it, or Wikidata are used (not the 'archived homepage title' inference).
    -> [{platform, url, name, title}] where a listing's title or quoted passage carries a former name and not the hotel's current name.
    """
    names = [f["name"] for f in former or [] if f.get("name") and "inference" not in (f.get("basis") or "")]
    # the current name (as written, and without 'hotel'/'spa') is taken out of the text first, so a former name that sits INSIDE the current one ('Marriott Opera
    # Ambassador' in 'Paris Marriott Opera Ambassador Hotel') is not mistaken for the old name
    mine = sorted({v for v in evidence.name_variants(hotel)} | {" ".join(evidence.distinctive_tokens(hotel))}, key=len, reverse=True)
    out, seen = [], set()
    cands = [{"url": p["url"], "title": p.get("title", ""), "text": p.get("cited_text", "")} for p in passages or []] + \
            [{"url": p["url"], "title": p.get("title", ""), "text": ""} for p in listings_pages or []]
    for c in cands:
        plat = _platform_of(c["url"])
        if not plat:
            continue
        hay = evidence.fold(f"{c['title']} {c['text']}")
        for v in mine:
            if v:
                hay = re.sub(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", " ", hay)
        for nm in names:
            f = evidence.fold(nm)
            if f and re.search(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])", hay):
                key = (plat, f)
                if key not in seen:
                    seen.add(key)
                    out.append({"platform": plat, "url": c["url"], "name": nm, "title": c["title"][:120]})
    return out


def build(lookup, hotel, guest, own_pages, former, location=None):
    """-> the report block: {"listings", "rows", "former_name", "summary"} or None when there were no quoted passages at all."""
    passages = (lookup or {}).get("passages") or []
    if not passages:
        return None
    site = site_facts(guest, own_pages, hotel, location)
    listings = listing_facts(passages, hotel, site)
    rows = compare(listings, site)
    hits = former_name_hits(passages, (lookup or {}).get("pages"), former, hotel)
    shown = {p: {k: v for k, v in l.items() if k != "quotes"} for p, l in listings.items()}
    names = [{"platform": p, "shown_name": l["name"], "status": next((r["status"] for r in rows if r["platform"] == p and r["fact"] == "Hotel name"), "matches"),
              "level": next((r.get("level") for r in rows if r["platform"] == p and r["fact"] == "Hotel name"), "same"), "url": l["url"]} for p, l in listings.items() if l.get("name")]
    return {"source": SOURCE, "listings": shown, "rows": rows, "former_name": hits, "names": names,
            "summary": {"platforms_quoted": len(listings), "compared": len(rows), "differs": sum(1 for r in rows if r["status"] == "differs"), "former_name": len(hits),
                        "names_shown": len(names), "names_differ": sum(1 for n in names if n["status"] == "differs"), "site_name": hotel}}
