"""
Evidence ledger and hotel matching.

Every finding in the wider report points at one or more evidence records, so
a reader can always ask "says who?" and get a URL, a date and the actual
words. A record is one of three kinds:

  observed    - we fetched it and this is what it says
  inference   - we drew a conclusion from observed evidence (the evidence ids
                the conclusion rests on are listed with it)
  unassessed  - something worth checking that we could not check, with why

Hotel-name matching lives here too, because the biggest accuracy risk in this
whole tool is attributing an article about "Brooklands" (a motor circuit) or
another "Brooklands Hotel" to the hotel being audited. Matching therefore
requires the full name, and then looks for a location signal near it.
"""

import datetime as dt
import re
import unicodedata
import urllib.parse

KINDS = ("observed", "inference", "unassessed")

SOURCE_TYPES = (
    "own_website", "booking_platform", "tourism_directory", "hotel_directory",
    "hotel_group", "map_or_open_data", "news_or_magazine", "blog", "social",
    "video", "destination_body", "awards_body", "wiki", "government_register",
    "other",
)

# Words that say "this is somewhere to stay" - never enough on their own to
# identify a hotel, because every hotel has one.
LODGING_WORDS = {"hotel", "hotels", "inn", "lodge", "resort", "spa", "suites",
                 "house", "manor", "hall", "arms", "guesthouse", "bnb", "b&b",
                 "apartments", "motel", "retreat", "boutique"}
FILLER = {"the", "and", "at", "of", "by", "a", "&"}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def fold(s):
    """Lower-case, accent-free, punctuation-free, single-spaced."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fold_map(raw):
    """
    Like fold(), but also returns, for each character of the folded string,
    the index in `raw` it came from - so a match found in the folded text can
    be shown as the original wording around it.
    """
    out, idx = [], []
    pending_space = False
    for i, ch in enumerate(str(raw or "")):
        pieces = " and " if ch == "&" else unicodedata.normalize("NFKD", ch)
        for p in pieces:
            if unicodedata.combining(p):
                continue
            p = p.lower()
            if p.isascii() and p.isalnum():
                if pending_space and out:
                    out.append(" ")
                    idx.append(i)
                pending_space = False
                out.append(p)
                idx.append(i)
            else:
                pending_space = True
    return "".join(out), idx


def domain_of(url):
    host = urllib.parse.urlparse(url or "").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def registrable(domain):
    """Crude registrable domain (handles co.uk-style suffixes)."""
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "gov", "ac", "net"} \
            and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def same_site(url_a, url_b):
    return registrable(domain_of(url_a)) == registrable(domain_of(url_b))


# --------------------------------------------------------------------- matching

def name_variants(hotel):
    """
    The phrases that count as this hotel's name. Always the full folded name,
    plus the name with a trailing 'and spa' / leading 'the' dropped. Never the
    distinctive word alone: 'brooklands' is a motor circuit, a college, a
    station and several other hotels.
    """
    full = fold(hotel)
    out = {full} if full else set()
    if full.startswith("the "):
        out.add(full[4:])
    for suf in (" and spa", " hotel and spa", " spa", " and restaurant"):
        if full.endswith(suf):
            out.add(full[: -len(suf)])
            out.add(full[: -len(suf)] + " hotel")
    # drop variants that are only lodging words / fillers
    keep = set()
    for v in out:
        toks = [t for t in v.split() if t not in FILLER and t not in LODGING_WORDS]
        if toks:
            keep.add(v)
    return keep


def distinctive_tokens(hotel):
    return [t for t in fold(hotel).split() if t not in FILLER and t not in LODGING_WORDS]


def place_tokens(city="", postcode=""):
    toks = {t for t in re.findall(r"[a-z]{3,}", fold(city))}
    toks -= {"england", "scotland", "wales", "united", "kingdom", "great", "britain"}
    pc = fold(postcode).replace(" ", "")
    return toks, (pc if len(pc) >= 5 else "")


def match_hotel(text, hotel, city="", postcode="", own_domain="", links=(),
                window=700):
    """
    -> {"level": high|medium|low|none, "why": str, "extract": str}

    high    full hotel name AND a location signal (town / postcode) within
            `window` characters of it, or a link to the hotel's own domain
    medium  full hotel name, no location signal found near it
    low     the distinctive word appears but never the full name
    none    neither

    The extract is the sentence-ish window around the first best mention, for
    showing as evidence.
    """
    raw = str(text or "")
    if not raw.strip() or not hotel:
        return {"level": "none", "why": "no text to match", "extract": ""}
    folded, idx = fold_map(raw)
    variants = sorted(name_variants(hotel), key=len, reverse=True)
    city_toks, pc = place_tokens(city, postcode)

    def window_for(pos_folded):
        if not idx:
            return ""
        c = idx[min(pos_folded, len(idx) - 1)]
        return clip(raw, c - 160, c + 260)

    best = None
    for v in variants:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", folded):
            seg = folded[max(0, m.start() - window): m.end() + window]
            seg_tokens = set(seg.split())
            loc = bool(city_toks & seg_tokens) or (pc and pc in seg.replace(" ", ""))
            cand = (2 if loc else 1, m.start())
            if best is None or cand > best[0]:
                best = (cand, v, loc)
    own_link = False
    if own_domain:
        for l in links or ():
            if same_site(l, own_domain):
                own_link = True
                break
    if best:
        (_, pos), v, loc = best
        if loc or own_link:
            why = ("full name with the town/postcode nearby" if loc
                   else "full name, and the page links to the hotel's own site")
            return {"level": "high", "why": why, "extract": window_for(pos)}
        return {"level": "medium",
                "why": "full name found but no town or postcode near it - "
                       "could be a different hotel with the same name",
                "extract": window_for(pos)}
    dts = distinctive_tokens(hotel)
    if dts and all(t in folded.split() for t in dts):
        pos = folded.find(dts[0])
        return {"level": "low",
                "why": f"only the word '{dts[0]}' appears, never the full name",
                "extract": window_for(pos)}
    return {"level": "none", "why": "the hotel is not named", "extract": ""}


def clip(text, lo, hi):
    """text[lo:hi] trimmed to word boundaries and with whitespace collapsed, so an extract
    never starts or ends in the middle of a word."""
    text = str(text or "")
    lo, hi = max(0, lo), min(len(text), hi)
    if lo > 0 and not text[lo - 1].isspace():
        sp = text.find(" ", lo, lo + 40)
        lo = sp + 1 if sp != -1 else lo
    if hi < len(text) and not text[hi:hi + 1].isspace():
        sp = text.rfind(" ", max(lo, hi - 40), hi)
        hi = sp if sp != -1 else hi
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def mention_windows(text, hotel, n=4, radius=350):
    """
    Up to `n` non-overlapping stretches of the ORIGINAL text around mentions of
    the full hotel name. Analysis of themes, awards and partnerships looks only
    inside these windows, so a roundup's language about the other nine hotels
    is never attributed to this one. Returns (windows, mention_count).
    """
    folded, idx = fold_map(text)
    variants = sorted(name_variants(hotel), key=len, reverse=True)
    spans = []
    for v in variants:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", folded):
            spans.append((m.start(), m.end()))
    spans.sort()
    # collapse overlaps between variants ("brooklands hotel" inside "brooklands hotel and spa")
    merged = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    windows, last_end = [], -1
    for s, e in merged:
        c = idx[min(s, len(idx) - 1)] if idx else 0
        lo, hi = max(0, c - radius), min(len(text), c + radius)
        if lo < last_end:
            continue
        windows.append(clip(text, lo, hi))
        last_end = hi
        if len(windows) >= n:
            break
    return windows, len(merged)


# ----------------------------------------------------------------------- ledger

class Ledger:
    """Collects evidence records and hands back stable ids (E1, E2, ...)."""

    def __init__(self, hotel="", city=""):
        self.hotel, self.city = hotel, city
        self.items = []
        self._by_key = {}

    def add(self, *, url, source, source_type="other", extract="", published=None,
            match="high", match_why="", kind="observed", via="", note="",
            supports=(), lang=None):
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        if source_type not in SOURCE_TYPES:
            source_type = "other"
        key = (url or "", (extract or "")[:80])
        if key in self._by_key:
            return self._by_key[key]
        eid = f"E{len(self.items) + 1}"
        self.items.append({
            "id": eid, "url": url or "", "source": source or domain_of(url),
            "source_type": source_type, "extract": (extract or "").strip()[:600],
            "published": published, "collected_at": now_iso(),
            "match": match, "match_why": match_why, "kind": kind,
            "via": via, "note": note, "supports": list(supports), "lang": lang,
        })
        self._by_key[key] = eid
        return eid

    def get(self, eid):
        return next((e for e in self.items if e["id"] == eid), None)

    def to_list(self):
        return list(self.items)


def parse_date(s):
    """Best-effort date -> 'YYYY-MM-DD' or None. Never guesses a day or year."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"(\d{4})(\d{2})(\d{2})T?\d{0,6}Z?$", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%d %B %Y", "%B %d, %Y", "%d %b %Y",
                "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def age_months(date_iso, today=None):
    """Whole months between a YYYY-MM-DD date and today, or None."""
    d = parse_date(date_iso)
    if not d:
        return None
    y, mo, _ = (int(x) for x in d.split("-"))
    t = today or dt.date.today()
    return max(0, (t.year - y) * 12 + (t.month - mo))
