"""
A fallback reader for a hotel's own pages when the site refuses OUR reader (typically a chain's bot protection).

Anthropic's web-fetch tool fetches a page from Anthropic's servers and hands back its text. When our own crawler is
turned away with HTTP 403, we can ask that tool to fetch the hotel's pages instead. The tool identifies itself, respects
robots.txt, and is not disguised as a browser - this is simply a different, openly identified reader. If it is refused
too, we report that and nothing else.

Rules:
  * used only as a FALLBACK, when our own reader got fewer than three pages;
  * only pages inside the hotel's own folder (urlscope), at most MAX_PAGES (default 6);
  * we keep the RAW fetched text (taken from the tool's result blocks, never from the model's summary of it);
  * pages are marked text_only: there is no HTML, so markup, canonical, alt-text and other technical checks are
    NOT assessed from them (the analysis is told, and says so);
  * the report states that the pages were read through Anthropic's page reader.
"""

import re
import urllib.parse

import ai_sample
import guest_questions
import lexicon
import textutil

FETCH_TOOL = "web_fetch_20250910"
MAX_PAGES = 6
SOURCE = "Claude page reader"

ACCESS = (
    "Anthropic's web-fetch tool, used only when the hotel's site refuses this tool's own reader. It fetches pages from Anthropic's servers, identifies "
    "itself and respects robots.txt. Pages come back as plain text, so only what the pages SAY can be checked (questions answered, facts, location, "
    "consistency); markup and other technical details are not assessed. Uses the operator's free Anthropic credit.")

_LINK = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MDLINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TEL = re.compile(r"\+\d[\d\s().-]{4,}\d")
_MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def split_front_matter(text):
    """The reader prepends '--- key: value ---'. -> (dict of those lines, the page text after it)."""
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for ln in text[3:end].splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            return meta, text[end + 4:]
    return meta, text


def to_page(url, text, title=""):
    """One fetched document -> the page dict the rest of the audit already understands, flagged text_only."""
    meta, body = split_front_matter(text or "")
    links = _LINK.findall(body)
    h1 = [ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")][:3]
    plain = _IMG.sub(" ", body)
    plain = _MDLINK.sub(r"\1", plain)
    plain = re.sub(r"(?m)^[#>*\-\s|:]+", " ", plain)
    plain = re.sub(r"[|*_`]+", " ", plain)
    plain = re.sub(r"\s+", " ", textutil.strip_label_runs(plain)).strip()[:30000]
    ok = len(plain) >= guest_questions.MIN_READABLE_CHARS
    return {"url": url, "ok": ok, "reason": "" if ok else "no readable text", "title": title or meta.get("title", "") or (h1[0] if h1 else ""), "h1": h1,
            "text": plain, "footer_text": "", "tels": [t.strip() for t in _TEL.findall(plain)][:5], "mails": sorted(set(_MAIL.findall(plain)))[:5],
            "links": links[:150], "signals": {}, "status": 200, "final_url": url, "text_only": True}


def _fetch(client, model, urls):
    """One request asking the tool to fetch these URLs. -> (list of page dicts, usage tuple). Raises on API failure."""
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    resp = client.messages.create(
        model=model, max_tokens=6000, tools=[{"type": FETCH_TOOL, "name": "web_fetch", "max_uses": len(urls)}],
        messages=[{"role": "user", "content": "Fetch each of these pages so I can read them, then reply with just the word done:\n" + "\n".join(urls)}], **extra)
    pages, got = [], set()
    for b in ai_sample._get(resp, "content", []) or []:
        if ai_sample._get(b, "type") != "web_fetch_tool_result":
            continue
        blk = ai_sample._get(b, "content")
        doc = ai_sample._get(blk, "content")
        if doc is None:                                           # an error object: url_not_accessible and the like
            continue
        url = ai_sample._get(blk, "url", "") or ""
        text = ai_sample._get(ai_sample._get(doc, "source"), "data", "") or ""
        if url and text:
            got.add(url)
            pages.append(to_page(url, text, ai_sample._get(doc, "title", "") or ""))
    for u in urls:
        if u not in got and not any(u.rstrip("/") == g.rstrip("/") for g in got):
            pages.append({"url": u, "ok": False, "reason": "the page reader could not fetch it", "title": "", "h1": [], "text": "", "footer_text": "", "tels": [],
                          "mails": [], "links": [], "signals": {}, "status": None, "final_url": u, "text_only": True})
    _a, _d, _s, tin, tout = ai_sample.parse_response(resp)
    return pages, (tin, tout)


def read_hotel_pages(start_url, *, api_key=None, model=None, client=None, max_pages=MAX_PAGES, progress=None):
    """
    The hotel's page and its most useful sub-pages, read through Anthropic's fetch tool.
    -> {"status": ok|unavailable|not_configured, "reason", "pages": [...], "cost_usd", "model"}. Never raises.
    """
    def out(status, reason="", pages=None, cost=0.0, model_=None):
        return {"source": SOURCE, "status": status, "reason": reason, "access": ACCESS, "pages": pages or [], "cost_usd": round(cost, 5), "model": model_}

    model = model or ai_sample.MODEL_DEFAULT
    if client is None:
        if not api_key:
            return out("not_configured", "No Anthropic API key is configured, so the fallback page reader was not used.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return out("unavailable", f"The Anthropic library could not be started ({type(e).__name__}).")
    say = progress or (lambda m: None)
    cost = 0.0
    try:
        say("The site refused our reader, so trying Anthropic's page reader...")
        first, (tin, tout) = _fetch(client, model, [start_url])
        cost += ai_sample.cost_usd(model, tin, tout, 0)
        home = next((p for p in first if p["ok"]), None)
        if home is None:
            return out("unavailable", "Anthropic's page reader could not read the page either, so the site stays unread.", first, cost, model)
        targets = [u for u in guest_questions.select_pages(start_url, home["links"], [], max_pages=max_pages + 3)
                   if u.rstrip("/") != start_url.rstrip("/")
                   and not lexicon.LEGAL_PAGE.search(urllib.parse.urlparse(u).path) and not lexicon.BOOKING_PAGE.search(urllib.parse.urlparse(u).path)]
        pages = [home]
        if targets:
            say(f"Reading {len(targets)} more of the hotel's pages...")
            more, (tin, tout) = _fetch(client, model, targets[: max_pages - 1])
            cost += ai_sample.cost_usd(model, tin, tout, 0)
            pages += more
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return out("unavailable", ai_sample._reason_for(e), [], cost, model)
    return out("ok", "", pages, cost, model)
