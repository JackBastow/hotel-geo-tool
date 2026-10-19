"""
External presence: for each outside source, can the right hotel be identified, do its name and location agree with the hotel's own site, does it link to the official website, and does anything
it shows contradict the site?

Built only from evidence the audit has already collected (listing search results, open map data, the listing facts quoted in search results, the media coverage found). Nothing new is fetched.
Each source ends in one status:

  verified     read directly from an open source (OpenStreetMap, Wikidata) and compared with the hotel's own site
  identified   a page for this hotel was found in public search results and its title and address carry the hotel's name and town; the platform itself was NOT read (their terms prohibit it),
               so what it shows is not checked
  contradicts  a fact quoted in the search results differs from the hotel's own site
  unclear      something was found, but not enough to say it is this hotel
  not_verified the source cannot be checked reliably or nothing was found. This is NEVER reported as 'missing' or 'wrong': a platform we cannot read says nothing about the hotel.

Quality over quantity: a count of websites that mention the hotel earns nothing by itself. Publications are weighed by what they are (independent editorial, a blog, a roundup of many hotels,
sponsored content), how much they say about this hotel and how recent they are.
"""

import re
import urllib.parse

import evidence
import identity

LABEL = {"verified": "Verified", "identified": "Identified, not read", "contradicts": "Contradicts the website", "unclear": "Uncertain match", "limited": "Found, limited coverage", "not_verified": "Not verified"}
GENERIC_PAGE = re.compile(r"/(?:guide|best-hotels|hotels-c\d|hotels?-in-|hotels-near|city-guide|destination|things-to-do|moments|blog|news|article)s?(?:/|-|$)|/hotels/[a-z-]+-hotels?$", re.I)

PLATFORMS = [("Booking.com", ("Booking.com",)), ("Expedia", ("Expedia",)), ("Tripadvisor", ("TripAdvisor",))]


def _domain(u):
    h = urllib.parse.urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _row(source, status, **kw):
    base = {"source": source, "status": status, "label": LABEL[status], "identified": None, "name_location": None, "official_link": None, "contradictions": [], "url": "", "title": "", "note": "", "read": False}
    base.update(kw)
    return base


def _platform(label, names, footprint, listing_checks, hotel, city):
    """One travel platform: from the footprint row (a page found in search results) and the quoted listing facts."""
    fp = next((r for r in footprint or [] if r["platform"] in names), None)
    town = evidence.fold((city or "").split(",")[0])
    if not fp or not fp.get("discovered"):
        return _row(label, "not_verified", note="Not found by our searches. This does not show the hotel is not listed: the platform cannot be searched directly.")
    url, title = fp["url"], fp.get("title", "")
    generic = bool(GENERIC_PAGE.search(urllib.parse.urlparse(url).path))
    named = identity.names_hotel(url, title, "", hotel)          # the address or title itself carries the name: a snippet alone is not enough
    in_town = bool(fp.get("location_confirmed")) or (bool(town) and town in evidence.fold(f"{title} {url}"))
    diffs = [r for r in (listing_checks or {}).get("rows", []) if r["platform"] in names and r["status"] == "differs"]
    contradictions = [f"{r['fact']}: the listing shows {r['listing_says']}, the website says {r['site_says']}" for r in diffs]
    matched = [r for r in (listing_checks or {}).get("rows", []) if r["platform"] in names and r["status"] == "matches"]
    if generic or not named:
        return _row(label, "unclear", identified=False, url=url, title=title[:100],
                    note="A page was found, but it is a guide or list page, or its title and address do not name the hotel, so it is not taken as the hotel's own listing." if generic or not named else "")
    st = "contradicts" if contradictions else "identified"
    note = ("The platform's own page was not read (its terms prohibit automated reading). " + (f"{len(matched)} fact(s) quoted in search results agree with the website." if matched else "No quoted facts were available to compare."))
    return _row(label, st, identified=True, name_location=("consistent" if in_town else "town not confirmed"), official_link=None, contradictions=contradictions, url=url, title=title[:100], note=note)


def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def identifiers(e, hotel, own, own_domain):
    """
    How many independent identifiers tie an open-data entry to THIS hotel, beyond being in the same town. -> {"matched": [...], "conflicts": [...], "checked": [...]}
    name (the entry's name carries the hotel's distinctive words), coordinates (within 0.5 km of the hotel's own location), postcode, official website and telephone. A town name is not an identifier.
    """
    own = own or {}
    matched, conflicts, checked = [], [], []
    nm = evidence.fold(e.get("display_name") or e.get("label") or (e.get("facts") or {}).get("name") or "")
    toks = [t for t in evidence.distinctive_tokens(hotel or "") if len(t) > 2]
    if toks:
        checked.append("name")
        (matched if all(t in nm for t in toks) else conflicts).append("name")
    if e.get("lat") is not None and own.get("lat") is not None and own.get("lon") is not None:
        import sources
        km = sources.haversine_km(own["lat"], own["lon"], e["lat"], e["lon"])
        checked.append("coordinates")
        if km <= 0.5:
            matched.append(f"coordinates ({km:.2f} km apart)")
        elif km > 2.0:
            conflicts.append(f"coordinates ({km:.1f} km apart)")
    pc = (e.get("address_components") or {}).get("postcode")
    if pc and own.get("postcode"):
        checked.append("postcode")
        (matched if re.sub(r"\s", "", pc).upper() == re.sub(r"\s", "", own["postcode"]).upper() else conflicts).append("postcode")
    site_url = (e.get("facts") or {}).get("url")
    if site_url and own_domain:
        checked.append("website")
        d = _domain(site_url)
        (matched if d == own_domain or d.endswith("." + own_domain) or own_domain.endswith("." + d) else conflicts).append("official website")
    tel = (e.get("facts") or {}).get("telephone")
    if tel and own.get("phone"):
        checked.append("telephone")
        (matched if _digits(tel)[-9:] == _digits(own["phone"])[-9:] else conflicts).append("telephone")
    return {"matched": matched, "conflicts": conflicts, "checked": checked}


def _entity(source, entities, consistency_rows, own_domain, hotel="", own=None):
    e = next((x for x in entities or [] if x.get("source") == source), None)
    if not e or not e.get("found"):
        return _row(source, "not_verified", note=f"No {source} entry was matched to the hotel. That may only mean nobody has added it.")
    rows = [r for r in consistency_rows or [] if r.get("domain") == source]
    diffs = [f"{r['field']}: {source} shows '{r['other_source_value']}', the website says '{r['own_site_value']}'" for r in rows if r.get("verdict") == "significant discrepancy"]
    agree = [r for r in rows if r.get("verdict") == "consistent"]
    site_url = ((e.get("facts") or {}).get("url") or "")
    if site_url:
        official = "yes" if _domain(site_url) == own_domain or _domain(site_url).endswith("." + own_domain) or own_domain.endswith("." + _domain(site_url)) else "different"
        if official == "different":
            diffs.append(f"official website: {source} links to {_domain(site_url)}, not {own_domain}")
    elif source == "Wikidata":
        official = "not checked"          # the entry's official-website property is not read, so its absence says nothing
    else:
        official = "not stated"
    ids = identifiers(e, hotel, own, own_domain)
    title = (e.get("display_name") or e.get("label") or "")[:100]
    independent = [m for m in ids["matched"] if m != "name"]
    if ids["conflicts"] and "name" in ids["matched"] and (len(ids["conflicts"]) >= 1 and not independent):
        return _row(source, "unclear", identified=False, url=e.get("url", ""), title=title, official_link=official,
                    note=f"Found by name, but it does not agree with the website on {', '.join(ids['conflicts'])}, so it may be a different hotel with the same name. Not treated as a match.")
    if "name" not in ids["matched"] or not independent:
        got = ", ".join(ids["matched"]) or "only the town"
        return _row(source, "unclear", identified=False, url=e.get("url", ""), title=title, official_link=official,
                    note=f"Uncertain match: it agrees with the hotel on {got}; a match needs the name and at least one more identifier (coordinates within 0.5 km, postcode, official website or telephone). "
                         f"Checked: {', '.join(ids['checked']) or 'name only'}." + (" " + (e.get("note") or "")[:120] if e.get("note") else ""))
    return _row(source, "contradicts" if (diffs or ids["conflicts"]) else "verified", identified=True, name_location="consistent",
                official_link=official, contradictions=diffs + [f"{c} does not agree with the website" for c in ids["conflicts"] if c not in ("name",) and not any(c.split(" (")[0] in d for d in diffs)],
                url=e.get("url", ""), title=title, read=True,
                note="Read directly from open data. Matched on " + ", ".join(ids["matched"]) + f". {len(agree)} fact(s) agree with the website" + ("; none could be compared." if not rows else "."))


def _google(own_site_links):
    for lk in own_site_links or []:
        if "google." in lk.get("domain", "") and "map" in lk.get("url", ""):
            return _row("Google Maps / Google hotel listing", "not_verified", url=lk["url"], official_link=None,
                        note="The hotel's own site links to a Google Maps page. A Google Business Profile is free for the hotel to set up and manage, but Google does not allow automated reading of Maps or hotel listings, and its data interfaces need the owner's permission or are paid, so the listing's name, address, website link and hours were not checked.")
    return _row("Google Maps / Google hotel listing", "not_verified",
                note="Not checked. A Google Business Profile is free for the hotel to set up and manage, but Google does not allow automated reading of Maps or hotel listings, and its data interfaces need the owner's permission or are paid. Check the hotel's Google Business Profile by hand: name, address, phone, website link and opening details.")


def publications(media):
    """
    Independent coverage weighed by quality, not counted. Returns {rows, weighted, publishers, sponsored_excluded, recent, summary}. Each publisher counts once, by its best article. An article counts for
    more when it is independent editorial rather than a blog or a roundup of many hotels, when it says a lot about this hotel, when it clearly names it, and when it is recent. Sponsored content counts for nothing.
    """
    type_w = {"review": 1.0, "feature": 1.0, "news": 0.8, "interview": 0.8, "roundup": 0.4, "other": 0.4, "sponsored": 0.0}
    src_w = {"news_or_magazine": 1.0, "press": 1.0, "news": 1.0, "magazine": 1.0, "destination_body": 1.0, "awards_body": 1.0, "blog": 0.6, "hotel_directory": 0.3, "booking_platform": 0.0, "hotel_group": 0.0, "social": 0.0}
    sub_w = {"feature": 1.0, "substantial mention": 0.7, "passing mention": 0.3, "listed among others": 0.25}
    match_w = {"high": 1.0, "medium": 0.6}
    best = {}
    for a in (media or {}).get("articles", []):
        if a.get("type") == "sponsored":
            continue
        w = type_w.get(a.get("type"), 0.4) * src_w.get(a.get("source_type"), 0.5) * sub_w.get(a.get("substance"), 0.5) * match_w.get(a.get("match"), 0.0)
        w *= 1.0 if a.get("freshness") == "recent" else 0.7 if a.get("freshness") in ("dated", "unknown") else 0.4
        k = a.get("publisher_key") or a.get("domain")
        if w > best.get(k, (0, None))[0]:
            best[k] = (w, a)
    rows = sorted(({"publisher": a.get("publisher"), "url": a.get("url"), "title": a.get("title", "")[:100], "kind": f"{a.get('source_type', '')}, {a.get('type', '')}", "substance": a.get("substance"),
                    "match": a.get("match"), "freshness": a.get("freshness"), "weight": round(w, 2)} for w, a in best.values()), key=lambda r: -r["weight"])
    spons = sum(1 for a in (media or {}).get("articles", []) if a.get("type") == "sponsored")
    return {"rows": rows, "weighted": round(sum(r["weight"] for r in rows), 2), "publishers": len(rows), "sponsored_excluded": spons,
            "recent": sum(1 for r in rows if r["freshness"] == "recent"), "strong": sum(1 for r in rows if r["weight"] >= 0.5)}


def build(footprint, entities, consistency_rows, listing_checks, media, hotel, city, website, own_site_links=(), own=None):
    own_domain = _domain(website if "//" in (website or "") else "https://" + (website or ""))
    rows = [_google(own_site_links)]
    rows += [_platform(label, names, footprint, listing_checks, hotel, city) for label, names in PLATFORMS]
    rows += [_entity("OpenStreetMap", entities, consistency_rows, own_domain, hotel, own), _entity("Wikidata", entities, consistency_rows, own_domain, hotel, own)]
    pub = publications(media)
    if pub["publishers"]:
        rows.append(_row("Independent travel publications", "identified" if pub["strong"] else "limited", identified=True, name_location="consistent",
                         note=f"{pub['publishers']} publisher(s) found, of which {pub['strong']} are substantial independent coverage; {pub['recent']} recent."
                              + (f" {pub['sponsored_excluded']} sponsored piece(s) not counted." if pub["sponsored_excluded"] else "") + " Weighed by what each is, not counted."))
    else:
        rows.append(_row("Independent travel publications", "not_verified", note="No independent coverage was found in the searches run. That is a limited sample, not proof there is none."))
    contradictions = [{"source": r["source"], "text": c} for r in rows for c in r["contradictions"]]
    n = {k: sum(1 for r in rows if r["status"] == k) for k in LABEL}
    return {"rows": rows, "publications": pub, "summary": {**n, "contradictions": len(contradictions), "checkable": len(rows) - n["not_verified"]}, "contradictions": contradictions}


def authority_score(ep):
    """
    0-100 'outside validation' score from the external presence, or None when nothing could be checked. It rewards VERIFIED identification and weighs publications by quality; it is capped,
    because guest reviews cannot be measured and the platforms cannot be read. Contradictions subtract. A source that could not be verified neither adds nor subtracts.
    """
    if not ep:
        return None
    s = ep["rows"]
    pts = 0.0
    value = {"verified": 1.0, "identified": 0.7, "contradicts": 0.2, "unclear": 0.15, "limited": 0.0}
    weight = {"Google Maps / Google hotel listing": 0, "Booking.com": 10, "Expedia": 8, "Tripadvisor": 10, "OpenStreetMap": 10, "Wikidata": 7}
    for r in s:
        if r["source"] in weight:
            pts += weight[r["source"]] * value.get(r["status"], 0.0)
    pub = ep["publications"]
    pts += min(40.0, pub["weighted"] * 9.0) + (5.0 if pub["recent"] else 0.0)
    pts -= 6.0 * len(ep["contradictions"])
    cap = 85.0 if ep["summary"]["checkable"] >= 4 else 70.0 if ep["summary"]["checkable"] >= 2 else 55.0
    return max(0.0, min(cap, pts))
