"""
How much of the hotel's website is read, in one place, so every stage uses the same limits (page selection, the guest questions, the fact profile, the AI reading).

Adaptive: the most useful pages first (FIRST_BATCH), the fact profile built from them, then more pages read ONLY for what is still unverified (a facility the pages mention but the
profile did not confirm, a guest question not answered), up to LIMIT pages in all. Every page on the hotel's site that was considered is logged: read, failed (why), or not read
(lower priority, or not needed because the facts were already verified).

Discovery: the sitemap and the start page's links; when they give few of the hotel's own pages, Firecrawl's map of the site (one credit), restricted to the hotel's own section of a brand
website (urlscope), never the rest of marriott.com.
"""

import os
import re
import urllib.parse

LIMIT = int(os.environ.get("READ_LIMIT") or 40)           # the most pages any check reads
FIRST_BATCH = int(os.environ.get("READ_FIRST") or 25)     # read first, before the profile says what is still missing (20 lost facts at The Gainsborough)
STANDARD = 25                                              # the old fixed read, kept for the A/B comparison ('standard' reading)
PROFILE_CHARS = 200000                                     # what the fact profile may send in all (~50,000 tokens, about $0.10 on Sonnet)
PAGE_CHARS = 12000
FEW_PAGES = 15                                             # fewer in-scope pages than this from the sitemap and links: ask Firecrawl for the site's map

# a group's own terms, policies and FAQ (they apply to every hotel in it); not a page about one of its other hotels or destinations
POLICY_PAGE = re.compile(r"terms|conditions|polic(?:y|ies)|faqs?|booking-?info|guest-?info|cancellation", re.I)
OTHER_PROPERTY = re.compile(r"/(?:hotels?|locations?|destinations?|properties|resorts?)/[^/]+/", re.I)

# what to look for, per unverified topic: WHOLE words in a page's address or title, a strong match (the page is about it) and a weak one (it may say). Substrings misled the first
# version: 'carbis-bay-gift-shop' matched parking on 'car', 'special-offers-early-booking' matched cancellation on 'booking'.
TOPIC_PAGES = {
    "parking": (r"parking|car-?park|getting-?here|directions|find-?us|how-?to-?find-?us", r"location|travel|arrival|contact|faqs?"),
    "breakfast": (r"breakfast", r"dining|restaurant|food|eat|menus?"),
    "checkin_out": (r"check-?in|check-?out|arrival|policies|policy|good-?to-?know|need-?to-?know|hotel-?info(?:rmation)?|guest-?info(?:rmation)?", r"faqs?|terms|information"),
    "cancellation": (r"(?:booking-)?terms(?:-and)?-conditions(?:-of-booking)?|terms-conditions-of-booking|booking-?(?:policy|terms|conditions)|cancellation(?:-policy)?|cancel|conditions|terms|policies|policy", r"faqs?"),
    "pets": (r"dogs?|pets?|dog-?friendly|pet-?friendly|pooches?", r"faqs?|policies|policy"),
    "accessibility": (r"accessib(?:le|ility)|disabled|mobility", r"faqs?|policies|policy"),
    "family": (r"famil(?:y|ies)|kids|children|child", r"faqs?|rooms?"),
    "transport": (r"getting-?here|directions|find-?us|how-?to-?get-?here|travel|transport", r"location|contact|arrival"),
    "wifi": (r"wi-?fi|internet|amenities|facilities", r"faqs?|rooms?"),
    "ev": (r"ev|electric|charging|parking|car-?park", r"facilities|getting-?here|faqs?"),
    "restaurant": (r"restaurants?|dining|dine|eat|food|menus?|brasserie|bistro|grill", r"bars?"),
    "bar": (r"bars?|lounge|cocktails?|drinks", r"dining"),
    "spa": (r"spa|wellness|treatments?|massage", r"relax|leisure"),
    "pool": (r"pools?|swimming|lido", r"spa|leisure|facilities|wellness"),
    "gym": (r"gym|fitness|leisure", r"spa|facilities|wellness"),
    "meeting_rooms": (r"meetings?|conferences?|events?|venues?|business|boardroom", r"private-?dining"),
    "weddings": (r"weddings?|ceremon(?:y|ies)", r"celebrations?|events?"),
    "room_service": (r"room-?service|in-?room-?dining", r"dining|faqs?"),
}
# pages a follow-up is never worth: a shop, offers and vouchers, news and blogs, jobs, one event or one menu item
NOT_FOR_FOLLOW_UP = re.compile(r"(?:^|[/_-])(?:shop|store|gift|vouchers?|offers?|special|deals?|promo|news|blog|press|careers?|jobs?|whats-?on|event-?\d|gallery|photos?|reviews?"
                               r"|privacy|cookies?|gdpr|terms-?of-?(?:use|service|website)|website-?terms|legal|modern-?slavery|accessibility-?statement)(?:$|[/_.-])", re.I)      # the privacy policy is not the booking terms (THE NICI)


def _words_in(url, title=""):
    """The words of a page's address path and title, joined by '-' so a pattern can match a whole word or a short phrase."""
    path = urllib.parse.urlparse(url).path.lower()
    words = re.split(r"[^a-z0-9]+", path + " " + (title or "").lower())
    return "-" + "-".join(w for w in words if w) + "-"


def _match(rx, words):
    return re.search(r"-(?:" + rx + r")-", words) is not None


# a page that answers by pointing elsewhere: 'Please see our terms and conditions page on our website' (THE NICI's FAQ on cancellation)
POINTS_ELSEWHERE = re.compile(r"\b(?:please )?(?:see|refer to|read|visit|view|check|consult|found (?:in|on))\b[^.\n]{0,40}\b(?:terms|conditions|t&cs?|policy|policies|faq|booking (?:terms|conditions)|website|page|link)\b"
                              r"|\b(?:terms|conditions|policy) (?:page|section)\b|\bset out in (?:our|the)\b", re.I)


def retrieval_gaps(guest, read_urls):
    """
    Questions the pages answered only by pointing to another page, when that page was not read: a retrieval failure on our side, not a gap in the hotel's website. They become
    'couldn't check' with the reason, and are returned for the operator. -> [question id]
    """
    out = []
    for q in (guest or {}).get("questions") or []:
        if q.get("state") in ("partial", "not_found", "needs_checking") and not q.get("found") and POINTS_ELSEWHERE.search(q.get("snippet") or ""):
            q["state"] = "couldnt_check"
            q["missing"], q["nice_to_have"] = [], []
            q["retrieval_gap"] = True
            q["note"] = (f"The site answers this on another page (“{(q.get('snippet') or '')[:140]}”), which we could not read; this is a limit of our check, not a gap in the website.")
            try:
                import guest_questions
                q["state_label"] = guest_questions.STATE_LABELS["couldnt_check"]
            except Exception:  # noqa: BLE001
                pass
            out.append(q["id"])
    return out


def unverified(guest, profile, features=None):
    """
    What is still not verified after the first read: guest questions not answered, and facilities the word rules find on the pages but the profile did not confirm.
    -> [topic], most important first.
    """
    out = []
    for q in (guest or {}).get("questions") or []:
        if q.get("state") in ("not_found", "couldnt_check", "partial") and q.get("id") in TOPIC_PAGES:
            out.append(q["id"])
    facs = (profile or {}).get("facilities") or {}
    for f in features or []:
        if f.get("key") in TOPIC_PAGES and f["key"] not in facs and f.get("pages", 0) >= 1:
            out.append(f["key"])                   # mentioned on the pages, not confirmed either way
    seen = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def follow_up(candidates, read_urls, topics, room):
    """
    The next pages to read for the unverified topics: for each topic, the unread candidate that is most clearly about it (a strong whole-word match in its address or title before a weak
    one, a shorter address before a longer), never a shop, offer, news or one-event page. At most `room`.
    candidates: [{"url", "title"}] in priority order. -> ([url], {url: [topics it is read for]})
    """
    def _k(u):
        return u.split("#")[0].rstrip("/").lower()                # 'faqs/#main-content' is the FAQ already read
    done = {_k(u) for u in read_urls}
    seen, pool = set(), []
    for c in candidates:
        k = _k(c["url"])
        if k in done or k in seen or NOT_FOR_FOLLOW_UP.search(urllib.parse.urlparse(c["url"]).path):
            continue
        seen.add(k)
        pool.append(dict(c, url=c["url"].split("#")[0]))
    picked, why = [], {}
    for t in topics:
        if len(picked) >= room or t not in TOPIC_PAGES:
            continue
        strong, weak = TOPIC_PAGES[t]
        best = None
        for i, c in enumerate(pool):
            w = _words_in(c["url"], c.get("title") or "")
            score = 2 if _match(strong, w) else 1 if _match(weak, w) else 0
            if score == 2 and t == "cancellation" and re.search(r"-(?:booking|cancel\w*)-", w):
                score = 3                              # the booking terms before any other policy page
            if score:
                depth = len([x for x in urllib.parse.urlparse(c["url"]).path.split("/") if x])
                key = (-score, depth, i)
                if best is None or key < best[0]:
                    best = (key, c["url"])
        if best:
            u = best[1]
            if u not in picked:
                picked.append(u)
            why.setdefault(u, []).append(t)
    return picked, why


def firecrawl_map(start_url, api_key, *, post=None, limit=200, timeout=40):
    """The site's pages as Firecrawl maps them (one credit). -> [{"url", "title"}] or [] on any failure."""
    import requests
    post = post or requests.post
    for api in ("https://api.firecrawl.dev/v2/map", "https://api.firecrawl.dev/v1/map"):
        try:
            r = post(api, json={"url": start_url, "limit": limit, "includeSubdomains": False}, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
            if r.status_code != 200:
                continue
            d = r.json()
            links = d.get("links") or (d.get("data") or {}).get("links") or []
            out = []
            for x in links:
                if isinstance(x, str):
                    out.append({"url": x, "title": ""})
                elif isinstance(x, dict) and x.get("url"):
                    out.append({"url": x["url"], "title": x.get("title") or ""})
            if out:
                return out
        except Exception:  # noqa: BLE001 - discovery is an extra; the sitemap and links stand
            continue
    return []


def ledger(pages, candidates, followed=None):
    """Every page of the hotel's site that was considered: read, failed (why), or not read (and why). -> [{"url", "status", "why"}]"""
    out, seen = [], set()
    for p in pages or []:
        u = p.get("url") or ""
        seen.add(u.rstrip("/").lower())
        if p.get("ok"):
            out.append({"url": u, "status": "read", "why": ("follow-up for " + ", ".join((followed or {}).get(u, []))) if (followed or {}).get(u) else ""})
        elif p.get("replaced"):
            out.append({"url": u, "status": "failed", "why": (p.get("reason") or "") + " (replaced by another page)"})
        else:
            out.append({"url": u, "status": "failed", "why": p.get("reason") or "could not be read"})
    for c in candidates or []:
        u = c["url"] if isinstance(c, dict) else c
        if u.rstrip("/").lower() not in seen:
            seen.add(u.rstrip("/").lower())
            out.append({"url": u, "status": "not read", "why": "lower priority; the facts it might hold were already verified or the page limit was reached"})
    return out
