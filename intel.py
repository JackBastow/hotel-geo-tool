"""
Assembles the discovery and reputation intelligence report from the evidence
the collector gathered. No network access happens here - everything is
computed from `corpus` and the audit's own findings - so the PDF and the
dashboard can be produced from a finished audit without re-running requests.
"""

import evidence
import identity
import localctx
import media
import recommend
import reviews
import sources
import sourcetypes
import targets
import travellers

SECTIONS = [
    ("summary", "Executive summary and priority actions"),
    ("identity", "Identity and distribution"),
    ("reviews", "Reviews and reputation"),
    ("media", "Media coverage and independent validation"),
    ("traveller", "Traveller fit and positioning"),
    ("social_local", "Social, video and local context"),
    ("website", "Website support"),
    ("gaps", "Coverage gaps and methodology"),
]

CHECK_NAMES = {
    1: ("identity", "Cross-source identity"), 2: ("identity", "Public listing footprint"),
    3: ("identity", "Listing consistency"), 4: ("identity", "Destination organisation presence"),
    5: ("identity", "Booking and distribution evidence"),
    6: ("reviews", "Available review sample"), 7: ("reviews", "Review freshness"),
    8: ("reviews", "Recurring praise"), 9: ("reviews", "Recurring complaints"),
    10: ("reviews", "Management response coverage"), 11: ("reviews", "Management response speed"),
    12: ("reviews", "Management response language"), 13: ("reviews", "Review languages"),
    14: ("reviews", "Reputation versus positioning"),
    15: ("media", "Named media coverage"), 16: ("media", "Type of coverage"),
    17: ("media", "Coverage freshness"), 18: ("media", "Independent source diversity"),
    19: ("media", "Awards and accreditation"), 20: ("media", "Media narrative"),
    21: ("media", "Comparison-hotel coverage"), 22: ("media", "Specific media targets"),
    23: ("media", "Evidence-backed pitch angles"),
    24: ("traveller", "Traveller-need coverage"), 25: ("traveller", "Specific recommendation opportunities"),
    26: ("traveller", "Distinctive positioning"), 27: ("traveller", "Language and terminology consistency"),
    28: ("social_local", "Public social and video evidence"),
    29: ("social_local", "Location and local partnerships"),
    30: ("website", "Website support for external claims"),
}

CAT_SECTION = {"website": "website", "freshness": "website", "entity": "identity", "otas": "identity",
               "reviews": "reviews", "editorial": "media", "social": "social_local",
               "ai_visibility": "gaps"}
DEFAULT_TEAM = {"identity": "distribution", "media": "PR", "reviews": "reputation management",
                "social_local": "marketing", "website": "web", "gaps": "marketing"}

RESEARCH_DIRECTIONS = [
    {"category": "Regional and local news/lifestyle sites", "why": "They cover openings, refurbishments and "
     "local dining and often run 'best places to stay' features.",
     "how": "Search '{town} + weekend/where to stay/hotel' on the sites your own guests read."},
    {"category": "Specialist press for your strongest segment", "why": "Wedding, spa, family or business-travel "
     "titles run segment roundups that match a specific audience.", "how": "Start with the segment your "
     "own pages cover best (see Traveller fit)."},
    {"category": "The official destination body", "why": "It is a trusted local source of hotel lists.",
     "how": "Find the area's destination website and its business/partner page."},
    {"category": "Awards and accreditation schemes", "why": "Independent, checkable recognition.",
     "how": "Check entry criteria and fees on each scheme's own site before applying."},
]


def _first(x, default=None):
    return x[0] if x else default


def _src(corpus, name):
    return (corpus.get("sources") or {}).get(name) or {"status": "unavailable", "reason": "not run",
                                                         "items": [], "access": ""}


def _entity_evidence(entities, ledger):
    for e in entities or []:
        if e.get("found"):
            ledger.add(url=e.get("url", ""), source=e["source"],
                       source_type="map_or_open_data" if e["source"] == "OpenStreetMap" else "wiki",
                       extract=(e.get("display_name") or e.get("description") or e.get("label") or "")[:300],
                       match="high" if e.get("match_confident") else "medium",
                       match_why=e.get("match_reason") or e.get("note", "")[:120],
                       kind="observed", via=e["source"])


def build_intel(*, hotel, city, base_url, location, site, discovery, guest, own_pages, entities,
                tavily_result, corpus, site_links, own_facts, scorecard_recs=None):
    L = evidence.Ledger(hotel, city)
    town = (city or "").split(",")[0].strip()
    searched = bool(corpus.get("queries")) and any(not q["error"] for q in corpus["queries"])
    _entity_evidence(entities, L)

    # ---- media
    arts, rejected, unread = media.build_articles(corpus, hotel, L)
    clusters = media.cluster(arts)
    cov = media.summarise_coverage(arts, clusters)
    awards = media.find_awards(own_pages, arts, corpus, hotel, L)
    themes = media.theme_scan(arts, own_pages)
    own_theme_counts = {t["theme"]: t["own_pages"] for t in themes["themes"]}
    ratings = media.rating_signals(corpus, hotel, city, L)

    osm = _src(corpus, "osm_context")
    osm_ctx = _first(osm["items"]) if osm["status"] == "ok" else None
    fsa = _src(corpus, "fsa")
    fsa_items = fsa["items"] if fsa["status"] == "ok" else []
    for f in fsa_items:
        f["evidence_id"] = L.add(
              url=f["url"], source="UK Food Standards Agency", source_type="government_register",
              extract=(f"{f['name']} ({f['type']}): food hygiene rating {f['rating']} - "
                       f"{f.get('descriptor') or 'see register'}, inspected {f.get('rating_date')}"),
              published=f.get("rating_date"), match="high" if f.get("same_postcode") else "medium",
              match_why="name and postcode" if f.get("same_postcode") else "name matched; postcode differs",
              kind="observed", via="FSA")

    tg = targets.comparison_and_targets(corpus, arts, hotel, city, osm_ctx, own_theme_counts,
                                        [], awards, L)
    angles = targets.pitch_angles(own_pages, L)
    fallback_directions = ([] if tg["targets"] else
                           [{**d, "how": d["how"].replace("{town}", town or "your town")}
                            for d in RESEARCH_DIRECTIONS])

    # ---- identity & distribution
    wd = _src(corpus, "wikidata_detail")
    wb = _src(corpus, "wayback")
    wiki = _src(corpus, "wikipedia")
    for it in wiki["items"] if wiki["status"] == "ok" else []:
        m = evidence.match_hotel(it["snippet"], hotel, city, "", "")
        if m["level"] in ("high", "medium"):
            L.add(url=it["url"], source="Wikipedia", source_type="wiki", extract=it["snippet"][:300],
                  published=it.get("page_updated"), match=m["level"], match_why=m["why"],
                  kind="observed", via="Wikipedia")
    own_name = (own_facts or {}).get("name") or hotel
    variants = identity.name_variants_seen(hotel, corpus, entities, own_name, L)
    cur_title = ""
    former = identity.former_names(hotel, own_pages, arts,
                                   wd["items"] if wd["status"] == "ok" else [],
                                   wb["items"] if wb["status"] == "ok" else [], cur_title)
    nameshare = identity.namesakes(hotel, city, corpus, entities)
    footprint = identity.listing_footprint(corpus, hotel, city, entities,
                                           [{"domain": evidence.domain_of(l["url"]), "url": l["url"]}
                                            for l in discovery.get("profiles", [])
                                            if l.get("platform") == "Google Maps"])
    consistency = identity.listing_consistency(corpus, hotel, own_facts, own_pages, L)
    dest_cands = [c for c in corpus.get("candidates", []) if c["source_type"] == "destination_body"]
    body = None
    area_toks = evidence.place_tokens(city)[0] | {evidence.fold(town)}
    # Prefer a destination site named for the area (visitsurrey.com for Weybridge) over a
    # national body, and link its home page - not whichever page the search happened to return.
    for c in sorted(dest_cands, key=lambda c: (not any(t in c["domain"] for t in area_toks if t),
                                                "destination" not in c["roles"])):
        local = any(t in c["domain"] for t in area_toks if t)
        national = any(t in c["domain"] for t in ("visitbritain", "visitengland", "visitscotland",
                                                  "visitwales", "enjoyengland", "discoverbritain"))
        body = {"name": c["label"] or c["domain"], "domain": c["domain"],
                "url": f"https://{c['domain']}/",
                "scope": "national" if national else ("local" if local else "local or regional")}
        break
    dest_found = [c for c in dest_cands if c["read"]["status"] == "read" and
                  c["match"]["level"] in ("high", "medium")]
    destination = {
        "body": ({**body, "evidence_id": L.add(
            url=body["url"], source=body["name"], source_type="destination_body",
            extract=next((c["snippet"] or c["title"] for c in dest_cands if c["url"] == body["url"]), "")[:300],
            kind="observed", match="high", match_why="official destination site for the area",
            via="search")} if body else None),
        "listing_found": bool(dest_found),
        "pages_naming_hotel": [{"url": c["url"], "title": c["page"].get("title", ""),
                                "date": c["page"].get("published")} for c in dest_found],
        "route": ("Use the destination site's own contact or business/partner pages to ask how hotels "
                  "are listed or featured. Whether the hotel is eligible, and any cost, were not checked."),
    }
    booking = identity.booking_links(site_links)
    discovered_platforms = [r["platform"] for r in footprint
                            if r["discovered"] and r["type"] != "map / open data"]
    distribution = {
        "booking_links_on_site": booking,
        "platforms_discovered": discovered_platforms,
        "statement": ("Platforms listed here were discovered in search results or linked from the site. "
                      "Availability, rates and eligibility for any AI-assisted booking were NOT checked - "
                      "that needs live distribution data this tool does not have."),
    }
    ident = {"name_variants": variants, "former_names": former, "namesakes": nameshare,
             "footprint": footprint, "consistency": consistency, "destination": destination,
             "distribution": distribution,
             "sources_compared": [
                 {"source": "Hotel's own website", "name": own_name,
                  "place": (own_facts or {}).get("address", ""), "domain": evidence.domain_of(base_url)}] +
                 [{"source": e["source"], "name": (e.get("facts") or {}).get("name") or e.get("label"),
                   "place": (e.get("facts") or {}).get("address") or e.get("description", ""),
                   "domain": evidence.domain_of((e.get("facts") or {}).get("url", "")),
                   "confident": e.get("match_confident")}
                  for e in entities or [] if e.get("found")] +
                 [{"source": "FSA hygiene register", "name": f["name"], "place": f.get("postcode"),
                   "domain": "", "confident": f.get("same_postcode")} for f in fsa_items[:2]]}

    # ---- reviews
    rv = reviews.assess(ratings, arts, themes, own_theme_counts, cov)

    # ---- traveller
    needs = travellers.traveller_need_coverage(themes, guest, osm_ctx, fsa_items)
    comp_entries = [e for r in tg["roundups"] for e in r["entries"]]
    opp = travellers.opportunities(needs, osm_ctx, town or city, themes, guest, arts)
    dist = travellers.distinctive_positioning(themes, own_pages, osm_ctx, arts, comp_entries)
    term = travellers.terminology(hotel, own_pages, arts, entities, corpus, themes)
    trav = {"needs": needs, "opportunities": opp, "positioning": dist, "terminology": term}

    # ---- social & local, website
    yt = _src(corpus, "youtube")
    social = localctx.social_and_video(discovery, yt, tavily_result)
    local = localctx.location_context(osm, own_pages, arts, L)
    website = localctx.website_support(themes, awards, own_pages, arts, guest, site, ratings, entities)

    media_block = {"articles": arts, "clusters": clusters, "summary": cov, "rejected": rejected,
                   "unread": unread, "awards": awards, "themes": themes, "ratings": ratings,
                   "comparison": tg["comparison"], "roundups": tg["roundups"], "targets": tg["targets"],
                   "angles": angles, "research_directions": fallback_directions,
                   "gdelt": {k: _src(corpus, "gdelt")[k] for k in ("status", "reason")}}

    ctx = {"media": media_block, "targets": tg, "angles": angles, "awards": awards, "identity": ident,
           "rating_signals": ratings, "fsa": fsa_items, "traveller": trav, "website": website,
           "flags": {"searched": searched}, "hotel": hotel, "city": city}
    recs = recommend.build(ctx)
    # recommendations from the existing scoring engine join the same schema
    for r in scorecard_recs or []:
        section = CAT_SECTION.get(r.get("category_key"), "website")
        owner = (r.get("owner") or "").lower()
        team = (recommend.OWNER_TO_TEAM.get(owner)
                or recommend.OWNER_TO_TEAM.get(owner.split(" (")[0])
                or DEFAULT_TEAM.get(section, "web"))
        pr = r.get("priority") if r.get("priority") in recommend.PRIORITY_RANK else "medium"
        recs.append(recommend._rec(
            "S-" + str(r.get("code") or r["action"][:18]), section, r["action"][:120],
            r["action"], [],
            r.get("why") or "It affects whether guests and assistants can read the hotel's own facts.",
            r["action"] + (f" (page: {r['page']})" if r.get("page") else ""),
            team, pr, "Carried over from the category scoring (" + str(r.get("category", "")) + ").",
            "The next audit no longer lists it.", "observation", example=r.get("example")))
    recs.sort(key=lambda r: (recommend.PRIORITY_RANK[r["priority"]], r["id"]))
    top5 = recommend.prioritise(recs, 5)

    checks = _checks(ident, rv, media_block, trav, social, local, website, corpus, searched,
                     awards, tg, angles, opp, consistency, footprint, booking, discovered_platforms,
                     variants, own_pages)
    method = _methodology(corpus, checks, searched)

    return {"version": 1, "ledger": L.to_list(), "identity": ident, "reviews": rv, "media": media_block,
            "traveller": trav, "social": social, "local": local, "website": website,
            "recommendations": recs, "priority_actions": [r["id"] for r in top5],
            "checks": checks, "methodology": method,
            "sections": [{"id": i, "title": t} for i, t in SECTIONS]}


# --------------------------------------------------------------------- checks

def _c(n, status, summary, reason="", ids=None, inference=False):
    section, name = CHECK_NAMES[n]
    return {"n": n, "section": section, "name": name, "status": status, "summary": summary,
            "reason": reason, "evidence_ids": ids or [], "inference": inference}


def _checks(ident, rv, md, trav, social, local, website, corpus, searched, awards, tg, angles, opp,
            consistency, footprint, booking, discovered_platforms, variants, own_pages):
    out = []
    ok_ent = [s for s in ident["sources_compared"] if s["source"] != "Hotel's own website"]
    out.append(_c(1, "assessed" if len(ok_ent) >= 1 else "partial",
                  f"Compared the website with {len(ok_ent)} other source(s); "
                  f"{len(variants)} name form(s); {len(ident['namesakes'])} possible namesake(s); "
                  f"{len(ident['former_names'])} possible former name(s).",
                  "" if ok_ent else "No other source could be matched to this hotel.", inference=True))
    n_disc = sum(1 for r in footprint if r["discovered"])
    n_read = sum(1 for r in footprint if r["content_assessed"])
    out.append(_c(2, "assessed" if searched else "partial",
                  f"{n_disc} listing(s) discovered; the content of {n_read} was read. 'Discovered' and "
                  "'content assessed' are kept separate.",
                  "" if searched else "No search was run (no Tavily key), so only open-data records and "
                  "links on the website were considered."))
    out.append(_c(3, "assessed" if consistency["pages_compared"] else "not_assessed",
                  f"{consistency['pages_compared']} listing page(s) could be read and compared; "
                  f"{len(consistency['rows'])} difference(s) found.",
                  "" if consistency["pages_compared"] else
                  "No listing page could lawfully be read: the major platforms prohibit automated "
                  "reading, and the rest were not found or not readable."))
    out.append(_c(4, "assessed" if ident["destination"]["body"] else "partial",
                  ("Official destination site found; " + ("a page naming the hotel exists."
                   if ident["destination"]["listing_found"] else "no page naming the hotel was found.")
                   if ident["destination"]["body"] else "No official destination site was identified."),
                  "Eligibility and cost were not checked." if ident["destination"]["body"] else
                  "The destination-body search returned no suitable site."))
    out.append(_c(5, "partial" if (booking or discovered_platforms) else "not_assessed",
                  f"{len(booking)} booking link(s) on the site; {len(discovered_platforms)} platform(s) "
                  "discovered.",
                  "Availability, rates and AI-booking eligibility were not checked - they need live "
                  "distribution data."))
    for n in range(6, 15):
        c = rv["checks"][n]
        out.append(_c(n, c["status"], c["summary"], c.get("reason", "")))
    cov = md["summary"]
    reads_ok = corpus.get("reads", {}).get("ok", 0)
    out.append(_c(15, "assessed" if (searched and reads_ok) else ("partial" if searched else "not_assessed"),
                  f"{cov['articles']} page(s) naming the hotel from {cov['publishers']} publisher(s); "
                  f"{len(md['rejected'])} look-alike page(s) rejected.",
                  "" if searched else "No search ran (no Tavily key).", [a["id"] for a in md["articles"]][:6]))
    out.append(_c(16, "assessed" if cov["articles"] else "not_assessed",
                  "Types: " + (", ".join(f"{k} {v}" for k, v in cov["by_type"].items()) or "none") + ".",
                  "Types are inferred from titles, URLs and wording, not from a publisher's own labels.",
                  inference=True))
    out.append(_c(17, "assessed" if cov["articles"] else "not_assessed",
                  "Freshness: " + (", ".join(f"{k} {v}" for k, v in cov["by_freshness"].items()) or "n/a") + ".",
                  "Undated pages are reported as 'unknown'." if cov["by_freshness"].get("unknown") else ""))
    out.append(_c(18, "assessed" if cov["articles"] else "not_assessed",
                  f"{cov['independent_publishers']} independent publisher(s); {cov['duplicates_removed']} "
                  "duplicate/syndicated copies collapsed; sponsored and press-release pieces excluded."))
    out.append(_c(19, "assessed", f"{len(awards)} award/accreditation theme(s) checked against issuers.",
                  "Where no page on the issuer's own site names the hotel, the claim stays 'claimed by "
                  "the hotel'."))
    out.append(_c(20, "assessed" if md["themes"]["themes"] else "not_assessed",
                  f"{len(md['themes']['themes'])} theme(s) with extracts; "
                  f"{len(md['themes']['disagreements'])} disagreement(s) between sources."))
    n_cmp = len(md["comparison"])
    out.append(_c(21, "assessed" if n_cmp >= 3 else ("partial" if n_cmp else "not_assessed"),
                  f"{n_cmp} comparison hotel(s) could be validated from guides." if n_cmp
                  else "No comparison hotels could be validated.",
                  "" if n_cmp >= 3 else
                  "Too few: it needs readable guides that list nearby hotels, and most guides found were "
                  "paywalled, blocked automated reading, or did not list properties in a readable form."))
    real_targets = [t for t in tg["targets"]]
    out.append(_c(22, "assessed" if real_targets else "partial",
                  f"{len(real_targets)} target(s), each backed by a real page." if real_targets else
                  "No evidenced targets - research directions are given instead, clearly labelled.",
                  "" if real_targets else "Discovery coverage was insufficient to name outlets."))
    out.append(_c(23, "assessed" if angles else "not_assessed",
                  f"{len(angles)} angle(s) grounded in facts on the hotel's own pages, each with the "
                  "evidence still missing." if angles else "No documented, pitch-worthy fact was found.",
                  "" if angles else "Nothing in the pages read supports an angle; none has been invented."))
    out.append(_c(24, "assessed", f"{sum(1 for n in trav['needs'] if n['strength'] >= 2)} of "
                  f"{len(trav['needs'])} traveller needs have independent evidence."))
    out.append(_c(25, "assessed" if opp else "partial",
                  f"{len(opp)} opportunity question(s), each with supporting facts and missing evidence.",
                  "These are opportunities, not measured AI rankings."))
    out.append(_c(26, "partial", f"{len(trav['positioning']['candidates'])} candidate feature(s) named by "
                  "independent sources.",
                  "Comparison with other hotels is limited to the guides that were readable."
                  if not trav["positioning"]["comparison_available"] else
                  "Comparison covers only hotels named in the guides that were read.", inference=True))
    out.append(_c(27, "partial", f"{len(trav['terminology']['labels'])} property-type label(s) compared; "
                  f"{len(trav['terminology']['conflicts'])} conflict(s).",
                  "Guest wording was not assessed - no guest review text was accessible."))
    n_prof = len(social["profiles"])
    out.append(_c(28, "partial" if (n_prof or social["videos"]) else "not_assessed",
                  f"{n_prof} official profile(s) linked from the website; {len(social['videos'])} public "
                  "video(s) found." if social["youtube_status"] == "ok" else
                  f"{n_prof} official profile(s) linked from the website.",
                  "Social platforms do not allow automated reading of posts, so activity and sentiment are "
                  "not inferred. " + (social["youtube_reason"] if social["youtube_status"] != "ok" else "")))
    if local["available"]:
        failed = local["failed_parts"]
        out.append(_c(29, "partial" if failed else "assessed",
                      f"{len(local['stations'])} station(s), {len(local['attractions'])} attraction(s), "
                      f"{len(local['venues'])} venue(s) mapped; {len(local['partnerships'])} partnership "
                      "statement(s).",
                      ("Some map queries were not answered: " + ", ".join(failed) + ". ") if failed else ""
                      + "Distances are straight-line."))
    else:
        out.append(_c(29, "partial" if local["partnerships"] else "not_assessed",
                      f"{len(local['partnerships'])} partnership statement(s) found." if local["partnerships"]
                      else "Local context was not assessed.", local["reason"]))
    out.append(_c(30, "assessed", f"{len(website['external_facts_missing_on_site'])} thing(s) others say "
                  "are not on the website; crawler access summarised."))
    return out


def _methodology(corpus, checks, searched):
    srcs = []
    for name, env in (corpus.get("sources") or {}).items():
        srcs.append({"source": env.get("source", name), "status": env["status"],
                     "reason": env.get("reason", ""), "items": len(env["items"]),
                     "access": env.get("access", "")})
    counts = {"assessed": 0, "partial": 0, "not_assessed": 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {
        "check_counts": counts,
        "sources_this_run": srcs,
        "queries": corpus.get("queries", []),
        "tavily_credits_used": corpus.get("tavily_credits", 0),
        "reads": corpus.get("reads", {}),
        "source_catalogue": sources.SOURCES,
        "excluded_sources": sources.EXCLUDED_SOURCES,
        "notes": corpus.get("notes", []),
        "principles": [
            "No AI assistant was asked about the hotel. Nothing here measures what AI recommends.",
            "Every finding links to evidence: source, URL, date collected, publication date where "
            "stated, an extract, hotel-match confidence and whether it is observed or inferred.",
            "A page counts as coverage of this hotel only if it names the hotel in full; look-alikes "
            "(same word, different place or thing) are rejected and listed.",
            "Search results are not a complete crawl: not finding something does not mean it does not exist.",
            "robots.txt is respected. Pages that decline automated reading are reported as not read.",
            "Recommendations are labelled 'documented guidance', 'hypothesis' or 'observation'. None "
            "guarantees an AI recommendation, and none advises fake, incentivised or keyword-scripted reviews, "
            "or indiscriminate media outreach.",
        ],
    }
