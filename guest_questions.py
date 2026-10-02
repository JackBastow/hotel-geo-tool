#!/usr/bin/env python3
"""
Guest-question coverage and the hotel fact sheet.

The question this answers is not "does the site have a parking keyword" but
"does the site actually tell a guest what they need to know" - and it shows
the exact text it relied on, so a human can check it.

An earlier check guessed from URL slugs whether a "parking page" existed, and
reported "Add pages for: pool, gym, parking..." when none matched. That
conflated "we didn't find it" with "it isn't there", which is a claim this
tool cannot make. So every result here is in one of FIVE states, and they
mean different things:

    answered        every required detail found, on a page about the topic
    partial         the topic is covered but specific details are missing
                    (lists which, e.g. "price, whether you can reserve")
    needs_checking  only passing mentions - a human should look
    not_found       nothing found on the pages we checked. NOT "missing":
                    we read a bounded number of pages and say how many
    couldnt_check   we could not read enough of the site to say anything
                    (blocked, timed out, or JavaScript-rendered with no
                    readable text). Never counted against the hotel.

Everything is rule-based and says so. Rules find evidence; they do not
understand meaning, which is why uncertain results are labelled rather than
guessed at.

Bounded by design: at most MAX_PAGES pages, per-request timeouts, a total
time budget, parallel fetching, and a short-lived in-process cache so
re-checking the same site does not refetch it.
"""

import bisect
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait

from site_check import get

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

MAX_PAGES = 25
FETCH_TIMEOUT = 12
TIME_BUDGET_S = 60
CACHE_TTL_S = 6 * 3600
CACHE_MAX = 400
MIN_READABLE_CHARS = 200

MAX_HITS_PER_PAGE = 12

_CACHE = {}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ questions

def _rx(*patterns):
    return [re.compile(p, re.I) for p in patterns]


def _fact(key, label, *patterns, required=True):
    return {"key": key, "label": label, "patterns": _rx(*patterns),
            "required": required}


# The lookbehinds stop a price like "£10.00" or a date like "12.05" being read
# as a time of day.
_TIME = (r"(?<![£€\d.:])\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)\b"
         r"|(?<![£€\d.:])\d{1,2}[:.]\d{2}(?!\d|\.\d)")

# The gap between "check-in" and its time must not itself contain "check",
# otherwise "check-in is flexible, check-out 11am" gives check-in = 11am.
_CI = [
    rf"check[\s\-]?in(?:(?!check)[^.\n]){{0,60}}?(?P<t>{_TIME})",
    rf"(?P<t>{_TIME})(?:(?!check)[^.\n]){{0,40}}?check[\s\-]?in",
]
_CO = [
    rf"check[\s\-]?out(?:(?!check)[^.\n]){{0,60}}?(?P<t>{_TIME})",
    rf"(?P<t>{_TIME})(?:(?!check)[^.\n]){{0,40}}?check[\s\-]?out",
]

QUESTIONS = [
    {
        "id": "parking", "short": "Parking", "high_value": True,
        "label": "Is there parking, and what does it cost?",
        "slugs": ["parking", "car park", "getting here", "directions",
                  "transport", "travel", "facilities", "faq"],
        "mention": _rx(r"\bparking\b", r"\bcar[\s\-]?park\b", r"\bvalet\b"),
        "facts": [
            _fact("price", "the price",
                  r"[£€]\s?\d", r"\bfree\b", r"complimentary", r"no (?:extra )?charge",
                  r"\bcharge[sd]?\b", r"per (?:night|day|24)", r"\bfee\b"),
            _fact("onsite", "whether it is on-site",
                  r"on[\s\-]?site", r"\bour (?:own )?(?:private )?(?:car[\s\-]?park|parking)",
                  r"\bprivate (?:car[\s\-]?park|parking)", r"\bvalet\b",
                  r"\bsecure (?:car[\s\-]?park|parking)", r"\bunderground\b",
                  r"\boff[\s\-]?site\b", r"\bnearby\b", r"public car[\s\-]?park",
                  r"\bat the hotel\b", r"\bon (?:the )?premises\b",
                  r"\bfor (?:our |hotel )?guests\b"),
            # deliberately NOT a bare "book/booking": that word turns up in
            # neighbouring answers and falsely satisfied this fact
            _fact("reserve", "whether you can or must reserve",
                  r"\breserv", r"pre[\s\-]?book", r"\bbook (?:a |your |in advance|ahead)",
                  r"in advance", r"first[\s\-]come", r"subject to availability",
                  r"spaces? (?:are )?limited", r"cannot be (?:booked|reserved)"),
        ],
    },
    {
        "id": "breakfast", "short": "Breakfast", "high_value": True,
        "label": "When is breakfast served, and what does it cost?",
        "slugs": ["breakfast", "dining", "restaurant", "eat drink", "food", "faq"],
        "mention": _rx(r"\bbreakfast\b"),
        "facts": [
            _fact("times", "serving times", rf"{_TIME}"),
            _fact("details", "what is included or the price",
                  r"included", r"complimentary", r"[£€]\s?\d", r"continental",
                  r"full english", r"buffet", r"[àa] la carte", r"per person",
                  r"bed (?:and|&) breakfast"),
        ],
    },
    {
        "id": "checkin_out", "short": "Check-in and check-out", "high_value": True,
        "label": "What are the check-in and check-out times?",
        "slugs": ["check in", "check out", "arrival", "faq", "policies", "policy",
                  "terms", "information", "guest"],
        "mention": _rx(r"check[\s\-]?in", r"check[\s\-]?out"),
        "facts": [
            _fact("checkin", "the check-in time", *_CI),
            _fact("checkout", "the check-out time", *_CO),
        ],
    },
    {
        "id": "pets", "short": "Pets", "high_value": False, "refusal": True,
        "label": "Are dogs or pets allowed, and is there a charge?",
        "slugs": ["pet", "dog", "faq", "policies", "policy", "terms", "information"],
        "mention": _rx(r"\bdogs?\b", r"\bpets?\b", r"\banimals?\b"),
        "facts": [
            _fact("policy", "whether pets are allowed",
                  r"(?:dogs?|pets?|animals?)[^.\n]{0,60}?(?:allowed|welcome|permitted|accepted|accommodate|friendly|not allowed|not permitted|cannot|unable)",
                  r"(?:dog|pet)[\s\-]friendly", r"\bno (?:dogs|pets)\b",
                  r"(?:welcome|allow|accept)[^.\n]{0,30}(?:dogs?|pets?)"),
            _fact("fee", "any charge",
                  r"[£€]\s?\d", r"free of charge", r"no (?:extra |additional )?charge",
                  r"per (?:night|stay|dog|pet)", r"\bfee\b", r"supplement"),
            _fact("limits", "any limits (number, size, rooms)",
                  r"\bmax(?:imum)?\b", r"\blimit", r"\bdesignated\b", r"\bselected rooms\b",
                  r"\b\d+\s+(?:dogs?|pets?)\b", r"\bsize\b", r"\bbreed", required=False),
        ],
    },
    {
        "id": "accessibility", "short": "Accessibility", "high_value": True,
        "label": "Are there accessible rooms, and what features do they have?",
        "slugs": ["accessib", "disabled", "mobility", "facilities", "faq", "information"],
        "mention": _rx(r"accessib", r"wheelchair", r"disabled", r"disabilit",
                       r"mobility", r"step[\s\-]free"),
        "facts": [
            _fact("rooms", "whether accessible rooms are offered",
                  r"accessible (?:room|bedroom|suite|accommodation)",
                  r"wheelchair[\s\-]accessible", r"adapted (?:room|bedroom)",
                  r"disabled (?:room|access)", r"ground[\s\-]floor (?:room|bedroom)"),
            _fact("features", "specific features (bathroom, lift, step-free)",
                  r"wet[\s\-]?room", r"roll[\s\-]in", r"grab (?:rail|bar)", r"hearing loop",
                  r"\blift\b", r"\belevator\b", r"\bramp\b", r"step[\s\-]free",
                  r"walk[\s\-]in shower", r"ground[\s\-]floor"),
        ],
    },
    {
        "id": "family", "short": "Family rooms", "high_value": False,
        "label": "Are there family or connecting rooms, and how many can they sleep?",
        "slugs": ["family", "rooms", "accommodation", "suites", "faq"],
        "mention": _rx(r"family (?:room|suite|bedroom|friendly)", r"connecting (?:room|bedroom)s?",
                       r"interconnecting", r"\bcots?\b", r"extra beds?", r"\bz[\s\-]?bed",
                       r"sofa[\s\-]?bed", r"travelling with children"),
        "facts": [
            _fact("roomtype", "the family or connecting room type",
                  r"family (?:room|suite|bedroom)", r"connecting (?:room|bedroom)s?",
                  r"interconnecting"),
            _fact("capacity", "how many guests it sleeps",
                  r"sleeps? (?:up to )?\d", r"up to \d+ (?:guests|people|adults|persons|children)",
                  r"\d adults? (?:and|&|\+) \d", r"max(?:imum)?\.? (?:occupancy|of \d)",
                  r"\b\d+ (?:adults?|guests)\b"),
            _fact("cots", "cots or extra beds",
                  r"\bcots?\b", r"extra beds?", r"z[\s\-]?bed", r"sofa[\s\-]?bed",
                  r"travel cot", r"\bcrib\b", required=False),
        ],
    },
    {
        "id": "transport", "short": "Getting there", "high_value": False,
        "label": "How do guests get there by train, air and road?",
        "slugs": ["getting here", "directions", "transport", "location", "find us",
                  "how to find", "travel", "contact"],
        "mention": _rx(r"\bstation\b", r"\bairport\b", r"\btrain\b", r"\btaxi\b",
                       r"\bjunction\b", r"\bM\d{1,3}\b", r"sat[\s\-]?nav",
                       r"getting here", r"how to find"),
        "facts": [
            _fact("public", "public transport (rail, air, bus)",
                  r"station", r"\btrain\b", r"\brail\b", r"airport", r"\bbus\b",
                  r"\btube\b", r"\btaxi\b", r"shuttle"),
            _fact("road", "road directions (junction, postcode, sat-nav)",
                  r"junction", r"\bM\d{1,3}\b", r"\bA\d{1,3}\b", r"sat[\s\-]?nav",
                  r"postcode", r"by car", r"driving"),
            _fact("distance", "distances or journey times",
                  r"\b\d+(?:\.\d+)?\s?(?:miles?|mi|km|minutes?|mins?)\b", required=False),
        ],
    },
    {
        "id": "wifi", "short": "Wi-Fi", "high_value": False,
        "label": "Is Wi-Fi available, and is it free?",
        "slugs": ["wifi", "wi fi", "facilities", "faq", "rooms", "information"],
        "mention": _rx(r"wi[\s\-]?fi", r"wireless internet"),
        "facts": [
            _fact("cost", "whether it is free",
                  r"\bfree\b", r"complimentary", r"included", r"no (?:extra )?charge",
                  r"[£€]\s?\d", r"\bcharge"),
        ],
    },
    {
        "id": "ev", "short": "EV charging", "high_value": False,
        "label": "Is there EV charging, and what does it cost?",
        "slugs": ["ev", "electric", "charging", "parking", "getting here", "faq", "facilities"],
        "mention": _rx(r"\bEV\b", r"electric (?:vehicle|car)", r"charging (?:point|station|port)s?",
                       r"\bchargers?\b", r"\btesla\b"),
        "facts": [
            _fact("availability", "how many points and what type",
                  r"\b\d+\s*(?:x\s*)?(?:ev )?(?:charging )?(?:points?|chargers?|bays?|ports?)\b",
                  r"\bkw\b", r"type 2", r"\brapid\b", r"fast[\s\-]charg", r"destination charg"),
            _fact("cost", "cost or how to pay",
                  r"\bfree\b", r"complimentary", r"[£€]\s?\d", r"per\s?kwh",
                  r"\btariff\b", r"\bapp\b", required=False),
        ],
    },
    {
        "id": "cancellation", "short": "Cancellation", "high_value": True,
        "label": "What is the cancellation policy?",
        "slugs": ["cancel", "terms", "conditions", "policies", "policy", "faq", "booking"],
        "mention": _rx(r"cancel+(?:ation|ing|led|s)?\b"),
        "facts": [
            _fact("deadline", "the deadline",
                  r"\b\d+\s*(?:hours?|hrs?|days?)\b", r"24 ?h", r"48 ?h",
                  r"before (?:arrival|check[\s\-]?in)", r"prior to arrival", r"\bnoon\b",
                  r"\bmidday\b", r"\b\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)\b"),
            _fact("penalty", "the penalty or refund terms",
                  r"refund", r"penalt", r"non[\s\-]?refundable", r"first night",
                  r"full (?:stay|amount|charge)", r"deposit", r"no charge",
                  r"free (?:of charge )?cancel", r"\bcharged\b"),
        ],
    },
]

STATE_LABELS = {
    "answered": "Answered",
    "partial": "Partly answered",
    "needs_checking": "Needs checking",
    "not_found": "Not found on pages checked",
    "couldnt_check": "Couldn't check",
}

# 1.0 = fully answered. couldnt_check is excluded from scoring entirely.
STATE_CREDIT = {"answered": 1.0, "partial": 0.5, "needs_checking": 0.25,
                "not_found": 0.0}

GENERIC_SLUGS = ["faq", "faqs", "frequently", "terms", "conditions", "policy",
                 "policies", "information", "guest", "guests", "contact",
                 "getting", "directions", "location", "rooms", "accommodation",
                 "facilities", "services", "help"]

_SKIP_PATH = re.compile(
    r"/(?:blog|news|post|posts|tag|category|author|wp-json|feed|cart|basket|"
    r"checkout|login|account|search)(?:/|$)|\.(?:jpg|jpeg|png|gif|webp|svg|pdf|"
    r"zip|css|js|xml|ico|mp4|mp3)$", re.I)


# --------------------------------------------------------------------- fetch

def _bare(netloc):
    low = (netloc or "").lower()
    return low[4:] if low.startswith("www.") else low


def _norm_words(s):
    return " ".join(re.split(r"[^a-z0-9]+", urllib.parse.unquote(s or "").lower())).strip()


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _parse_html(url, html):
    """Pull readable main text, title, headings, contact links out of a page."""
    out = {"title": "", "h1": [], "text": "", "footer_text": "",
           "tels": [], "mails": [], "links": []}
    if BeautifulSoup is None:
        out["text"] = _clean(re.sub(r"<[^>]+>", " ", html))[:30000]
        return out
    soup = BeautifulSoup(html, "html.parser")
    out["title"] = _clean(soup.title.get_text()) if soup.title else ""
    out["h1"] = [_clean(h.get_text()) for h in soup.find_all("h1")][:3]
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("tel:"):
            out["tels"].append(urllib.parse.unquote(href[4:]).strip())
        elif low.startswith("mailto:"):
            out["mails"].append(urllib.parse.unquote(href[7:]).split("?")[0].strip())
        elif not low.startswith(("javascript:", "#")):
            out["links"].append(urllib.parse.urljoin(url, href))
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    foot = soup.find("footer")
    if foot:
        out["footer_text"] = _clean(foot.get_text(" "))[:3000]
        foot.decompose()
    for tag in soup(["nav", "header", "form"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    out["text"] = _clean(root.get_text(" "))[:30000]
    return out


def fetch_page(url, timeout=FETCH_TIMEOUT):
    """Fetch and parse one page, with a short-lived shared cache. Never raises."""
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(url)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]

    res = {"url": url, "ok": False, "reason": "", "title": "", "h1": [],
           "text": "", "footer_text": "", "tels": [], "mails": [], "links": []}
    try:
        r = get(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - one bad page must not sink the audit
        r = None
        res["reason"] = f"error: {type(e).__name__}"
    if r is None:
        res["reason"] = res["reason"] or "request failed or timed out"
    elif r.status_code != 200:
        res["reason"] = f"HTTP {r.status_code}"
    elif "html" not in (r.headers.get("Content-Type", "").lower()):
        res["reason"] = "not an HTML page"
    else:
        res.update(_parse_html(r.url or url, r.text))
        if len(res["text"]) < MIN_READABLE_CHARS:
            res["reason"] = ("no readable text (probably built with JavaScript, "
                             "so a plain fetch sees an empty page)")
        else:
            res["ok"] = True

    with _LOCK:
        if len(_CACHE) >= CACHE_MAX:
            oldest = sorted(_CACHE, key=lambda k: _CACHE[k][0])[:CACHE_MAX // 4]
            for k in oldest:
                _CACHE.pop(k, None)
        _CACHE[url] = (now, res)
    return res


# ------------------------------------------------------------ page selection

def select_pages(base, home_links, sitemap_urls, max_pages=MAX_PAGES):
    """
    Choose which pages to read: the homepage, then the pages whose addresses
    look most like they answer guest questions, then the shortest (top-level)
    addresses to broaden coverage. Only URLs the site itself lists or links to
    are used - this never guesses addresses, which would just generate 404s.
    """
    host = _bare(urllib.parse.urlparse(base).netloc)
    seen, cands = set(), []
    for u in list(sitemap_urls or []) + list(home_links or []):
        p = urllib.parse.urlparse(u)
        if p.scheme not in ("http", "https") or _bare(p.netloc) != host:
            continue
        clean = urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        key = clean.rstrip("/").lower()
        if key in seen or _SKIP_PATH.search(p.path):
            continue
        seen.add(key)
        cands.append(clean)

    home_key = base.rstrip("/").lower()
    question_slugs = {s for q in QUESTIONS for s in q["slugs"]}

    def score(u):
        path = _norm_words(urllib.parse.urlparse(u).path)
        s = sum(2 for slug in question_slugs if _norm_words(slug) in path)
        s += sum(1 for g in GENERIC_SLUGS if g in path.split())
        depth = len([x for x in urllib.parse.urlparse(u).path.split("/") if x])
        return s - 0.1 * depth, depth

    cands = [u for u in cands if u.rstrip("/").lower() != home_key]
    ranked = sorted(cands, key=lambda u: (-score(u)[0], score(u)[1]))
    chosen = [u for u in ranked if score(u)[0] > 0][: max_pages - 1]
    if len(chosen) < max_pages - 1:
        rest = sorted((u for u in cands if u not in chosen), key=lambda u: score(u)[1])
        chosen += rest[: max_pages - 1 - len(chosen)]
    return [base] + chosen


# ---------------------------------------------------------------- evaluation

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9£€\"“'‘(])")

# If the page says this is NOT offered, the follow-up details (a pet fee, say)
# stop being relevant and shouldn't be demanded.
_REFUSAL = _rx(r"unfortunately", r"can[’']?t accommodate", r"cannot accommodate",
               r"unable to accommodate", r"not (?:allowed|permitted|accepted|available)",
               r"\bno (?:dogs|pets)\b", r"do not (?:allow|accept)", r"don[’']?t (?:allow|accept)")


def _sentences(text):
    """[(start, end)] spans. FAQ pages have no line breaks, so split on . ? !"""
    spans, pos = [], 0
    for m in _SENT_SPLIT.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def _sent(text, sents, i):
    a, b = sents[i]
    return text[a:b]


def _answer_snippet(text, sents, j, limit=320):
    """The sentence that holds the evidence, plus the question it answers when
    the page is laid out as Q&A ("Is parking available? Yes, £14 a night")."""
    s = _sent(text, sents, j)
    if j > 0 and _sent(text, sents, j - 1).rstrip().endswith("?"):
        s = _sent(text, sents, j - 1) + " " + s
    elif s.rstrip().endswith("?") and j + 1 < len(sents):
        # the evidence landed on the question itself; the answer follows it
        s = s + " " + _sent(text, sents, j + 1)
    s = _clean(s)
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def _snippet(text, start, end, pad=110):
    a, b = max(0, start - pad), min(len(text), end + pad)
    s = _clean(text[a:b])
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def _topic_relevant(page, q):
    hay = _norm_words(" ".join([urllib.parse.urlparse(page["url"]).path,
                                page.get("title", ""), " ".join(page.get("h1", []))]))
    # match at the START of a word, so the slug "pet" does not hit "carpet"
    padded = f" {hay}"
    return any(f" {_norm_words(s)}" in padded for s in q["slugs"] if len(s) > 2)


def _window_sentences(text, sents, spans):
    """
    Which sentences count as 'about this topic' around each mention: the
    mention's own sentence, the question just before it if the page is laid
    out as Q&A, and the next two sentences (details usually follow).

    Sentence-level rather than a fixed number of characters on purpose: FAQ
    pages pack many unrelated answers together, and a character window let a
    word from the neighbouring answer (a "booking" about accessibility, a £
    price about gift vouchers) count as evidence for the wrong topic.
    """
    starts = [a for a, _ in sents]
    idxs = set()
    for s, _e in spans[:MAX_HITS_PER_PAGE]:
        i = max(0, bisect.bisect_right(starts, s) - 1)
        is_q = _sent(text, sents, i).rstrip().endswith("?")
        lo = i
        if not is_q and i > 0 and _sent(text, sents, i - 1).rstrip().endswith("?"):
            lo = i - 1
        idxs.update(range(lo, min(len(sents) - 1, i + 2) + 1))
    return sorted(idxs)


def _eval_question(q, ok_pages):
    per_page = []
    refused = False
    for p in ok_pages:
        text = p["text"]
        spans = []
        for rx in q["mention"]:
            spans += [(m.start(), m.end()) for m in rx.finditer(text)]
        if not spans:
            continue
        spans.sort()
        sents = _sentences(text)
        win = _window_sentences(text, sents, spans)

        sat = {}
        for f in q["facts"]:
            for j in win:
                sent = _sent(text, sents, j)
                if any(rx.search(sent) for rx in f["patterns"]):
                    sat[f["key"]] = _answer_snippet(text, sents, j)
                    break
        if q.get("refusal"):
            # a sentence that both names the topic and refuses it. This is a
            # rule, not understanding - e.g. "dogs are not allowed in the
            # restaurant" would trip it - so the result is flagged for a look.
            for j in win:
                sent = _sent(text, sents, j)
                if (any(rx.search(sent) for rx in q["mention"])
                        and any(rx.search(sent) for rx in _REFUSAL)):
                    refused = True

        first = spans[0]
        fi = max(0, bisect.bisect_right([a for a, _ in sents], first[0]) - 1)
        mention_snip = _clean(_sent(text, sents, fi) + " " +
                              (_sent(text, sents, fi + 1) if fi + 1 < len(sents) else ""))
        per_page.append({
            "page": p, "hits": len(spans), "sat": sat,
            "relevant": _topic_relevant(p, q) or len(spans) >= 3,
            "mention_snippet": mention_snip[:320],
        })

    required = [f for f in q["facts"] if f["required"]]
    if refused:
        # "we can't accommodate dogs" fully answers the pets question
        required = [f for f in required if f["key"] == "policy"]
    optional = [f for f in q["facts"] if not f["required"]]
    result = {"id": q["id"], "short": q["short"], "label": q["label"],
              "high_value": q["high_value"], "found": [], "missing": [],
              "nice_to_have": [], "snippet": "", "source_url": "",
              "other_sources": [], "note": ""}

    if not per_page:
        result["state"] = "not_found"
        result["missing"] = [f["label"] for f in required]
        return result

    found_keys = set()
    for pp in per_page:
        found_keys |= set(pp["sat"])
    best = max(per_page, key=lambda pp: (len(pp["sat"]), pp["relevant"], pp["hits"]))
    result["found"] = [f["label"] for f in q["facts"] if f["key"] in found_keys]
    result["missing"] = [f["label"] for f in required if f["key"] not in found_keys]
    result["nice_to_have"] = [f["label"] for f in optional
                              if f["key"] not in found_keys] if not refused else []
    result["source_url"] = best["page"]["url"]
    result["other_sources"] = [pp["page"]["url"] for pp in per_page
                               if pp is not best][:3]
    first_fact = next((best["sat"][f["key"]] for f in q["facts"]
                       if f["key"] in best["sat"]), None)
    result["snippet"] = first_fact or best["mention_snippet"]
    if refused:
        result["note"] = ("the text appears to say this is not offered - "
                          "check the wording")
    result["_per_page"] = per_page
    result["_found_keys"] = found_keys

    any_relevant = any(pp["relevant"] for pp in per_page)
    if not result["missing"] and any_relevant:
        result["state"] = "answered"
    elif any_relevant:
        result["state"] = "partial"
    else:
        result["state"] = "needs_checking"
    return result


def evaluate(pages, sufficient=True):
    """Pure function over already-fetched pages - the part worth unit-testing."""
    ok_pages = [p for p in pages if p["ok"]]
    results = []
    for q in QUESTIONS:
        r = _eval_question(q, ok_pages)
        if r["state"] == "not_found" and not sufficient:
            r["state"] = "couldnt_check"
        r["state_label"] = STATE_LABELS[r["state"]]
        results.append(r)
    return results


# ------------------------------------------------------------- time parsing

def parse_time(token):
    """'3pm' / '3.30 pm' / '15:00' -> 'HH:MM', or None if ambiguous.
    A bare '3.00' with no am/pm is rejected rather than guessed at."""
    m = re.match(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s?(am|pm)?\s*$", token or "", re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if not ap and not (":" in token and h >= 10):
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _times_for(ok_pages, patterns):
    """[(HH:MM, source_url, snippet)] for every check-in or check-out time found."""
    found = []
    for p in ok_pages:
        text = p["text"]
        for rx in _rx(*patterns):
            got = False
            for m in rx.finditer(text):
                t = parse_time(m.group("t"))
                if t:
                    got = True
                    found.append((t, p["url"], _snippet(text, m.start(), m.end(), 60)))
            if got:
                # The patterns are ordered "keyword then time" before "time
                # then keyword". Once the first form has matched on a page,
                # skip the reversed one: in "Check-in is from 15:00, and
                # check-out is by 11:00" the reversed check-out pattern reads
                # 15:00 as the check-out time. Seen live on a real hotel FAQ.
                break
    return found


# ---------------------------------------------------------------- fact sheet

_PHONE = re.compile(r"(?:\+44\s?\(?0?\)?\s?|0)\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4}")


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _most_common(items):
    counts = {}
    for key, val, src in items:
        counts.setdefault(key, {"n": 0, "val": val, "src": src})["n"] += 1
    if not counts:
        return None
    return max(counts.values(), key=lambda c: c["n"])


def build_fact_sheet(ok_pages, questions, hotel, base, lodging_node=None, location=None):
    """
    Facts a machine could learn from this site, each with the page it came
    from. Also returns conflicts (different values on different pages) and a
    synthesized 'own facts' node so the consistency check against other
    sources works even when the site publishes no structured data.
    """
    rows, conflicts, node = [], [], {}
    lodging_node = lodging_node or {}
    location = location or {}

    if hotel:
        rows.append({"fact": "Name", "value": hotel, "source_url": base,
                     "note": "from the site's own markup"})
        node["name"] = hotel

    # address
    addr = lodging_node.get("address")
    if isinstance(addr, dict):
        addr = ", ".join(str(addr.get(k, "")) for k in
                         ("streetAddress", "addressLocality", "postalCode") if addr.get(k))
    if addr:
        rows.append({"fact": "Address", "value": addr, "source_url": base,
                     "note": "structured data (JSON-LD)"})
        node["address"] = addr
    elif location.get("address"):
        rows.append({"fact": "Address", "value": location["address"], "source_url": base,
                     "note": f"from {location.get('source') or 'the site'}"})
        node["address"] = location["address"]

    # telephone: tel: links are explicit, so prefer those over text patterns
    tel_items = []
    for p in ok_pages:
        for t in p["tels"]:
            if len(_digits(t)) >= 9:
                tel_items.append((_digits(t)[-10:], t, p["url"]))
    best_tel = _most_common(tel_items)
    if lodging_node.get("telephone"):
        rows.append({"fact": "Telephone", "value": str(lodging_node["telephone"]),
                     "source_url": base, "note": "structured data (JSON-LD)"})
        node["telephone"] = str(lodging_node["telephone"])
    elif best_tel:
        val = best_tel["val"].strip()
        if re.fullmatch(r"44\d{9,10}", val):  # tel:441932335700 -> +441932335700
            val = "+" + val
        rows.append({"fact": "Telephone", "value": val,
                     "source_url": best_tel["src"], "note": "a tel: link on the page"})
        node["telephone"] = val

    if not lodging_node.get("telephone") and not best_tel:
        # no tel: link anywhere - fall back to a number written in the footer
        # or near the top of a page, which is weaker evidence, so say so
        text_items = []
        for p in ok_pages:
            for blob in (p.get("footer_text", ""), p["text"][:4000]):
                for m in _PHONE.finditer(blob):
                    text_items.append((_digits(m.group())[-10:], _clean(m.group()), p["url"]))
        txt_tel = _most_common(text_items)
        if txt_tel:
            rows.append({"fact": "Telephone", "value": txt_tel["val"],
                         "source_url": txt_tel["src"], "note": "a number written on the page"})
            node["telephone"] = txt_tel["val"]

    mail = _most_common([(m.lower(), m, p["url"]) for p in ok_pages for m in p["mails"]])
    if mail:
        rows.append({"fact": "Email", "value": mail["val"], "source_url": mail["src"],
                     "note": "a mailto: link on the page"})

    # check-in / check-out, with conflict detection across pages
    for label, key, patterns, nodekey in (
            ("Check-in time", "checkinTime", _CI, "checkinTime"),
            ("Check-out time", "checkoutTime", _CO, "checkoutTime")):
        found = _times_for(ok_pages, patterns)
        ld = parse_time(str(lodging_node.get(key, ""))) if lodging_node.get(key) else None
        if ld:
            found.append((ld, base, "structured data (JSON-LD)"))
        if not found:
            continue
        counts = {}
        for t, src, snip in found:
            counts.setdefault(t, []).append((src, snip))
        top = max(counts, key=lambda t: len(counts[t]))
        src, snip = counts[top][0]
        rows.append({"fact": label, "value": top, "source_url": src,
                     "note": f"{len(counts[top])} mention(s)"})
        node[nodekey] = top
        if len(counts) > 1:
            conflicts.append({
                "fact": label,
                "values": [{"value": t, "source_url": counts[t][0][0]}
                           for t in sorted(counts)],
                "note": "different pages give different times - guests (and AI "
                        "assistants) can't tell which is right",
            })

    # policy snippets: what a reader would learn, with the page it came from
    for q in questions:
        if q["id"] in ("checkin_out",) or q["state"] not in ("answered", "partial"):
            continue
        rows.append({"fact": q["short"], "value": q["snippet"],
                     "source_url": q["source_url"],
                     "note": "answered" if q["state"] == "answered"
                             else "partly answered - missing " + ", ".join(q["missing"])})

    return rows, conflicts, node


# ----------------------------------------------------------------------- run

def run(site, base, hotel="", location=None, progress=None,
        max_pages=MAX_PAGES, budget_s=TIME_BUDGET_S):
    """
    Crawl a bounded set of the hotel's own pages and answer the guest
    questions from them. `site` is site_check.run_site_check()'s output.
    """
    t0 = time.time()
    say = progress or (lambda m: None)

    say("Reading the homepage...")
    home = fetch_page(base)
    sitemap_urls = site.get("sitemap_urls") or []
    targets = select_pages(base, home.get("links", []), sitemap_urls, max_pages)

    say(f"Reading up to {len(targets)} pages to see what guests can learn...")
    pages = [home]
    rest = [u for u in targets if u != base]
    ex = ThreadPoolExecutor(max_workers=6)
    try:
        futs = {ex.submit(fetch_page, u): u for u in rest}
        done, not_done = wait(futs, timeout=max(5, budget_s - (time.time() - t0)))
        for f in done:
            try:
                pages.append(f.result())
            except Exception as e:  # noqa: BLE001
                pages.append({"url": futs[f], "ok": False, "reason": f"error: {e}",
                              "text": "", "tels": [], "mails": [], "h1": [],
                              "title": "", "footer_text": "", "links": []})
        for f in not_done:
            pages.append({"url": futs[f], "ok": False,
                          "reason": "timed out (time budget reached)",
                          "text": "", "tels": [], "mails": [], "h1": [],
                          "title": "", "footer_text": "", "links": []})
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    ok_pages = [p for p in pages if p["ok"]]
    failed = [p for p in pages if not p["ok"]]
    attempted = len(pages)
    sufficient = (len(ok_pages) >= 3 and bool(home.get("ok"))
                  and len(failed) <= 0.5 * max(attempted, 1))

    questions = evaluate(pages, sufficient=sufficient)
    sheet, conflicts, node = build_fact_sheet(
        ok_pages, questions, hotel, base,
        lodging_node=site.get("lodging_node"), location=location)

    for q in questions:  # strip internals before returning
        q.pop("_per_page", None)
        q.pop("_found_keys", None)

    return {
        "pages_attempted": attempted,
        "pages_ok": len(ok_pages),
        "pages_failed": [{"url": p["url"], "reason": p["reason"]} for p in failed],
        "sitemap_total": (site.get("sitemap") or {}).get("url_count", len(sitemap_urls)),
        "evidence_sufficient": sufficient,
        "elapsed_s": round(time.time() - t0, 1),
        "questions": questions,
        "fact_sheet": sheet,
        "conflicts": conflicts,
        "own_facts_node": node,
    }


def coverage_fraction(guest):
    """Share of answerable questions answered, or None if nothing could be judged.
    'Couldn't check' is excluded, so a blocked site is never penalised."""
    judged = [q for q in (guest or {}).get("questions", []) if q["state"] != "couldnt_check"]
    if not judged:
        return None
    return sum(STATE_CREDIT[q["state"]] for q in judged) / len(judged)


if __name__ == "__main__":  # quick manual run: python guest_questions.py <site>
    import json
    import sys
    import site_check

    target = sys.argv[1] if len(sys.argv) > 1 else "brooklandshotelsurrey.com"
    s = site_check.run_site_check(target)
    g = run(s, s["meta"]["base"], progress=print)
    print(json.dumps({k: g[k] for k in
                      ("pages_attempted", "pages_ok", "evidence_sufficient", "elapsed_s")}))
    for q in g["questions"]:
        print(f"  [{q['state_label']:<26}] {q['short']}: "
              f"missing={q['missing']} src={q['source_url']}")
    for r in g["fact_sheet"]:
        print("  FACT", r["fact"], "=", r["value"][:70], "|", r["source_url"])
    print("  CONFLICTS:", g["conflicts"])
