"""
Reddit: how the hotel shows up on the site that AI assistants cite most for "where should I stay" questions.

Reddit cannot be read directly: anonymous access is blocked and the official API is paid for commercial use. So this works from two free sources and says so:
  1. The sampled AI answers the audit already collected: how many cited Reddit, and which threads.
  2. One web-search call (Anthropic's search tool, restricted to reddit.com) that looks for threads about the hotel and for traveller threads about the town. We use it only to DRIVE
     the search: its words are thrown away, and a thread is accepted only if it was in the search results, with the passage the search service itself quoted.
Threads the search cannot see are not counted: "no thread found in these searches" is never reported as "nobody talks about the hotel". The tone of a thread is a rule-based reading of
the quoted passage and is shown only where the passage names the hotel.
"""

import re
import urllib.parse

import ai_sample
import identity

SOURCE = "Reddit (searches of public pages, and the sampled AI answers)"
MAX_TOKENS = 2500
MAX_SEARCHES = 4
SEARCH_TOOL = {**ai_sample.SEARCH_TOOL, "max_uses": MAX_SEARCHES, "allowed_domains": ["reddit.com"]}

SYSTEM = ("You are a research assistant who finds Reddit discussions about a hotel and about where to stay in its town. Use the web search tool (it only searches Reddit). "
          "Then write one short line per thread you found, saying which subreddit it is in and, only if the thread mentions the hotel, quoting what it says about it. "
          "Quote only what the thread shows. If nothing relevant exists, say so plainly.")
PROMPT = ("Search Reddit for discussions of the hotel \"{hotel}\" in {city}, then for traveller threads about where to stay in {city} (for example 'where to stay in {city}', "
          "'{city} hotel recommendations', 'best area to stay in {city}'). List the threads you found, one line each.")

_POS = re.compile(r"\b(lovely|great|excellent|recommend(?:ed)?|clean|friendly|comfortable|perfect|amazing|loved|helpful|good value|fantastic|superb|wonderful|spotless)\b", re.I)
_NEG = re.compile(r"\b(dirty|noisy|rude|terrible|avoid|awful|disappointing|disappointed|filthy|scam|overpriced|smell(?:y|ed)?|worst|poor|horrible|mould|bed ?bugs?)\b", re.I)
_THREAD = re.compile(r"/r/([^/]+)/comments/([a-z0-9]+)", re.I)


def _reddit(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def _thread_id(url):
    m = _THREAD.search(urllib.parse.urlparse(url or "").path)
    return (m.group(1), m.group(2)) if m else None


def tone_of(text):
    """'positive' | 'critical' | 'mixed' | 'no clear tone', by counting plain praise and complaint words in the passage. Rule-based, and only a hint."""
    p, n = len(_POS.findall(text or "")), len(_NEG.findall(text or ""))
    if not p and not n:
        return "no clear tone"
    if p and n:
        return "positive" if p >= 2 * n else "critical" if n >= 2 * p else "mixed"
    return "positive" if p else "critical"


def _envelope(status, reason="", **kw):
    return {"source": SOURCE, "status": status, "reason": reason, "pages": [], "passages": [], "cost_usd": 0.0, "searches": 0, **kw}


def run(hotel, city, *, api_key=None, model=None, client=None):
    """-> {"status", "reason", "pages", "passages", "cost_usd", "searches"}. Never raises."""
    model = model or ai_sample.MODEL_DEFAULT
    if not hotel or not (city or "").strip():
        return _envelope("not_configured", "The hotel's name and town are both needed to look for Reddit threads.")
    if client is None:
        if not api_key:
            return _envelope("not_configured", "No Anthropic API key is configured, so Reddit was not searched.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return _envelope("unavailable", f"The Anthropic library could not be started ({type(e).__name__}).")
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    messages = [{"role": "user", "content": PROMPT.format(hotel=hotel, city=city.split(",")[0].strip())}]
    pages, passages, searches, tin, tout = {}, [], 0, 0, 0
    try:
        for _ in range(3):
            resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[dict(SEARCH_TOOL)], messages=messages, **extra)
            for p in ai_sample.parse_sources(resp, limit=100):
                pages.setdefault(p["url"], p)
            passages += ai_sample.parse_passages(resp)
            _a, _d, s, i, o = ai_sample.parse_response(resp)
            searches, tin, tout = searches + s, tin + i, tout + o
            if ai_sample._get(resp, "stop_reason") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": ai_sample._get(resp, "content", []) or []}]
                continue
            break
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return _envelope("unavailable", ai_sample._reason_for(e), cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5), searches=searches)
    return _envelope("ok", "", pages=list(pages.values()), passages=passages[:100], cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5), searches=searches)


def _threads(pages, passages, hotel):
    """Reddit threads among the pages found: [{url, subreddit, title, passage, about_hotel, tone}], one per thread."""
    said = {}
    for ps in passages or []:
        if _reddit(ps.get("url")):
            said.setdefault(ps["url"], []).append(ps.get("cited_text", ""))
    seen, out = set(), []
    for p in pages or []:
        url = p.get("url") or ""
        tid = _thread_id(url)
        if not _reddit(url) or not tid or tid in seen:
            continue
        seen.add(tid)
        passage = " ".join(filter(None, [p.get("cited_text", "")] + said.get(url, [])))[:500]
        about = bool(identity.names_hotel(url, p.get("title", ""), passage, hotel))
        out.append({"url": url, "subreddit": tid[0], "title": (p.get("title") or "").replace(" : ", " - ")[:140] or "(untitled thread)", "passage": passage,
                    "about_hotel": about, "tone": tone_of(passage) if about and passage else None})
    return out


def build(lookup, ai_result, hotel, city=""):
    """
    The Reddit section of the report, from the search `lookup` (or None) and the sampled AI answers `ai_result` (or None). Never raises.
    summary.hotel_mentioned is True when a found thread names the hotel, False when the search ran and found none, and None when no search ran, so nothing is claimed.
    """
    lookup = lookup or _envelope("not_configured", "Reddit was not searched.")
    threads = _threads(lookup.get("pages"), lookup.get("passages"), hotel) if lookup.get("status") == "ok" else []
    hotel_threads = [t for t in threads if t["about_hotel"]]
    town_threads = [t for t in threads if not t["about_hotel"]]
    items = [i for i in (ai_result or {}).get("items") or [] if i.get("answer")]
    cited_items = [i for i in items if any(_reddit(f"https://{d}") for d in i.get("domains") or [])]
    ai_threads, seen = [], set()
    for i in items:
        for t in _threads([p for p in i.get("pages") or [] if p.get("cited")], [], hotel):
            if (t["subreddit"], t["url"]) not in seen:
                seen.add((t["subreddit"], t["url"]))
                ai_threads.append(t)
    searched = lookup.get("status") == "ok"
    summary = {"hotel_mentioned": (bool(hotel_threads) if searched else None), "hotel_threads": len(hotel_threads), "town_threads": len(town_threads), "searches": lookup.get("searches", 0),
               "tones": {k: sum(1 for t in hotel_threads if t["tone"] == k) for k in ("positive", "mixed", "critical", "no clear tone")},
               "ai_answers": len(items), "ai_cited_reddit": len(cited_items), "ai_threads": len(ai_threads),
               "ai_threads_name_hotel": sum(1 for t in ai_threads if t["about_hotel"]),
               "subreddits": sorted({t["subreddit"] for t in threads + ai_threads})[:8]}
    if lookup.get("status") != "ok" and not items:
        return {"source": SOURCE, "status": lookup["status"], "reason": lookup.get("reason", ""), "hotel_threads": [], "town_threads": [], "ai_threads": [], "summary": summary, "cost_usd": lookup.get("cost_usd", 0.0)}
    return {"source": SOURCE, "status": "ok" if searched or items else lookup["status"], "reason": "" if searched else lookup.get("reason", ""), "hotel_threads": hotel_threads,
            "town_threads": town_threads[:8], "ai_threads": ai_threads[:8], "summary": summary, "cost_usd": lookup.get("cost_usd", 0.0), "searches": lookup.get("searches", 0)}
