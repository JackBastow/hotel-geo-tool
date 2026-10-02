"""
Social/video evidence and local context (checks 28-29) and website support
for external claims (check 30).
"""

import re

import evidence
import sourcetypes

PARTNER_RX = re.compile(
    r"(in partnership with|partner(?:ed|ship)? with|official (?:hotel|partner|accommodation)|"
    r"exclusive partner|collaborat\w+ with|working with|sister (?:hotel|property)|"
    r"member of|part of the)\s+(?:the\s+)?([A-Z][\w'’&.-]*(?:\s+[A-Z&][\w'’&.-]*){0,4})")
SOCIAL_NOTE = ("Instagram, Facebook, TikTok and X do not permit automated reading of their content, so "
               "post topics, dates and activity are not assessed. A profile being linked is all that "
               "can be confirmed; nothing is inferred about activity or sentiment.")


def social_and_video(discovery, youtube, tavily):
    profiles = [p for p in (discovery or {}).get("profiles", [])
                if p["platform"] in {"Facebook", "Instagram", "TikTok", "X / Twitter", "X",
                                     "YouTube", "LinkedIn", "Pinterest", "Threads"}]
    rows = [{"platform": p["platform"], "url": p["url"], "evidence": "official profile linked from the hotel's site",
             "content_assessed": False, "note": "content not readable by automated tools"}
            for p in profiles]
    indep = []
    for h in (tavily or {}).get("social_hits", []) or []:
        indep.append({"platform": h.get("platform"), "url": h.get("url"), "title": h.get("title"),
                      "snippet": h.get("snippet"),
                      "note": "found in a search index; content not read"})
    vids = []
    if youtube and youtube["status"] == "ok":
        for v in youtube["items"]:
            vids.append(v)
    dates = sorted(v["published"] for v in vids if v.get("published"))
    return {"profiles": rows, "independent_social": indep[:6], "videos": vids,
            "video_range": [dates[0], dates[-1]] if dates else None,
            "youtube_status": (youtube or {}).get("status"),
            "youtube_reason": (youtube or {}).get("reason", ""), "note": SOCIAL_NOTE}


def location_context(osm, own_pages, arts, ledger):
    """Straight-line distances from OpenStreetMap plus partnerships actually evidenced in text."""
    items = (osm or {}).get("items") or []
    ctx = items[0] if items else {}
    partners = []
    seen = set()
    for p in own_pages or []:
        for m in PARTNER_RX.finditer(p.get("text", "")):
            name = m.group(2).strip(" .,;")
            k = evidence.fold(name)
            if len(k) < 4 or k in seen or k in ("our", "the hotel", "this"):
                continue
            seen.add(k)
            eid = ledger.add(url=p["url"], source="Hotel's own website", source_type="own_website",
                             extract=evidence.clip(p["text"], m.start() - 80, m.end() + 100), kind="observed",
                             match="high", match_why="the hotel's own page", via="own pages",
                             note="possible partnership statement")
            partners.append({"partner": name, "relationship": m.group(1), "source_url": p["url"],
                             "evidence_id": eid,
                             "confirmed_by_partner": False,
                             "status": "stated by the hotel; the partner's side was not checked"})
    for a in arts:
        for w in a["windows"]:
            for m in PARTNER_RX.finditer(w):
                name = m.group(2).strip(" .,;")
                k = evidence.fold(name)
                if len(k) < 4 or k in seen:
                    continue
                seen.add(k)
                partners.append({"partner": name, "relationship": m.group(1), "source_url": a["url"],
                                 "evidence_id": a["id"], "confirmed_by_partner": False,
                                 "status": f"stated in an article by {a['publisher']}"})
    return {"available": bool(ctx), "status": (osm or {}).get("status"),
            "reason": (osm or {}).get("reason", ""),
            "stations": ctx.get("stations", []), "attractions": ctx.get("attractions", []),
            "airports": ctx.get("airports", []), "venues": ctx.get("venues", []),
            "nearby_hotels": ctx.get("hotels", []), "failed_parts": ctx.get("failed_parts", []),
            "partnerships": partners[:8],
            "label": ("All distances are straight-line from OpenStreetMap coordinates. Travel times "
                      "are not calculated and none is implied.")}


def website_support(themes, awards, own_pages, arts, guest, site, ratings_seen, entities):
    """
    Does the website explain what the rest of the evidence says, and can
    public crawlers read it? One pillar of the report, not all of it.
    """
    own_text = " ".join(p.get("text", "") for p in own_pages or []).lower()
    rows = []
    for t in themes["themes"]:
        if t["independent_publishers"] and not t["own_pages"]:
            rows.append({"item": f"Independent writers describe the hotel as '{t['theme']}'",
                         "on_website": False,
                         "evidence": (t["independent_extracts"] or [{}])[0],
                         "action_hint": "If true and useful to guests, say so plainly on a page that "
                                        "covers it."})
    for a in awards:
        if a["issuer"] == "(issuer not named)":
            continue
        claimed = bool(a["claims"])
        if a["independent"] and not claimed:
            rows.append({"item": f"{a['issuer']} recognition is mentioned by others",
                         "on_website": False,
                         "evidence": a["independent"][0],
                         "action_hint": "If the recognition is current, state it with year and a link "
                                        "to the issuer."})
    nav_urls = " ".join(p["url"] for p in own_pages or [])
    has_press = bool(re.search(r"/(press|news|media|awards?|accolades|in-the-press)\b", nav_urls, re.I))
    gq = {q["id"]: q for q in (guest or {}).get("questions", [])}
    unanswered = [q["short"] for q in gq.values() if q["state"] in ("not_found", "needs_checking")]
    partial = [q["short"] for q in gq.values() if q["state"] == "partial"]
    robots = (site or {}).get("robots", {})
    return {
        "external_facts_missing_on_site": rows[:8],
        "has_press_or_awards_page": has_press,
        "guest_questions_unanswered": unanswered, "guest_questions_partial": partial,
        "crawler_access": {
            "robots_txt_present": robots.get("present"),
            "blocks_all": robots.get("blocks_all"),
            "ai_crawlers_blocked": (site or {}).get("ai_crawlers_blocked") or [],
            "sitemap": bool((site or {}).get("sitemap")),
            "structured_data_found": bool((site or {}).get("lodging_node_found")),
        },
    }
