"""
A second fallback reader for a hotel's OWN pages, using Firecrawl (https://www.firecrawl.dev) when FIRECRAWL_API_KEY is set on the host.

When the hotel's site refuses this tool's own reader (a chain's bot protection, say) the audit tries, in order: this reader, then Anthropic's page reader. Firecrawl returns clean text (markdown) and the page's links,
so the audit keeps working on pages that would otherwise stay unread, and it costs no Claude credit. The same rules as the other fallback reader apply:
  * only the hotel's own website, only inside the hotel's own folder (urlscope), and only when our own reader got fewer than three pages;
  * only where the site's robots.txt allows it: if it asks automated readers to keep out, this reader is not used, and the report says the pages stay unread;
  * the standard (not the 'stealth') proxy mode is requested: nothing here tries to disguise the request or get round a block;
  * pages come back as text only, so markup, titles, canonical tags and image text are NOT assessed from them, and the report says the pages were read through Firecrawl;
  * a call per page against a monthly cap (store.SERVICE_CAPS['firecrawl']) kept under the free allowance; at most MAX_PAGES pages.
No key -> 'not configured'. It never raises.
"""

import os
import urllib.parse

import requests

import claude_reader
import guest_questions
import lexicon
import polite

SOURCE = "Firecrawl page reader"
API = ["https://api.firecrawl.dev/v2/scrape", "https://api.firecrawl.dev/v1/scrape"]
MAX_PAGES = 12
ACCESS = ("Firecrawl, used only when the hotel's site refuses this tool's own reader and its robots.txt allows automated reading. It returns the page's text and links; markup and other technical details are not assessed. "
          "Uses the operator's Firecrawl allowance (1 credit a page).")


def has_key(api_key=None):
    return bool(api_key or os.environ.get("FIRECRAWL_API_KEY"))


def scrape(url, api_key, post=requests.post, timeout=45):
    """One page -> {"ok", "markdown", "links", "title", "reason"}. Tries the current API, then the older one."""
    last = ""
    for ep in API:
        try:
            r = post(ep, json={"url": url, "formats": ["markdown", "links"], "onlyMainContent": False, "proxy": "basic"}, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}"
            continue
        if r.status_code == 404:
            last = "endpoint not found"
            continue
        if r.status_code != 200:
            return {"ok": False, "markdown": "", "links": [], "title": "", "reason": f"HTTP {r.status_code}"}
        try:
            data = (r.json() or {}).get("data") or {}
        except ValueError:
            return {"ok": False, "markdown": "", "links": [], "title": "", "reason": "unreadable reply"}
        md = data.get("markdown") or ""
        return {"ok": bool(md.strip()), "markdown": md, "links": [l if isinstance(l, str) else (l or {}).get("url", "") for l in data.get("links") or []], "title": (data.get("metadata") or {}).get("title", ""), "reason": "" if md.strip() else "empty page"}
    return {"ok": False, "markdown": "", "links": [], "title": "", "reason": last or "no answer"}


def read_hotel_pages(start_url, *, api_key=None, max_pages=MAX_PAGES, progress=None, post=requests.post, robots_ok=None):
    """-> {"status": ok|unavailable|not_configured|refused, "reason", "pages", "cost_usd", "credits"} in the same shape as claude_reader.read_hotel_pages. Never raises."""
    def out(status, reason="", pages=None, credits=0):
        return {"source": SOURCE, "status": status, "reason": reason, "access": ACCESS, "pages": pages or [], "cost_usd": 0.0, "credits": credits, "model": None}
    key = api_key or os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return out("not_configured", "No Firecrawl key is configured, so this reader was not used.")
    say = progress or (lambda m: None)
    allowed = polite.allowed(start_url) if robots_ok is None else robots_ok
    if not allowed:
        return out("refused", "The site's robots.txt asks automated readers to keep out, so no alternative reader was used.")
    try:
        say("The site refused our reader, so trying Firecrawl...")
        first = scrape(start_url, key, post=post)
        credits = 1
        if not first["ok"]:
            return out("unavailable", f"Firecrawl could not read the page either ({first['reason']}), so the site stays unread.", [], credits)
        home = claude_reader.to_page(start_url, first["markdown"], first["title"])
        home["links"] = (first["links"] or home["links"])[:150]
        pages = [home]
        targets = [u for u in guest_questions.select_pages(start_url, home["links"], [], max_pages=max_pages + 3)
                   if u.rstrip("/") != start_url.rstrip("/") and not lexicon.LEGAL_PAGE.search(urllib.parse.urlparse(u).path) and not lexicon.BOOKING_PAGE.search(urllib.parse.urlparse(u).path)]
        if targets:
            say(f"Reading {len(targets)} more of the hotel's pages...")
        for u in targets[: max_pages - 1]:
            if not polite.allowed(u) if robots_ok is None else not robots_ok:
                continue
            res = scrape(u, key, post=post)
            credits += 1
            if res["ok"]:
                pg = claude_reader.to_page(u, res["markdown"], res["title"])
                pg["links"] = (res["links"] or pg["links"])[:150]
                pages.append(pg)
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return out("unavailable", f"Firecrawl did not answer ({type(e).__name__}).", [], 0)
    return out("ok", "", pages, credits)
