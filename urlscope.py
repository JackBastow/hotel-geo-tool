"""
What the visitor typed, turned into something the audit can use.

People paste whatever is in their address bar: tracking parameters (?msockid=...), a language
folder, or - for chain hotels - a page inside the brand's website
(hilton.com/en/hotels/xyz-doubletree-luxembourg/). Treating that as "the hotel's website" gave
a malformed address and then audited the whole brand site.

  normalise(text)  -> (start_url, scope)
      start_url: scheme + host + path, no query or fragment, always ending in "/"
      scope:     None for an ordinary site (an inner page like /rooms/ starts from the site's front page); for a
                 chain page, the path prefix that belongs to this one hotel, e.g. "/en/hotels/xyz-doubletree-luxembourg/"
  in_scope(url, scope) -> True when the URL is inside that prefix (always True when scope is None)
"""

import re
import urllib.parse

# folders that name a place's own section on a multi-property website
_PROPERTY_FOLDERS = {"hotels", "hotel", "properties", "property", "resorts", "resort", "locations", "destinations", "rooms-and-suites-hotels"}
_LANG = re.compile(r"^[a-z]{2}([-_][a-z]{2,4})?$", re.I)


def normalise(text):
    raw = (text or "").strip()
    if "//" not in raw:
        raw = "https://" + raw
    p = urllib.parse.urlparse(raw)
    host = p.netloc.lower()
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    segs = [s for s in path.split("/") if s]
    if segs and "." in segs[-1]:                      # a file such as /index.html: the page's folder is the unit
        segs = segs[:-1]
    start = urllib.parse.urlunparse((p.scheme or "https", host, "/" + "/".join(segs) + ("/" if segs else ""), "", "", ""))
    content = [s for s in segs if not _LANG.match(s)]
    if not content:
        return start, None
    # a chain page: keep everything up to and including the folder that names this hotel
    for i, s in enumerate(segs):
        if s.lower() in _PROPERTY_FOLDERS and i + 1 < len(segs):
            return start, "/" + "/".join(segs[: i + 2]) + "/"
    # an ordinary site and the visitor pasted an inner page (/rooms/): they mean the hotel's whole website
    return urllib.parse.urlunparse((p.scheme or "https", host, "/", "", "", "")), None


def in_scope(url, scope):
    if not scope:
        return True
    return urllib.parse.urlparse(url).path.lower().startswith(scope.lower())


def origin(url):
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def scope_note(start_url, scope):
    if not scope:
        return ""
    host = urllib.parse.urlparse(start_url).netloc
    return (f"You entered a page inside a larger website ({host}), so only this hotel's own pages were read. robots.txt, the sitemap and "
            f"other site-wide settings belong to the whole {host} website, which the hotel usually can't change itself; "
            "raise those with the brand's web team.")


# ------------------------------------------------------------ a name from the address

_BRAND_OR_COMMON = {"hotel", "hotels", "the", "grand", "royal", "hilton", "marriott", "hyatt", "radisson", "holiday", "inn", "best", "western", "park",
                    "doubletree", "hampton", "courtyard", "ibis", "novotel", "mercure", "sofitel", "resort", "spa", "suites", "lodge", "house", "manor"}


_BRAND_NAMES = {"doubletree": "DoubleTree by Hilton", "hampton": "Hampton by Hilton", "conrad": "Conrad", "canopy": "Canopy by Hilton",
                "curio": "Curio Collection by Hilton", "tapestry": "Tapestry Collection by Hilton", "waldorf": "Waldorf Astoria", "embassy": "Embassy Suites by Hilton"}


_CODE_HOSTS = ("marriott.com",)        # their address is /hotels/<5-letter property code>-<hotel name>/ (paroa-paris-marriott-opera-ambassador-hotel)


def property_code(start_url, scope=None):
    """The property code at the front of a chain hotel's address slug ('paroa', 'lxmhidi'), or '' when the slug has none."""
    path = scope or urllib.parse.urlparse(start_url).path
    segs = [s for s in path.split("/") if s]
    if not segs:
        return ""
    toks = [t for t in re.split(r"[-_]+", segs[-1].lower()) if t]
    host = urllib.parse.urlparse(start_url).netloc.lower()
    if len(toks) >= 3 and toks[0] not in _BRAND_OR_COMMON and (
            (re.fullmatch(r"[a-z]{5,8}", toks[0]) and sum(c in "aeiou" for c in toks[0]) <= 2)
            or (host.endswith(_CODE_HOSTS) and re.fullmatch(r"[a-z]{5}", toks[0]))):
        return toks[0]
    return ""


_NOT_A_PLACE = _BRAND_OR_COMMON | {"airport", "apartments", "apartment", "residence", "residences", "collection", "hostel", "motel", "and", "by", "at", "of", "in", "centre", "center", "station",
                                    "central", "city", "plaza", "garden", "gardens", "express", "premier", "plus", "boutique", "luxury", "beach", "lake", "view", "sheraton", "westin", "radisson",
                                    "blu", "hyatt", "regency", "ibis", "budget", "styles", "novotel", "mercure", "pullman", "kimpton", "intercontinental", "crowne", "plaza", "renaissance", "meridien",
                                    "four", "seasons", "ritz", "carlton", "mandarin", "oriental", "fairmont", "ambassador", "opera", "club", "tower", "towers", "palace", "castle", "court", "lodge"}


def place_candidates(name, limit=6):
    """
    Words in a hotel's name (or address slug) that might be its town: 'Hilton Zurich Airport' -> ['zurich']. Brand, lodging and generic words are skipped; single words come first (later words
    before earlier ones, because the town usually follows the brand), then pairs ('new york'). Each is only a candidate: the caller asks a place search whether it really is a town.
    """
    toks = [t for t in re.split(r"[^a-z\u00c0-\u024f]+", str(name or "").lower()) if len(t) >= 3]
    keep = [t for t in toks if t not in _NOT_A_PLACE]
    out = list(reversed(keep))
    for i in range(len(toks) - 1, 0, -1):
        a, b = toks[i - 1], toks[i]
        if a not in _NOT_A_PLACE and b not in _NOT_A_PLACE:
            out.append(f"{a} {b}")
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:limit]


def name_from_url(start_url, scope):
    """
    For a chain's page whose content we cannot read, the address itself usually names the hotel:
    /en/hotels/lxmhidi-doubletree-luxembourg/ -> "Doubletree Luxembourg". A leading run of letters that
    looks like a property code (lxmhidi, lonlm) is dropped. Returns {"name", "city_candidates"}; both empty
    when the address says nothing useful. This is a GUESS and is always reported as one.
    """
    path = scope or urllib.parse.urlparse(start_url).path
    segs = [s for s in path.split("/") if s]
    if not segs:
        return {"name": "", "city_candidates": []}
    slug = segs[-1]
    toks = [t for t in re.split(r"[-_]+", slug.lower()) if t]
    if property_code(start_url, scope):
        toks = toks[1:]
    if not (2 <= len(toks) <= 8) or any(t.isdigit() for t in toks):
        return {"name": "", "city_candidates": []}
    host = urllib.parse.urlparse(start_url).netloc.lower()
    brand = _BRAND_NAMES.get(toks[0]) if host.endswith("hilton.com") else None      # "doubletree-luxembourg" is "DoubleTree by Hilton Luxembourg"
    if brand:
        full = brand + " " + " ".join(t.capitalize() for t in toks[1:])
        return {"name": full, "city_candidates": place_candidates(" ".join(toks[1:])) or [toks[-1]]}
    return {"name": " ".join(t.capitalize() for t in toks), "city_candidates": place_candidates(" ".join(toks)) or [toks[-1]]}
