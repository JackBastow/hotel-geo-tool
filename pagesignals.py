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

    imgs = soup.find_all("img")
    no_alt, files = 0, []
    for im in imgs:
        alt = (im.get("alt") or "").strip()
        src = im.get("src") or im.get("data-src") or ""
        # decorative images may legitimately have empty alt; count only images that look
        # like content (not tiny icons/tracking pixels)
        w = str(im.get("width") or "")
        tiny = w.isdigit() and int(w) < 40
        if not alt and not tiny and "logo" not in src.lower():
            no_alt += 1
        if len(files) < 14:
            files.append({"src": urllib.parse.unquote(src.split("?")[0].rsplit("/", 1)[-1])[:80], "alt": alt[:80]})
    sig["images"] = {"total": len(imgs), "no_alt": no_alt, "files": files}

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
