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

import pagetarget
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
        if n == 1 and qs[0].get("optional") and not qs[0]["found"]:
            rec["short_title"] = f"State whether the hotel has {_OPTIONAL_NAME.get(qs[0]['id'], shorts[0].lower())}"
        else:
            rec["short_title"] = (f"Add the missing details on {shorts[0].lower()} to {where_txt}" if n == 1 else
                                  f"Answer {n} open guest questions on {where_txt}")

_OPTIONAL_NAME = {"ev": "EV charging", "pets": "a pet policy (dogs or other pets)"}


CANON = {"parking": "parking", "family": "family_rooms", "connecting_rooms": "family_rooms", "accessibility": "accessibility", "breakfast": "breakfast", "checkin_out": "checkin_out", "pets": "pets",
         "transport": "transport", "wifi": "wifi", "ev": "ev", "cancellation": "cancellation", "room_configuration": "room_config", "area_guide": "area_guide", "rate_inclusions": "rate_inclusions",
         "meeting_detail": "meetings", "wedding_detail": "weddings", "spa_detail": "spa", "pool_detail": "spa", "restaurant_detail": "restaurant_detail", "room_count": "room_count", "balconies": "room_config"}
ABSENCE_SOURCES = ("questions", "location", "hidden", "traveller")


def _inspected(site, topic):
    """The pages read that a topic belongs on (pagetarget): where a statement of it would be expected."""
    if site is None:
        return []
    allowed = pagetarget.TOPIC_TYPES.get(topic) or pagetarget.GENERAL
    return [p for p in site.content_pages if pagetarget.classify(site, p) in allowed]


def _absence_evidence(site, qs, w, coverage):
    """
    Evidence for a 'not stated' finding: what WAS found (the sentences that state each fact, never menus or telephone strips), which pages were inspected for the rest, what remains unanswered, and
    whether those pages were fully readable. -> (rows, pages inspected, fully_readable)
    """
    coverage = coverage or {}
    pages = []
    for q in qs:
        for pg in _inspected(site, q["id"]):
            pth = _path(pg["url"])
            if pth not in pages:
                pages.append(pth)
        for u in q.get("pages_with_topic", []):
            if _path(u) not in pages:
                pages.append(_path(u))
    rows = []
    for q in qs:
        for fs in (q.get("fact_snippets") or [])[:2]:
            rows.append({"url": fs["url"], "snippet": f"Found - {fs['label']}: {fs['snippet'][:200]}"})
    not_stated = sorted({m for q in qs for m in q["missing"]})
    collapsed = any(q.get("access_note") for q in qs)
    nread, natt = coverage.get("pages_read"), coverage.get("pages_attempted")
    txt = (("Pages inspected for this: " + ", ".join(pages[:4]) + (" and more" if len(pages) > 4 else "")) if pages else "No page about this topic was among the pages read")
    txt += f" ({nread} of {natt} pages read in all)." if nread else "."
    txt += (" Still not stated: " + ", ".join(not_stated[:4]) + ".") if not_stated else ""
    txt += (" Some sections of these pages had no text in the page as read, so the detail may be stated there." if collapsed else (" The text of these pages was fully readable." if pages else ""))
    return [{"url": w.get("url", "") if pages else "", "snippet": txt}] + rows, pages, not collapsed


def _from_questions(questions, site=None, coverage=None, suppressed=None):
    coverage = coverage or {}
    limited = bool(coverage.get("limited") or coverage.get("text_only"))
    kept_qs = []
    for q in questions:
        # nothing found at all, and no page this information belongs on was read: it cannot be said whether it is stated, so no recommendation is made
        if limited and site is not None and not q.get("found") and not q.get("fact_snippets") and not _inspected(site, q["id"]) and q["source"] != "location":
            if suppressed is not None:
                suppressed.append({"topic": q.get("short") or q["question"], "why": "no page this information belongs on was among the pages read, so it cannot be said whether it is stated"})
            continue
        kept_qs.append(q)
    groups = {}
    for q in kept_qs:
        w = q["where"]
        # a guest-information gap and a gap in the detail of a segment the hotel promotes (weddings, spa,
        # meeting rooms) are different kinds of thing, so they are not grouped together
        kind = "opportunity" if (q.get("source") == "extended" or q.get("relevance") == "secondary") else "fix"
        key = (w["url"] or w["label"], kind)
        groups.setdefault(key, {"where": w, "qs": [], "kind": kind})["qs"].append(q)
    recs = []
    for i, (key, g) in enumerate(groups.items(), 1):
        qs, w = g["qs"], g["where"]
        high = any(q.get("high_value") and q["state"] in ("missing", "unclear") for q in qs)
        partial_high = any(q.get("high_value") for q in qs)
        n = len(qs)
        priority = "high" if high or n >= 4 else ("medium" if partial_high or n >= 2 else "low")
        unread = all(q.get("access_note") for q in qs)
        if unread:
            priority = {"high": "medium", "medium": "low", "low": "low"}[priority]      # the answer may be in text the reader could not see
        adds = []
        for q in qs:
            for m in q["missing"]:
                adds.append(f"{q['question'].rstrip('?')} - add: {m}" if n > 1 else m[:1].upper() + m[1:])
        topics = [q["question"].rstrip("?") for q in qs]
        where_txt = f"{_path(w['url'])}" if w["url"] else w["label"]
        found_bits = [f for q in qs for f in q["found"]][:3]
        if g["kind"] == "opportunity":
            shorts = [q.get("short") or q["question"].rstrip("?") for q in qs]
            secondary = all(q.get("relevance") == "secondary" for q in qs)
            finding = ((f"The site offers {', '.join(sh.lower() for sh in shorts[:4])}, which is not what the hotel mainly serves, and the pages don't yet state: " if secondary
                        else f"The hotel promotes {', '.join(sh.lower() for sh in shorts[:4])}, but the pages don't yet state: ")
                       + "; ".join(sorted({m for q in qs for m in q["missing"]})[:6]) + (". Optional: worth completing only if this is a market you want." if secondary else ". Worth completing if this is a segment you want to attract."))
            title = ("Optional: complete the details on " if secondary else "If this is a target segment, complete the details: ") + ", ".join(shorts[:3])
        elif n == 1 and qs[0].get("optional") and not qs[0]["found"]:
            # nothing on the site says whether the hotel has this: we cannot know it does, so the advice is to say either way, never to provide it
            q = qs[0]
            finding = (f"None of the pages read says whether the hotel has {_OPTIONAL_NAME.get(q['id'], q['short'].lower())}. We cannot tell whether it is offered, so this is not a suggestion to provide it; "
                       "guests who need it check before they book, and an assistant cannot answer for a hotel that does not say.")
            title = f"State whether the hotel has {_OPTIONAL_NAME.get(q['id'], q['short'].lower())}"
        elif n == 1:
            q = qs[0]
            finding = (f"{q['question']} " + ("The site touches on it" + (f" ({', '.join(found_bits)})" if found_bits else "") +
                                                 f" but doesn't say {', '.join(q['missing'])}." if q["missing"] else "No page we read answers it clearly."))
            title = f"Answer this clearly: {q['question']}"
        else:
            shorts = [q.get("short") or q["question"].rstrip("?") for q in qs]
            finding = (f"{n} questions guests ask are only partly answered or not answered: "
                       + "; ".join(f"{sh}: " + (f"the page states {', '.join(q['found'][:2])}" if q["found"] else "nothing found")
                                   + (f"; not stated: {', '.join(q['missing'][:2])}" if q["missing"] else "") for sh, q in zip(shorts, qs[:5])) + ".")
            title = (f"Fill the gaps on {where_txt}: " + ", ".join(shorts[:3])
                     + (f" and {n - 3} more" if n > 3 else ""))
        ev, inspected_pages, readable = _absence_evidence(site, qs, w, coverage)
        examples = [q["example"] for q in qs if q.get("example")][:3]
        if unread:
            finding += " Note: " + next(q["access_note"] for q in qs if q.get("access_note"))
        verified = (not limited) and bool(inspected_pages) and readable and any(q.get("high_value") for q in qs)
        recs.append(_rec(
            f"Q{i}", "content", title, finding, WHY_QUESTION, _ev(ev, 4),
            ((f"Add one sentence to {where_txt} ({w['reason']}): the details if the hotel has it, or that it does not." if (n == 1 and qs[0].get("optional") and not qs[0]["found"]) else f"Add the answer to {where_txt} ({w['reason']}).")
             if w["url"] else f"Add a short section to {w['label']} with the answers (no existing page covers this).")
            + (f" Also worth repeating on {_path(w['also'][0]['url'])}." if w.get("also") and w["also"][0].get("url") != w.get("url") else ""),
            priority, "low" if len(adds) <= 8 else "medium", page={"url": w["url"], "label": where_txt} if w["url"] else {"url": "", "label": w["label"]},
            additions=adds[:10], example="\n".join(examples),
            technical="Content-completeness gap. Write each answer as plain text in a clearly headed section so it can be quoted; "
                      "optionally mark up an FAQ section as FAQPage (see structured data).",
            confidence=BEST if verified else INFER, team="web",
            success="The question is answered in plain text on the page and the next audit marks it 'answered'.",
            source="questions", question_ids=[q["id"] for q in qs]))
        recs[-1]["topics"] = sorted({CANON.get(q["id"], q["id"]) for q in qs})
        recs[-1]["absence_based"] = True
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
    sc = sd.get("scope") or {}
    n_pages = sc.get("pages_inspected") or len(site.pages)
    inspected = f"the {n_pages} page(s) inspected" + (f" ({', '.join(sc['relevant_inspected'][:4])})" if sc.get("relevant_inspected") else "")
    if hotel and hotel["status"] == "missing":
        recs.append(_rec(
            "SD1", "understanding", "Add Hotel structured data to the homepage",
            f"No Hotel, LodgingBusiness or LocalBusiness structured data was found in the page source of {inspected}. The hotel's name, address and phone are stated in sentences, so every system reading the page has to work these facts out for itself. "
            + (f" The only structured data seen is {', '.join(sc['types_seen'])}, none of which describes the hotel itself." if sc.get("types_seen") else "")
            + " This is what the pages contained when fetched: markup added after the page loads, or on pages not inspected, would not show here.",
            "Structured data states the hotel's basic facts in a standard form that search engines and AI tools can read directly, which reduces the chance of a wrong or missing fact. It supports accuracy; there is no evidence that it makes an assistant recommend a hotel.",
            [{"url": site.base, "snippet": f"No Hotel/LodgingBusiness/LocalBusiness JSON-LD in the source of {inspected}"}],
            "Give the web developer this: add one JSON-LD <script> block of type Hotel to the homepage (in the page head, or through the CMS's SEO plugin) with name, url, telephone, address (PostalAddress), geo (GeoCoordinates), image, checkinTime, checkoutTime and sameAs (the official profiles). "
            "The block below is filled only from facts read on your own pages; anything in [brackets] must be filled by the hotel, and nothing should be added that the hotel cannot stand behind (no ratings, no facilities it does not offer). "
            "First check the live page at search.google.com/test/rich-results in case a tag manager already adds one; then validate the result at validator.schema.org.",
            "high", "low", page={"url": site.base, "label": "the homepage"}, example=jsonld_example or "",
            technical="schema.org Hotel on the homepage: name, url, telephone, PostalAddress, GeoCoordinates, image, checkinTime, checkoutTime, sameAs. Mark each value to match the visible page text. " + CAUTION_SHORT,
            confidence=BEST, team="web", success="A Hotel block is present on the homepage, validates, and matches the page text.", source="structured", tag="SD1",
            summary="No Hotel structured data on the pages inspected"))
    elif hotel and hotel["status"] == "could_improve" and sd.get("generic_only"):
        recs.append(_rec(
            "SD1", "understanding", "Change the structured data type from a generic business to Hotel",
            hotel["detail"], "A generic business type tells a reading system less than Hotel: it cannot tell a hotel from any other local business.", _ev(hotel["evidence"], 3),
            hotel["advice"] + " Keep the existing properties; add any of name, address, telephone, geo, image, checkinTime, checkoutTime and sameAs that are missing, and validate at validator.schema.org.",
            "medium", "low", page={"url": site.base, "label": "the homepage"}, example=jsonld_example or "", technical="Change @type from LocalBusiness to Hotel. " + CAUTION_SHORT,
            confidence=BEST, team="web", success="The block is typed Hotel and validates.", source="structured", tag="SD1", summary="Structured data is typed as a generic business"))
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
DROP_INTEL = ("V3", "T2-", "W1", "T1", "T3", "M5")      # limits, or superseded by findings above, or preparation steps with no verified issue behind them (M5: 'prepare the pitch evidence')
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


def _from_ai_gap(gap):
    """
    Investigations and outreach, only from what the sampled answers and the pages read actually show. An investigation says: the hotel was not named for this question, these hotels were, this is what the
    evidence shows about the difference, look into it. It never says more content will fix it, and never promises to change what an assistant says. An outreach suggestion names the exact article and
    is made only for an editorial list that is not sponsored, names rivals and leaves the hotel out.
    """
    if not gap or gap.get("status") != "ok" or not gap.get("gaps"):
        return []
    ms = {m["qid"]: m for m in gap.get("markets") or []}
    obs, steps, arts = gap.get("observations") or {}, gap.get("investigate") or {}, gap.get("articles") or []
    order = sorted((ms[q] for q in gap["gaps"] if q in ms), key=lambda m: (not m["consistent"], m["status"] != "not_named", m["kind"] not in ("niche", "custom"), m["qid"]))
    out = []
    for k, m in enumerate(order[:3], 1):
        names = ", ".join(r["name"] for r in m["rivals"][:3])
        counts = "; ".join(f"{r['name']} in {r['answers']} of {r['of']}" for r in m["rivals"][:3])
        q = m["question"] if len(m["question"]) <= 95 else m["question"][:92].rstrip() + "..."
        ev = [{"url": (o["urls"] or [""])[0], "snippet": o["text"][:260]} for o in obs.get(m["qid"], [])[:4]] or [{"url": "", "snippet": f"Named instead: {counts}."}]
        out.append(_rec(
            "AG-" + m["qid"], "authority", f"Not named when asked “{q}”: {names} {'were' if len(m['rivals']) > 1 else 'was'}",
            f"When one assistant was asked “{m['question']}”, it named the hotel in {m['named']} of {m['of']} answers. It named instead: {counts}."
            + (" Every answer named the same leading hotel." if m["consistent"] else "") + " One assistant on one day is a sample.",
            "A traveller who asks an assistant this question is shown those hotels, not this one. The sample cannot say why the assistant chose them, but the observations show where the evidence about the hotel differs from the evidence about them.",
            ev, " ".join((steps.get(m["qid"]) or [])[:3]) or "Compare what the named hotels state and which independent sources feature them with what the hotel's pages and outside sources say.",
            "medium" if m["consistent"] else "low", "medium", confidence=EXPER, team="marketing", source="ai", tag=f"AG{k}", summary=f"Not named for: {q}"))
        out[-1]["kind_hint"] = "opportunity"
    n = 0
    for a in arts:
        if not a.get("opportunity") or n >= 3:
            continue
        n += 1
        qs = [ms[x]["question"] for x in a.get("questions") or [] if x in ms]
        dated = f" It is dated {a['published']}; check it is still being kept up to date." if a.get("published") else " Its date could not be read, so check it is current."
        out.append(_rec(
            f"AG-OUT-{n}", "authority", f"Ask {a['domain']} whether the hotel can be included in “{a['title'][:80]}”",
            f"The assistant cited this page when asked “{qs[0] if qs else 'a hotel question'}”. It names {', '.join(a['rivals_in'][:3])} and does not mention the hotel.{dated}",
            "A page the assistant reads and cites is one place it learns which hotels to name. Being fairly described in a page like this is a legitimate way to be found; it is not a guarantee of being recommended.",
            [{"url": a["url"], "snippet": a.get("rival_sentence") or a.get("passage") or a["title"]}],
            "If the hotel genuinely fits what the article covers, write to the publication's editor with accurate, factual information (what the hotel offers, where it is, anything new). Do not pay for a placement presented as editorial, "
            "and do not ask for changes to reviews. Check the page is current first.",
            "low", "medium", confidence=EXPER, team="PR", source="ai", tag=f"AGO{n}", summary="An editorial list the assistant cited that omits the hotel"))
        out[-1]["kind_hint"] = "opportunity"
    return out


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


def _from_review_pack(p):
    """Findings from the hotel's own review export. Counts are for the file supplied; the reading of how replies were written is rule-based and said so."""
    if not p or not p.get("reviews"):
        return []
    n, out = p["reviews"], []
    ev = lambda text: [{"url": "", "snippet": text}]      # noqa: E731
    cu, ct = p.get("critical_unanswered"), p.get("critical", 0)
    if cu:
        out.append(_rec(
            "RP1", "authority", f"{cu} critical review(s) in the export have no reply",
            f"Of {ct} critical review(s) (rated 2.5 or below out of 5) in the {n}-review export, {cu} have no reply from the hotel.",
            "A reply to a critical review is read by every later guest and sets the tone of what the review page says about the hotel. It is also the one place the hotel's own words sit "
            "inside third-party evidence.", ev(f"{cu} of {ct} critical reviews unanswered in the export supplied"),
            "Work through the unanswered critical reviews, newest first (the list and starting drafts are under Beyond your website, Reviews & reputation). Thank the guest, address what they "
            "raised specifically, say what has been done, and give a way to get in touch. Do not offer anything in return for a changed review.",
            "high" if cu >= 5 or (ct and cu / ct > 0.5) else "medium", "medium", confidence=BEST, team="reputation management", source="review_pack", tag="RP1", summary="Critical reviews without a reply"))
    rr = p.get("reply_rate")
    if rr is not None and n >= 30 and rr < 50:
        out.append(_rec(
            "RP2", "authority", f"The hotel replied to {rr}% of the reviews in the export",
            f"{p['replied']} of the {n} reviews in the export have a reply ({rr}%).",
            "Guests and AI assistants read what a hotel says back as well as what was said about it. A low reply rate leaves most of the review history one-sided.",
            ev(f"{p['replied']} of {n} reviews replied to, in the export supplied"),
            "Set a routine: every critical review within three days, and a short specific thank-you for positive reviews that mention something concrete.",
            "medium", "medium", confidence=BEST, team="reputation management", source="review_pack", tag="RP2", summary="Low reply rate"))
    t = p.get("templates") or {}
    if t.get("pct") is not None and t.get("replies_compared", 0) >= 10 and t["pct"] >= 40:
        out.append(_rec(
            "RP3", "authority", "Many replies are the same text",
            f"{t['in_repeated_templates']} of {t['replies_compared']} replies ({t['pct']}%) are identical or near-identical to another once the greeting and sign-off are removed; the largest group is {t['largest_group']} replies.",
            "A reply that could sit under any review reads as a template, to guests and to anything that reads the page.",
            ev(f"{t['pct']}% of replies in repeated templates"),
            "Keep a short structure (thank, one specific detail, what was done, a named role) but write the detail each time.", "low", "low", confidence=EXPER, team="reputation management",
            source="review_pack", tag="RP3", summary="Replies repeat the same text"))
    pq = (p.get("reply_quality") or {}).get("personal") or {}
    if pq.get("judged", 0) >= 10 and pq["yes"] / pq["judged"] <= 0.34 and not (t.get("pct") is not None and t["pct"] >= 40):
        out.append(_rec(
            "RP4", "authority", "Replies rarely refer to what the guest said",
            f"Only {pq['yes']} of {pq['judged']} replies echo specifics from the review (a rule-based reading of the file).",
            "A specific reply is the one place a hotel's own words sit inside third-party evidence that travellers and AI assistants read.",
            ev(f"{pq['yes']} of {pq['judged']} replies specific"), "Name what the guest raised (the room, the breakfast, a member of staff), thank them for that, and say what was done.",
            "low", "low", confidence=EXPER, team="reputation management", source="review_pack", tag="RP4", summary="Replies read as generic"))
    rt = p.get("response_time") or {}
    if rt.get("measured", 0) >= 10 and rt.get("median_days") is not None and rt["median_days"] > 7:
        out.append(_rec(
            "RP5", "authority", f"Replies take a median of {rt['median_days']:g} days",
            f"Across {rt['measured']} replies with both dates, the median time to reply was {rt['median_days']:g} days and {rt['within_3_days_pct']}% were within 3 days.",
            "A late reply to a critical review has already been read many times.", ev(f"median {rt['median_days']} days over {rt['measured']} replies"),
            "Aim to answer critical reviews within three days; assign one person and a weekly slot.", "low", "low", confidence=EXPER, team="reputation management", source="review_pack", tag="RP5",
            summary="Slow replies"))
    gaps = [r for r in p.get("praised", []) if r.get("site") in ("not_found", "partial", "needs_checking") and r["reviews"] >= 3]
    if gaps:
        names = ", ".join(r["topic"] for r in gaps[:3])
        out.append(_rec(
            "RP6", "content", f"Guests praise {names}, but the website does not state it clearly",
            "; ".join(f"{r['reviews']} positive review(s) mention {r['topic']}" for r in gaps[:3]) + ", yet the hotel's own pages do not fully state the details a guest looks for.",
            "What guests praise is what the next guest wants to know. If the website does not say it in plain language, an assistant finds it on a review site and cites that instead.",
            ev("praised in reviews; not clearly stated on the site"), "State it in plain sentences on the relevant page (times, what is included, the price) and use the guests' own words.",
            "medium", "low", confidence=INFER, team="web", source="review_pack", tag="RP6", summary="Praised in reviews but not stated on the site"))
    rec_c = [r for r in p.get("criticised", []) if r["reviews"] >= 3 and (r.get("pct") or 0) >= 15]
    if rec_c:
        names = ", ".join(r["topic"] for r in rec_c[:3])
        out.append(_rec(
            "RP7", "authority", f"A recurring complaint: {names}",
            "; ".join(f"{r['topic']} in {r['reviews']} critical or mixed review(s) ({r['pct']}%)" for r in rec_c[:3]) + ".",
            "A complaint that recurs is both a guest problem to fix and an expectation to set: what the website says about it decides whether the next guest is surprised.",
            ev("recurring topics in critical and mixed reviews"), "Look at the cause first. Where it cannot be fixed soon, say plainly on the website what guests should expect.",
            "medium", "medium", confidence=INFER, team="operations", source="review_pack", tag="RP7", summary="Recurring complaint"))
    return out


def _from_listing_checks(lc):
    """Differences between what travel sites show and what the hotel's own site says, and listings that still carry a former name. Worded as 'worth checking'."""
    if not lc:
        return []
    out = []
    diff = [r for r in lc.get("rows", []) if r["status"] == "differs"]
    if diff:
        names = sorted({r["platform"] for r in diff})
        out.append(_rec(
            "LC1", "authority", "A travel site shows different details from the hotel's own site",
            f"{len(diff)} fact(s) on {', '.join(names)} differ from the hotel's own pages: "
            + "; ".join(f"{r['platform']} shows {r['fact'].lower()} {r['listing_says']}, the site says {r['site_says']}" for r in diff[:4]) + ".",
            "Guests and AI assistants meet the same fact in several places. When they disagree, an assistant may repeat the wrong one, and a guest arrives expecting it. "
            "The listing may be right and the hotel's own site out of date, so the first step is to find out which.",
            [{"url": r["url"], "snippet": f"{r['platform']}, {r['fact'].lower()}: {r['passage'] or r['listing_says']}"} for r in diff[:3]],
            "Decide which figure is correct, then correct the other: update the hotel's own pages, or the platform's extranet (check-in and check-out times, star rating and phone "
            "number are set there). These were read from short passages in public search results, so look at the live listing before changing anything.",
            "medium", "low", confidence=EXPER, team="distribution", source="listings", tag="LC1", summary="Travel-site details differ from the website"))
    fn = lc.get("former_name") or []
    if fn:
        out.append(_rec(
            "LC2", "authority", "A listing still shows a former name of the hotel",
            "; ".join(f"{h['platform']} still shows '{h['name']}' (page title: {h['title'] or 'not shown'})" for h in fn[:4]) + ".",
            "After a rebrand the old name lingers in listings and then in AI answers for years. A guest or an assistant matching on the old name finds a page that does not "
            "carry the current one.",
            [{"url": h["url"], "snippet": f"{h['platform']}: {h['title'] or h['name']}"} for h in fn[:3]],
            "Ask each platform to update the property name (through the extranet or the platform's support), and use the new name in the property description. "
            "Keep the former name in the description for a while ('formerly ...') so searches for it still land here.",
            "medium", "low", confidence=EXPER, team="distribution", source="listings", tag="LC2", summary="Listing shows a former name"))
    return out


def _from_reddit(rd):
    """Findings from the Reddit check. Worded as what the searches found: they see public search results, not all of Reddit, and the advice is to take part honestly, never to seed posts."""
    if not rd or rd.get("status") != "ok":
        return []
    sm, out = rd["summary"], []
    ev_threads = lambda ts: [{"url": t["url"], "snippet": f"r/{t['subreddit']}: {t['title']}"} for t in ts[:3]]      # noqa: E731
    honest = ("Take part as the hotel, openly: answer questions in the town's subreddit from an account that says who it is, follow that subreddit's rules on promotion, and correct wrong "
              "facts politely. Do not post as a guest, seed reviews, or ask anyone to vote or to delete a thread: Reddit bans for it and assistants learn to discount it.")
    if sm["hotel_mentioned"] is False and sm["town_threads"]:
        out.append(_rec(
            "RD1", "authority", "The hotel does not appear in the Reddit threads where travellers ask where to stay",
            f"{sm['town_threads']} traveller thread(s) about the town turned up in searches of Reddit's public pages and none of them mentions the hotel. This is a sample of what search can see, "
            "not all of Reddit.",
            "Reddit is one of the sources AI assistants cite most for where-to-stay questions. A hotel that is never named in those threads is leaving the assistant to describe its competitors.",
            ev_threads(rd["town_threads"]), honest, "medium", "medium", confidence=EXPER, team="PR and social", source="reddit", tag="RD1", summary="Not named in Reddit where-to-stay threads"))
    crit = [t for t in rd["hotel_threads"] if t["tone"] == "critical"]
    if crit:
        out.append(_rec(
            "RD2", "authority", f"{len(crit)} Reddit thread(s) about the hotel read as critical",
            f"{len(crit)} of {len(rd['hotel_threads'])} thread(s) that name the hotel have a passage that reads as critical (a rule-based reading of the quoted passage: open the thread to judge it).",
            "A critical thread stays findable for years and is the kind of page an assistant quotes when asked what guests say.",
            ev_threads(crit), "Read each thread. Fix what is genuinely wrong, then, where the subreddit allows it, reply once as an identified member of the hotel's team with what has changed. "
            "Never ask for a thread to be removed or for votes either way.", "medium", "low", confidence=EXPER, team="reputation management", source="reddit", tag="RD2", summary="Critical Reddit threads"))
    if sm["ai_cited_reddit"] and not sm["ai_threads_name_hotel"]:
        out.append(_rec(
            "RD3", "authority", f"AI assistants cited Reddit in {sm['ai_cited_reddit']} of {sm['ai_answers']} sampled answers, and not for this hotel",
            f"In {sm['ai_cited_reddit']} of {sm['ai_answers']} sampled answers the assistant relied on Reddit; none of the threads it cited names the hotel.",
            "When an assistant builds its answer from Reddit threads, the hotels named in those threads are the hotels it can recommend.",
            ev_threads(rd["ai_threads"]) or [{"url": "", "snippet": f"Reddit cited in {sm['ai_cited_reddit']} of {sm['ai_answers']} sampled answers"}], honest, "medium", "medium",
            confidence=EXPER, team="PR and social", source="reddit", tag="RD3", summary="AI answers cite Reddit, not the hotel"))
    return out


TRAVELLER_WHY = {
    "spa_couples": "Couples choosing a spa break compare what the spa includes, who may use it, what it costs and how to book. Where those facts are not stated, the hotel loses the booking to one that states them, and an assistant asked for a romantic spa break has nothing specific to quote.",
    "families": "Parents choose by whether a room physically fits the family and by what the hotel does for children. A room that does not say how many it sleeps is one they cannot book with confidence, and an assistant asked for a family-friendly hotel cannot say whether this one fits.",
    "business": "Business travellers decide on a short list of practical facts: Wi-Fi, parking, meeting space, how to get there. Where one is not stated they ask elsewhere or book a hotel that states it, and an assistant answering a business-travel question will not quote what the site does not say.",
    "location": "People search by place (hotels near a station, an airport or a venue). A place named without a distance or time is a much weaker location signal than 'a 10-minute walk'.",
    "airport_stay": "Travellers with a flight decide on a few facts: how far the airport is and how to get there, whether there is a shuttle and what it costs, what happens with a very early departure or a late arrival, and where to park. An airport hotel that leaves these unstated loses the booking to one that states them.",
}
TRAVELLER_TEAM = {"spa_couples": "marketing", "families": "operations", "business": "sales", "location": "marketing", "airport_stay": "operations"}
TRAVELLER_CORE = {"spa_facilities", "restrictions", "family_rooms", "occupancy", "children_policy", "wifi", "parking", "meetings", "transport", "loc_transport", "loc_airports",
                  "airport_distance", "airport_shuttle", "airport_parking", "airport_public_transport", "airport_early_late"}
TRAVELLER_SUPERSEDES = {"business": ("meeting_detail",), "spa_couples": ("spa_detail",), "families": ("connecting_rooms",)}


TR_CANON = {"family_rooms": "family_rooms", "occupancy": "family_rooms", "children_policy": "family_rooms", "family_facilities": "family_rooms", "connecting": "family_rooms", "accommodation": "room_config",
            "wifi": "wifi", "parking": "parking", "airport_parking": "parking", "meetings": "meetings", "transport": "transport", "loc_transport": "transport", "loc_airports": "transport",
            "airport_distance": "transport", "airport_public_transport": "transport", "spa_facilities": "spa", "couples_packages": "spa", "restrictions": "spa", "dining": "restaurant_detail",
            "business_amenities": "business_amenities", "airport_shuttle": "airport_transfer", "airport_early_late": "airport_early_late", "airport_stopover": "airport_stopover",
            "loc_attractions": "attractions", "loc_venues": "venues", "loc_journeys": "journeys"}


def _tr_topics(trv):
    """The topics the traveller-requirement check assesses for the segments it ran: it is the authority on them, so the general guest-question finding for the same topic is not raised as well."""
    return {TR_CANON.get(r["id"], r["id"]) for seg in (trv or {}).get("segments", []) for r in seg["requirements"] if r["state"] != "unknown"}


def _from_traveller(trv, coverage=None, site=None):
    """
    One finding per kind of traveller whose requirements are missing or incomplete. Each names the information to add and the EXISTING page each item belongs on (chosen by page type, never
    by a matching word), cites what the site does say and which pages were inspected for the rest, and is marked optional when the segment is not what this kind of hotel mainly serves.
    A requirement the site denies ('not available') and one that is Unknown raise nothing.
    """
    coverage = coverage or {}
    limited = bool(coverage.get("limited") or coverage.get("text_only"))
    out = []
    for seg in (trv or {}).get("segments", []):
        todo = [r for r in seg["requirements"] if r["state"] in ("partial", "missing")]
        if not todo:
            continue
        secondary = seg.get("relevance") == "secondary"
        by_page = {}
        for r in todo:
            w = r.get("where") or {"url": "", "label": "the hotel's general information page", "reason": ""}
            slot = by_page.setdefault(w.get("url") or w.get("label"), {"w": w, "adds": []})
            slot["adds"] += list(r["add"][:2])
        pages = list(by_page.values())
        main = pages[0]["w"]
        names = [r["label"].lower() for r in todo]
        adds = [f"{r['label']}: {a}" for r in todo for a in r["add"]]
        ev, all_readable, any_inspected = [], True, False
        for r in todo:
            insp = r.get("inspected") or []
            any_inspected = any_inspected or bool(insp)
            all_readable = all_readable and r.get("readable", True) and not r.get("why")
            for f in r["found"][:2]:
                ev.append({"url": f["url"], "snippet": f"Found - {r['label']}: {f['snippet'][:180]}"})
            ev.append({"url": (r.get("where") or {}).get("url", ""), "snippet": (f"{r['label']}: pages inspected for this: {', '.join(insp)}; " if insp else f"{r['label']}: ")
                       + ("still not stated: " + ", ".join(m.split(' (')[0] for m in r["missing"][:3]) if r["missing"] else "not stated") + ("." if r.get("readable", True) else ". Some sections of these pages had no text in the page as read.")})
        n_missing, n_partial = sum(1 for r in todo if r["state"] == "missing"), sum(1 for r in todo if r["state"] == "partial")
        status = ([f"{n_missing} not stated"] if n_missing else []) + ([f"{n_partial} only partly stated"] if n_partial else [])
        first = todo[0]
        what = (f"state {first['add'][0]}" if len(todo) == 1 and first["add"] else f"complete {len(todo)} things travellers need ({', '.join(names[:3])})")
        title = (f"Optional - {seg['label']}: " if secondary else f"{seg['label']}: ") + what
        core = any(r["id"] in TRAVELLER_CORE for r in todo) and not secondary
        action = "; ".join(("Add to the existing " + (f"{_path(pg['w']['url'])} page" if pg["w"].get("url") else f"{pg['w'].get('label', 'general information')}") + ": " + "; ".join(pg["adds"])[:260]) for pg in pages[:3])
        action += ". State only what the hotel actually offers; check each fact before publishing."
        verified = (not limited) and any_inspected and all_readable
        out.append(_rec(
            f"TR-{seg['key']}", "content", title,
            f"For {seg['goes_to']}, {', '.join(status)}: " + "; ".join(f"{r['label']} ({'not stated' if r['state'] == 'missing' else 'partly stated: missing ' + ', '.join(m.split(' (')[0] for m in r['missing'][:2])})" for r in todo) + "."
            + (" This is not the market the hotel mainly serves, so treat it as optional." if secondary else ""),
            TRAVELLER_WHY[seg["key"]], _ev(ev, 5), action, "high" if n_missing and core else "medium", "low",
            page={"url": main.get("url", ""), "label": _path(main["url"]) if main.get("url") else main.get("label", "")}, additions=adds[:8],
            technical="Traveller-requirement check: each requirement was matched against the visible text of the pages read; the state is Confirmed, Partially confirmed, Missing, Unknown or Stated as not available.",
            confidence=BEST if verified else INFER, team=TRAVELLER_TEAM.get(seg["key"], "web"), source="traveller", tag="TR-" + seg["key"],
            success="The next audit shows these requirements as Confirmed.", summary="; ".join(names[:4])))
        out[-1]["kind_hint"] = "fix" if core else "opportunity"
        out[-1]["risk_hint"] = 1 if secondary else (3 if sum(1 for r in todo if r["state"] == "missing" and r["id"] in TRAVELLER_CORE) >= 2 else 2)
        out[-1]["topics"] = sorted({TR_CANON.get(r["id"], r["id"]) for r in todo})
        out[-1]["absence_based"] = True
    return out


def _from_competitors(cp, site=None):
    """Opportunities where the hotel offers something but says less about it than comparable hotels do. Only verified comparisons (both sides read) are raised."""
    if not cp or cp.get("status") != "ok":
        return []
    out = []
    names = ", ".join(c["name"] for c in cp["competitors"])
    for c in cp["comparisons"]:
        if not c["behind"] or not c["missing"]:
            continue
        better = [r for r in c["rivals"] if r["depth"] > c["own_depth"]]
        slugs = {"spa_detail": ("spa", "wellness"), "meeting_detail": ("meeting", "conference", "events"), "pool_detail": ("pool", "spa", "leisure"), "restaurant_detail": ("restaurant", "dining", "eat"),
                 "wedding_detail": ("wedding",), "connecting_rooms": ("family", "rooms")}.get(c["topic"], ())
        pg = site.best_page(slugs) if site is not None and slugs else None
        page = {"url": pg["url"], "label": site.path(pg)} if pg else {"url": "", "label": f"your {c['label']} page"}
        ev = [{"url": "", "snippet": f"Your pages state {c['own_depth']} of {c['of']}: {', '.join(c['own_stated']) or 'none'}"}] + [e for r in better[:2] for e in r["evidence"][:1]]
        out.append(_rec(
            "CP-" + c["topic"], "authority", f"Say more about {c['label']}: comparable hotels state more",
            c["statement"] + f" Compared with {names} (chosen as comparable by rating or size and by facilities).",
            "A traveller, or an assistant answering for one, can only recommend a hotel for what its pages say. Where comparable hotels are specific and yours is not, they are the easier ones to recommend.",
            _ev(ev, 3), (f"Add to the existing {page['label']} page: " if page["url"] else f"Add to {page['label']}: ") + "; ".join(c["missing"][:4]) + ". State only what the hotel offers.",
            "medium", "low", page=page, additions=c["missing"][:5], example=c["example"], technical="Comparison of the facts each hotel's own pages state, on pages that were read for both hotels.",
            confidence=INFER, team="marketing", success="The page states these details.", source="competitors", tag="CP-" + c["topic"], summary=c["statement"][:200]))
        out[-1]["kind_hint"] = "opportunity"
    return out


def _from_external(ep):
    """
    Findings from the external-presence check. Travel-platform differences are raised by the listing check (LC1); this adds what the open data (OpenStreetMap, Wikidata) shows that disagrees with the
    website or does not link to it, and any source where something was found but could not be tied to this hotel. A source that was simply not verified raises nothing.
    """
    if not ep:
        return []
    out = []
    open_rows = [r for r in ep["rows"] if r["source"] in ("OpenStreetMap", "Wikidata")]
    contra = [(r, c) for r in open_rows for c in r["contradictions"]]
    if contra:
        r0 = contra[0][0]
        out.append(_rec(
            "EX1", "authority", "Open map data disagrees with the website: " + "; ".join(sorted({r["source"] for r, _c in contra})),
            "; ".join(f"{r['source']}: {c}" for r, c in contra[:4]) + ".",
            "OpenStreetMap and Wikidata are read directly by search engines and AI tools, which use them to check a hotel's facts. When they disagree with the hotel's own site, a system may repeat the wrong one.",
            [{"url": r["url"], "snippet": c} for r, c in contra[:3]],
            "Decide which is right. If the website is right, correct the entry (OpenStreetMap and Wikidata can be edited by anyone with an account: say who you are and keep the edit factual). If the entry is right, update the website.",
            "medium", "low", technical="Fact comparison against open data, from the entries' own fields.", confidence=BEST, team="distribution", success="The entries and the website agree.", source="external", tag="EX1",
            summary="Open data disagrees with the website"))
    nolink = [r for r in open_rows if r["status"] in ("verified",) and r["official_link"] == "not stated"]
    if nolink:
        out.append(_rec(
            "EX2", "authority", "The open-data entry for the hotel does not link to its website",
            "; ".join(f"{r['source']} found and matched, but it states no official website" for r in nolink) + ".",
            "A link from an open-data entry to the official site lets a system connect the two as one hotel with more confidence.",
            [{"url": r["url"], "snippet": f"{r['source']}: matched to the hotel, no official website stated"} for r in nolink[:3]],
            "Add the hotel's official website address to the entry (OpenStreetMap: the website tag on the hotel's place; Wikidata: the official website property). Edit as the hotel, factually and once.",
            "low", "low", technical="No website field in the matched entry's data as retrieved.", confidence=INFER, team="distribution", success="The entry links to the official website.", source="external", tag="EX2",
            summary="Open-data entry has no website link"))
    unclear = [r for r in ep["rows"] if r["status"] == "unclear" and r["source"] not in ("Independent travel publications",)]
    if unclear:
        out.append(_rec(
            "EX3", "authority", "Check the hotel's own listing on " + ", ".join(r["source"] for r in unclear[:3]),
            "; ".join(f"{r['source']}: {r['note'][:160]}" for r in unclear[:3]),
            "If a platform's own listing cannot be told apart from a page that merely mentions the hotel, a system looking for the listing may not find it, and guests may land on the wrong page.",
            [{"url": r["url"], "snippet": r["note"][:160]} for r in unclear[:3] if r["url"]] or [{"url": "", "snippet": unclear[0]["note"][:160]}],
            "Open each platform's extranet (or search the platform for the hotel by name and town) and confirm the listing's name, address and website link are the hotel's.",
            "low", "low", technical="A page was found in search results but its title and address did not name the hotel.", confidence=INFER, team="distribution", success="The listing is found and confirmed.", source="external", tag="EX3",
            summary="Listing identity unclear"))
    return out


def _from_booking(bk):
    """Findings from the booking-readiness check. A destination that merely refused the automated check is never reported as broken."""
    if not bk or bk.get("status") != "ok":
        return []
    out = []
    by = {c["id"]: c for c in bk.get("checks", [])}
    link = by.get("link")
    if link and link["state"] == "fail":
        out.append(_rec(
            "BK1", "content", "Make the way to book obvious on the homepage",
            link["detail"], "An assistant can send a traveller to the website, but if the traveller cannot see how to book once there, the visit ends without a booking.",
            [{"url": link["url"], "snippet": link["detail"][:200]}],
            "Put a clearly labelled 'Book now' (or 'Check availability') link in the homepage header, linking straight to the booking page or engine, and repeat it on the rooms pages. If one already exists but is added by a script, ask the web supplier to render it in the page itself.",
            "medium", "low", page={"url": link["url"], "label": "the homepage"}, technical="Booking route: no booking link or known booking engine among the homepage links as read.",
            confidence=INFER, team="web", success="The next audit identifies a booking link on the homepage.", source="booking", tag="BK1", summary="No booking link found on the homepage"))
    dest = by.get("destination")
    if dest and dest["state"] == "fail":
        out.append(_rec(
            "BK2", "content", "The booking link leads to a page that does not work",
            dest["detail"], "Every traveller who clicks 'Book now' reaches an error. This is a lost booking, whatever else the hotel does for visibility.",
            [{"url": dest["url"], "snippet": dest["detail"]}],
            "Open the booking link from the homepage, find out why it fails (a changed engine address or an expired link), and correct it today. Then test it from a phone.",
            "high", "low", page={"url": dest["url"], "label": "the booking link"}, technical="The booking destination returned 404/410 or a server error to a polite request.",
            confidence=BEST, team="web", success="The booking destination answers.", source="booking", tag="BK2", summary="Booking link is broken"))
    lk = by.get("links")
    if lk and lk["state"] == "fail" and bk.get("broken_links"):
        bl = bk["broken_links"]
        out.append(_rec(
            "BK3", "content", f"{len(bl)} link(s) on the site lead to pages that do not exist",
            lk["detail"], "A guest or a crawler that follows a broken link meets an error page, and it tells a reading system the site is not maintained.",
            [{"url": b["url"], "snippet": f"HTTP {b['status']}"} for b in bl[:4]],
            "Fix or remove each link (or add a redirect to the page that replaced it): " + ", ".join(b["url"] for b in bl[:5]) + ".",
            "medium" if len(bl) >= 3 else "low", "low", technical="Links returned 404/410 or a server error to a polite request.", confidence=BEST, team="web",
            success="The next audit finds no broken links.", source="booking", tag="BK3", summary="Broken links"))
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
        if rid in ("S-editorial_outreach", "S-otas_missing", "S-social_none_found", "S-editorial_negative") or rid.startswith("S-editorial_outreach"):
            recs[-1]["kind_hint"] = "opportunity"                 # no verified defect behind it: a sample of searches found little, which is a prompt to look, not a finding
            recs[-1]["confidence"] = INFER
        if rid.startswith("S-entity_unverified"):
            # an uncertain match is a prompt to check by hand, not a fault: it is never a verified finding, and its evidence is what the match lacked, not the action itself
            recs[-1]["kind_hint"] = "opportunity"
            recs[-1]["confidence"] = INFER
            recs[-1]["priority"], recs[-1]["impact"] = "low", "low"
            recs[-1]["evidence"] = [{"url": "", "snippet": "Open map data lists an entry with the hotel's name, but it could not be matched on anything else (coordinates within 0.5 km, postcode, official website or telephone), so it may be this hotel or another with the same name."}]
            recs[-1]["finding"] = "An entry with this name was found in open map data but could not be confirmed as this hotel. Check it by hand; if it is the hotel, add its website and telephone to the entry so it can be verified."
    return recs


# ---------------------------------------------------------------------- assemble

def build(*, questions, location, consistency, hidden, structured, machine, intel, jsonld_example, site, coverage=None, ai=None, reviews=None, text_only=False, ai_insights=None, listing_checks=None, reddit=None, traveller=None, booking=None, external=None, competitors=None, suppressed=None, ai_gap=None):
    coverage = coverage or {}
    # the requirement checks say more, and more exactly, than the extended guest questions they cover
    superseded = {q for seg in (traveller or {}).get("assessed", []) for q in TRAVELLER_SUPERSEDES.get(seg, ())}
    if superseded:
        questions = [q for q in questions if q.get("id") not in superseded or q.get("source") != "extended"]
    covered = _tr_topics(traveller)
    if covered:
        # the requirement check is the authority on these topics: raising the general guest question as well would say the same thing twice, in different words
        questions = [q for q in questions if CANON.get(q.get("id"), q.get("id")) not in covered]
    recs = []
    recs += _from_questions(questions, site, coverage, suppressed)
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
    gap_recs = _from_ai_gap(ai_gap)
    if gap_recs:
        # the specific finding (not named for THIS question, and who was) replaces the general 'not named in a sample' notes, and a named article replaces the generic 'consider a travel publication'
        recs = [r for r in recs if r["id"] not in ("AI1", "AI4") and not (r["id"].startswith("X-S-editorial_outreach") and any(g["id"].startswith("AG-OUT") for g in gap_recs))]
        recs += gap_recs
    recs += _from_listing_checks(listing_checks)
    recs += _from_reddit(reddit)
    recs += _from_traveller(traveller, coverage, site)
    recs += _from_booking(booking)
    recs += _from_external(external)
    recs += _from_competitors(competitors, site)
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


GENERIC_ACTION = re.compile(r"improve (?:your )?(?:online )?visibility|optimi[sz]e (?:your )?(?:content|website|site) for (?:ai|search)|strengthen (?:your )?(?:digital|online) presence|boost (?:your )?(?:seo|visibility)|"
                            r"increase (?:your )?(?:online )?presence|improve (?:your )?(?:ai|search) (?:presence|ranking)", re.I)


def _title_tokens(t):
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 3}


_NAVISH = None


def validate(recs, coverage=None, site=None):
    """
    The last gate before a recommendation reaches the hotel. A recommendation must have, in order:
      1. evidence that supports it (a page, a source or a quoted passage), with menus, navigation strips and unrelated extracts removed;
      2. a specific action, in wording that is not a slogan ('improve your online visibility');
      3. a page to act on that is of a type the information belongs on (when it names a page);
      4. an honest confidence label: a finding that something is NOT stated is 'Verified' only when the audit read a page it belongs on, fully, and coverage was not limited; otherwise it is an inference;
      5. no overlap with an earlier recommendation: one underlying issue is one recommendation.
    `recs` is expected best-first. -> (kept, dropped); each dropped row says why, so nothing disappears silently.
    """
    from textutil import looks_like_nav
    coverage = coverage or {}
    limited = bool(coverage.get("limited") or coverage.get("text_only"))
    kept, dropped, covered = [], [], {}
    for r in recs:
        # 1. evidence: menu strips and bare navigation are never evidence
        r["evidence"] = [e for e in r.get("evidence") or [] if ((e.get("snippet") or "").strip() or (e.get("url") or "").strip()) and not looks_like_nav((e.get("snippet") or "")[:160])]
        ev = r["evidence"]
        why = None
        if not ev:
            why = "no supporting evidence"
        elif len((r.get("action") or "").strip()) < 25:
            why = "no specific action"
        elif GENERIC_ACTION.search(r.get("action", "")) or GENERIC_ACTION.search(r.get("title", "")):
            why = "generic wording"
        else:
            # 3. the page to act on must be of a type this information belongs on
            pg = r.get("page") or {}
            if site is not None and pg.get("url") and r.get("topics"):
                tgt = site.by_key.get(__import__("insight_content")._key(pg["url"]))
                topics = [t for t in (pagetarget_topic(t) for t in r["topics"]) if t]
                if tgt is not None and topics and not any(pagetarget.allowed_for(site, tgt, t) for t in topics):
                    why = f"it points to a page ({_path(pg['url'])}) that this information does not belong on"
            tt = _title_tokens(r.get("title"))
            if not why:
                for k in kept:
                    kt = _title_tokens(k.get("title"))
                    if tt and kt and len(tt & kt) / len(tt | kt) >= 0.8 and k.get("source") == r.get("source"):
                        why = f"repeats {k['id']}"
                        break
            # 5. one underlying issue, one recommendation
            if not why and r.get("topics"):
                owner = {t: covered[t] for t in r["topics"] if t in covered}
                if len(owner) == len(r["topics"]):
                    why = f"the same issue as {', '.join(sorted(set(owner.values())))}"
        if why:
            dropped.append({"id": r["id"], "title": r.get("title", ""), "reason": why})
            continue
        # 4. honest confidence: a statement that something is missing is only 'Verified' with enough coverage of the right pages
        if r.get("absence_based") and limited and r.get("confidence") == BEST:
            r["confidence"] = INFER
        for t in r.get("topics") or []:
            covered.setdefault(t, r["id"])
        kept.append(r)
    return kept, dropped


def pagetarget_topic(canon):
    """The page-targeting topic for a canonical issue name."""
    return {"parking": "parking", "family_rooms": "family_occupancy", "accessibility": "accessibility", "breakfast": "breakfast", "checkin_out": "checkin_out", "pets": "pets",
            "transport": "transport", "wifi": "wifi", "ev": "ev", "cancellation": "cancellation", "room_config": "room_configuration", "area_guide": "area_guide", "rate_inclusions": "rate_inclusions",
            "meetings": "meeting_detail", "weddings": "wedding_detail", "spa": "spa_detail", "restaurant_detail": "restaurant_detail", "airport_transfer": "airport_transfer",
            "business_amenities": "wifi", "airport_early_late": "hotel_info", "airport_stopover": "hotel_info", "attractions": "location", "venues": "location", "journeys": "location",
            "room_count": "room_count"}.get(canon)


def top_actions(recs, n=7):
    """The few required fixes most worth doing, chosen from the whole audit by the global ranking."""
    return ranking.top_actions(recs, n=n)


def quick_wins(recs, exclude_ids=(), n=8):
    return ranking.quick_wins(recs, exclude_ids, n=n)
