"""
Strategy actions: the bigger moves that position a hotel in the market it wants, by getting it onto the OUTSIDE sources AI assistants read. They sit in their own section of the hotel's Actions, apart
from the fixes to its own website and listings.

Where they come from
  1. Seen: sites the assistant actually relied on in the hotel's latest check (source_actions), where comparable rivals appear and the hotel does not: an editorial list, a tourism board, a venue directory,
     an attraction, a review or booking site. Each is a site the hotel could realistically be on.
  2. Suggested: the kinds of source that matter for the market the hotel described in its profile (a nature destination: the regional tourism board and nature-travel writers; conferences: venue
     directories and the convention bureau; weddings: wedding directories; food: restaurant guides; any hotel: travel creators who cover the area). These are labelled as suggestions, not as sites the
     assistant was seen to use.

Each action has a few steps: who to contact (the contact page when one was found), what to send (true facts from the hotel's profile), and how to follow up. Never: another chain's own website or a
rival hotel's site (a Hilton cannot get onto marriott.com), paying for undisclosed coverage, or fake reviews. Nothing promises that being on a source makes an assistant recommend the hotel.
"""

import re

import evidence

# hotel groups' and brands' own websites: not a place another hotel can be listed
CHAIN_DOMAINS = ("marriott.com", "hilton.com", "ihg.com", "hyatt.com", "accor.com", "all.accor.com", "wyndhamhotels.com", "choicehotels.com", "bestwestern.com", "radissonhotels.com", "melia.com",
                 "nh-hotels.com", "scandichotels.com", "scandichotels.se", "strawberry.se", "nordicchoicehotels.com", "premierinn.com", "travelodge.co.uk", "kempinski.com", "fourseasons.com",
                 "ritzcarlton.com", "mandarinoriental.com", "shangri-la.com", "peninsula.com", "rosewoodhotels.com", "belmond.com", "minorhotels.com", "barcelo.com", "iberostar.com", "riu.com",
                 "omnihotels.com", "loewshotels.com", "sonesta.com", "ihg.co.uk", "holidayinn.com", "crowneplaza.com", "hamptoninn.com", "doubletree.com", "sheraton.com", "westin.com", "novotel.com",
                 "ibis.com", "mercure.com", "sofitel.com", "pullmanhotels.com", "fairmont.com", "raffles.com", "swissotel.com", "movenpick.com", "leonardo-hotels.com", "motel-one.com", "citizenm.com")


# booking, review and price-comparison sites: we never read them (their terms forbid it), so we can never say the hotel is NOT on one. A page of one that the assistant cited (a list of hotels in a
# town) not naming the hotel says nothing about whether the hotel is listed there.
OTA = re.compile(r"booking\.|expedia|hotels\.com|trip\.com|agoda|trivago|kayak|skyscanner|momondo|zenhotels|cozycozy|hotelscombined|priceline|orbitz|travelocity|lastminute|ebookers|hrs\.|hotel\.de|"
                 r"airbnb|vrbo|holidaycheck|tripadvisor|google\.|yelp|ostrovok|goibibo|makemytrip|hostelworld|hotwire|travelsupermarket|wotif|lastminute|otel\.com|tablethotels|mrandmrssmith", re.I)


def is_listing_site(domain, type_=""):
    return type_ in ("review", "comparison") or bool(OTA.search(domain or ""))


def _dom(url_or_domain):
    d = re.sub(r"^https?://", "", str(url_or_domain or "")).split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def is_chain_site(domain):
    d = _dom(domain)
    return any(d == c or d.endswith("." + c) for c in CHAIN_DOMAINS)


def _rival_domains(rep):
    out = set()
    for r in ((rep or {}).get("ai_gap") or {}).get("rivals") or []:
        if r.get("url"):
            out.add(_dom(r["url"]))
    return out


def _facts(profile):
    p = profile or {}
    out = list(p.get("reasons") or [])[:3]
    return out


def _steps_for_site(s, facts, hotel):
    contact = s["route"][len("a contact page was found: "):] if s["route"].startswith("a contact page was found: ") else ""
    pitch = ("; ".join(facts[:3])) if facts else "two or three true, specific facts about the hotel that fit what the page covers"
    steps = [(f"Contact them through {contact}." if contact else f"Find who to contact on {s['domain']}: the editor, the listings or partnerships page, or the contact page."),
             f"Send a short note: who you are, why {hotel or 'the hotel'} fits what they cover, and the facts that back it up ({pitch}). Offer photos and an invitation to visit; never pay for undisclosed coverage.",
             "If they take listings or submissions, submit the hotel and check the name, address and facilities they show. Note the date here; the next checks show whether the assistant starts citing you there."]
    if s["type"] in ("review", "comparison"):
        steps = [f"Open your listing on {s['domain']} (or create one if you are not there).", "Check the name, address, photos, facilities and description against your website; add what is missing, especially "
                 + (facts[0] if facts else "what makes the hotel different") + ".", "Reply to recent reviews, good and bad, plainly and as the hotel; never offer anything for a review."]
    return steps


# kinds of source that matter for a market, from the hotel's profile: (when, title, why, steps)
SUGGESTIONS = [
    (lambda p: bool(p.get("region") or p.get("area")), "Get listed by the official tourism board for {region}",
     "Tourism boards are among the sources AI assistants trust for where to stay in a region, and most list accommodation for free or as partners.",
     ["Find the tourism board for {region} (search for its official 'visit' site) and its accommodation or partner page.", "Ask to be listed, with your address, what kind of stay you offer and why guests come ({facts}).",
      "Once listed, check the description is accurate and links to your website."]),
    (lambda p: bool({"destination", "countryside", "coastal"} & set(p.get("kinds") or [])), "Get featured by writers who cover nature and short breaks in {area}",
     "Travellers ask AI for experiences ('a wildlife weekend in {area}'), and it answers from travel articles and blogs about those trips.",
     ["Search for recent articles and blogs about trips like yours in {area} (for example 'best nature weekends {area}') and note the writers and publications that come up.",
      "Write to two or three of them with what makes the stay different ({facts}), and offer a visit.", "Keep a list here of who you contacted and when; the checks show when the assistant starts citing those pages."]),
    (lambda p: "meetings" in (p.get("audiences") or []) or "business" in (p.get("kinds") or []), "Get on the conference venue directories and the convention bureau for {region}",
     "Event planners ask AI for venues, and it reads venue directories and convention bureau listings.",
     ["Find the main meeting-venue directories used in your country and the convention bureau for {region} or {town}.", "List the hotel with room capacities, layouts and equipment stated plainly.",
      "Check the listings every few months: out-of-date capacities are worse than none."]),
    (lambda p: "weddings" in (p.get("audiences") or []), "Get on the wedding venue directories couples use",
     "Couples ask AI for wedding venues, and it reads wedding directories and planning blogs.",
     ["Find the wedding venue directories and planning blogs that cover {region}.", "List the hotel with capacities, ceremony options and rooms for guests.", "Ask a recent couple whether you may share their day as a real-wedding feature (with their permission)."]),
    (lambda p: "food" in (p.get("audiences") or []) or any(re.search(r"restaurant|dining|food|chef|wine|michelin|guide", r, re.I) for r in p.get("reasons") or []),
     "Get the restaurant onto the food and restaurant guides",
     "Food lovers ask AI where to eat and stay, and it reads restaurant guides and food writers.",
     ["List the restaurant on the restaurant guides that cover {region} and make sure any award you hold is stated on your own site in plain words.", "Invite one or two food writers who cover the area.",
      "Check that the guides link to your website and show the right opening hours."]),
    (lambda p: True, "Work with travel creators who cover {area}",
     "AI assistants increasingly read social and video content; creators who cover your area shape what is said about it.",
     ["Find two or three creators (Instagram, TikTok, YouTube) who post about trips in {area} and whose audience matches your guests.", "Offer a stay in return for an honest post that is clearly marked as a hosted stay.",
      "Ask them to name the hotel and link to your website in the description."]),
]


def build(rep, profile=None, hotel_name="", limit_seen=6, limit_suggested=4):
    """-> recommendation dicts (source 'strategy', with 'steps') for the hotel's Actions: the sources seen in the latest check first, then the suggestions for its market."""
    import source_actions
    p = profile or {}
    facts = _facts(p)
    own = _dom(((rep or {}).get("meta") or {}).get("base") or "")
    rivals = _rival_domains(rep)
    out = []
    try:
        seen = source_actions.build(rep, limit=20) if rep else []
    except Exception:  # noqa: BLE001
        seen = []
    read_absent = {_dom(a.get("domain")) for a in ((rep or {}).get("ai_gap") or {}).get("articles") or [] if a.get("read") == "ok" and a.get("hotel_in") is False}
    listings = []
    for s in seen:
        d = _dom(s["domain"])
        if not d or d == own or is_chain_site(d) or d in rivals:
            continue                                  # never another chain's or a rival's own site, nor the hotel's own
        if is_listing_site(d, s["type"]):
            listings.append(s)                        # booking and review sites: one action for all of them, never "get onto" (we cannot see whether the hotel is listed)
            continue
        if s["hotel_appears"]:
            continue
        who = ", ".join(s["rivals"][:2])
        absent = d in read_absent                     # we read a page of this site and the hotel is not on it
        title = f"Get featured on {d}" if absent else f"Check whether you are featured on {d}"
        why = (f"The AI assistant used {d} ({s['type_label'].lower()}) {s['cited']} time(s) in your latest check"
               + (f"; the page it read features {who} and does not mention you." if absent and who else f"; it features {who}." if who else "."))
        out.append({"id": f"strat-{d}", "title": title, "finding": why, "why": "Being on the sites the assistant reads gives it something to say about you when it answers.", "action": s["action"],
                    "steps": ([f"Search {d} for your hotel's name to see whether you are already featured."] if not absent else []) + _steps_for_site(s, facts, hotel_name),
                    "source": "strategy", "category": "Strategy", "kind": "strategy", "team": "marketing", "tag": d, "track": "visibility",
                    "priority": "high" if absent and who else "medium", "effort": "medium", "confidence_label": "Seen in the latest check",
                    "evidence": [{"url": u, "snippet": f"Cited by the assistant ({s['type_label'].lower()})"} for u in (s.get("evidence") or [])[:2]]})
        if len(out) >= limit_seen:
            break
    if listings:
        names = [_dom(s["domain"]) for s in sorted(listings, key=lambda s: -s["cited"])][:8]
        out.insert(0, {"id": "strat-listings", "title": "Make your booking and review site listings work for AI",
                       "finding": f"The AI assistant read these booking and review sites in your latest check: {', '.join(names)}. It uses what your listings there say (description, facilities, rating, recent reviews) when it answers.",
                       "why": "We do not read these sites (their terms do not allow it), so this does not say whether you are listed; it says the assistant relies on them, so your listing on each is part of what it knows about you.",
                       "action": "Check each listing is complete and says why guests choose you.",
                       "steps": [f"Open your listing on each of: {', '.join(names)} (create one where you are missing and it suits you).",
                                 "Check the name, address, photos and facilities; make sure the description states why guests choose you" + (f" ({'; '.join(facts[:3])})" if facts else "") + ".",
                                 "Reply to recent reviews, good and bad, as the hotel; never offer anything in return for a review."],
                       "source": "strategy", "category": "Strategy", "kind": "strategy", "team": "marketing", "tag": "listings", "track": "visibility", "priority": "medium", "effort": "medium",
                       "confidence_label": "Seen in the latest check"})
    if p:
        fill = {"region": p.get("region") or p.get("town") or "your region", "area": p.get("area") or p.get("region") or p.get("town") or "your area", "town": p.get("town") or "your town",
                "facts": "; ".join(facts) if facts else "what makes the stay different"}
        n = 0
        for when, title, why, steps in SUGGESTIONS:
            if n >= limit_suggested:
                break
            try:
                ok = when(p)
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                continue
            t = title.format(**fill)
            out.append({"id": "strat-" + evidence.fold(t)[:40].replace(" ", "-"), "title": t, "finding": why.format(**fill), "why": "A suggestion for the market described in your profile: it was not seen in the assistant's answers, so check it suits you first.",
                        "action": steps[0].format(**fill), "steps": [x.format(**fill) for x in steps], "source": "strategy", "category": "Strategy", "kind": "strategy", "team": "marketing",
                        "tag": "suggested:" + title.split("{")[0].strip().lower()[:30], "track": "visibility", "priority": "medium", "effort": "medium", "confidence_label": "Suggested from your profile"})
            n += 1
    return out
