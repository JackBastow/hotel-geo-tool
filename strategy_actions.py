"""
Strategy actions: the bigger, longer-term moves that position a hotel in the market it wants, by getting it onto the OUTSIDE sources AI assistants read and by becoming a source itself. They sit in their
own section of the hotel's Actions, apart from the fixes to its own website and listings.

Where they come from, most specific first
  1. Seen: sites the assistant actually relied on in the latest check (source_actions) where comparable rivals appear: an editorial list, a tourism board, a directory, an attraction.
  2. Researched: the specific sources for the hotel's market, found by web search with their real addresses and contact pages (strategy_research): the tourism board's partner page, the convention
     bureau, wedding directories, restaurant guides, publications, creators, tour operators, awards, partners.
  3. Questions AI is asked where the hotel is not named: a guide on its own site that answers them (become a source, not just a listing).
  4. Long-term moves for its market from its profile, where nothing more specific was found: Wikidata, awards, press, video, partnerships, tour operators.

Every action is a short set of steps a marketing manager can follow: a button to the right page, a ready-to-send email (with the hotel's own facts) to copy, and how to follow up. Booking and review sites
are one listings action (we never read them, so we never say the hotel is missing from one). Never: another hotel group's own site or a rival hotel's, paying for undisclosed coverage, or fake reviews.
Nothing promises that being on a source makes an assistant recommend the hotel.
"""

import re
import urllib.parse

import evidence

# hotel groups' and brands' own websites: not a place another hotel can be listed
CHAIN_DOMAINS = ("marriott.com", "hilton.com", "ihg.com", "hyatt.com", "accor.com", "all.accor.com", "wyndhamhotels.com", "choicehotels.com", "bestwestern.com", "radissonhotels.com", "melia.com",
                 "nh-hotels.com", "scandichotels.com", "scandichotels.se", "strawberry.se", "nordicchoicehotels.com", "premierinn.com", "travelodge.co.uk", "kempinski.com", "fourseasons.com",
                 "ritzcarlton.com", "mandarinoriental.com", "shangri-la.com", "peninsula.com", "rosewoodhotels.com", "belmond.com", "minorhotels.com", "barcelo.com", "iberostar.com", "riu.com",
                 "omnihotels.com", "loewshotels.com", "sonesta.com", "ihg.co.uk", "holidayinn.com", "crowneplaza.com", "hamptoninn.com", "doubletree.com", "sheraton.com", "westin.com", "novotel.com",
                 "ibis.com", "mercure.com", "sofitel.com", "pullmanhotels.com", "fairmont.com", "raffles.com", "swissotel.com", "movenpick.com", "leonardo-hotels.com", "motel-one.com", "citizenm.com")
# booking, review and price-comparison sites: we never read them (their terms forbid it), so we can never say the hotel is NOT on one
OTA = re.compile(r"booking\.|expedia|hotels\.com|trip\.com|agoda|trivago|kayak|skyscanner|momondo|zenhotels|cozycozy|hotelscombined|priceline|orbitz|travelocity|lastminute|ebookers|hrs\.|hotel\.de|"
                 r"airbnb|vrbo|holidaycheck|tripadvisor|google\.|yelp|ostrovok|goibibo|makemytrip|hostelworld|hotwire|travelsupermarket|wotif|otel\.com|tablethotels|mrandmrssmith", re.I)


def is_listing_site(domain, type_=""):
    return type_ in ("review", "comparison") or bool(OTA.search(domain or ""))


def _dom(url_or_domain):
    d = re.sub(r"^https?://", "", str(url_or_domain or "")).split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def is_chain_site(domain):
    d = _dom(domain)
    return any(d == c or d.endswith("." + c) for c in CHAIN_DOMAINS)


def _rival_domains(rep):
    return {_dom(r["url"]) for r in ((rep or {}).get("ai_gap") or {}).get("rivals") or [] if r.get("url")}


def _search(q):
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": q})


# ------------------------------------------------------------------ the email

ASK = {
    "tourism_board": "How can we be listed as accommodation (or join as a partner) on your site? I am happy to send whatever you need.",
    "convention_bureau": "Could we be added to your venue listings? Happy to send capacities, layouts and photos.",
    "venue_directory": "Could we be added as a venue? Happy to send capacities, layouts and photos.",
    "wedding_directory": "We would like to be listed as a wedding venue. What do you need from us?",
    "restaurant_guide": "How can we put the restaurant forward for your guide? We would be glad to welcome your reviewers.",
    "award": "We would like to enter. Could you tell me how, and the dates for this year?",
    "publication": "Would a piece about it interest your readers? We would be glad to host you for a night so you can see it for yourself (a hosted stay, disclosed as such).",
    "creator": "Would you like to come and stay to make an honest post about it? It would be a hosted stay, clearly marked as such.",
    "tour_operator": "Would you consider including us in your trips to the area? We can offer trade rates.",
    "attraction": "Could we point our guests to you and you point yours to us: a 'where to stay' mention on your site and a 'what to do' one on ours?",
    "community": "We would like to join and take part. How do we go about it?",
    "editorial": "Would you consider us for that page, or a future update of it? We would be glad to host you for a night so you can see it for yourself (disclosed as a hosted stay).",
}


def email(kind, hotel, profile, to_name="", page_title=""):
    """A short, honest outreach email built from the hotel's own profile, with [brackets] to fill in."""
    p = profile or {}
    where = ", ".join(x for x in (p.get("town"), p.get("region")) if x) or "[town]"
    facts = (p.get("reasons") or [])[:3]
    lines = [f"Subject: {hotel or '[Hotel]'}" + (f" for {page_title}" if page_title else ""), "", f"Hi {to_name or '[name]'},", "",
             f"I am [your name], [your role] at {hotel or '[Hotel]'} in {where}."
             + (f" I saw {page_title} and think we would be a good fit." if page_title else "")]
    if facts:
        lines += ["", "A few facts about us:"] + [f"- {f}" for f in facts]
    lines += ["", ASK.get(kind, ASK["publication"]), "", "Photos and a fact sheet: [link to your press page or photos]", "", "Thank you,", "[your name]", "[phone]"]
    return "\n".join(lines)


# ------------------------------------------------------------------ building the actions

def _act(id_, title, finding, steps, *, kind_label, priority="medium", effort="about an hour", confidence="Suggested from your profile", tag="", evidence_=None):
    return {"id": id_, "title": title, "finding": finding, "why": finding, "action": (steps[0]["title"] if steps else ""), "steps": steps, "source": "strategy", "category": "Strategy", "kind": "strategy",
            "team": "marketing", "tag": tag or id_, "track": "visibility", "priority": priority, "effort": effort, "confidence_label": confidence, "kind_label": kind_label, "evidence": evidence_ or []}


def _outreach_steps(kind, name, url, contact_url, mail, hotel, profile, page_title=""):
    d = _dom(contact_url or url)
    s1 = {"title": f"Open {name}" + (" (contact page)" if contact_url else ""), "link": {"url": contact_url or url, "label": f"Open {d}"},
          "detail": (f"Their published email: {mail}" if mail else ("Look for the listings, partners or contact page." if not contact_url else ""))}
    s2 = {"title": "Send this email" + (f" to {mail}" if mail else ""), "detail": "Fill in the [brackets] and check every fact before you send it.",
          "copy": {"label": "Copy email", "text": email(kind, hotel, profile, page_title=page_title)}}
    s3 = {"title": "Follow up after 10 days if you have not heard back", "detail": "One short, friendly reminder; then leave it."}
    s4 = {"title": "When you are featured, check the facts and the link to your website, then mark this done", "detail": "The next checks show whether the assistant starts citing that page."}
    return [s1, s2, s3, s4]


def _from_seen(rep, profile, hotel, own, rivals):
    import source_actions
    out, listings = [], []
    try:
        seen = source_actions.build(rep, limit=20) if rep else []
    except Exception:  # noqa: BLE001
        seen = []
    gap = (rep or {}).get("ai_gap") or {}
    read_absent = {}
    for a in gap.get("articles") or []:
        if a.get("read") == "ok" and a.get("hotel_in") is False:
            read_absent.setdefault(_dom(a.get("domain")), a)
    for s in seen:
        d = _dom(s["domain"])
        if not d or d == own or is_chain_site(d) or d in rivals:
            continue
        if is_listing_site(d, s["type"]):
            listings.append(s)
            continue
        if s["hotel_appears"]:
            continue
        who = ", ".join(s["rivals"][:2])
        art = read_absent.get(d)
        url = (art or {}).get("url") or (s.get("evidence") or [f"https://{d}"])[0]
        contact = s["route"][len("a contact page was found: "):] if s["route"].startswith("a contact page was found: ") else ""
        if art:
            title, finding = f"Get featured on {d}", f"The AI assistant read this page for questions about your market: it features {who or 'other hotels'} and does not mention you."
            steps = _outreach_steps("editorial", d, url, contact, "", hotel, profile, page_title=(art.get("title") or "")[:80])
        else:
            title, finding = f"Check whether you are featured on {d}", f"The AI assistant used {d} ({s['type_label'].lower()}) in your latest check" + (f"; it features {who}." if who else ".")
            steps = [{"title": f"Search {d} for your hotel's name", "link": {"url": _search(f'site:{d} "{hotel}"'), "label": f"Search {d}"}, "detail": "If you are already there, check the facts are right; if not, carry on."}] \
                + _outreach_steps({"tourism": "tourism_board", "conference": "venue_directory", "attraction": "attraction"}.get(s["type"], "editorial"), d, url, contact, "", hotel, profile)
        out.append(_act(f"strat-{d}", title, finding, steps, kind_label=s["type_label"], priority="high" if art and who else "medium", confidence="Seen in the latest check", tag=d,
                        evidence_=[{"url": u, "snippet": "Cited by the assistant"} for u in (s.get("evidence") or [])[:2]]))
    return out, listings


def _listings_action(listings, profile, hotel):
    names = [_dom(s["domain"]) for s in sorted(listings, key=lambda s: -s["cited"])][:8]
    facts = (profile or {}).get("reasons") or []
    steps = [{"title": f"Open your listing on {n}", "link": {"url": _search(f'{hotel} {n}'), "label": f"Find it on {n}"}} for n in names[:4]]
    steps += [{"title": "Make each description say why guests choose you", "detail": ("For example: " + "; ".join(facts[:3]) + ".") if facts else "Two or three specific reasons, not a generic welcome."},
              {"title": "Check the facts and photos match your website", "detail": "Name, address, facilities, check-in times, the restaurant and meeting rooms."},
              {"title": "Reply to recent reviews as the hotel", "detail": "Good and bad, plainly. Never offer anything in return for a review."}]
    return _act("strat-listings", "Make your booking and review site listings work for AI",
                f"The AI assistant read these booking and review sites in your latest check: {', '.join(names)}. It uses what your listings there say. (We do not read those sites, so this is not a claim about whether you are listed.)",
                steps, kind_label="Booking and review sites", confidence="Seen in the latest check", tag="listings", effort="an hour per site")


def _from_research(research, profile, hotel, own, rivals, limit=8):
    out = []
    for s in ((research or {}).get("sources") or [])[:limit]:
        d = s["domain"]
        if d == own or d in rivals or is_chain_site(d) or is_listing_site(d):
            continue
        verb = {"tourism_board": "Get listed with", "convention_bureau": "Get listed with", "venue_directory": "Get listed on", "wedding_directory": "Get listed on", "restaurant_guide": "Put the restaurant forward to",
                "award": "Enter", "publication": "Pitch a story to", "creator": "Invite", "tour_operator": "Get into the trips of", "attraction": "Partner with", "community": "Join"}.get(s["kind"], "Approach")
        out.append(_act(f"strat-r-{d}", f"{verb} {s['name']}", s.get("why") or f"A {s['kind_label'].lower()} for your market.",
                        _outreach_steps(s["kind"], s["name"], s["url"], s.get("contact_url"), s.get("email"), hotel, profile),
                        kind_label=s["kind_label"], confidence="Found for your market", tag=d, priority="high" if s["kind"] in ("tourism_board", "convention_bureau") else "medium",
                        evidence_=[{"url": s["url"], "snippet": s["kind_label"]}]))
    return out


def _content_hub(rep, profile, hotel):
    """Questions the assistant was asked where the hotel was not named: answer them on the hotel's own site, so it becomes a source."""
    ms = [m for m in ((rep or {}).get("ai_gap") or {}).get("markets") or [] if m.get("kind") != "direct" and m.get("status") != "named" and m.get("rivals")]
    if not ms:
        return None
    qs = [m["question"] for m in ms[:4]]
    facts = (profile or {}).get("reasons") or []
    steps = [{"title": "Pick the questions below where you were not named", "detail": " | ".join(qs)},
             {"title": "Write one page for each theme that answers them plainly", "detail": "What it is, where, how long, what it costs, who it suits, how to book. Use your real facts" + (f" ({'; '.join(facts[:2])})" if facts else "") + ", with photos."},
             {"title": "Link to the pages from your homepage and menu, and add them to your sitemap", "detail": "A page nobody can find from the homepage is rarely read."},
             {"title": "Ask your web team to add each page to the sitemap and keep the facts up to date", "detail": "The next checks show whether the assistant starts naming you for these questions."}]
    return _act("strat-content-hub", "Answer the questions travellers ask AI, on your own website",
                f"In your latest check the assistant was asked {len(ms)} question(s) where it named other hotels and not you. A clear page on your site that answers them gives it something to cite.",
                steps, kind_label="Your own content", confidence="Seen in the latest check", effort="half a day per page", tag="content-hub", priority="high")


def _long_term(profile, hotel, have_kinds):
    """Long-term moves for the market in the profile, where research found nothing more specific of that kind."""
    p = profile or {}
    town, region, area = p.get("town") or "", p.get("region") or p.get("town") or "", p.get("area") or p.get("region") or p.get("town") or ""
    out = []
    if "tourism_board" not in have_kinds and region:
        out.append(_act("strat-g-tourism", f"Get listed by the official tourism board for {region}", "Tourism boards are among the sources AI assistants trust for where to stay in a region; most list accommodation for free or as partners.",
                        [{"title": f"Find the official tourism board for {region}", "link": {"url": _search(f"official tourism board {region} accommodation partner"), "label": "Search for it"}},
                         {"title": "Send this email to their partner or listings contact", "copy": {"label": "Copy email", "text": email("tourism_board", hotel, p)}},
                         {"title": "Once listed, check the description and the link to your website"}], kind_label="Tourism board"))
    out.append(_act("strat-g-wikidata", "Make sure Wikidata and Wikipedia describe you correctly", "AI assistants lean on Wikidata and Wikipedia for basic facts about places: the right name, location, website and what the place is.",
                    [{"title": "Search Wikidata for your hotel", "link": {"url": "https://www.wikidata.org/w/index.php?" + urllib.parse.urlencode({"search": hotel}), "label": "Search Wikidata"}},
                     {"title": "If there is an item, check it has your official website, coordinates and 'instance of: hotel'", "detail": "Anyone can correct Wikidata; cite your website for each fact."},
                     {"title": "Do not write your own Wikipedia article", "detail": "That is a conflict of interest. If the place is notable and has no article, suggest one on the relevant talk page, with independent sources."}],
                    kind_label="Reference sites", effort="about 30 minutes"))
    if "award" not in have_kinds:
        out.append(_act("strat-g-awards", "Enter the awards and certifications guides quote", "Awards and certifications are facts assistants repeat ('award-winning', 'eco-certified'), and their lists are pages they read.",
                        [{"title": "List the awards that fit you: national hotel awards, restaurant guides, sustainability (for example Green Key)", "link": {"url": _search(f"hotel awards {region or area} enter"), "label": "Search for awards"}},
                         {"title": "Enter one or two this year", "copy": {"label": "Copy enquiry", "text": email("award", hotel, p)}},
                         {"title": "State each award or certification on your website in plain words, with the year"}], kind_label="Awards", effort="a few hours"))
    if not {"publication", "creator"} & have_kinds:
        out.append(_act("strat-g-press", "Give journalists and creators one good story a season", f"Travel articles and creators about trips in {area} are what assistants quote when travellers ask for experiences.",
                        [{"title": "Pick one angle from why guests choose you", "detail": "; ".join((p.get("reasons") or ["a seasonal event", "something only you offer"])[:3])},
                         {"title": "Make sure your press page has facts, photos and a contact", "detail": "One page journalists can use without asking."},
                         {"title": f"Find five writers or creators who cover {area}", "link": {"url": _search(f"{area} travel blog {(p.get('reasons') or ['weekend'])[0]}"), "label": "Search for them"}},
                         {"title": "Send each a short pitch", "copy": {"label": "Copy pitch", "text": email("publication", hotel, p)}}], kind_label="Press and creators", effort="a few hours a season"))
    if p.get("attractions") and "attraction" not in have_kinds:
        a = p["attractions"][0]
        out.append(_act("strat-g-partner", f"Partner with {a}", f"Guests come for {a}. A 'where to stay' mention on its site, and a 'what to do' one on yours, connect the two in what assistants read.",
                        [{"title": f"Find who runs {a} and their partnerships contact", "link": {"url": _search(f"{a} partners contact"), "label": "Search"}},
                         {"title": "Propose a simple exchange of mentions", "copy": {"label": "Copy email", "text": email("attraction", hotel, p)}},
                         {"title": "Add a short guide to visiting it on your own site"}], kind_label="Partnerships"))
    if {"destination", "countryside", "coastal", "resort"} & set(p.get("kinds") or []) and "tour_operator" not in have_kinds:
        out.append(_act("strat-g-operators", f"Get into the trips tour operators sell to {area}", "Tour operators' trip pages describe where their guests stay; assistants read them when asked for trips like yours.",
                        [{"title": f"Find operators selling trips to {area}", "link": {"url": _search(f"{area} {(p.get('reasons') or ['nature'])[0]} tour operator"), "label": "Search for them"}},
                         {"title": "Offer them trade rates and a fact sheet", "copy": {"label": "Copy email", "text": email("tour_operator", hotel, p)}}], kind_label="Tour operators"))
    out.append(_act("strat-g-video", "Show the stay on video", "Assistants increasingly read video titles, descriptions and transcripts (YouTube in particular).",
                    [{"title": "Film three short videos of what guests come for", "detail": "; ".join((p.get("reasons") or ["the rooms", "the setting", "what there is to do"])[:3])},
                     {"title": "Publish them on YouTube with plain titles and descriptions that name the place", "detail": f"For example: '{(p.get('reasons') or ['A weekend'])[0]} at {hotel}, {town}'."},
                     {"title": "Embed them on the matching pages of your website"}], kind_label="Video", effort="a day"))
    return out


def build(rep, profile=None, hotel_name="", research=None):
    """-> recommendation dicts (source 'strategy', with steps) for the hotel's Actions, most specific first."""
    p = profile or {}
    own = _dom(((rep or {}).get("meta") or {}).get("base") or "")
    rivals = _rival_domains(rep)
    seen, listings = _from_seen(rep, p, hotel_name, own, rivals)
    found = _from_research(research, p, hotel_name, own, rivals)
    out = seen[:4]
    if listings:
        out.append(_listings_action(listings, p, hotel_name))
    out += found
    hub = _content_hub(rep, p, hotel_name)
    if hub:
        out.append(hub)
    if p:
        have = {s["kind"] for s in (research or {}).get("sources") or []}
        out += _long_term(p, hotel_name, have)[: max(2, 10 - len(out))]
    return out
