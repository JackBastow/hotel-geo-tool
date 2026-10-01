#!/usr/bin/env python3
"""
The scoring model: eight categories, weighted, with honest coverage.

The weights are the ones the tool is designed around:

    AI Visibility             25.0%   does the hotel appear in AI recommendations
    OTAs & Travel Platforms   15.0%   representation on Booking, Expedia, TripAdvisor
    Reviews & Reputation      15.0%   rating, volume, recency, recurring themes
    Editorial & Blogs         15.0%   credible publications, tourism sites, guides
    Website & Technical       12.5%   can machines crawl and understand the site
    Social & UGC               7.5%   recent discussion on Instagram, TikTok, Reddit
    Entity Consistency         5.0%   does the web agree on what this hotel is
    Freshness                  5.0%   is the information current or stale

THE CENTRAL DESIGN PROBLEM
--------------------------
Most of that model cannot be measured without paid or keyed APIs:

  - AI Visibility needs Google Search grounding, which is not on any free tier.
  - OTAs and Reviews live on sites that refuse automated requests outright
    (TripAdvisor 403, Hilton 403, Booking.com bot challenge). Their robots.txt
    is readable and disallows exactly this, so the tool does not work around it.
  - Editorial coverage needs a web search index. There is no free one that can
    be queried without a key.

That is 70% of the weighted model. A single "score out of 100" that quietly
left those out would tell a hotel it scored 61 when two thirds of what the
score claims to measure was never looked at - which is worse than useless,
because it reads as reassurance.

So the score is computed over ASSESSED categories only, and the coverage is
reported next to it, always. `coverage_pct` is the share of total weight that
was actually measured. A score of 78 at 27.5% coverage is stated as exactly
that, never as 78/100.

Unassessed categories score nothing and cost nothing. A hotel is never
penalised for a gap in this tool's reach.
"""

import datetime as dt
import re

# key, label, weight, one-line description of what it answers
CATEGORIES = [
    ("ai_visibility", "AI Visibility", 25.0,
     "Does the hotel actually appear in relevant AI recommendation searches?"),
    ("otas", "OTAs & Travel Platforms", 15.0,
     "Is it well represented on Booking, Expedia, TripAdvisor, Google Hotels?"),
    ("reviews", "Reviews & Reputation", 15.0,
     "Rating, review volume, recency, and the themes guests keep raising."),
    ("editorial", "Editorial & Blogs", 15.0,
     "Is it mentioned by credible travel publications, tourism sites, guides?"),
    ("website", "Website & Technical", 12.5,
     "Can AI and search systems crawl and understand the site?"),
    ("social", "Social & UGC", 7.5,
     "Is there meaningful recent discussion on Instagram, TikTok, Reddit?"),
    ("entity", "Entity Consistency", 5.0,
     "Do the name, address, amenities and key facts agree across the web?"),
    ("freshness", "Freshness", 5.0,
     "Is the information current, or stale?"),
]

WEIGHTS = {k: w for k, _, w, _ in CATEGORIES}
LABELS = {k: l for k, l, _, _ in CATEGORIES}


def _cat(key, score, detail, evidence=None, recs=None, partial=False):
    return {
        "key": key, "label": LABELS[key], "weight": WEIGHTS[key],
        "assessed": True, "partial": partial,
        "score": max(0, min(100, round(score))),
        "detail": detail, "evidence": evidence or [], "recommendations": recs or [],
    }


def _not_assessed(key, why, how_to_enable):
    return {
        "key": key, "label": LABELS[key], "weight": WEIGHTS[key],
        "assessed": False, "partial": False, "score": None,
        "detail": why, "evidence": [], "recommendations": [],
        "how_to_enable": how_to_enable,
    }


# --------------------------------------------------------------- categories

HIGH_VALUE_SCHEMA = ["checkinTime", "checkoutTime", "address", "telephone",
                     "geo", "amenityFeature", "starRating", "priceRange"]


def score_website(site):
    """Crawlability and machine-readability of the hotel's own site."""
    pts, ev, recs = [], [], []

    blocked = site.get("ai_crawlers_blocked") or []
    if blocked:
        pts.append(("AI crawlers blocked", 0.0, 0.30))
        ev.append(f"robots.txt blocks: {', '.join(blocked)}")
        recs.append({
            "priority": "critical",
            "action": f"Unblock {', '.join(blocked)} in robots.txt",
            "why": "These crawlers are refused outright, so the hotel's own site "
                   "cannot be used as a source by the assistants that rely on "
                   "them. Usually an accident - a security plugin or CDN default.",
        })
    else:
        pts.append(("AI crawlers allowed", 1.0, 0.30))
        ev.append("robots.txt does not block the major AI crawlers")

    has_node = site.get("lodging_node_found")
    if has_node:
        props = site.get("lodging_properties_present") or {}
        filled = [k for k in HIGH_VALUE_SCHEMA if props.get(k)]
        frac = len(filled) / len(HIGH_VALUE_SCHEMA)
        pts.append(("Hotel schema present", 1.0, 0.20))
        pts.append(("Schema completeness", frac, 0.25))
        ev.append(f"Hotel schema fields filled: {len(filled)}/{len(HIGH_VALUE_SCHEMA)}")
        missing = [k for k in HIGH_VALUE_SCHEMA if not props.get(k)]
        if missing:
            recs.append({
                "priority": "high",
                "action": f"Fill the empty Hotel schema fields: {', '.join(missing)}",
                "why": "These are the exact fields an assistant reads to answer "
                       "factual questions about the hotel.",
            })
    else:
        pts.append(("Hotel schema present", 0.0, 0.20))
        pts.append(("Schema completeness", 0.0, 0.25))
        types = ", ".join(site.get("schema_types_found") or []) or "none"
        ev.append(f"No Hotel/LodgingBusiness node. Types published: {types}")
        recs.append({
            "priority": "critical",
            "action": "Add a Hotel (or LodgingBusiness) JSON-LD block to the homepage",
            "why": "Without it the site's facts exist only as prose and every "
                   "machine has to infer them - so any other source that does "
                   "publish structured data becomes the authority by default.",
        })

    if site.get("sitemap", {}).get("present"):
        pts.append(("Sitemap", 1.0, 0.10))
        ev.append(f"Sitemap found, {site['sitemap'].get('url_count', 0)} URLs")
    else:
        pts.append(("Sitemap", 0.0, 0.10))
        recs.append({"priority": "medium",
                     "action": "Publish sitemap.xml and link it from robots.txt",
                     "why": "Without it crawlers must find pages by following links."})

    covered = site.get("topics_covered") or []
    gaps = site.get("topics_no_page_found") or []
    total = len(covered) + len(gaps)
    frac = len(covered) / total if total else 0.0
    pts.append(("Topic coverage", frac, 0.15))
    ev.append(f"Traveller topics with a page: {len(covered)}/{total}")
    if gaps:
        recs.append({
            "priority": "low",
            "action": f"Add pages for: {', '.join(gaps)}",
            "why": "A question with no page answering it has no source to cite. "
                   "Detection is by URL pattern, so check for unusual slugs first.",
        })

    score = sum(v * w for _, v, w in pts) * 100
    return _cat("website", score,
                f"{len([p for p in pts if p[1] >= 0.99])} of {len(pts)} technical "
                "checks fully passed.", ev, recs)


def score_entity(entities, consistency, location):
    """Does the web agree on what and where this hotel is?"""
    pts, ev, recs = [], [], []

    for e in entities:
        src = e["source"]
        weight = 0.30 if src == "OpenStreetMap" else 0.25
        if e.get("found") and e.get("match_confident") is True:
            pts.append((f"{src} verified", 1.0, weight))
            ev.append(f"{src}: verified entry"
                      + (f" ({e['match_reason']})" if e.get("match_reason") else ""))
        elif e.get("found"):
            pts.append((f"{src} unverified", 0.5, weight))
            ev.append(f"{src}: entry found by name but could not be verified")
            recs.append({
                "priority": "low",
                "action": f"Confirm the {src} entry is this hotel",
                "why": "Matched on name only. Hotel names repeat across the "
                       "country, so this may be a different business.",
            })
        else:
            pts.append((f"{src} missing", 0.0, weight))
            ev.append(f"{src}: no entry found for this hotel")
            recs.append({
                "priority": "high" if src == "OpenStreetMap" else "medium",
                "action": f"Add the hotel to {src}",
                "why": ("OpenStreetMap feeds Apple Maps and many apps and AI tools."
                        if src == "OpenStreetMap" else
                        "Wikidata feeds Google's Knowledge Graph and is well "
                        "represented in LLM training data."),
            })

    # Can the hotel's own site even state where it is?
    loc = location or {}
    if loc.get("postcode") or loc.get("lat"):
        pts.append(("Location readable", 1.0, 0.20))
        ev.append(f"Location determined from: {loc.get('source', 'unknown')}")
    else:
        pts.append(("Location readable", 0.0, 0.20))
        recs.append({
            "priority": "high",
            "action": "Publish a PostalAddress in JSON-LD, including the postcode",
            "why": "Nothing on the site states the address in a machine-readable "
                   "way. If an automated check can't tell where this hotel is, "
                   "neither can an assistant - nor can it be told apart from "
                   "same-named hotels elsewhere.",
        })

    sig = [c for c in consistency if c["verdict"] == "significant discrepancy"]
    minor = [c for c in consistency if c["verdict"] == "minor discrepancy"]
    if consistency:
        clean = 1.0 - (len(sig) * 1.0 + len(minor) * 0.4) / len(consistency)
        pts.append(("Facts agree", max(0.0, clean), 0.25))
        ev.append(f"{len(consistency)} fact comparisons: {len(sig)} significant, "
                  f"{len(minor)} minor discrepancies")
        if sig:
            fields = sorted({c["field"] for c in sig})
            recs.append({
                "priority": "high",
                "action": f"Resolve conflicting {', '.join(fields)} between sources",
                "why": "Another source states something materially different from "
                       "the hotel's own site. Whichever is wrong, an assistant "
                       "may repeat it.",
            })
    else:
        # Nothing to compare is not "consistent" - it is unknown.
        pts.append(("Facts agree", 0.0, 0.25))
        ev.append("No fact comparisons possible - the hotel's own site publishes "
                  "no structured facts to compare against")

    score = sum(v * w for _, v, w in pts) * 100
    return _cat("entity", score, "Entity presence and agreement across open data.",
                ev, recs)


def score_freshness(site):
    """How recently the hotel has touched its own content."""
    lastmods = [lm for lm in (site.get("sitemap", {}).get("lastmods") or []) if lm]
    if not lastmods:
        return _not_assessed(
            "freshness",
            "The sitemap carries no lastmod dates, so there is no free signal "
            "for how current the content is.",
            "Publish lastmod dates in sitemap.xml - most CMS platforms do this "
            "automatically.")

    now = dt.datetime.now(dt.timezone.utc)
    ages = []
    for lm in lastmods:
        try:
            d = dt.datetime.fromisoformat(lm.replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        ages.append((now - d).days)
    if not ages:
        return _not_assessed("freshness", "lastmod dates present but unparseable.",
                             "Use ISO-8601 dates in the sitemap.")

    ages.sort()
    newest, median = ages[0], ages[len(ages) // 2]
    fresh_12m = sum(1 for a in ages if a <= 365) / len(ages)

    # newest page: under a month is ideal, over a year is bad
    newest_score = 1.0 if newest <= 30 else (0.6 if newest <= 120 else
                                             (0.3 if newest <= 365 else 0.0))
    median_score = 1.0 if median <= 180 else (0.6 if median <= 365 else
                                              (0.3 if median <= 730 else 0.0))
    score = (newest_score * 0.35 + median_score * 0.35 + fresh_12m * 0.30) * 100

    ev = [
        f"{len(ages)} pages carry a lastmod date",
        f"Most recently updated page: {newest} days ago",
        f"Median page age: {median} days",
        f"Updated within 12 months: {round(fresh_12m * 100)}% of pages",
    ]
    recs = []
    if newest > 90:
        recs.append({"priority": "medium",
                     "action": "Update the site - nothing has changed in months",
                     "why": "Stale content is a signal to ranking and retrieval "
                            "systems, and factual pages drift out of date."})
    if fresh_12m < 0.5:
        recs.append({
            "priority": "medium",
            "action": f"Review the {round((1 - fresh_12m) * 100)}% of pages not "
                      "touched in over a year",
            "why": "Old pages often carry superseded prices, times and facilities, "
                   "which assistants will happily repeat.",
        })
    return _cat("freshness", score, "Based on sitemap lastmod dates.", ev, recs)


def score_otas(tavily_result):
    """
    Which OTAs list this hotel, read from a search index rather than by
    visiting the OTA sites directly - see tavily_check.py's module docstring
    for why. `tavily_result` is tavily_check.check_coverage()'s return value,
    or None if Tavily was never configured.
    """
    if tavily_result is None or not tavily_result.get("configured"):
        return _not_assessed(
            "otas",
            "Not measured. Booking.com, TripAdvisor and similar explicitly "
            "prohibit automated collection in their Terms of Use - this tool "
            "does not attempt to get around that. Reading a search index "
            "instead (rather than the OTA sites themselves) needs a Tavily "
            "key, which this free public tool does not include.",
            "A Tavily API key (tavily.com, free, 1,000 searches/month, no "
            "card) would enable this - see full_audit.py's TAVILY_API_KEY "
            "option if self-hosting.")
    if tavily_result.get("error"):
        return _not_assessed("otas", f"Tavily configured but the search failed: "
                                     f"{tavily_result['error']}", "Check the API key.")

    hits = tavily_result.get("ota_hits") or []
    ev = [f"OTAs found in search results: {', '.join(h['platform'] for h in hits)}"
         if hits else "No OTA listing surfaced in the search results checked"]
    recs = []
    # A hotel not surfacing on ANY OTA in a plain search is worth flagging,
    # even though absence-from-a-10-result-search is a weak negative signal.
    if not hits:
        recs.append({
            "priority": "medium",
            "action": "Confirm the hotel is listed on major OTAs (Booking.com, "
                      "Expedia, TripAdvisor)",
            "why": "None surfaced in a search for this hotel's reviews. This "
                  "is based on one search's top results, not a full listing "
                  "check - verify by hand before treating it as certain.",
        })
    score = min(len(hits), 4) / 4.0 * 100
    return _cat("otas", score,
               f"{len(hits)} OTA(s) found via search index (Tavily), not scraped "
               "directly.", ev, recs)


def score_reviews(places_result, amadeus_result):
    """
    Reviews & Reputation from whichever of Google Places / Amadeus Hotel
    Ratings is configured. Either alone is a partial signal; both together
    give star rating + review count + snippets (Places) plus a category
    breakdown of what guests actually say (Amadeus).
    """
    places_on = places_result and places_result.get("configured")
    amadeus_on = amadeus_result and amadeus_result.get("configured")

    if not places_on and not amadeus_on:
        return _not_assessed(
            "reviews",
            "Not measured. Rating and review data lives on platforms that "
            "prohibit automated collection in their Terms of Use, so this "
            "tool reads it through official, licensed channels instead - "
            "neither is configured.",
            "A Google Places API key (official rating, review count, up to 5 "
            "review snippets - free monthly allowance, but needs Google Cloud "
            "billing enabled) would enable part of this - see full_audit.py's "
            "options if self-hosting. Amadeus Hotel Ratings used to offer a "
            "free self-service tier for this too, but Amadeus decommissioned "
            "that portal on 2026-07-17 - it's Enterprise-sales-only now, so "
            "amadeus_check.py is kept for anyone with that access but is not "
            "a realistic free option any more.")

    pts, ev, recs = [], [], []

    if places_on:
        if places_result.get("found"):
            rating = places_result.get("rating")
            count = places_result.get("review_count") or 0
            pts.append(("Google rating", min(rating / 5.0, 1.0) if rating else 0.0, 0.5))
            ev.append(f"Google: {rating}/5 from {count} ratings"
                      + (f" ({places_result.get('place_name')})"
                         if places_result.get("place_name") else ""))
            if rating and rating < 4.0:
                recs.append({
                    "priority": "high",
                    "action": f"Google rating is {rating}/5 - review what guests are saying",
                    "why": f"Below 4.0 is a real visibility drag: it affects "
                          f"both consumer trust and how confidently an AI "
                          f"assistant recommends the hotel.",
                })
        else:
            pts.append(("Google rating", 0.0, 0.5))
            ev.append(f"Google Places: {places_result.get('error', 'not found')}")

    if amadeus_on:
        if amadeus_result.get("found"):
            overall = amadeus_result.get("overall_sentiment")
            pts.append(("Amadeus sentiment", (overall or 0) / 100.0,
                       0.5 if places_on else 1.0))
            ev.append(f"Amadeus aggregated sentiment: {overall}/100 "
                     f"across {amadeus_result.get('num_reviews', '?')} reviews")
            cats = amadeus_result.get("categories") or {}
            low = sorted(cats.items(), key=lambda kv: kv[1])[:2]
            if low and low[0][1] < 60:
                recs.append({
                    "priority": "medium",
                    "action": f"Guest sentiment is weakest on: "
                              f"{', '.join(k for k, v in low)}",
                    "why": "These are the specific themes guests raise most "
                          "negatively, aggregated across reviews - the most "
                          "actionable form this signal comes in.",
                })
        else:
            pts.append(("Amadeus sentiment", 0.0, 0.5 if places_on else 1.0))
            ev.append(f"Amadeus: {amadeus_result.get('error', 'no data')}")

    if not pts:
        return _not_assessed("reviews", "Configured but no usable result came back.",
                             "Check the API keys and try again.")

    total_w = sum(w for _, _, w in pts)
    score = sum(v * w for _, v, w in pts) / total_w * 100 if total_w else 0
    return _cat("reviews", score, "From official/licensed sources, not scraped.",
               ev, recs)


def score_editorial(tavily_result):
    """Credible third-party mentions - from a search index, see score_otas."""
    if tavily_result is None or not tavily_result.get("configured"):
        return _not_assessed(
            "editorial",
            "Not measured. Needs a search index to find mentions in travel "
            "publications, tourism boards and guides - this free public tool "
            "does not include it.",
            "A Tavily API key (tavily.com, free, 1,000 searches/month, no "
            "card) would enable this - see full_audit.py's TAVILY_API_KEY "
            "option if self-hosting.")
    if tavily_result.get("error"):
        return _not_assessed("editorial", f"Tavily configured but the search "
                                          f"failed: {tavily_result['error']}",
                             "Check the API key.")

    hits = tavily_result.get("editorial_hits") or []
    ev = [f"Editorial/credible mentions found: "
         f"{', '.join(h['platform'] for h in hits)}" if hits else
         "No editorial or tourism-board mention surfaced in the search checked"]
    recs = []
    if not hits:
        recs.append({
            "priority": "low",
            "action": "Consider outreach to a relevant travel publication or "
                      "the local tourism board",
            "why": "No third-party editorial coverage surfaced. This is based "
                  "on one search's results, not a full press-coverage audit.",
        })
    score = min(len(hits), 3) / 3.0 * 100
    return _cat("editorial", score,
               f"{len(hits)} editorial/credible source(s) found via search "
               "index.", ev, recs)


def score_ai_visibility(audit_payload):
    """
    Scores a (usually reduced) audit.run_full() result. Reused as-is: this
    module doesn't reimplement Gemini grounding, it just turns audit.py's
    existing metrics into this category's 0-100 and evidence lines.
    """
    if audit_payload is None:
        return _not_assessed(
            "ai_visibility",
            "Not measured. Requires Gemini with Google Search grounding, which "
            "needs a billing-enabled Google Cloud project.",
            "Add a Gemini API key with billing enabled, then tick 'Include AI "
            "visibility' before running the audit.")

    m = audit_payload.get("metrics", {})
    if not m.get("queries_succeeded"):
        return _not_assessed(
            "ai_visibility",
            f"Configured, but no queries succeeded "
            f"({m.get('queries_failed', 0)} failed). Check the API key and "
            f"that billing is enabled on the project.",
            "Check the Gemini API key.")

    mention = m.get("mention_rate", 0.0)
    top3 = m.get("top3_rate", 0.0)
    rec = m.get("recommendation_rate", 0.0)
    fp = m.get("first_party_citation_rate", 0.0)

    score = (mention * 0.35 + top3 * 0.25 + rec * 0.25 + fp * 0.15) * 100

    ev = [
        f"Mentioned in {round(mention * 100)}% of unbranded discovery queries",
        f"In the top 3 in {round(top3 * 100)}%",
        f"Recommended (not just named) in {round(rec * 100)}%",
        f"Answers cited the hotel's own site {round(fp * 100)}% of the time",
        f"Based on {m['queries_succeeded']}/{m['queries_attempted']} queries "
        f"(a sample - run the full AI visibility tab for the complete 40-query set)",
    ]
    recs = []
    if mention < 0.5:
        recs.append({
            "priority": "high",
            "action": "The hotel is absent from most unbranded AI recommendations",
            "why": f"Only named in {round(mention * 100)}% of 'best hotels in "
                  f"[city]'-style questions. This is the core AI-discoverability "
                  f"problem the rest of the model exists to diagnose.",
        })
    if mention > 0 and fp < 0.3:
        recs.append({
            "priority": "medium",
            "action": "The AI rarely cites the hotel's own site as a source",
            "why": f"Only {round(fp * 100)}% of citations point to the hotel's "
                  f"own domain - third-party sources are answering for it.",
        })

    return _cat("ai_visibility", score,
               "From a live Gemini grounded-search sample.", ev, recs)


def score_social(discovery):
    """
    Presence only - deliberately capped.

    The category as designed asks about "meaningful recent discussion" on
    Instagram, TikTok, YouTube and Reddit. That needs each platform's API:
    Instagram and TikTok are restricted, and Reddit's public JSON endpoint now
    returns 403 without OAuth (verified). So what can be established for free
    is only whether the hotel HAS a linked presence, not whether anyone is
    talking about it. The score is capped at 60 to reflect that the activity
    half was never measured, and the category is marked partial.
    """
    profs = discovery.get("profiles") or []
    platforms = {p["platform"] for p in profs}
    social = platforms & {"Facebook", "Instagram", "TikTok", "YouTube",
                          "X / Twitter", "LinkedIn", "Pinterest"}

    ev = [f"Profiles linked from the site: {', '.join(sorted(platforms)) or 'none'}"]
    recs = []

    count_score = min(len(social), 3) / 3.0
    sameas = 1.0 if discovery.get("declares_sameas") else 0.0
    if not sameas and profs:
        recs.append({
            "priority": "medium",
            "action": "Declare the hotel's profiles in a JSON-LD `sameAs` array",
            "why": "They're currently ordinary links, which is a weaker, inferred "
                   "signal than an explicit statement that these are the same "
                   "entity. `sameAs` is how the link is made machine-readable.",
        })
    if not social:
        recs.append({
            "priority": "medium",
            "action": "Link the hotel's social profiles from its own site",
            "why": "Nothing connects the site to its presence elsewhere, so the "
                   "relationship isn't discoverable.",
        })

    raw = (count_score * 0.6 + sameas * 0.4)
    ev.append("Activity and recency NOT measured - needs platform API access")
    return _cat("social", raw * 60, "Linked presence only; activity not measured.",
                ev, recs, partial=True)


# ------------------------------------------------------------------ assembly

def build_scorecard(site, entities, consistency, location, discovery,
                    ai_visibility=None, tavily_result=None,
                    places_result=None, amadeus_result=None):
    """
    Every category is assembled the same way: run its scorer, which itself
    decides "assessed" vs "not assessed" based on whether the data it needs
    was actually supplied. The caller (full_audit.py) is responsible for
    calling the optional integrations when keys are configured and passing
    their results in here - this function never reaches out to an API itself.
    """
    cats = [
        score_website(site),
        score_entity(entities, consistency, location),
        score_freshness(site),
        score_social(discovery),
        score_otas(tavily_result),
        score_reviews(places_result, amadeus_result),
        score_editorial(tavily_result),
    ]

    if ai_visibility is not None:
        cats.append(ai_visibility)
    else:
        cats.append(_not_assessed(
            "ai_visibility",
            "Not measured. This free tool does not automate asking AI "
            "assistants about the hotel - that needs a paid, billed API "
            "(Gemini with Google Search grounding), which isn't included here.",
            "Test this yourself: ask ChatGPT, Gemini or another assistant "
            "'best hotels in [city]' and see whether this hotel comes up."))

    order = {k: i for i, (k, _, _, _) in enumerate(CATEGORIES)}
    cats.sort(key=lambda c: order[c["key"]])

    assessed = [c for c in cats if c["assessed"]]
    not_assessed = [c for c in cats if not c["assessed"]]
    total_weight = sum(c["weight"] for c in assessed)
    overall = (sum(c["score"] * c["weight"] for c in assessed) / total_weight
               if total_weight else 0)

    if not_assessed:
        missing = ", ".join(c["label"] for c in not_assessed)
        caveat = (
            f"Score is {round(overall)} across the {round(total_weight, 1)}% of "
            f"the model that could be measured. It is NOT a score out of 100 "
            f"for the whole model - {round(100 - total_weight, 1)}% "
            f"({missing}) was not assessed. Unassessed categories neither help "
            f"nor hurt the number - see 'Not assessed' below for what each one "
            f"would need."
        )
    else:
        caveat = f"Score is {round(overall)}, assessed across the full model."

    return {
        "overall": round(overall),
        "coverage_pct": round(total_weight, 1),
        "assessed_weight": round(total_weight, 1),
        "categories": cats,
        "caveat": caveat,
    }


def all_recommendations(scorecard):
    """Every recommendation, worst first, tagged with the category it came from."""
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out = []
    for c in scorecard["categories"]:
        for r in c.get("recommendations", []):
            out.append({**r, "category": c["label"]})
    out.sort(key=lambda r: rank.get(r["priority"], 9))
    return out
