"""
The hotel's biggest AI discovery opportunities: the few things worth a general manager's attention, with the evidence behind each, instead of a long list of tasks.

An opportunity is a kind of traveller or search where the hotel is a credible option, the assistant is NOT naming it, and rival hotels are. For each one this gathers, from the audit's own data:
  how often the hotel was named (of how many answers), which comparable hotels were named instead, the reasons the assistant gave for them, the sites it cited, and the differences the evidence shows between those hotels
  and this one, with the recommendations that are the supporting actions.

Credibility comes first: a search only counts as a gap when the kind of traveller fits what the hotel is (its classes and core traveller segments), so a business hotel is not told it is missing from family searches.
The reasons shown are what the assistant SAID and what it CITED, not a claim about how the model works; the report says so. Up to three are returned: the biggest gaps in the hotel's own market, and independent
publications when the sites the assistant cites name rivals and not the hotel.
"""

import re

THEMES = [
    ("business", "Business travellers and conference enquiries", r"business|conference|meeting|workshop|offsite|corporate|team\b", {"business", "conference", "airport", "city_centre"}, r"business|meeting"),
    ("romantic", "Romantic breaks and couples", r"romantic|couple|anniversary|honeymoon|spa break|unwind", {"spa_hotel", "boutique", "luxury", "resort"}, r"romantic|couple|spa"),
    ("family", "Families", r"famil|kids|child", {"family_focused", "resort"}, r"famil"),
    ("airport", "Airport and transit stays", r"airport|flight|layover|stopover", {"airport"}, r"airport"),
    ("dining", "Hotels known for dining", r"restaurant|dining|dinner|eat\b|food", {"luxury", "boutique", "resort"}, r"dining|food"),
    ("luxury", "Luxury and special occasions", r"luxury|splurge|special occasion|palace|5[- ]star|five[- ]star", {"luxury"}, r"luxur"),
    ("value", "Quality for the price", r"value|price|quality for|affordable|cheap|budget|worth", set(), r""),
    ("location", "Hotels near a landmark or area", r"\bnear\b|walking distance|closest|close to|next to|around the", {"city_centre"}, r"location"),
    ("leisure", "City breaks and weekends", r"weekend|city break|long weekend|first visit|where should i stay|best hotels in|looking for", set(), r""),
]
GENERIC_THEMES = {"value", "leisure", "location"}          # fit most hotels: credible by default


def theme_of(text):
    t = (text or "").lower()
    for key, label, rx, _classes, _seg in THEMES:
        if re.search(rx, t):
            return key
    return "leisure"


def _fit(theme, classes, segments):
    """2 = the hotel clearly is this (class or core segment), 1 = fits any hotel, 0 = nothing in the audit says it is this kind of hotel."""
    for key, _label, _rx, cls, seg in THEMES:
        if key != theme:
            continue
        if theme in GENERIC_THEMES:
            return 1
        if cls & classes or (seg and any(re.search(seg, s, re.I) for s in segments)):
            return 2
        return 0
    return 1


def _clean(text):
    """An observation is dropped when the 'proof' it quotes is a menu strip or a list of links, not a sentence from the page."""
    import textutil
    quoted = re.findall(r"[“\"]([^”\"]{12,})[”\"]", text or "")
    bad = [q for q in quoted if textutil.looks_like_nav(q) or textutil.looks_like_list(q)]
    return "" if bad or textutil.looks_like_nav(text) else text


def build(rep, limit=3):
    """-> up to `limit` opportunity dicts, biggest first. Works on a stored report of any age (a missing section just gives fewer)."""
    gap = (rep or {}).get("ai_gap") or {}
    c = (rep or {}).get("consultant") or {}
    markets = [m for m in gap.get("markets") or [] if m.get("kind") in ("niche", "custom", "generic")]
    if gap.get("status") != "ok" or not markets:
        return []
    classes = {x.get("key") for x in (c.get("hotel_class") or {}).get("classes") or []}
    segments = [s.get("label", "") for s in (c.get("traveller") or {}).get("segments") or [] if s.get("relevance", "core") == "core"]
    obs = gap.get("observations") or {}
    arts = gap.get("articles") or []
    recs = c.get("recommendations") or []
    by = {}
    for m in markets:
        th = theme_of(m.get("question", "") + " " + (m.get("angle") or ""))
        by.setdefault(th, []).append(m)
    out = []
    for th, ms in by.items():
        fit = _fit(th, classes, segments)
        asked = sum(m["of"] for m in ms)
        named = sum(m["named"] for m in ms)
        if fit == 0 or asked < 2 or named / asked >= 0.5:
            continue
        label = next(x[1] for x in THEMES if x[0] == th)
        riv = {}
        for m in ms:
            for r in m.get("rivals") or []:
                a = riv.setdefault(r["name"], {"name": r["name"], "answers": 0, "of": 0})
                a["answers"] += r["answers"]
                a["of"] += r["of"]
        rivals = sorted(riv.values(), key=lambda r: -r["answers"])[:3]
        if not rivals:
            continue
        qids = {m["qid"] for m in ms}
        reasons, diffs = [], []
        for q in qids:
            for o in obs.get(q) or []:
                txt = _clean(o.get("text", ""))
                if not txt:
                    continue
                (reasons if o["kind"] == "assistant" else diffs if o["kind"] in ("criterion", "facility", "source") else []).append(txt)
        sources = [{"domain": a["domain"], "title": a.get("title") or a["url"], "url": a["url"], "cited": a.get("cited") or 0, "rivals": a.get("rivals_in") or [], "sponsored": bool(a.get("sponsored"))}
                   for a in sorted(arts, key=lambda a: -(a.get("cited") or 0)) if set(a.get("questions") or []) & qids and a.get("hotel_in") in (None, False)][:3]
        supp = [r for r in recs if (r.get("id", "").startswith("AG-") and any(q in r["id"] for q in qids)) or (th == "business" and r.get("id") in ("FD-events",)) or (th == "romantic" and r.get("id") in ("FD-spa",))
                or r.get("id") in ("SG1",) or (th == "business" and str(r.get("id", "")).startswith("TR-"))]
        score = (asked - named) * (2 if fit == 2 else 1)
        out.append({"key": th, "title": label, "kind": "search", "named": named, "of": asked, "credible": fit == 2, "rivals": rivals, "reasons": reasons[:2], "differences": diffs[:3], "sources": sources,
                    "questions": [m["question"] for m in ms][:3], "supporting": [{"ref": r.get("ref") or r["id"], "title": r.get("short_title") or r["title"]} for r in supp[:4]], "score": score})
    out.sort(key=lambda o: -o["score"])
    top = out[: max(0, limit - 1)]
    # independent publications: sites the assistant cited that name rivals and not this hotel
    pubs = [a for a in arts if a.get("hotel_in") in (None, False) and (a.get("rivals_in") or a.get("opportunity")) and (a.get("cited") or 0) >= 1]
    sg = next((r for r in recs if r.get("id") == "SG1"), None)
    if pubs or sg:
        dom = {}
        for a in pubs:
            d = dom.setdefault(a["domain"], {"domain": a["domain"], "cited": 0, "title": a.get("title") or a["url"], "url": a["url"], "rivals": set(), "sponsored": False})
            d["cited"] += a.get("cited") or 0
            d["rivals"] |= set(a.get("rivals_in") or [])
            d["sponsored"] = d["sponsored"] or bool(a.get("sponsored"))
        sources = [{**d, "rivals": sorted(d["rivals"])[:3]} for d in sorted(dom.values(), key=lambda d: -d["cited"])[:3]]
        if sources or sg:
            top.append({"key": "publications", "title": "Independent travel publications", "kind": "sources", "named": 0, "of": 0, "credible": True, "rivals": [], "reasons": [], "differences": [],
                        "sources": sources, "questions": [], "supporting": [{"ref": sg.get("ref") or sg["id"], "title": sg.get("short_title") or sg["title"]}] if sg else [], "score": 0})
    for o in out[max(0, limit - 1):]:
        if len(top) >= limit:
            break
        top.append(o)
    return top[:limit]


def sentence(o):
    """One plain sentence for a dashboard card."""
    if o["kind"] == "sources":
        names = ", ".join(s["domain"] for s in o["sources"][:3])
        return (f"The assistant cites {names} for hotels like this one, and those pages name rival hotels and not this one." if names else "Independent publications are cited alongside rival hotels.")
    rv = ", ".join(r["name"] for r in o["rivals"][:2])
    return f"This hotel was named in {o['named']} of {o['of']} answers for these searches. {rv} {'was' if len(o['rivals'][:2]) == 1 else 'were'} named instead."
