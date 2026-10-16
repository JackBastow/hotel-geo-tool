"""
Booking readiness: if a traveller is persuaded by what an assistant says, can they get from the hotel's website to a booking?

Lightweight on purpose. From the homepage as it was read, and a few polite requests (at most two booking destinations and eight of the site's own links, in parallel, with the audit's honest
user agent and the site's robots.txt respected), it checks:
  * is a booking link or booking engine identifiable on the homepage, and how is it labelled
  * is it linked from other pages too (not only from one place)
  * does the booking destination answer (without trying to read rooms, prices or availability, which are not touched)
  * do the site's own links lead to pages that exist

A destination that refuses automated visitors (HTTP 403/429, a bot check) is reported as not verified, never as broken. Only a clear 404, 410 or server error counts as broken.
"""

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

import identity
import netguard
import polite

BOOK_ANCHOR = re.compile(r"\b(?:book(?:ing)?(?:\s+(?:now|direct|online|a (?:room|stay|table)|your (?:stay|room)))?|reserve(?:\s+now)?|reservations?|check (?:availability|rates|prices)|availability|stay with us|book a stay)\b", re.I)
BOOK_PATH = re.compile(r"/(?:book|booking|bookings|reserve|reservations?|availability|rooms?/book|stay/book)(?:/|$|\?|-)", re.I)
ROOMS_ONLY = re.compile(r"^\s*(?:rooms?|suites?|accommodation|stay)\s*$", re.I)
SKIP_LINK = re.compile(r"^(?:mailto:|tel:|javascript:|#)|\.(?:pdf|jpe?g|png|gif|webp|svg|css|js|zip|docx?)(?:$|\?)", re.I)
TABLE_ENGINES = ("opentable", "sevenrooms", "resdiary", "designmynight", "tablebooking", "bookatable", "quandoo")
MAX_DESTINATIONS, MAX_LINKS, TIMEOUT_S = 2, 4, 6        # a slow site answers one request at a time, so every extra request costs seconds


def _host(u):
    h = urllib.parse.urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _same_site(u, base):
    a, b = _host(u), _host(base)
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def candidates(home_links, base):
    """Booking links on the homepage: [{url, anchor, kind, engine, room_booking}], best first. A table-booking link is kept apart from a room booking link."""
    seen, out = set(), []
    for lk in home_links or []:
        url, anchor = (lk.get("url") or "").strip(), re.sub(r"\s+", " ", lk.get("anchor") or "").strip()
        if not url or SKIP_LINK.search(url):
            continue
        low = (_host(url) + urllib.parse.urlparse(url).path).lower()
        engine = next((label for tok, label in identity.BOOKING_ENGINES.items() if tok in low and not _same_site_engine_false_positive(tok, url, base)), "")
        by_anchor = bool(BOOK_ANCHOR.search(anchor)) and not ROOMS_ONLY.match(anchor)
        by_path = bool(BOOK_PATH.search(urllib.parse.urlparse(url).path))
        if not (engine or by_anchor or by_path):
            continue
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        table = any(t in low for t in TABLE_ENGINES) or bool(re.search(r"\btable|restaurant|dining|afternoon tea|spa|treatment", anchor + " " + url, re.I))
        pu = urllib.parse.urlparse(url)
        widget = _same_site(url, base) and bool(pu.fragment) and pu.path.rstrip("/") == urllib.parse.urlparse(base).path.rstrip("/")      # '#book' on the homepage itself: a booking panel, not a destination
        out.append({"url": url, "anchor": anchor[:60], "kind": ("booking panel on the homepage" if widget else "booking engine" if engine and not _same_site(url, base) else "booking page on the hotel's own site" if _same_site(url, base) else "external booking link"),
                    "engine": engine, "room_booking": not table, "widget": widget})
    out.sort(key=lambda c: (not c["room_booking"], c["widget"], not (BOOK_ANCHOR.search(c["anchor"]) is not None), c["kind"] == "external booking link"))
    return out


def _same_site_engine_false_positive(tok, url, base):
    """'book.' or 'booking.' as a token matches the hotel's own 'booking.' pages as well as engines; the generic subdomain tokens only count when the link is on another host."""
    return tok in ("book.", "booking.", "reservations.") and _same_site(url, base)


def probe(url, timeout=TIMEOUT_S):
    """One polite look at a URL: {'status': int|None, 'final': url, 'state': ok|broken|refused|unreachable|robots}. Nothing on the page is read."""
    try:
        if not polite.allowed(url):
            return {"status": None, "final": url, "state": "robots"}
        r = netguard.get(url, headers={"User-Agent": polite.UA}, timeout=timeout, stream=True)      # status and headers only: the body is never downloaded
        r.close()
    except requests.RequestException:
        return {"status": None, "final": url, "state": "unreachable"}
    except Exception:  # noqa: BLE001 - a blocked or odd address is simply not checked
        return {"status": None, "final": url, "state": "unreachable"}
    code = r.status_code
    state = "ok" if code < 400 else "refused" if code in (401, 403, 406, 429, 451, 999) else "broken" if code in (404, 410) or code >= 500 else "unreachable"
    return {"status": code, "final": getattr(r, "url", url), "state": state}


def run(base, home_links, pages, pages_meta=None, fetch=probe):
    """-> the booking-readiness section. `home_links` is [{url, anchor}] from the homepage as read; `pages` the pages read (with their 'links'); `pages_meta` the crawl's row per page."""
    out = {"status": "ok", "candidates": [], "destinations": [], "broken_links": [], "links_checked": 0, "checks": [], "limits": [
        "Rooms, prices and availability were not looked at: only whether a booking link exists, whether its destination answers and whether the site's own links lead somewhere."]}
    if not home_links:
        return {**out, "status": "unavailable", "reason": "The homepage links could not be read, so the booking route was not checked."}
    cands = candidates(home_links, base)
    out["candidates"] = cands[:6]
    rooms = [c for c in cands if c["room_booking"]]
    primary = next((c for c in rooms if not c["widget"]), rooms[0] if rooms else None)        # a real destination is checked; a '#book' panel on the homepage only counts as a booking control
    # --- is a booking route identifiable, and how prominent is it
    linked_from = sum(1 for p in pages or [] if primary and any(l.split("#")[0] == primary["url"].split("#")[0] for l in p.get("links", [])))
    if primary:
        panel = next((c for c in rooms if c["widget"]), None)
        out["checks"].append({"id": "link", "label": "A booking link on the homepage", "state": "pass",
                              "detail": f"'{primary['anchor'] or 'booking link'}' on the homepage leads to {primary['engine'] or _host(primary['url'])} ({primary['kind']})."
                              + (f" A '{panel['anchor']}' control on the homepage itself opens a booking panel." if panel and panel is not primary else ""), "url": primary["url"]})
        n_pages = len(pages or [])
        out["checks"].append({"id": "prominence", "label": "The booking route is linked from several pages", "state": "pass" if linked_from >= max(2, n_pages // 3) else "warn",
                              "detail": f"Linked from {linked_from} of the {n_pages} pages read." + ("" if linked_from >= max(2, n_pages // 3) else " A guest on a page without the link has to go back to the homepage to book."), "url": primary["url"]})
    else:
        tel = any(str(l.get("url", "")).lower().startswith("tel:") for l in home_links)
        out["checks"].append({"id": "link", "label": "A booking link on the homepage", "state": "fail",
                              "detail": "No room-booking link or booking engine could be identified among the homepage's links" + (", only a telephone number" if tel else "") + ". It may be added by a script after the page loads, which this check cannot see.", "url": base})
    # --- does the destination answer (at most two, in parallel, with the site's own links below)
    dests = list({c["url"].split("#")[0]: c for c in cands if not c["widget"]}.values())[:MAX_DESTINATIONS]
    known = {}
    for m in pages_meta or []:
        if m.get("url") and m.get("status"):
            known[m["url"].split("#")[0].rstrip("/")] = m["status"]
    internal = []
    seen_i = set()
    for lk in home_links:
        u = (lk.get("url") or "").split("#")[0]
        if not u or SKIP_LINK.search(u) or not _same_site(u, base) or u.rstrip("/") in seen_i or u.rstrip("/") == base.rstrip("/") or u.rstrip("/") in known:
            continue
        seen_i.add(u.rstrip("/"))
        internal.append(u)
    internal = internal[:MAX_LINKS]
    with ThreadPoolExecutor(max_workers=6) as ex:           # one round: destinations and links together
        res = list(ex.map(fetch, [d["url"] for d in dests] + internal))
    dres, ires = res[:len(dests)], res[len(dests):]
    for d, r in zip(dests, dres):
        out["destinations"].append({**d, **r})
    if primary:
        r = next((x for x in out["destinations"] if x["url"] == primary["url"]), None)
        if r:
            st = {"ok": ("pass", "The booking destination answers (HTTP %s)." % r["status"]), "broken": ("fail", f"The booking destination returned HTTP {r['status']}: it appears to be broken."),
                  "refused": ("not_verified", f"The booking destination refused this automated check (HTTP {r['status']}). That is normal for booking engines and does not mean it is broken."),
                  "robots": ("not_verified", "The booking destination's robots.txt asks automated visitors to stay out, so it was not requested."),
                  "unreachable": ("not_verified", "The booking destination could not be reached from here, so it was not verified.")}[r["state"]]
            out["checks"].append({"id": "destination", "label": "The booking destination answers", "state": st[0], "detail": st[1], "url": primary["url"]})
    # --- the site's own links: those the crawl already fetched, and a few more from the homepage
    broken = [{"url": m["url"], "status": m.get("status"), "found_on": base} for m in pages_meta or [] if m.get("status") in (404, 410) or (m.get("status") or 0) >= 500]
    broken += [{"url": u, "status": r["status"], "found_on": base} for u, r in zip(internal, ires) if r["state"] == "broken"]
    out["links_checked"] = len(internal) + len([m for m in pages_meta or [] if m.get("status")])
    out["broken_links"] = broken[:10]
    out["checks"].append({"id": "links", "label": "The site's own links lead to pages that exist", "state": "fail" if broken else "pass",
                          "detail": (f"{len(broken)} of the {out['links_checked']} links checked returned 'not found' or a server error: " + ", ".join(urllib.parse.urlparse(b["url"]).path or "/" for b in broken[:4]) + ".")
                          if broken else f"None of the {out['links_checked']} links checked was broken.", "url": broken[0]["url"] if broken else base})
    return out
