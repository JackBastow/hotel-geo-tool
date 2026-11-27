"""
Commercial priorities: the few actions most likely to win the hotel bookings, built from what the AI test showed (Paris Marriott review, Nov 2026: 'it doesn't adequately distinguish high-value
opportunities from generic improvements'; the evidence was collected but sat lower down as 'Not named when asked...' observations and 'Worth checking' leads).

Two kinds of play, each resting on repeated evidence from the hotel's OWN market (its tracked and niche searches, never the generic 'best hotels in Paris'):

  source play   a page the assistant cited for two or more of the searches the hotel lost (or cited three times or more), naming rival hotels and not this one, not sponsored:
                get onto it by the honest route (the editor, the listing, the brand's PR for a chain).
  search play   the searches the hotel lost, grouped by what the traveller wanted (business trips, value, weekends...): the hotels of its own level named instead, the reasons the
                assistant gave, and whether the hotel's own pages state the same thing. If they do, the gap is in the sources (the source plays); if they do not, the page to say it on.

The generic findings a play covers fold into it ('Position the hotel for business travellers...', the per-search 'Not named when asked...', the same article suggested twice); findings resting on a
generic town-wide search, and distances to minor attractions no search mentions, drop to low priority. A play is 'Likely' only when its evidence repeats (several searches or answers); one answer is
a lead ('Worth checking'). Nothing here promises a recommendation: it says where the evidence points.
"""

import re

import evidence

RELEVANT = ("niche", "custom")                       # the hotel's own market; 'generic' is the town-wide 'best hotels in X'
LOST = ("not_named", "rarely")
NEAR_LEVEL = {"budget": {"budget", "midscale"}, "midscale": {"budget", "midscale", "upscale"}, "upscale": {"midscale", "upscale", "luxury"}, "luxury": {"upscale", "luxury", "palace"},
              "palace": {"luxury", "palace"}}
# what the traveller wanted, from the angle the question was written for -> (plain label, differentiation themes it covers)
ANGLE = {
    "Business travel": ("business trips", {"business"}), "Meetings and events": ("meetings and events", {"business"}),
    "Price level": ("value for money at the hotel's level", {"value"}), "Value for money": ("value for money at the hotel's level", {"value"}),
    "City breaks": ("weekend and city breaks", {"location"}), "Neighbourhood": ("staying in the hotel's neighbourhood", {"location"}),
    "Near a landmark": ("staying near the places guests come for", {"location"}), "Near a venue": ("staying near the venues guests come for", {"location"}),
    "Near a place": ("staying near the places guests come for", {"location"}), "Near transport": ("easy arrival by train or plane", {"location"}), "Airport": ("airport stays", {"airport"}),
    "Families": ("family stays", {"family"}), "Couples": ("couples and romantic breaks", {"romantic"}), "Spa and wellness": ("spa and wellness breaks", {"romantic"}),
    "Weddings": ("weddings and celebrations", {"weddings"}), "Pet-friendly": ("stays with a dog", {"pets"}), "Accessibility": ("accessible stays", {"accessible"}),
    "Dining": ("eating well at the hotel", {"dining"}), "Character and heritage": ("hotels with character", set()), "Luxury": ("luxury stays", set()),
    "Groups": ("group stays", set()), "Long stays": ("longer stays", set()), "Parking": ("arriving by car", set()), "Facilities": ("the hotel's facilities", set()),
    "Traveller intent": ("the hotel's own kind of stay", set()), "Short search": ("the hotel's own kind of stay", set()),
    "Conversational": ("the hotel's own kind of stay", set()), "Benchmark": ("the hotel's own kind of stay", set()),
}
MAX_SOURCE, MAX_SEARCH = 3, 3


def _generic(m):
    """A town-wide search: asked of every hotel in the town ('best hotels in Paris'), or a baseline town question written when the hotel's facts were thin (ids niche_base*)."""
    return m.get("kind") not in RELEVANT or str(m.get("qid") or "").startswith("niche_base")


def _lost(m):
    return not _generic(m) and m.get("status") in LOST


def _level_ok(rival, tier):
    """Is the rival a hotel of the audited hotel's level (or next to it)? None when its level is not known."""
    k = (rival.get("tier") or {}).get("key")
    if not k or not tier:
        return None
    return k in NEAR_LEVEL.get(tier, {tier})


def _short(q, n=80):
    q = " ".join(str(q or "").split())
    return q if len(q) <= n else q[: n - 3].rstrip() + "..."


_NAME_STOP = {"hotel", "hotels", "hotell", "hôtel", "resort", "house", "suites", "palace", "grand", "boutique", "residence", "collection", "inn", "lodge", "spa", "home", "best", "the"}


def rival_own_site(a):
    """A page on one of the rival hotels' own websites (Eriksberg: 'bestwestern.se' naming only Best Western Hotell Karlshamn): there is nothing to get onto. The domain carries a
    distinctive word of a rival's name, and the page names one or two hotels (a town's tourism site that happens to share a word with a hotel names many)."""
    dom = evidence.fold(a.get("domain") or "").replace("-", "")
    names = a.get("rivals_in") or []
    import competitor_domains
    if any(competitor_domains.name_matches_domain(n, a.get("domain") or "") for n in names):
        return True                                    # the address IS a rival's name ('northcotemanor.co.uk'), however many hotels the page names
    if len(names) > 2 and a.get("lists_hotels") is not False:
        return False
    for n in names:
        whole = re.sub(r"[^a-z0-9]", "", evidence.fold(n))
        if len(whole) >= 6 and whole in dom:
            return True                                # the name run together: 'hotelcasa.nl' is Hotel Casa's own site (Holiday Inn Amsterdam)
        for w in evidence.fold(n).split():
            if len(w) >= 5 and w not in _NAME_STOP and w in dom:
                return True
    # a hotel group's own site under its group name (The Hoxton: imperialhotels.co.uk, 'Conference Venues | ... | Imperial London Hotels', naming only its Royal National Hotel)
    label = dom.split(".")[0]
    if "hotel" in label and names and _site_type(a) not in ("booking_platform", "hotel_directory", "review_platform"):
        return True
    return False


def _site_type(a):
    """What kind of site a cited page is on (sourcetypes): a hotel chain's own site, a booking or review platform, a directory, a tourism body, or another site."""
    try:
        import sourcetypes
        return sourcetypes.classify_domain(a.get("url") or ("https://" + (a.get("domain") or "")))[0]
    except Exception:  # noqa: BLE001
        return "other"


def source_plays(gap, rec_fn, conf):
    """Pages the assistant used for the hotel's own lost searches that name its rivals and not it. -> [recommendation]"""
    markets = {m["qid"]: m for m in gap.get("markets") or []}
    lost = {q for q, m in markets.items() if _lost(m)}
    found = []
    for a in gap.get("articles") or []:
        st = _site_type(a)
        if a.get("hotel_in") or a.get("sponsored") or not a.get("rivals_in") or rival_own_site(a) or st in ("hotel_group", "own_website", "social", "video", "map_or_open_data"):
            continue
        qs = [q for q in a.get("questions") or [] if q in lost]
        cited = int(a.get("cited") or 0)
        if not qs or not (len(qs) >= 2 or cited >= 3):
            continue
        found.append((len(qs), cited, a, qs))
    found.sort(key=lambda t: (-t[0], -t[1], t[2].get("domain") or ""))
    out, seen = [], set()
    for n_q, cited, a, qs in found:
        if a.get("domain") in seen or len(out) >= MAX_SOURCE:
            continue
        seen.add(a.get("domain"))
        sure = n_q >= 2 and cited >= 3
        rivals = a["rivals_in"][:3]
        q1 = markets[qs[0]]["question"]
        editorial = st not in ("booking_platform", "hotel_directory", "government_register", "awards_body") and (a.get("kind") or "").lower() not in ("booking and comparison site", "booking site", "review site", "directory")
        route = (("For a chain hotel this is normally the brand's PR or regional marketing team. " if gap.get("chain") else "")
                 + ("Write to the publication's editor with accurate, factual information about what the hotel offers and where it is; ask how hotels are chosen for the list. Do not pay for a "
                    "placement presented as editorial." if editorial else "Claim or update the hotel's listing there, with the same facts as the hotel's own website."))
        r = rec_fn(f"CP-S{len(out) + 1}", "authority",
                   f"Get the hotel onto {a.get('domain')}: the AI used it for {n_q} of the hotel's own searches, and it names {', '.join(rivals[:2])}, not the hotel",
                   f"When asked “{_short(q1)}”" + (f" and {n_q - 1} similar search{'es' if n_q > 2 else ''} for the hotel's own market" if n_q > 1 else "") + f", the assistant cited “{_short(a.get('title'), 90)}”"
                   + (f" ({cited} times)" if cited > 1 else "") + f". The page names {', '.join(rivals)} and does not mention the hotel."
                   + (f" It is dated {a['published']}." if a.get("published") else ""),
                   "The pages an assistant cites for a search are where it learns which hotels to name. Being fairly described on the page it uses for the hotel's own market is the most direct, honest "
                   "way to be in the answer; it is not a guarantee.",
                   [{"url": a.get("url", ""), "snippet": a.get("rival_sentence") or a.get("passage") or a.get("title") or ""}],
                   route + " Check the page is current first, and keep every fact identical to the hotel's own website.",
                   "high", "medium", confidence=conf["INFER"] if sure else conf["EXPER"], team="PR", source="commercial", tag="CP-S",
                   short_title=f"Get onto {a.get('domain')} (used for {n_q} of your searches)", summary=a.get("url", ""))
        r["kind_hint"], r["play"] = "opportunity", {"kind": "source", "url": a.get("url"), "questions": qs, "rivals": rivals, "cited": cited}
        out.append(r)
    return out


def search_plays(gap, src_plays, rec_fn, conf):
    """The searches the hotel lost, grouped by what the traveller wanted, with the same-level hotels named instead and what the evidence says about the difference. -> [recommendation]"""
    tier = gap.get("hotel_tier")
    criteria = gap.get("criteria") or {}
    groups = {}
    for m in gap.get("markets") or []:
        if not _lost(m):
            continue
        groups.setdefault(m.get("angle") or "Traveller intent", []).append(m)
    rows = []
    for angle, ms in groups.items():
        asked = sum(int(m.get("of") or 0) for m in ms)
        named = sum(int(m.get("named") or 0) for m in ms)
        tally = {}
        for m in ms:
            for rv in m.get("rivals") or []:
                if _level_ok(rv, tier) is False:
                    continue                                   # another category (a palace hotel for an upscale one) is not who it competes with
                t = tally.setdefault(rv["name"], {"name": rv["name"], "answers": 0, "reasons": [], "level": _level_ok(rv, tier)})
                t["answers"] += int(rv.get("answers") or 0)
                t["reasons"] += [x for x in rv.get("reasons") or [] if x not in t["reasons"]][:2]
        winners = sorted(tally.values(), key=lambda t: (-t["answers"], t["name"]))[:3]
        if not winners:
            continue
        themes = {}
        for m in ms:
            for c in criteria.get(m["qid"]) or []:
                th = themes.setdefault(c["theme"], {"label": c["label"], "count": 0, "hotel": c.get("hotel") or {}})
                th["count"] += int(c.get("count") or 0)
        rows.append((asked - named, asked, angle, ms, winners, sorted(themes.values(), key=lambda x: -x["count"])[:3]))
    rows.sort(key=lambda t: (-t[0], t[2]))
    out = []
    for lost_n, asked, angle, ms, winners, themes in rows[:MAX_SEARCH]:
        label = ANGLE.get(angle, ("searches like these", set()))[0]
        sure = len(ms) >= 2 and asked >= 4
        reasons = "; ".join(f"{w['name']}: {w['reasons'][0]}" for w in winners if w["reasons"])[:400]
        has = [t for t in themes if (t["hotel"].get("state") in ("strong", "mentioned"))]
        lacks = [t for t in themes if t["hotel"].get("state") == "not_found"]
        srcs = [p for p in src_plays if set(p["play"]["questions"]) & {m["qid"] for m in ms}]
        steps = []
        if has:
            steps.append("The hotel's own pages already state " + ", ".join(t["label"] for t in has) + " (the reasons given for the hotels named), so the difference is not on its website: "
                         + ("it is in the pages the assistant used; start with " + ", ".join(p["play"]["url"] for p in srcs[:2]) + "." if srcs else
                            "it is in the outside sources the assistant reads (see the sources in this report)."))
        if lacks:
            steps.append("The hotel's pages do not state " + ", ".join(t["label"] for t in lacks) + ", which the assistant gave as reasons for the hotels it named. Where the hotel genuinely offers it, "
                         "say so plainly on the page about it.")
        if not steps:
            steps.append("Compare the pages the assistant cited for these searches with the hotel's own pages and outside listings; the sources in this report are the place to start.")
        ev = [{"url": "", "snippet": f"“{_short(m['question'], 110)}”: named in {m.get('named', 0)} of {m.get('of', 0)} answers"} for m in ms[:3]]
        if reasons:
            ev.append({"url": "", "snippet": "Reasons the assistant gave: " + reasons})
        r = rec_fn(f"CP-M{len(out) + 1}", "authority",
                   f"Win searches about {label}: the hotel was named in {asked - lost_n} of {asked} answers; {' and '.join(w['name'] for w in winners[:2])} were named instead",
                   f"Across {len(ms)} search{'es' if len(ms) != 1 else ''} for {label} (for example “{_short(ms[0]['question'])}”), the hotel was named in {asked - lost_n} of {asked} answers. "
                   f"Named instead: " + ", ".join(f"{w['name']} ({w['answers']})" for w in winners) + "."
                   + ("" if all(w["level"] for w in winners) else " Some of these hotels' level could not be confirmed."),
                   "These are searches for the market the hotel is actually in, written from its own facts, not a town-wide list. They are where a better answer is most likely to bring bookings.",
                   ev, " ".join(steps), "high", "medium", confidence=conf["INFER"] if sure else conf["EXPER"], team="marketing", source="commercial", tag="CP-M",
                   short_title=f"Win searches about {label}", summary=label)
        r["kind_hint"], r["play"] = "opportunity", {"kind": "search", "angle": angle, "questions": [m["qid"] for m in ms], "rivals": [w["name"] for w in winners]}
        out.append(r)
    return out


_DIST_TITLE = re.compile(r"how far the hotel is from (.+?)(?: and \d+ other place\(s\))?$", re.I)


def apply(recs, gap, rec_fn, conf, anchors=()):
    """
    Add the plays, fold in the generic findings they cover, and lower the generic leftovers. -> recs (changed in place where noted).
    rec_fn: advice._rec; conf: {"INFER": ..., "EXPER": ...}; anchors: names of the places the hotel's searches are built on.
    """
    if not gap or gap.get("status") != "ok":
        return recs
    src = source_plays(gap, rec_fn, conf)
    srch = search_plays(gap, src, rec_fn, conf)
    markets = {m["qid"]: m for m in gap.get("markets") or []}
    covered_q = {q for p in srch for q in p["play"]["questions"]}
    covered_urls = {p["play"]["url"] for p in src}
    covered_themes = set()
    for p in srch:
        covered_themes |= ANGLE.get(p["play"]["angle"], ("", set()))[1]
    words = " ".join([m.get("question") or "" for m in markets.values()] + list(anchors or ())).lower()
    out = []
    for r in recs:
        rid = r.get("id") or ""
        if rid.startswith("AG-OUT") and any(e.get("url") in covered_urls for e in r.get("evidence") or []):
            continue                                                       # the same page, now a source play
        if rid.startswith("AG-") and not rid.startswith("AG-OUT"):
            qid = rid[3:]
            if qid in covered_q:
                continue                                                   # folded into a search play
            if qid in markets and _generic(markets[qid]):
                r["tag"] = "AG-GENERIC"                                    # a town-wide 'best hotels in X' answer: context, not a priority
        if r.get("source") == "differentiation" and rid.startswith("DE-"):
            if rid[3:] in covered_themes:
                for p in srch:
                    if rid[3:] in ANGLE.get(p["play"]["angle"], ("", set()))[1]:
                        p["action"] = p["action"].rstrip() + " " + (r.get("action") or "")
                        p.setdefault("folded", []).append(rid)
                continue
            r["tag"] = "DE-LOW"                                            # 'position the hotel for X' with no lost search behind it
        if r.get("source") == "location":
            m = _DIST_TITLE.search(r.get("title") or "")
            if m and evidence.fold(m.group(1)) not in evidence.fold(words):
                r["tag"] = "L-MINOR"                                       # a distance to a place none of the hotel's searches is about
        out.append(r)
    recs[:] = src + srch + out
    return recs


def top(recs, n=3):
    """The commercial plays a report should lead with: those whose evidence repeats ('Likely' or better), strongest first."""
    plays = [r for r in recs if r.get("source") == "commercial" and r.get("confidence_label") in ("Confirmed", "Likely")]
    return sorted(plays, key=lambda r: -(r.get("rank") or 0))[:n]
