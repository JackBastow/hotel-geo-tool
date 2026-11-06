"""
A second fallback reader for a hotel's OWN pages, using Firecrawl (https://www.firecrawl.dev) when FIRECRAWL_API_KEY is set on the host.

When the hotel's site refuses this tool's own reader (a chain's bot protection, say) the audit tries, in order: this reader, then Anthropic's page reader. Firecrawl returns clean text (markdown) and the page's links,
so the audit keeps working on pages that would otherwise stay unread, and it costs no Claude credit. The same rules as the other fallback reader apply:
  * only the hotel's own website, only inside the hotel's own folder (urlscope), and only when our own reader got fewer than three pages;
  * only where the site's robots.txt allows it: if it asks automated readers to keep out, this reader is not used, and the report says the pages stay unread;
  * the standard (not the 'stealth') proxy mode is requested: nothing here tries to disguise the request or get round a block;
  * the page's HTML is requested too and parsed like any page this tool fetched, so titles, headings, markup and structured data can be checked; what depends on how OUR reader is treated (the sitemap, robots.txt,
    error codes, speed, script-built content) is still not judged, and the report says the pages were read through Firecrawl; a page whose HTML has too little text falls back to its markdown, text only;
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
            r = post(ep, json={"url": url, "formats": ["markdown", "rawHtml", "links"], "onlyMainContent": False, "proxy": "basic"}, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=timeout)
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
        html = data.get("rawHtml") or data.get("html") or ""
        return {"ok": bool(md.strip() or html.strip()), "markdown": md, "html": html, "links": [l if isinstance(l, str) else (l or {}).get("url", "") for l in data.get("links") or []], "title": (data.get("metadata") or {}).get("title", ""), "reason": "" if (md.strip() or html.strip()) else "empty page"}
    return {"ok": False, "markdown": "", "html": "", "links": [], "title": "", "reason": last or "no answer"}


def build_page(url, res):
    """
    One scraped page -> the page dict the audit uses. With the page's HTML it is parsed exactly as a page this tool fetched itself (title, headings, markup, structured data, images, canonical), so the
    technical checks can run on it; if the HTML has too little text (a script-built page) the markdown is used and the page stays text-only. Pages built from HTML carry html_via='firecrawl'.
    """
    import guest_questions
    html = res.get("html") or ""
    if html.strip():
        try:
            parsed = guest_questions._parse_html(url, html)
        except Exception:  # noqa: BLE001
            parsed = None
        if parsed and parsed.get("signals") and len(parsed.get("text") or "") >= guest_questions.MIN_READABLE_CHARS:
            parsed["links"] = list(dict.fromkeys(parsed["links"] + [l for l in res.get("links") or [] if l]))[:150]
            parsed.update(url=url, ok=True, reason="", status=200, final_url=url, text_only=False, html_via="firecrawl")
            return parsed
    pg = claude_reader.to_page(url, res.get("markdown") or "", res.get("title") or "")
    pg["links"] = ([l for l in res.get("links") or [] if l] or pg["links"])[:150]
    return pg


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
        home = build_page(start_url, first)
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
                pages.append(build_page(u, res))
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return out("unavailable", f"Firecrawl did not answer ({type(e).__name__}).", [], 0)
    return out("ok", "", pages, credits)


REFUSED = (401, 403, 429, 451)


def fallback_fetch(base_fetch, api_key, limit=8, post=requests.post, robots_ok=None):
    """
    Wraps a page fetcher (guest_questions.fetch_page) for OTHER sites the audit reads: rival hotels' sites, pages that AI answers cited. When our own reader is refused (401/403/429/451) and the site's robots.txt allows
    automated reading, the same page is read through Firecrawl instead, up to `limit` pages an audit. Nothing is hidden: no stealth proxy, and a refusal that Firecrawl cannot read either stays a refusal.
    The returned function has .credits (pages read through Firecrawl) and .used (their addresses).
    """
    state = {"credits": 0, "used": []}

    def fetch(url):
        pg = base_fetch(url)
        if not api_key or (pg or {}).get("ok") or (pg or {}).get("status") not in REFUSED or state["credits"] >= limit:
            return pg
        try:
            if not (polite.allowed(url) if robots_ok is None else robots_ok):
                return pg
            state["credits"] += 1
            res = scrape(url, api_key, post=post)
            if not res["ok"]:
                return pg
            new = build_page(url, res)
            if new.get("ok"):
                state["used"].append(url)
                return new
        except Exception:  # noqa: BLE001
            pass
        return pg

    fetch.state = state
    return fetch
