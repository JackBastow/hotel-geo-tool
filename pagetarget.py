"""
Which existing page should a missing fact be added to?

Choosing a page because it happens to contain a matching word puts accessible-room details on a dining page (it mentions accessibility in passing). Each page is first given a TYPE from its address,
title and main heading (rooms, dining, location, accessibility, hotel information, FAQ, policies, events...), and each kind of information has the page types it belongs on, best first. Only an
existing page of an allowed type is ever recommended. When there is none, the advice names the general hotel-information (or FAQ) page if the site has one, and otherwise describes the page without
inventing an address.
"""

import re
import urllib.parse

import evidence

_TYPES = [
    ("accessibility", re.compile(r"accessib|disabled|disabilit|mobility|wheelchair|barrier[- ]free|inclusive")),
    ("policies", re.compile(r"polic|terms|condition|privacy|cookie|gdpr|legal|cancel|house[- ]rules|booking[- ]conditions")),
    ("faq", re.compile(r"\bfaqs?\b|frequently|questions|help[- ]centre|help")),
    ("events", re.compile(r"meeting|conference|event|wedding|banquet|function|celebration|occasion|private[- ]dining|boardroom|business[- ]centre")),
    ("spa", re.compile(r"\bspa\b|wellness|treatment|massage|sauna|health[- ]club|fitness|gym|pool")),
    ("dining", re.compile(r"dining|restaurant|\bbar\b|\bgrill\b|\beat\b|drink|food|menu|breakfast|brunch|afternoon[- ]tea|lounge|cafe|brasserie|bistro")),
    ("family", re.compile(r"famil|children|kids|child")),
    ("rooms", re.compile(r"\brooms?\b|suites?|accommodation|bedroom|stay\b|zimmer|chambres?|habitaciones")),
    ("location", re.compile(r"location|getting[- ]here|directions|how[- ]to[- ](?:get|find|reach)|find[- ]us|transport|transfer|shuttle|airport|map\b|parking|car[- ]park|travel|around[- ]the[- ]hotel|area|neighbourhood|nearby")),
    ("offers", re.compile(r"offer|deal|package|special|promo|rates?\b")),
    ("contact", re.compile(r"contact")),
    ("gallery", re.compile(r"gallery|photos|images|video")),
    ("hotel_info", re.compile(r"hotel[- ]info|information|facilit|amenit|services?|overview|about|property|at[- ]a[- ]glance|guest[- ]info|guest[- ]services")),
]

# information -> page types it belongs on, best first
TOPIC_TYPES = {
    "accessibility": ("accessibility", "hotel_info", "rooms", "faq", "policies"),
    "parking": ("location", "hotel_info", "faq", "contact", "policies"),
    "ev": ("location", "hotel_info", "faq", "contact"),
    "transport": ("location", "hotel_info", "faq", "contact"),
    "airport_transfer": ("location", "hotel_info", "faq", "contact"),
    "location": ("location", "hotel_info", "contact", "faq"),
    "occupancy": ("rooms", "family", "hotel_info"),
    "family_occupancy": ("family", "rooms", "hotel_info"),
    "room_configuration": ("rooms", "family", "hotel_info"),
    "family": ("family", "rooms", "policies", "hotel_info", "faq"),
    "children_policy": ("family", "policies", "hotel_info", "faq", "rooms"),
    "children_facilities": ("family", "hotel_info", "rooms", "faq"),
    "connecting_rooms": ("rooms", "family", "faq", "hotel_info"),
    "wifi": ("hotel_info", "rooms", "faq"),
    "breakfast": ("dining", "hotel_info", "faq"),
    "checkin_out": ("hotel_info", "faq", "policies", "contact"),
    "pets": ("policies", "hotel_info", "faq"),
    "cancellation": ("policies", "faq", "hotel_info"),
    "rate_inclusions": ("offers", "hotel_info", "faq", "rooms", "policies"),
    "meeting_detail": ("events",),
    "wedding_detail": ("events",),
    "spa_detail": ("spa", "hotel_info"),
    "pool_detail": ("spa", "hotel_info"),
    "restaurant_detail": ("dining",),
    "area_guide": ("location", "hotel_info", "faq"),
    "room_count": ("hotel_info", "rooms"),
    "balconies": ("rooms",),
}
GENERAL = ("hotel_info", "faq")
LABEL = {"hotel_info": "hotel information page", "faq": "FAQ page", "rooms": "rooms page", "location": "location / getting-here page", "accessibility": "accessibility page", "family": "family rooms page",
         "policies": "hotel policies page", "events": "meetings and events page", "dining": "dining page", "spa": "spa page", "offers": "offers page", "contact": "contact page"}


def classify(site, page):
    """The page type: from the path first (the folder says what a page is), then the title and main heading."""
    if site.is_home(page):
        return "home"
    raw = urllib.parse.unquote(urllib.parse.urlparse(page["url"]).path)
    base_path = urllib.parse.urlparse(site.base).path
    if len(base_path) > 1 and raw.lower().startswith(base_path.lower()):
        raw = raw[len(base_path):]          # '/en/hotels/zrhhitw-hilton-zurich-airport/hotel-info/' is judged by 'hotel-info/', not by the hotel's own name
    path = evidence.fold(raw.replace("-", " ").replace("_", " "))
    head = evidence.fold(" ".join([page.get("title", "")] + list(page.get("h1", []))[:1]))
    for hay in (path, head):
        for name, rx in _TYPES:
            if rx.search(hay):
                return name
    return "other"


def choose(site, topic, prefer_urls=()):
    """
    The best EXISTING page for `topic`, as {url, label, reason, new_page, type}. Never invents an address. `prefer_urls` are pages where related facts were found; one is used only if its type is allowed.
    """
    allowed = TOPIC_TYPES.get(topic) or GENERAL
    pages = [p for p in site.content_pages if not site.is_home(p)]
    typed = [(p, classify(site, p)) for p in pages]
    pref = {u.split("#")[0].rstrip("/") for u in prefer_urls if u}
    for rank, t in enumerate(allowed):
        cands = [p for p, ty in typed if ty == t]
        if not cands:
            continue
        cands.sort(key=lambda p: (p["url"].split("#")[0].rstrip("/") not in pref, site.depth(p), len(site.path(p))))
        p = cands[0]
        return {"url": p["url"], "label": site.path(p), "reason": f"the {LABEL.get(t, t + ' page')}" + (" that already covers this" if rank == 0 else ""), "new_page": False, "type": t}
    for t in GENERAL:
        cands = [p for p, ty in typed if ty == t]
        if cands:
            p = sorted(cands, key=lambda p: (site.depth(p), len(site.path(p))))[0]
            return {"url": p["url"], "label": site.path(p), "reason": f"the hotel's general {LABEL[t]}; no page that fits this topic better was found", "new_page": False, "type": t}
    return {"url": "", "label": "the hotel's general information page", "reason": "no suitable existing page was found among the pages read", "new_page": False, "type": ""}


def allowed_for(site, page, topic):
    """Is this page one the topic belongs on?"""
    return classify(site, page) in (TOPIC_TYPES.get(topic) or GENERAL)
