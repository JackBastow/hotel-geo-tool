"""
Evidence-backed recommendations for the wider report.

Every recommendation names:
  problem / opportunity, supporting evidence ids, why it matters (to
  discovery, traveller suitability, reputation or conversion), the exact
  action, the responsible team, a priority WITH its rationale, and how
  success could be checked.

Each is also labelled by its basis:
  documented guidance - a platform or regulator has published this advice
  hypothesis          - plausible and common practice, but no one has shown
                        it changes what AI assistants recommend
  observation         - the finding itself is the point (a factual gap)

Nothing here promises that an action produces an AI recommendation, and
nothing advises fake or incentivised reviews, keyword-stuffed reviews or
indiscriminate outreach.
"""

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TEAMS = ("operations", "reputation management", "PR", "distribution", "marketing", "web")
OWNER_TO_TEAM = {"web developer or website supplier": "web", "web developer": "web",
                 "reception": "operations", "general manager": "operations",
                 "marketing": "marketing", "revenue": "distribution",
                 "revenue / distribution": "distribution", "pr": "PR"}


def _rec(rid, section, title, problem, evidence_ids, why, action, team, priority, priority_why,
         success, basis, basis_note="", example=None):
    assert team in TEAMS, team
    return {"id": rid, "section": section, "title": title, "problem": problem,
            "evidence_ids": [e for e in evidence_ids if e], "why_it_matters": why, "action": action,
            "team": team, "priority": priority, "priority_why": priority_why,
            "success_check": success, "basis": basis, "basis_note": basis_note, "example": example}


def build(ctx):
    """
    ctx: dict with identity, reviews, media, traveller, local, website, awards,
    targets, angles, rating_signals, fsa, hotel, city, collected (flags).
    """
    recs = []
    media = ctx["media"]
    cov = media["summary"]
    searched = ctx["flags"]["searched"]
    arts = media["articles"]

    # ---------------------------------------------------------------- media
    if searched and cov["independent_stories"] == 0:
        recs.append(_rec(
            "M1", "media", "No independent editorial coverage was found",
            f"{cov['articles']} page(s) naming the hotel were read, but none is independent editorial "
            "coverage (the rest are the hotel's own, directory, sponsored or republished material).",
            [a["id"] for a in arts[:3]],
            "Independent write-ups are one of the few signals about a hotel that it does not control, "
            "so their absence leaves travellers and assistants with mostly the hotel's own account.",
            "Build the evidence first (see the pitch-angle list for what is missing), then approach only "
            "the outlets listed in the media-target table, each with a specific, factual story.",
            "PR", "high",
            "It is the largest gap in the independent evidence, though coverage can't be bought into existence.",
            "Re-run this audit in 3 months and count independent publishers and dated pieces.",
            "hypothesis", "Coverage is expected to help travellers and may be among many signals "
                          "assistants draw on; no one has shown a specific article changes a recommendation."))
    elif searched and cov["independent_stories"] and cov["recent_independent"] == 0:
        recs.append(_rec(
            "M2", "media", "Independent coverage exists but none is recent",
            f"{cov['independent_stories']} independent piece(s) were found; the newest is "
            f"{max((a['date'] for a in arts if a['date']), default='undated')}. Pieces more than three "
            "years old may describe a previous version of the hotel.",
            [a["id"] for a in arts if a["freshness"] == "old"][:3],
            "Out-of-date descriptions can set the wrong expectations and age the hotel's profile.",
            "List what has changed since the older pieces (rooms, spa, restaurant, ownership) and use "
            "the real changes as the basis for fresh, factual outreach.",
            "PR", "medium", "It is a gap in freshness rather than in existence.",
            "A dated independent piece within the last 12 months appears in the next audit.",
            "hypothesis"))
    nonindep = cov["stories"] - cov["independent_stories"]
    if searched and cov["stories"] >= 3 and nonindep / max(1, cov["stories"]) >= 0.6:
        recs.append(_rec(
            "M3", "media", "Most coverage found is not independent",
            f"{nonindep} of {cov['stories']} distinct stories naming the hotel are sponsored, press-release "
            "or syndicated material, aggregator copies or destination-body pieces.",
            [a["id"] for a in arts if a["type"] in ("sponsored", "press_release")][:3],
            "Syndicated or paid material does not count as independent validation.",
            "Treat the independent count, not the raw count, as the measure of coverage.",
            "PR", "low", "Informational - it changes how to read the coverage count, not an urgent fix.",
            "Track independent publishers separately from total mentions.", "observation"))
    tg = [t for t in ctx["targets"]["targets"] if t["supported"] and t["read"]]
    if tg:
        names = ", ".join(t["name"] for t in tg[:3])
        recs.append(_rec(
            "M4", "media", f"{len(tg)} relevant guides and organisations to approach, with evidence",
            f"Real, current pages in your area or segment that do not mention the hotel: {names}.",
            [t["evidence_id"] for t in tg[:4]],
            "These pages already serve travellers with the hotel's profile; being absent from them is a "
            "specific, checkable gap.",
            "Read each page in the target table; where the hotel genuinely fits, send a short factual "
            "note with the hotel's supporting facts. Skip anything the hotel does not match. Do not use "
            "paid or incentivised placement without disclosing it.",
            "PR", "medium", "Concrete and low-cost, but outcomes are not in the hotel's control.",
            "Each approach and any resulting listing is logged with a date; re-audit in 3 months.",
            "hypothesis"))
    if ctx["angles"]:
        recs.append(_rec(
            "M5", "media", "Prepare the evidence behind your pitch angles",
            f"{len(ctx['angles'])} angle(s) rest on facts from the hotel's own pages "
            f"({', '.join(a['angle'].lower() for a in ctx['angles'][:3])}), but none is yet supported "
            "by an independent source or by pitch-ready material.",
            [a["evidence_id"] for a in ctx["angles"][:3]],
            "A pitch needs verifiable specifics; without them it reads as promotion.",
            "For each angle, gather the items listed under 'missing evidence' in the pitch table "
            "before contacting anyone.",
            "PR", "medium", "Preparation that makes every later approach stronger.",
            "Each angle has its missing items ticked off and a named internal owner.", "observation"))
    # ---------------------------------------------------------------- awards
    for a in ctx["awards"]:
        if a["issuer"] == "(issuer not named)" and a["claims"]:
            recs.append(_rec(
                "A1", "media", "Award wording that names no issuer cannot be verified",
                "The website uses award wording (e.g. 'award-winning') without naming who gave it or when.",
                [c["id"] for c in a["claims"]][:2],
                "Unverifiable claims are weaker than named, dated, linked ones, and UK advertising rules "
                "expect claims to be substantiated.",
                "Name the award, issuer and year, and link to the issuer's page - or remove the wording.",
                "marketing", "medium", "Quick to fix and removes a credibility risk.",
                "Each award statement names its issuer, year and a link.",
                "documented guidance", "UK CAP Code rules on substantiating advertising claims."))
        elif a["claims"] and not a["issuer_confirmed"] and a["issuer"] != "(issuer not named)":
            recs.append(_rec(
                f"A2-{a['issuer'][:6]}", "media", f"Confirm and link the {a['issuer']} recognition",
                f"The hotel states {a['issuer']} recognition"
                f"{' (' + ', '.join(a['years']) + ')' if a['years'] else ''}, but no page on the issuer's "
                "site naming the hotel was found.",
                [c["id"] for c in a["claims"]][:2],
                "Issuer-confirmed recognition is verifiable; an unconfirmed claim is only the hotel's word.",
                "Check the issuer's current listing. If it is current, link to it and state the year; if "
                "it has lapsed, update or remove the wording.",
                "marketing", "medium", "Protects accuracy and makes a genuine award checkable.",
                "The issuer's own page names the hotel and the website links to it.",
                "documented guidance", "UK CAP Code rules on substantiating advertising claims."))
    # --------------------------------------------------------------- identity
    ident = ctx["identity"]
    if len(ident["name_variants"]) > 1:
        v = [x["variant"] for x in ident["name_variants"][:3]]
        recs.append(_rec(
            "I1", "identity", "The hotel appears under more than one name",
            "Sources use different forms of the name: " + "; ".join(f"'{x}'" for x in v) + ".",
            [],
            "Inconsistent names make it harder for people and systems to treat listings as one hotel.",
            "Decide the canonical trading name (and spa/restaurant sub-brands), then align the website, "
            "OpenStreetMap, Wikidata and every platform listing to it.",
            "distribution", "medium", "Cheap to fix and affects every listing at once.",
            "The next audit shows one dominant name form.", "documented guidance",
            "Google's Business Profile guidelines ask for the real-world name, used consistently."))
    if ident["consistency"]["rows"]:
        r = ident["consistency"]["rows"]
        recs.append(_rec(
            "I2", "identity", f"{len(r)} fact(s) differ between a listing and the website",
            "; ".join(f"{x['field']}: website '{x['own']}' vs {x['source']} '{x['other']}'" for x in r[:3]),
            [x["evidence_id"] for x in r][:3],
            "Contradictory contact details or ratings send guests to the wrong place and weaken trust.",
            "Correct each listing through its extranet or owner portal, or confirm the website is wrong.",
            "distribution", "high", "Conflicting facts are directly visible to guests.",
            "The same facts appear on the website and every listed source.", "observation"))
    missing_plat = [r["platform"] for r in ident["footprint"]
                    if not r["discovered"] and r["type"] == "booking / review platform"
                    and r["platform"] in ("Booking.com", "Expedia", "TripAdvisor", "Hotels.com")]
    if searched and missing_plat:
        recs.append(_rec(
            "I3", "identity", f"Check your presence on {', '.join(missing_plat)}",
            "Our searches did not surface a listing page for the hotel on: " + ", ".join(missing_plat) +
            ". A search index is not a platform directory, so this may simply be a search gap.",
            [], "Major booking and review platforms are where many travellers look first.",
            "Search each platform yourself for the hotel; if it is not listed or the listing is wrong, "
            "contact the platform's partner support.",
            "distribution", "low", "Unconfirmed - the checking is quick but the finding may be nothing.",
            "Each platform's listing URL is recorded and its details checked.", "hypothesis",
            "Based only on our searches not surfacing a listing - absence from a search index is weak evidence."))
    if ident["destination"] and not ident["destination"]["listing_found"] and ident["destination"]["body"]:
        d = ident["destination"]
        recs.append(_rec(
            "I4", "identity", f"Ask {d['body']['name']} how hotels are listed or featured",
            f"{d['body']['name']} is the official destination site found for the area. No listing or "
            "feature naming the hotel was found on the pages read.",
            [d["body"].get("evidence_id")],
            "Destination bodies are a trusted source for visitors and often a source of local hotel lists.",
            "Use the contact route on the destination site to ask whether and how the hotel can be listed. "
            "Eligibility and any membership cost are not assumed.",
            "marketing", "medium", "Low effort; a destination body is a credible local authority.",
            "The hotel appears on the destination site, or the answer is recorded.", "hypothesis"))
    # ---------------------------------------------------------------- reputation
    for r in ctx["rating_signals"]:
        norm = r["value"] / r["scale"] * 5
        if r["verified_location"] and norm < 3.5:
            recs.append(_rec(
                f"V1-{r['source'][:8]}", "reviews", f"A low aggregate rating is displayed on {r['source']}",
                f"{r['source']} shows {r['value']}/{r['scale']}"
                f"{' from ' + str(r['count']) + ' ratings' if r['count'] else ''}.",
                [r["id"]], "Low displayed ratings are visible to travellers at the point of choice.",
                f"Read the recent reviews on {r['source']} directly; reply to those that warrant it, and fix any "
                "operational causes you find.",
                "reputation management", "high",
                "Directly visible to travellers; the cause needs reading before anyone acts.",
                "The platform's rating and recent review mix are re-checked monthly.", "observation"))
        elif not r["verified_location"] and norm < 3.5:
            recs.append(_rec(
                f"V2-{r['source'][:8]}", "reviews", f"Check whether the low rating on {r['source']} is your hotel",
                f"{r['source']} shows {r['value']}/{r['scale']} for 'a hotel with your name', but the "
                "snippet names no town, so it may be another hotel.",
                [r["id"]], "Mistaken identity can attach someone else's reputation to the hotel.",
                f"Open the {r['source']} page and confirm the address.", "reputation management", "low",
                "Needs a two-minute manual check.", "The listing is confirmed as yours or as another hotel.",
                "observation"))
    recs.append(_rec(
        "V3", "reviews", "Guest reviews were not assessed - monitor them where they live",
        "No lawful free source of guest review text exists for this tool, so review volume, recency, "
        "themes, reply coverage, reply speed and reply quality were not measured.",
        [], "Reviews and how a hotel responds to them are central to reputation; this audit cannot "
            "speak to them.",
        "Review your own reviews directly on each platform: note recurring praise and complaints, reply "
        "factually and courteously, and fix the operational causes. Do not incentivise positive reviews or "
        "script review wording.",
        "reputation management", "medium", "A known blind spot of this tool, not a finding about the hotel.",
        "Your own log of response rate and response time by platform.", "documented guidance",
        "Review platforms publish guidance on owner responses, and prohibit incentivised or fake reviews."))
    fsa = ctx.get("fsa") or []
    for f in fsa:
        try:
            val = int(f["rating"])
        except (TypeError, ValueError):
            continue
        if val < 4:
            recs.append(_rec(
                f"F1-{val}", "reviews", f"Food hygiene rating {val}/5 recorded for {f['name']}",
                f"The Food Standards Agency's public register shows {val}/5 "
                f"('{f.get('descriptor') or 'see register'}') for {f['name']}, inspected "
                f"{f.get('rating_date') or 'date unknown'}.",
                [f.get("evidence_id")], "Hygiene ratings are public, shown on the FSA site and many "
                "others, and weigh on trust in the hotel's food and drink.",
                "Review the inspection report with the kitchen team, fix the findings and ask the local "
                "authority about a re-inspection.", "operations", "high",
                "An official public rating below 4 is visible to guests.",
                "A new FSA rating is published.", "observation"))
    # ---------------------------------------------------------------- traveller fit
    weak = [n for n in ctx["traveller"]["needs"] if n["strength"] == 1 and n["own_pages"] and
            not n["independent_publishers"]]
    if weak:
        recs.append(_rec(
            "T1", "traveller", "Some traveller needs rest on the hotel's own word only",
            "No independent source supports: " + ", ".join(n["segment"].lower() for n in weak[:4]) + ".",
            [], "Claims that nobody else corroborates are weaker evidence of suitability.",
            "Where the claim is true, give independent sources something concrete to verify "
            "(dated facts, photographs, third-party listings) - and be willing to drop claims you "
            "cannot support.", "marketing", "low",
            "Useful context; not a defect.", "More independent sources describe these needs next time.",
            "hypothesis"))
    for o in ctx["traveller"]["opportunities"][:6]:
        if o["missing_evidence"]:
            recs.append(_rec(
                f"T2-{o['segment'][:6]}", "traveller", f"Fill the evidence gap for: '{o['question']}'",
                "The hotel has some supporting facts for this traveller question but is missing: " +
                "; ".join(o["missing_evidence"][:2]) + ".",
                [], "Clear, specific facts on a crawlable page are what people (and systems) can quote.",
                "Publish the missing facts on one clearly titled page: " + "; ".join(o["missing_evidence"][:3]) + ".",
                "web", "medium", "Concrete and fully in the hotel's control.",
                "The page exists, is in the sitemap, and the next audit marks the question answered.",
                "hypothesis", "Specific published facts make a hotel easier to describe correctly; this is "
                             "not a guarantee of being recommended."))
            break  # one traveller-gap recommendation at the top; the rest are listed in the report
    gen = ctx["traveller"]["positioning"]["generic_claims_found"]
    if gen:
        recs.append(_rec(
            "T3", "traveller", "Generic claims do not distinguish the hotel",
            "The website relies on claims every hotel makes: " + ", ".join(gen[:4]) + ".",
            [], "Specific, verifiable features give travellers a reason to choose; generic ones do not.",
            "Replace each generic line with a specific fact that is true only for this hotel "
            "(see the distinctive-features list).", "marketing", "low",
            "Copy improvement; no urgency.", "Generic phrases are replaced by specifics.", "hypothesis"))
    # ---------------------------------------------------------------- website support
    ws = ctx["website"]
    if ws["external_facts_missing_on_site"]:
        x = ws["external_facts_missing_on_site"]
        recs.append(_rec(
            "W1", "website", f"{len(x)} thing(s) others say about the hotel are not on its website",
            "; ".join(r["item"] for r in x[:3]) + ".",
            [(r["evidence"] or {}).get("id") for r in x][:3],
            "A website that doesn't back up what others say leaves a gap people and systems must fill by inference.",
            "Where true and useful, state each plainly on the relevant page.", "web", "medium",
            "In the hotel's control and quick.", "Each item appears on a crawlable page.", "observation"))
    if ctx["flags"]["searched"] and not ws["has_press_or_awards_page"] and (arts or ctx["awards"]):
        recs.append(_rec(
            "W2", "website", "No press, news or awards page was found among the pages read",
            "Coverage and recognition exist but no page of the website collects them.",
            [a["id"] for a in arts[:2]],
            "A single dated, linked page of coverage and awards is easy to verify and easy to cite.",
            "Publish a press page listing each piece with publication, date and link; add the issuer and "
            "year to each award.", "web", "low", "Housekeeping with lasting value.",
            "A press page exists and is linked from the footer and sitemap.", "hypothesis"))
    return recs


def prioritise(recs, n=5):
    """Top n: by priority, then spreading across sections so five fixes aren't all one kind."""
    picked, used = [], {}
    for tier in (0, 1, 2, 3):
        pool = sorted((r for r in recs if PRIORITY_RANK[r["priority"]] == tier), key=lambda r: r["id"])
        while pool and len(picked) < n:
            r = min(pool, key=lambda x: used.get(x["section"], 0))   # least-represented section first
            pool.remove(r)
            picked.append(r)
            used[r["section"]] = used.get(r["section"], 0) + 1
        if len(picked) >= n:
            break
    return picked
