"""
Fact-check what the AI assistant says about the hotel.

Every answer in a check that names the hotel (the tracked prompts, the exploratory questions and the direct 'tell me about this hotel' ones) may also say something about it: "no parking", "has an outdoor
pool", "a 3-star hotel", "closed for refurbishment". A traveller who reads that takes it as true. This module:

  1. takes the passage of each answer that is about THIS hotel (its own paragraph or list entry, never a rival's),
  2. asks a model to list the claims in it on a fixed set of topics, each with the exact words used; a claim whose words are not in the passage is thrown away (nothing is invented),
  3. compares each claim with what the hotel's own website says, using the same facility detection as the rest of the audit.

Verdicts, worded honestly:
  differs    the assistant says the hotel does NOT have something its own website clearly states (or gives another star rating than the website): very likely wrong.
  check      the assistant says the hotel HAS something the pages we read do not mention, or says it is closed or being refurbished: possibly wrong, the hotel should check.
  matches    the assistant and the website agree.
A claim we cannot judge is counted, never called wrong. One assistant, one day: the result says so.
"""

import re

import ai_insights as ains
import ai_sample
import evidence
import insight_content as ic
import lexicon
import review_replies

SOURCE = "What the AI assistant said about the hotel, checked against the hotel's own website"
TOPICS = ("restaurant", "bar", "spa", "pool", "gym", "meeting_rooms", "weddings", "parking", "ev", "pets", "family", "accessible", "airport_transfer", "room_service", "garden")
LABEL = {k: lexicon.FEATURES[k][0] for k in TOPICS if k in lexicon.FEATURES}
LABEL.update({"stars": "Star rating", "status": "Open or closed"})
MAX_SNIPPETS, SNIPPET_CHARS = 30, 700

SYSTEM = ("You list factual claims an AI travel assistant made about ONE hotel. Use only the words in each passage; never add or infer anything. Reply with one JSON object and nothing else.")
PROMPT = '''Target hotel: {hotel}, {city}.

Each passage below is part of an assistant's answer that mentions the target hotel. List the claims it makes about THE TARGET HOTEL ONLY (ignore anything said about other hotels) on these topics:
{topics}
plus "stars" (the star rating it gives the hotel) and "status" (whether the hotel is open, closed, or closed for refurbishment or renovation).

{blocks}

Return JSON: {{"claims": [{{"passage": "P1", "topic": "pool", "stance": "has|lacks|value", "value": "for stars a number 1 to 5, for status open|closed|refurbishment, else empty", "quote": "the exact words from the passage, under 25 words"}}]}}
stance "has" = the passage says the hotel has it; "lacks" = it says the hotel does not have it (no pool, no parking, does not allow dogs); "value" = stars or status. Leave out anything the passage does not state about the target hotel. An empty list is fine.'''


def _fold(s):
    return re.sub(r"\s+", " ", evidence.fold(s or "")).strip()


def passage(answer, hotel):
    """The part of an answer that is about the hotel: from the start of the line that names it to the end of that paragraph or list entry. '' when the answer does not name it."""
    if not answer or not hotel:
        return ""
    i = -1
    for name in (hotel, ains.canon(hotel)):                 # searched in the answer as written (folding would shift the positions)
        n = (name or "").strip()
        if len(n) >= 4:
            m = re.search(r"\s+".join(re.escape(w) for w in n.split()), answer, re.I)
            if m:
                i = m.start()
                break
    if i < 0:
        return ""
    start = answer.rfind("\n", 0, i) + 1
    m = re.search(r"\n\s*\n|\n\s*(?:[-*•]|\d{1,2}[.)])\s+|\n#{1,4}\s", answer[i:])
    end = i + (m.start() if m else len(answer) - i)
    return answer[start:end].strip()[:SNIPPET_CHARS]


def passages(items, hotel):
    """[{id, text}] of the passages about the hotel, one per different passage, the direct questions' whole answers first."""
    out, seen = [], set()
    for it in sorted(items or [], key=lambda x: x.get("kind") != "direct"):
        ans = it.get("answer") or ""
        if not ans:
            continue
        txt = ans.strip()[:1500] if it.get("kind") == "direct" else (passage(ans, hotel) if it.get("mentioned") else "")
        key = _fold(txt)[:200]
        if not txt or key in seen:
            continue
        seen.add(key)
        out.append({"id": f"P{len(out) + 1}", "text": txt, "item": it.get("id")})
        if len(out) >= MAX_SNIPPETS:
            break
    return out


def extract(client, model, snippets, hotel, city):
    """-> ([{topic, stance, value, quote, passage}], (tokens in, tokens out)). Claims whose quote is not in their passage, or on another topic, are dropped."""
    if not snippets:
        return [], (0, 0)
    blocks = "\n\n".join(f"[{s['id']}] {s['text']}" for s in snippets)
    topics = ", ".join(f"{k} ({LABEL[k]})" for k in TOPICS if k in LABEL)
    resp = client.messages.create(model=model, max_tokens=2500, system=SYSTEM, messages=[{"role": "user", "content": PROMPT.format(hotel=hotel, city=city, topics=topics, blocks=blocks)}])
    text, _d, _s, tin, tout = ai_sample.parse_response(resp)
    data = review_replies.parse_json(text)
    by_id = {s["id"]: s for s in snippets}
    out = []
    for c in (data or {}).get("claims") or [] if isinstance(data, dict) else []:
        if not isinstance(c, dict):
            continue
        topic, stance, quote, pid = str(c.get("topic") or ""), str(c.get("stance") or ""), str(c.get("quote") or "").strip(), str(c.get("passage") or "")
        if topic not in LABEL or stance not in ("has", "lacks", "value") or pid not in by_id or len(quote) < 3:
            continue
        if _fold(quote) not in _fold(by_id[pid]["text"]):
            continue                                  # not the passage's own words: never used
        value = str(c.get("value") or "").strip().lower()[:20]
        if topic == "stars" and not re.fullmatch(r"[1-5](?:\.5)?", value):
            continue
        if topic == "status" and value not in ("open", "closed", "refurbishment"):
            continue
        out.append({"topic": topic, "stance": stance, "value": value, "quote": quote[:200], "passage": pid})
    return out, (tin, tout)


def site_facts(own_pages, base, hotel):
    """What the hotel's own pages state, per topic: {topic: {"level": strong|some|none, "url", "snippet"}}. {} when no pages were read."""
    if not own_pages:
        return {}
    site = ic.Site(own_pages, base, hotel, "")
    out = {}
    for f in ic.features(site):
        if f["key"] in LABEL:
            top = f["found"][0] if f["found"] else None
            out[f["key"]] = {"level": f["level"] if f["found"] else "none", "url": top["page"]["url"] if top else "", "snippet": (top or {}).get("snippet", "")[:200] if top else ""}
    return out


def compare(claims, facts, site_stars=None, answers=0):
    """-> {"rows": [{topic, label, status, says, our_record, url, times}], "matches": n, "unjudged": n}. One row per topic and what was said, most serious first."""
    grouped = {}
    for c in claims or []:
        grouped.setdefault((c["topic"], c["stance"], c["value"]), []).append(c)
    rows, matches, unjudged = [], 0, 0
    for (topic, stance, value), cs in grouped.items():
        says, n = cs[0]["quote"], len(cs)
        f = facts.get(topic) or {}
        stated = f.get("level") in ("strong", "some")
        if topic == "status":
            if value in ("closed", "refurbishment"):
                rows.append({"topic": topic, "label": LABEL[topic], "status": "check", "says": says, "times": n, "url": "",
                             "our_record": "Check this at once: if the hotel is open, travellers are being told it is not."})
            else:
                matches += 1
            continue
        if topic == "stars":
            if site_stars and value and abs(float(value) - float(site_stars)) >= 1:
                rows.append({"topic": topic, "label": LABEL[topic], "status": "differs", "says": says, "times": n, "url": "", "our_record": f"The hotel's website says {site_stars:g}-star."})
            elif site_stars and value:
                matches += 1
            else:
                unjudged += 1
            continue
        if not facts:
            unjudged += 1
            continue
        mentioned = f.get("level") in ("strong", "some", "weak")
        if stance == "lacks" and stated:
            rows.append({"topic": topic, "label": LABEL[topic], "status": "differs", "says": says, "times": n, "url": f.get("url", ""),
                         "our_record": "The hotel's website states it" + (f": \"{f['snippet'][:140]}\"" if f.get("snippet") else ".")})
        elif stance == "lacks" and mentioned:
            rows.append({"topic": topic, "label": LABEL[topic], "status": "check", "says": says, "times": n, "url": f.get("url", ""),
                         "our_record": "The hotel's website mentions it once" + (f": \"{f['snippet'][:140]}\"" if f.get("snippet") else "") + ". If the hotel has it, say so more clearly."})
        elif stance == "has" and mentioned:
            matches += 1
        elif stance == "has" and not stated:
            rows.append({"topic": topic, "label": LABEL[topic], "status": "check", "says": says, "times": n, "url": "",
                         "our_record": "Not found on the website pages we read. If the hotel does not have it, guests are being told it does; if it does, the website should say so."})
        elif stance == "has" and stated:
            matches += 1
        else:
            unjudged += 1            # the assistant says the hotel lacks something the website does not mention either: it may well be right
    order = {"differs": 0, "check": 1}
    rows.sort(key=lambda r: (order[r["status"]], r["topic"] != "status", -r["times"]))
    return {"rows": rows, "matches": matches, "unjudged": unjudged, "answers": answers}


def run(ai, hotel, city, own_pages, base, *, site_stars=None, api_key=None, model=None, client=None):
    """The whole check for one audit. Never raises. -> {"source", "status": ok|none|unavailable, "rows", "matches", "unjudged", "passages", "cost_usd", "reason"?}"""
    base_out = {"source": SOURCE, "rows": [], "matches": 0, "unjudged": 0, "passages": 0, "cost_usd": 0.0}
    try:
        snips = passages((ai or {}).get("items"), hotel)
        if not snips:
            return {**base_out, "status": "none", "reason": "No answer in this check said anything about the hotel itself."}
        if client is None:
            if not api_key:
                return {**base_out, "status": "unavailable", "reason": "No AI key is configured."}
            client = ai_sample._make_client(api_key, timeout=90.0)
        model = model or ai_sample.MODEL_DEFAULT
        claims, (tin, tout) = extract(client, model, snips, hotel, city)
        res = compare(claims, site_facts(own_pages, base, hotel), site_stars, answers=len(snips))
        return {**base_out, **res, "status": "ok", "passages": len(snips), "claims": len(claims), "cost_usd": round(ai_sample.cost_usd(model, tin, tout, 0), 5)}
    except Exception as e:  # noqa: BLE001 - an extra; the rest of the audit stands
        return {**base_out, "status": "unavailable", "reason": f"The fact-check did not finish ({type(e).__name__})."}
