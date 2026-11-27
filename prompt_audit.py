"""
Prompt audit (a diagnostic): for every prompt a stored check asked, what it assumes, what supports that, and whether it is a fair question for measuring ORGANIC discovery.

It reads the report and asks no assistant; it changes no report, no prompt set and no score. Nothing here removes or re-labels a tracked prompt: every finding is a flag with its reason, so a person
decides. Used by the admin page; the same record is what a later change to the measurement would be built on.

For each prompt:
  segment        the guest segment it speaks to (business, families, spa and wellness...), from its angle and wording
  requires       what the wording demands of the hotel: facilities, a price level, a place, with the state of each against what is verified:
                 verified (the fact profile has it at the hotel), partner/nearby, not_offered (the profile says the hotel does not), unverified (nothing says either way)
  scope          how wide a place the guest is searching: town, district, place (near a landmark), region, or none
  realism        flags for wording a traveller would not plausibly type (stacked constraints, exact figures, a quoted claim)
  kind           broad_discovery | guest_intent | experience_specific | effectively_branded | explicitly_branded. 'Effectively branded' is a prompt that does not name the hotel but only this
                 hotel could answer, shown by what the assistants did (it was named in most answers with almost no other hotel beside it) and by how it is worded (a figure, a superlative, a claim
                 about a feature). A distinctive experience is NOT rejected for being distinctive: it is labelled by whether it asks for a category of hotel or assumes the one.
  organic        True where the prompt is a fair test of discovery; 'caution' for effectively branded ones; False for explicitly branded ones.
"""

import re

import evidence

# what a prompt's wording demands. key -> (label, regex, the fact-profile facility that would support it or None when no fact can)
REQUIRES = [
    ("spa", "a spa", r"\bspa\b|wellness|massage|treatment|sauna|steam room", "spa"),
    ("pool", "a pool", r"\bpool\b|swimming|splash", "pool"),
    ("gym", "a gym", r"\bgym\b|fitness", "gym"),
    ("parking", "parking", r"\bparking\b|car park", "parking"),
    ("ev", "EV charging", r"\bEV\b|electric vehicle|charging", "ev"),
    ("pets", "dogs or pets welcome", r"\bdogs?\b|\bpets?\b|dog[- ]friendly", "pets"),
    ("meeting_rooms", "meeting rooms", r"meeting (?:rooms?|space)|conference|workshop|off-?site|team meeting", "meeting_rooms"),
    ("weddings", "weddings", r"wedding", "weddings"),
    ("restaurant", "a restaurant", r"restaurant|dining|game restaurant|wine cellar|food lover", "restaurant"),
    ("family", "family facilities", r"\bfamil(?:y|ies)\b|kids|children|child|toddler|splash pool", "family"),
    ("accessible", "accessible rooms", r"wheelchair|step-free|accessible", "accessible"),
    ("airport_transfer", "an airport shuttle", r"shuttle|airport transfer", "airport_transfer"),
    ("wifi", "Wi-Fi", r"wi-?fi", "wifi"),
    ("breakfast", "an early breakfast", r"early breakfast|breakfast", None),
    ("desk", "a proper desk", r"\bdesk\b", None),
    ("cinema", "a cinema room", r"cinema", None),
]
SEGMENTS = [("business", r"business|meeting|conference|workshop|team|corporate"), ("families", r"famil|kids|children|child"), ("couples", r"romantic|couple|anniversary|honeymoon|for two"),
            ("wellness", r"\bspa\b|wellness|massage|sauna"), ("weddings", r"wedding"), ("airport", r"airport|flying|flight|layover"), ("food", r"restaurant|dining|food|wine|gourmet"),
            ("pets", r"\bdogs?\b|\bpets?\b"), ("leisure break", r"weekend|break|getaway|short stay|holiday|escape"), ("activity", r"surf|golf|safari|hiking|walk|wildlife|ski|bike|birdwatch")]
TIER_WORDS = {"luxury": r"luxury|5[- ]star|five[- ]star|splurge|palace", "upscale": r"upscale|4[- ]star|four[- ]star", "midscale": r"mid-?range|3[- ]star|three[- ]star", "budget": r"cheap|budget|bargain|hostel"}
STOP = set("the a an of in on at for to with and or near is are which what where best hotel hotels places place stay stays good great that have has has for your our their from by as it its be do you i we my".split())
_NEARPLACE = re.compile(r"\b(?:near|closest to|close to|walking distance (?:of|to|from)|right by|next to|view over|around)\s+(?:the\s+)?([A-Z][\w'’.-]*(?:[ ,]+[A-Z][\w'’.-]*){0,4})")
_FIG = re.compile(r"\b\d[\d,.]*\s?(?:-?bottle|people|guests|rooms|m\b|km\b|metres|meters|hectares|acres|beds)|\b\d{2,}\b")
_CLAIM = re.compile(r"largest|biggest|oldest|first|only|award[- ]winning|architect[- ]designed|famous|renowned|unique", re.I)
_KNOWN_FOR = re.compile(r"known for|famous for|with an? |that has|where (?:you can|there is)", re.I)


def _fold(s):
    return evidence.fold(s or "")


def _facility_state(report, key):
    """'on_site' | 'nearby' | 'partner' | 'not_offered' | None, as the stored fact profile holds it: {"status": ..., "relations": [{status, quote, url}...]} for each facility."""
    v = ((report.get("fact_profile") or {}).get("facilities") or {}).get(key)
    if isinstance(v, dict):
        st = v.get("status") or v.get("state")
        if st:
            return st
        rels = [r for r in v.get("relations") or [] if isinstance(r, dict) and r.get("status")]
        if rels:
            import fact_profile
            rels = [{"quote": "", "url": "", "note": "", **r} for r in rels]
            return fact_profile.headline(rels)["status"]
        return None
    return v


def requirements(text, report):
    """-> [{key, label, state, basis}] for what the wording demands. state: verified | partner | nearby | not_offered | unverified."""
    out = []
    mp = report.get("market_profile") or {}
    for key, label, rx, fkey in REQUIRES:
        if not re.search(rx, text or "", re.I):
            continue
        if fkey is None:
            out.append({"key": key, "label": label, "state": "unverified", "basis": "no verified fact can show this: the hotel's profile does not record it"})
            continue
        st = _facility_state(report, fkey)
        if st is None and not (report.get("fact_profile") or {}).get("facilities"):
            feats = [f for f in (report.get("question_plan") or {}).get("facts") or [] if f.get("kind") == "feature" and fkey.replace("_", " ") in (f.get("text") or "")]
            st = "on_site" if feats else None
            basis = "its own pages show it strongly (the verified fact profile was not built for this check)" if feats else "the check holds no fact profile and the pages do not show it"
        else:
            basis = "the verified fact profile says " + (st or "nothing about it")
        mapped = {"on_site": "verified", "partner": "partner", "nearby": "nearby", "not_offered": "not_offered"}.get(st, "unverified")
        out.append({"key": key, "label": label, "state": mapped, "basis": basis})
    tier = (mp.get("tier") or {}).get("key")
    for tk, rx in TIER_WORDS.items():
        if re.search(rx, text or "", re.I):
            if tier == tk:
                state, basis = "verified", f"the hotel's price level is {tk} ({(mp.get('tier') or {}).get('why', '')[:80]})"
            elif tier:
                state, basis = "not_offered", f"the prompt says {tk}; the hotel's price level is {tier}"
            else:
                state, basis = "unverified", "the hotel's price level is not known"
            out.append({"key": f"tier_{tk}", "label": f"{tk} price level", "state": state, "basis": basis})
            break
    for m in _NEARPLACE.finditer(text or ""):
        place = m.group(1).strip(" ,")
        anchors = [a for a in (report.get("question_plan") or {}).get("anchors") or [] if isinstance(a, dict)] + [a for a in mp.get("anchors") or [] if isinstance(a, dict)]
        hit = next((a for a in anchors if a.get("name") and (_fold(a["name"]) in _fold(place) or _fold(place) in _fold(a["name"]))), None)
        city = _fold(((report.get("meta") or {}).get("city") or "").split(",")[0])
        if _fold(place) == city:
            continue
        if hit:
            out.append({"key": "place", "label": f"near {place}", "state": "verified", "basis": f"{hit['name']} is {hit.get('km') or hit.get('distance')} from the hotel ({hit.get('source', 'the check')})"})
        else:
            out.append({"key": "place", "label": f"near {place}", "state": "unverified", "basis": "no measured distance to this place is recorded"})
        break
    return out


_REGION_WORDS = re.compile(r"\b(?:southern|northern|south|north|east|west|eastern|western)\b|\bcoast\b|\bcounty\b|\bregion\b|\bshire\b", re.I)
_IN_PLACE = re.compile(r"\b(?:in|across|around|throughout)\s+(?:the\s+)?([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3})")


def scope_of(text, report):
    """-> 'place' (near a named landmark) | 'district' | 'region' (a wider area than the hotel's town) | 'town' | 'none': how wide a place the traveller is searching."""
    meta, mp = report.get("meta") or {}, report.get("market_profile") or {}
    city = _fold((meta.get("city") or "").split(",")[0])
    t = _fold(text)
    m = _NEARPLACE.search(text or "")
    if m and _fold(m.group(1)) != city:
        return "place"
    if mp.get("district") and _fold(mp["district"]) in t:
        return "district"
    in_city = bool(city and re.search(r"\b" + re.escape(city) + r"\b", t))
    prof = meta.get("profile") or {}
    named = [_fold(r) for r in (prof.get("region"), prof.get("area")) if r]
    other = next((_fold(x.group(1)) for x in _IN_PLACE.finditer(text or "") if _fold(x.group(1)) != city), None)
    if not in_city and (any(r and r in t for r in named) or other or _REGION_WORDS.search(text or "")):
        return "region"
    return "town" if in_city else "none"


def segment_of(text, angle=""):
    t = f"{angle} {text}"
    found = [k for k, rx in SEGMENTS if re.search(rx, t, re.I)]
    return found[0] if found else "general"


def realism(text):
    """Flags for wording a traveller would not plausibly type. -> [str]"""
    flags = []
    if _FIG.search(text or ""):
        flags.append("an exact figure (" + _FIG.search(text).group(0).strip() + ") that only the hotel's own marketing would state")
    if _CLAIM.search(text or "") and _KNOWN_FOR.search(text or ""):
        flags.append("repeats a claim about the hotel (" + _CLAIM.search(text).group(0).lower() + ")")
    n = sum(1 for _k, _l, rx, _f in REQUIRES if re.search(rx, text or "", re.I))
    if n >= 3:
        flags.append(f"stacks {n} requirements in one question")
    if len(text or "") > 150:
        flags.append("very long for a traveller's question")
    return flags


def _answer_facts(report, qid, items):
    """From what the assistants did for this prompt: answers, how many named the hotel, and the distinct OTHER hotels listed beside it."""
    ex = (report.get("ai_insights") or {}).get("extracted_answers") or {}
    answers = [i for i in items if (i.get("qid") or i.get("id")) == qid]
    named = sum(1 for i in answers if i.get("mentioned"))
    others, listed, read = set(), [], 0
    hotel = (report.get("meta") or {}).get("hotel") or ""
    city = (report.get("meta") or {}).get("city") or ""
    import hotelname
    for a in answers:
        names = ex.get(a["id"])
        if names is None:
            continue
        read += 1
        listed.append(len(names))
        for h in names:
            if not hotelname.mentioned(h.get("name") or "", hotel, city):
                others.add(evidence.fold(h.get("name") or ""))
    return {"answers": len(answers), "named": named, "read": read, "others": len(others), "avg_listed": round(sum(listed) / len(listed), 1) if listed else None}


def kind_of(text, scope, req, facts, names_hotel, flags):
    """-> (kind, why)."""
    if names_hotel:
        return "explicitly_branded", "the prompt contains the hotel's name"
    fig, claim = any("exact figure" in f for f in flags), any("claim" in f for f in flags)
    shape = fig or claim or bool(re.search(r"known for|largest|award", text or "", re.I))
    converged = facts["answers"] and facts["read"] and facts["named"] / facts["answers"] >= 2 / 3 and facts["others"] <= 1 and (facts["avg_listed"] or 9) <= 2.0
    if converged and shape:
        return "effectively_branded", "worded around a feature only this hotel has, and the assistants named it in most answers with almost no other hotel beside it"
    if converged:
        return "effectively_branded", "the assistants named this hotel in most answers with almost no other hotel beside it: the wording leaves it as the only candidate"
    if shape:
        return "experience_specific", "asks for a distinctive experience; other hotels are named for it" if facts["read"] else "asks for a distinctive experience (no analysed answers to show whether others fit)"
    if re.search(r"best hotels? in|where should i stay|good value|do guests rate|places to stay in and around|first time", text or "", re.I) and not req:
        return "broad_discovery", "an ordinary question that suits any hotel in the place"
    return "guest_intent", "asks for a kind of stay a traveller has in mind"


def audit(report, limit=80):
    """-> {"prompts": [...], "summary": {...}} for a stored report. Never raises on a partial report."""
    report = report or {}
    ai = report.get("ai_sample") or {}
    items = [i for i in ai.get("items") or [] if i.get("kind") != "direct" and i.get("answer")]
    plan = {q.get("id"): q for q in (report.get("question_plan") or {}).get("questions") or []}
    by_q = {}
    for i in items:
        q = i.get("qid") or i.get("id")
        by_q.setdefault(q, {"id": q, "text": i["text"], "kind_asked": i.get("kind"), "source": i.get("source") or (plan.get(q) or {}).get("source") or "", "priority": i.get("priority") or (plan.get(q) or {}).get("priority") or "",
                            "angle": i.get("angle") or (plan.get(q) or {}).get("angle") or "", "why": i.get("why") or (plan.get(q) or {}).get("why") or "", "names_hotel": bool(i.get("names_hotel")), "n": 0})
        by_q[q]["n"] += 1
    rows = []
    for q in list(by_q.values())[:limit]:
        facts = _answer_facts(report, q["id"], items)
        req = requirements(q["text"], report)
        flags = realism(q["text"])
        scope = scope_of(q["text"], report)
        kind, why = kind_of(q["text"], scope, req, facts, q["names_hotel"], flags)
        problems = [f"{r['label']}: {r['basis']}" for r in req if r["state"] == "not_offered"]
        unverified = [r["label"] for r in req if r["state"] == "unverified"]
        organic = False if kind == "explicitly_branded" else "caution" if kind == "effectively_branded" else True
        rows.append({"id": q["id"], "text": q["text"], "tracked": q["source"] == "benchmark" or q["priority"] == "core", "source": q["source"], "angle": q["angle"], "segment": segment_of(q["text"], q["angle"]),
                     "scope": scope, "requires": req, "contradicted": problems, "unverified": unverified, "realism": flags, "kind": kind, "kind_why": why, "organic": organic,
                     "named": facts["named"], "answers": facts["answers"], "others_named": facts["others"], "avg_listed": facts["avg_listed"], "why_asked": q["why"][:160],
                     "flag": bool(problems or unverified or flags or kind in ("effectively_branded", "explicitly_branded"))})
    tracked = [r for r in rows if r["tracked"]]
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"prompts": rows, "summary": {"prompts": len(rows), "tracked_or_core": len(tracked), "kinds": counts, "flagged": sum(1 for r in rows if r["flag"]),
                                         "contradicted": sum(1 for r in rows if r["contradicted"]), "unverified": sum(1 for r in rows if r["unverified"]),
                                         "caution_effectively_branded": sum(1 for r in rows if r["organic"] == "caution")}}


def _rate(rows):
    named, asked = sum(r["named"] for r in rows), sum(r["answers"] for r in rows)
    return {"prompts": len(rows), "named": named, "asked": asked, "pct": round(100 * named / asked) if asked else None}


def breakdown(report):
    """
    The same answers the headline figure rests on, grouped three ways (read-only, nothing replaces the headline): by the width of the place searched, by kind of prompt, and by segment. Each group says
    how many DISTINCT prompts and how many answers stand behind it. -> {"headline", "by_scope", "by_kind", "by_segment", "what_if"}.
    what_if: the same figure without the prompts that rest on conditions the facts contradict or cannot confirm, and without effectively branded ones.
    """
    rows = [r for r in audit(report, limit=400)["prompts"] if not r["kind"] == "explicitly_branded"]
    groups = {}
    for dim in ("scope", "kind", "segment"):
        g = {}
        for r in rows:
            g.setdefault(r[dim], []).append(r)
        groups["by_" + dim] = {k: _rate(v) for k, v in sorted(g.items())}
    unsupported = [r for r in rows if r["contradicted"] or r["unverified"]]
    branded = [r for r in rows if r["kind"] == "effectively_branded"]
    drop = {id(r) for r in unsupported} | {id(r) for r in branded}
    return {"headline": _rate(rows), **groups,
            "what_if": {"without_unsupported": _rate([r for r in rows if id(r) not in {id(x) for x in unsupported}]), "without_effectively_branded": _rate([r for r in rows if id(r) not in {id(x) for x in branded}]),
                        "organic_only": _rate([r for r in rows if id(r) not in drop]), "unsupported_prompts": len(unsupported), "effectively_branded_prompts": len(branded)}}


_AUDIENCE_FACILITY = {"wellness": ("spa", "pool"), "meetings": ("meeting_rooms",), "weddings": ("weddings",), "food": ("restaurant",), "pets": ("pets",), "accessible": ("accessible",), "ev": ("ev",),
                      "family": ("family",)}


def audience_status(report):
    """
    The audiences a check planned prompts for, each placed in one of four states, WITHOUT deciding the operator is wrong:
      verified              the site or the fact profile shows the hotel serves it
      operator_confirmed    the operator says so; nothing on the site or in the fact profile shows it. This may be a market the hotel does not serve, or one the site describes badly: only the operator can say.
      contradicted          the fact profile says the hotel does not offer what the audience needs (not_offered)
      aspirational          only when the operator has marked it as a target to grow; no such mark is recorded yet, so none is placed here
    -> [{key, label, level, state, why}]
    """
    mp = report.get("market_profile") or {}
    out = []
    for a in mp.get("audiences") or []:
        key, level = a.get("key"), a.get("level")
        need = _AUDIENCE_FACILITY.get(key) or ()
        states = [_facility_state(report, f) for f in need]
        if any(s == "not_offered" for s in states) and need and all(s in ("not_offered", None) for s in states):
            state, why = "contradicted", "the fact profile says the hotel does not offer " + " or ".join(need).replace("_", " ")
        elif level == "stated":
            ok = any(s in ("on_site", "partner") for s in states) if need else None
            state, why = ("verified", "stated by the operator, and the fact profile has " + "/".join(f for f, s in zip(need, states) if s in ("on_site", "partner"))) if ok else \
                ("operator_confirmed", "stated by the operator; the site and fact profile do not show it" if need else "stated by the operator; there is no facility to check it against")
        else:
            state, why = "verified", a.get("why") or "the hotel's own pages signal it"
        out.append({"key": key, "label": a.get("label"), "level": level, "state": state, "why": why})
    return out
