"""
An INDICATIVE snapshot of the hotel's public reviews and how its management replies to them.

How: one Claude model with web search is asked to look at the review pages that appear in public search results
(Tripadvisor, Booking.com, Google and similar) and to report ratings, review counts and - the point of this - whether the
hotel replied to each review it could see, by whom (a role, never a name), the reply's tone, and a short paraphrase.

Why it is trustworthy only because of the checking: the model is told to report nothing it did not see, but a model can
still invent. So every item must carry a URL, and any item whose URL was NOT among the pages the search tool actually
returned in this request is dropped (and counted). What survives is "seen in public search results", not "verified by us".

What it is NOT: a response rate. The reviews visible in search results are a small, unrepresentative sample (often the
most recent or most indexed), so the numbers are reported as "replies seen on X of the Y reviews we could examine" and
never as the hotel's reply rate. Nothing here is scored. Reviews are paraphrased, reviewers are not named, and replies are
attributed to a role. The platforms' terms prohibit automated collection by this tool; the searching is done by Anthropic's
search service, which is why this is shown as an AI reading of public search results and not as data collected from the
platforms.
"""

import json
import re
import urllib.parse

import ai_sample

SOURCE = "Reviews and replies (AI reading of public search results)"
MAX_SEARCHES = 6
MAX_TOKENS = 12000          # thinking and the JSON share this; it is a ceiling, not a spend
MAX_ITEMS = 12

ACCESS = (
    "One Claude model with web search reads the review pages that appear in public search results. Every item must carry a link "
    "and is dropped unless that page was in the search results returned for this request. The reviews visible this way are a small, "
    "unrepresentative sample: the figures are replies SEEN on reviews EXAMINED, not the hotel's reply rate. Reviews are paraphrased "
    "and reviewers are not named. The platforms prohibit automated collection by this tool; the searching is done by Anthropic's "
    "search service. Nothing here is scored.")

SYSTEM = (
    "You are a careful research assistant. Search the web for public guest reviews of the named hotel on review platforms (Tripadvisor, "
    "Booking.com, Google, Trustpilot and similar) and look at whether the hotel's management replied to them. Report ONLY what you actually "
    "saw in the search results; if you cannot see something, say so in not_found. Never invent a review, a reply or a number. Paraphrase; do not "
    "copy review or reply text, and do not name reviewers or staff (use a role such as 'General Manager'). Every item needs the exact URL of "
    "the page where you saw it. Reply with one JSON object and nothing else.")

PROMPT = '''Hotel: {hotel}, {city}.

Search for public reviews of this hotel (at least two differently worded searches, including one aimed at reviews with a management response, and one at recent critical reviews). Then return JSON in exactly this shape:

{{
  "platforms": [{{"platform": "Tripadvisor", "rating": 4.0, "review_count": 1234, "url": "https://..."}}],
  "reviews": [
    {{"platform": "Tripadvisor", "url": "https://...", "review_date": "2026-08", "sentiment": "positive|mixed|negative",
      "owner_replied": true, "reply_by": "General Manager", "reply_date": "2026-08",
      "reply_tone": "warm template|specific and engaged|brief|defensive|dismissive",
      "reply_summary": "paraphrase in under 25 words",
      "reply_quality": {{"personal": true, "acknowledges": true, "offers_action": false, "signed": true}},
      "topics": ["breakfast", "noise"]}}
  ],
  "not_found": ["things you looked for and could not find, e.g. Google reviews, replies on Booking.com"]
}}

Rules: at most {max_items} reviews, mixing recent positive and critical ones where you can see them. Use owner_replied: true only when you saw a reply, false when the page shows the review without one, null when you cannot tell from what you saw. Leave rating/review_count null if not seen. reply_quality is about the reply you saw, each flag true/false/null: personal = it refers to specifics of that guest's stay rather than a generic thank-you; acknowledges = it thanks the guest or apologises for what went wrong; offers_action = it says what will be done or invites the guest to get in touch; signed = it is signed by a named role or team. topics = up to three one- or two-word subjects the review is about (for example breakfast, noise, staff, location, cleanliness, parking). JSON only.'''


# ------------------------------------------------------------------ helpers

def norm_url(u):
    """host + path, lowercase, no scheme/www/query/fragment/trailing slash - to compare a cited page with the pages the search returned."""
    p = urllib.parse.urlparse((u or "").strip())
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + (p.path or "").rstrip("/").lower()


def seen_urls(resp_content):
    out = set()
    for b in resp_content or []:
        if ai_sample._get(b, "type") == "web_search_tool_result":
            res = ai_sample._get(b, "content")
            if isinstance(res, list):
                for r in res:
                    n = norm_url(ai_sample._get(r, "url", ""))
                    if n:
                        out.add(n)
    return out


def was_seen(url, seen):
    n = norm_url(url)
    if not n:
        return False
    return n in seen or any((n.startswith(s) or s.startswith(n)) and min(len(n), len(s)) >= 25 for s in seen)


def parse_json(text):
    """The model's JSON, tolerant of a code fence or a stray sentence around it. None when there is no object."""
    if not text:
        return None
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except ValueError:
        return None


_QUALITY = ("personal", "acknowledges", "offers_action", "signed")
_TONES = {"warm template", "specific and engaged", "brief", "defensive", "dismissive"}
_SENT = {"positive", "mixed", "negative"}


def clean_review(r, seen):
    """-> a safe review dict, or None when it is unusable or its page was never in the search results."""
    if not isinstance(r, dict) or not was_seen(r.get("url", ""), seen):
        return None
    replied = r.get("owner_replied")
    replied = replied if isinstance(replied, bool) else None
    tone = r.get("reply_tone") if r.get("reply_tone") in _TONES else None
    summ = re.sub(r"\s+", " ", str(r.get("reply_summary") or "")).strip()[:220]
    q = r.get("reply_quality") if isinstance(r.get("reply_quality"), dict) else {}
    quality = {k: (q.get(k) if isinstance(q.get(k), bool) else None) for k in _QUALITY} if replied else None
    topics = [re.sub(r"[^a-z &-]", "", str(t).lower()).strip()[:24] for t in (r.get("topics") or [])[:3] if isinstance(t, str)]
    return {"platform": str(r.get("platform") or "")[:30], "url": str(r["url"])[:300], "review_date": str(r.get("review_date") or "")[:10],
            "reply_quality": quality, "topics": [t for t in topics if t],
            "sentiment": r.get("sentiment") if r.get("sentiment") in _SENT else None, "owner_replied": replied,
            "reply_by": (str(r.get("reply_by") or "")[:40] or None) if replied else None,
            "reply_date": (str(r.get("reply_date") or "")[:10] or None) if replied else None,
            "reply_tone": tone if replied else None, "reply_summary": summ if replied else ""}


def clean_platform(p, seen):
    if not isinstance(p, dict) or not was_seen(p.get("url", ""), seen):
        return None
    def num(v, lo, hi):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return x if lo <= x <= hi else None
    return {"platform": str(p.get("platform") or "")[:30], "url": str(p["url"])[:300], "rating": num(p.get("rating"), 0, 10),
            "review_count": (int(n) if (n := num(p.get("review_count"), 0, 10_000_000)) is not None else None)}


def summarise(reviews):
    examined = [r for r in reviews if r["owner_replied"] is not None]
    replied = [r for r in examined if r["owner_replied"]]
    neg = [r for r in examined if r["sentiment"] == "negative"]
    neg_replied = [r for r in neg if r["owner_replied"]]
    tones = {}
    for r in replied:
        if r["reply_tone"]:
            tones[r["reply_tone"]] = tones.get(r["reply_tone"], 0) + 1
    quality = {k: {"yes": sum(1 for r in replied if (r.get("reply_quality") or {}).get(k) is True),
                   "judged": sum(1 for r in replied if (r.get("reply_quality") or {}).get(k) is not None)} for k in _QUALITY}
    praised, criticised = {}, {}
    for r in reviews:
        for t in r.get("topics") or []:
            bucket = praised if r["sentiment"] == "positive" else criticised if r["sentiment"] in ("negative", "mixed") else None
            if bucket is not None:
                bucket[t] = bucket.get(t, 0) + 1
    top = lambda d: [{"topic": k, "reviews": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]      # noqa: E731
    return {"reply_quality": quality, "praised": top(praised), "criticised": top(criticised),
            "reviews_seen": len(reviews), "examined": len(examined), "replied": len(replied), "unclear": len(reviews) - len(examined),
            "negative_examined": len(neg), "negative_replied": len(neg_replied), "tones": tones,
            "platforms_with_replies": sorted({r["platform"] for r in replied if r["platform"]})}


def budget_exhausted():
    return {"source": SOURCE, "status": "unavailable", "access": ACCESS, "items": [],
            "reason": "This month's allowance for AI-assisted checks has been used, so reviews and replies were not looked at this time. It resets next month."}


# ---------------------------------------------------------------------- run

def run(hotel, city, *, api_key=None, model=None, client=None, budget_usd=0.25, progress=None):
    def env(status, reason="", **kw):
        return {"source": SOURCE, "status": status, "reason": reason, "access": ACCESS, "items": [], **kw}

    model = model or ai_sample.MODEL_DEFAULT
    if not hotel or not (city or "").strip():
        return env("not_configured", "The hotel's name and town are both needed to look for its reviews, so this was not run.")
    if client is None:
        if not api_key:
            return env("not_configured", "No Anthropic API key is configured, so reviews and replies were not looked at.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return env("unavailable", f"The Anthropic library could not be started ({type(e).__name__}), so this was not run.")
    if progress:
        progress("Looking at public reviews and the hotel's replies...")

    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    messages = [{"role": "user", "content": PROMPT.format(hotel=hotel, city=city.split(",")[0].strip(), max_items=MAX_ITEMS)}]
    seen, text, tin, tout, searches = set(), "", 0, 0, 0
    try:
        for _ in range(3):                                   # a long search can pause; continue it up to twice
            resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[dict(tool)], messages=messages, **extra)
            content = ai_sample._get(resp, "content", []) or []
            seen |= seen_urls(content)
            a, _d, s, i, o = ai_sample.parse_response(resp)
            text, searches, tin, tout = a or text, searches + s, tin + i, tout + o
            if ai_sample._get(resp, "stop_reason") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": content}]
                continue
            break
    except Exception as e:  # noqa: BLE001 - never fail the audit
        return env("unavailable", ai_sample._reason_for(e), model=model)
    cost = ai_sample.cost_usd(model, tin, tout, searches)

    data = parse_json(text)
    if not isinstance(data, dict):
        why = ("The assistant ran out of room before finishing its reading of the review pages, so nothing is shown." if ai_sample._get(resp, "stop_reason") == "max_tokens"
               else "The assistant's reading of the review pages could not be understood, so nothing is shown.")
        return env("unavailable", why, model=model, cost_usd=cost)
    raw_reviews = [r for r in (data.get("reviews") or []) if isinstance(r, dict)][:MAX_ITEMS]
    reviews = [c for c in (clean_review(r, seen) for r in raw_reviews) if c]
    raw_platforms = [p for p in (data.get("platforms") or []) if isinstance(p, dict)][:8]
    platforms = [c for c in (clean_platform(p, seen) for p in raw_platforms) if c]
    dropped = (len(raw_reviews) - len(reviews)) + (len(raw_platforms) - len(platforms))
    not_found = [str(x)[:160] for x in (data.get("not_found") or []) if x][:8]
    if not reviews and not platforms:
        return env("no_results", "No review pages could be confirmed in public search results"
                   + (f" ({dropped} item(s) were dropped because their pages were not among the search results)." if dropped else "."),
                   model=model, cost_usd=cost, not_found=not_found, dropped=dropped)
    return env("ok", "", model=model, cost_usd=cost, platforms=platforms, items=reviews, summary=summarise(reviews), not_found=not_found, dropped=dropped,
               searches=searches, run_at=ai_sample.time.strftime("%Y-%m-%d", ai_sample.time.gmtime()))
