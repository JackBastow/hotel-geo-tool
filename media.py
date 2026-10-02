"""
Media coverage and independent validation (checks 15-20) plus aggregate
rating signals.

Everything here is computed from pages the collector actually read. A page
counts as coverage of THIS hotel only if evidence.match_hotel() said so; the
look-alikes it rejected are kept and shown, so a reader can see what was
excluded and why.

Syndication is handled explicitly: ten copies of one press release are one
story, and three titles from one publishing group are one publisher.
"""

import datetime as dt
import re
from collections import Counter, defaultdict

import evidence
import sourcetypes

EXCLUDED_FROM_COVERAGE = {"booking_platform", "hotel_directory", "social", "video", "wiki",
                          "map_or_open_data", "government_register", "own_website",
                          "hotel_group"}


# ------------------------------------------------------------------- helpers

def _words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _shingles(text, k=7):
    w = _words(text)[:260]
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))} if len(w) >= k else set()


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def freshness(date_iso):
    m = evidence.age_months(date_iso)
    if m is None:
        return "unknown", None
    if m <= 12:
        return "recent", m
    if m <= 36:
        return "dated", m
    return "old", m


def sentences_with(text, pattern, limit=2, max_len=260):
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text or ""):
        if re.search(pattern, s, re.I):
            out.append(s.strip()[:max_len])
            if len(out) >= limit:
                break
    return out


def _substance(mentions, ptype, text_len):
    if ptype in ("roundup", "destination_guide") and mentions <= 2:
        return "listed among others"
    if mentions >= 6:
        return "feature"
    if mentions >= 3:
        return "substantial mention"
    return "passing mention"


# ------------------------------------------------------------------ articles

def build_articles(corpus, hotel, ledger):
    """-> (articles, rejected, unread). Each article is registered as evidence."""
    arts, rejected, unread = [], [], []
    for c in corpus.get("candidates", []):
        if c["source_type"] in EXCLUDED_FROM_COVERAGE:
            continue
        if c["read"]["status"] != "read":
            if any(r in ("news_recent", "news_events", "features") for r in c["roles"]):
                unread.append({"url": c["url"], "title": c["title"], "domain": c["domain"],
                               "why_unread": c["read"]["why"], "date": c.get("published_search")})
            continue
        pg, m = c["page"], c["match"]
        if m["level"] not in ("high", "medium"):
            if pg.get("title"):
                rejected.append({"url": c["url"], "title": pg["title"][:120], "domain": c["domain"],
                                 "level": m["level"], "why": m["why"]})
            continue
        date = pg.get("published") or c.get("published_search")
        fresh, age = freshness(date)
        # A page's metadata date is when it was first published; listing-style pages
        # are updated in place. If the text mentions a later year, say so.
        yrs = [int(y) for y in _YEAR.findall(" ".join(pg.get("windows") or []) + " "
                                              + pg.get("text_head", ""))
               if int(y) <= dt.date.today().year]
        date_note = None
        if date and yrs and max(yrs) > int(date[:4]):
            date_note = (f"the page text mentions {max(yrs)}, later than its metadata date ({date}); "
                         "it may have been updated since first publication")
        ptype = pg["page_type"]["type"]
        domain = c["domain"]
        pk = sourcetypes.publisher_key(domain)
        publisher = pg.get("publisher") or c["label"] or domain
        stype = "destination_body" if c["source_type"] == "destination_body" else (
            "awards_body" if c["source_type"] == "awards_body" else (
                "news_or_magazine" if (ptype in ("news", "roundup", "destination_guide")
                                       or pk in sourcetypes.PUBLISHER_GROUPS) else "blog"))
        win = (pg.get("windows") or [""])[0]
        eid = ledger.add(url=c["url"], source=publisher, source_type=stype, extract=win[:500],
                         published=date, match=m["level"], match_why=m["why"], kind="observed",
                         via=c["via"], lang=pg.get("lang"),
                         note=f"page type (inferred from {pg['page_type']['basis']}): {ptype}")
        arts.append({
            "id": eid, "url": c["url"], "title": pg.get("title") or c["title"], "domain": domain,
            "publisher": publisher, "publisher_key": pk, "source_type": stype,
            "date": date, "date_source": ("the page" if pg.get("published")
                                          else "the search index" if date else None),
            "freshness": fresh, "age_months": age, "date_note": date_note, "type": ptype,
            "type_basis": pg["page_type"]["basis"], "type_confidence": pg["page_type"]["confidence"],
            "cue_text": pg["page_type"].get("cue_text"),
            "lang": pg.get("lang"), "match": m["level"], "match_why": m["why"],
            "mentions": pg.get("mentions", 0), "text_len": pg.get("text_len", 0),
            "substance": _substance(pg.get("mentions", 0), ptype, pg.get("text_len", 0)),
            "windows": (pg.get("windows") or [])[:4], "fingerprint": pg.get("fingerprint", ""),
            "author": pg.get("author"), "aggregator": sourcetypes.is_aggregator(domain),
            "links_to_hotel": pg.get("links_to_hotel", False),
        })
    arts.sort(key=lambda a: a["date"] or "", reverse=True)
    return arts, rejected, unread


def cluster(arts):
    """Group syndicated/duplicated stories. Sets a['cluster'] and returns clusters."""
    n = len(arts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sh = [_shingles(a["fingerprint"] or " ".join(a["windows"])) for a in arts]
    ft = [evidence.fold(a["title"]) for a in arts]
    for i in range(n):
        for j in range(i + 1, n):
            same_title = ft[i] and ft[i] == ft[j]
            sim = _jaccard(sh[i], sh[j])
            if same_title or sim >= 0.5:
                parent[find(j)] = find(i)
    groups = defaultdict(list)
    for i, a in enumerate(arts):
        groups[find(i)].append(a)
    clusters = []
    for k, members in enumerate(groups.values(), 1):
        members.sort(key=lambda a: a["date"] or "9999")
        cid = f"S{k}"
        pubs = sorted({a["publisher_key"] for a in members})
        # Near-identical text carried by two or more DIFFERENT publishers is shared
        # material (a press release or wire copy), so even its first appearance is not
        # independent editorial. Copies inside one publishing group are just that group.
        syndicated = len(pubs) >= 2
        for a in members:
            a["cluster"] = cid
            a["syndicated"] = syndicated
        clusters.append({"id": cid, "original": members[0]["id"],
                         "members": [a["id"] for a in members], "size": len(members),
                         "publishers": pubs, "syndicated": syndicated})
    return clusters


def summarise_coverage(arts, clusters):
    non_dup = {}
    for a in arts:
        non_dup.setdefault(a["cluster"], a)          # earliest member of each story
    stories = list(non_dup.values())
    independent = [a for a in stories
                   if a["type"] not in ("press_release", "sponsored") and not a["aggregator"]
                   and a["source_type"] != "destination_body" and not a.get("syndicated")]
    return {
        "articles": len(arts), "stories": len(stories),
        "duplicates_removed": len(arts) - len(stories),
        "syndicated_stories": sum(1 for a in stories if a.get("syndicated")),
        "publishers": len({a["publisher_key"] for a in arts}),
        "independent_publishers": len({a["publisher_key"] for a in independent}),
        "independent_stories": len(independent),
        "by_type": dict(Counter(a["type"] for a in stories)),
        "by_freshness": dict(Counter(a["freshness"] for a in stories)),
        "by_language": dict(Counter(a["lang"] or "unknown" for a in stories)),
        "recent_independent": sum(1 for a in independent if a["freshness"] == "recent"),
        "old_independent": sum(1 for a in independent if a["freshness"] == "old"),
        "destination_body_pieces": sum(1 for a in stories if a["source_type"] == "destination_body"),
    }


# --------------------------------------------------------------------- awards

_YEAR = re.compile(r"\b(20[0-2]\d)\b")


def _award_hits(text):
    """[(issuer, domains, snippet, year)] for award wording in `text`."""
    out = []
    for pat, issuer, doms in sourcetypes.AWARD_ISSUERS:
        for m in re.finditer(pat, text or "", re.I):
            snip = evidence.clip(text, m.start() - 90, m.end() + 110)
            ys = _YEAR.findall(snip)
            out.append((issuer, doms, snip, ys[-1] if ys else None))
            break  # one hit per issuer per text is enough
    return out


def find_awards(own_pages, arts, corpus, hotel, ledger):
    """
    Award/accreditation claims, separating what the hotel says about itself
    from what the issuer (or an independent page) says. A claim on the
    hotel's own site that no issuer page confirms stays "claimed by the hotel".
    """
    rows = {}

    def row(issuer, doms):
        return rows.setdefault(issuer, {"issuer": issuer, "claims": [], "independent": [],
                                        "issuer_confirmed": None, "issuer_pages": [],
                                        "years": set(), "domains": doms})

    for p in own_pages or []:
        for issuer, doms, snip, year in _award_hits(p.get("text", "")):
            r = row(issuer, doms)
            eid = ledger.add(url=p["url"], source="Hotel's own website", source_type="own_website",
                             extract=snip, kind="observed", match="high",
                             match_why="the hotel's own page", via="own pages")
            r["claims"].append({"id": eid, "url": p["url"], "text": snip, "year": year})
            if year:
                r["years"].add(year)

    for a in arts:
        if a["type"] in ("sponsored",):
            continue
        for w in a["windows"]:
            for issuer, doms, snip, year in _award_hits(w):
                r = row(issuer, doms)
                r["independent"].append({"id": a["id"], "publisher": a["publisher"], "url": a["url"],
                                         "text": snip, "year": year, "date": a["date"]})
                if year:
                    r["years"].add(year)

    # issuer pages: a candidate on the issuer's own domain that names the hotel
    for c in corpus.get("candidates", []):
        if c["read"]["status"] != "read":
            continue
        for r in rows.values():
            if r["domains"] and any(d in c["domain"] for d in r["domains"]):
                named = c["match"]["level"] in ("high", "medium")
                r["issuer_pages"].append({"url": c["url"], "names_hotel": named})
                if named:
                    r["issuer_confirmed"] = True
                    ev = (c["page"].get("windows") or [""])[0]
                    eid = ledger.add(url=c["url"], source=c["label"] or c["domain"],
                                     source_type="awards_body", extract=ev[:500],
                                     published=c["page"].get("published"), kind="observed",
                                     match=c["match"]["level"], match_why=c["match"]["why"],
                                     via=c["via"])
                    r["confirmation_id"] = eid
    out = []
    for r in rows.values():
        if r["issuer"] == "(issuer not named)":
            status = "unverifiable - issuer not named"
        elif r["issuer_confirmed"]:
            status = "confirmed by a page on the issuer's own site"
        elif r["independent"] and not r["claims"]:
            status = "mentioned by independent pages; not confirmed by the issuer"
        elif r["issuer_pages"]:
            status = "issuer page read - it does not name the hotel"
        elif r["claims"]:
            status = "claimed by the hotel; not independently confirmed"
        else:
            status = "mentioned; not confirmed"
        out.append({**{k: v for k, v in r.items() if k not in ("domains", "years")},
                    "years": sorted(r["years"]), "status": status})
    out.sort(key=lambda r: (r["issuer"] == "(issuer not named)", r["issuer"]))
    return out


# --------------------------------------------------------------------- themes

def theme_scan(arts, own_pages):
    """
    Themes by source group. Only the windows around the hotel's name are read
    from third-party pages, so a roundup's words about the other hotels are
    never attributed to this one. The hotel's own pages are read whole, and
    kept separate because it is the hotel describing itself.
    """
    rx = {k: re.compile(v, re.I) for k, v in sourcetypes.THEMES.items()}
    themes = {k: {"own_pages": 0, "independent": [], "other": []} for k in rx}
    for p in own_pages or []:
        for k, r in rx.items():
            if r.search(p.get("text", "")):
                themes[k]["own_pages"] += 1
    for a in arts:
        text = " ".join(a["windows"])
        for k, r in rx.items():
            if not r.search(text):
                continue
            sents = sentences_with(text, rx[k].pattern, limit=1)
            ex = {"id": a["id"], "publisher": a["publisher"], "publisher_key": a["publisher_key"],
                  "url": a["url"], "date": a["date"], "text": (sents[0] if sents else text[:220])}
            bucket = "independent" if (a["type"] not in ("sponsored", "press_release")
                                       and a["source_type"] != "destination_body") else "other"
            themes[k][bucket].append(ex)
    rows = []
    for k, v in themes.items():
        pubs = {e["publisher_key"] for e in v["independent"]}
        rows.append({"theme": k, "own_pages": v["own_pages"],
                     "independent_publishers": len(pubs),
                     "independent_extracts": v["independent"][:3],
                     "other_extracts": v["other"][:2]})
    rows = [r for r in rows if r["own_pages"] or r["independent_publishers"] or r["other_extracts"]]
    rows.sort(key=lambda r: (-r["independent_publishers"], -r["own_pages"]))
    disagreements = []
    for a_t, b_t in sourcetypes.OPPOSITES:
        pa = {e["publisher_key"] for e in themes[a_t]["independent"]}
        pb = {e["publisher_key"] for e in themes[b_t]["independent"]}
        # a real disagreement needs one source on each side: one that uses
        # theme A without B, and a different one that uses B without A
        if (pa - pb) and (pb - pa):
            disagreements.append({
                "themes": [a_t, b_t],
                "a": themes[a_t]["independent"][:1], "b": themes[b_t]["independent"][:1]})
    own_only = [r["theme"] for r in rows if r["own_pages"] and not r["independent_publishers"]]
    ext_only = [r["theme"] for r in rows if r["independent_publishers"] and not r["own_pages"]]
    return {"themes": rows, "disagreements": disagreements,
            "own_only": own_only, "independent_only": ext_only}


# -------------------------------------------------------------- rating signals

_RATING_PATTERNS = [
    re.compile(r"(?P<v>\d(?:\.\d)?)\s*(?:/|out of|of)\s*(?P<s>5|10)\b[^.]{0,60}?"
               r"(?:\(?\s*(?P<n>\d[\d,]*)\s*(?:reviews?|ratings?)\)?)?", re.I),
    re.compile(r"(?P<v>[1-5]\.\d)\s*\((?P<n>\d[\d,]*)\)"),
    re.compile(r"rated\s+[\"“']?[A-Za-z ]{3,12}[\"”']?\s+with\s+(?P<v>\d(?:\.\d)?)\s*/\s*(?P<s>5)", re.I),
]


def rating_signals(corpus, hotel, city, ledger):
    """
    Aggregate ratings third parties display about the hotel (e.g. "5.0 (13)").
    These are numbers shown in search results or on pages we were allowed to
    read - NOT reviews, and not a sample we can analyse. A rating found only
    in a search snippet, with no town named beside the hotel, is marked
    unverified because the same name is shared by many hotels.
    """
    out = []
    for c in corpus.get("candidates", []):
        if c["source_type"] in ("own_website", "social", "video", "wiki"):
            continue
        texts = [("search result", f"{c['title']} {c['snippet']}")]
        if c["read"]["status"] == "read":
            texts = [("page", w) for w in (c["page"].get("windows") or [])[:3]] + texts
        for where, t in texts:
            m_hotel = evidence.match_hotel(t, hotel, city, "", "")
            slug = evidence.fold(c["url"].replace("-", " ").replace("/", " "))
            named = m_hotel["level"] in ("high", "medium") or any(
                v in slug for v in evidence.name_variants(hotel))
            if not named:
                continue
            variants = evidence.name_variants(hotel)
            for rx in _RATING_PATTERNS:
                m = None
                for cand in rx.finditer(t):
                    # the rating must sit right beside the hotel's name; a number
                    # elsewhere on a multi-hotel listing belongs to some other hotel
                    near = evidence.fold(t[max(0, cand.start() - 170): cand.end() + 170])
                    if any(v in near for v in variants):
                        m = cand
                        break
                if not m:
                    continue
                gd = m.groupdict()
                # "1 / 10 results" or "2 / 5 photos" is a page counter, not a rating. Accept
                # a whole-number score only with rating wording beside it; decimals ("4.5/5")
                # are accepted as they are.
                around = t[max(0, m.start() - 45): m.end() + 45]
                if re.match(r"\s*(?:results?|photos?|images?|pages?|slides?|rooms?|hotels?|of \d)",
                            t[m.end(): m.end() + 12], re.I):
                    continue
                if "." not in gd["v"] and not re.search(r"rat(?:ed|ing)|score|review|stars?|out of", around, re.I):
                    continue
                val = float(gd["v"])
                scale = int(gd.get("s") or 5)
                if val > scale:
                    continue
                n = int(gd["n"].replace(",", "")) if gd.get("n") else None
                verified = (c["read"]["status"] == "read" and c["match"]["level"] == "high") or \
                           (m_hotel["level"] == "high")
                eid = ledger.add(url=c["url"], source=c["label"] or c["domain"],
                                 source_type=c["source_type"] if c["source_type"] in
                                 evidence.SOURCE_TYPES else "other",
                                 extract=t[:300], published=None,
                                 match="high" if verified else "medium",
                                 match_why=("town named beside the hotel" if verified else
                                            "no town named beside the hotel - may be a different hotel"),
                                 kind="observed", via=c["via"])
                out.append({"id": eid, "source": c["label"] or c["domain"], "url": c["url"],
                            "value": val, "scale": scale, "count": n, "where": where,
                            "verified_location": verified,
                            "text": re.sub(r"\s+", " ", t)[:200]})
                break
            else:
                continue
            break
    seen, uniq = set(), []
    for r in out:
        k = (r["source"], r["value"], r["count"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq
