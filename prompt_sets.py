"""
The prompts a hotel's AI tests are built from, and who chooses them.

Why this exists: the audit asks an AI assistant the questions a traveller would ask, with no mention of the hotel, and counts how often the hotel is named. To see whether the hotel is coming up MORE often over
time, the same prompts have to be asked every week. If the prompts keep changing, a better or worse week might only mean different questions. So:

  1. After a hotel's first check we RECOMMEND a set (balanced: places near it, who it suits, what it offers, price, a short search and a conversational request), usually 12.
  2. The hotel reviews it, edits it (remove, reword, add its own), and CONFIRMS it, with a warning that changing it later makes earlier results harder to compare.
  3. From then on every check asks exactly the confirmed prompts, word for word, in addition to a few exploratory ones that are never part of the trend.
  4. Changing a confirmed set is allowed but is a deliberate step (a new version, with the warning again). Earlier checks keep the version they used.

Rules for a prompt: 20 to 220 characters, never names the hotel (it tests whether the assistant volunteers the hotel), and mentions the town or a place near it. 8 to 20 prompts; 12 recommended.
"""

import re

import ai_niche
import ai_questions
import evidence

RECOMMENDED, MIN_PROMPTS, MAX_PROMPTS = 20, 8, 30
ANGLE_CAP = 3                    # at most this many prompts of one angle in the recommended set, so it covers the hotel's market and not one theme

# The tracked prompts come in kinds, and which kinds matter depends on the hotel (an airport hotel lives on 'places near it', a country house on 'who it is for' and 'what it offers').
# (key, title, what it covers, how many of the recommended set it aims for)
SECTIONS = [
    ("place", "Where the hotel is", "The town or neighbourhood, the price level and the kind of stay the area is known for.", 4),
    ("near", "Places near the hotel", "Airports, stations, venues, business parks and landmarks that guests travel to.", 5),
    ("who", "Who it is for", "Kinds of traveller and occasion: business trips, meetings, families, couples, weddings, groups.", 5),
    ("offer", "What it offers", "Facilities guests search for by name: spa, pool, restaurant, parking, dogs welcome.", 3),
    ("style", "How people ask", "Real needs written the way people type them: a short search, or a chatty request to an assistant.", 3),
    ("own", "Your own prompts", "Prompts you added that do not fit a kind above.", 0),
]
SECTION_KEYS = [k for k, *_r in SECTIONS]
_ANGLE_SECTION = {
    "Neighbourhood": "place", "Price level": "place", "City breaks": "place", "Luxury": "place", "Value for money": "place", "Character and heritage": "place", "Traveller intent": "place",
    "Near a venue": "near", "Near a landmark": "near", "Near a place": "near", "Airport": "near", "Near transport": "near",
    "Business travel": "who", "Meetings and events": "who", "Families": "who", "Couples": "who", "Weddings": "who", "Groups": "who", "Long stays": "who", "Accessibility": "who",
    "Spa and wellness": "offer", "Dining": "offer", "Parking": "offer", "Facilities": "offer", "EV charging": "offer", "Pet-friendly": "offer",
    "Short search": "style", "Conversational": "style",
}
_TEXT_SECTION = [
    ("near", r"\b(?:near|nearest|close to|closest|walking distance|minutes? from|airport|station|terminal|venue|stadium|arena|museum|park|circuit|racecourse|business park)\b"),
    ("who", r"\b(?:business|meetings?|conferences?|workshops?|famil\w*|kids|child\w*|couples?|romantic|wedding\w*|honeymoon|groups?|teams?|solo|anniversar\w*|accessib\w*|wheelchair)\b"),
    ("offer", r"\b(?:spas?|pools?|swim\w*|gym|restaurants?|dining|breakfast|bars?|parking|ev charg\w*|dogs?|pets?|terraces?|gardens?|views?)\b"),
]


def section_of(p):
    """Which kind of prompt this is (a key of SECTIONS). A section someone chose is kept; otherwise it is worked out from the prompt's angle, its style, then its words."""
    sec = (p or {}).get("section")
    if sec in SECTION_KEYS:
        return sec
    if (p or {}).get("style") in ("short search", "conversational"):
        return "style"
    a = (p or {}).get("angle") or ""
    if a in _ANGLE_SECTION:
        return _ANGLE_SECTION[a]
    t = (p or {}).get("text") or ""
    for key, rx in _TEXT_SECTION:
        if re.search(rx, t, re.I):
            return key
    return "own" if (p or {}).get("source") == "own" else "place"


def by_section(prompts):
    """-> [(key, title, blurb, [prompts in that section])] in the SECTIONS order, every section listed (empty ones too)."""
    groups = {k: [] for k in SECTION_KEYS}
    for p in prompts or []:
        groups[section_of(p)].append(p)
    return [(k, t, b, groups[k]) for k, t, b, _n in SECTIONS]

WARNING = ("Choose prompts you are happy to keep for a while. Each week we ask the same prompts and count how often your hotel is named, which is how we show whether it is coming up more often. "
           "If you change the prompts later, results from before and after the change cannot be compared directly, so it becomes much harder to tell whether the hotel is really improving.")
GUIDE = (f"We recommend {RECOMMENDED} prompts (anything from {MIN_PROMPTS} to {MAX_PROMPTS} works). Each one is asked several times in every check, so a single lucky or unlucky answer does not mislead. "
         "Good prompts sound like a real traveller, mention the town or a place near the hotel, and never name your hotel.")


def recommend_set(pool, hotel="", n=RECOMMENDED, exclude=()):
    """
    Pick n prompts from the audit's question pool that together cover the hotel's market. Not the first n: core prompts first, each SECTION up to its share, at most ANGLE_CAP of one angle, at most three
    style variants, no near-duplicates; then, when the hotel has few prompts of some kind, the rest from whatever is left. `exclude`: texts already in the set (a top-up never repeats them).
    pool: [{text, angle, why, priority, style, kind}] -> [{id, text, angle, why, style, section, source: 'recommended'}], in SECTIONS order.
    """
    cands = [q for q in pool or [] if q.get("kind", "niche") == "niche" and q.get("text")]
    cands.sort(key=lambda q: (q.get("priority") != "core", q.get("style") in ("short search", "conversational")))
    quota = {k: q for k, _t, _b, q in SECTIONS}
    scale = n / max(1, sum(quota.values()))
    quota = {k: max(1, round(v * scale)) if v else 0 for k, v in quota.items()}
    chosen, per_angle, per_sec = [], {}, {}
    taken = list(exclude or [])

    def ok(q):
        if any(q["text"] == t or ai_questions._similar(q["text"], t, 0.6) for t in taken):
            return False
        return not (hotel and not ai_niche._safe(q["text"] if q["text"].endswith("?") else q["text"] + "?", hotel))

    def take(q, sec):
        chosen.append({"text": q["text"], "angle": q.get("angle") or "Other", "why": q.get("why") or "", "style": q.get("style") or "", "section": sec, "source": "recommended"})
        taken.append(q["text"])
        per_angle[q.get("angle") or "Other"] = per_angle.get(q.get("angle") or "Other", 0) + 1
        per_sec[sec] = per_sec.get(sec, 0) + 1

    for q in cands:                                              # first pass: each kind up to its share
        if len(chosen) >= n:
            break
        sec = section_of(q)
        if per_sec.get(sec, 0) >= quota.get(sec, 0) or per_angle.get(q.get("angle") or "Other", 0) >= ANGLE_CAP or not ok(q):
            continue
        take(q, sec)
    for q in cands:                                              # still short (a hotel with few kinds): fill from what is left, whatever the kind
        if len(chosen) >= n:
            break
        if ok(q):
            take(q, section_of(q))
    order = {k: i for i, k in enumerate(SECTION_KEYS)}
    chosen.sort(key=lambda c: order[c["section"]])
    return [{"id": f"p{i}", **c} for i, c in enumerate(chosen, 1)]


def place_words(city, anchors=()):
    words = set(re.findall(r"[a-z0-9]{3,}", evidence.fold((city or "").replace("/", " "))))
    for a in anchors or []:
        words |= set(re.findall(r"[a-z0-9]{4,}", evidence.fold(a.get("name", "") if isinstance(a, dict) else str(a))))
    return words


def check_prompt(text, hotel, city, anchors=()):
    """-> (cleaned text, error or ''). The rules every prompt must pass, whoever wrote it."""
    t = " ".join(str(text or "").split())
    if not 20 <= len(t) <= 220:
        return t, "Use between 20 and 220 characters."
    if not ai_niche._safe(t if t.endswith("?") else t + "?", hotel):
        return t, "Do not name your hotel. These prompts test whether an assistant suggests you without being asked."
    if place_words(city, anchors) and not (set(re.findall(r"[a-z0-9]{3,}", evidence.fold(t))) & place_words(city, anchors)):
        return t, f"Mention the town ({(city or '').split('/')[0].split(',')[0].strip() or 'the hotel town'}) or a place near the hotel, so the answer is about your market."
    return t, ""


def check_set(prompts, hotel, city, anchors=()):
    """-> (clean prompts, errors [{i, msg}]). Also catches near-duplicates and a set that is too big."""
    out, errors = [], []
    for i, p in enumerate(prompts or []):
        t, err = check_prompt((p or {}).get("text"), hotel, city, anchors)
        if not err and any(ai_questions._similar(t, o["text"], 0.8) for o in out):
            err = "This is almost the same as another prompt."
        if err:
            errors.append({"i": i, "msg": err})
        out.append({"id": (p or {}).get("id") or f"p{i + 1}", "text": t, "angle": (p or {}).get("angle") or "Your own", "why": (p or {}).get("why") or "Written by you.",
                    "style": (p or {}).get("style") or "", "source": (p or {}).get("source") or "own", "section": section_of(p)})
    if len(out) > MAX_PROMPTS:
        errors.append({"i": None, "msg": f"Use at most {MAX_PROMPTS} prompts."})
    return out, errors


def anchors_from(*sets):
    """The places the current prompts are built around ('near Palais Garnier'), so a hotel's own prompt about one of them passes the 'mention a place' rule."""
    out = []
    for st in sets:
        for p in (st or {}).get("prompts") or []:
            for m in re.finditer(r"\b(?:near|around|by|from|at|close to)\s+((?:the\s+)?[A-Z][\w'\u2019-]+(?:\s+[A-Z][\w'\u2019-]+)*)", p.get("text", "")):
                out.append({"name": re.sub(r"^the\s+", "", m.group(1), flags=re.I)})
    return out


def pool_from_report(report):
    """The audit's question pool as stored in the report (the recommended prompts come from it); older reports fall back to their frozen benchmark prompts."""
    qs = ((report or {}).get("question_plan") or {}).get("questions")
    if qs:
        return qs
    return [{"text": b["text"], "angle": b.get("angle"), "why": b.get("why"), "priority": "core", "kind": "niche"} for b in ((report or {}).get("benchmark") or {}).get("prompts") or [] if b.get("text")]


def latest_pool(db, hotel):
    """The question pool of the hotel's newest saved check that has one (scraps of page text left out), else its frozen benchmark prompts. [] when there is nothing."""
    import placenames
    try:
        for r in db.hotel_runs(hotel["hotel_key"]):
            pool = [q for q in pool_from_report(db.get_report(r["id"])) if not placenames.has_scrap(q.get("text"))]
            if pool:
                return pool
        return [{"text": b["text"], "angle": b.get("angle"), "why": b.get("why"), "priority": "core", "kind": "niche"} for b in db.get_benchmark(hotel["hotel_key"]) if b.get("text") and not placenames.has_scrap(b["text"])]
    except Exception:  # noqa: BLE001
        return []


def ensure_draft(db, hotel, report):
    """After a check: a hotel with no prompt set yet gets a RECOMMENDED draft to review and confirm. Returns the draft id or None."""
    if db.prompt_sets(hotel["id"]):
        return None
    chosen = recommend_set(pool_from_report(report), hotel["name"])
    if len(chosen) < 3:
        return None
    return db.insert_prompt_set(hotel["id"], "draft", chosen, "recommended")


def ensure_from_history(db, hotel):
    """
    A hotel registered AFTER its audits were saved has runs but no prompt set (a set is made when an audit is saved). When it has none, build the recommended draft from its newest saved audit that has prompts
    (its question pool, or the benchmark prompts that audit froze), leaving out any prompt built on a scrap of page text. Returns the draft id, or None. Never raises.
    """
    try:
        if db.prompt_sets(hotel["id"]):
            return None
        import placenames
        for r in db.hotel_runs(hotel["hotel_key"]):
            rep = db.get_report(r["id"])
            pool = [q for q in pool_from_report(rep) if not placenames.has_scrap(q.get("text"))]
            chosen = recommend_set(pool, hotel["name"])
            if len(chosen) >= 3:
                return db.insert_prompt_set(hotel["id"], "draft", chosen, "recommended")
        pool = [{"text": b["text"], "angle": b.get("angle"), "why": b.get("why"), "priority": "core", "kind": "niche"} for b in db.get_benchmark(hotel["hotel_key"]) if b.get("text") and not placenames.has_scrap(b["text"])]
        chosen = recommend_set(pool, hotel["name"])
        return db.insert_prompt_set(hotel["id"], "draft", chosen, "recommended") if len(chosen) >= 3 else None
    except Exception:  # noqa: BLE001 - the dashboard still shows
        return None


def state(db, hotel):
    """What the Prompts tab shows: {"active": confirmed set or None, "draft": draft or None, "history": [...]}."""
    sets = db.prompt_sets(hotel["id"])
    conf = [s for s in sets if s["status"] == "confirmed"]
    draft = next((s for s in sets if s["status"] == "draft"), None)
    return {"active": max(conf, key=lambda s: s["version"]) if conf else None, "draft": draft, "history": sorted(conf, key=lambda s: -s["version"])}


def handle(db, hotel, who, payload, anchors=()):
    """
    The one place prompt sets change. payload: {"action": save | confirm | start_change | discard, "prompts": [...], "agree": bool, "agree_change": bool}.
    -> (ok, {"error"?, "errors"?, "message"?}). Nothing is saved when a rule is broken.
    """
    action = (payload or {}).get("action")
    st = state(db, hotel)
    if action == "start_change":
        if not st["active"]:
            return False, {"error": "There is no confirmed set to change yet."}
        if not st["draft"]:
            db.insert_prompt_set(hotel["id"], "draft", st["active"]["prompts"], who, base_version=st["active"]["version"])
        return True, {"message": "A copy is ready to edit. Your confirmed prompts stay in use until you confirm the new set."}
    if action == "discard":
        if st["draft"] and st["active"]:
            db.delete_prompt_set(st["draft"]["id"])
        return True, {"message": "The changes were discarded."}
    if action == "top_up":
        if not st["draft"] and st["active"]:
            return False, {"error": "Click 'Change these prompts' first; the confirmed set is never changed directly."}
        given = [p for p in ((payload or {}).get("prompts") or []) if (p or {}).get("text", "").strip()]
        want = max(0, RECOMMENDED - len(given))
        if not want:
            return False, {"error": f"The set already has {len(given)} prompts, the recommended number or more."}
        extra = recommend_set(latest_pool(db, hotel), hotel["name"], n=want, exclude=[p["text"] for p in given])
        if not extra:
            return False, {"error": "The latest check has no more prompts to recommend that are not already here. Add your own, or try again after the next check."}
        merged = given + [dict(e, id=f"r{len(given) + i}") for i, e in enumerate(extra, 1)]
        prompts, _errors = check_set(merged, hotel["name"], hotel["city"], list(anchors or []) + anchors_from(st["draft"], st["active"], {"prompts": merged}))
        if st["draft"]:
            db.update_prompt_set(st["draft"]["id"], prompts=prompts)
        else:
            db.insert_prompt_set(hotel["id"], "draft", prompts, who)
        return True, {"message": f"Added {len(extra)} recommended prompt{'s' if len(extra) != 1 else ''}. Nothing changes until you confirm."}
    if action not in ("save", "confirm"):
        return False, {"error": "Unknown action."}
    given = (payload or {}).get("prompts") or []
    anchors = list(anchors or []) + anchors_from(st["draft"], st["active"], {"prompts": [p for p in given if (p or {}).get("source") == "recommended"]})      # the places our own recommended prompts are built around always count
    prompts, errors = check_set(given, hotel["name"], hotel["city"], anchors)
    if action == "save":
        hard = [e for e in errors if e["i"] is None]
        if hard:
            return False, {"error": hard[0]["msg"], "errors": errors}
        if not prompts:
            return False, {"error": "Add at least one prompt."}
        if st["draft"]:
            db.update_prompt_set(st["draft"]["id"], prompts=prompts)
        else:
            db.insert_prompt_set(hotel["id"], "draft", prompts, who, base_version=(st["active"] or {}).get("version"))
        return True, {"message": "Saved as a draft. It is not used until you confirm it.", "errors": errors}
    # confirm
    if errors:
        return False, {"error": "Fix the prompts marked in red first.", "errors": errors}
    if not MIN_PROMPTS <= len(prompts) <= MAX_PROMPTS:
        return False, {"error": f"Use between {MIN_PROMPTS} and {MAX_PROMPTS} prompts ({len(prompts)} now)."}
    if not (payload or {}).get("agree"):
        return False, {"error": "Tick the box to say you are happy with these prompts."}
    changing = bool(st["active"]) and [p["text"] for p in prompts] != [p["text"] for p in st["active"]["prompts"]]
    if changing and not (payload or {}).get("agree_change"):
        return False, {"error": "Tick the second box: you understand that changing prompts makes earlier results harder to compare."}
    if st["active"] and not changing:
        if st["draft"]:
            db.delete_prompt_set(st["draft"]["id"])
        return True, {"message": "Nothing changed: these are the prompts already in use."}
    version = (st["active"]["version"] + 1) if st["active"] else 1
    if st["draft"]:
        db.update_prompt_set(st["draft"]["id"], prompts=prompts, status="confirmed", version=version, confirmed_by=who)
    else:
        sid = db.insert_prompt_set(hotel["id"], "draft", prompts, who)
        db.update_prompt_set(sid, status="confirmed", version=version, confirmed_by=who)
    return True, {"message": f"Confirmed as version {version}. Every check from now on asks these prompts word for word and measures the trend on them."}
