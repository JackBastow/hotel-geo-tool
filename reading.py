"""
How much of the hotel's website is read, in one place, so every stage uses the same limits (page selection, the guest questions, the fact profile, the AI reading).

Adaptive: the most useful pages first (FIRST_BATCH), the fact profile built from them, then more pages read ONLY for what is still unverified (a facility the pages mention but the
profile did not confirm, a guest question not answered), up to LIMIT pages in all. Every page on the hotel's site that was considered is logged: read, failed (why), or not read
(lower priority, or not needed because the facts were already verified).

Discovery: the sitemap and the start page's links; when they give few of the hotel's own pages, Firecrawl's map of the site (one credit), restricted to the hotel's own section of a brand
website (urlscope), never the rest of marriott.com.
"""

import os
import re
import urllib.parse

LIMIT = int(os.environ.get("READ_LIMIT") or 40)           # the most pages any check reads
FIRST_BATCH = int(os.environ.get("READ_FIRST") or 20)     # read first, before the profile says what is still missing
STANDARD = 25                                              # the old fixed read, kept for the A/B comparison ('standard' reading)
PROFILE_CHARS = 200000                                     # what the fact profile may send in all (~50,000 tokens, about $0.10 on Sonnet)
PAGE_CHARS = 12000
FEW_PAGES = 15                                             # fewer in-scope pages than this from the sitemap and links: ask Firecrawl for the site's map

# what to look for, per unverified topic: words in a page's address or title
TOPIC_PAGES = {
    "parking": r"park|getting-?here|directions|location|find-?us|travel|arriv|faq|contact|car",
    "breakfast": r"breakfast|dining|restaurant|food|eat|menu",
    "checkin_out": r"faq|polic|terms|info|guest-?info|need-?to-?know|check",
    "cancellation": r"terms|polic|condition|cancel|booking|faq",
    "pets": r"dog|pet|faq|polic",
    "accessibility": r"access|disab|faq|polic",
    "family": r"famil|kid|child|faq",
    "transport": r"getting-?here|directions|location|find-?us|travel|contact|arriv",
    "wifi": r"faq|facilit|amenit|room",
    "ev": r"park|ev-?charg|electric|faq|facilit|getting-?here",
    "restaurant": r"dining|restaurant|eat|food|menu|bar",
    "bar": r"bar|lounge|drink|dining",
    "spa": r"spa|wellness|treatment|relax",
    "pool": r"pool|spa|leisure|facilit|wellness",
    "gym": r"gym|fitness|leisure|facilit|wellness",
    "meeting_rooms": r"meeting|event|conference|business|venue",
    "weddings": r"wedding|celebrat|event",
    "room_service": r"room|dining|faq|in-?room",
}


def unverified(guest, profile, features=None):
    """
    What is still not verified after the first read: guest questions not answered, and facilities the word rules find on the pages but the profile did not confirm.
    -> [topic], most important first.
    """
    out = []
    for q in (guest or {}).get("questions") or []:
        if q.get("state") in ("not_found", "couldnt_check", "partial") and q.get("id") in TOPIC_PAGES:
            out.append(q["id"])
    facs = (profile or {}).get("facilities") or {}
    for f in features or []:
        if f.get("key") in TOPIC_PAGES and f["key"] not in facs and f.get("pages", 0) >= 1:
            out.append(f["key"])                   # mentioned on the pages, not confirmed either way
    seen = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def follow_up(candidates, read_urls, topics, room):
    """
    The next pages to read for the unverified topics: unread candidates whose address or title fits a topic, the topics' best pages first, at most `room`.
    candidates: [{"url", "title"}] in priority order. -> ([url], {url: [topics it is read for]})
    """
    done = {u.rstrip("/").lower() for u in read_urls}
    picked, why = [], {}
    for t in topics:
        rx = re.compile(TOPIC_PAGES[t], re.I)
        for c in candidates:
            u = c["url"]
            if u.rstrip("/").lower() in done or len(picked) >= room:
                continue
            path = urllib.parse.urlparse(u).path
            if rx.search(path) or rx.search(c.get("title") or ""):
                if u not in picked:
                    picked.append(u)
                why.setdefault(u, []).append(t)
                break                              # one page per topic per round: the most likely one
    return picked, why


def firecrawl_map(start_url, api_key, *, post=None, limit=200, timeout=40):
    """The site's pages as Firecrawl maps them (one credit). -> [{"url", "title"}] or [] on any failure."""
    import requests
    post = post or requests.post
    for api in ("https://api.firecrawl.dev/v2/map", "https://api.firecrawl.dev/v1/map"):
        try:
            r = post(api, json={"url": start_url, "limit": limit, "includeSubdomains": False}, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
            if r.status_code != 200:
                continue
            d = r.json()
            links = d.get("links") or (d.get("data") or {}).get("links") or []
            out = []
            for x in links:
                if isinstance(x, str):
                    out.append({"url": x, "title": ""})
                elif isinstance(x, dict) and x.get("url"):
                    out.append({"url": x["url"], "title": x.get("title") or ""})
            if out:
                return out
        except Exception:  # noqa: BLE001 - discovery is an extra; the sitemap and links stand
            continue
    return []


def ledger(pages, candidates, followed=None):
    """Every page of the hotel's site that was considered: read, failed (why), or not read (and why). -> [{"url", "status", "why"}]"""
    out, seen = [], set()
    for p in pages or []:
        u = p.get("url") or ""
        seen.add(u.rstrip("/").lower())
        if p.get("ok"):
            out.append({"url": u, "status": "read", "why": ("follow-up for " + ", ".join((followed or {}).get(u, []))) if (followed or {}).get(u) else ""})
        elif p.get("replaced"):
            out.append({"url": u, "status": "failed", "why": (p.get("reason") or "") + " (replaced by another page)"})
        else:
            out.append({"url": u, "status": "failed", "why": p.get("reason") or "could not be read"})
    for c in candidates or []:
        u = c["url"] if isinstance(c, dict) else c
        if u.rstrip("/").lower() not in seen:
            seen.add(u.rstrip("/").lower())
            out.append({"url": u, "status": "not read", "why": "lower priority; the facts it might hold were already verified or the page limit was reached"})
    return out
