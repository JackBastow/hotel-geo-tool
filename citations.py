"""
What the assistant cites when it names the hotel, ranked by how often each source came up, and what that says about booking direct versus through an agent.

For every answer the audit holds which sources the assistant used (the pages it cited and the sites its searches returned). This module counts them where it matters most:

  ranking()            the answers that NAMED the hotel: which sites came up, in how many of those answers, which pages, and how often the same site came up in the answers that did NOT name the hotel.
                       (When the hotel was never named, the same ranking is given for all answers and says so: it then shows what assistants rely on in the hotel's market.) A second ranking is for the answers
                       to the questions asked ABOUT the hotel by name, which show where the assistant gets its facts about it.
  by_kind              the same counts by kind of source: the hotel's own website, booking and comparison sites (the agents that charge commission), review sites, travel media, tourism boards, forums...
  direct_findings()    the facts the assistant took from an agent's page (a rating, a price, a cancellation rule, a distance, breakfast, parking, a facility) that the hotel's OWN pages do not state, and whether the
                       own site says why booking direct is better. These are the concrete reasons the assistant leans on an agent instead of the hotel's site.

Counts are answers in one sample from one assistant: they show what that assistant used, never what a traveller does or what a fix would earn.
"""

import re
import urllib.parse

import ai_insights as ains
import textutil

OTA = "Booking and comparison site"
OWN = ("The hotel's own website", "The hotel's brand website")
TOP_ROWS = 12


def _dom(url):
    h = urllib.parse.urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _answers(items):
    return [i for i in items or [] if i.get("answer") and i.get("kind") != "direct" and i.get("mentioned") is not None]


def _sources_of(item):
    """-> (cited domains, domains that came up at all (cited or returned by a search)), and the page rows the assistant cited."""
    pages = item.get("pages") or []
    cited = {_dom(p["url"]) for p in pages if p.get("cited") and p.get("url")}
    seen = set(cited) | {_dom(p["url"]) for p in pages if p.get("url")} | {str(d).lower().removeprefix("www.") for d in item.get("domains") or []}
    return cited, {d for d in seen if d}, pages


def _rank(group, others, own_domain, brand_domains):
    rows = {}
    for it in group:
        cited, seen, pages = _sources_of(it)
        for d in seen:
            r = rows.setdefault(d, {"domain": d, "kind": ains.source_kind(d, own_domain, brand_domains), "came_up": 0, "cited": 0, "elsewhere": 0, "pages": {}})
            r["came_up"] += 1
            r["cited"] += 1 if d in cited else 0
        for p in pages:
            if p.get("cited") and p.get("url"):
                pg = rows[_dom(p["url"])]["pages"].setdefault(p["url"], {"url": p["url"], "title": (p.get("title") or "")[:90], "n": 0, "passage": (p.get("cited_text") or "")[:220]})
                pg["n"] += 1
    for it in others:
        _c, seen, _p = _sources_of(it)
        for d in seen:
            if d in rows:
                rows[d]["elsewhere"] += 1
    n = len(group)
    out = []
    for r in rows.values():
        out.append({"domain": r["domain"], "kind": r["kind"], "came_up": r["came_up"], "cited": r["cited"], "of": n, "share_pct": round(100 * r["came_up"] / n) if n else 0, "elsewhere": r["elsewhere"],
                    "is_own": r["kind"] in OWN, "pages": sorted(r["pages"].values(), key=lambda p: -p["n"])[:3]})
    out.sort(key=lambda r: (-r["cited"], -r["came_up"], r["domain"]))
    return out


def _by_kind(group, own_domain, brand_domains):
    n = len(group)
    kinds = {}
    for it in group:
        _c, seen, _p = _sources_of(it)
        for k in {ains.source_kind(d, own_domain, brand_domains) for d in seen}:
            kinds[k] = kinds.get(k, 0) + 1
    return [{"kind": k, "answers": v, "of": n, "share_pct": round(100 * v / n) if n else 0} for k, v in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))]


def ranking(items, own_domain="", brand_domains=()):
    """
    -> {"basis": "named" | "all" | "none", "answers": n, "answers_all": m, "rows": [...], "by_kind": [...], "own_share_pct", "ota_share_pct", "direct": {...the same for the answers about the hotel by name...}}.
    Rows are most-cited first: {domain, kind, came_up (answers it came up in), cited (answers that cited a page of it), of, share_pct, elsewhere (answers NOT naming the hotel it also came up in), is_own, pages}.
    """
    judged = _answers(items)
    named = [i for i in judged if i["mentioned"]]
    not_named = [i for i in judged if not i["mentioned"]]
    basis = "named" if named else "all" if judged else "none"
    group = named if named else judged
    out = {"basis": basis, "answers": len(group), "answers_all": len(judged), "rows": _rank(group, not_named if named else [], own_domain, brand_domains)[:TOP_ROWS],
           "by_kind": _by_kind(group, own_domain, brand_domains)}
    kinds = {k["kind"]: k["share_pct"] for k in out["by_kind"]}
    out["own_share_pct"] = max([kinds.get(k, 0) for k in OWN] + [0])
    out["ota_share_pct"] = kinds.get(OTA, 0)
    out["own_answers"] = sum(k["answers"] for k in out["by_kind"] if k["kind"] in OWN)
    out["ota_answers"] = kinds_answers(out["by_kind"], OTA)
    about = [i for i in items or [] if i.get("answer") and i.get("kind") == "direct"]
    out["direct"] = {"answers": len(about), "rows": _rank(about, [], own_domain, brand_domains)[:8], "by_kind": _by_kind(about, own_domain, brand_domains)}
    return out


def kinds_answers(by_kind, kind):
    return sum(k["answers"] for k in by_kind if k["kind"] == kind)


# ------------------------------------------------- what the assistant took from an agent, and whether the hotel's site says it

# facts an assistant quotes from a booking or review page, each with how to recognise it in a quoted passage and how to recognise the hotel's own site stating it
FACTS = [
    ("rating", "a guest rating or score", r"\b(?:\d(?:\.\d)?\s?/\s?(?:5|10)|\d(?:\.\d)?\s?(?:out of|of)\s?(?:5|10)|rated\s+\d|\d(?:\.\d)?\s?stars?\s+(?:from|based on)|\d[\d,]*\s+(?:guest\s+)?reviews?)",
     r"guest (?:rating|review)|rated\s+\d|\d(?:\.\d)?\s?/\s?(?:5|10)|\d[\d,]*\s+reviews?|tripadvisor|travellers['’] choice|review score"),
    ("price", "a price or rate", r"(?:[£€$]\s?\d|\b(?:from|rates? from|starting at)\s+[£€$]?\d|\d+\s?(?:eur|gbp|usd|chf)\b)", r"(?:[£€$]\s?\d|\bfrom\s+[£€$]\s?\d|rates? (?:from|start)|\d+\s?(?:eur|gbp|usd|chf)\b)"),
    ("cancellation", "a cancellation or flexibility rule", r"free cancell?ation|cancel(?:l?ation)? (?:free|up to|until|policy)|non-?refundable|flexible rate|pay (?:later|at the hotel)|no prepayment",
     r"cancel|refund|flexible|deposit|pay (?:later|at the hotel)"),
    ("location", "how far it is from a named place", r"\b\d+(?:[.,]\d+)?\s?(?:km|miles?|m|min(?:ute)?s?)\b[^.]{0,40}(?:from|to|walk|drive)|\bsteps? from\b|\bwalking distance\b|\bnear(?:by)?\s+[A-Z]", r"\b\d+(?:[.,]\d+)?\s?(?:km|miles?|m|min(?:ute)?s?)\b|steps? from|walking distance|next to|opposite"),
    ("breakfast", "breakfast", r"breakfast", r"breakfast"),
    ("parking", "parking", r"parking|car park|garage", r"parking|car park|garage|valet"),
    ("facilities", "its facilities", r"\b(?:spa|pool|gym|fitness|restaurant|bar|meeting rooms?|conference|wi-?fi|air[- ]conditioning)\b", r"\b(?:spa|pool|gym|fitness|restaurant|bar|meeting rooms?|conference|wi-?fi|air[- ]conditioning)\b"),
    ("times", "check-in or check-out times", r"check-?\s?(?:in|out)\s+(?:from|is|at|time|by)|\b(?:check-?in|check-?out)\b[^.]{0,30}\d{1,2}[:.h]?\d{0,2}", r"check-?\s?(?:in|out)\b[^.]{0,40}\d"),
]
DIRECT_BENEFIT = re.compile(r"book direct|direct(?:ly)? (?:with us|booking)|best (?:rate|price)(?: guarantee)?|price (?:match|promise|guarantee)|member (?:rate|price|offer)|exclusive (?:rate|offer)s?|"
                            r"book (?:on|via|through) our (?:website|site)|when you book (?:with us|direct)|free (?:upgrade|breakfast|cancell?ation) (?:when|if) you book", re.I)


def direct_findings(items, own_pages, own_domain="", brand_domains=()):
    """
    -> {"facts": [{key, label, from_agents: [{url, domain, snippet}], on_own_site: bool, own_evidence: {url, snippet}|None}], "gaps": [keys quoted from an agent and not stated by the hotel's own pages],
    "book_direct": {"stated": bool, "evidence": {url, snippet}|None}, "agents": [domains the facts came from], "passages": n}. Looks only at passages the assistant cited from booking and comparison sites in the answers that
    named the hotel or were about it. 'Not on the own site' means not found on the pages read, which can also mean those pages could not all be read.
    """
    passages = []
    for it in items or []:
        if not it.get("answer") or not (it.get("mentioned") or it.get("kind") == "direct"):
            continue
        for p in it.get("pages") or []:
            d = _dom(p.get("url"))
            if p.get("cited") and p.get("cited_text") and ains.source_kind(d, own_domain, brand_domains) == OTA:
                passages.append({"url": p["url"], "domain": d, "text": re.sub(r"\s+", " ", p["cited_text"])})
    seen, uniq = set(), []
    for p in passages:
        if (p["url"], p["text"][:60]) not in seen:
            seen.add((p["url"], p["text"][:60]))
            uniq.append(p)
    own = [textutil.strip_label_runs(p.get("text", "")) for p in own_pages or []]
    facts, gaps = [], []
    for key, label, agent_rx, own_rx in FACTS:
        a_rx, o_rx = re.compile(agent_rx, re.I), re.compile(own_rx, re.I)
        quoted = []
        for p in uniq:
            m = a_rx.search(p["text"])
            if m:
                quoted.append({"url": p["url"], "domain": p["domain"], "snippet": textutil.sentence_of(p["text"], m.start(), m.end(), limit=200)})
        if not quoted:
            continue
        hit = None
        for pg, text in zip(own_pages or [], own):
            m = o_rx.search(text)
            if m:
                hit = {"url": pg.get("url", ""), "snippet": textutil.sentence_of(text, m.start(), m.end(), limit=200)}
                break
        facts.append({"key": key, "label": label, "from_agents": quoted[:3], "on_own_site": bool(hit), "own_evidence": hit})
        if not hit:
            gaps.append(key)
    bd = None
    for pg, text in zip(own_pages or [], own):
        m = DIRECT_BENEFIT.search(text)
        if m:
            bd = {"url": pg.get("url", ""), "snippet": textutil.sentence_of(text, m.start(), m.end(), limit=200)}
            break
    return {"facts": facts, "gaps": gaps, "book_direct": {"stated": bool(bd), "evidence": bd}, "agents": sorted({p["domain"] for p in uniq}), "passages": len(uniq), "own_pages_read": len(own_pages or [])}
