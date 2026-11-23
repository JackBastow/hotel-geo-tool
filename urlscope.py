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
import threading
import unicodedata
import urllib.parse

_HINT = threading.local()          # the hotel's name and town for the audit running in this thread (set by full_audit.run_full_audit)


def set_hint(hotel="", city=""):
    """Tell normalise() which hotel and town this audit is about, so a brand site's folder named after the town or the hotel ('thenici.com/newquay/') is read as that hotel's own section."""
    _HINT.names = (hotel or "", city or "")


def _words(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", s))


# first folders that are ordinary pages of a single hotel's own website, never a property's section
_GENERIC = {"rooms", "room", "suites", "accommodation", "stay", "contact", "contact-us", "about", "about-us", "offers", "special-offers", "packages", "dining", "restaurant", "restaurants", "food",
            "bar", "spa", "wellness", "meetings", "meetings-events", "events", "weddings", "gallery", "location", "location-map", "find-us", "faq", "faqs", "book", "booking", "news", "blog", "home",
            "index", "en", "our-story", "experiences", "things-to-do", "explore", "facilities", "amenities", "careers", "jobs", "press", "gift-vouchers", "vouchers", "privacy", "terms", "policies"}

# folders that name a place's own section on a multi-property website
_PROPERTY_FOLDERS = {"hotels", "hotel", "properties", "property", "resorts", "resort", "locations", "destinations", "rooms-and-suites-hotels"}
_LANG = re.compile(r"^[a-z]{2}([-_][a-z]{2,4})?$", re.I)


def normalise(text, hotel=None, city=None):
    """
    -> (start_url, scope). A brand site's folder is the hotel's own section when it is a known property folder (/hotels/xyz/), or when its name is the hotel's town or part of its name
    (thenici.com/newquay/ for 'THE NICI Newquay'): then only that folder is the hotel's website, never the whole brand site with its other hotels.
    """
    if hotel is None and city is None:
        hotel, city = getattr(_HINT, "names", ("", ""))
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
    # a brand site's folder named after this hotel's town or the hotel itself: that folder is the hotel's own section
    names = _words(hotel) | _words(city)
    first_i = next(i for i, s in enumerate(segs) if not _LANG.match(s))
    first = segs[first_i]
    fw = _words(first.replace("-", " ").replace("_", " "))
    if names and first.lower() not in _GENERIC and fw and fw <= names and not fw <= {"the", "hotel", "hotels", "and", "spa", "resort"}:
        last = first_i
        for j in range(first_i + 1, len(segs)):              # thehoxton.com/london/shoreditch/: the hotel's section is the deepest folder still named after it, not the whole city
            wj = _words(segs[j].replace("-", " ").replace("_", " "))
            if segs[j].lower() in _GENERIC or not wj or not wj <= names:
                break
            last = j
        scope = "/" + "/".join(segs[: last + 1]) + "/"
        return urllib.parse.urlunparse((p.scheme or "https", host, scope, "", "", "")), scope
    # an ordinary site and the visitor pasted an inner page (/rooms/): they mean the hotel's whole website
    return urllib.parse.urlunparse((p.scheme or "https", host, "/", "", "", "")), None


def in_scope(url, scope):
    if not scope:
        return True
    return urllib.parse.urlparse(url).path.lower().startswith(scope.lower())


def origin(url):
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"


_SECOND_LEVEL = {"co.uk", "org.uk", "ac.uk", "com.au", "co.nz", "com.br", "co.za", "co.jp", "com.mx", "com.tr", "com.sg", "co.in"}


def registered_domain(netloc):
    """'spa.accor.com' -> 'accor.com'; 'www.somehotel.co.uk' -> 'somehotel.co.uk'."""
    labels = [x for x in (netloc or "").lower().split(":")[0].split(".") if x]
    if len(labels) >= 3 and ".".join(labels[-2:]) in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def property_token(scope):
    """The part of a chain hotel's folder that identifies it, wherever else it is repeated: '/hotel/1168/' -> '1168', '/en/hotels/zrhhitw-hilton-zurich-airport/' -> 'zrhhitw-hilton-zurich-airport'."""
    segs = [s for s in (scope or "").split("/") if s]
    tok = segs[-1] if segs else ""
    if tok.isdigit():
        return tok if len(tok) >= 3 else ""
    return tok if len(tok) >= 8 else ""


def is_sibling(url, base_host, scope):
    """
    Is this link one of the hotel's own pages on another address of the same chain website (a spa, restaurant or meetings site such as spa.accor.com/en/hotels/1168)? Only when it is on the same
    registered domain AND carries the hotel's own identifier (its id or full address slug) as a whole token in its address, so another hotel's page and a general brand page never qualify.
    """
    tok = property_token(scope)
    if not tok:
        return False
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or bare_host(p.netloc) == bare_host(base_host) or registered_domain(p.netloc) != registered_domain(base_host):
        return False
    if re.search(r"/(?:booking|book|reservation|checkout|login|account|search)(?:/|$)", p.path, re.I):
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", p.path + "?" + p.query))


def bare_host(netloc):
    h = (netloc or "").lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


_TRACKING = re.compile(r"^(?:utm_.*|gclid|gbraid|wbraid|fbclid|msclkid|msockid|mc_cid|mc_eid|igshid|igsh|_ga|_gl|yclid|dclid|cmpid|ref_src|sc_cid|srsltid)$", re.I)
_INDEX = re.compile(r"/index(?:[._-][a-z]{2}(?:[_-][a-z]{2})?)?\.(?:s?html?|php\d?|aspx?|jsp|cfm)$", re.I)


def canon_index(path):
    """A folder and its index file are the same page: '/hotel/1168/index.en.shtml' -> '/hotel/1168/'."""
    return _INDEX.sub("/", path or "/")


def clean_entry(text):
    """
    The address exactly as the visitor pasted it, with only what never changes the page removed: the #fragment and tracking parameters (utm_*, fbclid, msockid...). The path, a file name such as
    index.en.shtml, a trailing slash and any other query parameter are kept as typed.
    """
    raw = (text or "").strip()
    if "//" not in raw:
        raw = "https://" + raw
    p = urllib.parse.urlparse(raw)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urllib.parse.urlunparse((p.scheme or "https", p.netloc.lower(), path, "", urllib.parse.urlencode(q), ""))


def address_forms(entry):
    """
    Other forms of the same address, to try only if the exact one does not answer: the other trailing-slash form, the page's folder if it ended in an index file, the file name with the index file
    added if it was a folder, and the other of www / no-www. -> [(url, why)] in the order they are tried.
    """
    p = urllib.parse.urlparse(entry)
    base = lambda path, host=None, query=p.query: urllib.parse.urlunparse((p.scheme, host or p.netloc, path, "", query, ""))      # noqa: E731
    out = [(entry, "the address exactly as submitted")]
    path = p.path or "/"
    if path != "/" and "." not in path.rsplit("/", 1)[-1]:
        out.append((base(path.rstrip("/") if path.endswith("/") else path + "/"), "the other trailing-slash form"))
    if _INDEX.search(path):
        out.append((base(canon_index(path)), "the page's folder"))
    host = p.netloc.lower()
    alt = host[4:] if host.startswith("www.") else "www." + host
    out.append((base(path, alt), "the same address on the other of www / no-www"))
    seen, uniq = set(), []
    for u, w in out:
        if u not in seen:
            seen.add(u)
            uniq.append((u, w))
    return uniq


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


_COUNTRY_NAMES = {"france", "germany", "spain", "italy", "portugal", "netherlands", "belgium", "switzerland", "austria", "ireland", "england", "scotland", "wales", "united kingdom", "uk", "great britain", "britain",
                  "united states", "usa", "us", "america", "canada", "mexico", "brazil", "argentina", "chile", "peru", "colombia", "australia", "new zealand", "japan", "china", "india", "thailand", "vietnam", "indonesia",
                  "malaysia", "singapore", "turkey", "greece", "croatia", "czech republic", "czechia", "poland", "hungary", "romania", "bulgaria", "denmark", "sweden", "norway", "finland", "iceland", "estonia", "latvia",
                  "lithuania", "luxembourg", "malta", "cyprus", "morocco", "egypt", "south africa", "kenya", "tanzania", "uae", "united arab emirates", "qatar", "saudi arabia", "israel", "jordan"}


def is_country(name):
    """True when the 'town' someone gave is really a country ('France'): the questions put to AI assistants and the place checks need a town, so a country is never accepted in its place."""
    return " ".join((name or "").lower().replace(",", " ").split()) in _COUNTRY_NAMES
