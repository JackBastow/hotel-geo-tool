"""
Machine readability, structured data and the readiness profile.

Findings are kept in four separate buckets because they need different
people and different fixes - they are deliberately NOT blended into one
"GEO score":

  access         can crawlers reach the information at all?
  understanding  can a machine tell what the hotel is, where, and what it offers?
  content        is important traveller information missing?
  authority      where is outside validation thin?

Everything is computed from pages the crawl already read. The crawl reads raw
HTML and does not run JavaScript; the report says so wherever it matters.
"""

import re
from collections import Counter, defaultdict
import urllib.parse

import evidence
import media

HOTEL_TYPES = {"Hotel", "LodgingBusiness", "Resort", "BedAndBreakfast", "Motel", "Hostel", "Inn", "Campground"}
FOOD_TYPES = {"Restaurant", "FoodEstablishment", "BarOrPub", "CafeOrCoffeeShop"}
CAUTION = ("Structured data helps machines read facts accurately. There is no evidence that adding it, on its own, makes an "
           "AI assistant recommend a hotel - treat it as accuracy and tidiness, not a ranking lever.")

BEST = "Established good practice"
INFER = "Reasonable inference"
EXPER = "Experimental"


def _types(n):
    return set(n["types"])


def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def _norm_tel(s):
    d = _digits(s)
    if d.startswith("44"):
        d = "0" + d[2:]
    return d[-10:]


def _km(a_lat, a_lon, b_lat, b_lon):
    import sources
    return sources.haversine_km(a_lat, a_lon, b_lat, b_lon)


# ------------------------------------------------------------ structured data

def structured_audit(site, location, guest, intent_rows):
    nodes = []          # (page_url, node)
    errors = 0
    for p in site.pages:
        sg = p.get("signals") or {}
        errors += sg.get("jsonld_errors", 0)
        for n in sg.get("structured", []):
            nodes.append((p["url"], n))
    items = []

    def add(item, status, detail, evd=None, advice="", level=BEST, optional=False):
        items.append({"item": item, "status": status, "detail": detail, "evidence": evd or [],
                      "advice": advice, "confidence": level, "optional": optional})

    hotel = [(u, n) for u, n in nodes if _types(n) & HOTEL_TYPES]
    if errors:
        add("Valid JSON-LD", "incorrect", f"{errors} structured-data block(s) could not be read at all (invalid JSON).",
            advice="Fix the syntax so the block can be read; an unreadable block is the same as none.")
    if not hotel:
        add("Hotel / LodgingBusiness", "missing",
            "No Hotel or LodgingBusiness markup was found on any page read, so the website does not state its basic facts in a standard, machine-readable form.",
            advice="Add one Hotel block to the homepage with the name, address, telephone, coordinates and links to the official profiles.",
            level=BEST)
        best = None
    else:
        # richest node is the one the audit judges
        u, best = max(hotel, key=lambda x: len(x[1]["keys"]))
        on_home = any(_key_of(uu) == site.home_key for uu, _ in hotel)
        add("Hotel / LodgingBusiness", "present" if on_home else "could_improve",
            f"Found ({', '.join(best['types'])}) on {urllib.parse.urlparse(u).path or '/'}."
            + ("" if on_home else " It is not on the homepage."),
            [{"url": u, "snippet": "Properties present: " + ", ".join(best["keys"][:14])}],
            advice="" if on_home else "Put the Hotel block on the homepage, where it is easiest to find.")

        # --- the fields a useful Hotel block carries
        missing_core = [f for f, ok in (("name", best["name"]), ("url", best["url"]), ("telephone", best["telephone"]),
                                         ("address", best["address"]), ("geo (coordinates)", best["geo"]),
                                         ("image", best["image"]), ("description", best["description"])) if not ok]
        if missing_core:
            add("Hotel details", "could_improve", "The Hotel block is missing: " + ", ".join(missing_core) + ".",
                [{"url": u, "snippet": "Present: " + ", ".join(best["keys"][:14])}],
                advice="Add the missing properties so the block states the basic facts completely.")
        else:
            add("Hotel details", "present", "The Hotel block carries name, URL, telephone, address, coordinates, image and description.",
                [{"url": u, "snippet": ""}])
        extras = [f for f, ok in (("checkinTime", best["checkinTime"]), ("checkoutTime", best["checkoutTime"]),
                                  ("priceRange", best["priceRange"]), ("sameAs (official profiles)", best["sameAs"])) if not ok]
        if extras:
            add("Useful extras", "could_improve", "Not included in the Hotel block: " + ", ".join(extras) + ".",
                advice="Check-in and check-out times and the official profile links are the most useful additions; price range only if you want to publish it.",
                level=INFER, optional=True)

        # --- is what it says correct?
        wrong = []
        page_tels = {_norm_tel(t) for p in site.pages for t in p.get("tels", []) if len(_digits(t)) >= 9}
        if best["telephone"] and page_tels and _norm_tel(best["telephone"]) not in page_tels:
            wrong.append(("telephone", f"The markup says {best['telephone']}, but the pages show {', '.join(sorted(page_tels))}."))
        a = best["address"]
        if a.get("postalCode"):
            pcs = {re.sub(r"\s", "", m.group(0)).upper() for p in site.pages for m in re.finditer(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", p["text"])}
            if pcs and re.sub(r"\s", "", str(a["postalCode"])).upper() not in pcs:
                wrong.append(("postcode", f"The markup postcode is {a['postalCode']}, but the pages show {', '.join(sorted(pcs))}."))
        g = best["geo"]
        try:
            lat, lon = float(g.get("latitude")), float(g.get("longitude"))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                wrong.append(("coordinates", "The latitude/longitude are not valid numbers on a map."))
            elif location and location.get("lat") is not None and _km(lat, lon, location["lat"], location["lon"]) > 1.5:
                wrong.append(("coordinates", f"The markup coordinates are {_km(lat, lon, location['lat'], location['lon']):.1f} km from the location the site's own map link gives."))
        except (TypeError, ValueError):
            if g:
                wrong.append(("coordinates", "The latitude/longitude are present but are not numbers."))
        if best["url"]:
            host = lambda s: (urllib.parse.urlparse(s).netloc or "").lower().replace("www.", "")  # noqa: E731
            if host(best["url"]) and host(best["url"]) != host(site.base):
                wrong.append(("url", f"The markup URL ({best['url']}) is a different site from this one."))
        node = (guest or {}).get("own_facts_node", {})
        for key, lab in (("checkinTime", "check-in time"), ("checkoutTime", "check-out time")):
            if best.get(key) and node.get(key):
                import guest_questions as gq
                if gq.parse_time(str(best[key])) and gq.parse_time(str(best[key])) != node[key]:
                    wrong.append((lab, f"The markup says {best[key]}, the pages say {node[key]}."))
        if wrong:
            add("Is the markup correct?", "incorrect", "; ".join(w[1] for w in wrong),
                [{"url": u, "snippet": w[1]} for w in wrong[:3]],
                advice="Correct the markup so it matches the page text (the page is usually the one that's right).")
        else:
            add("Is the markup correct?", "present", "What the Hotel block says matches the page text where we could compare it.")

        # --- address detail
        if a:
            miss = [k for k in ("streetAddress", "addressLocality", "postalCode", "addressCountry") if not a.get(k)]
            if miss:
                add("PostalAddress", "could_improve", "The address is missing: " + ", ".join(miss) + ".",
                    [{"url": u, "snippet": str(a)[:160]}], advice="Complete the address in the standard fields.")
            else:
                add("PostalAddress", "present", "A complete postal address is given.")
        else:
            add("PostalAddress", "missing", "The Hotel block has no structured address.", advice="Add the address in its separate parts.")
        add("GeoCoordinates", "present" if g and g.get("latitude") else "missing",
            "Coordinates are given." if g and g.get("latitude") else "No coordinates in the Hotel block.",
            advice="" if g and g.get("latitude") else "Add the hotel's latitude and longitude - it is a precise way to pin the property to a map.")
        # --- amenities
        listed = {a["name"].lower() for a in best["amenities"]}
        if not listed:
            add("amenityFeature (facilities)", "missing", "No facilities are listed in the markup.",
                advice="List the facilities you genuinely offer (Wi-Fi, parking, pool, pets...).", level=INFER, optional=True)
        else:
            add("amenityFeature (facilities)", "present", f"{len(listed)} facilities are listed in the markup.")
    # --- ratings: never push self-published ratings
    ratings = [(u, n) for u, n in nodes if n.get("aggregateRating") or "AggregateRating" in n["types"] or "Review" in n["types"]]
    if ratings:
        add("AggregateRating / Review", "present", "Rating or review markup is present on the site.",
            [{"url": ratings[0][0], "snippet": ""}],
            advice="Only keep it if the ratings come from genuine, independent reviews you may show; search engines restrict how a business's own ratings about itself are shown, so it may not be used.",
            level=BEST, optional=True)
    else:
        add("AggregateRating / Review", "missing", "None - and none is recommended unless it comes from a genuine independent source.",
            advice="", level=BEST, optional=True)
    # --- restaurant
    if any(r["key"] == "food" and r["level"] in ("some", "strong") for r in intent_rows):
        has = any(_types(n) & FOOD_TYPES for _, n in nodes)
        add("Restaurant", "present" if has else "could_improve",
            "Restaurant markup found." if has else "The site talks about its restaurant, but there is no Restaurant markup.",
            advice="" if has else "If the restaurant is a distinct, bookable place, mark it up as its own Restaurant entity with opening hours.",
            level=INFER, optional=True)
    # --- FAQ
    faq_pages = [p for p in site.pages if (p.get("signals") or {}).get("faq_like_items", 0) >= 3 or (site.is_faq(p) and (p.get("signals") or {}).get("faq_like_items", 0) >= 1)]
    faq_nodes = [(u, n) for u, n in nodes if "FAQPage" in _types(n)]
    if faq_nodes:
        bad = [u for u, n in faq_nodes if n["n_questions"] == 0]
        add("FAQPage", "incorrect" if bad else "present",
            "FAQ markup is present but lists no questions." if bad else "FAQ markup is present.",
            [{"url": faq_nodes[0][0], "snippet": ""}], advice="List each question and answer in the markup." if bad else "")
    elif faq_pages:
        p = faq_pages[0]
        add("FAQPage", "could_improve",
            f"{site.label(p)} answers {p['signals']['faq_like_items']} questions in plain text but has no FAQ markup.",
            [{"url": p["url"], "snippet": "; ".join((p["signals"].get("headings") or [])[:3])}],
            advice="Marking up an existing FAQ makes the questions and answers easier for systems that read the page to identify. Search engines have limited FAQ rich results to a few kinds of site, so do not expect a visible change in results.",
            level=INFER, optional=True)
    # --- breadcrumbs
    crumbs_visible = [p for p in site.pages if (p.get("signals") or {}).get("breadcrumb")]
    if any("BreadcrumbList" in _types(n) for _, n in nodes):
        add("BreadcrumbList", "present", "Breadcrumb markup is present.")
    elif crumbs_visible:
        add("BreadcrumbList", "could_improve", f"Visible breadcrumbs exist on {len(crumbs_visible)} page(s) but have no markup.",
            [{"url": crumbs_visible[0]["url"], "snippet": ""}], advice="Mark up the breadcrumbs that are already visible.", level=INFER, optional=True)
    # --- events: only if relevant
    if any("Event" in _types(n) for _, n in nodes):
        add("Event", "present", "Event markup is present.")
    return {"items": items, "node_count": len(nodes), "hotel_found": bool(hotel), "best": best, "caution": CAUTION}


def _key_of(u):
    import insight_content
    return insight_content._key(u)


# --------------------------------------------------------------- machine readiness

def _f(bucket, fid, title, status, severity, detail, consequence, fix="", evd=None, level=BEST):
    return {"bucket": bucket, "id": fid, "title": title, "status": status, "severity": severity, "detail": detail,
            "consequence": consequence, "fix": fix, "evidence": evd or [], "confidence": level}


def machine_readiness(site, pages_meta, site_payload, entities, intel, structured, consistency_items, question_rows, web=None):
    out = []
    pm = pages_meta or []
    robots = (site_payload or {}).get("robots", {})
    sitemap = (site_payload or {}).get("sitemap", {})
    crawled = len(pm)

    # ======================= ACCESS
    if robots.get("blocks_all"):
        out.append(_f("access", "robots_block_all", "robots.txt tells every crawler to stay out", "issue", "critical",
                      "robots.txt disallows the whole site.", "Search engines and AI crawlers that respect robots.txt will not read the hotel's pages (other sources may still describe the hotel).",
                      "Remove the blanket Disallow rule unless the site is deliberately private.", [{"url": site.base.rstrip("/") + "/robots.txt", "snippet": "Disallow: /"}]))
    elif not robots.get("present"):
        out.append(_f("access", "robots_missing", "No robots.txt found", "info", "low", "The site has no robots.txt.",
                      "Crawlers will read everything by default, but they have no pointer to your sitemap.",
                      "Add a robots.txt that points to the sitemap.", level=BEST))
    else:
        out.append(_f("access", "robots_ok", "robots.txt allows crawlers", "ok", "none", "robots.txt is present and does not block the whole site.", ""))
    blocked = (site_payload or {}).get("ai_crawlers_blocked") or []
    if blocked:
        out.append(_f("access", "ai_blocked", f"{len(blocked)} AI crawler(s) are blocked in robots.txt", "issue", "medium",
                      "Blocked: " + ", ".join(blocked), "Those assistants' crawlers are told not to read the site, so they may be less able to draw on it directly (they can still use other sources). "
                      "Blocking can be a deliberate choice about content use.", "Decide deliberately. If you want to be discoverable by those assistants, remove the block.",
                      [{"url": site.base.rstrip("/") + "/robots.txt", "snippet": ", ".join(blocked)}], level=BEST))
    if sitemap.get("present"):
        out.append(_f("access", "sitemap_ok", "A sitemap is published", "ok", "none", f"{sitemap.get('url_count', 0)} URLs listed.", ""))
    else:
        out.append(_f("access", "sitemap_missing", "No sitemap.xml found", "issue", "medium", "No sitemap was found at the usual addresses or in robots.txt.",
                      "Crawlers rely on links alone to discover pages; deep pages (meetings, spa, offers) may be missed.",
                      "Publish a sitemap.xml and reference it in robots.txt.", level=BEST))
    shells_all = [r for r in pm if r.get("js_shell") or "probably built with JavaScript" in (r.get("reason") or "")]
    booking = re.compile(r"book|reserv|checkout|basket|cart|availability|enquir", re.I)
    shells = [r for r in shells_all if not booking.search(urllib.parse.urlparse(r["url"]).path)]
    tools = [r for r in shells_all if r not in shells]
    if tools:
        out.append(_f("access", "js_booking", f"{len(tools)} booking page(s) need JavaScript", "info", "low",
                      ", ".join(urllib.parse.urlparse(r["url"]).path for r in tools[:4]),
                      "Booking tools normally load this way, so it is expected. Just make sure everything a guest needs to decide (times, prices, policies) is also written as normal text on a page.",
                      "", level=INFER))
    if shells:
        out.append(_f("access", "js_empty", f"{len(shells)} page(s) show almost no text without JavaScript", "issue", "high",
                      "The raw page contains little or no readable text: " + ", ".join(urllib.parse.urlparse(r["url"]).path or "/" for r in shells[:4]) + ".",
                      "Crawlers that don't run JavaScript see an almost empty page, so the facts on it may not be picked up by them. (We read the raw HTML and do not run JavaScript, so a page that renders fine in a browser can still look empty here.)",
                      "Make the key content part of the page's HTML (server-side rendering) or provide a text version.",
                      [{"url": r["url"], "snippet": r.get("reason") or "app shell with almost no text"} for r in shells[:3]], level=INFER))
    errs = [r for r in pm if not r["ok"] and r.get("status") and r["status"] >= 400]
    if errs:
        out.append(_f("access", "http_errors", f"{len(errs)} linked page(s) returned an error", "issue", "high" if len(errs) > 2 else "medium",
                      ", ".join(f"{urllib.parse.urlparse(r['url']).path or '/'} ({r['status']})" for r in errs[:5]),
                      "Pages that error out can't be read, and links to them look like an unmaintained site.",
                      "Fix or redirect each broken page, or remove the links to them.",
                      [{"url": r["url"], "snippet": f"HTTP {r['status']}"} for r in errs[:3]], level=BEST))
    timeouts = [r for r in pm if not r["ok"] and not r.get("status") and r not in shells]
    if timeouts and len(timeouts) >= 3:
        out.append(_f("access", "slow_pages", f"{len(timeouts)} page(s) could not be fetched in time", "info", "low",
                      ", ".join(urllib.parse.urlparse(r["url"]).path or "/" for r in timeouts[:4]),
                      "Very slow or unreliable pages can be skipped by crawlers (this may also just be our fetch limit).", "Check those pages' speed and hosting."))
    noidx = [r for r in pm if r.get("noindex")]
    if noidx:
        out.append(_f("access", "noindex", f"{len(noidx)} page(s) are marked 'noindex'", "issue", "high",
                      ", ".join(urllib.parse.urlparse(r["url"]).path or "/" for r in noidx[:5]),
                      "'noindex' asks search engines to leave the page out. If it is a guest-information page, it may not appear in search results.",
                      "Remove 'noindex' from pages you want found.", [{"url": r["url"], "snippet": "robots meta contains noindex"} for r in noidx[:3]]))
    # canonicals
    off = []
    for p in site.pages:
        c = (p.get("signals") or {}).get("canonical")
        if c and _key_of(c) != _key_of(p["url"]):
            off.append((p["url"], c))
    nocanon = [p for p in site.pages if not (p.get("signals") or {}).get("canonical")]
    if off:
        out.append(_f("access", "canonical_other", f"{len(off)} page(s) say another page is the 'real' one", "issue", "medium",
                      "; ".join(f"{urllib.parse.urlparse(u).path or '/'} -> {urllib.parse.urlparse(c).path or '/'}" for u, c in off[:4]),
                      "Search engines may treat the page named as the preferred version. That is right for true duplicates, but a problem if this page is unique.",
                      "Check each canonical points where you intend.", [{"url": u, "snippet": f"canonical: {c}"} for u, c in off[:3]]))
    if site.pages and len(nocanon) >= max(3, len(site.pages) // 2):
        out.append(_f("access", "canonical_missing", f"{len(nocanon)} of {len(site.pages)} pages have no canonical address", "info", "low",
                      "No <link rel=canonical> found.", "Without it, tracking-parameter and www/non-www variants can be treated as separate pages.",
                      "Add a self-referencing canonical to each page.", level=BEST))
    # duplicates
    titles = defaultdict(list)
    for r in pm:
        if r["ok"] and r.get("title"):
            titles[evidence.fold(r["title"])].append(r)
    dup_t = {k: v for k, v in titles.items() if len(v) >= 2 and len(k) > 4}
    if dup_t:
        k, v = max(dup_t.items(), key=lambda kv: len(kv[1]))
        out.append(_f("access", "dup_titles", f"{sum(len(x) for x in dup_t.values())} pages share a title with another page", "issue", "medium",
                      f"{len(v)} pages are titled “{v[0]['title'][:70]}”: " + ", ".join(urllib.parse.urlparse(r['url']).path or '/' for r in v[:4]),
                      "Identical titles make pages hard to tell apart in results and for any system summarising the site.",
                      "Give every page its own descriptive title.", [{"url": r["url"], "snippet": r["title"][:100]} for r in v[:3]]))
    sh = [(p, media._shingles(p["text"][:2500])) for p in site.pages]
    dups = []
    for i in range(len(sh)):
        for j in range(i + 1, len(sh)):
            if media._jaccard(sh[i][1], sh[j][1]) >= 0.85:
                dups.append((sh[i][0]["url"], sh[j][0]["url"]))
    if dups:
        out.append(_f("access", "dup_content", f"{len(dups)} pair(s) of pages are near-identical", "issue", "medium",
                      "; ".join(f"{urllib.parse.urlparse(a).path or '/'} = {urllib.parse.urlparse(b).path or '/'}" for a, b in dups[:3]),
                      "Duplicate pages can leave a search engine unsure which version to show.", "Merge duplicates or make each page distinct.",
                      [{"url": a, "snippet": f"near-identical to {b}"} for a, b in dups[:2]]))
    pdf_total = sum(len(r.get("pdfs", [])) for r in pm)
    if pdf_total:
        out.append(_f("access", "pdfs", f"{pdf_total} PDF link(s) found on the pages read", "info", "low",
                      "Information in PDFs is less reliably indexed and quoted than normal page text.",
                      "Where a PDF holds facts guests ask about (capacities, menus, prices), repeat them as page text.", level=INFER))

    # ======================= UNDERSTANDING
    home = site.home
    if home:
        sg = home.get("signals") or {}
        title = home.get("title", "")
        place = evidence.fold((site.city or "").split(",")[0])
        has_name = bool(site.hotel) and evidence.fold(site.hotel) in evidence.fold(title)
        has_place = bool(place) and place in evidence.fold(title + " " + sg.get("meta_description", "") + " " + " ".join(home.get("h1", [])))
        if title and has_name and has_place:
            out.append(_f("understanding", "home_title_ok", "The homepage title names the hotel and its place", "ok", "none", f"“{title[:90]}”", ""))
        else:
            miss = [x for x, ok in (("the hotel's name", has_name), ("where it is", has_place)) if not ok]
            out.append(_f("understanding", "home_title", "The homepage title doesn't say " + " or ".join(miss), "issue", "medium",
                          f"The title is “{title[:90] or 'missing'}”.",
                          "The title is one of the main labels a search engine shows for a page; without the name and place it describes the hotel less clearly.",
                          f"Rewrite it to include the hotel name and town, e.g. “{site.hotel or '[Hotel name]'} | [type of hotel] in {(site.city or '[town]').split(',')[0]}”.",
                          [{"url": home["url"], "snippet": f"<title>{title[:100]}</title>"}], level=BEST))
        if not sg.get("meta_description"):
            out.append(_f("understanding", "home_meta", "The homepage has no meta description", "issue", "medium", "No description tag found.",
                          "Search results then show random page text instead of a clear summary written for guests.",
                          "Write a 140-160 character description: what the hotel is, where, and what makes it distinctive.",
                          [{"url": home["url"], "snippet": "no <meta name=description>"}], level=BEST))
        else:
            out.append(_f("understanding", "home_meta_ok", "The homepage has a meta description", "ok", "none", sg["meta_description"][:140], ""))
    nometa = [r for r in pm if r["ok"] and not r.get("meta_description") and not (site.home and _key_of(r["url"]) == site.home_key)]
    if len(nometa) >= max(3, len(pm) // 3):
        out.append(_f("understanding", "meta_missing", f"{len(nometa)} pages have no meta description", "issue", "low",
                      ", ".join(urllib.parse.urlparse(r["url"]).path or "/" for r in nometa[:5]),
                      "Those pages will be summarised from whatever text a search engine picks.", "Add a short, specific description to each guest-facing page.", level=BEST))
    h1bad = [r for r in pm if r["ok"] and r.get("h1_count") not in (1, None)]
    if len(h1bad) >= max(3, len(pm) // 3):
        out.append(_f("understanding", "h1", f"{len(h1bad)} pages don't have exactly one main heading", "issue", "low",
                      ", ".join(f"{urllib.parse.urlparse(r['url']).path or '/'} ({r['h1_count']})" for r in h1bad[:5]),
                      "A single clear main heading states what each page is about.", "Give each page one H1 that names its topic.", level=INFER))
    imgs = sum(r.get("images_total") or 0 for r in pm)
    noalt = sum(r.get("images_no_alt") or 0 for r in pm)
    if imgs >= 10 and noalt / imgs > 0.5:
        ex = next(((r["url"], f) for r in site.pages for f in ((r.get("signals") or {}).get("images") or {}).get("files", []) if not f["alt"]), None)
        out.append(_f("understanding", "alt", f"{noalt} of {imgs} images have no alt text", "issue", "medium",
                      "More than half the images on the pages read have no description" + (f" (for example {ex[1]['src']})" if ex else "") +
                      ". Some may be purely decorative.",
                      "Important information contained only in images is less reliably discoverable, indexable and accessible than clear text and descriptive alt text; screen-reader guests also get nothing from an undescribed image.",
                      "Describe the important images (rooms, facilities, views) in a short, factual alt text.",
                      [{"url": ex[0], "snippet": f"image {ex[1]['src']} has no alt attribute"}] if ex else None, level=BEST))
    elif imgs:
        out.append(_f("understanding", "alt_ok", "Most images have alt text", "ok", "none", f"{imgs - noalt} of {imgs} images are described.", ""))
    ents = [e for e in entities or [] if e.get("found") and e.get("match_confident") is True]
    if ents:
        out.append(_f("understanding", "entity_ok", "The hotel is recognised in open map/knowledge data", "ok", "none",
                      ", ".join(e["source"] for e in ents) + " lists it, matched to this location.", ""))
    else:
        out.append(_f("understanding", "entity_missing", "No confident match in OpenStreetMap or Wikidata", "issue", "medium",
                      "Neither source could be matched to this hotel with confidence.",
                      "Open map and knowledge data feed many apps and tools; without a clear entry the hotel is less well established there.",
                      "Check the hotel's OpenStreetMap entry (adding the website and phone) and consider whether Wikidata is appropriate.", level=BEST))
    if structured["hotel_found"]:
        out.append(_f("understanding", "schema_ok", "The site states the hotel's facts as structured data", "ok", "none", "Hotel markup is present.", ""))
    for it in structured["items"]:
        if it["status"] in ("incorrect",):
            out.append(_f("understanding", "schema_incorrect", "Structured data contradicts the page", "issue", "high", it["detail"],
                          "A system that relies on the markup may repeat the wrong fact.", it["advice"], it["evidence"], level=BEST))
    for c in consistency_items:
        if c["severity"] in ("high", "medium"):
            out.append(_f("understanding", f"cons_{c['type']}", c["title"], "issue", c["severity"], c["detail"],
                          "Contradictory facts make a hotel harder to describe correctly.", c["fix"],
                          [{"url": v["url"], "snippet": v["value"]} for v in c["values"][:3]], level=BEST))

    # ======================= CONTENT
    gaps = [q for q in question_rows if q["state"] in ("missing", "unclear", "partial")]
    hv = [q for q in gaps if q.get("high_value")]
    out.append(_f("content", "gaps", f"{len(gaps)} traveller question(s) are unclear or missing", "issue" if gaps else "ok",
                  "high" if len(hv) >= 2 else ("medium" if gaps else "none"),
                  "; ".join(q["question"] for q in gaps[:3]) + ("..." if len(gaps) > 3 else ""),
                  "If authoritative sources don't state these clearly, AI systems and search tools may be less able to answer these questions accurately or confidently.", "See the unanswered-questions list for where to add each answer.") if gaps else
               _f("content", "gaps_ok", "The common traveller questions are answered", "ok", "none", "", ""))

    # ======================= AUTHORITY
    if intel and "error" not in intel:
        md = intel["media"]["summary"]
        searched = bool(intel["methodology"]["queries"])
        if not searched:
            out.append(_f("authority", "not_measured", "Outside validation was not measured this run", "info", "none",
                          "The wider discovery was switched off or no search was available.", ""))
        else:
            if md["independent_publishers"] == 0:
                out.append(_f("authority", "no_independent", "No independent coverage was found", "issue", "medium",
                              f"{md['articles']} page(s) name the hotel, none independent editorial.",
                              "With little outside confirmation, what is known about the hotel rests mostly on the hotel's own words.",
                              "See the media section for evidenced places to approach.", level=INFER))
            else:
                out.append(_f("authority", "independent_ok", f"{md['independent_publishers']} independent publisher(s) cover the hotel", "ok", "none",
                              f"{md['recent_independent']} in the last 12 months.", ""))
            if md["independent_publishers"] and md["recent_independent"] == 0:
                out.append(_f("authority", "stale_coverage", "None of the independent coverage is recent", "issue", "low",
                              "The newest independent piece is over a year old.", "Old descriptions can describe a previous version of the hotel.",
                              "Look for a genuine reason for fresh coverage (see pitch angles).", level=INFER))
    else:
        out.append(_f("authority", "not_measured", "Outside validation was not measured", "info", "none", "", ""))
    out += web_findings(web, site.base)
    return out


A11Y_GROUPS = ("a11y-names-labels", "a11y-contrast", "a11y-navigation", "a11y-aria", "a11y-best-practices", "a11y-color-contrast",
               "a11y-tables-lists", "a11y-language", "a11y-audio-video", "")


def web_findings(web, base):
    """Findings from web_signals (Common Crawl, PageSpeed, llms.txt). Wording stays on what was observed."""
    out = []
    if not web:
        return out
    cc = web.get("commoncrawl") or {}
    ccbot_blocked = "CCBot" in ((web.get("ai_policy") or {}).get("groups", {}).get("training", {}).get("blocked") or [])
    if cc.get("status") == "ok":
        dom = cc.get("domain", "")
        url = f"https://index.commoncrawl.org/{cc['items'][0]['crawl']}-index?url={dom}&matchType=domain&output=json"
        refused, pages = cc.get("refused", 0), cc.get("pages_captured", 0)
        rs = next((i["robots_status"] for i in cc["items"] if i.get("robots_status")), None)
        if cc.get("state") == "refused" and ccbot_blocked:
            out.append(_f("access", "cc_policy", "Common Crawl is kept out by robots.txt", "info", "none",
                          "robots.txt asks CCBot (Common Crawl's crawler) to stay away, and the archive holds no readable copies of the site.",
                          "A deliberate choice about content use. It means pages from this site are less likely to be in datasets built from Common Crawl.",
                          level=BEST))
        elif cc.get("state") == "refused":
            out.append(_f("access", "cc_refused", "The website refused Common Crawl's crawler", "issue", "medium",
                          f"In Common Crawl's latest crawl(s) the site answered its crawler 'forbidden' or 'too many requests' {refused} time(s) and gave "
                          f"{'no' if not pages else str(pages)} readable page(s)" + (f" (robots.txt itself: HTTP {rs})" if rs else "") + ".",
                          "Common Crawl is a public archive that much AI training data is drawn from, so a site it cannot read is less likely to appear in "
                          "that data. A firewall that refuses this crawler may refuse other automated visitors too. (Being in the archive does not show "
                          "what any AI model says about the hotel.)",
                          "Ask your web supplier whether a firewall or bot-protection rule is refusing automated visitors. If keeping them out is deliberate, "
                          "no change is needed; if not, allow well-behaved crawlers (CCBot, Googlebot, Bingbot).",
                          [{"url": url, "snippet": f"Common Crawl: {refused} refused capture(s)" + (f"; robots.txt HTTP {rs}" if rs else "")}], level=INFER))
        else:
            out.append(_f("access", "cc_ok", "The site's pages are in Common Crawl", "ok", "none",
                          f"{pages} page(s) captured in the latest crawl(s)"
                          + (", including the homepage" if any(i.get("homepage_captured") for i in cc["items"]) else "")
                          + (f"; the crawler was also refused {refused} time(s)" if refused else "") + ".", ""))
    elif cc.get("status") == "no_results":
        out.append(_f("access", "cc_none", "No copies of the site were found in Common Crawl", "info", "low", cc.get("reason", ""), "",
                      level=INFER))
    ll = web.get("llms_txt") or {}
    if ll.get("present"):
        out.append(_f("access", "llms_ok", "The site publishes an llms.txt", "ok", "none",
                      f"{ll.get('bytes', 0)} bytes, {ll.get('link_count', 0)} link(s).", ""))
    elif ll.get("status") == "no_results":
        out.append(_f("access", "llms_missing", "No llms.txt (optional)", "info", "none", ll.get("reason", ""), ll.get("note", ""), level=INFER))
    ps = web.get("pagespeed") or {}
    if ps.get("status") == "ok":
        sc = ps["scores"]
        perf, acc = sc.get("performance"), sc.get("accessibility")
        link = f"https://pagespeed.web.dev/analysis?url={ps.get('url', base)}"
        mets = "; ".join(f"{m['label'].lower()} {m['value']}" for m in ps.get("metrics", [])[:3])
        if perf is not None:
            st, sev = ("issue", "medium") if perf < 50 else (("info", "low") if perf < 90 else ("ok", "none"))
            out.append(_f("access", "speed", f"Mobile speed score {perf}/100" + (" - slow" if perf < 50 else ""), st, sev,
                          f"Google's lab test of the homepage on a simulated phone scored {perf}/100 ({mets}). One page, one test: scores vary from run to run.",
                          "Slow pages frustrate guests booking on a phone and are harder for crawlers to read reliably." if st != "ok" else "",
                          "Ask your web supplier to act on the main findings in Google's report (typically oversized images and heavy scripts).",
                          [{"url": link, "snippet": f"PageSpeed Insights, mobile: performance {perf}"}], level=BEST))
        if acc is not None and acc < 90:
            weak = "; ".join(w["title"] for w in ps.get("weak", []) if w.get("group") in A11Y_GROUPS)[:240]
            out.append(_f("access", "a11y", f"Accessibility score {acc}/100", "issue" if acc < 80 else "info", "medium" if acc < 80 else "low",
                          "Google's automated accessibility checks flagged problems on the homepage" + (f" (e.g. {weak})" if weak else "") + ".",
                          "Accessibility problems affect guests using screen readers or keyboards and are often legal and reputational issues as well as "
                          "practical ones. Automated checks catch only some problems.",
                          "Fix the items listed in Google's report; ask a web supplier to check key pages with a screen reader.",
                          [{"url": link, "snippet": f"PageSpeed Insights, mobile: accessibility {acc}"}], level=BEST))
    return out


# --------------------------------------------------------------- readiness profile

def _band(s):
    return "strong" if s >= 75 else ("fair" if s >= 50 else "needs work")


def readiness_profile(site, guest, intent_rows, location_res, structured, findings, consistency_items, intel,
                      coverage=None, map_failed=()):
    comps = []

    def comp(key, label, score, drivers, assessed=True, note=""):
        comps.append({"key": key, "label": label, "score": None if not assessed else int(round(max(0, min(100, score)))),
                      "band": _band(score) if assessed else "not assessed", "drivers": drivers, "note": note,
                      "assessed": assessed})

    byid = {f["id"]: f for f in findings}
    # Discoverability: can the pages be reached and indexed
    d, dr = 100, []
    for fid, pen, msg in (("robots_block_all", 100, "robots.txt blocks everything"), ("sitemap_missing", 15, "no sitemap"),
                          ("js_empty", 30, "pages that look empty without JavaScript"), ("noindex", 30, "pages marked noindex"),
                          ("http_errors", 15, "linked pages that error"), ("dup_titles", 8, "duplicate page titles"),
                          ("dup_content", 8, "near-duplicate pages"), ("canonical_other", 6, "pages pointing to another canonical"),
                          ("ai_blocked", 5, "AI crawlers blocked"), ("cc_refused", 8, "the public web archive's crawler was refused")):
        if fid in byid and byid[fid]["status"] == "issue":
            d -= pen
            dr.append(f"- {msg}")
    if d == 100:
        dr.append("+ robots.txt, sitemap and page access show no problems")
    comp("discoverability", "Discoverability", d, dr, note="Can crawlers reach and index the pages?")

    # Entity clarity
    e, er = 40, []
    if structured["hotel_found"]:
        e += 20
        er.append("+ Hotel structured data present")
    else:
        er.append("- no Hotel structured data")
    if byid.get("entity_ok"):
        e += 20
        er.append("+ matched in open map/knowledge data")
    else:
        er.append("- no confident open-data match")
    bad = [c for c in consistency_items if c["type"] in ("name", "phone", "postcode", "address", "times")]
    if not bad:
        e += 20
        er.append("+ name, phone, address and times are consistent across pages")
    else:
        er.append(f"- {len(bad)} consistency problem(s): " + ", ".join(sorted({c['type'] for c in bad})))
    if any(i["status"] == "incorrect" for i in structured["items"]):
        e -= 20
        er.append("- structured data contradicts the page")
    comp("entity", "Entity clarity", e, er, note="Is it clear what and where this hotel is?")

    # Content completeness
    qs = (guest or {}).get("questions", [])
    import guest_questions as gq
    frac = gq.coverage_fraction(guest) if guest else None
    if frac is None or not qs:
        comp("content", "Content completeness", 0, ["not enough pages could be read"], assessed=False)
    else:
        n_ans = sum(1 for q in qs if q["state"] == "answered")
        comp("content", "Content completeness", frac * 100,
             [f"{n_ans} of {len(qs)} common guest questions fully answered"] +
             [f"- {q['short']}: {q['state_label'].lower()}" for q in qs if q["state"] in ("partial", "not_found", "needs_checking")][:4],
             note="Does the site answer what travellers ask?")

    # Location relevance
    items = location_res["items"]
    rail_clear = any(i["category"] == "transport" and i["state"] == "stated" for i in items)
    graded = [i for i in items if i["category"] in ("transport", "airports", "attractions", "venues", "business", "city_centre")
              and not (i["category"] == "transport" and rail_clear and i["state"] == "not_mentioned")]
    if not graded:
        comp("location", "Location relevance", 0, ["no transport or landmark was mentioned or could be mapped"], assessed=False)
    else:
        score = sum({"stated": 1.0, "mentioned_no_distance": 0.5, "not_mentioned": 0.0}[i["state"]] for i in graded) / len(graded) * 100
        comp("location", "Location relevance", score,
             [f"{sum(1 for i in graded if i['state'] == 'stated')} of {len(graded)} relevant places are tied to the hotel with a distance or time"]
             + [f"- {i['place'] or i['label']}: {i['state'].replace('_', ' ')}" for i in graded if i["state"] != "stated"][:4],
             note="Does the site tie the hotel to the places guests care about?")

    # Traveller-intent coverage
    with_ev = [r for r in intent_rows if r["level"] != "none"]
    if not with_ev:
        comp("intent", "Traveller-intent coverage", 0, ["no clear traveller focus found on the pages read"], assessed=False)
    else:
        w = {"strong": 1.0, "some": 0.6, "weak": 0.25}
        sc = sum(w[r["level"]] for r in with_ev) / len(with_ev) * 100
        comp("intent", "Traveller-intent coverage", sc,
             [f"{sum(1 for r in with_ev if r['level'] == 'strong')} traveller types strongly supported, "
              f"{sum(1 for r in with_ev if r['level'] == 'some')} partly, {sum(1 for r in with_ev if r['level'] == 'weak')} barely"],
             note="Which kinds of search does the content support?")

    # Technical accessibility
    t, tr = 100, []
    for fid, pen, msg in (("home_title", 12, "homepage title lacks name/place"), ("home_meta", 12, "no homepage meta description"),
                          ("meta_missing", 8, "many pages lack a description"), ("h1", 6, "inconsistent main headings"),
                          ("alt", 14, "most images have no alt text"), ("canonical_missing", 4, "no canonical addresses"),
                          ("speed", 12, "slow on a phone (Google's lab test)"), ("a11y", 10, "accessibility problems found by Google's test")):
        if fid in byid and byid[fid]["status"] == "issue":
            t -= pen
            tr.append(f"- {msg}")
        elif fid in byid and byid[fid]["status"] == "info":
            t -= pen / 2
    if t == 100:
        tr.append("+ titles, descriptions, headings and image text look sound")
    comp("technical", "Technical accessibility", t, tr, note="Is the page itself built to be read reliably?")

    # Structured data quality
    pts, tot, sr = 0, 0, []
    for it in structured["items"]:
        if it["optional"]:
            continue
        tot += 1
        pts += {"present": 1.0, "could_improve": 0.6, "missing": 0.0, "incorrect": 0.2}[it["status"]]
        if it["status"] != "present":
            sr.append(f"- {it['item']}: {it['status'].replace('_', ' ')}")
    if tot:
        comp("structured", "Structured data", pts / tot * 100, (sr[:5] or ["+ the Hotel markup is complete and matches the page"]),
             note="Does the markup say the right things? (Not a ranking lever.)")
    else:
        comp("structured", "Structured data", 0, ["nothing to assess"], assessed=False)

    # External authority
    if intel and "error" not in intel and intel["methodology"]["queries"]:
        md = intel["media"]["summary"]
        s = min(60, md["independent_publishers"] * 12) + (15 if md["recent_independent"] else 0)
        s += 10 if any(a["issuer_confirmed"] for a in intel["media"]["awards"]) else 0
        s += 15 if len([r for r in intel["identity"]["footprint"] if r["discovered"] and r["type"] != "map / open data"]) >= 4 else 0
        comp("authority", "External authority / evidence", s,
             [f"{md['independent_publishers']} independent publisher(s), {md['recent_independent']} recent",
              "(reviews were not measurable - no lawful free source)"],
             note="Where measurable: independent coverage, awards, listings.")
    else:
        comp("authority", "External authority / evidence", 0, ["not measured this run"], assessed=False)
    _attach_evidence(comps, site, guest, intent_rows, location_res, structured, findings, intel, coverage or {}, map_failed)
    return comps


def _level(n, high, medium):
    return "high" if n >= high else ("medium" if n >= medium else "low")


def _attach_evidence(comps, site, guest, intent_rows, location_res, structured, findings, intel, cov, map_failed):
    """
    How much evidence stands behind each score. A score and the evidence behind it are different
    things: 100/100 from one place checked, with the map data down, is a thin 100.
    """
    pages = cov.get("pages_read", len(site.pages))
    attempted = cov.get("pages_attempted", pages)
    ratio = (pages / attempted) if attempted else 0
    base = f"{pages} of {attempted} pages read"
    graded = [i for i in location_res["items"]
              if i["category"] in ("transport", "airports", "attractions", "venues", "business", "city_centre")]
    n_int = sum(1 for r in intent_rows if r["level"] != "none")
    qs = [q for q in (guest or {}).get("questions", []) if q["state"] != "couldnt_check"]
    web = _level(pages, 15, 8) if ratio >= 0.6 else "low"
    ev = {
        "discoverability": (web, f"{base}; robots.txt and sitemap checked"),
        "technical": (web, f"{base}"),
        "entity": ("high" if web == "high" and structured.get("hotel_found") is not None and any(
            f["id"] == "entity_ok" for f in findings) else ("medium" if web != "low" else "low"),
            f"{base}; open-data match {'confirmed' if any(f['id'] == 'entity_ok' for f in findings) else 'not confirmed'}"),
        "content": (web if (guest or {}).get("evidence_sufficient", True) else "low", f"{len(qs)} common questions evaluated; {base}"),
        "intent": ("high" if web == "high" and n_int >= 5 else ("medium" if web != "low" and n_int >= 3 else "low"),
                   f"{n_int} traveller types had any evidence; {base}"),
        "structured": (("high" if web == "high" else "medium") if site.home is not None else "low",
                       "homepage read" if site.home is not None else "the homepage could not be read"),
    }
    # location: how many places were actually assessed, and whether the map data was complete
    n = len(graded)
    lv = "high" if n >= 4 else ("medium" if n >= 2 else "low")
    if map_failed:
        lv = "low" if n <= 2 else "medium"
    ev["location"] = (lv, f"{n} place(s) assessed; map data " + (f"incomplete ({', '.join(map_failed)})" if map_failed else "complete"))
    # outside authority: never better than medium - guest reviews cannot be measured at all
    if intel and "error" not in intel and intel["methodology"]["queries"]:
        reads = intel["methodology"]["reads"].get("ok", 0)
        ev["authority"] = (("medium" if reads >= 6 else "low"), f"{reads} outside pages read; guest reviews are not measurable")
    else:
        ev["authority"] = ("low", "not measured this run")
    for c in comps:
        lvl, why = ev.get(c["key"], ("low", ""))
        c["evidence"] = {"level": lvl, "why": why}
        if c["assessed"] and lvl == "low":
            c["band"] = "provisional"        # a thin basis cannot earn a confident 'strong'


