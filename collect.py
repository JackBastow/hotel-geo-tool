"""
Evidence collection for the wider discovery & reputation report.

This module only GATHERS. It runs the free source adapters, runs a planned set
of searches, reads the pages worth reading (respecting robots.txt), and
decides for each page whether it is actually about THIS hotel. Interpretation
(themes, awards, targets, recommendations) happens in intel.py, from what this
returns.

Cost discipline: the search plan below is ~9-12 Tavily credits per audit
(free plan: 1,000/month). Every query has a stated purpose, and each result is
tagged with the role of the query that found it so the report can say how a
page was discovered.
"""

import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import evidence
import langid
import polite
import sourcetypes
import sources
import tavily_check

ROLE_PRIORITY = {"news_recent": 0, "news_events": 0, "features": 1, "awards": 1,
                 "destination": 2, "roundup": 3, "footprint": 4, "existing": 3}


def _town(city):
    return (city or "").split(",")[0].strip()


def canonical_url(url):
    p = urllib.parse.urlparse(url or "")
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "igsh", "_t", "_r"))]
    path = p.path.rstrip("/") or "/"
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return urllib.parse.urlunparse((p.scheme.lower() or "https", host, path, "",
                                    urllib.parse.urlencode(q), ""))


def search_plan(hotel, city, segments):
    """[(role, query, tavily_options)] - small, purposeful, and visible in the report."""
    t = _town(city) or city
    h = f'"{hotel}"'
    plan = [
        ("news_recent", f"{h} {t}", {"topic": "news", "time_range": "year"}),
        ("news_events", f"{h} {t} refurbishment OR opens OR launches OR appoints OR new",
         {"topic": "news", "time_range": "year"}),
        ("footprint", f"{h} {t}", {}),
        ("features", f'{h} {t} review OR "stay at" OR guide OR feature', {}),
        # Tavily's index returns a different slice of review pages from run to run,
        # so recall needs more than one phrasing of "someone wrote about a stay here".
        ("features", f'{h} {t} hotel review blog', {}),
        ("features", f'{h} "we stayed" OR "our stay" OR "a night at" OR "spa day"', {}),
        ("roundup", f'{h} {t} "best hotels" OR "where to stay" OR "top hotels"', {}),
        ("awards", f'{h} award OR winner OR rosette OR "gold list" OR accredited', {}),
        ("destination", f"{t} tourism board official visit where to stay", {}),
        ("roundup", f"best hotels in {t}", {}),
    ]
    seg_q = {"wedding venue": f"best wedding venues hotels near {t}",
             "spa/wellness hotel": f"best spa hotels near {t}",
             "family hotel": f"best family hotels near {t}",
             "business/conference hotel": f"best conference hotels near {t}",
             "pet-friendly hotel": f"best dog friendly hotels near {t}"}
    for s in (segments or [])[:2]:
        if s in seg_q:
            plan.append(("roundup", seg_q[s], {}))
    return plan


def _run_search(role, query, opts, key):
    try:
        data = tavily_check._search(query, api_key=key, max_results=10, **opts)
        return {"role": role, "query": query, "error": None, "credits": 1,
                "results": data.get("results") or []}
    except tavily_check.TavilyError as e:
        return {"role": role, "query": query, "error": str(e), "credits": 0, "results": []}


def _read_candidate(c, hotel, city, postcode, own_url):
    """Fetch + parse + match one candidate. Fills c['read'], c['page'], c['match']."""
    res = polite.read(c["url"])
    f, page = res["fetch"], res["page"]
    if not f["ok"]:
        c["read"] = {"status": "not_read", "why": f["error"] or "could not be fetched",
                     "robots_blocked": f["robots_blocked"]}
        return c
    text = page.get("text", "")
    m = evidence.match_hotel(text, hotel, city, postcode, own_url, links=page.get("links", []))
    windows, n_mentions = evidence.mention_windows(text, hotel)
    lang, conf = langid.detect(text)
    cues = {"sponsored_cue": page.get("sponsored_cue"),
            "press_release_cue": page.get("press_release_cue")}
    # classify on the search-result title AND the page's own title: pages often
    # carry a generic <title> ("Find everything you need for your wedding")
    # while the search index has the real headline.
    ptype = sourcetypes.classify_page(
        c["url"], f"{c.get('title') or ''} | {page.get('title') or ''}", text, cues, n_mentions)
    ptype["cue_text"] = page.get("sponsored_cue_text") or page.get("press_release_cue_text")
    pg = {"title": page.get("title") or c.get("title"), "publisher": page.get("publisher"),
          "author": page.get("author"), "published": page.get("published"),
          "modified": page.get("modified"), "canonical": page.get("canonical"),
          "lang": lang or (page.get("lang_attr") or "")[:2].lower() or None,
          "lang_source": "text" if lang else ("html lang attribute" if page.get("lang_attr") else None),
          "page_type": ptype, "mentions": n_mentions, "windows": windows,
          "text_len": len(text),
          "text_head": text[:600],
          "links_to_hotel": any(evidence.same_site(l, own_url) for l in page.get("links", []))
          if own_url else False}
    # Roundups: keep headed sections (each is usually one property) for comparison.
    if ptype["type"] in ("roundup", "destination_guide"):
        pg["sections"] = [{"heading": s["heading"], "text": s["text"][:350]}
                          for s in page.get("sections", [])[:40]]
    # page text fingerprint for syndication detection
    pg["fingerprint"] = re.sub(r"\W+", " ", text[:1500].lower()).strip()
    c["page"], c["match"] = pg, m
    c["read"] = {"status": "read", "why": "", "robots_blocked": False}
    return c


def collect(hotel, city, base_url, *, location=None, segments=None, tavily_key=None,
            youtube_key=None, existing_tavily=None, progress=None,
            read_budget_s=100, max_reads=30):
    say = progress or (lambda m: None)
    location = location or {}
    postcode = location.get("postcode") or ""
    lat, lon = location.get("lat"), location.get("lon")
    uk = bool(re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", postcode.upper())) \
        or "united kingdom" in (city or "").lower() or "england" in (city or "").lower()

    out = {"sources": {}, "queries": [], "candidates": [], "notes": [], "tavily_credits": 0,
           "raw_results": [],
           "reads": {"attempted": 0, "ok": 0, "robots_blocked": 0, "failed": 0,
                     "budget_hit": False}}

    # ---- 1. free adapters, in parallel (each is independent and polite)
    tasks = {
        "gdelt": lambda: sources.gdelt_search(hotel, city),
        "wikipedia": lambda: sources.wikipedia_mentions(hotel, city),
        "osm_context": lambda: sources.osm_context(lat, lon, hotel),
        "wayback": lambda: sources.wayback_titles(evidence.domain_of(base_url)),
        "fsa": lambda: sources.fsa_ratings(hotel, postcode, uk),
        "youtube": lambda: sources.youtube_search(hotel, city, youtube_key),
    }
    say("Checking GDELT, Wikipedia, OpenStreetMap, the Internet Archive and official registers...")
    adapter_ex = ThreadPoolExecutor(max_workers=4)
    adapter_futs = {adapter_ex.submit(fn): name for name, fn in tasks.items()}

    # ---- 2. planned searches
    pool = {}

    def add(url, title, snippet, published, role, via="tavily"):
        if not url:
            return
        key = canonical_url(url)
        if key in pool:
            if role not in pool[key]["roles"]:
                pool[key]["roles"].append(role)
            if published and not pool[key].get("published_search"):
                pool[key]["published_search"] = evidence.parse_date(published)
            return
        st, label = sourcetypes.classify_domain(url, base_url)
        pool[key] = {"url": url, "key": key, "title": (title or "")[:200],
                     "snippet": (snippet or "")[:400],
                     "published_search": evidence.parse_date(published),
                     "roles": [role], "source_type": st, "label": label,
                     "domain": evidence.domain_of(url), "via": via}

    if tavily_check.has_key(tavily_key):
        plan = search_plan(hotel, city, segments)
        say(f"Searching for coverage, listings and awards ({len(plan)} searches)...")
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(_run_search, r, q, o, tavily_key) for r, q, o in plan]
            for f in futs:
                res = f.result()
                out["queries"].append({k: res[k] for k in ("role", "query", "error", "credits")}
                                      | {"n_results": len(res["results"])})
                out["tavily_credits"] += res["credits"]
                for r in res["results"]:
                    out["raw_results"].append(r)
                    add(r.get("url"), r.get("title"), r.get("content"),
                        r.get("published_date"), res["role"])
    else:
        out["notes"].append("No Tavily key is configured, so the planned searches were not run: "
                            "media coverage, listing footprint, awards and publication targets "
                            "could not be discovered.")
    # hits the earlier Tavily pass already found cost nothing to reuse
    for k in ("ota_hits", "editorial_hits", "social_hits", "other_hits"):
        for h in (existing_tavily or {}).get(k, []) or []:
            add(h.get("url"), h.get("title"), h.get("snippet"), None, "existing", via="tavily")

    cands = [c for c in pool.values() if c["source_type"] != "own_website"]

    # ---- 3. read the pages worth reading
    def readable(c):
        if c["source_type"] in ("social", "video", "map_or_open_data", "wiki",
                                "government_register"):
            return False
        return sourcetypes.may_read(c["url"])

    def prio(c):
        base = min(ROLE_PRIORITY.get(r, 5) for r in c["roles"])
        if c["source_type"] == "booking_platform":
            base += 3
        return base

    to_read = sorted([c for c in cands if readable(c)], key=prio)[:max_reads]
    t0 = time.time()
    if to_read:
        say(f"Reading {len(to_read)} pages that may cover the hotel...")
        ex = ThreadPoolExecutor(max_workers=6)
        futs = {ex.submit(_read_candidate, c, hotel, city, postcode, base_url): c
                for c in to_read}
        try:
            for f in as_completed(futs, timeout=read_budget_s):
                out["reads"]["attempted"] += 1
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    futs[f]["read"] = {"status": "not_read", "why": f"error: {type(e).__name__}",
                                       "robots_blocked": False}
        except Exception:  # TimeoutError: budget used up
            out["reads"]["budget_hit"] = True
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    for c in cands:
        c.setdefault("read", {"status": "not_read",
                              "why": ("platform terms prohibit automated reading"
                                      if not sourcetypes.may_read(c["url"])
                                      else "not selected for reading (limit reached or not an article-type source)"),
                              "robots_blocked": False})
        if c["read"]["status"] == "read":
            out["reads"]["ok"] += 1
        elif c["read"].get("robots_blocked"):
            out["reads"]["robots_blocked"] += 1
        elif c in to_read:
            out["reads"]["failed"] += 1

    # ---- 4. join the background adapters (they ran while we searched and read)
    join_deadline = time.time() + 45
    for f, name in adapter_futs.items():
        try:
            out["sources"][name] = f.result(timeout=max(1, join_deadline - time.time()))
        except Exception as e:  # noqa: BLE001 - one adapter failing never fails the audit
            why = ("timed out waiting for the server" if type(e).__name__ == "TimeoutError"
                   else f"adapter error: {type(e).__name__}")
            out["sources"][name] = {"source": name, "status": "unavailable", "reason": why,
                                    "items": [], "access": ""}
    adapter_ex.shutdown(wait=False, cancel_futures=True)
    # GDELT items found late still join the candidate list (unread: reading is done)
    for it in (out["sources"].get("gdelt") or {}).get("items", []):
        key = canonical_url(it["url"])
        if key not in {c["key"] for c in cands}:
            st, label = sourcetypes.classify_domain(it["url"], base_url)
            cands.append({"url": it["url"], "key": key, "title": it["title"][:200], "snippet": "",
                          "published_search": it["published"], "roles": ["news_recent"],
                          "source_type": st, "label": label, "domain": it["domain"], "via": "gdelt",
                          "read": {"status": "not_read", "why": "found after reading had finished",
                                   "robots_blocked": False}})
    out["candidates"] = cands
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out
