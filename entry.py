"""
Finding the page the audit starts from, and saying exactly how.

What the visitor pastes is a real address that works in a browser. An earlier version cut it down to a folder ('https://all.accor.com/hotel/1168/index.en.shtml' became '/hotel/1168/'), which that site
answers with 404, and then reported the hotel's own page as broken and read nothing. This module never does that:

  1. The address as pasted is requested first, exactly (only tracking parameters such as utm_*, fbclid and msockid and the #fragment are removed: they never change the page).
  2. Only if that fails are other forms of the same address tried, in a fixed order, and every request is logged with its answer.
  3. If none works, pages the site itself lists in its own sitemap, inside the hotel's own folder, are tried. A page is used only if it answers 200 with readable HTML, on the same website.
  4. If nothing can be read, the log says so and the report says the audit could not read the page: that is a limit of this audit, never a fault of the hotel.

resolve(text, sitemap_urls=(), fetch=site_check.get) -> {"entry_url", "home_url", "ok", "via", "note", "log": [{"url", "status", "final_url", "bytes", "ms", "why"}]}
"""

import re
import time
import urllib.parse

import urlscope

MIN_HTML_CHARS = 200
MAX_ALTERNATIVES = 3


def _row(url, r, ms, why):
    if r is None:
        return {"url": url, "status": None, "final_url": url, "bytes": 0, "ms": ms, "why": why, "result": "no answer (connection failed or timed out)"}
    return {"url": url, "status": r.status_code, "final_url": getattr(r, "url", url) or url, "bytes": len(getattr(r, "content", b"") or b""), "ms": ms, "why": why,
            "result": "ok" if r.status_code == 200 else f"HTTP {r.status_code}"}


def _usable(r):
    """A 200 answer that is an HTML page with some text in it (a JavaScript shell can still be read in other ways later, so only an empty body is refused)."""
    if r is None or r.status_code != 200:
        return False
    ct = (r.headers.get("Content-Type", "") or "").lower()
    return ("html" in ct or not ct) and len(r.text or "") >= MIN_HTML_CHARS


def _alternatives(sitemap_urls, scope, host):
    """The hotel's own pages that its sitemap lists, home-like first: the folder itself or its index file, then the shortest addresses."""
    out, seen = [], set()
    for u in sitemap_urls or []:
        p = urllib.parse.urlparse(u)
        if p.scheme not in ("http", "https") or urlscope.bare_host(p.netloc) != host or not urlscope.in_scope(u, scope):
            continue
        key = urlscope.canon_index(p.path).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        rel = urlscope.canon_index(p.path)[len(scope or "/"):] if scope else urlscope.canon_index(p.path)
        homelike = 0 if not rel.strip("/") else 1
        out.append((homelike, len([s for s in rel.split("/") if s]), len(u), u))
    return [u for *_k, u in sorted(out)][:MAX_ALTERNATIVES]


def resolve(text, sitemap_urls=(), fetch=None):
    """Work out which page to start from. Never raises."""
    if fetch is None:
        import site_check
        fetch = site_check.get
    entry = urlscope.clean_entry(text)
    start, scope = urlscope.normalise(text)
    host = urlscope.bare_host(urllib.parse.urlparse(entry).netloc)
    out = {"entry_url": entry, "home_url": "", "ok": False, "via": "", "note": "", "log": [], "scope": scope}

    def attempt(url, why):
        t0 = time.time()
        try:
            r = fetch(url, timeout=20)
        except Exception:  # noqa: BLE001 - a bad address is a failed attempt, not a crash
            r = None
        out["log"].append(_row(url, r, int((time.time() - t0) * 1000), why))
        return r

    # 1-2: the address as pasted, then other forms of it. For a page inside a chain's website the pasted page comes first; for an ordinary site the front page does (people paste an inner page
    # meaning 'my website'), with the pasted page as the next try.
    forms = urlscope.address_forms(entry)
    if scope:
        order = [(entry, "the address exactly as submitted")] + [(u, w) for u, w in forms if u != entry]
    else:
        order = [(start, "the website's front page")] + [(entry, "the address exactly as submitted")] + [(u, w) for u, w in forms if u != entry]
    tried = set()
    for url, why in order:
        if url in tried:
            continue
        tried.add(url)
        r = attempt(url, why)
        if _usable(r):
            out.update(ok=True, home_url=getattr(r, "url", url) or url, via="submitted" if url == entry else "variant" if scope else "front page",
                       note="" if url == entry or not scope else f"The address as submitted did not answer; {why} did.")
            if out["home_url"].split("#")[0].rstrip("/") != url.split("#")[0].rstrip("/") and urlscope.bare_host(urllib.parse.urlparse(out["home_url"]).netloc) != host:
                out["note"] = (out["note"] + " " if out["note"] else "") + f"The site redirected to {urllib.parse.urlparse(out['home_url']).netloc}."
            return out

    # 3: pages the site itself lists in its own sitemap, inside the hotel's own folder
    for u in _alternatives(sitemap_urls, scope, host):
        if u in tried:
            continue
        tried.add(u)
        r = attempt(u, "a page the site's own sitemap lists for this hotel")
        if _usable(r):
            out.update(ok=True, home_url=getattr(r, "url", u) or u, via="alternative",
                       note=f"The address as submitted could not be read, so the audit used {u}, a page the site's own sitemap lists for this hotel and which answered normally.")
            return out

    # 4: nothing could be read
    codes = sorted({str(x["status"]) for x in out["log"] if x["status"]})
    out["note"] = ("No page for this hotel could be read by this audit (" + (", ".join(f"HTTP {c}" for c in codes) if codes else "no answer") + f" from {len(out['log'])} request(s)). "
                   "That describes what this tool's reader received, not the state of the hotel's website, so no 'broken page' is reported.")
    out["home_url"] = ""
    return out


# ------------------------------------------------------------------ is an error the hotel's?

SERVER_OR_GONE = (404, 410)


def is_error_status(status):
    return bool(status) and (status in SERVER_OR_GONE or status >= 500)


def credible_error(row, rows):
    """
    May a page that did not answer be reported to the hotel as broken? Only when this audit cannot reasonably be the cause:
      * it was not the page the audit started from (a failed start page says the audit could not read it, nothing more);
      * the audit did read the hotel's start page, so the site was reachable for it;
      * the answer was 404, 410 or a server error (never a refusal such as 403 or 429, which is bot protection);
      * the page was asked for again in another form of its address and still did not answer.
    Anything else is shown as 'not read by this audit', never as a fault to fix.
    """
    if row.get("ok") or row.get("is_start") or not is_error_status(row.get("status")) or not row.get("retested"):
        return False
    return any(r.get("is_start") and r.get("ok") for r in rows or [])


def retest(page, fetch, parse=None, limit=2):
    """
    Ask again for a page that answered 404, 410 or a server error, in other forms of its address (the other trailing slash, the folder of an index file, the other of www / no-www). If a form answers, the
    page is read from it. -> True when the page was recovered. The attempts are kept on the page as page['retest'] and page['retested'] is set either way.
    """
    page["retested"], page["retest"] = True, []
    for url, why in urlscope.address_forms(page["url"])[1:1 + limit + 1]:
        try:
            r = fetch(url, timeout=15)
        except Exception:  # noqa: BLE001
            r = None
        page["retest"].append({"url": url, "why": why, "status": getattr(r, "status_code", None)})
        if _usable(r):
            if parse:
                page.update(parse(url, r))
            return True
    return False
