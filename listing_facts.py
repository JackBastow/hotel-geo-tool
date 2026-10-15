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


def listing_facts(passages, hotel):
    """
    passages: [{url, title, cited_text}] cited by the model. -> {platform: {"url", "title", "check_in", "check_out", "stars", "phone", "quotes": {fact: passage}}}
    Only passages from a page on the platform whose address, title or passage names the hotel are used.
    """
    out = {}
    for p in passages or []:
        plat = _platform_of(p.get("url"))
        text = p.get("cited_text") or ""
        if not plat or not identity.names_hotel(p["url"], p.get("title", ""), text, hotel):
            continue
        r = out.setdefault(plat, {"url": p["url"], "title": p.get("title", ""), "check_in": None, "check_out": None, "stars": None, "phone": None, "quotes": {}})
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


def site_facts(guest, own_pages):
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
    return k


LABEL = {"check_in": "Check-in time", "check_out": "Check-out time", "stars": "Star rating", "phone": "Telephone"}


def compare(listings, site):
    """Rows for every fact a listing shows that the hotel's own site also states. Never a row for a fact only one side has: that is 'not shown', not a difference."""
    rows = []
    for plat, l in listings.items():
        for fact in ("check_in", "check_out", "stars", "phone"):
            lv, sv = l.get(fact), site.get(fact)
            if lv is None or sv is None:
                continue
            same = (lv[-7:] == sv[-7:]) if fact == "phone" else (lv == sv)
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


def build(lookup, hotel, guest, own_pages, former):
    """-> the report block: {"listings", "rows", "former_name", "summary"} or None when there were no quoted passages at all."""
    passages = (lookup or {}).get("passages") or []
    if not passages:
        return None
    listings = listing_facts(passages, hotel)
    rows = compare(listings, site_facts(guest, own_pages))
    hits = former_name_hits(passages, (lookup or {}).get("pages"), former, hotel)
    shown = {p: {k: v for k, v in l.items() if k != "quotes"} for p, l in listings.items()}
    return {"source": SOURCE, "listings": shown, "rows": rows, "former_name": hits,
            "summary": {"platforms_quoted": len(listings), "compared": len(rows), "differs": sum(1 for r in rows if r["status"] == "differs"), "former_name": len(hits)}}
