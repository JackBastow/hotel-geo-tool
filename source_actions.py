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
    for r in sorted(by.values(), key=lambda r: -r["cited"]):
        kind = ai_insights.source_kind(r["domain"])
        t = classify(r["domain"], kind)
        if r["hotel"] and not r["rivals"] and t != "review":
            continue                                   # the hotel is there and nobody is ahead of it: nothing to chase
        route = ("a contact page was found: " + r["route"]) if r["route"] else ("commission or affiliate site: placement is commercial, not editorial" if r["affiliate"] else ("sponsored content: a paid placement, check before approaching" if r["sponsored"] else "no submission route was found"))
        action = ("The hotel appears here: verify what is published is accurate and complete. " + ACTION[t]) if (r["hotel"] and t in ("review", "comparison")) else ACTION[t]
        out.append({"domain": r["domain"], "type": t, "type_label": LABEL[t], "cited": r["cited"], "hotel_appears": r["hotel"], "rivals": sorted(r["rivals"])[:3], "route": route, "action": action,
                    "why_now": (f"The hotel states {reason['label'].lower()}, which could justify inclusion." if reason else "No distinctive reason has been identified yet: do not approach until there is one."),
                    "evidence": r["urls"][:2]})
    return out[:limit]
