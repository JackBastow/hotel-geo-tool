"""
Find the hotel's own listing page on each major booking and review site, so the listing footprint does not say "not found" for a
hotel that is plainly listed.

Why this exists: the wider discovery only keeps what a handful of general web searches happened to return, and those often
miss a listing (an Expedia page for a hotel that has one). Here one Claude model with web search is asked to look for the hotel
on each site in turn. We use it only to DRIVE the searches: its words are thrown away, and a listing is accepted only if a page
in the search results it actually ran (or in the answers and review pages already collected in this audit) is on that site's
domain AND its address or title carries the hotel's name. Nothing is opened or read: the platforms' terms prohibit automated
reading, so a found listing is reported as "found in public search results; page not read".
"""

import re
import urllib.parse

import ai_sample
import evidence
import identity

SOURCE = "Listing lookup (AI web search)"
PLATFORMS = [(label, token) for label, token in identity.KEY_PLATFORMS if label in
             ("Booking.com", "Expedia", "Hotels.com", "TripAdvisor", "Trivago", "Agoda", "Trip.com")]
MAX_TOKENS = 1500

SYSTEM = ("You are a research assistant who finds a hotel's own listing page on booking and review websites. Use the web search tool, one search per site, "
          "with the hotel's name, its town and the site's name. You only need to search; when you are done reply with the single word: done.")

PROMPT = "Find the page for the hotel \"{hotel}\" in {city} on each of these websites: {sites}. Search for each site separately."


def _domain(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def hits_from_pages(pages, hotel, city, have=()):
    """
    pages: [{url, title}] from any source. -> [{platform, url, title, location_confirmed}] for the platforms in PLATFORMS not in `have`,
    one per platform, only where the page is on that platform's domain and the hotel's name is in its address or title.
    """
    town = evidence.fold((city or "").split(",")[0])
    out = {}
    for label, token in PLATFORMS:
        if label in have:
            continue
        cands = [p for p in pages if p.get("url") and token in _domain(p["url"]) + "/" and identity.names_hotel(p["url"], p.get("title", ""), "", hotel)]
        if not cands:
            continue
        cands.sort(key=lambda p: town in evidence.fold(f"{p.get('title', '')} {p['url']}") if town else False, reverse=True)
        c = cands[0]
        out[label] = {"platform": label, "url": c["url"], "title": (c.get("title") or "")[:100],
                      "location_confirmed": bool(town and town in evidence.fold(f"{c.get('title', '')} {c['url']}"))}
    return list(out.values())


def run(hotel, city, *, api_key=None, model=None, client=None, have=()):
    """-> {"status", "reason", "pages", "cost_usd", "searches"}. Never raises. `have`: platform labels already found, which are not searched for."""
    def env(status, reason="", **kw):
        return {"source": SOURCE, "status": status, "reason": reason, "pages": [], "cost_usd": 0.0, "searches": 0, **kw}

    model = model or ai_sample.MODEL_DEFAULT
    todo = [(l, t) for l, t in PLATFORMS if l not in have]
    if not hotel or not (city or "").strip():
        return env("not_configured", "The hotel's name and town are both needed to look for its listings.")
    if not todo:
        return env("ok", "Every platform was already found.")
    if client is None:
        if not api_key:
            return env("not_configured", "No Anthropic API key is configured, so the listings were not looked for beyond the general searches.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return env("unavailable", f"The Anthropic library could not be started ({type(e).__name__}).")
    tool = {**ai_sample.SEARCH_TOOL, "max_uses": len(todo) + 1}
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    messages = [{"role": "user", "content": PROMPT.format(hotel=hotel, city=city.split(",")[0].strip(), sites=", ".join(l for l, _ in todo))}]
    pages, searches, tin, tout = {}, 0, 0, 0
    try:
        for _ in range(3):                                   # a long search can pause; continue it up to twice
            resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[dict(tool)], messages=messages, **extra)
            for p in ai_sample.parse_sources(resp, limit=200):
                pages.setdefault(p["url"], p)
            _a, _d, s, i, o = ai_sample.parse_response(resp)
            searches, tin, tout = searches + s, tin + i, tout + o
            if ai_sample._get(resp, "stop_reason") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": ai_sample._get(resp, "content", []) or []}]
                continue
            break
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return env("unavailable", ai_sample._reason_for(e), cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5), searches=searches)
    return env("ok", "", pages=list(pages.values()), cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5), searches=searches)


def as_candidates(hits, base_url=""):
    """Footprint candidates for pages found this way, shaped like the ones the wider discovery builds (so the rest of the audit treats them the same)."""
    import sourcetypes
    out = []
    for h in hits:
        st, label = sourcetypes.classify_domain(h["url"], base_url)
        out.append({"url": h["url"], "key": re.sub(r"[?#].*$", "", h["url"]).rstrip("/").lower(), "title": h.get("title", ""), "snippet": "", "published_search": None,
                    "roles": ["listing_lookup"], "source_type": st, "label": label or h["platform"], "domain": evidence.domain_of(h["url"]), "via": "anthropic_search",
                    "read": {"status": "not_read", "why": "found in public search results by an AI web search; the page was not opened (the platform's terms prohibit automated reading)",
                             "robots_blocked": False}})
    return out
