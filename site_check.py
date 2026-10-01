#!/usr/bin/env python3
"""
First-party website machine-readability check (audit sections 2 and 7).

Needs no API key. Fetches only the hotel's own public website.

What it establishes as OBSERVED fact:
  - robots.txt present, and whether it blocks AI/search crawlers
  - sitemap.xml present, and how many URLs it declares
  - JSON-LD structured data on key pages, and which schema types
  - which Hotel/LodgingBusiness properties are actually populated
  - title, meta description, canonical, H1 presence per page
  - which traveller topics have a discoverable page at all

What it does NOT do: judge content quality. A page existing is not the same
as a page answering the question. Topic coverage here is a candidate list
for human/AI review, not a verdict.

Usage:
  python3 site_check.py --website brooklandshotelsurrey.com --out site.json
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = ("Mozilla/5.0 (compatible; HotelAuditBot/1.0; "
      "+digital visibility audit; contact: site owner)")

# Topics from the audit spec, with the URL fragments that usually signal them.
TOPIC_SIGNALS = {
    "rooms": ["room", "suite", "accommodation", "bedroom"],
    "restaurant": ["restaurant", "dining", "dine", "brasserie", "grill"],
    "bar": ["bar", "lounge", "cocktail"],
    "breakfast": ["breakfast"],
    "spa": ["spa", "wellness", "treatment"],
    "pool": ["pool", "swim"],
    "gym": ["gym", "fitness", "health-club", "leisure"],
    "meetings_events": ["meeting", "conference", "event", "corporate", "business"],
    "weddings": ["wedding", "civil-ceremony"],
    "parking": ["parking", "car-park"],
    "transport": ["transport", "getting-here", "how-to-find", "directions", "travel"],
    "location": ["location", "find-us", "where-we-are", "area"],
    "accessibility": ["accessib", "disabled", "mobility"],
    "families": ["family", "families", "kids", "children"],
    "pets": ["pet", "dog-friendly", "dogs"],
    "offers": ["offer", "package", "deal", "special"],
    "contact": ["contact"],
    "attractions": ["attraction", "things-to-do", "explore", "nearby", "local"],
    "faq": ["faq", "frequently-asked", "questions"],
    "gallery": ["gallery", "photo"],
}

# Properties that matter for an AI trying to describe a hotel as an entity.
LODGING_PROPS = [
    "name", "address", "geo", "telephone", "email", "url", "image",
    "priceRange", "starRating", "amenityFeature", "checkinTime",
    "checkoutTime", "numberOfRooms", "aggregateRating", "review",
    "petsAllowed", "makesOffer", "containsPlace", "hasMap", "sameAs",
]

# Crawlers worth checking specifically - AI training/answering agents.
AI_AGENTS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User",
    "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended",
    "Applebot-Extended", "CCBot", "Bytespider", "Amazonbot", "meta-externalagent",
]


def get(url, timeout=25):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout,
                         allow_redirects=True)
        return r
    except requests.RequestException as e:
        return None


# ------------------------------------------------------------------- robots

def check_robots(base):
    url = urllib.parse.urljoin(base, "/robots.txt")
    r = get(url)
    out = {"url": url, "present": False, "status": None, "sitemaps": [],
           "ai_agent_rules": {}, "blocks_all": False, "raw_excerpt": ""}
    if r is None:
        out["error"] = "request failed"
        return out
    out["status"] = r.status_code
    if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
        return out
    out["present"] = True
    text = r.text
    out["raw_excerpt"] = text[:1500]
    out["sitemaps"] = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)

    # parse into user-agent blocks
    blocks, current = {}, None
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"(?i)user-agent:\s*(.+)", line)
        if m:
            current = m.group(1).strip()
            blocks.setdefault(current, [])
            continue
        m = re.match(r"(?i)(dis)?allow:\s*(.*)", line)
        if m and current is not None:
            blocks[current].append(
                ("disallow" if m.group(1) else "allow", m.group(2).strip())
            )

    for agent in AI_AGENTS:
        for ua, rules in blocks.items():
            if ua.lower() == agent.lower():
                blocked = any(k == "disallow" and v == "/" for k, v in rules)
                out["ai_agent_rules"][agent] = {
                    "declared": True, "blocked_entirely": blocked, "rules": rules,
                }
    star = blocks.get("*", [])
    out["blocks_all"] = any(k == "disallow" and v == "/" for k, v in star)
    return out


# ------------------------------------------------------------------ sitemap

def check_sitemap(base, robots_sitemaps):
    candidates = list(robots_sitemaps) + [
        urllib.parse.urljoin(base, "/sitemap.xml"),
        urllib.parse.urljoin(base, "/sitemap_index.xml"),
    ]
    # lastmod is collected alongside the URLs because it is the only free,
    # site-wide freshness signal available - it says when the hotel last
    # touched each page, which is what "is this information current?" turns
    # into in practice.
    seen, urls, found, lastmods = set(), [], [], []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        r = get(c)
        if r is None or r.status_code != 200:
            continue
        found.append(c)
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        # index of sitemaps
        for sm in root.findall(f"{ns}sitemap"):
            loc = sm.findtext(f"{ns}loc")
            if loc and loc not in seen and len(seen) < 25:
                seen.add(loc)
                rr = get(loc)
                if rr is not None and rr.status_code == 200:
                    try:
                        sub = ET.fromstring(rr.content)
                        for u in sub.findall(f"{ns}url"):
                            urls.append(u.findtext(f"{ns}loc"))
                            lastmods.append(u.findtext(f"{ns}lastmod"))
                    except ET.ParseError:
                        pass
        for u in root.findall(f"{ns}url"):
            urls.append(u.findtext(f"{ns}loc"))
            lastmods.append(u.findtext(f"{ns}lastmod"))
    pairs = [(u, lm) for u, lm in zip(urls, lastmods) if u]
    urls = [u for u, _ in pairs]
    return {"found_at": found, "present": bool(found),
            "url_count": len(urls), "urls": urls[:2000],
            "lastmods": [lm for _, lm in pairs if lm][:2000]}


# ------------------------------------------------------------- page analysis

def analyse_page(url):
    r = get(url)
    out = {"url": url, "ok": False, "status": None}
    if r is None:
        out["error"] = "request failed"
        return out
    out["status"] = r.status_code
    if r.status_code != 200:
        return out
    html = r.text
    out["ok"] = True
    out["final_url"] = r.url
    out["title"] = _first(r"<title[^>]*>(.*?)</title>", html)
    out["meta_description"] = _attr(
        r'<meta[^>]+name=["\']description["\'][^>]*>', r'content=["\'](.*?)["\']', html)
    out["canonical"] = _attr(
        r'<link[^>]+rel=["\']canonical["\'][^>]*>', r'href=["\'](.*?)["\']', html)
    h1s = re.findall(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    out["h1"] = [_strip(h) for h in h1s]
    out["h2_count"] = len(re.findall(r"(?i)<h2[^>]*>", html))
    out["jsonld"] = _extract_jsonld(html)
    out["schema_types"] = sorted({t for b in out["jsonld"] for t in _types(b)})
    out["has_faq_schema"] = "FAQPage" in out["schema_types"]
    return out


def _extract_jsonld(html):
    blocks = []
    for m in re.finditer(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html
    ):
        raw = m.group(1).strip()
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            # tolerate trailing commas / multiple objects
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
            try:
                blocks.append(json.loads(cleaned))
            except json.JSONDecodeError:
                blocks.append({"_unparseable": raw[:400]})
    return blocks


def _types(block):
    found = []
    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            if isinstance(t, str):
                found.append(t)
            elif isinstance(t, list):
                found.extend(x for x in t if isinstance(x, str))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(block)
    return found


def find_lodging_node(jsonld_blocks):
    """Return the first Hotel/LodgingBusiness node found, if any."""
    target = {"hotel", "lodgingbusiness", "resort", "bedandbreakfast", "motel"}
    hit = []
    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            ts = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if any(isinstance(x, str) and x.lower() in target for x in ts):
                hit.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for b in jsonld_blocks:
        walk(b)
    return hit[0] if hit else None


def _first(pat, s):
    m = re.search(pat, s, re.I | re.S)
    return _strip(m.group(1)) if m else None


def _attr(tag_pat, attr_pat, s):
    m = re.search(tag_pat, s, re.I)
    if not m:
        return None
    a = re.search(attr_pat, m.group(0), re.I)
    return _strip(a.group(1)) if a else None


def _strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


# -------------------------------------------------------------------- topics

def map_topics(urls):
    cover = {}
    for topic, signals in TOPIC_SIGNALS.items():
        hits = [u for u in urls
                if any(sig in urllib.parse.urlparse(u).path.lower() for sig in signals)]
        cover[topic] = {"page_found": bool(hits), "urls": hits[:6]}
    return cover


# --------------------------------------------------------------- orchestrator

def run_site_check(website, max_pages=12, progress=None):
    """Importable entry point used by the Streamlit app."""
    base = website if "//" in website else "https://" + website
    base = base.rstrip("/") + "/"

    if progress:
        progress("Checking robots.txt")
    robots = check_robots(base)

    if progress:
        progress("Reading sitemap")
    sitemap = check_sitemap(base, robots.get("sitemaps", []))

    topics = map_topics(sitemap["urls"]) if sitemap["urls"] else {}
    covered = [t for t, v in topics.items() if v["page_found"]]
    missing = [t for t, v in topics.items() if not v["page_found"]]

    to_check = [base]
    for t, v in topics.items():
        if v["urls"]:
            to_check.append(v["urls"][0])
    to_check = list(dict.fromkeys(to_check))[:max_pages]

    pages = []
    for i, u in enumerate(to_check, 1):
        if progress:
            progress(f"Reading page {i}/{len(to_check)}")
        pages.append(analyse_page(u))
        time.sleep(0.4)

    all_jsonld = [b for p_ in pages for b in (p_.get("jsonld") or [])]
    lodging = find_lodging_node(all_jsonld)
    lodging_props = {}
    if lodging:
        for prop in LODGING_PROPS:
            lodging_props[prop] = prop in lodging and bool(lodging[prop])
    all_types = sorted({t for p_ in pages for t in (p_.get("schema_types") or [])})

    blocked_ai = [a for a, r in robots.get("ai_agent_rules", {}).items()
                  if r.get("blocked_entirely")]

    return {
        "meta": {"website": website, "base": base,
                 "pages_analysed": len([p_ for p_ in pages if p_.get("ok")])},
        "robots": robots,
        "ai_crawlers_blocked": blocked_ai,
        "sitemap": {k: v for k, v in sitemap.items() if k != "urls"},
        "sitemap_urls": sitemap["urls"][:500],
        "topic_coverage": topics,
        "topics_covered": covered,
        "topics_no_page_found": missing,
        "schema_types_found": all_types,
        "lodging_node_found": bool(lodging),
        "lodging_properties_present": lodging_props,
        "lodging_node": lodging,
        "pages": pages,
    }


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--website", required=True)
    p.add_argument("--out", default="site_check.json")
    p.add_argument("--max-pages", type=int, default=12)
    a = p.parse_args()

    base = a.website if "//" in a.website else "https://" + a.website
    base = base.rstrip("/") + "/"
    print(f"Base: {base}")

    robots = check_robots(base)
    print(f"robots.txt: present={robots['present']} blocks_all={robots['blocks_all']}")
    if robots["ai_agent_rules"]:
        for ag, r in robots["ai_agent_rules"].items():
            print(f"  {ag}: blocked_entirely={r['blocked_entirely']}")

    sitemap = check_sitemap(base, robots.get("sitemaps", []))
    print(f"sitemap: present={sitemap['present']} urls={sitemap['url_count']}")

    topics = map_topics(sitemap["urls"]) if sitemap["urls"] else {}
    covered = [t for t, v in topics.items() if v["page_found"]]
    missing = [t for t, v in topics.items() if not v["page_found"]]
    if topics:
        print(f"topic pages found: {len(covered)}/{len(topics)}")
        print(f"  no obvious page for: {', '.join(missing) or 'none'}")

    # analyse the homepage plus a sample of topic pages
    to_check = [base]
    for t, v in topics.items():
        if v["urls"]:
            to_check.append(v["urls"][0])
    to_check = list(dict.fromkeys(to_check))[: a.max_pages]

    pages = []
    for u in to_check:
        print(f"  reading {u}")
        pages.append(analyse_page(u))
        time.sleep(0.6)

    all_jsonld = [b for p_ in pages for b in (p_.get("jsonld") or [])]
    lodging = find_lodging_node(all_jsonld)
    lodging_props = {}
    if lodging:
        for prop in LODGING_PROPS:
            lodging_props[prop] = prop in lodging and bool(lodging[prop])

    all_types = sorted({t for p_ in pages for t in (p_.get("schema_types") or [])})

    payload = {
        "meta": {"website": a.website, "base": base,
                 "pages_analysed": len([p_ for p_ in pages if p_.get("ok")])},
        "robots": robots,
        "sitemap": {k: v for k, v in sitemap.items() if k != "urls"},
        "topic_coverage": topics,
        "topics_covered": covered,
        "topics_no_page_found": missing,
        "schema_types_found": all_types,
        "lodging_node_found": bool(lodging),
        "lodging_properties_present": lodging_props,
        "lodging_node": lodging,
        "pages": pages,
    }
    with open(a.out, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\nschema types found: {', '.join(all_types) or 'NONE'}")
    print(f"Hotel/LodgingBusiness node: {'yes' if lodging else 'NO'}")
    if lodging_props:
        absent = [k for k, v in lodging_props.items() if not v]
        print(f"  populated: {sum(lodging_props.values())}/{len(lodging_props)}")
        print(f"  absent: {', '.join(absent)}")
    print(f"\nWritten: {a.out}")


if __name__ == "__main__":
    sys.exit(main())
