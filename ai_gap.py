"""
Who the AI recommends instead, which pages it cites, and what the evidence shows about the difference.

Built from the answers the audit already collects (ai_sample items and their extracted hotel lists, ai_insights). For each question the assistant was asked it reports:

  1. THE GAP: whether the hotel was named (n of m answers) and, if not, the hotels the assistant named instead, with how many answers named each and the reason the assistant itself gave.
  2. THE ARTICLES: the third-party pages the assistant cited for those questions. Editorial pages (travel media, tourism boards, guides) are read politely (robots.txt respected, honest user agent, one
     fetch each, a hard time limit) to see whether they mention the hotel and which rivals. An outreach suggestion is made only for an editorial list that is not sponsored, names rivals, and does
     not include the hotel. Review sites and booking platforms are never read.
  3. THE COMPARISON: the top rivals' official websites are found (the map's website tag, a cited page, or one web search) and each is VERIFIED before use (its homepage names the hotel and the town).
     Their pages are read politely and compared with the hotel's own on stars, size and facilities, using the same rules as the rest of the audit.

What it does not do: it never says WHY an assistant chose a hotel. It lists observed differences (what the assistant said, which sources name a rival and not the hotel, which facilities a rival's pages
state more strongly) and says they are observations, not causes. One assistant, a handful of answers, one day: counts are shown as 'n of m answers', never as 'consistently' unless every answer agreed
and there were at least two. Nothing here fabricates a source: every URL is one the assistant cited, one the site itself publishes, or one verified on its page.
"""

import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import ai_insights as ains
import ai_sample
import competitors
import evidence
import insight_content as ic
import rivals
import textutil

SOURCE = "Competitors the assistant named instead, the pages it cited, and what the evidence shows"
MAX_RIVALS_PER_MARKET = 4
MAX_ARTICLES = 8
MAX_RIVAL_SITES = 3
DEADLINE_S = 45
SEARCH_BUDGET_USD = 0.20
EDITORIAL = ("Travel media", "Tourism board", "Other")
_LIST_TITLE = re.compile(r"\b(?:best|top|where to stay|guide|hotels? (?:in|near)|\d+\s+(?:best|top|great)|recommended|favou?rite|round-?up)\b", re.I)
_CONTACT = re.compile(r"/(?:contact|contact-us|about|about-us|write-for-us|submit|advertis\w*|pitch\w*|press|media-kit|work-with-us)(?:/|\.|$)", re.I)
_AFFILIATE = re.compile(r"affiliate|we may earn|earn a commission|commission from|paid links|sponsored links", re.I)
_URL = re.compile(r"https?://[^\s)\]>\"'<]+")
LIMITS = [
    "One assistant with web search was asked a handful of questions on one day. 'n of m answers' counts answers, not a market ranking, and the assistant's choices vary between runs.",
    "A cited page shows what the assistant read, not why it chose a hotel. Observed differences are leads to investigate, never proven causes.",
    "Only pages that robots.txt allows were read, and only editorial pages: review sites and booking platforms are not read. A page behind a paywall or built with scripts may show as unread.",
    "A rival's website is used only when its homepage was verified to be that hotel in that town; otherwise no comparison is made for it.",
]
FACILITY_KEYS = ("spa", "pool", "restaurant", "meeting_rooms", "weddings", "airport_transfer", "ev", "family", "pets", "accessible", "gym", "parking")


# ------------------------------------------------------------------ 1. the gap

def _resolver(items, extracted, hotel, city):
    """One decision, for the whole audit, about which names are one hotel: name -> (group key, display name, other names, uncertain). See rivals.resolve."""
    by_answer = []
    for it in items:
        if it.get("kind") == "direct" or it["id"] not in extracted:
            continue
        by_answer.append((it["id"], [h["name"] for h in extracted[it["id"]] if not ai_sample.mentioned(h["name"], hotel)]))
    out = {}
    for g in rivals.resolve(by_answer, city):
        for n in g["names"]:
            out[n] = (g["key"], g["name"], [x for x in g["names"] if x != g["name"]], g["uncertain"])
    return out


def market_rivals(answer_ids, extracted, hotel, resolver=None, city="", hotel_tier=None):
    """
    The hotels named in the answers to ONE question (repeats together), other than the hotel, each placed on the category ladder:
    [{name, aliases, uncertain, answers, of, best_rank, reasons, ratings, sentiment, themes, stars_said, tier, relation}], most-named first.
    """
    resolver = resolver or _resolver([{"id": a, "kind": "x"} for a in answer_ids], extracted, hotel, city)
    rows = {}
    for aid in answer_ids:
        for h in extracted.get(aid) or []:
            if ai_sample.mentioned(h["name"], hotel):
                continue
            key, display, aliases, unc = resolver.get(h["name"], (ains.canon(h["name"]), h["name"], [], False))
            r = rows.setdefault(key, {"name": display, "aliases": aliases, "uncertain": unc, "answers": set(), "ranks": [], "reasons": [], "ratings": [], "sent": [], "themes": {}, "stars": []})
            r["answers"].add(aid)
            r["sent"].append(h.get("sentiment") or "neutral")
            if h.get("rank"):
                r["ranks"].append(h["rank"])
            if h.get("stars"):
                r["stars"].append(h["stars"])
            for t in h.get("themes") or []:
                r["themes"][t] = r["themes"].get(t, 0) + 1
            if h.get("reason") and h["reason"] not in r["reasons"]:
                r["reasons"].append(h["reason"])
            if h.get("rating") and h["rating"] not in r["ratings"]:
                r["ratings"].append(h["rating"])
    out = []
    for r in rows.values():
        stars = max(set(r["stars"]), key=r["stars"].count) if r["stars"] else None
        tier = rivals.tier_of(r["name"], stars)
        out.append({"name": r["name"], "aliases": r["aliases"], "uncertain": r["uncertain"], "answers": len(r["answers"]), "of": len(answer_ids), "best_rank": min(r["ranks"]) if r["ranks"] else None,
                    "reasons": r["reasons"][:2], "ratings": r["ratings"][:2], "sentiment": ains.sentiment_of(r["sent"]).get("sentiment"), "themes": r["themes"], "stars_said": stars,
                    "tier": tier, "relation": rivals.relation(hotel_tier, tier["key"])})
    out.sort(key=lambda r: (-r["answers"], r["best_rank"] or 99, r["name"]))
    return out


def markets(items, extracted, hotel, city="", hotel_tier=None):
    """
    One record per question put to the assistant (never the 'about the hotel' ones): whether the hotel was named, and who was named. `rivals` are the COMPARABLE hotels (same category, one step either way,
    or category not known); `other_category` are hotels in a higher or lower category, which are shown but never make a gap.
    """
    resolver = _resolver(items, extracted, hotel, city)
    out = []
    for g in ai_sample.by_question([i for i in items if i.get("kind") != "direct"]):
        ids = [a["id"] for a in g["answers"] if a.get("answer")]
        if not ids:
            continue
        every = market_rivals(ids, extracted, hotel, resolver, city, hotel_tier)
        rv = [r for r in every if r["relation"] in rivals.COMPARABLE]
        other = [r for r in every if r["relation"] not in rivals.COMPARABLE]
        status = "named" if g["named"] == g["of"] and g["of"] else "sometimes" if g["named"] else "not_named"
        top = rv[0] if rv else None
        out.append({"qid": g["qid"], "kind": g["kind"], "question": g["text"], "angle": g.get("angle"), "why": g.get("why"), "priority": next((i.get("priority") for i in items if (i.get("qid") or i["id"]) == g["qid"]), None),
                    "named": g["named"], "of": g["of"], "status": status, "best_position": g["best_position"], "answer_ids": ids, "rivals": rv[:MAX_RIVALS_PER_MARKET], "other_category": other[:4],
                    "gap": status != "named" and bool(rv),
                    "consistent": bool(top and top["of"] >= 2 and top["answers"] == top["of"] and g["named"] == 0),
                    "note": ("The hotels named are in a different category from this hotel, so the hotel not being among them is not a competitive gap." if status != "named" and other and not rv else "")})
    return out


# ----------------------------------------------------------------- 2. articles

def _sentence_with(text, name):
    m = re.search(re.escape(name), text, re.I) or re.search(re.escape(ains.canon(name)), evidence.fold(text))
    if not m:
        return ""
    return textutil.sentence_of(text, m.start(), m.end(), limit=260)


def cited_pages(items, gap_markets, own_domain, brand_domains):
    """The third-party pages the assistant cited (or searched) for the questions where the hotel was not always named: [{url, title, domain, kind, cited, questions, passage}], most-cited first."""
    ids = {a for m in gap_markets for a in m["answer_ids"]}
    qof = {a: m["qid"] for m in gap_markets for a in m["answer_ids"]}
    pages = {}
    for it in items:
        if it["id"] not in ids:
            continue
        for pg in it.get("pages") or []:
            u = pg.get("url") or ""
            if not u:
                continue
            d = re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()
            r = pages.setdefault(u, {"url": u, "title": pg.get("title") or "", "domain": d, "kind": ains.source_kind(d, own_domain, brand_domains), "cited": 0, "questions": set(), "passage": ""})
            r["questions"].add(qof[it["id"]])
            r["title"] = r["title"] or pg.get("title") or ""
            if pg.get("cited"):
                r["cited"] += 1
                r["passage"] = r["passage"] or pg.get("cited_text") or ""
    out = list(pages.values())
    for r in out:
        r["questions"] = sorted(r["questions"])
    out.sort(key=lambda r: (-r["cited"], -len(r["questions"]), r["domain"], r["url"]))
    return out


def _read_article(url, reader):
    """Read one page politely. -> {read: 'ok'|'robots'|'unread', why, text, title, publisher, published, sponsored, press_release}. Never raises."""
    try:
        r = reader(url)
    except Exception as e:  # noqa: BLE001
        return {"read": "unread", "why": f"could not be read ({type(e).__name__})"}
    f, pg = r.get("fetch") or {}, r.get("page") or {}
    if f.get("robots_blocked"):
        return {"read": "robots", "why": "the site's robots.txt asks automated tools not to read this page, so it was not read"}
    if not f.get("ok") or not pg or len(pg.get("text") or "") < 300:
        return {"read": "unread", "why": f.get("error") or "no readable text (paywall, or built with scripts)"}
    return {"read": "ok", "why": "", "text": pg["text"], "title": pg.get("title") or "", "publisher": pg.get("publisher") or "", "published": pg.get("published"),
            "sponsored": bool(pg.get("sponsored_cue")), "press_release": bool(pg.get("press_release_cue")), "links": pg.get("links") or [], "sections_n": len(pg.get("sections") or []),
            "author": pg.get("author") or ""}


def _contact_url(links, domain):
    """The publication's own contact, about or write-for-us page, if the article links to one on its own site. Only surfaced for the hotel to use: nothing is ever sent."""
    host = (domain or "").lower().removeprefix("www.")
    for l in links or []:
        p = urllib.parse.urlparse(l)
        if (p.netloc.lower().removeprefix("www.") == host or p.netloc.lower().endswith("." + host)) and _CONTACT.search(p.path):
            return l
    return ""


def _age_months(published):
    m = re.match(r"(\d{4})-(\d{2})", str(published or ""))
    if not m:
        return None
    now = time.gmtime()
    return (now.tm_year - int(m.group(1))) * 12 + (now.tm_mon - int(m.group(2)))


def articles(pages, rivals_all, hotel, city, reader, deadline_s, limit=MAX_ARTICLES):
    """
    Read the editorial pages the assistant cited and say, for each, whether it names the hotel and which rivals. -> [{url, title, domain, kind, cited, questions, read, hotel_in, rivals_in, lists_hotels,
    rival_sentence, hotel_sentence, sponsored, published, opportunity, note}]. Review sites, booking platforms, social sites, maps and the hotel's own pages are listed but not read.
    """
    cand = [p for p in pages if p["kind"] in EDITORIAL][:limit]
    skipped = [p for p in pages if p["kind"] not in EDITORIAL][:6]
    end = time.time() + deadline_s
    names = sorted({n for n in rivals_all if n})

    def one(p):
        if time.time() > end:
            return p, {"read": "unread", "why": "the time limit for reading pages was reached"}
        return p, _read_article(p["url"], reader)
    with ThreadPoolExecutor(max_workers=4) as ex:
        read = list(ex.map(one, cand))
    out = []
    for p, a in read:
        row = {**{k: p[k] for k in ("url", "title", "domain", "kind", "cited", "questions", "passage")}, "read": a["read"], "note": a.get("why", ""), "hotel_in": None, "rivals_in": [],
               "lists_hotels": None, "rival_sentence": "", "hotel_sentence": "", "sponsored": False, "published": None, "opportunity": False,
               "contact_url": "", "affiliate": None, "age_months": None, "hotels_listed": None, "byline": None}
        if a["read"] == "ok":
            text = a["text"]
            row["title"] = a.get("title") or row["title"]
            row["sponsored"], row["published"] = a["sponsored"] or a["press_release"], (str(a["published"])[:10] if a.get("published") else None)
            row["hotel_in"] = ai_sample.mentioned(text, hotel, city)
            low = evidence.fold(text)
            found = [n for n in names if ains.appears(n, text)]
            row["rivals_in"] = sorted(found, key=lambda n: low.find(evidence.fold(n)) if evidence.fold(n) in low else low.find(ains.canon(n)))[:6]      # in the order the page names them
            row["lists_hotels"] = len(row["rivals_in"]) >= 3 or (bool(_LIST_TITLE.search(row["title"])) and len(row["rivals_in"]) >= 2)
            row["rival_sentence"] = _sentence_with(text, row["rivals_in"][0]) if row["rivals_in"] else ""
            row["hotel_sentence"] = _sentence_with(text, hotel) if row["hotel_in"] else ""
            row["contact_url"] = _contact_url(a.get("links"), p["domain"])
            row["affiliate"] = bool(_AFFILIATE.search(text[:3000] + " " + text[-2500:]))
            row["age_months"] = _age_months(a.get("published"))
            row["hotels_listed"] = max(a.get("sections_n") or 0, len(row["rivals_in"]))
            row["byline"] = bool(a.get("author") or a.get("publisher"))
            row["opportunity"] = bool(row["lists_hotels"] and not row["hotel_in"] and row["rivals_in"] and not row["sponsored"])
            if row["sponsored"]:
                row["note"] = "this page looks sponsored or like a republished press release, so it is not treated as an editorial opportunity"
        out.append(row)
    for p in skipped:
        out.append({**{k: p[k] for k in ("url", "title", "domain", "kind", "cited", "questions", "passage")}, "read": "not_read", "note": f"{p['kind'].lower()}: not read by this audit (platform terms)",
                    "hotel_in": None, "rivals_in": [], "lists_hotels": None, "rival_sentence": "", "hotel_sentence": "", "sponsored": False, "published": None, "opportunity": False})
    return out


# ------------------------------------------------------ 3. rivals and comparison

def _tokens(name, city=""):
    place = set(re.split(r"[^a-z0-9]+", evidence.fold((city or "").split(",")[0])))
    return [t for t in re.split(r"[^a-z0-9]+", evidence.fold(name)) if len(t) >= 4 and t not in ai_sample._GENERIC and t not in place]


def _map_site(name, osm_ctx):
    c = ains.canon(name)
    for h in (osm_ctx or {}).get("hotels", []):
        site = (h.get("tags") or {}).get("website")
        hc = ains.canon(h.get("name") or "")
        if site and c and hc and (hc == c or (len(c.split()) >= 2 and (c in hc or hc in c))):
            return site if "//" in site else "https://" + site
    return None


def _domain_guess(name, pages, city):
    toks = _tokens(name, city)
    if not toks:
        return None
    for p in pages:
        flat = re.sub(r"[^a-z0-9]", "", p["domain"].split(":")[0])
        if p["kind"] in ("Other",) and (all(t in flat for t in toks) or (max(toks, key=len) in flat and len(max(toks, key=len)) >= 6)):
            return "https://" + p["domain"]
    return None


def verify_site(url, name, city, fetch):
    """Is this homepage really that hotel in that town? -> (verified, why). The page must name the hotel (every distinctive word of its name in the title, heading or opening text) and the town."""
    pg = fetch(url)
    if not pg or not pg.get("ok"):
        return False, "the homepage could not be read"
    head = evidence.fold(" ".join([pg.get("title", "")] + list(pg.get("h1", [])[:2]) + [pg.get("text", "")[:1500]]))
    toks = _tokens(name, city)
    place = evidence.fold((city or "").split(",")[0])
    where = evidence.fold(" ".join([pg.get("title", "")] + list(pg.get("h1", [])) + [(pg.get("signals") or {}).get("meta_description", ""), pg.get("text", "")[:6000], pg.get("footer_text", "")]))
    if toks and all(t in head for t in toks) and (not place or place in where):
        return True, "its homepage names the hotel and the town"
    return False, "its homepage does not clearly name this hotel in this town"


_SEARCH_SYSTEM = ("You find a hotel's official website. Search the web. Reply with the single address of the hotel's own page (the hotel's website, or its brand's page for THIS hotel) and nothing else. "
                  "Reply NONE if you are not sure. Never reply with a booking site, review site or directory.")


def _search_site(client, model, name, city):
    """One web search for a hotel's official site -> (candidate urls, cost). The candidates are only candidates: each is verified on its own homepage before use."""
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    resp = client.messages.create(model=model, max_tokens=500, system=_SEARCH_SYSTEM, tools=[{**ai_sample.SEARCH_TOOL, "max_uses": 2}],
                                  messages=[{"role": "user", "content": f"The official website of the hotel \"{name}\" in {city.split(',')[0]}."}], **extra)
    answer, _domains, searches, tin, tout = ai_sample.parse_response(resp)
    urls = [u.rstrip(".,;") for u in _URL.findall(answer or "")]
    urls += [p["url"] for p in ai_sample.parse_sources(resp, limit=5) if all(t in evidence.fold(p["url"] + " " + p.get("title", "")) for t in _tokens(name, city)[:2])]
    out, seen = [], set()
    for u in urls:
        p = urllib.parse.urlparse(u)
        root = f"{p.scheme}://{p.netloc}/"
        if p.scheme in ("http", "https") and root not in seen and ains.source_kind(p.netloc.lower().removeprefix("www.")) == "Other":
            seen.add(root)
            out.append(u if u.count("/") > 3 else root)
    return out[:3], ai_sample.cost_usd(model, tin, tout, searches)


def find_rival_site(name, city, osm_ctx, pages, fetch, polite_allowed, client=None, model=None, budget_left=0.0):
    """-> {"url", "via", "verified", "why", "cost"}. Never raises. The map's website tag, then a cited page's domain, then one web search; every candidate is verified on its homepage."""
    cost = 0.0
    tried = []
    for via, url in (("the map's website entry", _map_site(name, osm_ctx)), ("a page the assistant cited", _domain_guess(name, pages, city))):
        if url:
            tried.append((via, url))
    if client is not None and budget_left > 0.03 and not tried:
        try:
            cands, cost = _search_site(client, model or ai_sample.MODEL_DEFAULT, name, city)
            tried += [("a web search", u) for u in cands]
        except Exception:  # noqa: BLE001
            pass
    why = "no official website could be found"
    for via, url in tried:
        if not polite_allowed(url):
            why = "its site's robots.txt asks automated tools not to read it"
            continue
        ok, w = verify_site(url, name, city, fetch)
        if ok:
            return {"url": url, "via": via, "verified": True, "why": w, "cost": cost}
        why = f"{via} gave {urllib.parse.urlparse(url).netloc}, but {w}"
    return {"url": None, "via": None, "verified": False, "why": why, "cost": cost}


def _level_word(lv):
    return {"strong": "describe it in detail", "some": "mention it"}.get(lv, "do not mention it")


_RANK = {"strong": 2, "some": 1}


def compare(own_pages, base, hotel, rivals, fetch, polite_allowed):
    """
    Read each verified rival's homepage and up to two pages about facilities, politely, and profile them like the hotel's own pages (stars, size, facilities).
    -> {"own": {...}, "rivals": [{name, url, pages_read, stars, rooms, facilities, levels}], "rows": [{facility, hotel, rivals: {name: level}}], "differences": [str]}
    """
    own = competitors.profile(own_pages, base, hotel)
    out = {"own": {"stars": own["stars"], "rooms": own["rooms"], "facilities": own["facilities"], "levels": {k: own["features"].get(k) for k in FACILITY_KEYS}}, "rivals": [], "rows": [], "differences": []}
    slugs = ("spa", "wellness", "meeting", "conference", "rooms", "dining", "restaurant", "facilities", "pool", "location")

    def one(r):
        if not r.get("url"):
            return r, []
        return r, competitors.read_rival({"url": r["url"], "name": r["name"]}, fetch, slugs)
    with ThreadPoolExecutor(max_workers=3) as ex:
        read = list(ex.map(one, rivals))
    for r, pages in read:
        if not pages:
            continue
        rp = competitors.profile(pages, r["url"], r["name"], {})
        out["rivals"].append({"name": r["name"], "url": r["url"], "pages_read": len(pages), "stars": rp["stars"], "rooms": rp["rooms"], "facilities": rp["facilities"],
                              "levels": {k: rp["features"].get(k) for k in FACILITY_KEYS}})
    for k in FACILITY_KEYS:
        own_lv = out["own"]["levels"].get(k)
        per = {r["name"]: r["levels"].get(k) for r in out["rivals"]}
        if own_lv in ("some", "strong") or any(v in ("some", "strong") for v in per.values()):
            out["rows"].append({"facility": (ic.lexicon.FEATURES.get(k) or (k,))[0], "key": k, "hotel": own_lv, "rivals": per})
    for r in out["rivals"]:
        if own["stars"] and r["stars"] and r["stars"] != own["stars"]:
            out["differences"].append(f"{r['name']} states {r['stars']}-star; the hotel's pages state {own['stars']}-star.")
        if own["rooms"] and r["rooms"] and (r["rooms"] / own["rooms"] >= 2 or r["rooms"] / own["rooms"] <= 0.5):
            out["differences"].append(f"{r['name']} states {r['rooms']} rooms; the hotel's pages state {own['rooms']}.")
        for row in out["rows"]:
            lv = row["rivals"].get(r["name"])
            if _RANK.get(lv, 0) > _RANK.get(row["hotel"], 0):
                out["differences"].append(f"{r['name']}'s pages {_level_word(lv)} ({row['facility'].lower()}); the hotel's pages {_level_word(row['hotel'])}.")
    return out


# ------------------------------------------------------------- criteria and observations

# what the hotel's own pages can show for each reason an assistant gives: ic.features / ic.intents keys, and a phrase to look for
THEME_EVIDENCE = {
    "location": {"rx": r"minutes?\b[^.]{0,40}(?:walk|from)|steps from|next to|opposite|heart of|close to|\bnear\b|\bkm\b"},
    "views_terrace": {"rx": r"rooftop|roof terrace|terrace|panoramic|\bviews?\b|garden|courtyard"},
    "spa_wellness": {"features": ("spa", "pool", "gym")},
    "meetings_events": {"features": ("meeting_rooms",), "intents": ("meetings",)},
    "dining": {"features": ("restaurant", "bar"), "rx": r"michelin|chef|brasserie"},
    "design_style": {"rx": r"boutique|design|stylish|contemporary|art deco|interiors?"},
    "luxury_service": {"intents": ("luxury",), "rx": r"concierge|butler|personali[sz]ed|bespoke"},
    "value": {"rx": r"best (?:rate|price)|great value|good value|affordable|price guarantee"},
    "family": {"features": ("family",)},
    "awards": {"rx": r"award|winner|michelin|travellers['\u2019] choice|recogni[sz]ed"},
    "transport_access": {"features": ("airport_transfer",), "rx": r"metro|station|airport|\btrain\b|\btram\b|\bRER\b"},
    "quiet_historic": {"rx": r"historic|heritage|quiet|peaceful|character|landmark"},
    "sustainability": {"rx": r"sustainab|eco-?label|green key|eco-?friendly|ecocertified"},
    "pets_accessibility": {"features": ("pets", "accessible")},
    "breakfast": {"rx": r"breakfast|buffet"},
}


def hotel_theme_states(own_pages, base, hotel):
    """For each reason an assistant gives, what the hotel's OWN pages show: {theme: {"state": strong|mentioned|not_found|not_assessed, "url", "snippet"}}. 'not_found' means not found on the pages read."""
    out = {}
    if not own_pages:
        return {t: {"state": "not_assessed", "url": "", "snippet": ""} for t in ains.THEMES}
    site = ic.Site(own_pages, base, hotel, "")
    feat = {f["key"]: f["level"] for f in ic.features(site)}
    ints = {i["key"]: i["level"] for i in ic.intents(site)}
    for theme in ains.THEMES:
        ev = THEME_EVIDENCE.get(theme)
        if not ev:
            out[theme] = {"state": "not_assessed", "url": "", "snippet": ""}          # ratings and reviews are outside the hotel's own pages
            continue
        lv = max([{"strong": 2, "some": 1}.get(feat.get(k), 0) for k in ev.get("features", ())] + [{"strong": 2, "some": 1}.get(ints.get(k), 0) for k in ev.get("intents", ())] + [0])
        hits = site.find(re.compile(ev["rx"], re.I)) if ev.get("rx") else []
        state = "strong" if lv == 2 or len(hits) >= 2 else "mentioned" if lv == 1 or hits else "not_found"
        top = hits[0] if hits else None
        out[theme] = {"state": state, "url": top["page"]["url"] if top else "", "snippet": top["snippet"][:200] if top else ""}
    return out


def criteria(market, extracted, hotel_states):
    """
    Why the assistant named the comparable hotels, as the reasons it gave (a fixed list of themes) that recur across the hotels named for this question, set beside what the hotel's own pages show for each.
    -> [{theme, label, rivals, count, quotes, hotel: {state, url, snippet}}], the most recurrent first. A reason given for a single hotel once is not a pattern and is left out.
    """
    by_theme = {}
    for r in market.get("rivals") or []:
        for t, n in (r.get("themes") or {}).items():
            d = by_theme.setdefault(t, {"rivals": [], "count": 0, "quotes": []})
            d["rivals"].append(r["name"])
            d["count"] += n
            if r.get("reasons") and r["reasons"][0] not in d["quotes"]:
                d["quotes"].append(r["reasons"][0])
    rows = []
    for t, d in by_theme.items():
        if len(d["rivals"]) >= 2 or d["count"] >= 2:
            rows.append({"theme": t, "label": ains.THEMES[t], "rivals": d["rivals"][:4], "count": d["count"], "quotes": d["quotes"][:2], "hotel": (hotel_states or {}).get(t) or {"state": "not_assessed", "url": "", "snippet": ""}})
    rows.sort(key=lambda r: (-len(r["rivals"]), -r["count"], r["theme"]))
    return rows[:5]


def observations(market, arts, comp, crit=None):
    """The evidence for ONE market where the hotel was not (always) named, as observations that name their source. Never a cause."""
    obs = []
    for r in market["rivals"][:3]:
        if r["reasons"]:
            obs.append({"kind": "assistant", "text": f"The assistant named {r['name']} in {r['answers']} of {r['of']} answers and gave this reason: {r['reasons'][0]}.", "urls": []})
    for c in crit or []:
        st, who = c["hotel"]["state"], ", ".join(c["rivals"][:3])
        if st == "not_found":
            obs.append({"kind": "criterion", "theme": c["theme"], "text": f"{who} were recommended for {c['label']}. The hotel's own pages do not mention it: either the hotel does not offer it, or it is not stated (only the hotel knows which).", "urls": []})
        elif st == "mentioned":
            obs.append({"kind": "criterion", "theme": c["theme"], "text": f"{who} were recommended for {c['label']}. The hotel's pages mention it only in passing: \u201c{c['hotel']['snippet'][:140]}\u201d.", "urls": [c["hotel"]["url"]] if c["hotel"]["url"] else []})
        elif st == "strong":
            obs.append({"kind": "criterion", "theme": c["theme"], "text": f"{who} were recommended for {c['label']}. The hotel's own pages already state it clearly (\u201c{c['hotel']['snippet'][:140]}\u201d), so the difference is more likely in the evidence outside the hotel's site.",
                        "urls": [c["hotel"]["url"]] if c["hotel"]["url"] else []})
    mine = [a for a in arts if market["qid"] in a["questions"] and a["read"] == "ok"]
    missing = [a for a in mine if a["rivals_in"] and a["hotel_in"] is False]
    present = [a for a in mine if a["hotel_in"]]
    if missing:
        obs.append({"kind": "source", "text": f"{len(missing)} of the {len(mine)} editorial page(s) the assistant cited for this question name {', '.join(sorted({n for a in missing for n in a['rivals_in']})[:3])} and do not mention the hotel.",
                    "urls": [a["url"] for a in missing[:3]]})
    if present:
        obs.append({"kind": "source", "text": f"{len(present)} cited page(s) do mention the hotel, so the assistant had it available: {', '.join(a['domain'] for a in present[:3])}.", "urls": [a["url"] for a in present[:3]]})
    rival_names = {r["name"] for r in market["rivals"]}
    for d in (comp or {}).get("differences", []):
        if any(n in d for n in rival_names):
            obs.append({"kind": "facility", "text": d, "urls": []})
    return obs


def investigate(market, obs):
    """Steps that follow from the observations, each conditional: look, compare, then decide. Nothing is promised."""
    steps = []
    kinds = {o["kind"] for o in obs}
    top = ", ".join(r["name"] for r in market["rivals"][:2])
    crit = [o for o in obs if o["kind"] == "criterion"]
    weak = [o for o in crit if "do not mention it" in o["text"] or "only in passing" in o["text"]]
    strong = [o for o in crit if "already state it clearly" in o["text"]]
    if weak:
        steps.append("For each reason listed above that the hotel's pages do not state: if the hotel offers it, state it plainly (what, how many, when, cost) on the page it belongs on; if it does not, there is nothing to fix, it is a real difference between the hotels.")
    if strong:
        steps.append("Where the hotel's own pages already state the reason, look outside the site: the pages the assistant cited and the hotel's listings, to see whether they carry the same fact.")
    if "source" in kinds:
        steps.append("Open the cited pages listed here and check whether the hotel is described there; where a relevant editorial list omits it, decide whether the hotel genuinely belongs in it.")
    if "facility" in kinds:
        steps.append("Compare the facilities noted here with the hotel's own pages, and state any the hotel really has as plainly as the rival does.")
    steps.append(f"Look at how {top} describe themselves and which independent sources feature them, and compare that with what the hotel's pages and outside sources say.")
    steps.append("Ask the same question again in a few weeks: one assistant on one day is a sample, and a gap that persists is worth more than one that does not.")
    return steps


# ------------------------------------------------------------------------ run

def run(ai, ins, ctx, *, api_key=None, model=None, client=None, reader=None, fetch=None, polite_allowed=None, deadline_s=DEADLINE_S, budget_usd=SEARCH_BUDGET_USD):
    """
    ai: the ai_sample envelope; ins: the ai_insights envelope (with 'extracted_answers'); ctx: {"hotel","city","own_domain","brand_domains","own_pages","base","osm_ctx"}.
    -> envelope {"status","reason","markets","gaps","articles","opportunities","rivals","comparison","observations","limits","cost_usd"}. Never raises.
    """
    def env(status, reason="", **kw):
        return {"source": SOURCE, "status": status, "reason": reason, "markets": [], "gaps": [], "articles": [], "opportunities": [], "rivals": [], "comparison": None, "observations": {},
                "limits": LIMITS, "cost_usd": 0.0, **kw}

    if not ai or ai.get("status") != "ok" or not ai.get("items"):
        return env("unavailable", "There were no sampled answers to analyse.")
    extracted = (ins or {}).get("extracted_answers")
    if not extracted:
        return env("unavailable", "The answers could not be broken down into the hotels they name, so who was named instead cannot be shown.")
    hotel, city = ctx["hotel"], ctx.get("city", "")
    ms = markets(ai["items"], extracted, hotel, city, ctx.get("hotel_tier"))
    gaps = [m for m in ms if m["gap"]]
    out = env("ok", "" if gaps else ("The hotel was named in every answer to every question, so there is no gap to analyse." if all(m["status"] == "named" for m in ms) else
                                      "The hotel was not named in some answers, but only hotels in a different category were: that is not a competitive gap."),
              markets=ms, gaps=[m["qid"] for m in gaps], hotel_tier=ctx.get("hotel_tier"), chain=bool(ctx.get("brand_domains")))
    if not gaps:
        return out
    if reader is None:
        import polite
        reader = polite.read
    if fetch is None:
        import guest_questions
        fetch = guest_questions.fetch_page
    if polite_allowed is None:
        import polite
        polite_allowed = polite.allowed
    pages = cited_pages(ai["items"], gaps, ctx.get("own_domain", ""), tuple(ctx.get("brand_domains") or ()))
    rival_names = []
    for m in gaps:
        for r in m["rivals"]:
            if r["name"] not in rival_names:
                rival_names.append(r["name"])
    t0 = time.time()
    arts = articles(pages, rival_names, hotel, city, reader, max(8, deadline_s * 0.5))
    out["articles"] = arts
    out["opportunities"] = [a["url"] for a in arts if a["opportunity"]]

    # the rivals the assistant named most across the questions where the hotel was missing
    tally = {}
    for m in gaps:
        for r in m["rivals"]:
            t = tally.setdefault(r["name"], {"name": r["name"], "answers": 0, "markets": []})
            t["answers"] += r["answers"]
            t["markets"].append(m["qid"])
    top = sorted(tally.values(), key=lambda t: (-t["answers"], t["name"]))[:MAX_RIVAL_SITES]
    cost = 0.0
    model = model or ai_sample.MODEL_DEFAULT
    if client is None and api_key:
        try:
            client = ai_sample._make_client(api_key, timeout=60.0)
        except Exception:  # noqa: BLE001
            client = None
    rivals = []
    for t in top:
        if time.time() - t0 > deadline_s:
            rivals.append({**t, "url": None, "verified": False, "via": None, "why": "the time limit was reached before its website could be looked for"})
            continue
        f = find_rival_site(t["name"], city, ctx.get("osm_ctx"), pages, fetch, polite_allowed, client=client, model=model, budget_left=budget_usd - cost)
        cost += f.pop("cost", 0.0)
        rivals.append({**t, **f})
    out["rivals"] = rivals
    verified = [r for r in rivals if r["verified"]]
    comp = compare(ctx.get("own_pages") or [], ctx.get("base", ""), hotel, verified, fetch, polite_allowed) if verified and ctx.get("own_pages") else None
    out["comparison"] = comp
    states = hotel_theme_states(ctx.get("own_pages") or [], ctx.get("base", ""), hotel)
    out["criteria"] = {m["qid"]: criteria(m, extracted, states) for m in gaps}
    out["observations"] = {m["qid"]: observations(m, arts, comp, out["criteria"][m["qid"]]) for m in gaps}
    out["investigate"] = {m["qid"]: investigate(m, out["observations"][m["qid"]]) for m in gaps}
    out["cost_usd"] = round(cost, 5)
    if not verified:
        out["reason"] = "None of the rivals' official websites could be found and verified, so their pages were not compared; the assistant's own words and the cited pages are shown."
    return out
