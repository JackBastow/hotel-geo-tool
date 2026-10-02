"""
Comparison hotels, media/organisation targets and evidence-backed pitch
angles (checks 21-23).

Rules this module holds itself to:
  * An outlet is named ONLY because a real page supports it (the page is
    attached). No page, no named target.
  * A comparison hotel must be valid: same local area, and named in the same
    kind of guide. Nothing is compared with a landmark just because it is famous.
  * A pitch angle must rest on a fact found on the hotel's own pages, and
    lists what evidence is still missing before anyone should pitch.
  * No journalist names or contact details are produced.
"""

import datetime as dt
import re

import evidence
import sourcetypes

# page-title words -> the hotel attribute they need (a key into media THEMES)
FIT_TERMS = [
    (r"wedding|bride|bridal|venue for", "weddings & events", "wedding venue"),
    (r"\bspa\b|wellness|treatment", "wellness / spa", "spa hotel"),
    (r"conference|meeting|corporate|business travel|event space", "business / meetings",
     "conference or business hotel"),
    (r"afternoon tea|restaurant|dining|brunch|sunday lunch|food", "food-focused", "food and dining"),
    (r"family|kids|children", "family-friendly", "family hotel"),
    (r"dog|pet", "dog-friendly", "dog-friendly hotel"),
    (r"romantic|couples|honeymoon", "romantic", "romantic stay"),
    (r"boutique|design|luxury|five[- ]star|5[- ]star", "luxury", "luxury / boutique stay"),
    (r"remote work|workation|digital nomad|work from", "business / meetings", "remote-working stays"),
]
# Never a media target: a business selling something else, or user-generated Q&A.
NOT_A_TARGET = ("realty", "estate", "property", "propert", "homes", "lettings", "savills",
                "knightfrank", "sothebys", "rightmove", "zoopla", "quora", "reddit")
_THEME_RX = {k: re.compile(v, re.I) for k, v in sourcetypes.THEMES.items()}
LODGING_HEADING = re.compile(
    r"\b(hotel|inn|lodge|resort|spa|house|manor|hall|park|arms|retreat|estate|club|"
    r"courtyard|suites?|b&b|guest ?house|venue)\b", re.I)
LISTING_PLATFORM_DOMAINS = ("hitched", "bridebook", "weddingwire", "theweddingsecret",
                            "confetti", "bridesmagazine", "hotels.uk.com", "conferences-uk",
                            "mitmagazine", "meetings-conventions", "cvent", "venuefinder",
                            "venuedirectory", "eventsvenue")


BAD_HEADING = re.compile(
    r"\b(location|address|contact|where|how|why|what|when|faq|price|prices|cost|book|booking|about|"
    r"review|reviews|directions|parking|getting|capacity|packages?|offers?|map|opening|details|"
    r"information|enquir\w*|similar|nearby|related|more|other|best|top)\b|\?|:", re.I)


def _looks_like_property(name):
    """A heading is a hotel only if it reads like a proper name, not a page section."""
    words = name.split()
    if not (2 <= len(words) <= 7) or BAD_HEADING.search(name):
        return False
    generic = evidence.LODGING_WORDS | evidence.FILLER | {"guest", "bed", "breakfast", "room",
                                                          "rooms", "restaurant", "bar", "pub"}
    distinctive = [w for w in words if w[:1].isupper() and w.lower() not in generic]
    return bool(distinctive)


def _is_guide(c, area_tokens):
    """
    A guide/roundup worth considering: it reads like a list or guide AND is
    about this area. Search role alone is not enough - a competitor's own
    listing page or a US news site came back for 'best hotels in <town>'.
    """
    read = c["read"]["status"] == "read"
    title = ((c["page"].get("title") if read else "") or "") + " " + (c["title"] or "")
    if read:
        looks = c["page"]["page_type"]["type"] in ("roundup", "destination_guide")
        hay = evidence.fold(title + " " + c["page"].get("text_head", "") + " " + c["url"])
    else:
        looks = bool(sourcetypes._ROUNDUP.search(title) or sourcetypes._GUIDE.search(title))
        hay = evidence.fold(title + " " + c["snippet"] + " " + c["url"])
    local = any(t in hay.split() or t in hay for t in area_tokens)
    return looks and local


def _clean_heading(h):
    h = re.sub(r"^\s*(?:\d{1,2}[.):]?|#\d+)\s*", "", h or "")
    return re.sub(r"\s*[|–—-]\s*.*$", "", h).strip()


def _roundup_entries(c, hotel, nearby, town):
    """Entries a roundup page lists, each judged as a comparison candidate."""
    me = evidence.fold(hotel)
    folded_nearby = {evidence.fold(n["name"]): n for n in nearby}
    entries = []
    for s in (c["page"].get("sections") or []):
        name = _clean_heading(s["heading"])
        if not name or not LODGING_HEADING.search(name) or len(name) > 70                 or not _looks_like_property(name):
            continue
        f = evidence.fold(name)
        if f == me or me in f:
            continue
        hit = next((n for k, n in folded_nearby.items() if k and (k == f or k in f or f in k)), None)
        in_town = bool(town) and evidence.fold(town) in evidence.fold(
            name + " " + s["text"] + " " + (c["page"].get("title") or ""))
        if hit:
            valid, why = True, f"mapped in OpenStreetMap {hit['km']} km (straight line) away"
        elif in_town:
            valid, why = True, f"described in a guide about {town}"
        else:
            valid, why = False, "no evidence it is in the same local area"
        themes = [k for k, rx in _THEME_RX.items() if rx.search(s["text"])]
        entries.append({"name": name, "valid_comparison": valid, "why": why,
                        "km": hit["km"] if hit else None,
                        "stars": (hit or {}).get("tags", {}).get("stars"),
                        "themes": themes})
    return entries


def _fit(title, own_theme_counts, segments):
    """-> (fit_label, supported: bool|None, hotel_attribute)"""
    t = (title or "").lower()
    for pat, theme, label in FIT_TERMS:
        if re.search(pat, t):
            n = own_theme_counts.get(theme, 0)
            return (label, n > 0, theme, n)
    return ("general hotels in the area", True, None, 0)


def comparison_and_targets(corpus, arts, hotel, city, osm_ctx, own_theme_counts, segments,
                           award_rows, ledger):
    town = (city or "").split(",")[0].strip()
    area_tokens = [t for t in evidence.place_tokens(city)[0]] or [evidence.fold(town)]
    nearby = (osm_ctx or {}).get("hotels") or []
    roundups, targets = [], []
    featured = {}          # comparison hotel -> list of pages featuring it
    for c in corpus.get("candidates", []):
        is_round = _is_guide(c, area_tokens)
        if not is_round or any(t in c["domain"] for t in NOT_A_TARGET) or c["source_type"] in ("booking_platform", "social", "video", "wiki",
                                                "own_website", "hotel_group", "map_or_open_data"):
            continue
        title = (c["page"].get("title") if c["read"]["status"] == "read" else None) or c["title"]
        read = c["read"]["status"] == "read"
        date = (c["page"].get("published") if read else None) or c.get("published_search")
        lists_me = read and c["match"]["level"] in ("high", "medium") and c["page"].get("mentions", 0) > 0
        entries = _roundup_entries(c, hotel, nearby, town) if read else []
        pub = (c["page"].get("publisher") if read else None) or c["label"] or c["domain"]
        rd = {"url": c["url"], "title": title[:140], "publisher": pub, "domain": c["domain"],
              "date": date, "read": read, "lists_hotel": bool(lists_me),
              "entries": entries[:25], "source_type": c["source_type"]}
        roundups.append(rd)
        for e in entries:
            if e["valid_comparison"]:
                featured.setdefault(e["name"], []).append(
                    {"publisher": pub, "url": c["url"], "title": title[:100], "date": date})

        if lists_me:
            continue
        is_platform_listing = any(p in c["domain"] for p in LISTING_PLATFORM_DOMAINS)
        if c["source_type"] in ("hotel_directory", "booking_platform") and not is_platform_listing:
            continue      # price-comparison and deal sites are not media or listing targets
        # ----- a target page: a real, relevant guide that does not include this hotel
        is_platform = any(p in c["domain"] for p in LISTING_PLATFORM_DOMAINS)
        label, supported, theme, n_pages = _fit(title, own_theme_counts, segments)
        age = evidence.age_months(date)
        valid = [e for e in entries if e["valid_comparison"]]
        if not read and not title:
            continue
        kind = ("listing / supplier directory (usually apply or subscribe)" if is_platform
                else "editorial guide or roundup")
        why = []
        if supported and theme:
            why.append(f"the hotel's own site covers this ({n_pages} page(s) mention "
                       f"{theme})")
        elif theme and not supported:
            why.append(f"NOT yet supported - the hotel's own pages say little about "
                       f"'{theme}', so there is nothing to offer this outlet yet")
        else:
            why.append("a general local guide; fit rests on location")
        if valid:
            why.append(f"it features {len(valid)} comparable nearby propert"
                       f"{'y' if len(valid) == 1 else 'ies'} (e.g. {', '.join(e['name'] for e in valid[:2])})")
        if age is not None and age > 24:
            why.append(f"dated {date} - check it is still maintained")
        elif age is None:
            why.append("no publication date found on the page")
        eid = ledger.add(url=c["url"], source=pub, source_type="news_or_magazine"
                         if not is_platform else "other",
                         extract=(c["page"].get("text_head") if read else c["snippet"])[:400],
                         published=date, match="high", kind="observed", via=c["via"],
                         match_why="page exists and is about this area/segment; hotel not named in it",
                         note="supporting page for a media/organisation target")
        targets.append({
            "name": pub, "domain": c["domain"], "url": c["url"], "page_title": title[:140],
            "date": date, "kind": kind, "audience_fit": label, "supported": bool(supported),
            "recent": age is not None and age <= 24, "read": read,
            "why_relevant": "; ".join(why), "comparators": [e["name"] for e in valid[:5]],
            "evidence_id": eid,
            "confidence": "page read" if read else "from search result only - page not read",
        })

    # destination bodies and award schemes that surfaced as real pages
    for c in corpus.get("candidates", []):
        if c["source_type"] == "destination_body" and c["domain"] not in {t["domain"] for t in targets}:
            read = c["read"]["status"] == "read"
            names_me = read and c["match"]["level"] in ("high", "medium")
            eid = ledger.add(url=c["url"], source=c["label"] or c["domain"],
                             source_type="destination_body",
                             extract=(c["snippet"] or c["title"])[:400],
                             published=c.get("published_search"), kind="observed",
                             match="high", via=c["via"], match_why="official destination site for the area")
            targets.append({
                "name": c["label"] or c["domain"], "domain": c["domain"], "url": c["url"],
                "page_title": c["title"][:140], "date": c.get("published_search"),
                "kind": "destination organisation",
                "audience_fit": "destination listing and visitor guides", "supported": True,
                "recent": False, "read": read,
                "why_relevant": ("it already features the hotel on this site"
                                 if names_me else
                                 ("the destination site for the area" if any(t in c["domain"] for t in area_tokens)
                                  else "a national or regional tourism body, not specific to the town") +
                                 "; ask how hotels are listed or featured (eligibility not assumed)"),
                "comparators": [], "evidence_id": eid,
                "confidence": "page read" if read else "from search result only - page not read"})
    # (awards the hotel claims but no issuer confirms are a verification task,
    # not a media target - they are handled in the recommendations)

    # de-duplicate targets by domain+path-prefix, rank
    seen, uniq = set(), []
    for t in targets:
        k = (t["domain"], t["kind"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    uniq.sort(key=lambda t: (not t["supported"], t["kind"].startswith("listing"),
                             not t["recent"], not t["read"]))
    comparison = []
    for name, pages in featured.items():
        comparison.append({"hotel": name, "featured_in": pages[:4], "n_guides": len(pages),
                           "valid": True})
    comparison.sort(key=lambda r: -r["n_guides"])
    return {"roundups": roundups, "targets": uniq[:14], "comparison": comparison[:12]}


# ---------------------------------------------------------------- pitch angles

ANGLE_RULES = [
    ("Documented refurbishment or new offering",
     r"(refurbish\w*|renovat\w*|redevelop\w*|re-?open\w*|transformation|revamp\w*|"
     r"newly (?:opened|built|launched|refurbished)|new (?:spa|restaurant|bar|wing|suite|rooms?))",
     ["Completion date and scope of the work", "Before/after photography you own the rights to",
      "A named spokesperson and a short quote", "What is genuinely new for guests"]),
    ("Heritage or setting",
     r"(grade\s+[iI]+\*?\s+listed|listed building|built in \d{4}|dating back to|"
     r"history of the|historic|heritage|founded in \d{4}|oldest|first purpose-built)",
     ["Verifiable dates and sources for the history", "A specific story, not a general claim",
      "Archive imagery with clear rights"]),
    ("Distinctive food and drink",
     r"(rosettes?|michelin|head chef|executive chef|tasting menu|afternoon tea|"
     r"locally sourced|kitchen garden|farm to fork|signature (?:dish|cocktail))",
     ["Chef name and background", "Menu sample and sourcing details", "Any rating or award with the issuer's page"]),
    ("Accessibility features",
     r"(wheelchair|step-free|hearing loop|accessible (?:room|bedroom|bathroom)|adapted room|"
     r"mobility|lift access)",
     ["Specific measurable features (door widths, wet-room, lift)", "Who tested or certified them",
      "A guest story shared with permission"]),
    ("Local partnership or destination link",
     r"(in partnership with(?! us\b| our\b)|partner(?:ed|ship)? with(?! us\b| our\b| the hotel\b)|"
     r"official (?:hotel|partner)|exclusive partner|collaborat\w+ with(?! us\b))",
     ["The partner's own confirmation or page", "What the partnership gives a guest",
      "Dates and any joint announcement"]),
    ("Events, weddings or experiences",
     r"(wedding (?:venue|packages?)|civil ceremon\w+|conference (?:centre|rooms?)|"
     r"experience days?|driving experience|masterclass|retreat package)",
     ["Capacity and facilities figures", "A real event to describe (with permission)",
      "Pricing position (do not publish unless intended)"]),
]


def pitch_angles(own_pages, ledger, today=None):
    """Angles with a real fact behind them. -> list of dicts (may be empty)."""
    out = []
    for name, pat, missing in ANGLE_RULES:
        rx = re.compile(pat, re.I)
        best = None
        for p in own_pages or []:
            m = rx.search(p.get("text", ""))
            if not m:
                continue
            snip = evidence.clip(p["text"], m.start() - 120, m.end() + 160)
            if best is None or len(snip) > len(best[1]):
                best = (p, snip)
        if best:
            p, snip = best
            eid = ledger.add(url=p["url"], source="Hotel's own website", source_type="own_website",
                             extract=snip, kind="observed", match="high",
                             match_why="the hotel's own page", via="own pages",
                             note="fact behind a candidate pitch angle")
            out.append({"angle": name, "fact": snip, "source_url": p["url"], "evidence_id": eid,
                        "status": "candidate - supported by a page on the hotel's own site, "
                                  "not yet by anything independent",
                        "missing_evidence": missing})
    return out
