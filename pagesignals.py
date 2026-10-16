"""
Machine-readability signals pulled from a page the crawl has ALREADY fetched.

Nothing here makes a request. guest_questions._parse_html calls extract()
on the parsed page before it strips scripts, so we see what a crawler sees
in the raw HTML: metadata, structured data, images, PDF links, how much of
the page is real text, and whether it looks like an empty JavaScript shell.

This reads the raw HTML only. It does NOT run JavaScript, so "rendered versus
raw" is approximated by a heuristic (little text + an app-shell marker), and
the report says so.
"""

import json
import re
import urllib.parse

SPA_MARKERS = re.compile(
    r'id=["\'](?:root|app|__next|__nuxt|___gatsby)["\']|data-reactroot|ng-app|ng-version|'
    r'window\.__(?:NEXT_DATA|NUXT)__|<noscript[^>]*>[^<]*(?:enable|requires?)[^<]*javascript',
    re.I)
QUESTION_START = re.compile(
    r"^(?:what|when|where|which|who|how|can|could|do|does|is|are|will|am|may|should)\b", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _meta(soup, **attrs):
    tag = soup.find("meta", attrs=attrs)
    return _clean(tag.get("content")) if tag and tag.get("content") else ""


def _walk(node, out):
    if isinstance(node, list):
        for n in node:
            _walk(n, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _walk(node["@graph"], out)
        if node.get("@type"):
            out.append(node)
        for k, v in node.items():
            if k != "@graph" and isinstance(v, (dict, list)):
                _walk(v, out)


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def _types(node):
    return [str(t) for t in _as_list(node.get("@type"))]


def _compact(node):
    """The parts of one JSON-LD node the audit needs, small enough to store."""
    addr = node.get("address")
    if isinstance(addr, list) and addr:
        addr = addr[0]
    geo = node.get("geo")
    agg = node.get("aggregateRating")
    amen = []
    for a in _as_list(node.get("amenityFeature")):
        if isinstance(a, dict):
            amen.append({"name": str(a.get("name", ""))[:60], "value": a.get("value")})
        elif isinstance(a, str):
            amen.append({"name": a[:60], "value": None})
    return {
        "types": _types(node), "keys": sorted(k for k in node if not k.startswith("@")),
        "name": str(node.get("name", ""))[:120] if not isinstance(node.get("name"), (dict, list)) else "",
        "url": node.get("url") if isinstance(node.get("url"), str) else "",
        "telephone": node.get("telephone") if isinstance(node.get("telephone"), str) else "",
        "address": ({k: addr.get(k) for k in ("@type", "streetAddress", "addressLocality",
                                               "addressRegion", "postalCode", "addressCountry")
                     if isinstance(addr, dict) and addr.get(k)} if isinstance(addr, dict) else
                    ({"raw": addr[:160]} if isinstance(addr, str) else {})),
        "geo": ({k: geo.get(k) for k in ("@type", "latitude", "longitude")}
                if isinstance(geo, dict) else {}),
        "checkinTime": node.get("checkinTime"), "checkoutTime": node.get("checkoutTime"),
        "priceRange": node.get("priceRange"), "starRating": node.get("starRating") is not None,
        "sameAs": [s for s in _as_list(node.get("sameAs")) if isinstance(s, str)][:12],
        "amenities": amen[:30],
        "aggregateRating": ({"ratingValue": agg.get("ratingValue"), "reviewCount": agg.get("reviewCount")
                             or agg.get("ratingCount")} if isinstance(agg, dict) else None),
        "image": bool(node.get("image")), "description": bool(node.get("description")),
        "n_questions": len(_as_list(node.get("mainEntity"))) if "FAQPage" in _types(node) else 0,
    }


def structured_data(soup):
    nodes, bad = [], 0
    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = s.string or s.get_text() or ""
        try:
            data = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        found = []
        _walk(data, found)
        nodes += [_compact(n) for n in found]
    return nodes, bad


_TRACKING = re.compile(r"pixel|track|beacon|analytics|doubleclick|googleads|facebook\.com/tr|bat\.bing|adsystem|spacer|1x1|blank\.(?:gif|png)|clear\.gif|transparent", re.I)
_DECORATIVE_CLASS = re.compile(r"icon|logo|sprite|spacer|bullet|divider|arrow|star|avatar|flag|badge|payment|social", re.I)
_KEY_KINDS = [("room", re.compile(r"room|suite|bedroom|bed\b|twin|double|king|queen|family|apartment|accommodation", re.I)),
              ("restaurant", re.compile(r"restaurant|dining|dishes?|menu|food|bar\b|grill|breakfast|afternoon|tea\b|cocktail|brasserie|chef", re.I)),
              ("spa", re.compile(r"\bspa\b|pool|sauna|steam|treatment|massage|wellness|gym|fitness", re.I)),
              ("facility", re.compile(r"meeting|conference|boardroom|wedding|ceremony|event|garden|terrace|lobby|reception|exterior|hotel[-_ ]?front|lounge|ballroom|function", re.I))]


def _real_src(im):
    """The address an image will actually show: lazy-loaders put a base64 or 1-pixel placeholder in src and the real file in a data attribute."""
    cands = [im.get(k) or "" for k in ("data-src", "data-lazy-src", "data-original", "data-lazy", "src")]
    for c in cands:
        if c and not c.startswith("data:"):
            return c
    srcset = (im.get("data-srcset") or im.get("srcset") or "").split(",")[0].strip().split(" ")[0]
    return srcset if srcset and not srcset.startswith("data:") else ""


_PAGE_KIND = [("room", re.compile(r"/(?:rooms?|suites?|accommodation|bedrooms?|stay)(?:/|$|-)", re.I)), ("restaurant", re.compile(r"/(?:eat|dine|dining|restaurants?|bar|menus?|food|afternoon-tea|eat-drink)(?:/|$|-)", re.I)),
              ("spa", re.compile(r"/(?:spa|bspa|wellness|treatments?|pool|leisure|gym)(?:/|$|-)", re.I)), ("facility", re.compile(r"/(?:meetings?|conference|events?|weddings?|private-dining|occasions|facilities|gardens?)(?:/|$|-)", re.I))]


def image_summary(soup, url=""):
    """
    Images on the page, counted the way a guest or a screen reader would meet them. Tracking pixels, base64 or 1-pixel placeholders, vector icons, logos and decorative images (empty alt on
    purpose, role=presentation, aria-hidden) are not content images and are left out. Of the content images, those that show rooms, food and drink, the spa or the hotel's facilities are
    the key ones: they are what a traveller (and a system describing the hotel) most needs words for.
    -> {total: every <img>, content: real images, no_alt: content images with no alt, key: key images, key_no_alt, skipped: {placeholders, tracking, decorative}, files: examples}
    """
    total = skipped_ph = skipped_tr = skipped_dec = 0
    content = no_alt = key = key_no_alt = 0
    files, key_files, by_kind = [], [], {}
    for im in soup.find_all("img"):
        total += 1
        src = _real_src(im)
        raw = im.get("src") or ""
        w, h = str(im.get("width") or ""), str(im.get("height") or "")
        if not src:
            skipped_ph += 1                  # only a base64 / data placeholder, with no real file behind it
            continue
        if _TRACKING.search(src) or (w.isdigit() and h.isdigit() and int(w) <= 2 and int(h) <= 2):
            skipped_tr += 1
            continue
        cls = " ".join(im.get("class") or []) if isinstance(im.get("class"), list) else str(im.get("class") or "")
        alt_attr = im.get("alt")
        name = urllib.parse.unquote(src.split("?")[0].rsplit("/", 1)[-1])[:80]
        fig = im.find_parent("figure")
        caption = fig.find("figcaption").get_text(" ")[:150] if fig is not None and fig.find("figcaption") else ""
        # what the picture shows: the kind of page it is on (rooms, dining, spa, meetings...) first, then its file name, class and caption. Navigation text around it is not used.
        name_kind = next((k for k, rxk in _KEY_KINDS if rxk.search(" ".join([name, caption]))), "")        # the file name and caption say what a picture shows; CSS classes (carousel, menu, bar...) do not
        kind = name_kind or next((k for k, rxp in _PAGE_KIND if rxp.search(urllib.parse.urlparse(url).path + "/")), "")
        alt = (alt_attr or "").strip()
        decorative = (im.get("role") in ("presentation", "none") or im.get("aria-hidden") == "true" or src.lower().split("?")[0].endswith(".svg") or (w.isdigit() and int(w) < 48)
                      or bool(_DECORATIVE_CLASS.search(cls)) or "logo" in src.lower() or (alt_attr is not None and not alt and not name_kind))      # an alt left empty on purpose, on a picture of nothing in particular
        if decorative:
            skipped_dec += 1
            continue
        content += 1
        if kind:
            key += 1
        if not alt:
            no_alt += 1
            if kind:
                key_no_alt += 1
                by_kind[kind] = by_kind.get(kind, 0) + 1
                if len(key_files) < 8:
                    key_files.append({"src": name, "kind": kind})
        if len(files) < 14:
            files.append({"src": name, "alt": alt[:80]})
    return {"total": total, "content": content, "no_alt": no_alt, "key": key, "key_no_alt": key_no_alt, "key_files": key_files, "key_no_alt_by_kind": by_kind,
            "skipped": {"placeholders": skipped_ph, "tracking": skipped_tr, "decorative": skipped_dec}, "files": files}


def extract(soup, url, raw_html):
    """-> dict of signals. Call BEFORE scripts/nav/footer are removed from `soup`."""
    sig = {}
    sig["meta_description"] = _meta(soup, name="description")[:400]
    canon = soup.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else [r]))
    sig["canonical"] = urllib.parse.urljoin(url, canon["href"]) if canon and canon.get("href") else None
    robots = _meta(soup, name=re.compile("^robots$", re.I)).lower()
    sig["robots_meta"] = robots
    sig["noindex"] = "noindex" in robots
    sig["og"] = {"title": _meta(soup, property="og:title"), "description": _meta(soup, property="og:description"),
                 "image": _meta(soup, property="og:image")}
    sig["hreflang"] = [l.get("hreflang") for l in soup.find_all("link", hreflang=True)][:12]
    sig["lang"] = (soup.html.get("lang") if soup.html else None) or None
    sig["structured"], sig["jsonld_errors"] = structured_data(soup)

    sig["images"] = image_summary(soup, url)

    pdfs = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if re.search(r"\.pdf(?:$|[?#])", href, re.I):
            pdfs.append({"url": urllib.parse.urljoin(url, href), "anchor": _clean(a.get_text(" "))[:90]})
    sig["pdfs"] = pdfs[:12]

    sig["scripts"] = len(soup.find_all("script"))
    sig["spa_marker"] = bool(SPA_MARKERS.search(raw_html[:200000]))
    sig["html_bytes"] = len(raw_html)
    sig["breadcrumb"] = bool(soup.find(attrs={"aria-label": re.compile("breadcrumb", re.I)})
                             or soup.find(class_=re.compile("breadcrumb", re.I)))

    heads = []
    for h in soup.find_all(["h2", "h3"]):
        t = _clean(h.get_text(" "))
        if t:
            heads.append(t[:120])
    sig["headings"] = heads[:30]
    qs = [h for h in heads if h.endswith("?") or QUESTION_START.match(h)]
    # <details>/<summary> accordions and <dt> lists are common FAQ markup
    qs += [_clean(s.get_text(" "))[:120] for s in soup.find_all("summary")]
    sig["faq_like_items"] = len(qs)
    sig["h1_count"] = len(soup.find_all("h1"))
    return sig


def finish(sig, text):
    """Add the signals that need the final visible text."""
    words = len(re.findall(r"\w+", text))
    sig["word_count"] = words
    # visible text per KB of HTML: a near-empty page with an app-shell marker is
    # what a crawler that doesn't run JavaScript sees for a JS-built site
    sig["text_density"] = round(len(text) / max(1, sig.get("html_bytes", 1)), 3)
    sig["js_shell"] = bool(sig.get("spa_marker") and words < 120)
    return sig
