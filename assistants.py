"""
The other AI assistants: ChatGPT (OpenAI), Gemini (Google) and Perplexity, each asked through its official API with live web search switched on. Until Nov 2026 every report was
'tested on Claude only'.

What they are asked: the hotel's TRACKED prompts (the ones asked every week), each a couple of times. Claude still runs the full sample (town-wide, market and exploratory questions);
the other assistants add a second, third and fourth view of the prompts that matter most, at a cost that fits a fixed monthly budget.

Every answer is judged by the same rules as Claude's: the one hotel-name matcher (hotelname.py), the same list-position and recommendation rules, the same one count
(report_model.engine_counts). An assistant with no key, or past its monthly cap, is 'not tested', never shown as zero.

Official APIs only:
  ChatGPT     POST https://api.openai.com/v1/responses, tools [{"type": "web_search"}]; $10 per 1,000 searches plus tokens (OPENAI_MODEL, default gpt-5.4-mini; prices in OPENAI_PRICES)
  Perplexity  POST https://api.perplexity.ai/v1/agent, model perplexity/sonar, tools [{"type": "web_search"}]; the API reports each answer's cost
  Gemini      the existing GeminiClient (Google Search grounding); $14 per 1,000 searches after 5,000 free a month (counted at the full price here, to stay on the safe side)
These answers come through the providers' APIs, a close stand-in for their consumer apps (which add memory, account history and their own settings), and are labelled as such.
"""

import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

import ai_sample

ENGINES = {
    "chatgpt": {"name": "ChatGPT", "maker": "OpenAI", "env": ("OPENAI_API_KEY",), "cap_env": "OPENAI_MONTHLY_CAP_USD", "cap": 60.0},
    "gemini": {"name": "Gemini", "maker": "Google", "env": ("GEMINI_API_KEY", "GEMINI_SEARCH_API_KEY"), "cap_env": "GEMINI_MONTHLY_CAP_USD", "cap": 20.0},
    "perplexity": {"name": "Perplexity", "maker": "Perplexity", "env": ("PERPLEXITY_API_KEY",), "cap_env": "PERPLEXITY_MONTHLY_CAP_USD", "cap": 20.0},
}
REPEATS = 2                 # each tracked prompt, per assistant, per check
WORKERS = 3                 # questions in flight per assistant
MAX_PROMPTS = 20            # tracked prompts asked per check at most
TIMEOUT = 90


def key_for(engine, env=None):
    e = env if env is not None else os.environ
    for n in ENGINES[engine]["env"]:
        v = (e.get(n) or "").strip()
        if v:
            return v
    return None


def service(engine):
    """The name the month's spend is recorded under (store.record_usage, in thousandths of a dollar)."""
    return f"ai_{engine}_usd"


def cap_milli(engine, env=None):
    e = env if env is not None else os.environ
    try:
        usd = float(e.get(ENGINES[engine]["cap_env"]) or ENGINES[engine]["cap"])
    except ValueError:
        usd = ENGINES[engine]["cap"]
    return int(usd * 1000)


def _instructions(country):
    name = ai_sample.COUNTRY_NAMES.get((country or "").upper())
    return f"The user lives in {name}: when a place name could mean more than one place, assume they mean the one in {name}." if name else ""


def _host(u):
    h = urllib.parse.urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


# ----------------------------------------------------------------- one question, one assistant -> {answer, domains, pages, searches, cost_usd}

# OpenAI's published prices ($ per million tokens, input / output; developers.openai.com/api/docs/models, Nov 2026) for models whose pages list web_search. The pages ChatGPT reads during a
# search are billed as input, so the model's input price matters most. gpt-5.4-mini: about $0.03 an answer; gpt-6.2-astra (OpenAI's suggestion for web search) about $0.20.
OPENAI_PRICES = {"gpt-6-luna": (0.10, 0.50), "gpt-5.6-luna": (0.20, 1.20), "gpt-5.4-nano": (0.20, 1.25), "gpt-5.4-mini": (0.75, 4.50), "gpt-5.4": (2.50, 15.00), "gpt-6.2-astra": (8.00, 40.00)}


def ask_chatgpt(q, key, country=None, post=requests.post):
    model = os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini"
    known_in, known_out = OPENAI_PRICES.get(model, (8.0, 40.0))         # an unknown model is priced as the dearest, never under-counted
    price_in = float(os.environ.get("OPENAI_PRICE_IN") or known_in)
    price_out = float(os.environ.get("OPENAI_PRICE_OUT") or known_out)
    tool = {"type": "web_search", "search_context_size": "medium"}
    if country:
        tool["user_location"] = {"type": "approximate", "country": country.upper()}
    body = {"model": model, "input": q, "tools": [tool]}
    ins = _instructions(country)
    if ins:
        body["instructions"] = ins
    r = post("https://api.openai.com/v1/responses", json=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise _Http(r.status_code, r.text[:200])
    d = r.json()
    text, pages, searches = [], [], 0
    for item in d.get("output") or []:
        if item.get("type") == "web_search_call" and (item.get("action") or {}).get("type", "search") == "search":
            searches += 1
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    text.append(c.get("text") or "")
                    for a in c.get("annotations") or []:
                        if a.get("type") == "url_citation" and a.get("url"):
                            pages.append({"url": a["url"], "title": a.get("title") or "", "cited": True})
    u = d.get("usage") or {}
    tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
    cost = tin / 1e6 * price_in + tout / 1e6 * price_out + searches * 0.010
    return {"answer": "\n".join(text).strip(), "pages": pages, "searches": searches, "cost_usd": round(cost, 5), "model": model}


def ask_perplexity(q, key, country=None, post=requests.post):
    model = os.environ.get("PERPLEXITY_MODEL") or "perplexity/sonar"
    tool = {"type": "web_search"}
    if country:
        tool["user_location"] = {"country": country.upper()}
    body = {"model": model, "input": q, "tools": [tool]}
    ins = _instructions(country)
    if ins:
        body["instructions"] = ins
    r = post("https://api.perplexity.ai/v1/agent", json=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise _Http(r.status_code, r.text[:200])
    d = r.json()
    text, pages = [], []
    for item in d.get("output") or []:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    text.append(c.get("text") or "")
        if item.get("type") == "search_results":
            for res in item.get("results") or []:
                if res.get("url"):
                    pages.append({"url": res["url"], "title": res.get("title") or "", "cited": True})
    u = d.get("usage") or {}
    searches = int(((u.get("tool_calls_details") or {}).get("search_web") or {}).get("invocation") or 0)
    cost = (u.get("cost") or {}).get("total_cost")
    if cost is None:
        cost = int(u.get("input_tokens") or 0) / 1e6 * 0.25 + int(u.get("output_tokens") or 0) / 1e6 * 2.50 + searches * 0.0025
    return {"answer": "\n".join(text).strip(), "pages": pages, "searches": searches, "cost_usd": round(float(cost), 5), "model": model}


def ask_gemini(q, key, country=None, client=None):
    import gemini_client
    c = client or gemini_client.GeminiClient(api_key=key, model=os.environ.get("GEMINI_SEARCH_MODEL") or gemini_client.DEFAULT_MODEL, pause=0, verbose=False)
    ins = _instructions(country)
    res = c.ask_grounded((ins + "\n\n" + q) if ins else q)
    if not res.get("ok", True) and not res.get("answer"):
        raise RuntimeError(res.get("error") or "no answer")
    pages = []
    for cit in res.get("citations") or []:
        url = cit.get("url") or ""
        title = cit.get("title") or ""
        if "grounding-api-redirect" in url and title and "." in title:
            url = "https://" + title.strip().lower()             # Google hides the page behind a redirect; its title is the site's address
        pages.append({"url": url, "title": title, "cited": True})
    searches = len(res.get("search_queries") or []) or 1
    cost = searches * 0.014 + 0.002                               # searches at the full price (the free 5,000 a month are not counted), plus a small allowance for the text
    return {"answer": (res.get("answer") or "").strip(), "pages": pages, "searches": searches, "cost_usd": round(cost, 5), "model": getattr(c, "model", "gemini")}


class _Http(RuntimeError):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {body}")
        self.status_code = code


ASK = {"chatgpt": ask_chatgpt, "perplexity": ask_perplexity, "gemini": ask_gemini}


def _fatal(e):
    code = getattr(e, "status_code", None)
    return code in (400, 401, 402, 403, 404) or "credit" in str(e).lower() or "billing" in str(e).lower() or "quota" in str(e).lower()


# ----------------------------------------------------------------- the tracked prompts, one assistant

def run_engine(engine, prompts, hotel, city, own_domain="", country=None, key=None, ask=None, budget_left_milli=None, stop_event=None, repeats=REPEATS):
    """Ask one assistant the tracked prompts. -> {"engine", "name", "status": ok|unavailable|not_configured|over_budget, "reason", "items", "summary", "cost_usd", "model"}. Never raises."""
    meta = ENGINES[engine]
    out = {"engine": engine, "name": meta["name"], "maker": meta["maker"], "status": "not_configured", "reason": "", "items": [], "cost_usd": 0.0, "model": None}
    key = key or key_for(engine)
    if not key and ask is None:
        out["reason"] = f"No {meta['maker']} API key is set on the host, so {meta['name']} was not asked."
        return out
    if budget_left_milli is not None and budget_left_milli <= 0:
        out.update(status="over_budget", reason=f"This month's budget for {meta['name']} is used, so it was not asked this time. It resets next month.")
        return out
    ask = ask or ASK[engine]
    own = (own_domain or "").lower()
    own = own[4:] if own.startswith("www.") else own
    qs = []
    for p in prompts[:MAX_PROMPTS]:
        for k in range(repeats):
            qs.append({"id": f"{engine}:{p['id']}" + (f"#{k + 1}" if k else ""), "qid": f"{engine}:{p['id']}", "text": p["text"], "kind": p.get("kind") or "niche", "source": "benchmark",
                       "angle": p.get("angle"), "repeat": k + 1, "repeats": repeats})
    lock = threading.Lock()
    state = {"spent": 0.0, "stop": False, "why": "", "in_a_row": 0, "model": None}

    def one(q):
        with lock:
            if state["stop"] or (stop_event is not None and stop_event.is_set()):
                return None
            if budget_left_milli is not None and state["spent"] * 1000 >= budget_left_milli:
                state["why"] = state["why"] or f"Stopped at this month's budget for {meta['name']}."
                return None
        for attempt in range(3):
            try:
                res = ask(q["text"], key, country=country) if engine != "gemini" else ask(q["text"], key, country=country)
                break
            except Exception as e:  # noqa: BLE001
                if _fatal(e) or attempt == 2:
                    with lock:
                        state["in_a_row"] += 1
                        if _fatal(e) or state["in_a_row"] >= 3:
                            state["stop"] = True
                        state["why"] = state["why"] or f"{meta['name']} did not answer ({str(e)[:120]})."
                    return None
                time.sleep(2 * (attempt + 1))
        with lock:
            state["spent"] += res.get("cost_usd") or 0
            state["in_a_row"] = 0
            state["model"] = res.get("model")
        ans = res.get("answer") or ""
        domains = list(dict.fromkeys(_host(p_["url"]) for p_ in res.get("pages") or [] if p_.get("url")))
        if not ans:
            return {**q, "answer": "", "mentioned": None, "position": None, "domains": domains, "pages": res.get("pages") or [], "searches": res.get("searches", 0), "cost_usd": res.get("cost_usd", 0)}
        return {**q, "answer": ans, "mentioned": ai_sample.mentioned(ans, hotel, city), "recommended": ai_sample.recommended(ans, hotel, city), "position": ai_sample.list_position(ans, hotel),
                "names_hotel": ai_sample._names_hotel(q["text"], hotel, city), "domains": domains, "pages": res.get("pages") or [], "searches": res.get("searches", 0),
                "cost_usd": res.get("cost_usd", 0), "own_site_cited": bool(own and any(d == own or d.endswith("." + own) for d in domains)),
                "platform": f"{meta['name']} ({res.get('model') or meta['maker']} API, with web search)", "tested_on": time.strftime("%Y-%m-%d", time.gmtime())}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        items = [r for r in ex.map(one, qs) if r]
    out.update(items=items, cost_usd=round(state["spent"], 5), model=state["model"])
    if items:
        out["status"], out["reason"] = "ok", state["why"]
    else:
        out["status"], out["reason"] = "unavailable", state["why"] or f"{meta['name']} gave no answers."
    _record(engine, state["spent"])
    return out


def _record(engine, usd):
    if usd and usd > 0:
        try:
            import store
            store.record_usage(max(1, round(usd * 1000)), audits=0, service=service(engine))
        except Exception:  # noqa: BLE001
            pass


def budget_left_milli(engine):
    try:
        import store
        used, _rem, _over = store.quota_status(0, service=service(engine), cap=cap_milli(engine))
        return cap_milli(engine) - used
    except Exception:  # noqa: BLE001
        return cap_milli(engine)


def run_all(prompts, hotel, city, own_domain="", country=None, stop_event=None, progress=None):
    """Every configured assistant, in parallel, on the tracked prompts. -> {engine: result}. Never raises."""
    say = progress or (lambda m: None)
    if not prompts:
        return {}
    out = {}
    todo = [e for e in ENGINES]
    names = ", ".join(ENGINES[e]["name"] for e in todo if key_for(e))
    if names:
        say(f"Asking {names} the hotel's tracked prompts...")

    def go(e):
        return e, run_engine(e, prompts, hotel, city, own_domain=own_domain, country=country, budget_left_milli=budget_left_milli(e) if key_for(e) else None, stop_event=stop_event)
    with ThreadPoolExecutor(max_workers=len(todo)) as ex:
        for e, res in ex.map(go, todo):
            out[e] = res
    return out
