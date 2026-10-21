"""
Open community conversations the hotel could join.

Assistants lean on places where anyone can post (Reddit above all). A traveller asking 'where should I stay near the Opera?' on one of them is asking exactly what the hotel's market questions ask, and the hotel can
answer honestly, in its own name. This finds those threads and gives the link.

Which forums: Reddit, Quora, the Travel Stack Exchange, FlyerTalk and Fodor's: places where any signed-in person can reply. Not Tripadvisor (its forum and reviews are a different kind of source and are not part of this).

How: one web search per few questions, limited to those sites, asking for recent threads where a traveller asks for hotels like this one's. A thread counts ONLY if it was in the search results (its link and the passage the search
service itself quoted); we never read the forums directly (Reddit blocks it), and the model's words are thrown away. Each thread is then judged by plain rules, not by the model: does it ask for a recommendation, does it
mention the town or one of the places the questions are built around, is it too old to take a comment (Reddit archives threads after about six months), did an AI answer in this audit cite it, does it already name the hotel.

What it never does: post anything, create accounts, or suggest posting as a guest, seeding reviews, asking for upvotes or offering anything in return. The guidance is to answer as the hotel, say so, read the rules, and help.
"""

import re
import urllib.parse

import ai_sample
import evidence
import identity

SOURCE = "Open community conversations (Reddit and similar)"
FORUMS = ["reddit.com", "quora.com", "travel.stackexchange.com", "flyertalk.com", "fodors.com"]
LABEL = {"reddit.com": "Reddit", "quora.com": "Quora", "travel.stackexchange.com": "Travel Stack Exchange", "flyertalk.com": "FlyerTalk", "fodors.com": "Fodor's forum"}
MAX_SEARCHES = 5
MAX_TOKENS = 2500
REDDIT_ARCHIVE_MONTHS = 6
_ASK = re.compile(r"where (?:to|should|can|do)|recommend|suggest|looking for|best (?:hotel|place|area|neighbou?rhood)|which hotel|hotels? (?:near|in|around|for)|any (?:ideas|tips|advice)|advice|stay(?:ing)? (?:near|in|at)|accommodation|"
                  r"\b(?:ideas|tips) for\b|where to stay|help me (?:choose|pick|find)", re.I)
_THREAD = re.compile(r"/r/([^/]+)/comments/([a-z0-9]+)", re.I)
SYSTEM = ("You find open forum threads where travellers ask for hotel recommendations. Use the web search tool, which is limited to open forums. Prefer threads from the last twelve months. "
          "List each thread you found with its link, in one line. Do not summarise the hotels recommended in them. If you find nothing relevant, say so plainly.")
PROMPT = ("Search for forum threads where a traveller asks for hotel recommendations like these (they are the questions a hotel in {city} is chosen for):\n{questions}\n"
          "Find recent threads in {city}'s travel communities and on Reddit, Quora and travel forums, where someone is asking where to stay for a reason like those. List the threads you found, one per line, with the link.")


def _envelope(status, reason="", **kw):
    return {"source": SOURCE, "status": status, "reason": reason, "opportunities": [], "closed": [], "searches": 0, "cost_usd": 0.0, "forums": [LABEL[d] for d in FORUMS], **kw}


def _domain(url):
    h = urllib.parse.urlparse(url or "").netloc.lower()
    h = h[4:] if h.startswith("www.") else h
    return next((f for f in FORUMS if h == f or h.endswith("." + f)), None)


def _is_thread(url, domain):
    p = urllib.parse.urlparse(url)
    path = p.path.lower().rstrip("/")
    if domain == "reddit.com":
        return bool(_THREAD.search(path))
    if domain == "travel.stackexchange.com":
        return bool(re.search(r"/questions/\d+", path))
    if domain == "quora.com":
        return path.count("/") == 1 and len(path) > 25 and "-" in path
    if domain == "flyertalk.com":
        return bool(re.search(r"/\d+-[a-z0-9-]+\.html$", path)) or "/threads/" in path
    return len(path.split("/")) >= 3 and bool(re.search(r"\d", path) or len(path) > 30)


def age_months(text):
    """How old a result is, in months, from the age the search service gives ('3 weeks ago', 'March 3, 2026', '2026-03-03'); None when it gives none."""
    t = str(text or "").strip().lower()
    if not t:
        return None
    m = re.match(r"(\d+)\s+(day|week|month|year)s?\s+ago", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return round(n * {"day": 1 / 30, "week": 1 / 4.3, "month": 1, "year": 12}[u], 1)
    d = evidence.parse_date(text)
    if d:
        import time
        now = time.gmtime()
        return float((now.tm_year - int(d[:4])) * 12 + (now.tm_mon - int(d[5:7])))
    return None


def can_comment(domain, months):
    """'open' | 'likely open' | 'closed' | 'check' and the plain-words reason. Reddit locks comments on a thread about six months after it was posted; the other forums keep threads open."""
    if domain == "reddit.com":
        if months is None:
            return "check", "Reddit stops accepting comments on threads about six months old: open the link to see whether this one still takes them"
        return (("open", "recent enough to take a comment") if months <= REDDIT_ARCHIVE_MONTHS - 1 else ("closed", "older than Reddit's six months: archived, no new comments (assistants may still read it)"))
    if months is None:
        return "check", "its age was not shown: open the link to see whether it still takes replies"
    return ("likely open", "this forum keeps old threads open for replies") if months <= 36 else ("check", "an old thread: replies may be closed")


def _norm(u):
    return re.sub(r"[?#].*$", "", (u or "").lower()).rstrip("/")


def judge(pages, passages, hotel, city, place_terms, ai_cited_urls=()):
    """
    The threads among the search results, each judged by rules: -> (open opportunities, closed ones). A result is a thread on one of the open forums, and it either asks for a recommendation or already names the hotel.
    place_terms: the town and the places the questions are built around, to see whether the thread is about the hotel's market.
    """
    said = {}
    for ps in passages or []:
        if _domain(ps.get("url")):
            said.setdefault(ps["url"], []).append(ps.get("cited_text", ""))
    terms = [t for t in {evidence.fold(x) for x in place_terms if x and len(x) > 2} if t]
    cited = {_norm(u) for u in ai_cited_urls}
    seen, ops = set(), []
    for p in pages or []:
        url = p.get("url") or ""
        dom = _domain(url)
        if not dom or not _is_thread(url, dom) or _norm(url) in seen:
            continue
        seen.add(_norm(url))
        title = (p.get("title") or "").replace(" : ", " - ")[:140] or "(untitled thread)"
        passage = " ".join(filter(None, [p.get("cited_text", "")] + said.get(url, [])))[:500]
        blob = evidence.fold(f"{title} {passage} {url}")
        about = bool(identity.names_hotel(url, title, passage, hotel))
        asks = bool(_ASK.search(f"{title} {passage}"))
        matched = [t for t in terms if t in blob]
        if not (asks or about) or not matched and not about:
            continue
        months = age_months(p.get("age"))
        status, why = can_comment(dom, months)
        tid = _THREAD.search(url)
        ops.append({"url": url, "forum": ("r/" + tid.group(1)) if tid else LABEL[dom], "site": LABEL[dom], "title": title, "passage": passage[:260], "asks": asks, "about_hotel": about, "matches": matched[:3],
                    "age": p.get("age") or "", "age_months": months, "can_comment": status, "can_comment_why": why, "cited_by_ai": _norm(url) in cited})
    rank = {"open": 0, "likely open": 1, "check": 2, "closed": 3}
    ops.sort(key=lambda o: (rank[o["can_comment"]], not o["cited_by_ai"], -len(o["matches"]), o["age_months"] if o["age_months"] is not None else 99, o["url"]))
    return [o for o in ops if o["can_comment"] != "closed"][:12], [o for o in ops if o["can_comment"] == "closed"][:6]


def run(hotel, city, questions, place_terms=(), *, api_key=None, model=None, client=None, ai_cited_urls=()):
    """-> the envelope {"status", "reason", "opportunities", "closed", "searches", "cost_usd", "forums"}. Never raises. `questions` are the hotel's market questions (their wording is what the search looks for)."""
    model = model or ai_sample.MODEL_DEFAULT
    if not hotel or not (city or "").strip():
        return _envelope("not_configured", "The hotel's name and town are both needed to look for forum conversations.")
    if client is None:
        if not api_key:
            return _envelope("not_configured", "No Anthropic API key is configured, so the forums were not searched.")
        try:
            client = ai_sample._make_client(api_key, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return _envelope("unavailable", f"The Anthropic library could not be started ({type(e).__name__}).")
    town = city.split(",")[0].strip()
    qs = [q for q in (questions or [])][:6] or [f"Where should I stay in {town}?"]
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    tool = {**ai_sample.SEARCH_TOOL, "max_uses": MAX_SEARCHES, "allowed_domains": list(FORUMS)}
    messages = [{"role": "user", "content": PROMPT.format(city=town, questions="\n".join("- " + q for q in qs))}]
    pages, passages, searches, tin, tout = {}, [], 0, 0, 0
    try:
        for _ in range(3):
            resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[dict(tool)], messages=messages, **extra)
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
        return _envelope("unavailable", ai_sample._reason_for(e), searches=searches, cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5))
    ops, closed = judge(list(pages.values()), passages, hotel, town, [town] + list(place_terms or []), ai_cited_urls)
    reason = "" if ops or closed else "No open conversation matching the hotel's market turned up in these searches. That is what the searches saw, not proof there are none: threads the search cannot see are not counted."
    return _envelope("ok", reason, opportunities=ops, closed=closed, searches=searches, cost_usd=round(ai_sample.cost_usd(model, tin, tout, searches), 5))
