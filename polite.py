"""
Polite page reading for third-party pages (articles, guides, directories).

  * Identifies itself honestly - no browser spoofing.
  * Checks robots.txt before every fetch and does not read what it forbids.
    A page that refuses is reported as "not read: robots.txt", never silently
    dropped and never worked around.
  * Spaces out requests to the same host.
  * Reads only what it needs: bounded size, bounded time.

parse_page() pulls out what the later analysis needs: the article text, the
publisher, the publication date (only if the page states one), the page
language, outbound links, and cues that a piece is sponsored or a republished
press release.
"""

import json
import re
import time
import urllib.parse
import urllib.robotparser

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

import evidence

UA = ("HotelDiscoverabilityAudit/1.0 (+https://hotel-geo-tool.streamlit.app/; "
      "independent hotel visibility audit; respects robots.txt)")
MAX_BYTES = 1_500_000
HOST_DELAY_S = 1.0

_robots_cache = {}
_last_hit = {}


def _robots_for(origin, timeout=8):
    if origin in _robots_cache:
        return _robots_cache[origin]
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = requests.get(origin + "/robots.txt", headers={"User-Agent": UA},
                         timeout=timeout)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        elif r.status_code in (401, 403):
            rp.disallow_all = True      # forbidden robots.txt = stay out
        else:
            rp.allow_all = True         # no robots.txt = no restriction
    except requests.RequestException:
        rp.allow_all = True             # unreachable robots.txt: normal default
    _robots_cache[origin] = rp
    return rp


def allowed(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    return _robots_for(f"{p.scheme}://{p.netloc}").can_fetch(UA, url)


def fetch(url, timeout=15):
    """
    -> {"ok", "status", "url", "html", "error", "robots_blocked"}
    Never raises.
    """
    out = {"ok": False, "status": None, "url": url, "html": "", "error": None,
           "robots_blocked": False}
    if not allowed(url):
        out["robots_blocked"] = True
        out["error"] = "robots.txt asks automated tools not to read this page"
        return out
    host = urllib.parse.urlparse(url).netloc
    wait = HOST_DELAY_S - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"},
                         timeout=timeout, stream=True)
        chunks, size = [], 0
        for chunk in r.iter_content(65536):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                break
        r.close()
        body = b"".join(chunks)
        enc = r.encoding or "utf-8"
        out["status"] = r.status_code
        out["url"] = r.url
        out["html"] = body.decode(enc, errors="replace")
        ctype = r.headers.get("Content-Type", "")
        if r.status_code != 200:
            out["error"] = f"HTTP {r.status_code}"
        elif "html" not in ctype and "xml" not in ctype and "text" not in ctype:
            out["error"] = f"not a web page ({ctype or 'unknown type'})"
        else:
            out["ok"] = True
    except requests.RequestException as e:
        out["error"] = f"request failed: {type(e).__name__}"
    return out


# ----------------------------------------------------------------------- parse

SPONSORED_CUES = re.compile(
    r"\b(sponsored (?:content|post|by|feature)|advertorial|advertisement feature|"
    r"paid partnership|partner content|in association with|promoted content|"
    r"commercial feature|brand(?:ed)? content|presented by)\b", re.I)
PRESS_RELEASE_CUES = re.compile(
    r"\b(press release|for immediate release|notes to editors|issued by|"
    r"media contact|press contact|pr contact)\b", re.I)


def _meta(soup, *names):
    for n in names:
        tag = (soup.find("meta", attrs={"property": n})
               or soup.find("meta", attrs={"name": n})
               or soup.find("meta", attrs={"itemprop": n}))
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _jsonld(soup):
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                out.append(n)
                for v in n.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(n, list):
                stack.extend(n)
    return out


def parse_page(html, url=""):
    """Structured facts about an article-like page. Returns {} if unreadable."""
    if not html or BeautifulSoup is None:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    ld = _jsonld(soup)

    published = evidence.parse_date(_meta(
        soup, "article:published_time", "datePublished", "og:article:published_time",
        "date", "pubdate", "DC.date.issued", "parsely-pub-date"))
    if not published:
        for n in ld:
            published = evidence.parse_date(n.get("datePublished") or n.get("dateCreated"))
            if published:
                break
    if not published:
        t = soup.find("time", attrs={"datetime": True})
        published = evidence.parse_date(t["datetime"]) if t else None
    modified = evidence.parse_date(_meta(soup, "article:modified_time", "dateModified")
                                   or next((n.get("dateModified") for n in ld
                                            if n.get("dateModified")), None))

    publisher = _meta(soup, "og:site_name", "application-name", "publisher")
    if not publisher:
        for n in ld:
            p = n.get("publisher")
            if isinstance(p, dict) and p.get("name"):
                publisher = str(p["name"])
                break
    author = _meta(soup, "author", "article:author")
    if not author:
        for n in ld:
            a = n.get("author")
            if isinstance(a, dict) and a.get("name"):
                author = str(a["name"])
                break
            if isinstance(a, list) and a and isinstance(a[0], dict) and a[0].get("name"):
                author = str(a[0]["name"])
                break
    title = (_meta(soup, "og:title") or (soup.title.string.strip()
             if soup.title and soup.title.string else "") or "")
    canonical = None
    ct = soup.find("link", rel="canonical")
    if ct and ct.get("href"):
        canonical = urllib.parse.urljoin(url, ct["href"])
    lang_attr = (soup.html.get("lang") if soup.html else None) or None

    links = []
    for a in soup.find_all("a", href=True):
        h = urllib.parse.urljoin(url, a["href"])
        if h.startswith("http"):
            links.append(h)
    sponsored_rel = any("sponsored" in (a.get("rel") or []) for a in soup.find_all("a"))

    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript",
                     "aside", "iframe"]):
        tag.decompose()
    # The article body is not always an <article>: sites wrap teaser cards in
    # <article> too (a Visit Surrey blog post yielded a 24-character "article").
    # Take the biggest of article/main, and fall back to the whole body when
    # that is too thin to be a real article.
    def size(n):
        return len(n.get_text(" ", strip=True))
    cands = soup.find_all("article") + soup.find_all("main")
    node = max(cands, key=size) if cands else None
    if node is None or size(node) < 500:
        node = soup.body or soup
    text = re.sub(r"\s+", " ", node.get_text(separator=" ", strip=True))

    # Headed sections (h2/h3 + the text up to the next heading). Roundups
    # ("10 best hotels in X") are structured as one heading per property, so
    # this lets us see WHICH hotels a guide features and what it says of each.
    sections = []
    for h in node.find_all(["h2", "h3"]):
        heading = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
        if not heading or len(heading) > 140:
            continue
        parts = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) in ("h2", "h3"):
                break
            if hasattr(sib, "get_text"):
                parts.append(sib.get_text(" ", strip=True))
            elif isinstance(sib, str):
                parts.append(sib.strip())
        sections.append({"heading": heading,
                         "text": re.sub(r"\s+", " ", " ".join(parts))[:700]})
        if len(sections) >= 60:
            break

    head = text[:2500]
    sp = SPONSORED_CUES.search(head)
    pr = PRESS_RELEASE_CUES.search(text[:4000]) or PRESS_RELEASE_CUES.search(text[-1500:])
    return {
        "title": re.sub(r"\s+", " ", title)[:200],
        "publisher": publisher, "author": author, "published": published,
        "modified": modified, "canonical": canonical, "lang_attr": lang_attr,
        "text": text[:40000], "links": links[:400], "sections": sections,
        "sponsored_cue": bool(sp) or sponsored_rel,
        "sponsored_cue_text": sp.group(0) if sp else ("rel=sponsored links" if sponsored_rel else None),
        "press_release_cue": bool(pr),
        "press_release_cue_text": pr.group(0) if pr else None,
    }


def read(url, timeout=15):
    """fetch + parse in one go. -> {"fetch": {...}, "page": {...}}"""
    f = fetch(url, timeout=timeout)
    page = parse_page(f["html"], f["url"]) if f["ok"] else {}
    f.pop("html", None)
    return {"fetch": f, "page": page}
