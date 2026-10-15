"""
The consultant's recommendations.

Each one is generated from a specific finding - never inserted as generic
advice - and has the same shape:

  finding      what was discovered, in plain hotel language
  why          why it matters to how the hotel is understood, found or chosen
  evidence     the actual page, wording or missing fact
  action       a specific thing to do
  page         where to do it (when there is a page)
  additions    the exact items to add (for page-level advice)
  example      what the improved wording could look like
  priority     critical / high / medium / low
  effort       low / medium / high
  technical    the SEO/GEO detail, for the digital team (collapsed in the UI)
  confidence   established good practice / reasonable inference / experimental

Nothing here claims that an action will make an AI assistant recommend the
hotel. Where confidence is limited the recommendation says so.
"""

import re
import urllib.parse

import ranking

PRIORITY_WEIGHT = {"critical": 100, "high": 70, "medium": 40, "low": 15}
EFFORT_COST = {"low": 1.0, "medium": 1.8, "high": 3.0}
CATEGORY_LABEL = {"access": "Can machines reach it?", "understanding": "Can machines understand it?",
                  "content": "Is the traveller information there?", "authority": "Is there outside evidence?"}
BEST = "Established good practice"
INFER = "Reasonable inference"
EXPER = "Experimental"

WHY_QUESTION = ("Guests look for this before they book. If authoritative sources don't state it clearly, AI systems and search "
                "tools may be less able to answer the question accurately or confidently.")


def _path(u):
    return urllib.parse.urlparse(u or "").path or "/"


def _ev(rows, n=2):
    out = []
    for r in rows or []:
        if isinstance(r, dict) and (r.get("snippet") or r.get("url")):
            out.append({"url": r.get("url", ""), "snippet": (r.get("snippet") or "")[:260]})
        if len(out) >= n:
            break
    return out


def _rec(rid, category, title, finding, why, evidence, action, priority, effort, *, page=None, additions=None,
         example="", technical="", confidence=BEST, team="web", success="", source="", question_ids=None, tag="",
         short_title="", summary=""):
    return {"id": rid, "tag": tag, "short_title": short_title or title, "summary": summary, "category": category, "title": title, "finding": finding, "why": why,
            "evidence": evidence, "action": action, "page": page, "additions": additions or [], "example": example,
            "technical": technical, "priority": priority, "effort": effort, "confidence": confidence, "team": team,
            "success_check": success or "The next audit no longer reports this.", "source": source,
            "question_ids": question_ids or []}


# ------------------------------------------------------------------ questions

def _name_group(rec, qs, where_txt, kind):
    """Short, readable names for a group of open questions (used in summaries and plans)."""
    shorts = [q.get("short") or q["question"].rstrip("?") for q in qs]
    rec["summary"] = "; ".join(
        f"{sh} ({', '.join(q['missing'][:2])})" if q["missing"] else sh for sh, q in zip(shorts, qs))[:400]
    if kind == "opportunity":
        rec["short_title"] = "If a target segment: complete the " + ", ".join(shorts[:2]).lower() + " details"
    else:
        n = len(qs)
        rec["short_title"] = (f"State the missing {shorts[0].lower()} details on {where_txt}" if n == 1 else
                              f"Answer {n} open guest questions on {where_txt}")

def _from_questions(questions):
    groups = {}
    for q in questions:
        w = q["where"]
        # a guest-information gap and a gap in the detail of a segment the hotel promotes (weddings, spa,
        # meeting rooms) are different kinds of thing, so they are not grouped together
        kind = "opportunity" if q.get("source") == "extended" else "fix"
        key = (w["url"] or w["label"], kind)
        groups.setdefault(key, {"where": w, "qs": [], "kind": kind})["qs"].append(q)
    recs = []
    for i, (key, g) in enumerate(groups.items(), 1):
        qs, w = g["qs"], g["where"]
        high = any(q.get("high_value") and q["state"] in ("missing", "unclear") for q in qs)
        partial_high = any(q.get("high_value") for q in qs)
        n = len(qs)
        priority = "high" if high or n >= 4 else ("medium" if partial_high or n >= 2 else "low")
        adds = []
        for q in qs:
            for m in q["missing"]:
                adds.append(f"{q['question'].rstrip('?')} - add: {m}" if n > 1 else m[:1].upper() + m[1:])
        topics = [q["question"].rstrip("?") for q in qs]
        where_txt = f"{_path(w['url'])}" if w["url"] else w["label"]
        found_bits = [f for q in qs for f in q["found"]][:3]
        if g["kind"] == "opportunity":
            shorts = [q.get("short") or q["question"].rstrip("?") for q in qs]
            finding = (f"The hotel promotes {', '.join(sh.lower() for sh in shorts[:4])}, but the pages don't yet state: "
                       + "; ".join(sorted({m for q in qs for m in q["missing"]})[:6]) + ". Worth completing if this is a segment you want to attract.")
            title = "If this is a target segment, complete the details: " + ", ".join(shorts[:3])
        elif n == 1:
            q = qs[0]
            finding = (f"{q['question']} " + ("The site touches on it" + (f" ({', '.join(found_bits)})" if found_bits else "") +
                                                 f" but doesn't say {', '.join(q['missing'])}." if q["missing"] else "No page we read answers it clearly."))
            title = f"Answer this clearly: {q['question']}"
        else:
            finding = f"{n} questions guests ask are only partly answered or not answered: " + "; ".join(topics[:5]) + "."
            shorts = [q.get("short") or q["question"].rstrip("?") for q in qs]
            title = (f"Fill the gaps on {where_txt}: " + ", ".join(shorts[:3])
                     + (f" and {n - 3} more" if n > 3 else ""))
        ev = []
        for q in qs:
            ev += q["evidence"]
        if not ev:
            ev = [{"url": "", "snippet": "None of the pages we read states this clearly."}]
        examples = [q["example"] for q in qs if q.get("example")][:3]
        recs.append(_rec(
            f"Q{i}", "content", title, finding, WHY_QUESTION, _ev(ev, 3),
            (f"Add the answer to {where_txt} ({w['reason']})." if w["url"] else f"Create {w['label']} and add the answers.")
            + (f" Also worth repeating on {_path(w['also'][0]['url'])}." if w.get("also") else ""),
            priority, "low" if len(adds) <= 8 else "medium", page={"url": w["url"], "label": where_txt} if w["url"] else {"url": "", "label": w["label"]},
            additions=adds[:10], example="\n".join(examples),
            technical="Content-completeness gap. Write each answer as plain text in a clearly headed section so it can be quoted; "
                      "optionally mark up an FAQ section as FAQPage (see structured data).",
            confidence=BEST if any(q.get("high_value") for q in qs) else INFER, team="web",
            success="The question is answered in plain text on the page and the next audit marks it 'answered'.",
            source="questions", question_ids=[q["id"] for q in qs]))
        _name_group(recs[-1], qs, where_txt, g["kind"])
    return recs


# ------------------------------------------------------------------- location

def _from_location(loc):
    recs = []
    nodist = [i for i in loc["items"] if i["state"] == "mentioned_no_distance" and i["category"] in ("transport", "airports", "venues", "attractions")]
    rail_clear = any(i["category"] == "transport" and i["state"] == "stated" for i in loc["items"])
    missing = [i for i in loc["items"] if i["state"] == "not_mentioned" and i["category"] in ("transport", "airports")
               and not (i["category"] == "transport" and rail_clear)]
    if nodist:
        first = nodist[0]
        names = [i["place"] or i["label"] for i in nodist]
        recs.append(_rec(
            "L1", "content", "Say how far the hotel is from " + (names[0] if len(names) == 1 else f"{names[0]} and {len(names) - 1} other place(s)"),
            "The website mentions " + ", ".join(names[:4]) + " but doesn't say how far away " + ("it is." if len(names) == 1 else "they are."),
            "People search by location (“hotels near [station]”). A named place without a distance is a much weaker location signal than “8 minutes' walk”.",
            _ev([{"url": e["evidence"][0]["url"], "snippet": e["evidence"][0]["snippet"]} for e in nodist if e["evidence"]], 3),
            "Add the walking or driving time next to each place, on your Location / Getting here page. Check the real route first.",
            "high" if any(i["category"] in ("transport", "airports") for i in nodist) else "medium", "low",
            page={"url": nodist[0]["evidence"][0]["url"] if nodist[0]["evidence"] else "", "label": _path(nodist[0]["evidence"][0]["url"]) if nodist[0]["evidence"] else "Location page"},
            additions=[f"{i['place'] or i['label']}: walking/driving time. {i['hint']}".strip() for i in nodist[:5]],
            example="\n".join(i["example"] for i in nodist[:3]),
            technical="Location relevance. Distances shown as hints are straight-line values from OpenStreetMap, not travel times; verify before publishing.",
            confidence=BEST, team="marketing", source="location"))
    if missing:
        names = [i["place"] for i in missing]
        recs.append(_rec(
            "L2", "content", "Connect the hotel to " + (names[0] if len(names) == 1 else f"{names[0]} and other nearby places"),
            "Open map data shows " + ", ".join(f"{i['place']} ({'about ' + str(i['open_data_km']) + ' km' if i['open_data_km'] is not None else 'nearby'})" for i in missing[:3]) +
            ", but the website doesn't mention " + ("it." if len(names) == 1 else "them."),
            "Travellers often search for hotels near a station, venue or airport. If the site never names the place, it can't match that search.",
            [{"url": "", "snippet": i["suggestion"]} for i in missing[:3]],
            "If these are useful connections for your guests, add a sentence on how to get there to the Location page - after checking the real route and time.",
            "medium", "low", page={"url": "", "label": "your Location / Getting here page"},
            additions=[f"{i['place']}: how to get there and how long it takes" for i in missing[:4]],
            example="\n".join(i["example"] for i in missing[:2]),
            technical="Distances in this report's hints are straight-line, from OpenStreetMap; do not publish them as travel times.",
            confidence=INFER, team="marketing", source="location"))
    return recs


# ---------------------------------------------------------------- consistency

def _from_consistency(items):
    recs = []
    for i, c in enumerate(items, 1):
        pr = {"high": "high", "medium": "medium", "low": "low"}[c["severity"]]
        vals = "; ".join(f"{v['value'][:90]}" + (f" ({_path(v['url'])})" if v.get("url") else "") for v in c["values"][:4])
        recs.append(_rec(
            f"C{i}", "understanding", c["title"], f"{c['title']}: {vals}.", c["detail"] + " Contradictory facts make a hotel harder to describe correctly.",
            _ev([{"url": v["url"], "snippet": v["value"]} for v in c["values"]], 3), c["fix"], pr, "low",
            page={"url": c["values"][0]["url"], "label": _path(c["values"][0]["url"])} if c["values"] else None,
            tag=c["type"],
            technical=f"Entity consistency ({c['type']}). Keep one value across page text, titles, footer and structured data.",
            # a second phone number, venue hours or an amenity rule can be perfectly legitimate, so those are inferences
            confidence=BEST if c["type"] in ("times", "postcode", "old_offer", "rooms") else INFER,
            team="operations" if c["type"] in ("times", "hours", "rooms", "amenity") else "web",
            source="consistency"))
    return recs


# ----------------------------------------------------------- hidden strengths

def _from_hidden(items):
    recs = []
    for i, h in enumerate(items[:8], 1):
        eff = "medium" if h["kind"] in ("pdf", "image") else "low"
        pr = "low" if h.get("menu") else ("medium" if h["kind"] in ("pdf", "once", "deep") else "low")
        recs.append(_rec(
            f"H{i}", "content", {"once": f"Make {h['label'].lower()} easier to find", "deep": f"Bring {h['label'].lower()} out of a buried page",
                                  "pdf": ("Write the essentials of your menus as page text" if h.get("menu") else f"Put the {h['label']} information on a web page, not only in a PDF"), "image": "Write out what's in the pictures",
                                  "poorly_linked": f"Link to {h['label']} from your main pages"}[h["kind"]],
            h["finding"], "A real strength that is hard to find is less likely to be noticed by travellers, and less reliably picked up by systems that read the site.",
            _ev(h["evidence"]), h["suggestion"], pr, eff, page={"url": h["pages"][0], "label": _path(h["pages"][0])},
            technical={"pdf": "Content in PDFs is harder to extract and cite than HTML. Keep the PDF as a download.",
                       "image": "Text inside images is not machine-readable without OCR; add real text and descriptive alt text.",
                       "deep": "Deep, weakly-linked pages are crawled less and weighted less. Improve internal linking.",
                       "poorly_linked": "No internal links found among the crawled sample - verify against the full navigation.",
                       "once": "Information stated once, off the main paths, is easy to miss; repeat key facts where people look."}[h["kind"]],
            confidence=INFER, team="web" if h["kind"] != "once" else "marketing", source="hidden",
            tag="pdf_menu" if h.get("menu") else h["kind"]))
    return recs


# ------------------------------------------------------------ structured data

def _from_structured(sd, jsonld_example, site):
    recs = []
    items = {i["item"]: i for i in sd["items"]}
    hotel = items.get("Hotel / LodgingBusiness")
    if hotel and hotel["status"] == "missing":
        recs.append(_rec(
            "SD1", "understanding", "Give search engines the hotel's basic facts in a form they can read directly",
            "Your pages state the hotel's name, address and phone in sentences, but there is no machine-readable 'Hotel' block, so every system has to work these facts out for itself.",
            "When the hotel's basic facts are stated in a standard, machine-readable format, systems reading the page can pick them out with less ambiguity. Search and AI tools also draw on other sources, so this is about accuracy and tidiness rather than a ranking boost.",
            [{"url": site.base, "snippet": "No Hotel/LodgingBusiness structured data found on any page read."}],
            "Ask your web supplier to add one Hotel block to the homepage (below is a starting point filled from what we read - check every value).",
            "high", "low", page={"url": site.base, "label": "the homepage"}, example=jsonld_example or "",
            technical="Add JSON-LD (schema.org Hotel/LodgingBusiness) to the homepage: name, url, telephone, PostalAddress, GeoCoordinates, image, sameAs. "
                      + CAUTION_SHORT,
            confidence=BEST, team="web", success="A Hotel block is present on the homepage and matches the page text.", source="structured"))
    inc = items.get("Is the markup correct?")
    if inc and inc["status"] == "incorrect":
        recs.append(_rec(
            "SD2", "understanding", "Correct facts in your structured data that disagree with the page", inc["detail"],
            "A system that relies on the markup may repeat the wrong fact, and a page whose markup disagrees with its text reads as unreliable.",
            _ev(inc["evidence"], 3), inc["advice"], "high", "low", page={"url": site.base, "label": "the homepage"},
            technical="JSON-LD values do not match visible text (telephone/postcode/coordinates/times). Update the markup to match the page.",
            confidence=BEST, team="web", source="structured"))
    det = items.get("Hotel details")
    if det and det["status"] == "could_improve":
        recs.append(_rec(
            "SD3", "understanding", "Complete the hotel's structured details", det["detail"],
            "A fuller block states more facts in a standard format, which leaves less for a reading system to infer.", _ev(det["evidence"]), det["advice"],
            "medium", "low", page={"url": site.base, "label": "the homepage"}, example=jsonld_example or "",
            technical=det["detail"] + " " + CAUTION_SHORT, confidence=BEST, team="web", source="structured"))
    ex = items.get("Useful extras")
    if ex and ex["status"] == "could_improve" and "sameAs" in ex["detail"]:
        recs.append(_rec(
            "SD4", "understanding", "Link your official profiles from your structured data", ex["detail"],
            "Declaring which profiles are really yours helps systems that read the page connect the website, the social accounts and the listings as one hotel.",
            [{"url": site.base, "snippet": ex["detail"]}], "Add the hotel's official Facebook, Instagram and other profile addresses to the Hotel block's 'sameAs' list.",
            "low", "low", page={"url": site.base, "label": "the homepage"}, technical="schema.org sameAs array on the Hotel node.",
            confidence=INFER, team="web", source="structured"))
    faq = items.get("FAQPage")
    if faq and faq["status"] == "could_improve":
        recs.append(_rec(
            "SD5", "understanding", "Mark up the FAQ you already have", faq["detail"],
            "Marking up existing questions and answers makes them easier for systems that read the page to identify accurately.",
            _ev(faq["evidence"]), faq["advice"], "low", "low", page={"url": faq["evidence"][0]["url"], "label": _path(faq["evidence"][0]["url"])} if faq["evidence"] else None,
            technical="FAQPage JSON-LD for the existing visible Q&A. Google limits FAQ rich results to a few site types, so this is for machine clarity, not a visible search feature.",
            confidence=INFER, team="web", source="structured"))
    amen = items.get("amenityFeature (facilities)")
    if amen and amen["status"] == "missing" and hotel and hotel["status"] != "missing":
        recs.append(_rec(
            "SD6", "understanding", "List the hotel's facilities in its structured data", amen["detail"],
            "A facilities list in a standard format states what the hotel offers in a form that is easy to read automatically.", _ev(hotel["evidence"]), amen["advice"],
            "low", "low", technical="amenityFeature (LocationFeatureSpecification) on the Hotel node.", confidence=INFER, team="web", source="structured"))
    return recs


CAUTION_SHORT = "This helps systems read the facts accurately; there is no evidence it makes an AI assistant recommend a hotel."


# ----------------------------------------------------------- machine readiness

TEXT = {
    "robots_block_all": ("Let search engines and AI tools read the website", "critical", "low"),
    "ai_blocked": ("Decide whether you want AI assistants to read the site", "medium", "low"),
    "sitemap_missing": ("Publish a sitemap so every page can be found", "medium", "low"),
    "js_empty": ("Make sure key pages show their text without JavaScript", "high", "high"),
    "http_errors": ("Fix the pages that return errors", "medium", "low"),
    "noindex": ("Remove the 'do not index' instruction from pages you want found", "high", "low"),
    "canonical_other": ("Check which pages point to a different 'main' page", "medium", "low"),
    "dup_titles": ("Give each page its own title", "medium", "low"),
    "dup_content": ("Merge or differentiate near-identical pages", "medium", "medium"),
    "home_title": ("Put the hotel's name and town in the homepage title", "medium", "low"),
    "home_meta": ("Write a description for the homepage", "medium", "low"),
    "meta_missing": ("Add descriptions to guest-facing pages", "low", "low"),
    "h1": ("Give every page one clear main heading", "low", "low"),
    "alt": ("Describe your key images in text (alt text) for search and screen readers", "medium", "medium"),
    "entity_missing": ("Get the hotel recognised in open map and knowledge data", "medium", "low"),
    "cc_refused": ("Check whether your firewall is refusing automated visitors", "medium", "medium"),
    "speed": ("Speed up the homepage on mobile", "medium", "high"),
    "a11y": ("Fix the accessibility problems Google's test found", "medium", "medium"),
}
PEOPLE = {
    "robots_block_all": "web", "ai_blocked": "marketing", "sitemap_missing": "web", "js_empty": "web", "http_errors": "web", "noindex": "web",
    "canonical_other": "web", "dup_titles": "web", "dup_content": "web", "home_title": "web", "home_meta": "marketing", "meta_missing": "marketing",
    "h1": "web", "alt": "marketing", "entity_missing": "distribution", "cc_refused": "web", "speed": "web", "a11y": "web",
}


def _from_machine(findings):
    recs = []
    for f in findings:
        if f["status"] != "issue" or f["id"] not in TEXT:
            continue
        title, pr, eff = TEXT[f["id"]]
        pr = f["severity"] if f["severity"] in ("critical", "high") and f["id"] in ("robots_block_all", "noindex", "js_empty") else pr
        recs.append(_rec(
            f"M-{f['id']}", f["bucket"], title, f["title"] + ". " + f["detail"], f["consequence"],
            _ev(f["evidence"], 3) or [{"url": "", "snippet": f["detail"]}], f["fix"], pr, eff,
            technical=f["title"] + " - " + f["detail"], confidence=f["confidence"], team=PEOPLE.get(f["id"], "web"), source="machine"))
    return recs


# -------------------------------------------------------------------- authority

SUPERSEDED_SCORING = ("no_hotel_schema", "schema_incomplete", "social_sameas", "social_link", "guest_", "topic_guess", "crawler_block",
                      "no_sitemap", "location_unreadable", "facts_conflict")
DROP_INTEL = ("V3", "T2-", "W1", "T1", "T3")      # limits or superseded by findings above
EFFORT_BY_TEAM = {"PR": "medium", "distribution": "low", "marketing": "low", "operations": "medium", "reputation management": "medium", "web": "low"}


def drop_duplicate_entity(recs):
    """The scoring layer names the specific sources (OpenStreetMap, Wikidata); drop the generic entity rec when it does."""
    if any(r["id"].startswith("X-S-entity_missing") for r in recs):
        return [r for r in recs if r["id"] != "M-entity_missing"]
    return recs


def _niche_rec(ai):
    s = (ai or {}).get("summary") or {}
    if (ai or {}).get("status") != "ok" or s.get("niche_asked", 0) < 2 or s.get("niche_named", 0) > 0:
        return []
    angles = [i for i in ai["items"] if i["kind"] == "niche"]
    lines = "; ".join(f"{i.get('angle', 'niche')}: \"{i['text']}\"" for i in angles[:4])
    return [_rec(
        "AI4", "authority", "The hotel was not named in the markets it is positioned for",
        f"In {s['niche_asked']} narrower questions drawn from what the audit found the hotel is (its location, price level or what it is known for), one AI model with web search "
        f"did not name it: {lines}.",
        "A hotel is chosen in its own market (near an airport, in a district, at a price, for a spa or a restaurant), not against every hotel in a city. "
        "Not being named where it is positioned to compete is a more useful signal than not topping a town-wide list. This is one model on one day.",
        [{"url": "", "snippet": f"{i.get('angle', 'niche')}: {i['text']} - hotel not named ({i.get('why', '')})"} for i in angles[:3]],
        "Look at which hotels the assistant did name in each of these questions and which sites it used (the tables above), then make sure the hotel's own pages and its "
        "main listings state that market plainly in their first lines: the airport distance and transfer, the neighbourhood, the price level, the feature it is known for.",
        "medium", "medium", confidence=EXPER, team="marketing", source="ai", tag="AI4", summary="Not named in the markets the hotel is positioned for")]


def _from_ai(ai):
    """One opportunity, only when the sample is solid enough to say something: an assistant asked for hotel suggestions never named the hotel."""
    if not ai or ai.get("status") != "ok":
        return []
    s = ai.get("summary") or {}
    niche = _niche_rec(ai)
    if s.get("generic_asked", 0) < 2 or s.get("generic_named", 0) > 0:
        return niche
    doms = ", ".join(s.get("top_domains", [])[:6]) or "(none recorded)"
    return [_rec(
        "AI1", "authority", "The hotel was not named when an AI assistant was asked for hotel suggestions",
        f"In {s['generic_asked']} sampled questions asking for hotels in the town, one AI model (with web search) did not name this hotel. "
        f"The sources it relied on included: {doms}.",
        "A single sample from one model is not a ranking and answers change between runs, but the sources it chose show where it looks. "
        "Accurate, current listings on those sources are one way the hotel can be found when someone asks.",
        [{"url": "", "snippet": f"Sampled by {ai.get('model', 'one AI model')} on {ai.get('run_at', '')}; the answers are in the report."}],
        "Check the hotel's entry on the sources above (name, address, photos, current facts) and ask whether the hotel wants to be in the kind of "
        "list the assistant gave. Re-run later to see whether it changes.",
        "low", "medium", confidence=EXPER, team="marketing", source="ai", tag="AI1",
        summary="Not named in a sample of AI hotel-suggestion answers")] + niche


def _from_ai_insights(ins):
    """Two things the sample can support: what the assistant said that differs from the hotel's own record, and sources it leaned on where the hotel is not evidenced."""
    if not ins or ins.get("status") not in ("ok", "partial"):
        return []
    out = []
    bad = [r for r in (ins.get("accuracy") or {}).get("rows", []) if r["status"] == "differs"]
    if bad:
        lines = "; ".join(f"{r['claim']}: the assistant said \"{r['assistant_says']}\" ({r['our_record']})" for r in bad[:3])
        out.append(_rec(
            "AI3", "authority", "An AI assistant told travellers something that differs from the hotel's own record",
            f"In the sampled answers: {lines}.",
            "Travellers who are told the wrong price, time or policy arrive with the wrong expectation. An assistant takes such details from the pages it finds, "
            "which may be out of date or ambiguous. This is one model on one day.",
            [{"url": "", "snippet": f"{r['claim']}: assistant said \"{r['assistant_says']}\"; record: {r['our_record']} ({r['source']})"} for r in bad[:3]],
            "State the real policy plainly in the first lines of the relevant page on the hotel's site, and check the same detail on the main booking and review "
            "listings the assistant used (see the source table), so every place a traveller or assistant might read agrees.",
            "medium", "low", confidence=INFER, team="web", source="ai", tag="AI3", summary="Assistant's statement differs from the hotel's record"))
    gaps = [s for s in (ins.get("sources") or []) if s["hotel_evidenced"] is False and s["kind"] in ("Booking and comparison site", "Review site")][:4]
    if gaps:
        out.append(_rec(
            "AI2", "authority", "The assistant leaned on sites where the hotel was not found",
            "Sites the assistant used that this audit did not find the hotel on: " + ", ".join(s["domain"] for s in gaps) + ".",
            "An assistant can only describe what it finds. If a site it relies on does not list the hotel (or lists it under another name), it may describe competitors instead. "
            "Not finding a listing through a search index can also be a search gap.",
            [{"url": "", "snippet": f"{s['domain']} cited in {s['answers']} answer(s); hotel not evidenced there"} for s in gaps[:3]],
            "Check whether the hotel is listed on each of these sites, under the right name, with current photos and facts; add or claim the listing where it is missing.",
            "low", "medium", confidence=EXPER, team="distribution", source="ai", tag="AI2", summary="Sources the assistant used without the hotel"))
    return out


def _from_reviews(rs):
    """Reply behaviour seen in public search results. A SAMPLE: worded as 'seen', never as a reply rate, and low-confidence."""
    if not rs or rs.get("status") != "ok":
        return []
    s = rs.get("summary") or {}
    items = rs.get("items") or []
    out = []
    first = lambda pred: [{"url": i["url"], "snippet": f"{i['platform']} review ({i.get('review_date') or 'date not shown'}): " + (i.get("reply_summary") or "no reply seen")}
                          for i in items if pred(i)][:3]
    if s.get("negative_examined", 0) >= 2 and s.get("negative_replied", 0) == 0:
        out.append(_rec(
            "RV1", "authority", "Critical reviews were visible with no reply from the hotel",
            f"Of {s['negative_examined']} critical review(s) we could examine in public search results, none showed a reply from the hotel.",
            "Public replies to critical reviews are read by prospective guests and are part of what a review page says about how a hotel treats guests. "
            "This is a small sample of what search shows, not a measure of the hotel's reply rate.",
            first(lambda i: i["sentiment"] == "negative" and i["owner_replied"] is False) or [{"url": "", "snippet": "no reply seen on the critical reviews examined"}],
            "Check the hotel's recent critical reviews on each platform and reply to the ones still unanswered: thank the guest, address what they raised "
            "specifically, say what will change, and invite them to contact the hotel. Do not offer anything in return for a changed review.",
            "medium", "low", confidence=EXPER, team="reputation management", source="reviews", tag="RV1",
            summary="Critical reviews seen without a reply")),
    elif s.get("examined", 0) >= 4 and s.get("replied", 0) == 0:
        out.append(_rec(
            "RV1", "authority", "No replies from the hotel were visible on the reviews examined",
            f"Of {s['examined']} reviews we could examine in public search results, none showed a reply from the hotel.",
            "Guests and review sites notice whether a hotel responds. This is a small sample of what search shows, not a measure of the hotel's reply rate.",
            first(lambda i: i["owner_replied"] is False) or [{"url": "", "snippet": "no reply seen on the reviews examined"}],
            "Check whether the hotel replies to reviews on each platform and, if not, set a routine: thank positive reviewers briefly and answer critical "
            "ones specifically.", "medium", "low", confidence=EXPER, team="reputation management", source="reviews", tag="RV1",
            summary="No replies seen on the reviews examined"))
    tones = s.get("tones") or {}
    if tones.get("defensive", 0) + tones.get("dismissive", 0) >= 1:
        bad = tones.get("defensive", 0) + tones.get("dismissive", 0)
        out.append(_rec(
            "RV2", "authority", "Some replies to critical reviews read as defensive",
            f"{bad} of the {s.get('replied', 0)} replies we could read were assessed as defensive or dismissive in tone (an AI's reading of a small sample).",
            "A defensive reply to a critical review is read by every later guest and can weigh more than the complaint itself.",
            first(lambda i: i["reply_tone"] in ("defensive", "dismissive")),
            "Have a senior person read those replies against the review. Where the hotel was right, say so calmly; where the guest had a point, "
            "acknowledge it and say what has changed.", "low", "low", confidence=EXPER, team="reputation management", source="reviews", tag="RV2",
            summary="Defensive tone in some replies"))
    pq = (s.get("reply_quality") or {}).get("personal") or {}
    if pq.get("judged", 0) >= 3 and pq["yes"] / pq["judged"] <= 0.34:
        out.append(_rec(
            "RV3", "authority", "Replies to reviews look generic rather than specific to the guest",
            f"Of {pq['judged']} replies we could judge, only {pq['yes']} referred to specifics of the guest's stay (an AI's reading of a small sample).",
            "A reply that could be pasted under any review reads as a template. A specific reply is the one place the hotel's own words sit inside third-party "
            "evidence that travellers, review sites and AI assistants all read.",
            first(lambda i: i["owner_replied"] and (i.get("reply_quality") or {}).get("personal") is False),
            "Reply to each review by naming what the guest raised (the room, the breakfast, the member of staff), thank them for that, and say what was done or "
            "will change. Keep a short checklist: thank, specifics, action, a named role at the end.", "low", "low", confidence=EXPER,
            team="reputation management", source="reviews", tag="RV3", summary="Replies read as generic"))
    return out


def _from_intel(intel):
    recs = []
    if not intel or "error" in intel:
        return recs
    ledger = {e["id"]: e for e in intel.get("ledger", [])}
    for r in intel.get("recommendations", []):
        rid = r["id"]
        if rid.startswith(DROP_INTEL):
            continue
        if rid.startswith("S-") and any(rid[2:].startswith(c) for c in SUPERSEDED_SCORING):
            continue
        ev = [{"url": ledger[e]["url"], "snippet": ledger[e]["extract"]} for e in r["evidence_ids"] if e in ledger]
        if not ev:
            ev = [{"url": "", "snippet": r["problem"][:220]}]
        cat = "authority" if r["section"] in ("media", "reviews", "social_local") else "understanding"
        recs.append(_rec(
            "X-" + rid, cat, r["title"], r["problem"], r["why_it_matters"], _ev(ev, 3), r["action"], r["priority"],
            EFFORT_BY_TEAM.get(r["team"], "medium"), example=r.get("example") or "",
            technical=(r["basis_note"] or ""), confidence={"documented guidance": BEST, "observation": BEST, "hypothesis": EXPER}[r["basis"]],
            team=r["team"], success=r["success_check"], source="intel"))
    return recs


# ---------------------------------------------------------------------- assemble

def build(*, questions, location, consistency, hidden, structured, machine, intel, jsonld_example, site, coverage=None, ai=None, reviews=None, text_only=False, ai_insights=None):
    coverage = coverage or {}
    recs = []
    recs += _from_questions(questions)
    recs += _from_location(location)
    recs += _from_consistency(consistency)
    recs += _from_hidden(hidden)
    if site.home is not None and not text_only:        # a "no Hotel markup" claim needs the homepage to have been read AS HTML
        recs += _from_structured(structured, jsonld_example, site)
    recs += _from_machine(machine)
    recs += _from_intel(intel)
    recs += _from_ai(ai)
    recs += _from_reviews(reviews)
    recs += _from_ai_insights(ai_insights)
    recs = drop_duplicate_entity(recs)
    limited_note = None
    if coverage.get("limited"):
        # Findings of the form "X isn't on the site" are weaker when part of the site wasn't read.
        limited_note = (f" (Only {coverage['pages_read']} of {coverage['pages_attempted']} pages could be read, so this may be "
                        "stated on a page we didn't read.)")
        for r in recs:
            if r["source"] in ("questions", "location", "hidden"):
                r["confidence"] = INFER
                r["finding"] += limited_note
    # ONE global judgement for everything the audit found (risk x traveller importance x visibility x confidence, moderated by effort)
    ranking.annotate(recs, questions)
    if limited_note:
        for r in recs:
            if r["source"] in ("questions", "location", "hidden") and r["priority"] in ("high", "critical"):
                r["priority"] = "medium"
                r["impact"] = "medium"
    for r in recs:
        r["ref"] = r["id"]
        r["expected_outcome"] = ranking.expected_outcome(r)
        r["score"] = r["rank"]          # kept for older readers of the report
    recs.sort(key=lambda r: -r["rank"])
    return recs


def top_actions(recs, n=7):
    """The few required fixes most worth doing, chosen from the whole audit by the global ranking."""
    return ranking.top_actions(recs, n=n)


def quick_wins(recs, exclude_ids=(), n=8):
    return ranking.quick_wins(recs, exclude_ids, n=n)
