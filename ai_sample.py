"""
A SAMPLE of what an AI assistant says when asked about the hotel.

The audit measures how well a hotel is set up to be understood. It cannot see what an assistant
actually answers. This module asks one Claude model about eight ordinary traveller questions with
live web search switched on, and records:

  * whether the hotel is named in the answer (and where in a list),
  * what the assistant says when asked about the hotel directly,
  * which websites it relied on (the sources worth being accurately listed on).

What this is NOT: a ranking, a measurement of "AI visibility" in general, or what ChatGPT or Gemini
would say. It is one model, on one day, asked a few questions; answers change between runs. It is shown
as a sample, never scored, and always labelled with the model and date.

Cost control (the operator's free credit is the budget):
  * a fixed number of questions (at most MAX_QUESTIONS), each limited to MAX_SEARCHES web searches and a token cap;
  * an estimated cost is computed from the usage the API reports and returned, so the app can keep a
    monthly counter and stop calling when the budget is used up;
  * a per-audit ceiling: once the estimate passes `budget_usd`, remaining questions are skipped;
  * every failure (no key, rejected key, out of credit, rate limit, tool not available) becomes a stated
    reason - never an error that fails the audit.
The hard stop is the spend limit set on the workspace in the Anthropic Console; this is a second guard.
"""

import re
import time
import urllib.parse

import evidence

SOURCE = "Claude (sampled answers)"
MODEL_DEFAULT = "claude-haiku-5-5"
MAX_SEARCHES = 3
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}
MAX_TOKENS = 1500
MAX_QUESTIONS = 8
WORKERS = 3

# USD per million tokens (input, output) - Anthropic's published list prices for the models we allow.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
SEARCH_USD = 0.010          # $10 per 1,000 web searches
EFFORT_MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")

ACCESS = (
    "Anthropic Claude API with its web-search tool. Uses the operator's own free credit, with a monthly budget guard and the "
    "workspace spend limit as the hard stop. It asks ONE model several traveller questions: a sample, not a ranking, and not what "
    "ChatGPT or Gemini would say. Answers differ between runs and between models.")

SYSTEM = ("You are a travel assistant answering a traveller's question. Search the web, running at least two searches with different wording, before you answer. Answer in at most 150 words. "
          "When you recommend hotels, name them in a short list, most suitable first, and say in a few words why. "
          "Only state facts you found; say so when you could not find something.")

_GENERIC = {"hotel", "hotels", "the", "by", "and", "spa", "resort", "resorts", "at", "of", "&", "inn", "suites", "collection"}


# ----------------------------------------------------------------- questions

def build_questions(hotel, city, segments=(), max_questions=MAX_QUESTIONS):
    """
    Ordinary things a traveller types. Generic ones test whether the hotel is named unprompted; the direct ones ask about
    the hotel itself: what it is, what it offers, what guests say, and which hotels the assistant sees as alternatives.
    """
    place = (city or "").split(",")[0].strip()
    if not place:
        return []
    segs = [x for x in segments if x][:2]
    generic = [{"id": "best", "kind": "generic", "text": f"What are the best hotels in {place}?"},
               {"id": "where", "kind": "generic", "text": f"Where should I stay in {place}? I want somewhere comfortable and well located."},
               {"id": "value", "kind": "generic", "text": f"Which hotels in {place} offer good value for money?"},
               {"id": "transport", "kind": "generic", "text": f"Which hotels in {place} are best for getting around, close to the station or airport?"}]
    for i, sg in enumerate(segs):
        generic.insert(1 + i, {"id": f"segment{i}", "kind": "generic", "text": f"I'm interested in {sg.lower()} in {place}. Which hotels would you suggest?"})
    direct = [{"id": "about", "kind": "direct", "text": f"Tell me about {hotel} in {place}. What is it like, and is it a good choice?"},
              {"id": "facilities", "kind": "direct", "text": f"What facilities does {hotel} in {place} have, and what is it known for?"},
              {"id": "reviews", "kind": "direct", "text": f"What do guests say about {hotel} in {place}? What do they like, and what do they complain about?"},
              {"id": "similar", "kind": "direct", "text": f"Which hotels in {place} are similar to {hotel}, and how do they compare?"}]
    # the direct questions are the point of the exercise: keep as many as fit, then fill the rest with generic ones in order
    room = max(0, max_questions - len(direct))
    if room == 0:
        return direct[:max_questions]
    return generic[:room] + direct


# ------------------------------------------------------------------ analysis

def _core_tokens(hotel):
    return [t for t in re.split(r"[^a-z0-9]+", evidence.fold(hotel)) if t and t not in _GENERIC]


def mentioned(text, hotel, city=""):
    """Is THIS hotel named? Full name, or its distinctive words together; a bare one-word name needs the place beside it."""
    if not text or not hotel:
        return False
    t, h = evidence.fold(text), evidence.fold(hotel).strip()
    core = _core_tokens(hotel)
    if not core:
        return False
    if len(core) >= 2:
        return (h in t) or (" ".join(core) in t)
    if h != core[0]:
        # "Brooklands Hotel": the distinctive word alone is also a museum and a racetrack, so it must appear AS a hotel
        return (h in t) or re.search(r"\b" + re.escape(core[0]) + r"\s+(?:hotel|spa|resort|inn|suites)\b", t) is not None
    # a bare one-word name: only with the town in the same sentence
    place = evidence.fold((city or "").split(",")[0]).strip()
    sentences = re.split(r"(?<=[.!?\n])\s+", t)
    return any(core[0] in s and bool(place) and place in s for s in sentences)


def list_position(text, hotel):
    """1-based place of the hotel among list lines (numbered or bulleted) in the answer; None when it is not in a list."""
    lines = [ln for ln in (text or "").splitlines() if re.match(r"\s*(?:\d+[.)]|[-*•])\s+", ln)]
    for i, ln in enumerate(lines, 1):
        if mentioned(ln, hotel):
            return i
    return None


def _host(url):
    h = urllib.parse.urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def parse_response(resp):
    """-> (answer text, source domains in the order they were seen, searches run, input tokens, output tokens)."""
    text, domains, searches = [], [], 0
    for b in _get(resp, "content", []) or []:
        bt = _get(b, "type")
        if bt == "text":
            text.append(_get(b, "text", "") or "")
            for c in _get(b, "citations", None) or []:
                d = _host(_get(c, "url", ""))
                if d and d not in domains:
                    domains.append(d)
        elif bt == "web_search_tool_result":
            res = _get(b, "content")
            if isinstance(res, list):                       # a list on success, an error object otherwise
                for r in res:
                    d = _host(_get(r, "url", ""))
                    if d and d not in domains:
                        domains.append(d)
    u = _get(resp, "usage")
    st = _get(u, "server_tool_use") if u is not None else None
    searches = int(_get(st, "web_search_requests", 0) or 0) if st is not None else 0
    tin = int((_get(u, "input_tokens", 0) or 0) + (_get(u, "cache_creation_input_tokens", 0) or 0) + (_get(u, "cache_read_input_tokens", 0) or 0)) if u is not None else 0
    tout = int(_get(u, "output_tokens", 0) or 0) if u is not None else 0
    return "".join(text).strip(), domains, searches, tin, tout


def cost_usd(model, tin, tout, searches):
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])        # unknown model: assume the dearest, never under-count
    return round(tin / 1e6 * pin + tout / 1e6 * pout + searches * SEARCH_USD, 5)


def _envelope(status, reason="", **kw):
    return {"source": SOURCE, "status": status, "reason": reason, "access": ACCESS, "items": [], **kw}


def _reason_for(exc):
    name = type(exc).__name__
    code = getattr(exc, "status_code", None)
    if code in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        return "Anthropic rejected the API key (check it is correct and belongs to a workspace with credit)."
    if code == 402 or "credit" in str(exc).lower() or "billing" in str(exc).lower():
        return "The Anthropic account has no credit left, so the sampled AI answers were not run."
    if code == 429 or name == "RateLimitError":
        return "Anthropic's rate limit was reached, so the sampled AI answers were not run."
    if code == 400 or name == "BadRequestError":
        return "Anthropic rejected the request (the model or its web-search tool may not be available to this account)."
    return f"The Anthropic API did not answer ({name}), so the sampled AI answers were not run."


def budget_exhausted():
    return _envelope("unavailable", "This month's allowance for sampled AI answers has been used, so no assistant was asked this time. It resets next month.")


# ---------------------------------------------------------------------- run

def run(hotel, city, *, api_key=None, model=None, segments=(), own_domain="", budget_usd=0.80, client=None, progress=None,
        max_questions=MAX_QUESTIONS, workers=WORKERS):
    """Ask the questions. `client` is injectable for tests; otherwise the official SDK is created from `api_key`."""
    def say(m):
        if progress:
            progress(m)

    model = model or MODEL_DEFAULT
    if not hotel or not (city or "").strip():
        return _envelope("not_configured", "The hotel's name and town are both needed to ask an assistant about it, so this was not run.")
    if client is None:
        if not api_key:
            return _envelope("not_configured", "No Anthropic API key is configured, so no AI assistant was asked about the hotel.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=60.0)
        except Exception as e:  # noqa: BLE001
            return _envelope("unavailable", f"The Anthropic library could not be started ({type(e).__name__}), so this was not run.")

    import threading
    from concurrent.futures import ThreadPoolExecutor
    own = _host(own_domain)
    qs = build_questions(hotel, city, segments, max_questions)
    lock = threading.Lock()
    state = {"spent": 0.0, "why": "", "stop": False}

    def ask(q):
        with lock:
            if state["stop"]:
                return None
            if state["spent"] >= budget_usd:
                state["why"] = state["why"] or "Stopped early to stay within the per-audit budget."
                return None
        say(f"Asking an AI assistant: {q['text']}")
        try:
            extra = {"output_config": {"effort": "low"}} if model in EFFORT_MODELS else {}       # older models reject the effort setting
            resp = client.messages.create(
                model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[dict(SEARCH_TOOL)],
                messages=[{"role": "user", "content": q["text"]}], **extra)
        except Exception as e:  # noqa: BLE001 - never fail the audit
            with lock:
                state["why"] = state["why"] or _reason_for(e)
                state["stop"] = True
            return None
        answer, domains, searches, tin, tout = parse_response(resp)
        c = cost_usd(model, tin, tout, searches)
        with lock:
            state["spent"] += c
        if not answer:
            return {**q, "answer": "", "mentioned": None, "position": None, "domains": domains, "searches": searches, "cost_usd": c,
                    "note": "The assistant returned no answer text."}
        return {**q, "answer": answer, "mentioned": mentioned(answer, hotel, city), "position": list_position(answer, hotel),
                "domains": domains, "searches": searches, "cost_usd": c,
                "own_site_cited": bool(own and any(d == own or d.endswith("." + own) for d in domains))}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:      # a few at a time: faster, still gentle on the rate limit
        items = [r for r in ex.map(ask, qs) if r]
    spent, why = state["spent"], state["why"]
    if not items:
        return _envelope("unavailable", why or "No question could be asked.", model=model, cost_usd=round(spent, 5))
    generic = [i for i in items if i["kind"] == "generic" and i["mentioned"] is not None]
    directs = [i for i in items if i["kind"] == "direct" and i["mentioned"] is not None]
    direct = next((i for i in items if i["id"] == "about"), None) or (directs[0] if directs else None)
    cited = {}
    for i in items:
        for d in i["domains"]:
            cited[d] = cited.get(d, 0) + 1
    summary = {"asked": len(items), "generic_asked": len(generic), "generic_named": sum(1 for i in generic if i["mentioned"]),
               "direct_known": None if not direct else bool(direct["mentioned"]),
               "direct_asked": len(directs), "direct_named": sum(1 for i in directs if i["mentioned"]),
               "own_site_cited": any(i.get("own_site_cited") for i in items),
               "top_domains": [d for d, _ in sorted(cited.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]}
    return _envelope("ok", why, model=model, items=items, summary=summary, cost_usd=round(spent, 5), partial=bool(why),
                     run_at=time.strftime("%Y-%m-%d", time.gmtime()))
