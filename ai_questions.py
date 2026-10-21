"""
The questions put to the AI assistant for one hotel: a short ladder built from facts the audit has VERIFIED, not from a list of topics.

  facts      what the hotel is and where it is, each with the evidence for it: its price level and why, its kind (airport, business, city-centre, spa...), the named places it is close to, what it offers strongly,
             which audiences its kind supports (ai_niche.profile, hotel_class, anchors).
  templates  realistic booking intents built on those facts and a real anchor: 'Which 4-star hotels near the Opera Garnier are best for a business trip, with reliable Wi-Fi and meeting space?'
  proposals  one cheap Claude call (no web search) that writes more prompts the way travellers actually phrase them, from the SAME facts only. Every proposal is checked by code: it must not name the hotel,
             must rest on a fact it cites, must mention the town or an anchor, must not contradict the price level and must not bring in a facility or audience the facts do not support.
  priority   'core' prompts (the hotel's own market) are asked more often than 'secondary' ones, so the answers that matter are the steadiest; the two town-wide questions stay as a labelled benchmark.

Nothing here asks the hotel for anything. If there is no anchor or no Claude key the templates in ai_niche still produce the questions, so the audit never ends up with none.
"""

import re

import ai_niche
import ai_sample
import evidence

MAX_CORE, MAX_SECONDARY, MAX_PROPOSALS = 14, 8, 8
# What a traveller asks for when a facility decides the booking, and what kind of hotel makes the question fit. Asked only for a facility the hotel's own pages show STRONGLY, and (where it needs one) a kind of hotel
# that supports it, so a gym does not become a spa question. Each is anchored on a real place the hotel is close to: a narrower search is a fairer test of the market the hotel really competes in than a town-wide list.
FEATURE_ASKS = {
    "meeting_rooms": ("Meetings and events", "have meeting rooms for a team offsite", {"business", "conference"}),
    "parking": ("Parking", "have parking for guests", None),
    "spa": ("Spa and wellness", "have a spa", {"spa_hotel", "resort"}),
    "pool": ("Spa and wellness", "have a swimming pool", {"spa_hotel", "resort"}),
    "gym": ("Facilities", "have a gym", None),
    "restaurant": ("Dining", "have a good restaurant", {"luxury", "boutique", "resort", "spa_hotel"}),
    "ev": ("EV charging", "have EV charging for guests", None),
    "family": ("Families", "suit a family with young children", {"family_focused", "resort"}),
    "pets": ("Pet-friendly", "welcome dogs", None),
    "accessible": ("Accessibility", "have step-free accessible rooms", None),
    "airport_transfer": ("Airport", "offer an airport shuttle", {"airport"}),
    "weddings": ("Weddings", "can host a wedding with rooms for the guests", {"resort", "luxury", "boutique", "spa_hotel"}),
}
MAX_FEATURE_QUESTIONS = 6
CORE_ANGLES = {"Price level", "Neighbourhood", "Near a venue", "Near a landmark", "Meetings and events", "Business travel", "Airport", "City breaks", "Traveller intent", "Near a place"}
LUXURY_WORDS = re.compile(r"\b(?:luxury|palace|5[- ]star|five[- ]star|splurge|lavish|ultra)\b", re.I)
BUDGET_WORDS = re.compile(r"\b(?:cheap|budget|bargain|hostel)\b", re.I)
# a facility or audience a proposal may only mention when a fact supports it: word -> the fact words that license it
LICENCE = {r"\bspa\b|wellness|massage|treatment": r"spa|wellness", r"\bpool\b|swim": r"pool", r"wedding": r"wedding", r"famil|kids|child|toddler": r"famil|kid|child",
           r"romantic|couple|honeymoon|anniversary": r"romantic|couple|spa|boutique", r"\bpets?\b|\bdogs?\b": r"pet|dog", r"\bev\b|electric|charging": r"\bev\b|electric|charging",
           r"wheelchair|accessible|mobility": r"accessib|wheelchair", r"\bairport\b|flight|layover|stopover": r"airport|flight", r"conference|meeting|workshop|offsite|off-site": r"meeting|conference|business",
           r"michelin|fine dining|restaurant": r"restaurant|dining|michelin|food"}


def _tokens(s):
    return {t for t in re.split(r"[^a-z0-9]+", evidence.fold(s)) if len(t) > 2}


def _similar(a, b, cut=0.6):
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= cut


# ------------------------------------------------------------------- facts

def fact_list(prof, anchor_list, features=None):
    """The verified facts a question may rest on: [{id, text, kind}]. Only facts the audit holds evidence for (see ai_niche.profile)."""
    out = []

    def add(kind, text):
        out.append({"id": f"f{len(out) + 1}", "kind": kind, "text": text})
    tier = (prof or {}).get("tier")
    if tier:
        add("tier", f"price level: {tier['label']}" + (f" ({prof['stars']}-star)" if prof.get("stars") and tier.get("source") != "brand" else "") + f"; {tier['why']}")
    for c in (prof or {}).get("classes") or []:
        add("class", f"kind of hotel: {c}")
    for a in anchor_list[:3]:
        add("anchor", f"close to {a['name']}" + (f" ({a['distance']}, from {a['source']})" if a.get("distance") else f" ({a['km']:g} km, from {a['source']})"))
    ap = (prof or {}).get("airport")
    if ap and prof.get("airport_hotel"):
        add("airport", f"{ap['km']:g} km from {ap['name']}")
    if (prof or {}).get("district"):
        add("district", f"in the {prof['district']} area")
    for key in ((prof or {}).get("strong_features") or (prof or {}).get("features") or [])[:8]:
        add("feature", f"offers {key.replace('_', ' ')} (strong evidence on its own pages)")
    for a in (prof or {}).get("audiences") or []:
        if a["level"] in ("strong", "stated"):
            add("audience", f"its kind and pages support: {a['label'].lower()}")
    return out


# --------------------------------------------------------------- templates

def anchor_questions(prof, hotel, city, anchor_list):
    """Realistic booking intents around the best real anchor. -> [{id, kind, angle, text, why, priority}]."""
    tier = (prof or {}).get("tier")
    tp = ai_niche._tier_phrase(tier, (prof or {}).get("stars"))
    out = []
    for k, a in enumerate(an_best(anchor_list, 2)):
        name = a["name"]
        where = f"the hotel's own pages put {name} close ({a['distance']})" if a.get("distance") else f"{name} is {a['km']:g} km from the hotel ({a['source']})"
        classes = set((prof or {}).get("classes") or [])
        if k == 0 and tier:
            out.append(("anchor_value", "Price level", f"Which {tp}hotels near {name} give the best quality for the price?", f"Hotel level: {tier['label']} ({tier['why']}); {where}.", "core"))
        if classes & {"business", "conference", "airport", "city_centre"} and k == 0:
            out.append((f"anchor_business{k}", "Business travel", f"Which {tp}hotels near {name} are best for a business trip, with reliable Wi-Fi and meeting space?", f"Kind of hotel: business; {where}.", "core"))
        if "city_centre" in classes and k == 0:
            out.append((f"anchor_break{k}", "City breaks", f"Where should I stay for a weekend near {name}, in a {tp}hotel within walking distance?", f"Kind of hotel: city-centre; {where}.", "core"))
        if k == 1 and a.get("source", "").startswith("the hotel"):
            out.append((f"anchor_second{k}", "Near a place", f"Which {tp}hotels are closest to {name}?", where.capitalize() + ".", "secondary"))
        if k == 1 and tier:
            out.append((f"anchor_value{k}", "Price level", f"Which {tp}hotels near {name} give the best quality for the price?", f"Hotel level: {tier['label']} ({tier['why']}); {where}.", "secondary"))
    for st_ in [a for a in anchor_list or [] if a.get("kind") == "station"][:1]:
        if tier:
            out.append(("station_value", "Near transport", f"Which {tp}hotels within walking distance of {st_['name']} are good value?", f"The hotel's own pages put {st_['name']} close ({st_['distance']}).", "secondary"))
    return [{"id": f"niche_{cid}", "kind": "niche", "angle": ang, "text": text, "why": why, "priority": pr} for cid, ang, text, why, pr in out if ai_niche._safe(text, hotel)]


def feature_questions(prof, hotel, city, anchor_list):
    """
    One question for each facility the hotel's pages show strongly (and whose kind of hotel fits), built around the best place the hotel is close to, or its area when no place is known:
    'Which 4-star hotels near the Opera Garnier have meeting rooms for a team offsite?'. Narrower than 'best hotels in Paris', and every part of it is true of the hotel.
    """
    tier = (prof or {}).get("tier")
    tp = ai_niche._tier_phrase(tier, (prof or {}).get("stars"))
    classes = set((prof or {}).get("classes") or []) if (prof or {}).get("classes") is not None else None
    best = an_best(anchor_list, 1)
    where = f"near {best[0]['name']}" if best else f"in {(prof or {}).get('district') or (city or '').split(',')[0].strip()}"
    basis = (f"the hotel's own pages put {best[0]['name']} close ({best[0]['distance']})" if best and best[0].get("distance") else f"{best[0]['name']} is {best[0]['km']:g} km from the hotel ({best[0]['source']})") if best else "the hotel's area"
    out = []
    for key in (prof or {}).get("strong_features") or []:
        spec = FEATURE_ASKS.get(key)
        if not spec:
            continue
        angle, phrase, needs = spec
        if needs and (classes is None or not (classes & needs)):
            continue
        text = f"Which {tp}hotels {where} {phrase}?"
        out.append({"id": f"niche_feat_{key}", "kind": "niche", "angle": angle, "text": text, "why": f"The hotel's own pages show {key.replace('_', ' ')} strongly; {basis}.", "priority": "core" if len(out) < 4 else "secondary", "source": "feature"})
        if len(out) >= MAX_FEATURE_QUESTIONS:
            break
    return [q for q in out if ai_niche._safe(q["text"], hotel)]


def an_best(anchor_list, n):
    return [a for a in anchor_list or [] if a.get("kind") in ("attraction", "venue")][:n]


# --------------------------------------------------------------- proposals

SYSTEM = ("You write realistic prompts that travellers type into an AI assistant when choosing where to stay. Use ONLY the facts supplied. Never name the hotel. Reply with JSON only.")
PROMPT = ('''A hotel in {city}. Verified facts about it (each has an id):
{facts}

Write up to {n} prompts a real traveller with a genuine booking intention would type into an AI assistant, for the market THIS hotel competes in. Rules:
- each rests on one or two of the fact ids above and must not need any fact that is not listed;
- each mentions {city} or a place named in the facts, and the star level where the facts give one;
- different intents (a purpose, a constraint or a place), phrased the way people write, not as keyword lists;
- never name the hotel; never ask about facilities or kinds of traveller the facts do not support.
Reply: {{"prompts": [{{"text": "...", "facts": ["f1"]}}]}}''')


def validate(proposed, facts, hotel, city, anchor_names, tier_key, existing=()):
    """Keep only proposals that pass every check. -> (kept questions, rejected [{text, why}])."""
    ids = {f["id"]: f for f in facts}
    place_words = [evidence.fold((city or "").split(",")[0])] + [evidence.fold(n) for n in anchor_names]
    kept, rejected = [], []
    for p in proposed or []:
        text = re.sub(r"\s+", " ", str((p or {}).get("text") or "")).strip()
        cited = [i for i in (p or {}).get("facts") or [] if i in ids]
        why = None
        if not 25 <= len(text) <= 180:
            why = "length"
        elif not ai_niche._safe(text if text.endswith("?") else text + "?", hotel):
            why = "names the hotel"
        elif not cited:
            why = "rests on no listed fact"
        elif not any(w and w in evidence.fold(text) for w in place_words):
            why = "mentions neither the town nor a named place"
        elif tier_key != "luxury" and LUXURY_WORDS.search(text):
            why = "luxury wording for a hotel that is not luxury"
        elif tier_key == "luxury" and BUDGET_WORDS.search(text):
            why = "budget wording for a luxury hotel"
        elif any(_similar(text, e) for e in list(existing) + [k["text"] for k in kept]):
            why = "repeats another question"
        else:
            cited_text = " ".join(ids[i]["text"] for i in cited).lower() + " " + " ".join(f["text"] for f in facts if f["kind"] in ("class", "feature", "audience", "airport")).lower()
            for needs, licence in LICENCE.items():
                if re.search(needs, text, re.I) and not re.search(licence, cited_text, re.I):
                    why = f"brings in something the facts do not support ({re.search(needs, text, re.I).group(0)})"
                    break
        if why:
            rejected.append({"text": text, "why": why})
            continue
        kept.append({"id": f"niche_prop{len(kept) + 1}", "kind": "niche", "angle": "Traveller intent", "text": text if text.endswith("?") else text.rstrip(".") + "?",
                     "why": "Written from: " + "; ".join(ids[i]["text"] for i in cited[:2]) + ".", "priority": "core", "source": "proposed"})
    return kept, rejected


def propose(client, model, facts, city, n=MAX_PROPOSALS + 2):
    """One Claude call (no tools) -> the raw proposals ([{text, facts}]), or [] when it fails or the reply is unreadable. Cost is returned too: (proposals, usd)."""
    import review_replies
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    msg = PROMPT.format(city=(city or "").split(",")[0], facts="\n".join(f"{f['id']}: {f['text']}" for f in facts), n=n)
    try:
        resp = client.messages.create(model=model, max_tokens=900, system=SYSTEM, messages=[{"role": "user", "content": msg}], **extra)
        text, _d, _s, tin, tout = ai_sample.parse_response(resp)
    except Exception:  # noqa: BLE001 - the templates stand without it
        return [], 0.0
    data = review_replies.parse_json(text)
    props = data.get("prompts") if isinstance(data, dict) else None
    return ([p for p in props if isinstance(p, dict)] if isinstance(props, list) else []), ai_sample.cost_usd(model, tin, tout, 0)


# --------------------------------------------------------------------- build

def build(prof, hotel, city, anchor_list, *, client=None, model=None, base_repeats=2, features=None, benchmark=None):
    """
    -> {"questions": [...], "facts": [...], "rejected": [...], "cost_usd": float}. Core questions are asked base_repeats + 1 times (at most 4), secondary ones base_repeats times; every question carries
    its priority, its repeat count and why it was asked. Never empty when ai_niche can write at least one question.

    benchmark: the prompts frozen at this hotel's FIRST audit ([{text, angle, why}]). When given they are asked again, word for word, as the core questions, so a later audit measures the same thing and a
    change means something; this audit's fresh questions are added as exploratory (secondary) ones. When there is none, this audit's core questions become the benchmark ('benchmark_prompts' in the result).
    """
    facts = fact_list(prof, anchor_list or [], features)
    tmpl = ai_niche.questions(prof, hotel, city, n=12) if prof else []
    for q in tmpl:
        q["priority"] = "core" if q["angle"] in CORE_ANGLES else "secondary"
    anch = anchor_questions(prof, hotel, city, anchor_list or [])
    # an anchored price question replaces the town-wide price question; the others are added
    for angle in ("Price level", "Business travel", "City breaks"):            # an anchored version of a question replaces its town-wide twin; the other kinds are added
        if any(q["angle"] == angle for q in anch):
            tmpl = [q for q in tmpl if q["angle"] != angle]
    feat = feature_questions(prof, hotel, city, anchor_list or [])
    pool = anch + feat + tmpl
    cost, rejected = 0.0, []
    if client is not None and facts:
        props, cost = propose(client, model or ai_sample.MODEL_DEFAULT, facts, city)
        kept, rejected = validate(props, facts, hotel, city, [a["name"] for a in an_best(anchor_list, 3)], ((prof or {}).get("tier") or {}).get("key"), [q["text"] for q in pool])
        pool += kept[:MAX_PROPOSALS]
    out, seen = [], set()
    for q in pool:
        if q["text"] in seen:
            continue
        seen.add(q["text"])
        out.append(q)
    core = [q for q in out if q["priority"] == "core"][:MAX_CORE]
    sec = [q for q in out if q["priority"] != "core"][:MAX_SECONDARY]
    bench_out = []
    if benchmark:
        frozen = [{"id": f"niche_bench{i}", "kind": "niche", "angle": b.get("angle") or "Benchmark", "text": b["text"], "priority": "core", "source": "benchmark",
                   "why": ((b.get("why") or "").rstrip(".") + ". " if b.get("why") else "") + "A benchmark prompt kept from this hotel's first audit and asked again word for word, so the results can be compared over time."} for i, b in enumerate(benchmark[:MAX_CORE], 1) if b.get("text")]
        fresh = [q for q in core + sec if not any(_similar(q["text"], f["text"], 0.8) for f in frozen)]
        for q in fresh:
            q["priority"], q["source"] = "secondary", q.get("source") or "new"
        core, sec = frozen, fresh[:MAX_SECONDARY + 2]
    else:
        bench_out = [{"text": q["text"], "angle": q["angle"], "why": q["why"]} for q in core]
    for q in core:
        q["repeats"] = min(4, base_repeats + 1)
    for q in sec:
        q["repeats"] = base_repeats
    return {"questions": core + sec, "facts": facts, "rejected": rejected, "cost_usd": round(cost, 5), "benchmark_prompts": bench_out, "benchmark_reused": bool(benchmark)}
