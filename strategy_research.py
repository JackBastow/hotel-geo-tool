"""
Strategy research: the SPECIFIC outside sources a hotel should be on for the market in its profile, with their real addresses and contact pages, found with Claude's web search.

For a nature destination in Blekinge that means things like the regional tourism board's partner page, the convention bureau, the wedding directories and restaurant guides that cover the region,
travel publications and creators who write about trips like it, tour operators that sell them, award schemes it could enter, and attractions to partner with.

Honesty rules (the same as the review snapshot):
  * a source is kept only when its address was among the pages the search tool actually returned in this request, so nothing comes from the model's memory;
  * a contact page must be on the same site; an email address is kept only when it is on that site's own domain;
  * never another hotel group's site, a rival hotel's site, or a booking/review site (those are covered by the listings action);
  * the result is a list of places to approach, not a promise that any of them will feature the hotel or that an AI assistant will then recommend it.

The result is kept on the hotel (hotels.strategy_json) and refreshed when the profile changes or someone asks; it costs about one search-assisted Claude call.
"""

import json
import re
import threading
import time

import evidence

KINDS = {"tourism_board": "Tourism board", "convention_bureau": "Convention bureau", "venue_directory": "Venue directory", "wedding_directory": "Wedding directory",
         "restaurant_guide": "Restaurant guide", "award": "Award or certification", "publication": "Travel publication or blog", "creator": "Travel creator", "tour_operator": "Tour operator",
         "attraction": "Attraction or partner", "community": "Community or association"}
MAX_SOURCES = 12
MAX_SEARCHES = 8
SYSTEM = ("You research where a specific hotel should be listed, featured or recognised so that travellers and AI assistants find it. Use the web search tool. Report only real organisations and pages you "
          "found in the search results, with their exact addresses. Never invent a URL or an email address. Reply with JSON only.")
PROMPT = """The hotel: {hotel}
Where: {town}, {region}, {area}
What it is: {kinds}
Why guests choose it: {reasons}
Its guests: {auds}; they come from: {origins}
Places guests come for: {attractions}

Find up to {n} specific outside sources this hotel should be on, for THIS market (not generic advice). Cover, where they exist:
- the official tourism board(s) for {region} and {town}, and the page where accommodation is listed or partners join;
- the convention bureau or meeting-venue directories for the area (if it hosts meetings);
- wedding venue directories that cover the region (if it hosts weddings);
- restaurant guides and awards that cover the region (if food is a reason guests come);
- travel publications, blogs and creators that write about trips like this one in {area};
- tour operators that sell trips like this one to {area};
- award schemes and certifications it could enter or hold (for example eco certifications);
- attractions or organisations nearby it could partner with.
Do NOT include: booking or review sites (Booking.com, Tripadvisor, Expedia and similar), any hotel group's own website, or other hotels.
For each: "name", "kind" (one of {kinds_list}), "url" (the organisation's page you found), "contact_url" (its contact, partner, submission or listing page on the same site, if you found one, else ""),
"email" (only if the page shows one, else ""), "why" (one sentence: why it matters for this hotel).
Reply: {{"sources": [{{"name": "", "kind": "", "url": "", "contact_url": "", "email": "", "why": ""}}]}}"""

_running = set()
_lock = threading.Lock()


def _dom(u):
    d = re.sub(r"^https?://", "", str(u or "")).split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def clean(raw, seen, hotel=""):
    """Keep only sources whose page was returned by the search, on an allowed site, with a same-site contact page and email. -> [source dicts]."""
    import review_replies
    import strategy_actions
    out, doms = [], set()
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "").strip()
        d = _dom(url)
        if not url.startswith(("http://", "https://")) or not d or not review_replies.was_seen(url, seen):
            continue                                              # not among the pages the search returned: dropped
        if strategy_actions.is_chain_site(d) or strategy_actions.is_listing_site(d) or d in doms:
            continue
        name = " ".join(str(r.get("name") or "").split())[:90]
        if not name or (hotel and evidence.fold(hotel)[:20] and evidence.fold(hotel)[:20] in evidence.fold(name)):
            continue
        kind = r.get("kind") if r.get("kind") in KINDS else "publication"
        contact = str(r.get("contact_url") or "").strip()
        contact = contact if contact.startswith(("http://", "https://")) and _dom(contact) == d else ""
        email = str(r.get("email") or "").strip().lower()
        email = email if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", email) and (email.split("@")[1] == d or email.split("@")[1].endswith("." + d) or d.endswith("." + email.split("@")[1])) else ""
        doms.add(d)
        out.append({"name": name, "kind": kind, "kind_label": KINDS[kind], "url": url, "domain": d, "contact_url": contact, "email": email, "why": " ".join(str(r.get("why") or "").split())[:240]})
        if len(out) >= MAX_SOURCES:
            break
    return out


def research(hotel, profile, cfg=None, client=None, model=None):
    """-> {"status": ok|unavailable, "at", "sources", "cost_usd", "reason"}. Never raises."""
    import ai_sample
    import review_replies
    p = profile or {}
    at = evidence.now_iso()
    if client is None:
        key = getattr(cfg, "anthropic", None)
        if not key:
            return {"status": "unavailable", "at": at, "sources": [], "cost_usd": 0.0, "reason": "No Claude key is set on the host, so specific sources could not be looked up."}
        try:
            client = ai_sample._make_client(key, timeout=150.0)
        except Exception as e:  # noqa: BLE001
            return {"status": "unavailable", "at": at, "sources": [], "cost_usd": 0.0, "reason": f"The search could not start ({type(e).__name__})."}
    model = model or getattr(cfg, "anthropic_model", None) or ai_sample.MODEL_DEFAULT
    import hotel_profile
    msg = PROMPT.format(hotel=hotel.get("name", ""), town=p.get("town") or hotel.get("city") or "-", region=p.get("region") or "-", area=p.get("area") or "-",
                        kinds=", ".join(dict(hotel_profile.KINDS).get(k, k) for k in p.get("kinds") or []) or "-", reasons="; ".join(p.get("reasons") or []) or "-",
                        auds=", ".join(dict(hotel_profile.audiences()).get(k, k) for k in p.get("audiences") or []) or "-", origins=p.get("origins") or "-",
                        attractions=", ".join(p.get("attractions") or []) or "-", n=MAX_SOURCES, kinds_list=", ".join(KINDS))
    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}
    extra = {"output_config": {"effort": "low"}} if model in ai_sample.EFFORT_MODELS else {}
    messages = [{"role": "user", "content": msg}]
    seen, text, tin, tout, searches = set(), "", 0, 0, 0
    try:
        for _ in range(3):
            resp = client.messages.create(model=model, max_tokens=2500, system=SYSTEM, tools=[dict(tool)], messages=messages, **extra)
            content = ai_sample._get(resp, "content", []) or []
            seen |= review_replies.seen_urls(content)
            a, _d, s, i, o = ai_sample.parse_response(resp)
            text, searches, tin, tout = a or text, searches + s, tin + i, tout + o
            if ai_sample._get(resp, "stop_reason") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": content}]
                continue
            break
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "at": at, "sources": [], "cost_usd": 0.0, "reason": f"The search did not finish ({type(e).__name__})."}
    cost = ai_sample.cost_usd(model, tin, tout, searches)
    try:
        import store
        pass                                          # the spend itself is metered per answer (costs.py)
    except Exception:  # noqa: BLE001
        pass
    data = review_replies.parse_json(text)
    sources = clean((data or {}).get("sources") if isinstance(data, dict) else None, seen, hotel.get("name", ""))
    return {"status": "ok", "at": at, "sources": sources, "cost_usd": round(cost, 4), "reason": "" if sources else "The search found no specific source that could be checked."}


def load(hotel):
    try:
        d = json.loads((hotel or {}).get("strategy_json") or "null")
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def running(hotel_id):
    with _lock:
        return hotel_id in _running


def start(db_url, hotel_id, cfg):
    """Research in the background (a minute or two), once at a time per hotel. -> True when started."""
    if not (db_url and getattr(cfg, "anthropic", None)):
        return False
    try:
        import store
        if store.quota_status(planned_calls=1, service="claude")[2]:
            return False                                   # this month's allowance for AI calls is used: no research until it resets
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        if hotel_id in _running:
            return False
        _running.add(hotel_id)

    def work():
        try:
            import backend
            import hotel_profile
            db = backend.open_store(db_url)
            h = db.get_hotel(hotel_id)
            if h:
                res = research(h, hotel_profile.confirmed(h) or hotel_profile.load(h) or {}, cfg)
                db.set_hotel(hotel_id, strategy_json=json.dumps(res, ensure_ascii=False))
                import progress
                progress._STRATEGY_TRIED.clear()                      # the hotel's strategy actions are rebuilt with the specific sources on the next page view
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _lock:
                _running.discard(hotel_id)
    threading.Thread(target=work, name="strategy-research", daemon=True).start()
    return True


def recent(hotel, hours=6):
    """Was research run (successfully or not) for this hotel within `hours`? Used to stop the hotel's own button running a paid search again and again."""
    r = load(hotel)
    if not r or not r.get("at"):
        return False
    try:
        import datetime as dt
        at = dt.datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - at).total_seconds() < hours * 3600
    except (TypeError, ValueError):
        return False


def stale(hotel, days=30):
    """No research yet, or older than `days`, or older than the profile it was based on."""
    r = load(hotel)
    if not r:
        return True
    if r.get("status") != "ok":
        # a failed run is tried again a day later, not on every page view (each try is a paid web search; a failure that repeats would otherwise run up the bill all day)
        try:
            import datetime as dt
            at = dt.datetime.fromisoformat(str(r.get("at") or "").replace("Z", "+00:00"))
            return (dt.datetime.now(dt.timezone.utc) - at).total_seconds() >= 86400
        except (TypeError, ValueError):
            return True
    try:
        import datetime as dt
        import hotel_profile
        at = dt.datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
        if (dt.datetime.now(dt.timezone.utc) - at).days >= days:
            return True
        p = hotel_profile.load(hotel) or {}
        return bool(p.get("confirmed_at")) and p["confirmed_at"] > r["at"]
    except Exception:  # noqa: BLE001
        return True
