#!/usr/bin/env python3
"""
Turn the report's recommendations into a short, usable action plan.

A long ranked list of findings is something people read once and shelve. What
gets acted on is "do these three things first", where each one says:

    who  should do it   (web developer / copywriter / manager ...)
    where                the page it affects
    what                 a concrete example to adapt, not just a description

The examples are built from facts the audit actually read off the hotel's own
site (name, address, phone, check-in times, social profiles), so a JSON-LD
block comes out pre-filled and only the parts we could not know are left as
[bracketed] blanks. Nothing here invents a fact: anything unknown stays a
visible placeholder.

Every recommendation carries a stable `code` (set in scoring.py), so this
module never has to guess from wording.
"""

import json
import re

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

WEB = "Web developer or website supplier"
COPY = "Whoever writes the website copy"
MGR = "General manager"
MKT = "Marketing"
PR = "Marketing / PR"
ANYONE = "Anyone at the hotel"
REVENUE = "Revenue or distribution manager"

# Codes that say "go and look" rather than "go and change something". They are
# real, but they make poor headline fixes, so they only fill the top three if
# there is nothing more actionable.
CHECK_ONLY = {"guest_not_found", "guest_needs_checking", "guest_unreadable",
              "topic_guess", "entity_unverified", "otas_missing"}

SOCIAL_FOR_SAMEAS = {"Facebook", "Instagram", "TikTok", "YouTube", "X / Twitter",
                     "LinkedIn", "Pinterest", "TripAdvisor"}


# ------------------------------------------------------------------ JSON-LD

def _street_from(address, hotel, city, postcode):
    """Best-effort street from 'Hotel, Street, Town POSTCODE'. '' if unsure."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    keep = []
    for p in parts:
        low = p.lower()
        if hotel and low == hotel.lower():
            continue
        if postcode and postcode.replace(" ", "").lower() in low.replace(" ", ""):
            continue
        if city and low == city.lower():
            continue
        keep.append(p)
    return keep[0] if keep else ""


def hotel_jsonld(ctx):
    """
    A Hotel JSON-LD block pre-filled from what the audit read, with [bracketed]
    placeholders for anything it could not know. Returns the text to paste,
    wrapped in its <script> tag.
    """
    guest = ctx.get("guest") or {}
    node = guest.get("own_facts_node") or {}
    loc = ctx.get("location") or {}
    hotel = ctx.get("hotel") or ""
    city = loc.get("city") or ""
    postcode = loc.get("postcode") or ""

    street = _street_from(loc.get("address") or node.get("address") or "",
                          hotel, city, postcode)
    d = {
        "@context": "https://schema.org",
        "@type": "Hotel",
        "name": hotel or "[Hotel name]",
        "url": ctx.get("base") or "[https://www.example.com/]",
        "telephone": node.get("telephone") or "[+44 …]",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": street or "[Street address]",
            "addressLocality": city or "[Town]",
            "postalCode": postcode or "[Postcode]",
            "addressCountry": "[Country code, e.g. GB]",
        },
    }
    if loc.get("lat") is not None and loc.get("lon") is not None:
        d["geo"] = {"@type": "GeoCoordinates", "latitude": loc["lat"],
                    "longitude": loc["lon"]}
    d["checkinTime"] = node.get("checkinTime") or "[15:00]"
    d["checkoutTime"] = node.get("checkoutTime") or "[11:00]"
    d["priceRange"] = "[£££]"

    same = []
    for p in (ctx.get("discovery") or {}).get("profiles", []):
        if p.get("platform") in SOCIAL_FOR_SAMEAS and p.get("url"):
            same.append(p["url"])
    for e in ctx.get("entities") or []:
        if e.get("found") and e.get("match_confident") is True and e.get("url"):
            same.append(e["url"])
    if same:
        d["sameAs"] = list(dict.fromkeys(same))

    # amenities we can state from the pages, and only those
    amen = []
    for q in guest.get("questions", []):
        if q["id"] == "wifi" and q["state"] == "answered" and re.search(
                r"free|complimentary|included", q["snippet"], re.I):
            amen.append({"@type": "LocationFeatureSpecification",
                         "name": "Free Wi-Fi", "value": True})
    if amen:
        d["amenityFeature"] = amen
    pets = next((q for q in guest.get("questions", []) if q["id"] == "pets"), None)
    if pets and pets["state"] == "answered" and pets.get("note"):
        d["petsAllowed"] = False  # the pets answer says they are not accepted

    body = json.dumps(d, indent=2, ensure_ascii=False)
    return ('<script type="application/ld+json">\n' + body + "\n</script>\n\n"
            "Fill the [bracketed] parts - the rest was read from your own site. "
            "Test it at https://validator.schema.org/ before publishing.")


def sameas_snippet(ctx):
    urls = []
    for p in (ctx.get("discovery") or {}).get("profiles", []):
        if p.get("platform") in SOCIAL_FOR_SAMEAS and p.get("url"):
            urls.append(p["url"])
    if not urls:
        return ""
    body = ",\n    ".join(json.dumps(u) for u in dict.fromkeys(urls))
    return ('Add this to your Hotel JSON-LD block:\n"sameAs": [\n    ' + body + "\n  ]")


# -------------------------------------------------------------- per-code info

def _guest_q(ctx, qid):
    return next((q for q in (ctx.get("guest") or {}).get("questions", [])
                 if q["id"] == qid), None)


def _info(code, rec, ctx):
    """(owner, page, example, effort) for one recommendation."""
    base = ctx.get("base") or ""
    kind, _, arg = code.partition(":")

    if kind == "crawler_block":
        agents = ", ".join(ctx.get("site", {}).get("ai_crawlers_blocked") or [])
        ex = (f"In robots.txt, find and remove (or change to `Allow: /`) the rules for "
              f"{agents}:\n\nUser-agent: <name>\nDisallow: /")
        return WEB, (ctx.get("site", {}).get("robots", {}).get("url") or base + "robots.txt"), ex, "quick"
    if kind in ("no_hotel_schema", "schema_incomplete", "location_unreadable"):
        return WEB, base, hotel_jsonld(ctx), "moderate"
    if kind == "no_sitemap":
        return WEB, base + "robots.txt", f"Add this line to robots.txt:\nSitemap: {base}sitemap.xml", "quick"
    if kind == "social_sameas":
        return WEB, base, sameas_snippet(ctx), "quick"
    if kind == "social_link":
        return MKT, base, "", "quick"
    if kind == "guest_partial":
        q = _guest_q(ctx, arg)
        if q:
            return COPY, q["source_url"], q["template"], "quick"
    if kind == "guest_not_found":
        nf = [q for q in (ctx.get("guest") or {}).get("questions", [])
              if q["state"] == "not_found"]
        ex = "\n\n".join(f"{q['short']}:\n{q['template']}" for q in nf[:3])
        return COPY, "Your FAQ or the page guests read policies on", ex, "quick"
    if kind == "guest_needs_checking":
        return COPY, base, "", "quick"
    if kind == "guest_unreadable":
        return WEB, base, "", "moderate"
    if kind == "entity_missing" and arg == "OpenStreetMap":
        node = (ctx.get("guest") or {}).get("own_facts_node") or {}
        tags = [f"tourism=hotel", f"name={ctx.get('hotel') or '[name]'}",
                f"website={base}"]
        if node.get("telephone"):
            tags.append(f"phone={node['telephone']}")
        if (ctx.get("location") or {}).get("postcode"):
            tags.append(f"addr:postcode={ctx['location']['postcode']}")
        ex = ("openstreetmap.org: find the building, click Edit, add a point or "
              "area with these tags:\n" + "\n".join(tags))
        return ANYONE + " (OpenStreetMap is edited by volunteers - no approval needed)", \
            "https://www.openstreetmap.org/", ex, "quick"
    if kind == "entity_missing" and arg == "Wikidata":
        ex = ("Wikidata only accepts items that independent, published sources can "
              "back up (for example the press and guide coverage listed in this "
              "report). It may not be possible for every hotel - if it is, create an "
              "item with: instance of = hotel, official website, coordinates, "
              "and a reference for each statement.")
        return PR, "https://www.wikidata.org/", ex, "larger"
    if kind == "entity_unverified":
        return ANYONE, base, "", "quick"
    if kind == "facts_conflict":
        return (COPY, base,
                "Decide the correct value, then update the hotel's own site and "
                "the listing named in the report so they agree.", "moderate")
    if kind in ("stale_site", "stale_pages"):
        return COPY, base, "", "moderate"
    if kind == "editorial_negative":
        hits = [h for h in (ctx.get("tavily") or {}).get("editorial_hits", [])
                if (h.get("read") or {}).get("sentiment") == "negative"]
        return MGR, (hits[0]["url"] if hits else base), \
            "\n".join(h["url"] for h in hits), "quick"
    if kind == "editorial_outreach":
        return PR, base, "", "larger"
    if kind == "otas_missing":
        return REVENUE, base, "", "moderate"
    if kind in ("rating_low", "sentiment_weak"):
        return MGR, base, "", "larger"
    if kind in ("ai_absent", "ai_no_firstparty"):
        return MKT, base, "", "larger"
    return MKT, base, "", "moderate"


def enrich(recs, ctx):
    """Add owner / page / example / effort to every recommendation (a copy)."""
    out = []
    for r in recs:
        code = r.get("code") or ""
        owner, page, example, effort = _info(code, r, ctx)
        out.append({**r, "owner": owner, "page": page, "example": example,
                    "effort": effort})
    return out


def top_fixes(recs, n=3):
    """
    The few to do first. Ordered by priority, then by the weight of the
    category it affects. Within one priority tier, a fix from a category not
    yet picked is preferred, so the plan isn't three variations on one theme -
    but a lower tier never jumps ahead of a higher one. 'Go and check' items
    only fill the list if nothing more actionable is left.
    """
    def key(r):
        return (PRIORITY_RANK.get(r["priority"], 9), -(r.get("category_weight") or 0))

    actionable = sorted((r for r in recs if (r.get("code") or "").split(":")[0] not in CHECK_ONLY),
                        key=key)
    checks = sorted((r for r in recs if (r.get("code") or "").split(":")[0] in CHECK_ONLY),
                    key=key)

    picked, used_cats = [], set()
    for pool in (actionable, checks):
        for tier in sorted({PRIORITY_RANK.get(r["priority"], 9) for r in pool}):
            tier_recs = [r for r in pool if PRIORITY_RANK.get(r["priority"], 9) == tier
                         and r not in picked]
            # first pass: new categories only; second pass: anything left
            for allow_repeat in (False, True):
                for r in tier_recs:
                    if len(picked) >= n:
                        break
                    if r in picked:
                        continue
                    if allow_repeat or r.get("category_key") not in used_cats:
                        picked.append(r)
                        used_cats.add(r.get("category_key"))
            if len(picked) >= n:
                break
        if len(picked) >= n:
            break
    return picked
