"""
Lightweight competitive context: up to three comparable hotels found automatically, and where the audited hotel offers something but says less about it than they do.

No competitor details are asked for. Candidates come from OpenStreetMap hotels near the hotel (already fetched for the local context) that have a website. A candidate is kept only if it is COMPARABLE
on evidence, not merely close: a similar star rating or room count (from its map entry or its own homepage), and the same kinds of facility (spa, restaurant, meeting rooms, pool, weddings).
Their homepage and up to two pages about the facilities in question are read, politely (the site's robots.txt is respected, one short fetch each, in parallel, with a hard time limit).

A comparison is made ONLY when both sides were read: the audited hotel offers the facility, the other hotel's pages for it were read, and the other hotel states clearly more of what a traveller needs to
know about it. Anything else is left out. If map data is missing, no comparable hotel is found, or their sites cannot be read, the section says so and makes no claim: the hotel's own opportunity analysis
(traveller requirements, hidden strengths) stands without it.
"""

import math
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import evidence
import insight_content as ic
import lexicon

MAX_CANDIDATES, MAX_RIVALS, MAX_EXTRA_PAGES, DEADLINE_S = 6, 3, 2, 25
KEY_FACILITIES = ("spa", "restaurant", "meeting_rooms", "pool", "weddings")
_STARS = re.compile(r"\b([1-5])[- ]?star\b|\b([1-5])\*\s?(?:hotel|rated)|\b(?:aa|visit\w*)\s+([1-5])[- ]?stars?", re.I)
_ROOMS = re.compile(r"(?:(?:hotel|property|we)\s+(?:has|have|offers?|boasts?|features?)\s+(?:a total of\s+)?(\d{2,3})\s+(?:\w+\s+){0,2}(?:bedrooms|rooms|suites))|(?:\b(\d{2,3})[- ](?:bedroom|bedroomed|room)\s+(?:hotel|property))|(?:\b(\d{2,3})\s+(?:individually|beautifully|stylish|luxurious)?\s*(?:\w+\s+)?(?:bedrooms|guest rooms|suites)\b)", re.I)
TOPIC_SLUGS = {"spa_detail": ("spa", "wellness", "treatments"), "meeting_detail": ("meeting", "conference", "events", "business"), "pool_detail": ("pool", "spa", "leisure"),
               "restaurant_detail": ("restaurant", "dining", "eat", "menu"), "wedding_detail": ("wedding",), "connecting_rooms": ("family", "rooms", "accommodation")}
TOPIC_LABEL = {"spa_detail": "the spa", "meeting_detail": "meeting facilities", "pool_detail": "the pool", "restaurant_detail": "the restaurant", "wedding_detail": "weddings", "connecting_rooms": "family rooms"}
FEATURE_FOR = {"spa_detail": "spa", "meeting_detail": "meeting_rooms", "pool_detail": "pool", "restaurant_detail": "restaurant", "wedding_detail": "weddings", "connecting_rooms": "family"}


def _site_of(url):
    h = urllib.parse.urlparse(url if "//" in (url or "") else "https://" + (url or "")).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _stars(text):
    ms = [int(next(g for g in m.groups() if g)) for m in _STARS.finditer(text or "")]
    return max(set(ms), key=ms.count) if ms else None


def _rooms(text):
    for m in _ROOMS.finditer(text or ""):
        n = int(next(g for g in m.groups() if g))
        if 5 <= n <= 900:
            return n
    return None


def _features(site):
    return {f["key"]: f["level"] for f in ic.features(site)}


def profile(pages, base, hotel, osm_tags=None):
    """What can be said about a hotel from the pages read (and its map entry): stars, rooms, facilities. Each value is None when not stated."""
    site = ic.Site(pages, base, hotel, "")
    text = " ".join(p.get("text", "")[:6000] for p in site.content_pages[:6])
    feats = _features(site)
    tags = osm_tags or {}
    stars = _stars(text) or (int(float(tags["stars"])) if str(tags.get("stars", "")).replace(".", "", 1).isdigit() else None)
    rooms = _rooms(text) or (int(tags["rooms"]) if str(tags.get("rooms", "")).isdigit() else None)
    return {"site": site, "stars": stars, "rooms": rooms, "features": feats, "facilities": sorted(k for k in KEY_FACILITIES if feats.get(k) in ("some", "strong"))}


def comparable(own, rival):
    """-> (points, reasons). Needs at least one attribute (stars or rooms) agreeing, or three shared facilities; closeness on a map is not comparability."""
    pts, why = 0, []
    if own["stars"] and rival["stars"]:
        d = abs(own["stars"] - rival["stars"])
        if d == 0:
            pts += 2
            why.append(f"both {own['stars']}-star")
        elif d == 1:
            pts += 1
            why.append(f"{rival['stars']}-star against {own['stars']}-star")
    if own["rooms"] and rival["rooms"]:
        ratio = rival["rooms"] / own["rooms"]
        if 0.5 <= ratio <= 2:
            pts += 2
            why.append(f"{rival['rooms']} rooms against {own['rooms']}")
        elif 0.33 <= ratio <= 3:
            pts += 1
            why.append(f"{rival['rooms']} rooms against {own['rooms']}")
    shared = sorted(set(own["facilities"]) & set(rival["facilities"]))
    pts += min(len(shared), 3)
    if shared:
        why.append("both have " + ", ".join(k.replace("_", " ") for k in shared))
    attr = any(w for w in why if "star" in w or "rooms" in w)
    return (pts if (attr or len(shared) >= 3) and pts >= 3 else 0), why


def pick(osm_ctx, own_domain, own_brand=""):
    """Candidates from the map data: hotels with a website, not the hotel itself, not the same brand or site. -> [{name, url, km, tags}]"""
    out, seen = [], {own_domain}
    for h in (osm_ctx or {}).get("hotels", []):
        t = h.get("tags") or {}
        site = t.get("website")
        if not site or t.get("tourism") not in ("hotel", None) or not h.get("name"):
            continue
        d = _site_of(site)
        if not d or d in seen or (own_brand and evidence.fold(t.get("brand", "")) == evidence.fold(own_brand)):
            continue
        seen.add(d)
        out.append({"name": h["name"], "url": site if "//" in site else "https://" + site, "km": h["km"], "tags": t})
    return out[:MAX_CANDIDATES]


def _read(url, fetch):
    try:
        return fetch(url)
    except Exception:  # noqa: BLE001
        return None


def _links_for(page, base, slugs):
    out = []
    for l in page.get("links", []):
        path = urllib.parse.urlparse(l).path.lower()
        if _site_of(l) == _site_of(base) and any(s in path for s in slugs) and l not in out and not re.search(r"\.(?:pdf|jpe?g|png)$", path):
            out.append(l)
    return out


def read_rival(c, fetch, wanted_slugs):
    """The homepage plus up to two pages about the facilities in question. -> list of parsed pages that were read (ok)."""
    home = _read(c["url"], fetch)
    if not home or not home.get("ok"):
        return []
    pages = [home]
    for l in _links_for(home, c["url"], wanted_slugs)[:MAX_EXTRA_PAGES]:
        p = _read(l, fetch)
        if p and p.get("ok"):
            pages.append(p)
    return pages


def _depth(rule, site):
    present = ic._facts_present(site, rule["facts"])
    return len(present), present


def run(osm_ctx, own_pages, base, hotel, fetch=None, deadline_s=DEADLINE_S, polite_allowed=None):
    """
    -> {"status", "reason", "competitors": [...], "comparisons": [...], "limits": [...]}. Never raises. `fetch(url)` returns a parsed page (guest_questions.fetch_page); `polite_allowed(url)` is robots.txt.
    """
    base_out = {"status": "unavailable", "reason": "", "competitors": [], "comparisons": [], "limits": [
        "Competitors are found from OpenStreetMap hotels that have a website, so a rival without a map entry or a website is not considered. Comparisons use only the pages that were read, and only where both hotels were read."]}
    own_domain = _site_of(base)
    cands = pick(osm_ctx, own_domain)
    if not osm_ctx:
        return {**base_out, "reason": "Open map data was not available, so no comparable hotels could be found. No comparison is made."}
    if not cands:
        return {**base_out, "status": "none", "reason": "Open map data lists no other hotels with a website near this one, so no comparison is made."}
    if fetch is None:
        import guest_questions
        fetch = guest_questions.fetch_page
    if polite_allowed is None:
        import polite
        polite_allowed = polite.allowed
    own_site = ic.Site(own_pages, base, hotel, "")
    own = profile(own_pages, base, hotel)
    own_wanted = [k for k in own["facilities"]]
    slugs = sorted({s for rid, ss in TOPIC_SLUGS.items() if FEATURE_FOR[rid] in own_wanted or FEATURE_FOR[rid] == "family" and own["features"].get("family") in ("some", "strong") for s in ss})
    end = time.time() + deadline_s

    def one(c):
        if time.time() > end or not polite_allowed(c["url"]):
            return c, []
        return c, read_rival(c, fetch, slugs or ("spa", "meeting", "rooms"))
    with ThreadPoolExecutor(max_workers=4) as ex:
        read = list(ex.map(one, cands))
    scored = []
    for c, pages in read:
        if not pages:
            continue
        rp = profile(pages, c["url"], c["name"], c["tags"])
        pts, why = comparable(own, rp)
        if pts:
            scored.append((pts, -c["km"], c, pages, rp, why))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    rivals = scored[:MAX_RIVALS]
    unread = sum(1 for _c, p in read if not p)
    if not rivals:
        return {**base_out, "status": "none", "reason": f"{len(cands)} nearby hotel(s) with a website were found, but " + (f"{unread} could not be read and " if unread else "") + "none was comparable on evidence (a similar star rating or size, and similar facilities), so no comparison is made."}
    comps = []
    for rid_rule in ic.EXTENDED:
        rid = rid_rule["id"]
        if rid not in FEATURE_FOR:
            continue
        feat = FEATURE_FOR[rid]
        if own["features"].get(feat) not in ("some", "strong"):
            continue                                   # only facilities the audited hotel actually offers
        n_own, present_own = _depth(rid_rule, own_site)
        total = len(rid_rule["facts"])
        rows = []
        for _p, _k, c, pages, rp, _w in rivals:
            if rp["features"].get(feat) not in ("some", "strong"):
                continue                               # the other hotel was not seen to offer it: nothing to compare
            n_r, present_r = _depth(rid_rule, rp["site"])
            rows.append({"name": c["name"], "url": c["url"], "depth": n_r, "stated": sorted(present_r), "evidence": [{"url": v["url"], "snippet": v["snippet"]} for v in list(present_r.values())[:2]]})
        better = [r for r in rows if r["depth"] - n_own >= max(1, math.ceil(0.4 * total))]
        if not rows:
            continue
        missing_own = [k for k in rid_rule["facts"] if k not in present_own]
        stated_by = sorted({f for r in better for f in r["stated"] if f in missing_own})
        comps.append({"topic": rid, "label": TOPIC_LABEL[rid], "own_depth": n_own, "of": total, "own_stated": sorted(present_own), "rivals": rows, "behind": bool(better),
                      "statement": (f"Your hotel offers {TOPIC_LABEL[rid]}, but its pages state {n_own} of {total} things travellers look for ({', '.join(sorted(present_own)) or 'none'}), "
                                    f"while {', '.join(r['name'] for r in better[:2])} state{'s' if len(better) == 1 else ''} more of them, including {', '.join(stated_by[:3]) or 'details yours omits'}."
                                    if better else (f"Your hotel's pages state {n_own} of {total} things travellers look for about {TOPIC_LABEL[rid]}, as many as or more than the {len(rows)} comparable hotel(s) that offer it."
                                                      if n_own >= max(r["depth"] for r in rows) else
                                                      f"Your hotel's pages state {n_own} of {total} things travellers look for about {TOPIC_LABEL[rid]}, close to (a little fewer than) the {max(r['depth'] for r in rows)} the comparable hotel(s) state; not enough of a gap to call.")),
                      "missing": missing_own, "example": rid_rule["example"], "verified": True})
    return {"status": "ok", "reason": "", "competitors": [{"name": c["name"], "url": c["url"], "km": c["km"], "why_comparable": why, "pages_read": len(pages), "stars": rp["stars"], "rooms": rp["rooms"],
                                                           "facilities": rp["facilities"]} for _p, _k, c, pages, rp, why in rivals],
            "own": {"stars": own["stars"], "rooms": own["rooms"], "facilities": own["facilities"]}, "comparisons": comps, "limits": base_out["limits"]}
