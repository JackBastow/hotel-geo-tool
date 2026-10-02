"""
The manual AI answer check.

This tool deliberately does not call AI assistants itself: grounded AI search
costs real money per request, and every free route to it was verified closed.
What it can do for free is make it easy for a person to run the test
themselves, in whichever assistant they like, and record what happened.

Two kinds of prompt, because they test different things:

    accuracy   "Does <hotel> have on-site parking, and what does it cost?"
               - does the assistant state the hotel's facts correctly?
    discovery  "Suggest hotels in <city> for a family who need parking."
               - does the assistant put the hotel in front of someone who
               hasn't heard of it? (The hotel's name never appears.)

Each recorded answer is ONE sample. An assistant can answer the same prompt
differently tomorrow, with web search on or off, signed in or not. So the
summary reports counts and says when there are too few to mean anything. It
never produces a ranking or a score, and it is kept out of the audit score.
"""

import datetime as dt
import re
import urllib.parse

ASSISTANTS = ["ChatGPT", "Gemini", "Microsoft Copilot", "Claude", "Perplexity",
              "Google AI Mode / AI Overviews", "Other"]
WEB_SEARCH = ["yes", "no", "unknown"]
MENTION = ["recommended", "mentioned", "not_mentioned"]
FACTS = ["all_correct", "some_wrong", "not_stated"]

MENTION_LABEL = {"recommended": "Recommended it", "mentioned": "Mentioned it",
                 "not_mentioned": "Did not mention it"}
FACTS_LABEL = {"all_correct": "Facts all correct", "some_wrong": "Some facts wrong",
               "not_stated": "Didn't state the facts"}

MIN_SAMPLES = 5  # below this, say so rather than draw conclusions
MAX_SOURCES = 15


def build_prompts(hotel, city="", segments=None):
    """
    Prompts tailored to this hotel. `segments` are the hotel types detected
    from its own site (e.g. 'wedding venue', 'spa/wellness hotel'), so the
    discovery prompts match how someone would plausibly search for it.
    """
    h = hotel.strip() or "[hotel name]"
    place = city.strip()
    where = f" in {place}" if place else ""
    prompts = [
        ("acc_parking", "accuracy", "Parking",
         f"Does {h}{where} have on-site parking, and what does it cost?"),
        ("acc_breakfast", "accuracy", "Breakfast",
         f"What time is breakfast at {h}{where}, and is it included in the room rate?"),
        ("acc_times", "accuracy", "Check-in and check-out",
         f"What are the check-in and check-out times at {h}{where}?"),
        ("acc_pets", "accuracy", "Pets",
         f"Does {h}{where} allow dogs?"),
        ("acc_access", "accuracy", "Accessibility",
         f"Does {h}{where} have wheelchair-accessible rooms?"),
        ("acc_about", "accuracy", "General description",
         f"Tell me about {h}{where}: where it is, what facilities it has and who it suits."),
    ]
    if place:
        prompts += [
            ("dis_best", "discovery", "Best hotels",
             f"What are the best hotels in {place}?"),
            ("dis_family", "discovery", "Family with parking",
             f"Suggest hotels in {place} for a family with two children who need parking."),
            ("dis_couples", "discovery", "Romantic weekend",
             f"Suggest a hotel in {place} for a romantic weekend away."),
            ("dis_business", "discovery", "Business travel",
             f"Which hotels in {place} are good for business travellers who need meeting rooms?"),
        ]
        seg = " ".join(segments or []).lower()
        if "wedding" in seg:
            prompts.append(("dis_wedding", "discovery", "Weddings",
                            f"Where can we get married and stay overnight near {place}?"))
        if "spa" in seg:
            prompts.append(("dis_spa", "discovery", "Spa break",
                            f"Which hotels near {place} are best for a spa break?"))
        if "pet" in seg:
            prompts.append(("dis_pets", "discovery", "Dog-friendly",
                            f"What are the best dog-friendly hotels in {place}?"))
    return [{"id": i, "kind": k, "label": l, "prompt": p} for i, k, l, p in prompts]


def _domain(url):
    host = urllib.parse.urlparse(url.strip()).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_sources(text):
    """URLs from free text, http(s) only, de-duplicated, capped."""
    urls = re.findall(r"https?://[^\s<>\"')\]]+", text or "")
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;")
        if u not in seen and _domain(u):
            seen.add(u)
            out.append(u[:300])
    return out[:MAX_SOURCES]


def clean_record(raw, today=None):
    """
    Validate and tidy one record - used for both the form and for records
    inside an uploaded report, which is untrusted input. Unknown choices raise
    ValueError rather than being stored.
    """
    if not isinstance(raw, dict):
        raise ValueError("record is not an object")

    def pick(key, allowed):
        v = str(raw.get(key, "")).strip()
        if v not in allowed:
            raise ValueError(f"{key} must be one of {allowed}")
        return v

    try:
        date = dt.date.fromisoformat(str(raw.get("date", ""))[:10]).isoformat()
    except ValueError:
        date = (today or dt.date.today()).isoformat()
    sources = raw.get("sources", [])
    if isinstance(sources, str):
        sources = parse_sources(sources)
    else:
        sources = parse_sources(" ".join(str(s) for s in list(sources)[:MAX_SOURCES]))
    kind = str(raw.get("kind", "")).strip()
    if kind not in ("accuracy", "discovery"):
        kind = "discovery" if str(raw.get("prompt_id", "")).startswith("dis_") else "accuracy"
    return {
        "assistant": pick("assistant", ASSISTANTS),
        "date": date,
        "kind": kind,
        "prompt_id": str(raw.get("prompt_id", ""))[:40],
        "prompt": str(raw.get("prompt", ""))[:500],
        "web_search": pick("web_search", WEB_SEARCH),
        "mention": pick("mention", MENTION),
        "facts": pick("facts", FACTS),
        "wrong_detail": str(raw.get("wrong_detail", ""))[:1000],
        "sources": sources,
        "notes": str(raw.get("notes", ""))[:1000],
    }


def clean_records(raws):
    """Keep the valid ones from an untrusted list; report how many were dropped."""
    good, dropped = [], 0
    for r in list(raws or [])[:200]:
        try:
            good.append(clean_record(r))
        except ValueError:
            dropped += 1
    return good, dropped


def summarise(records, own_domain=""):
    """
    Counts, not conclusions. Every figure is 'N of M recorded answers'.
    """
    own = _domain(own_domain if "//" in own_domain else f"https://{own_domain}") if own_domain else ""
    n = len(records)
    disc = [r for r in records if r["kind"] == "discovery"]
    acc = [r for r in records if r["kind"] == "accuracy"]

    out = {
        "n": n, "n_discovery": len(disc), "n_accuracy": len(acc),
        "discovery_mentioned": sum(1 for r in disc if r["mention"] != "not_mentioned"),
        "discovery_recommended": sum(1 for r in disc if r["mention"] == "recommended"),
        "accuracy_wrong": [r for r in acc if r["facts"] == "some_wrong"],
        "accuracy_stated": sum(1 for r in acc if r["facts"] != "not_stated"),
        "by_assistant": {}, "cited_domains": [], "own_cited": 0, "answers_with_sources": 0,
        "caveats": [],
    }
    for r in records:
        a = out["by_assistant"].setdefault(r["assistant"], {"n": 0, "mentioned": 0})
        a["n"] += 1
        if r["kind"] == "discovery" and r["mention"] != "not_mentioned":
            a["mentioned"] += 1

    counts = {}
    for r in records:
        if r["sources"]:
            out["answers_with_sources"] += 1
            doms = {_domain(u) for u in r["sources"]}
            if own and any(d == own or d.endswith("." + own) for d in doms):
                out["own_cited"] += 1
            for d in doms:
                counts[d] = counts.get(d, 0) + 1
    out["cited_domains"] = sorted(counts.items(), key=lambda kv: -kv[1])[:10]

    if n == 0:
        return out
    if n < MIN_SAMPLES:
        out["caveats"].append(
            f"Only {n} answer{'s' if n != 1 else ''} recorded. That is too few to "
            f"say anything reliable - an assistant can answer differently tomorrow. "
            f"Treat this as a first look.")
    if len({r["web_search"] for r in records} - {"unknown"}) > 1:
        out["caveats"].append(
            "Some answers had web search on and some off. They behave differently "
            "(search-backed answers can cite current pages), so compare like with like.")
    if len(out["by_assistant"]) == 1:
        out["caveats"].append(
            "Only one assistant tested. Different assistants draw on different sources.")
    if not disc:
        out["caveats"].append(
            "No discovery prompts recorded. Those test whether the hotel is "
            "suggested to someone who has never heard of it.")
    return out
