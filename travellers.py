"""
Traveller relevance and language (checks 24-27).

Everything here is an assessment of EVIDENCE, never a measured AI ranking.
"Opportunities" are realistic traveller questions the hotel has evidence to
fit; whether any assistant would actually surface the hotel for them is not
something this tool measures.
"""

import re

import evidence
import sourcetypes

# segment -> (label, theme keys that count as evidence, guest-question ids, open-data hook)
SEGMENTS = [
    ("families", "Families", ["family-friendly"], ["family"], None),
    ("couples", "Couples and romantic breaks", ["romantic", "quiet / peaceful"], [], None),
    ("business", "Business travellers and meetings", ["business / meetings"], ["wifi", "parking"], "venues"),
    ("pets", "Guests travelling with dogs or pets", ["dog-friendly"], ["pets"], None),
    ("accessible", "Guests needing accessible rooms", ["accessible"], ["accessibility"], None),
    ("wellness", "Spa and wellness", ["wellness / spa"], [], None),
    ("food", "Food and dining", ["food-focused"], ["breakfast"], "fsa"),
    ("events", "Weddings and events", ["weddings & events"], [], "venues"),
    ("rail", "Guests without a car", ["well connected"], ["transport"], "stations"),
    ("drivers", "Drivers (parking and EV charging)", [], ["parking", "ev"], None),
    ("heritage", "Heritage and design interest", ["historic / heritage", "design-led / contemporary"], [], None),
    ("outdoors", "Countryside, gardens and walking", ["countryside / gardens"], [], "attractions"),
]


def _is_destination(place):
    """A mapped place that people actually travel to, not an exhibit inside one
    (OpenStreetMap maps individual aircraft inside a museum as 'attractions')."""
    t = place.get("tags", {})
    return bool(t.get("website") or t.get("wikidata") or t.get("wikipedia")
                or t.get("tourism") in ("museum", "theme_park", "zoo", "gallery"))


def traveller_need_coverage(theme_info, guest, osm_ctx, fsa_items):
    themes = {t["theme"]: t for t in theme_info["themes"]}
    gq = {q["id"]: q for q in (guest or {}).get("questions", [])}
    ctx = osm_ctx or {}
    rows = []
    for key, label, tkeys, qids, hook in SEGMENTS:
        own_pages = sum(themes.get(t, {}).get("own_pages", 0) for t in tkeys)
        pubs = set()
        extracts = []
        for t in tkeys:
            for e in themes.get(t, {}).get("independent_extracts", []):
                pubs.add(e["publisher_key"])
                extracts.append(e)
        gstates = {q: gq.get(q, {}).get("state") for q in qids}
        answered = [q for q, s in gstates.items() if s == "answered"]
        partial = [q for q, s in gstates.items() if s == "partial"]
        odata = []
        if hook == "stations" and ctx.get("stations"):
            s = ctx["stations"][0]
            odata.append(f"{s['name']} station is {s['km']} km away (straight line)")
        if hook == "venues" and ctx.get("venues"):
            v = ctx["venues"][0]
            odata.append(f"mapped venue: {v['name']} ({v['km']} km, straight line)")
        if hook == "attractions" and ctx.get("attractions"):
            a = ctx["attractions"][0]
            odata.append(f"mapped nearby: {a['name']} ({a['km']} km, straight line)")
        if hook == "fsa" and fsa_items:
            f = fsa_items[0]
            odata.append(f"{f['name']}: food hygiene rating {f['rating']} (FSA)")
        own_ok = bool(own_pages or answered)
        if len(pubs) >= 2:
            status, strength = "evidenced by several independent sources", 3
        elif len(pubs) == 1:
            status, strength = "evidenced by one independent source", 2
        elif own_ok:
            status, strength = "evidenced on the hotel's own pages only", 1
        elif odata:
            status, strength = "indirect evidence only (location data)", 1
        else:
            status, strength = "no evidence found", 0
        gaps = []
        if own_ok and qids and not answered and partial:
            gaps.append("the website answers this only partly: " + ", ".join(partial))
        for q in qids:
            if gstates.get(q) in ("not_found", "needs_checking"):
                gaps.append(f"no clear answer found on the pages checked for '{gq[q]['short']}'")
        if strength == 1 and own_ok and not pubs:
            gaps.append("no independent source supports this")
        rows.append({"key": key, "segment": label, "status": status, "strength": strength,
                     "own_pages": own_pages, "guest_answers": answered, "independent_publishers": len(pubs),
                     "independent_extracts": extracts[:2], "open_data": odata, "gaps": gaps})
    return rows


def opportunities(needs, osm_ctx, town, theme_info, guest, arts):
    """
    Realistic traveller questions the hotel could fit. Each lists the facts
    that support it and what is still missing. These are opportunities, not
    measured rankings.
    """
    ctx = osm_ctx or {}
    need = {n["key"]: n for n in needs}
    gq = {q["id"]: q for q in (guest or {}).get("questions", [])}
    station = (ctx.get("stations") or [None])[0]
    out = []

    def add(question, seg, facts, missing, basis):
        out.append({"question": question, "segment": seg, "supporting_facts": facts,
                    "missing_evidence": missing, "basis": basis,
                    "status": "opportunity - not a measured AI ranking"})

    def facts_for(key):
        n = need[key]
        f = []
        if n["own_pages"]:
            f.append(f"{n['own_pages']} page(s) on the hotel's own site cover this")
        if n["independent_publishers"]:
            f.append(f"{n['independent_publishers']} independent publisher(s) describe it")
        f += n["open_data"]
        return f

    if need["families"]["strength"] and station:
        add(f"family hotel near {station['name']} station", "families",
            facts_for("families") + [f"{station['name']} is {station['km']} km away (straight line)"],
            [g for g in need["families"]["gaps"]] or ["state how many guests each family room sleeps"],
            "open-data distance plus the hotel's family information")
    if need["pets"]["strength"]:
        add(f"dog friendly hotel in {town}", "pets", facts_for("pets"),
            need["pets"]["gaps"] or ["publish the pet charge, room types and any areas dogs may not enter"],
            "the hotel's own pet policy")
    if need["wellness"]["strength"]:
        add(f"spa hotel near {town} for a couple's weekend", "couples/wellness",
            facts_for("wellness") + facts_for("couples"),
            ["spa opening hours and treatment menu on a crawlable page"] if need["wellness"]["strength"] < 3
            else [], "spa and romantic themes")
    if need["events"]["strength"]:
        add(f"wedding venue hotel in {town} with bedrooms", "events", facts_for("events"),
            ["capacity, accommodation numbers and a sample package on one page"], "wedding/event pages")
    if need["business"]["strength"] and station:
        add(f"business hotel near {station['name']} with meeting rooms and parking", "business",
            facts_for("business") + [f"{station['name']} is {station['km']} km away (straight line)"],
            need["business"]["gaps"] or ["meeting-room capacities and parking terms on one page"],
            "meetings pages and open data")
    if need["accessible"]["strength"]:
        add(f"accessible hotel rooms in {town}", "accessible", facts_for("accessible"),
            need["accessible"]["gaps"] or ["measurable features: door widths, wet-room, lift access"],
            "accessibility information")
    if gq.get("ev", {}).get("state") == "answered":
        add(f"hotel with EV charging in {town}", "drivers", ["EV charging is described on the website"],
            ["the number and type of chargers, and whether guests pay"], "guest-question evidence")
    shown = 0
    for a in [x for x in (ctx.get("attractions") or []) if _is_destination(x)][:4]:
        if shown >= 3:
            break
        shown += 1
        named_by = [x for x in arts if a["name"].lower() in " ".join(x["windows"]).lower()]
        add(f"hotel near {a['name']}", "visitors to a local attraction",
            [f"{a['name']} is {a['km']} km away (straight line, from OpenStreetMap)"] +
            ([f"{len(named_by)} independent article(s) connect the hotel and {a['name']}"]
             if named_by else []),
            [] if named_by else [f"no independent page was found connecting the hotel with {a['name']}"],
            "open-data distance" + (" and independent articles" if named_by else ""))
    if station and not any(o["question"].startswith("hotel near") and station["name"] in o["question"]
                           for o in out):
        add(f"hotel near {station['name']} station", "guests without a car",
            [f"{station['name']} is {station['km']} km away (straight line)"] + facts_for("rail"),
            ["walking or taxi directions published by the hotel (this tool does not calculate travel time)"],
            "open-data distance")
    return out


def distinctive_positioning(theme_info, own_pages, osm_ctx, arts, comparison_entries):
    """
    What may genuinely distinguish the hotel - and what does not.
    A feature counts as a candidate only if an independent source names it.
    Generic claims (friendly staff, great location...) are listed separately
    as non-distinguishing.
    """
    ctx = osm_ctx or {}
    own_text = " ".join(p.get("text", "") for p in own_pages or [])
    generic = sorted({m.group(0).lower() for m in sourcetypes.GENERIC_CLAIMS.finditer(own_text)})[:8]
    shares = {}
    valid = [e for e in comparison_entries if e.get("valid_comparison")]
    for t in theme_info["themes"]:
        if len(valid) >= 3:       # a share of fewer than three hotels means nothing
            n = sum(1 for e in valid if t["theme"] in e.get("themes", []))
            shares[t["theme"]] = (n, len(valid))
    cands = []
    for t in theme_info["themes"]:
        if t["independent_publishers"] < 2:
            continue              # one writer's opinion is not a distinguishing feature
        sh = shares.get(t["theme"])
        common = sh and sh[1] >= 3 and sh[0] / sh[1] >= 0.6
        cands.append({"feature": t["theme"], "independent_publishers": t["independent_publishers"],
                      "comparison_share": f"{sh[0]} of {sh[1]} comparable hotels in guides" if sh else None,
                      "assessment": ("common among comparable hotels - not distinctive" if common
                                     else "named by independent sources" +
                                          ("; less common among comparable hotels in guides" if sh else
                                           "; comparison data not available")),
                      "extract": (t["independent_extracts"] or [{}])[0]})
    # local anchors: mapped places that independent writers connect with the hotel
    anchors = []
    for pl in [x for x in (ctx.get("attractions") or []) if _is_destination(x)] +             (ctx.get("venues") or []):
        low = pl["name"].lower()
        hits = [a for a in arts if low in " ".join(a["windows"]).lower()]
        if hits and pl["km"] <= 5:
            anchors.append({"place": pl["name"], "km": pl["km"],
                            "named_by": sorted({a["publisher"] for a in hits})[:4],
                            "note": "a local anchor independent writers connect with the hotel"})
    return {"candidates": cands, "local_anchors": anchors, "generic_claims_found": generic,
            "generic_note": ("These claims are real but every hotel makes them, so they do not "
                             "distinguish this one: " + ", ".join(generic)) if generic else "",
            "comparison_available": len(valid) >= 3}


TYPE_TERMS = re.compile(
    r"\b(boutique hotel|country house hotel|country house|spa hotel|art[- ]deco|luxury hotel|"
    r"business hotel|conference hotel|family hotel|historic hotel|resort|inn|guest ?house|"
    r"design hotel|hotel and spa|hotel & spa|wedding venue|[3-5][- ]star)\b", re.I)


def terminology(hotel, own_pages, arts, entities, corpus, theme_info):
    """
    How the hotel, the open-data records and independent publishers describe
    the property. Guest wording is unavailable (no review text). Reports
    conflicting labels and descriptive words independent writers use that the
    hotel's own pages never do - for the hotel to consider where TRUE, never
    as keywords to insert.
    """
    used = {}

    def note(text, source):
        for m in TYPE_TERMS.finditer(text or ""):
            t = re.sub(r"\s+", " ", m.group(0).lower()).replace("&", "and")
            used.setdefault(t, set()).add(source)

    for p in own_pages or []:
        note(p.get("title", "") + " " + p.get("text", "")[:1500], "the hotel's own site")
    for e in entities or []:
        if e.get("found"):
            note((e.get("description") or "") + " " + (e.get("facts", {}).get("name") or ""), e["source"])
    for a in arts:
        note(" ".join(a["windows"]) + " " + a["title"], a["publisher"])
    for c in corpus.get("candidates", []):
        if c["source_type"] in ("booking_platform", "hotel_directory"):
            note(c["title"], c["label"] or c["domain"])
    rows = [{"term": t, "used_by": sorted(s)[:6], "n_sources": len(s)} for t, s in used.items()]
    rows.sort(key=lambda r: -r["n_sources"])
    stars = {r["term"] for r in rows if re.match(r"[3-5].star", r["term"])}
    conflicts = []
    if len(stars) > 1:
        conflicts.append("Different star ratings appear across sources: " +
                         ", ".join(sorted(stars)) + ".")
    own_low = " ".join(p.get("text", "") for p in own_pages or []).lower()
    unused = []
    seen = set()
    for t in theme_info["themes"]:
        for e in t["independent_extracts"]:
            for m in re.finditer(sourcetypes.THEMES[t["theme"]], e["text"], re.I):
                w = m.group(0).lower()
                if len(w) >= 5 and w not in own_low and w not in seen:
                    seen.add(w)
                    unused.append({"word": w, "theme": t["theme"], "publisher": e["publisher"],
                                   "url": e["url"]})
    return {"labels": rows[:10], "conflicts": conflicts, "words_others_use": unused[:10],
            "guest_wording": "not assessed - no guest review text was accessible",
            "caution": ("Use a word only where it is true for the hotel and useful to a guest. "
                        "Do not insert keywords or script guest reviews.")}
