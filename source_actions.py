"""
The sites the assistant relies on, and what the hotel could realistically do about each one.

For each site that came up in the assistant's answers (not the hotel's own), the audit asks the questions that decide whether it is worth acting on:
  1. is it a relevant article or directory (what kind of site, how often it was used)?
  2. does this hotel appear on it?
  3. do comparable hotels appear on it?
  4. is there a route for the hotel to be included (a contact page, a submission form), or is it a commission or sponsored placement?
  5. does the hotel have something distinctive that would justify inclusion (an advantage the differentiation engine found)?
The action depends on the kind of site: verify a listing, check event-space information, investigate genuine editorial opportunities, check amenities on a comparison site, explore partnerships with an attraction, or
improve accuracy and answer real guest concerns on a review platform. Nothing here says that coverage, or paying for placement, guarantees an AI recommendation; the report says so.
"""

import re

import ai_insights
import differentiation

TYPES = [
    ("tourism", "Official destination tourism website", r"visit|tourism|tourisme|tourist|turismo|parisjetaime|destination|convention|cvb|lonelyplanet|rough-?guides"),
    ("conference", "Conference or venue directory", r"cvent|venue|meetingpackage|eventsnear|eventplan|conference|meetings|bizzabo|eventective|meetingsbooker|kayak\.com/meetings"),
    ("attraction", "Local attraction website", r"museum|musee|musée|gallery|theatre|theater|palace|chateau|cathedral|tickets?|opera|louvre|eiffel|zoo|stadium|arena"),
]
ACTION = {
    "tourism": "Check whether the hotel is listed and whether the tourism body accepts submissions or partner listings; verify the name, address and amenities shown.",
    "conference": "Check the event-space information shown (capacities, configurations, equipment) and whether the hotel is eligible to be listed; correct anything out of date.",
    "publisher": "Investigate genuine editorial opportunities: does the publication cover hotels like this one, who writes about them, and does the hotel have something distinctive worth their readers' attention? Do not pay for undisclosed coverage.",
    "comparison": "Verify the amenities and description published about the hotel are accurate and complete.",
    "attraction": "Explore a genuine partnership or a 'where to stay nearby' mention, if the attraction publishes accommodation information.",
    "review": "Improve the accuracy of the listing and answer genuine guest concerns; do not ask guests for reviews in return for anything.",
}
LIKELY_TYPE = {"Booking and comparison site": "comparison", "Review site": "review", "Travel media": "publisher", "Tourism board": "tourism", "Social and forum": "publisher"}


def classify(domain, kind=""):
    d = (domain or "").lower()
    for key, label, rx in TYPES:
        if re.search(rx, d):
            return key
    return LIKELY_TYPE.get(kind) or "publisher"


LABEL = {"tourism": "Official destination tourism website", "conference": "Conference or venue directory", "attraction": "Local attraction website", "comparison": "Hotel comparison website",
         "review": "Review platform", "publisher": "Travel publisher or blog"}


def listing_presence(rep, domain):
    """For a booking or review site: did the audit find the hotel's OWN listing on it in public search results (the listing lookup and the wider discovery)?
    -> ("found", url) | ("not_found", "") | ("not_searched", ""). A listing found is real evidence; one not found is not proof of absence."""
    import identity
    fp = (((rep or {}).get("intel") or {}).get("identity") or {}).get("footprint") or []
    for r in fp:
        tok = next((t for l, t in identity.KEY_PLATFORMS if l == r.get("platform")), None)
        if tok and identity.on_platform(domain, tok):
            return ("found", r.get("url") or "") if r.get("discovered") else ("not_found", "")
    for r in ((rep or {}).get("external") or {}).get("rows") or []:
        if r.get("url") and r.get("status") in ("identified", "verified", "contradicts") and identity.on_platform(domain, _dom_root(r["url"])):
            return ("found", r["url"])
    return ("not_searched", "")


def _dom_root(url):
    d = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def presence_text(s):
    """What the 'Hotel there?' column says, the same on the dashboard and in the PDF."""
    if s.get("hotel_appears"):
        return "Yes" + (": its listing was found in search results" if s.get("listing_url") else "")
    if s.get("listing_site"):
        return {"not_found": "Not found by our searches (this does not show it is not listed)", "not_searched": "Not searched for on this site"}.get(s.get("listing_status"), "Not checked")
    return "Not on the page it read"


def build(rep, limit=6):
    ins = (rep or {}).get("ai_insights") or {}
    gap = (rep or {}).get("ai_gap") or {}
    own = (((rep or {}).get("meta") or {}).get("base") or "")
    own_dom = re.sub(r"^https?://(www\.)?", "", own).split("/")[0].lower()
    by = {}
    for p in ins.get("pages") or []:
        d = p.get("domain") or ""
        if not d or p.get("own_site") or (own_dom and (d == own_dom or d.endswith("." + own_dom))):
            continue
        r = by.setdefault(d, {"domain": d, "cited": 0, "hotel": False, "rivals": set(), "urls": [], "route": "", "affiliate": False, "sponsored": False})
        r["cited"] += p.get("cited") or p.get("answers") or 0
        r["hotel"] = r["hotel"] or bool(p.get("names_hotel"))
        if p.get("names_competitor"):
            r["rivals"].add(p["names_competitor"])
        r["urls"].append(p["url"])
    for a in gap.get("articles") or []:
        d = a.get("domain") or ""
        if not d or d not in by:
            if not d or (own_dom and d == own_dom):
                continue
            by.setdefault(d, {"domain": d, "cited": a.get("cited") or 0, "hotel": False, "rivals": set(), "urls": [a["url"]], "route": "", "affiliate": False, "sponsored": False})
        r = by[d]
        r["hotel"] = r["hotel"] or a.get("hotel_in") is True
        r["rivals"] |= set(a.get("rivals_in") or [])
        r["route"] = r["route"] or a.get("contact_url") or ""
        r["affiliate"] = r["affiliate"] or bool(a.get("affiliate"))
        r["sponsored"] = r["sponsored"] or bool(a.get("sponsored"))
    d = differentiation.build(rep)
    reason = (d["advantages"] or d["strengths"] or [None])[0]
    out = []
    import strategy_actions
    rival_sites = strategy_actions._rival_domains(rep)
    for r in sorted(by.values(), key=lambda r: -r["cited"]):
        if strategy_actions.is_chain_site(r["domain"]) or strategy_actions._dom(r["domain"]) in rival_sites:
            continue                                   # another hotel group's own website, or a rival hotel's: not somewhere this hotel can be listed
        kind = ai_insights.source_kind(r["domain"])
        t = classify(r["domain"], kind)
        if strategy_actions.is_listing_site(r["domain"]) and t not in ("review", "comparison"):
            t = "review" if re.search(r"tripadvisor|trustpilot|yelp|holidaycheck", r["domain"]) else "comparison"      # OYO, Kayak and the like are booking sites, never 'travel publishers'
        status, lurl = listing_presence(rep, r["domain"]) if strategy_actions.is_listing_site(r["domain"]) else (None, "")
        if status == "found":
            r["hotel"] = True
        if r["hotel"] and not r["rivals"] and t != "review":
            continue                                   # the hotel is there and nobody is ahead of it: nothing to chase
        route = ("a contact page was found: " + r["route"]) if r["route"] else ("commission or affiliate site: placement is commercial, not editorial" if r["affiliate"] else ("sponsored content: a paid placement, check before approaching" if r["sponsored"] else "no submission route was found"))
        action = ("The hotel appears here: verify what is published is accurate and complete. " + ACTION[t]) if (r["hotel"] and t in ("review", "comparison")) else ACTION[t]
        listing = strategy_actions.is_listing_site(r["domain"], t)
        out.append({"domain": r["domain"], "type": t, "type_label": LABEL[t], "cited": r["cited"], "hotel_appears": r["hotel"], "listing_site": listing, "listing_status": status, "listing_url": lurl, "rivals": sorted(r["rivals"])[:3], "route": route, "action": action,
                    "why_now": (f"The hotel states {reason['label'].lower()}, which could justify inclusion." if reason else "No distinctive reason has been identified yet: do not approach until there is one."),
                    "evidence": r["urls"][:2]})
    return out[:limit]
