"""
What the sampled AI answers MEAN: who the assistant recommends instead, which sources it leaned on, how it describes the
hotel, whether what it says is right, and - carefully - why the hotel may not be named.

Built on the answers ai_sample.py already collected (one model, one day, a handful of questions). Nothing here claims to
know that model's reasoning, and nothing is scored. Rules that keep it honest:

  * Names come from an extraction pass over the answer text, and a name is kept only if it really appears in that answer.
  * Counts, shares, ranks and source tables are plain arithmetic on what was extracted.
  * "Is it right?" compares only claims we can check against facts we hold (phone, check-in/out, address); everything
    else is 'cannot check', never 'wrong'.
  * "Why you may not be named" is a set of HYPOTHESES. The model is shown a numbered ledger of evidence (built here, from
    this audit) and may cite only those ids; any hypothesis with no valid id is dropped. It is told it cannot see its own
    reasoning, and the report says so.
  * Every LLM step is optional: if it fails, the arithmetic sections still show and the failure is stated.
"""

import json
import re

import ai_sample
import evidence
import review_replies

SOURCE = "AI answer insights"
MAX_TOKENS = 6000
BATCH = 8                                  # answers per extraction call, so a long set (repeats) never overruns the output cap
EXTRACT_THINKING = {"type": "disabled"}    # confirmed on a stored lost group (THE NICI, run 123): with thinking on, a thinking block used about 4,500 of the 6,000 output tokens and the answer was cut off; with it off the same group read 8 of 8 in 3,400 tokens
RETRY_CALLS = 24                           # extra calls a whole check may spend on splitting groups that could not be read: bounded, so a bad day cannot run up the bill
SENTIMENTS = ("positive", "neutral", "negative")

# ------------------------------------------------------------------- sources

_DOMAIN_KINDS = [
    ("Booking and comparison site", ("booking.com", "expedia.", "hotels.com", "agoda.", "trivago.", "kayak.", "trip.com", "lastminute.", "laterooms.", "hotelscombined.",
                                     "tablethotels.", "momondo.", "skyscanner.", "traveloka.", "priceline.", "orbitz.", "cheaptickets.", "zenhotels.", "cozycozy.",
                                     "hotelplanner.", "travelmyth.", "hotelguru", "thehotelguru.", "hotels-in-", "easemytrip.", "makemytrip.", "ebookers.", "opodo.")),
    ("Review site", ("tripadvisor.", "trustpilot.", "yelp.", "google.com", "holidaycheck.", "cylex.")),
    ("Social and forum", ("facebook.", "instagram.", "youtube.", "reddit.", "tiktok.", "x.com", "twitter.", "pinterest.", "linkedin.", "tumblr.")),
    ("Reference and maps", ("wikipedia.", "wikidata.", "openstreetmap.", "wikivoyage.", "britannica.")),
    ("Tourism board", ("visit", "tourism", "tourist", "lonelyplanet.", "ontourism")),
    ("Travel media", ("travelweekly.", "telegraph.", "guardian.", "timeout.", "cntraveler.", "forbes.", "bbc.", "independent.", "thetimes.", "travelandleisure.",
                      "fodors.", "frommers.", "luxtimes.", "premium-flights.", "world-adventurer.")),
]
_PLATFORM_OF = {"booking.com": "Booking.com", "expedia.": "Expedia", "hotels.com": "Hotels.com", "tripadvisor.": "TripAdvisor", "trivago.": "Trivago", "agoda.": "Agoda",
                "trip.com": "Trip.com", "kayak.": "Kayak", "lastminute.": "lastminute.com", "hotelscombined.": "HotelsCombined", "trustpilot.": "Trustpilot"}


def source_kind(domain, own_domain="", brand_domains=()):
    d = (domain or "").lower()
    own = (own_domain or "").lower()
    if own and (d == own or d.endswith("." + own)):
        return "The hotel's own website"
    if any(d == b or d.endswith("." + b) for b in brand_domains):
        return "The hotel's brand website"
    import sourcetypes
    wk = sourcetypes.web_kind(d)                       # one definition of each kind of site for the whole report (destinationwellknown.com is a blog, not a tourism body)
    if wk:
        return {"ota": "Booking and comparison site", "review": "Review site", "tourism": "Tourism board", "editorial": "Travel media", "blog": "Travel blog"}[wk]
    for kind, pats in _DOMAIN_KINDS:
        if kind == "Tourism board":
            continue                                   # 'visit' or 'tourist' anywhere in a name is not a tourism body: web_kind decides
        if any(p in d for p in pats):
            return kind
    return "Other"


def _platform(domain):
    d = (domain or "").lower()
    return next((v for k, v in _PLATFORM_OF.items() if k in d), None)


def source_table(items, footprint, entities, own_domain="", brand_domains=()):
    """Which sites the assistant leaned on, how often, and whether the hotel is evidenced on each (from this audit's own lookups)."""
    counts, qs = {}, {}
    for i in items:
        for d in i.get("domains", []):
            counts[d] = counts.get(d, 0) + 1
            qs.setdefault(d, set()).add(i["id"])
    found = {r["platform"]: bool(r.get("discovered")) for r in (footprint or []) if r.get("platform")}
    wiki = next((e for e in entities or [] if e.get("source") == "Wikidata"), None)
    osm = next((e for e in entities or [] if e.get("source") == "OpenStreetMap"), None)
    rows = []
    for d, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        kind = source_kind(d, own_domain, brand_domains)
        plat = _platform(d)
        if kind in ("The hotel's own website", "The hotel's brand website"):
            present = True
        elif plat and plat in found:
            present = found[plat]
        elif "wikipedia" in d or "wikidata" in d:
            present = None if wiki is None else bool(wiki.get("found") and wiki.get("match_confident"))
        elif "openstreetmap" in d:
            present = None if osm is None else bool(osm.get("found") and osm.get("match_confident"))
        else:
            present = None
        rows.append({"domain": d, "kind": kind, "answers": n, "questions": sorted(qs[d]), "hotel_evidenced": present})
    return rows


# --------------------------------------------------------------- name handling

def canon(name):
    """A hotel's identity for counting: lower-case, accents folded, generic words dropped ('Oatlands Park Hotel' = 'Oatlands Park')."""
    base = re.sub(r"\s*\([^)]*\)", " ", name or "")                  # a brand or district in brackets does not make another hotel: 'Hôtel du Louvre (Unbound Collection by Hyatt)' = 'Hôtel du Louvre'
    toks = [t for t in re.split(r"[^a-z0-9]+", evidence.fold(base)) if t and t not in ai_sample._GENERIC]
    return " ".join(toks)


def appears(name, answer):
    c = canon(name)
    text = evidence.fold(answer).replace("&", " ")
    return (bool(c) and c in text) or evidence.fold(name) in evidence.fold(answer)


# ------------------------------------------------------------ LLM: extraction

# the reasons an assistant gives for recommending a hotel, as a fixed list, so the reasons for different hotels in different answers can be counted and compared with what the hotel's own pages say
THEMES = {"location": "close to a named landmark, area, station or attraction", "views_terrace": "a rooftop, terrace, garden or views", "spa_wellness": "a spa, pool, gym or wellness",
          "meetings_events": "meeting rooms, conferences or events", "dining": "a restaurant, bar or food", "design_style": "design, boutique or stylish character", "luxury_service": "luxury, service or an exclusive feel",
          "value": "price, value or affordability", "family": "family-friendly", "rating_reviews": "high ratings or good reviews", "awards": "awards or recognition", "transport_access": "easy transport links or airport access",
          "quiet_historic": "quiet, historic or characterful", "sustainability": "sustainability or eco credentials", "pets_accessibility": "pet-friendly or accessible", "breakfast": "breakfast"}
THEMES_TEXT = "; ".join(f"{k} = {v}" for k, v in THEMES.items())

EXTRACT_SYSTEM = ("You extract structured facts from answers a travel assistant gave. Use ONLY what is written in each answer; never add anything. "
                  "Reply with one JSON object and nothing else.")

EXTRACT_PROMPT = '''Target hotel: {hotel}, {city}.

Below are an assistant's answers, each with an id. For every answer return the hotels it recommends or compares, in the order given, with a short paraphrase of why (under 15 words), any rating it states, and the sentiment the answer expresses toward THAT hotel (positive = recommends or praises it, negative = warns against it or lists mainly drawbacks, neutral = just lists or describes it).
For the answers that are ABOUT the target hotel (ids: {about_ids}) also return how it describes the hotel.

{blocks}

Return JSON in exactly this shape:
{{
  "answers": [{{"id": "best", "hotels": [{{"name": "as written", "rank": 1, "reason": "paraphrase", "rating": "e.g. 8.6 on Booking.com or null", "sentiment": "positive|neutral|negative", "stars": 4, "town": "Olten", "themes": ["location"]}}]}}],
  "about": {{"tone": "positive|mixed|negative|unclear",
            "strengths": ["short phrases the assistant gives as positives"], "weaknesses": ["short phrases the assistant gives as drawbacks"],
            "claims": [{{"type": "phone|address|check_in|check_out|star_rating|parking|pets|other", "value": "exactly as stated", "answer_id": "about"}}]}}
}}
Use an empty list where nothing applies. rank is the position in the answer's list (1 first), or null if the answer is not a list.
town is the town or city the answer places THAT hotel in, as written in the answer, or null when the answer does not say: never guess it.
stars is the star rating the answer gives for THAT hotel (a number from 1 to 5), or null when the answer gives none: never guess it. themes are the reasons the answer gives for recommending THAT hotel, chosen ONLY from this list: {themes}.'''


def _blocks(items):
    return "\n\n".join(f"[{i['id']}] ({i['kind']}) Question: {i['text']}\nAnswer: {(i.get('answer') or '')[:1800]}" for i in items if i.get("answer"))


def _salvage(text):
    """The complete answers of a reply that was cut off or damaged part-way: {"answers": [...complete answer objects...], "about": {}, "salvaged": True}, or None when there are none.
    The answers come first in the reply, so a cut-off reply still holds the ones written before the cut."""
    text = text or ""
    i = text.find('"answers"')
    j = text.find("[", i) if i >= 0 else -1
    if j < 0:
        return None
    dec, k, out = json.JSONDecoder(), j + 1, []
    while True:
        while k < len(text) and text[k] in " \r\n\t,":
            k += 1
        if k >= len(text) or text[k] != "{":
            break
        try:
            obj, k = dec.raw_decode(text, k)
        except ValueError:
            break
        if isinstance(obj, dict) and obj.get("id"):
            out.append(obj)
    return {"answers": out, "about": {}, "salvaged": True} if out else None


def _extract_batch(client, model, batch, hotel, city, diag=None, max_tokens=None, thinking=None):
    """One call for up to BATCH answers -> (parsed dict | None, (tin, tout)). `diag` (a dict), when given, is filled with why the reply was or was not usable: the stop reason, the tokens,
    the kinds of block it held, and how it parsed (ok / salvaged / unreadable / empty)."""
    about_ids = [i["id"] for i in batch if i["kind"] == "direct"]
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    if thinking or EXTRACT_THINKING:
        extra["thinking"] = thinking or EXTRACT_THINKING
    msg = [{"role": "user", "content": EXTRACT_PROMPT.format(hotel=hotel, city=city, about_ids=", ".join(about_ids) or "none", blocks=_blocks(batch), themes=THEMES_TEXT)}]
    try:
        resp = client.messages.create(model=model, max_tokens=max_tokens or MAX_TOKENS, system=EXTRACT_SYSTEM, messages=msg, **extra)
    except Exception as e:  # noqa: BLE001
        if "thinking" not in extra or "thinking" not in str(e).lower():
            raise
        extra.pop("thinking")                              # a model that does not accept the setting is asked without it
        if diag is not None:
            diag["thinking_setting_refused"] = True
        resp = client.messages.create(model=model, max_tokens=max_tokens or MAX_TOKENS, system=EXTRACT_SYSTEM, messages=msg, **extra)
    text, _d, _s, tin, tout = ai_sample.parse_response(resp)
    data = review_replies.parse_json(text)
    state = "ok" if isinstance(data, dict) else ("empty" if not text else "unreadable")
    if state != "ok":
        data = _salvage(text)
        if data:
            state = "salvaged"
    if diag is not None:
        diag.update(stop_reason=str(ai_sample._get(resp, "stop_reason") or ""), in_tokens=tin, out_tokens=tout, reply_chars=len(text or ""), parse=state,
                    blocks=[str(ai_sample._get(b, "type") or "") for b in (ai_sample._get(resp, "content", []) or [])][:6], tail=(text or "")[-120:] if state != "ok" else "", head=(text or "")[:200] if state != "ok" else "")
    return (data if isinstance(data, dict) else None), (tin, tout)


def _why_failed(diag):
    """A plain reason an answer could not be read, from the last call that tried it."""
    if diag.get("error"):
        return "the request failed (" + diag["error"][:80] + ")"
    if diag.get("stop_reason") == "max_tokens":
        return "the reply was cut off at the output limit"
    if diag.get("parse") in ("unreadable", "empty"):
        return "the reply was not valid JSON"
    return "the assistant left it out of its reply"


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_STAR = re.compile(r"(\d|one|two|three|four|five)[\s-]?(?:star|stars|\*|\u00e9toiles?)\b|(\d)\*", re.I)


def _star_near(answer, name, stars):
    """Does the answer give this star rating right beside THIS hotel's name (the rest of its line or sentence)? A rating given for another hotel in the same answer does not count."""
    low = evidence.fold(answer)
    i = low.find(evidence.fold(name))
    if i < 0:
        i = low.find(canon(name))
    if i < 0:
        return False
    end = re.search(r"(?<=[.!?])\s|\s\d{1,2}\.\s|\n", answer[i + len(name):])
    stop = i + len(name) + (end.start() if end else 160)
    for m in _STAR.finditer(answer[max(0, i - 20): stop]):
        v = (m.group(1) or m.group(2) or "").lower()
        if (int(v) if v.isdigit() else _WORDS.get(v)) == stars:
            return True
    return False


def extract(client, model, items, hotel, city, retry_calls=RETRY_CALLS, log=None):
    """
    -> (validated dict | None, usage). Names are kept only if they appear in that answer's own text. The answers about the hotel go first, in one batch.
    A group of answers whose reply could not be read is split in half and asked again (at most `retry_calls` extra calls in all), so one bad answer costs itself and not its seven neighbours, and
    a reply that was cut off still gives the answers written before the cut. What happened is recorded in `log` (and in the result's "extraction"): calls, why each failed, what was recovered.
    """
    by_id = {i["id"]: i for i in items if i.get("answer")}
    if not by_id:
        return None, (0, 0)
    ordered = sorted(by_id.values(), key=lambda i: i["kind"] != "direct")
    pending = [(ordered[k:k + BATCH], False) for k in range(0, len(ordered), BATCH)]
    got, failed, calls_log, data_about, tin, tout = {}, {}, [], {}, 0, 0
    spent = good_calls = 0
    while pending:
        batch, is_retry = pending.pop(0)
        ids = [i["id"] for i in batch]
        if is_retry:
            if spent >= retry_calls:
                for i in ids:
                    failed.setdefault(i, "the limit on repeat attempts was reached")
                calls_log.append({"n": len(batch), "retry": True, "parse": "not_asked", "recovered": 0, "missing": len(ids)})
                continue
            spent += 1
        diag = {"n": len(batch), "retry": is_retry}
        try:
            d, (a, b) = _extract_batch(client, model, batch, hotel, city, diag)
        except Exception as e:  # noqa: BLE001
            if not good_calls and not got:
                raise                                       # nothing has worked yet: the caller states the cause (a bad key, no credit)
            d, (a, b) = None, (0, 0)
            diag.update(parse="error", error=f"{type(e).__name__}: {str(e)[:100]}", stop_reason="")
        tin, tout = tin + a, tout + b
        want = set(ids)
        rows = [x for x in ((d or {}).get("answers") or []) if isinstance(x, dict) and x.get("id") in want]
        for x in rows:
            got.setdefault(x["id"], x)
        if d is not None:
            good_calls += 1
            if isinstance(d.get("about"), dict) and d["about"] and not data_about:
                data_about = d["about"]
        missing = [i for i in batch if i["id"] not in got and not (i["kind"] == "direct" and data_about)]      # the hotel's own description is returned as `about`, so it need not also be listed as an answer
        diag.update(recovered=len({x["id"] for x in rows}), missing=len(missing))
        calls_log.append(diag)
        need_about = [i for i in batch if i["kind"] == "direct" and not data_about and i["id"] in got]
        if need_about and not is_retry:
            pending.insert(0, (need_about, True))           # the description of the hotel comes last in a reply, so a cut-off reply loses it: ask for it again
        if not missing:
            continue
        if len(batch) == 1:
            failed[ids[0]] = _why_failed(diag)
        elif rows:
            pending.insert(0, (missing, True))             # part of the reply was good: ask only for what is missing, together
        else:
            h = (len(missing) + 1) // 2                    # nothing usable came back: halve the group, so a single bad answer is found and the rest are read
            pending[0:0] = [(missing[:h], True), (missing[h:], True)]
    answers_raw = list(got.values())
    failed_ids = list(failed)
    reasons = {}
    for r in failed.values():
        reasons[r] = reasons.get(r, 0) + 1
    summary = {"eligible": len(by_id), "analysed": len(got), "unprocessed": len(failed_ids), "unprocessed_ids": failed_ids[:60], "reasons": reasons, "calls": len(calls_log), "retry_calls": spent,
               "retry_limit": retry_calls, "salvaged_replies": sum(1 for c in calls_log if c.get("parse") == "salvaged"), "cut_off_replies": sum(1 for c in calls_log if c.get("stop_reason") == "max_tokens"),
               "unreadable_replies": sum(1 for c in calls_log if c.get("parse") in ("unreadable", "empty")), "batch_size": BATCH, "max_tokens": MAX_TOKENS,
               "recovered_on_retry": sum(c.get("recovered", 0) for c in calls_log if c.get("retry")),
               "calls_detail": [{k: v for k, v in c.items() if k not in ("tail", "head")} for c in calls_log][:40],
               "failure_samples": [{"head": c.get("head", ""), "tail": c["tail"], "stop_reason": c.get("stop_reason"), "out_tokens": c.get("out_tokens")} for c in calls_log if c.get("tail") or c.get("head")][:3]}
    if log is not None:
        log.update(summary)
    if not got:
        return None, (tin, tout)
    data = {"answers": answers_raw, "about": data_about}
    answers = {}
    for a in data.get("answers") or []:
        if not isinstance(a, dict) or a.get("id") not in by_id:
            continue
        keep, seen = [], set()
        for h in (a.get("hotels") or [])[:12]:
            if not isinstance(h, dict):
                continue
            nm = re.sub(r"\s+", " ", str(h.get("name") or "")).strip()[:80]
            if not nm or canon(nm) in seen or not appears(nm, by_id[a["id"]]["answer"]):
                continue                                    # a name the answer never contained is an invention: dropped
            seen.add(canon(nm))
            rank = h.get("rank")
            sent = str(h.get("sentiment") or "").strip().lower()
            stars = h.get("stars")
            stars = int(stars) if str(stars).strip().isdigit() and 1 <= int(str(stars).strip()) <= 5 else None
            if stars and not _star_near(by_id[a["id"]]["answer"], nm, stars):
                stars = None                                   # a star rating the answer does not give for THIS hotel is an invention
            themes = [t for t in (h.get("themes") or []) if t in THEMES][:5]
            town = re.sub(r"\s+", " ", str(h.get("town") or "")).strip()[:60]
            if town.lower() in ("null", "none") or (town and evidence.fold(town) not in evidence.fold(by_id[a["id"]]["answer"])):
                town = ""                                      # a town the answer never wrote is an invention
            keep.append({"name": nm, "stars": stars, "themes": themes, "town": town or None, "rank": rank if isinstance(rank, int) and 1 <= rank <= 30 else None, "sentiment": sent if sent in SENTIMENTS else "neutral",
                         "reason": re.sub(r"\s+", " ", str(h.get("reason") or "")).strip()[:140],
                         "rating": (str(h.get("rating"))[:40] if h.get("rating") not in (None, "null", "") else None)})
        answers[a["id"]] = keep
    ab = data.get("about") if isinstance(data.get("about"), dict) else {}
    clean = lambda xs: [re.sub(r"\s+", " ", str(x)).strip()[:90] for x in (xs or []) if x][:8]      # noqa: E731
    claims = []
    for c in (ab.get("claims") or [])[:12]:
        if isinstance(c, dict) and c.get("type") in ("phone", "address", "check_in", "check_out", "star_rating", "parking", "pets", "other") and c.get("value"):
            claims.append({"type": c["type"], "value": str(c["value"])[:120], "answer_id": str(c.get("answer_id") or "")[:20]})
    about = {"tone": ab.get("tone") if ab.get("tone") in ("positive", "mixed", "negative", "unclear") else "unclear",
             "strengths": clean(ab.get("strengths")), "weaknesses": clean(ab.get("weaknesses")), "claims": claims}
    return {"answers": answers, "about": about, "failed_ids": failed_ids, "failed": failed, "extraction": summary}, (tin, tout)


# ------------------------------------------------------------ arithmetic

def sentiment_of(labels):
    """positive / neutral / negative counts and the net sentiment score (% positive minus % negative, -100..+100); None when there is nothing to judge."""
    labels = [x for x in labels if x in SENTIMENTS]
    n = len(labels)
    pos, neg = labels.count("positive"), labels.count("negative")
    return {"positive": pos, "neutral": labels.count("neutral"), "negative": neg, "sentiment": round(100 * (pos - neg) / n) if n else None}


def sentiment_label(v):
    """A plain word for a net sentiment score."""
    if v is None:
        return "not judged"
    return "positive" if v >= 30 else "negative" if v <= -30 else "mixed" if abs(v) >= 1 else "neutral"


SIBLING_WORDS = {"airport", "garden", "express", "centre", "center", "city", "suites", "hampton", "doubletree", "conrad", "embassy", "curio", "tapestry", "homewood", "canopy"}


def _sibling(name, hotel):
    """Another property of the same brand: it carries a word that marks a different hotel ('Airport', 'City Centre', 'Garden Inn', 'Hampton') that the hotel's own name does not have."""
    own = set(re.findall(r"[a-z]+", evidence.fold(hotel)))
    return any(w in SIBLING_WORDS and w not in own for w in re.findall(r"[a-z]+", evidence.fold(name)))


def brand_ranking(lbs, hotel, top=5):
    """
    Otterly-style 'brand ranking': the hotel plus the `top` hotels the assistant named most, by how many answers named each, with coverage %, average
    position and net sentiment. lbs = the leaderboards to combine (town-wide, niche). Counts are answers in this one sample, not a market ranking.
    """
    rows, asked = {}, 0
    for lb in lbs:
        if not lb:
            continue
        asked += lb["questions"]
        for r in lb["rows"]:
            k = r.get("key") or canon(r["name"])
            a = rows.setdefault(k, {"name": r["name"], "is_target": r["is_target"], "mentions": 0, "ranks": [], "sent": []})
            a["mentions"] += r["mentions"]
            a["is_target"] = a["is_target"] or r["is_target"]
            a["ranks"] += [r["avg_rank"]] * r["mentions"] if r["avg_rank"] else []
            a["sent"] += ["positive"] * r["positive"] + ["neutral"] * r["neutral"] + ["negative"] * r["negative"]
    tg = [k for k, a in rows.items() if a["is_target"]]
    if len(tg) > 1:                  # the hotel written two ways ('Brooklands Hotel', 'Brooklands Hotel & Spa, Weybridge') is ONE hotel: one line, not three
        keep = max(tg, key=lambda k: rows[k]["mentions"])
        base = rows[keep]
        for k in tg:
            if k != keep:
                b = rows.pop(k)
                base["mentions"] = max(base["mentions"], b["mentions"])        # one answer can name the hotel under two spellings, so the counts are never added
                base["ranks"] += b["ranks"]
                base["sent"] += b["sent"]
        base["name"] = hotel
    out = []
    for a in rows.values():
        out.append({"name": a["name"], "is_target": a["is_target"], "mentions": a["mentions"], "of": asked, "coverage_pct": round(100 * min(a["mentions"], asked) / asked) if asked else 0,
                    "avg_rank": round(sum(a["ranks"]) / len(a["ranks"]), 1) if a["ranks"] else None, **sentiment_of(a["sent"])})
    out.sort(key=lambda r: (-r["mentions"], r["avg_rank"] or 99, r["name"]))
    me = next((r for r in out if r["is_target"]), None)
    rivals = [r for r in out if not r["is_target"]][:top]
    table = ([me] if me else []) + rivals
    for k, r in enumerate(sorted(table, key=lambda r: (-r["mentions"], r["avg_rank"] or 99, r["name"])), 1):
        r["place"] = k
    table.sort(key=lambda r: r["place"])
    return {"rows": table, "all": out, "asked": asked}


def page_table(items, hotel, rivals=(), own_domain="", limit=25):
    """
    The exact pages the assistant cited or searched, across all answers: [{url, domain, title, answers, cited, names_hotel, names_competitor, own_site, passage}].
    'names_hotel' / 'names_competitor' are judged only from the page title and the short passage the assistant quoted from it (we do not read the page),
    so False means 'not visible in what we hold', not 'the page does not mention it'.
    """
    pages = {}
    own = (own_domain or "").lower().removeprefix("www.")
    for it in items:
        for pg in it.get("pages") or []:
            u = pg.get("url") or ""
            if not u:
                continue
            r = pages.setdefault(u, {"url": u, "domain": re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower(),
                                     "title": pg.get("title") or "", "answers": set(), "cited": 0, "passage": "", "kinds": set()})
            r["answers"].add(it.get("qid") or it["id"])
            r["kinds"].add(it["kind"])
            if pg.get("cited"):
                r["cited"] += 1
                r["passage"] = r["passage"] or pg.get("cited_text") or ""
            r["title"] = r["title"] or pg.get("title") or ""
    out = []
    for r in pages.values():
        seen = f"{r['title']} {r['passage']} {r['url']}"
        rival = next((n for n in rivals if n and appears(n, seen)), None)
        d = r["domain"]
        out.append({"url": r["url"], "domain": d, "title": r["title"][:120], "questions": len(r["answers"]), "cited": r["cited"], "passage": r["passage"][:200],
                    "names_hotel": ai_sample.mentioned(seen, hotel), "names_competitor": rival, "own_site": bool(own and (d == own or d.endswith("." + own)))})
    out.sort(key=lambda r: (-r["cited"], -r["questions"], r["domain"], r["url"]))
    return out[:limit]


def own_site_reliance(items, pages):
    """
    How often the hotel's OWN website was among the sources behind the answers to the town and market questions, and which other sites were relied on instead.
    If the answer is not on the hotel's own site in plain language, the assistant finds it elsewhere and cites elsewhere.
    """
    asked = [i for i in items if i.get("kind") in ("generic", "niche") and i.get("answer")]
    own = [i for i in asked if i.get("own_site_cited")]
    other = {}
    for p in pages or []:
        if not p.get("own_site") and p.get("cited"):
            other[p["domain"]] = other.get(p["domain"], 0) + p["cited"]
    return {"answers": len(asked), "own_cited": len(own), "instead": [{"domain": d, "cited": n} for d, n in sorted(other.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]}


def question_rows(items, extracted, resolver=None):
    """One row per QUESTION (repeats merged): whether the hotel was named and in how many of the answers, the best position, and the hotels named."""
    out = []
    for g in ai_sample.by_question(items):
        names, seen = [], set()
        for a in g["answers"]:
            for h in (extracted["answers"].get(a["id"]) or []):
                if resolver and resolver.is_ambiguous(h["name"]):
                    continue
                k = resolver.key(h["name"]) if resolver else canon(h["name"])
                if k not in seen:
                    seen.add(k)
                    names.append(resolver.display(h["name"]) if resolver else h["name"])
        out.append({"id": g["qid"], "kind": g["kind"], "question": g["text"], "angle": g["angle"], "why": g["why"], "named": g["named"], "of": g["of"],
                    "hotel_named": g["named"] > 0, "position": g["best_position"], "hotels_named": names[:6], "answer_ids": [a["id"] for a in g["answers"]]})
    return out


def _resolver_for(hotel, extracted, resolver=None, city=""):
    import hotel_identity
    return resolver or hotel_identity.resolver_for(hotel, city, (extracted or {}).get("answers"))


def leaderboard(extracted, items, hotel, kinds=("generic",), resolver=None):
    """
    Who is named most across the GENERIC questions (or the niche ones), with the hotel in the same table (a row of zeros if it is never named).
    Every name goes through ONE resolver (hotel_identity.py): the hotel under any verified spelling is one row, the same rival written two ways is one row, and a name that merely looks
    alike (a self-catering block, a villa, 'Terminal 5') is its own row. An answer that names a hotel under two spellings counts once.
    """
    res = _resolver_for(hotel, extracted, resolver)
    failed = set(extracted.get("failed_ids") or [])
    gen_ids = [i["id"] for i in items if i["kind"] in kinds and i.get("answer") and i["id"] not in failed]     # an answer the analysis could not read is not an answer that named nobody
    rows, total, amb = {}, 0, set()
    for qid in gen_ids:
        counted, best = set(), {}
        for h in (extracted["answers"].get(qid) or []):
            if res.is_ambiguous(h["name"]):
                amb.add(qid)                  # the group's name alone: possibly this hotel, possibly a sister hotel: not counted either way
                continue
            k = res.key(h["name"])
            r = rows.setdefault(k, {"name": res.display(h["name"]), "key": k, "mentions": 0, "ranks": [], "questions": [], "reasons": [], "ratings": [], "sent": [], "spellings": {}})
            r["spellings"][h["name"]] = r["spellings"].get(h["name"], 0) + 1
            if k not in counted:
                counted.add(k)
                r["mentions"] += 1
                total += 1
                r["sent"].append(h.get("sentiment") or "neutral")
                r["questions"].append(qid)
            if h["rank"]:
                best[k] = min(best.get(k, 99), h["rank"])
            if h["reason"] and h["reason"] not in r["reasons"]:
                r["reasons"].append(h["reason"])
            if h["rating"] and h["rating"] not in r["ratings"]:
                r["ratings"].append(h["rating"])
        for k, rk in best.items():
            rows[k]["ranks"].append(rk)
    out = []
    for r in rows.values():
        out.append({"name": r["name"], "key": r["key"], "is_target": r["key"] == res.SELF, "mentions": r["mentions"], "of": len(gen_ids),
                    "share": round(100 * r["mentions"] / total) if total else 0, "best_rank": min(r["ranks"]) if r["ranks"] else None,
                    "avg_rank": round(sum(r["ranks"]) / len(r["ranks"]), 1) if r["ranks"] else None, "questions": r["questions"],
                    "reasons": r["reasons"][:2], "ratings": r["ratings"][:2], "coverage_pct": round(100 * len(set(r["questions"])) / len(gen_ids)) if gen_ids else 0,
                    "spellings": sorted(r["spellings"], key=lambda n: (-r["spellings"][n], n))[:8], **sentiment_of(r["sent"])})
    out.sort(key=lambda r: (-r["mentions"], r["avg_rank"] or 99, r["name"]))
    if not any(r["is_target"] for r in out):
        out.append({"name": (res.ident or {}).get("canonical") or hotel, "key": res.SELF, "is_target": True, "mentions": 0, "of": len(gen_ids), "share": 0, "best_rank": None, "avg_rank": None,
                    "questions": [], "reasons": [], "ratings": [], "coverage_pct": 0, "spellings": [], **sentiment_of([])})
    return {"rows": out, "questions": len(gen_ids), "total_mentions": total, "ambiguous_answers": len(amb)}


def reconcile(ai, extracted, hotel, resolver=None):
    """
    One answer to 'did this answer name the hotel?' for the whole report. The quick text match (ai_sample.mentioned) and the reading of each answer (the hotels it lists) can disagree, for example
    on 'The Nici' for 'THE NICI Newquay'; then one page said 9 of 24 and another 6 of 24. An answer counts as naming the hotel when either finds the hotel itself (never a sister property of
    the same brand), and the sample's summary is recounted from that, so every figure in the report comes from the same marks. -> number of answers changed.
    """
    import ai_sample
    if not ai or ai.get("status") != "ok" or not extracted:
        return 0
    res = _resolver_for(hotel, extracted, resolver)
    answers = extracted.get("answers") or {}
    n = 0
    for it in ai.get("items") or []:
        if it.get("mentioned") or it.get("kind") == "direct":
            continue
        for h in answers.get(it["id"]) or []:
            if res.is_target(h.get("name", "")):
                it["mentioned"] = True
                it["position"] = it.get("position") or h.get("rank")
                if it.get("position"):
                    it["recommended"] = True                 # a line of the assistant's own list of suggestions is a recommendation, as it is for a text match
                it["reconciled"] = True
                n += 1
                break
    if n:
        ai["summary"] = ai_sample.summarise(ai["items"])
    return n


def alternatives(extracted, hotel, resolver=None):
    """The set the assistant offers when asked what is similar - its view of the competitive set."""
    res = _resolver_for(hotel, extracted, resolver)
    return [h for h in (extracted["answers"].get("similar") or []) if not res.is_target(h["name"])]


# ------------------------------------------------- is what it says correct?

def _digits(s):
    return re.sub(r"\D", "", s or "")


def _time(s):
    m = re.search(r"(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm)?", (s or "").lower())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if 0 <= h < 24 else None


def accuracy(claims, known):
    """
    Compare what the assistant said with facts we hold. `known` = {"phones": [...], "check_in": "15:00", "check_out": "12:00", "address": "...", "address_source": ""}.
    Only the claim types we can really check are judged; the rest are counted as 'could not check', never as wrong.
    """
    rows, unchecked = [], 0
    for c in claims or []:
        t, v = c["type"], c["value"]
        if t == "phone" and known.get("phones"):
            ok = any(_digits(v)[-7:] and _digits(v)[-7:] == _digits(p)[-7:] for p in known["phones"])
            rows.append({"claim": "Phone number", "assistant_says": v, "our_record": ", ".join(known["phones"][:2]), "status": "matches" if ok else "differs",
                         "source": known.get("phone_source", "")})
        elif t in ("check_in", "check_out") and known.get(t):
            a, b = _time(v), known[t]
            if a:
                rows.append({"claim": "Check-in time" if t == "check_in" else "Check-out time", "assistant_says": v, "our_record": b,
                             "status": "matches" if a == b else "differs", "source": known.get("hours_source", "")})
            else:
                unchecked += 1
        elif t == "parking" and known.get("parking_text"):
            says_free = bool(re.search(r"\b(free|complimentary|no charge)\b", v, re.I))
            page_charges = bool(re.search(r"[€£$]\s?\d|\d\s?[€£$]|per (day|night|24)|\bfee\b|\bcharge", known["parking_text"], re.I))
            page_free = bool(re.search(r"free (self[- ])?parking|complimentary parking|parking is free", known["parking_text"], re.I))
            if says_free and page_charges and not page_free:
                rows.append({"claim": "Parking", "assistant_says": v, "our_record": "the hotel's page mentions a parking charge", "status": "differs",
                             "source": known.get("parking_source", "")})
            elif says_free and page_free:
                rows.append({"claim": "Parking", "assistant_says": v, "our_record": "the hotel's page says parking is free", "status": "matches", "source": known.get("parking_source", "")})
            else:
                unchecked += 1
        elif t == "address" and known.get("address"):
            want = {w for w in re.split(r"[^a-z0-9]+", evidence.fold(known["address"])) if len(w) > 2}
            got = {w for w in re.split(r"[^a-z0-9]+", evidence.fold(v)) if len(w) > 2}
            ok = len(want & got) >= min(2, len(want))
            rows.append({"claim": "Address", "assistant_says": v, "our_record": known["address"], "status": "matches" if ok else "differs", "source": known.get("address_source", "")})
        else:
            unchecked += 1
    return {"rows": rows, "unchecked": unchecked}


# ------------------------------------------------------ perception vs positioning

_INTENT_WORDS = {"famil": ("family", "families", "kids", "children", "child"), "meeting": ("meeting", "conference", "event", "business"),
                 "wedding": ("wedding",), "spa": ("spa", "wellness", "pool", "massage"), "food": ("restaurant", "dining", "breakfast", "food", "bar"),
                 "pet": ("pet", "dog"), "romant": ("romantic", "couple"), "luxur": ("luxury", "5-star", "five-star"), "access": ("accessible", "wheelchair"),
                 "sustain": ("sustainab", "eco", "green"), "golf": ("golf",), "walk": ("walking", "hiking", "forest", "countryside", "nature")}


def perception(about, strong_intents):
    texts = " ".join(about.get("strengths", []) + about.get("weaknesses", []) + [c["value"] for c in about.get("claims", [])]).lower() if about else ""
    absent = []
    for label in strong_intents or []:
        low = label.lower()
        words = next((w for k, w in _INTENT_WORDS.items() if k in low), tuple(t for t in re.split(r"\W+", low) if len(t) > 3))
        if words and not any(w in texts for w in words):
            absent.append(label)
    return {"site_emphasises": list(strong_intents or []), "not_in_assistant_description": absent}


# ----------------------------------------------- LLM: grounded hypotheses

EXPLAIN_SYSTEM = ("You help a hotel understand why an AI assistant did not name it. You CANNOT see the assistant's reasoning, so you must not claim to; "
                  "you can only point out differences visible in the numbered evidence below. Use ONLY that evidence. Every hypothesis must cite the "
                  "evidence ids it rests on. Reply with one JSON object and nothing else.")

EXPLAIN_PROMPT = '''Hotel: {hotel}, {city}. In {missed} of {asked} questions (general 'where to stay' ones and narrower ones about the markets the hotel is positioned for) an AI assistant (with web search) did not name this hotel.

EVIDENCE (numbered; cite these ids only):
{ledger}

Return JSON: {{"summary": "two sentences, hedged, no claim to know the assistant's reasoning",
  "hypotheses": [{{"text": "one plain sentence, starting 'It may be that' or 'One difference is'", "evidence": ["E2", "E5"], "action": "one concrete thing the hotel could check or do, or null"}}]}}
At most 5 hypotheses. Prefer differences in sources, ratings, review volume, stated strengths and listings. Do not suggest anything about changing reviews. Never assert facts about competitors (their listings, ratings, content, sources) beyond what the evidence states.'''


def build_ledger(lb, sources, perc, about, snapshot, ai, footprint, entities, strong, niche=None):
    L = []
    def add(t):
        L.append({"id": f"E{len(L) + 1}", "text": t})
    for r in lb["rows"][:6]:
        if r["is_target"]:
            add(f"The hotel was named in {r['mentions']} of {r['of']} generic questions." + (f" Best rank {r['best_rank']}." if r["best_rank"] else ""))
        else:
            add(f"'{r['name']}' was named in {r['mentions']} of {r['of']} generic questions (best rank {r['best_rank']})."
                + (f" Reasons given: {'; '.join(r['reasons'])}." if r["reasons"] else "") + (f" Ratings quoted: {'; '.join(r['ratings'])}." if r["ratings"] else ""))
    for n in (niche or [])[:4]:
        names = ", ".join(n["hotels_named"][:5]) or "no hotels"
        add(f"In the niche question '{n['question']}' (asked because: {n['why']}) the assistant named: {names}; the hotel was "
            + ("named" if n["hotel_named"] else "not named") + ".")
    gen_src = [f"{s['domain']} ({s['answers']})" for s in sources[:6]]
    if gen_src:
        add("Sources the assistant leaned on most: " + ", ".join(gen_src) + ".")
    if about and (about.get("strengths") or about.get("weaknesses")):
        add("When asked directly the assistant described the hotel as: positives - " + ("; ".join(about["strengths"][:5]) or "none given") + "; drawbacks - "
            + ("; ".join(about["weaknesses"][:5]) or "none given") + f". Overall tone: {about.get('tone', 'unclear')}.")
    for p in (snapshot or {}).get("platforms", [])[:3]:
        if p.get("rating") is not None:
            add(f"The hotel's {p['platform']} page shows {p['rating']}" + (f" from {p['review_count']} reviews." if p.get("review_count") else "."))
    if perc.get("site_emphasises"):
        add("The hotel's own website emphasises: " + ", ".join(perc["site_emphasises"][:6]) + ".")
    if perc.get("not_in_assistant_description"):
        add("Not mentioned in the assistant's description of the hotel despite being emphasised on its site: " + ", ".join(perc["not_in_assistant_description"][:5]) + ".")
    found = [r["platform"] for r in (footprint or []) if r.get("discovered")]
    if found:
        add("The hotel was found listed on: " + ", ".join(found[:8]) + ".")
    wd = next((e for e in entities or [] if e.get("source") == "Wikidata"), None)
    if wd is not None:
        add("The hotel " + ("has" if wd.get("found") and wd.get("match_confident") else "does not have") + " a confirmed Wikidata entry.")
    add("The hotel's own website " + ("was" if (ai or {}).get("summary", {}).get("own_site_cited") else "was not") + " among the sources the assistant used.")
    return L


def explain(client, model, hotel, city, ledger, asked, missed):
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    ledger_text = "\n".join(f"{e['id']}: {e['text']}" for e in ledger)
    resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=EXPLAIN_SYSTEM, messages=[{"role": "user", "content": EXPLAIN_PROMPT.format(
        hotel=hotel, city=city, missed=missed, asked=asked, ledger=ledger_text)}], **extra)
    text, _d, _s, tin, tout = ai_sample.parse_response(resp)
    data = review_replies.parse_json(text)
    if not isinstance(data, dict):
        return None, (tin, tout)
    valid = {e["id"] for e in ledger}
    hyps = []
    for h in (data.get("hypotheses") or [])[:5]:
        if not isinstance(h, dict) or not h.get("text"):
            continue
        ev = [e for e in (h.get("evidence") or []) if e in valid]
        if not ev:
            continue                                         # a hypothesis resting on no evidence we supplied is dropped
        hyps.append({"text": re.sub(r"\s+", " ", str(h["text"])).strip()[:300], "evidence": ev,
                     "action": (re.sub(r"\s+", " ", str(h.get("action"))).strip()[:240] if h.get("action") not in (None, "null", "") else None)})
    return {"summary": re.sub(r"\s+", " ", str(data.get("summary") or "")).strip()[:400], "hypotheses": hyps}, (tin, tout)


# ------------------------------------------------------- head-to-head

H2H_PROMPT = ("A traveller is choosing between {hotel} and {rival} in {city}. Compare them for that traveller: what each is best for, where they differ on location, "
              "facilities, ratings and price level, and which you would suggest to whom. Search before answering. Answer in at most 180 words and say what you could not confirm.")


def head_to_head(client, model, hotel, city, rival):
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    resp = client.messages.create(model=model, max_tokens=ai_sample.MAX_TOKENS, system=ai_sample.SYSTEM, tools=[dict(ai_sample.SEARCH_TOOL)],
                                  messages=[{"role": "user", "content": H2H_PROMPT.format(hotel=hotel, rival=rival, city=city)}], **extra)
    answer, domains, searches, tin, tout = ai_sample.parse_response(resp)
    if not answer:
        return None, ai_sample.cost_usd(model, tin, tout, searches)
    return {"rival": rival, "question": f"{hotel} or {rival} in {city}?", "answer": answer, "domains": domains, "searches": searches,
            "both_named": ai_sample.mentioned(answer, hotel, city) and appears(rival, answer)}, ai_sample.cost_usd(model, tin, tout, searches)


# ---------------------------------------------------------------------- run

def known_facts(guest, entities):
    """The facts we already hold about the hotel, from its own pages and from the map, for the accuracy check."""
    k = {}
    sheet = {r["fact"]: r for r in (guest or {}).get("fact_sheet", []) if isinstance(r, dict)}
    for key, fact in (("check_in", "Check-in time"), ("check_out", "Check-out time")):
        if sheet.get(fact) and sheet[fact].get("value"):
            k[key] = _time(sheet[fact]["value"])
            k["hours_source"] = "the hotel's own pages"
    for r in (guest or {}).get("fact_sheet", []):
        if isinstance(r, dict) and r.get("fact") == "Parking" and r.get("value"):
            k["parking_text"], k["parking_source"] = str(r["value"])[:600], "the hotel's own pages"
    phones = [t for e in entities or [] if e.get("source") == "OpenStreetMap" for t in [((e.get("facts") or {}).get("telephone"))] if t]
    if phones:
        k["phones"], k["phone_source"] = phones, "OpenStreetMap"
    addr = next((((e.get("facts") or {}).get("address")) for e in entities or [] if e.get("source") == "OpenStreetMap" and (e.get("facts") or {}).get("address")), None)
    if addr:
        k["address"], k["address_source"] = addr, "OpenStreetMap"
    return k


def _observed_names(answers):
    """{name: how many times the assistant used it} across every answer."""
    out = {}
    for hs in (answers or {}).values():
        for h in hs:
            if h.get("name"):
                out[h["name"]] = out.get(h["name"], 0) + 1
    return out


def derive(out, ai, extracted, items, hotel, city, own_domain, resolver):
    """
    Everything that depends on WHICH NAMES are the hotel, worked out from the hotels each answer was read as listing, with no further question put to an assistant: the leaderboards, the
    brand ranking, the question table, the scoreboard, the pages and the hotel's own-site reliance. Used by run() and to recalculate a stored report (identity_fix.py).
    """
    lb = leaderboard(extracted, items, hotel, resolver=resolver)
    out.update(leaderboard=lb, alternatives=alternatives(extracted, hotel, resolver), matrix=question_rows(items, extracted, resolver))
    niche_rows = [m for m in out["matrix"] if m["kind"] == "niche"]
    lbn = leaderboard(extracted, items, hotel, kinds=("niche",), resolver=resolver) if niche_rows else None
    out["niche"] = {"questions": niche_rows, "leaderboard": lbn} if niche_rows else None
    me = next((r for r in lb["rows"] if r["is_target"]), None)
    out["scoreboard"] = {"questions": lb["questions"], "named": me["mentions"] if me else 0, "avg_rank": me["avg_rank"] if me else None, "repeats": ai.get("summary", {}).get("repeats", 1),
                         "share": me["share"] if me else 0, "rank_in_table": (lb["rows"].index(me) + 1) if me else None, "table_size": len(lb["rows"]),
                         "top_competitor": next((r["name"] for r in lb["rows"] if not r["is_target"]), None)}
    me_n = next((r for r in lbn["rows"] if r["is_target"]), None) if lbn else None
    asked = lb["questions"] + (lbn["questions"] if lbn else 0)
    missed = (lb["questions"] - (me["mentions"] if me else 0)) + ((lbn["questions"] - (me_n["mentions"] if me_n else 0)) if lbn else 0)
    out["scoreboard"].update(niche_asked=lbn["questions"] if lbn else 0, niche_named=(me_n["mentions"] if me_n else 0) if lbn else 0)
    out["brand_ranking"] = br = brand_ranking([lb, lbn], hotel)
    me_b = next((r for r in br["rows"] if r["is_target"]), None)
    out["scoreboard"].update(coverage_pct=me_b["coverage_pct"] if me_b else 0, sentiment=me_b["sentiment"] if me_b else None, place=me_b["place"] if me_b else None,
                             positive=me_b["positive"] if me_b else 0, negative=me_b["negative"] if me_b else 0, asked_all=br["asked"])
    out["pages"] = page_table(items, hotel, [r["name"] for r in br["rows"] if not r["is_target"]], own_domain)
    out["own_site"] = own_site_reliance(items, out["pages"])
    return {"lb": lb, "lbn": lbn, "niche_rows": niche_rows, "asked": asked, "missed": missed, "br": br}


def run(ai, ctx, *, api_key=None, model=None, client=None, budget_usd=0.25, do_head_to_head=True):
    """
    ai: the ai_sample envelope. ctx: {"hotel","city","guest","entities","footprint","snapshot","strong_intents","own_domain","brand_domains"}.
    -> envelope. Never raises; LLM steps degrade to a stated reason while the arithmetic sections still show.
    """
    def env(status, reason="", **kw):
        return {"source": SOURCE, "status": status, "reason": reason, **kw}

    if not ai or ai.get("status") != "ok" or not ai.get("items"):
        return env("unavailable", "There were no sampled answers to analyse.")
    hotel, city = ctx["hotel"], ctx["city"]
    model = model or ai_sample.MODEL_DEFAULT
    items = ai["items"]
    sources = source_table(items, ctx.get("footprint"), ctx.get("entities"), ctx.get("own_domain", ""), ctx.get("brand_domains", ()))
    out = env("ok", "", model=model, sources=sources, cost_usd=0.0, notes=[])
    if client is None:
        if not api_key:
            return {**out, "status": "partial", "reason": "No Anthropic key, so only the source analysis could be shown."}
        try:
            import anthropic
            client = ai_sample._make_client(api_key, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return {**out, "status": "partial", "reason": f"The Anthropic library could not be started ({type(e).__name__}).", }

    cost = 0.0
    try:
        _xlog = {}
        extracted, (tin, tout) = extract(client, model, items, hotel, city, log=_xlog)
        out["extraction"] = _xlog
        cost += ai_sample.cost_usd(model, tin, tout, 0)
    except Exception as e:  # noqa: BLE001
        return {**out, "status": "partial", "reason": ai_sample._reason_for(e), "cost_usd": round(cost, 5)}
    if not extracted:
        return {**out, "status": "partial", "reason": "The answers could not be broken down into hotels and claims, so only the source analysis is shown.", "cost_usd": round(cost, 5)}

    out["extracted_answers"] = extracted["answers"]           # the hotels each answer named, kept so ai_gap can say who was named instead, question by question
    if extracted.get("failed_ids"):
        out["unanalysed"] = len(extracted["failed_ids"])
        out["reason"] = (out.get("reason") or "") + (f" {len(extracted['failed_ids'])} answer(s) could not be broken down into hotels even after being asked again in smaller groups; they are left out of the "
                                                     "rival and ranking figures rather than counted as naming nobody.")
    import hotel_identity
    _ents = [n for e in (ctx.get("entities") or []) if e.get("found") for n in [e.get("label") or (e.get("facts") or {}).get("name")] if n]
    _obs = _observed_names(extracted["answers"])
    ident = (hotel_identity.refine(ctx["identity"], observed=_obs, entity_names=_ents, city=city) if ctx.get("identity")
             else hotel_identity.build(hotel, city, ctx.get("website") or ctx.get("own_domain") or "", brand_site=bool(ctx.get("brand_domains")), observed=_obs, entity_names=_ents))
    res = hotel_identity.Resolver(ident, hotel_identity.by_answer_of(extracted["answers"]), city)
    about = extracted["about"]
    out["about"] = about
    out["perception"] = perception(about, ctx.get("strong_intents"))
    out["accuracy"] = accuracy(about.get("claims"), known_facts(ctx.get("guest"), ctx.get("entities")))
    d = derive(out, ai, extracted, items, hotel, city, ctx.get("own_domain", ""), res)
    lb, lbn, niche_rows, asked, missed, br = d["lb"], d["lbn"], d["niche_rows"], d["asked"], d["missed"], d["br"]
    out["identity"] = ident
    if asked and missed > 0 and cost < budget_usd:
        try:
            ledger = build_ledger(lb, sources, out["perception"], about, ctx.get("snapshot"), ai, ctx.get("footprint"), ctx.get("entities"), ctx.get("strong_intents"),
                                  niche=niche_rows)
            exp, (tin, tout) = explain(client, model, hotel, city, ledger, asked, missed)
            cost += ai_sample.cost_usd(model, tin, tout, 0)
            out["ledger"] = ledger
            out["explanation"] = exp
            if not exp:
                out["notes"].append("The explanation step returned nothing usable, so no hypotheses are shown.")
        except Exception as e:  # noqa: BLE001
            out["notes"].append("The explanation step failed: " + ai_sample._reason_for(e))
    rival = out["scoreboard"]["top_competitor"]
    if do_head_to_head and rival and cost < budget_usd:
        try:
            h2h, c = head_to_head(client, model, hotel, city, rival)
            cost += c
            out["head_to_head"] = h2h
        except Exception as e:  # noqa: BLE001
            out["notes"].append("The head-to-head comparison failed: " + ai_sample._reason_for(e))
    out["cost_usd"] = round(cost, 5)
    return out
