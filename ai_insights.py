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

import re

import ai_sample
import evidence
import review_replies

SOURCE = "AI answer insights"
MAX_TOKENS = 6000
BATCH = 8                                  # answers per extraction call, so a long set (repeats) never overruns the output cap
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
    for kind, pats in _DOMAIN_KINDS:
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
    toks = [t for t in re.split(r"[^a-z0-9]+", evidence.fold(name)) if t and t not in ai_sample._GENERIC]
    return " ".join(toks)


def appears(name, answer):
    c = canon(name)
    text = evidence.fold(answer).replace("&", " ")
    return (bool(c) and c in text) or evidence.fold(name) in evidence.fold(answer)


# ------------------------------------------------------------ LLM: extraction

EXTRACT_SYSTEM = ("You extract structured facts from answers a travel assistant gave. Use ONLY what is written in each answer; never add anything. "
                  "Reply with one JSON object and nothing else.")

EXTRACT_PROMPT = '''Target hotel: {hotel}, {city}.

Below are an assistant's answers, each with an id. For every answer return the hotels it recommends or compares, in the order given, with a short paraphrase of why (under 15 words), any rating it states, and the sentiment the answer expresses toward THAT hotel (positive = recommends or praises it, negative = warns against it or lists mainly drawbacks, neutral = just lists or describes it).
For the answers that are ABOUT the target hotel (ids: {about_ids}) also return how it describes the hotel.

{blocks}

Return JSON in exactly this shape:
{{
  "answers": [{{"id": "best", "hotels": [{{"name": "as written", "rank": 1, "reason": "paraphrase", "rating": "e.g. 8.6 on Booking.com or null", "sentiment": "positive|neutral|negative"}}]}}],
  "about": {{"tone": "positive|mixed|negative|unclear",
            "strengths": ["short phrases the assistant gives as positives"], "weaknesses": ["short phrases the assistant gives as drawbacks"],
            "claims": [{{"type": "phone|address|check_in|check_out|star_rating|parking|pets|other", "value": "exactly as stated", "answer_id": "about"}}]}}
}}
Use an empty list where nothing applies. rank is the position in the answer's list (1 first), or null if the answer is not a list.'''


def _blocks(items):
    return "\n\n".join(f"[{i['id']}] ({i['kind']}) Question: {i['text']}\nAnswer: {(i.get('answer') or '')[:1800]}" for i in items if i.get("answer"))


def _extract_batch(client, model, batch, hotel, city):
    """One call for up to BATCH answers -> (parsed dict | None, (tin, tout))."""
    about_ids = [i["id"] for i in batch if i["kind"] == "direct"]
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=EXTRACT_SYSTEM, messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
        hotel=hotel, city=city, about_ids=", ".join(about_ids) or "none", blocks=_blocks(batch))}], **extra)
    text, _d, _s, tin, tout = ai_sample.parse_response(resp)
    data = review_replies.parse_json(text)
    return (data if isinstance(data, dict) else None), (tin, tout)


def extract(client, model, items, hotel, city):
    """-> (validated dict | None, usage). Names are kept only if they appear in that answer's own text. The answers about the hotel go first, in one batch."""
    by_id = {i["id"]: i for i in items if i.get("answer")}
    if not by_id:
        return None, (0, 0)
    ordered = sorted(by_id.values(), key=lambda i: i["kind"] != "direct")
    batches = [ordered[k:k + BATCH] for k in range(0, len(ordered), BATCH)]
    answers_raw, data_about, tin, tout, ok = [], {}, 0, 0, 0
    for n, batch in enumerate(batches):
        d, (a, b) = _extract_batch(client, model, batch, hotel, city)
        tin, tout = tin + a, tout + b
        if d is None:
            continue
        ok += 1
        answers_raw += [x for x in (d.get("answers") or []) if isinstance(x, dict)]
        if n == 0 and isinstance(d.get("about"), dict):
            data_about = d["about"]
    if not ok:
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
            keep.append({"name": nm, "rank": rank if isinstance(rank, int) and 1 <= rank <= 30 else None, "sentiment": sent if sent in SENTIMENTS else "neutral",
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
    return {"answers": answers, "about": about}, (tin, tout)


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
            k = canon(r["name"])
            a = rows.setdefault(k, {"name": r["name"], "is_target": r["is_target"], "mentions": 0, "ranks": [], "sent": []})
            a["mentions"] += r["mentions"]
            a["is_target"] = a["is_target"] or r["is_target"]
            a["ranks"] += [r["avg_rank"]] * r["mentions"] if r["avg_rank"] else []
            a["sent"] += ["positive"] * r["positive"] + ["neutral"] * r["neutral"] + ["negative"] * r["negative"]
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


def question_rows(items, extracted):
    """One row per QUESTION (repeats merged): whether the hotel was named and in how many of the answers, the best position, and the hotels named."""
    out = []
    for g in ai_sample.by_question(items):
        names, seen = [], set()
        for a in g["answers"]:
            for h in (extracted["answers"].get(a["id"]) or []):
                if canon(h["name"]) not in seen:
                    seen.add(canon(h["name"]))
                    names.append(h["name"])
        out.append({"id": g["qid"], "kind": g["kind"], "question": g["text"], "angle": g["angle"], "why": g["why"], "named": g["named"], "of": g["of"],
                    "hotel_named": g["named"] > 0, "position": g["best_position"], "hotels_named": names[:6], "answer_ids": [a["id"] for a in g["answers"]]})
    return out


def leaderboard(extracted, items, hotel, kinds=("generic",)):
    """Who is named most across the GENERIC questions (or the niche ones), with the hotel in the same table (a row of zeros if it is never named)."""
    gen_ids = [i["id"] for i in items if i["kind"] in kinds and i.get("answer")]
    rows, total = {}, 0
    for qid in gen_ids:
        for h in (extracted["answers"].get(qid) or []):
            k = canon(h["name"])
            r = rows.setdefault(k, {"name": h["name"], "key": k, "mentions": 0, "ranks": [], "questions": [], "reasons": [], "ratings": [], "sent": []})
            r["mentions"] += 1
            r["sent"].append(h.get("sentiment") or "neutral")
            total += 1
            if h["rank"]:
                r["ranks"].append(h["rank"])
            r["questions"].append(qid)
            if h["reason"] and h["reason"] not in r["reasons"]:
                r["reasons"].append(h["reason"])
            if h["rating"] and h["rating"] not in r["ratings"]:
                r["ratings"].append(h["rating"])
    # one hotel written two ways ('Park Inn by Radisson' / 'Park Inn by Radisson Luxembourg City'): fold the shorter into the longer
    for short in sorted(rows, key=lambda k: -len(k)):
        st = short.split()
        host = next((k for k in rows if k != short and len(st) >= 2 and k.split()[:len(st)] == st), None)
        if host and short in rows:
            a, b = rows[host], rows.pop(short)
            a["mentions"] += b["mentions"]
            a["ranks"] += b["ranks"]
            a["questions"] += b["questions"]
            a["reasons"] += [x for x in b["reasons"] if x not in a["reasons"]]
            a["ratings"] += [x for x in b["ratings"] if x not in a["ratings"]]
            a["sent"] += b["sent"]
    me = canon(hotel)
    out = []
    for r in rows.values():
        out.append({"name": r["name"], "is_target": ai_sample.mentioned(r["name"], hotel) or r["key"] == me, "mentions": r["mentions"], "of": len(gen_ids),
                    "share": round(100 * r["mentions"] / total) if total else 0, "best_rank": min(r["ranks"]) if r["ranks"] else None,
                    "avg_rank": round(sum(r["ranks"]) / len(r["ranks"]), 1) if r["ranks"] else None, "questions": r["questions"],
                    "reasons": r["reasons"][:2], "ratings": r["ratings"][:2], "coverage_pct": round(100 * len(set(r["questions"])) / len(gen_ids)) if gen_ids else 0,
                    **sentiment_of(r["sent"])})
    out.sort(key=lambda r: (-r["mentions"], r["avg_rank"] or 99, r["name"]))
    if not any(r["is_target"] for r in out):
        out.append({"name": hotel, "is_target": True, "mentions": 0, "of": len(gen_ids), "share": 0, "best_rank": None, "avg_rank": None, "questions": [],
                    "reasons": [], "ratings": [], "coverage_pct": 0, **sentiment_of([])})
    return {"rows": out, "questions": len(gen_ids), "total_mentions": total}


def alternatives(extracted, hotel):
    """The set the assistant offers when asked what is similar - its view of the competitive set."""
    return [h for h in (extracted["answers"].get("similar") or []) if not ai_sample.mentioned(h["name"], hotel)]


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
            client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            return {**out, "status": "partial", "reason": f"The Anthropic library could not be started ({type(e).__name__}).", }

    cost = 0.0
    try:
        extracted, (tin, tout) = extract(client, model, items, hotel, city)
        cost += ai_sample.cost_usd(model, tin, tout, 0)
    except Exception as e:  # noqa: BLE001
        return {**out, "status": "partial", "reason": ai_sample._reason_for(e), "cost_usd": round(cost, 5)}
    if not extracted:
        return {**out, "status": "partial", "reason": "The answers could not be broken down into hotels and claims, so only the source analysis is shown.", "cost_usd": round(cost, 5)}

    lb = leaderboard(extracted, items, hotel)
    out.update(leaderboard=lb, alternatives=alternatives(extracted, hotel), matrix=question_rows(items, extracted))
    niche_rows = [m for m in out["matrix"] if m["kind"] == "niche"]
    lbn = leaderboard(extracted, items, hotel, kinds=("niche",)) if niche_rows else None
    out["niche"] = {"questions": niche_rows, "leaderboard": lbn} if niche_rows else None
    about = extracted["about"]
    out["about"] = about
    out["perception"] = perception(about, ctx.get("strong_intents"))
    out["accuracy"] = accuracy(about.get("claims"), known_facts(ctx.get("guest"), ctx.get("entities")))
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
    out["pages"] = page_table(items, hotel, [r["name"] for r in br["rows"] if not r["is_target"]], ctx.get("own_domain", ""))
    out["own_site"] = own_site_reliance(items, out["pages"])
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
