"""
The hotel profile: what the hotel IS and how its guests find it, confirmed by the hotel (or the operator) before anything is measured.

Why: a hotel was set up from three words (name, website, town) and everything else was guessed from its website. That fits a town-centre hotel; it does not fit a nature reserve people travel to on
purpose, whose guests search for 'a wildlife weekend in southern Sweden', not 'hotels in Karlshamn'. And a town name can be read as somewhere else entirely ('Eriksberg' is also a district of Gothenburg).
So a new hotel is set up in this order:

  1. the operator adds it (name, website, town); a DRAFT profile is written in the background from its own website, in any language (draft_from_site);
  2. the hotel opens its invite and confirms the profile: exactly which property it is (address, map), the kind of stay, why people come, who they are, where they search from, price level, competitors;
  3. prompts are written from the confirmed profile at every level guests search at (prompts_from_profile) and the hotel confirms them;
  4. confirming the prompts starts the first full check. Weekly checks begin only after that.

The confirmed profile then feeds every check (facts_for_audit, audit_params): the town, price level and audiences the questions use, the places they may mention, the owner-stated facts AI proposals may
rest on, the coordinates the nearby places are found from, and the competitors the hotel chose. Hotels set up before profiles keep their weekly checks; they get a draft to review.

Honesty: a reason to visit taken from the website is kept only when its quote is really on the pages; competitors suggested by the AI are labelled as suggestions to check; nothing is used until confirmed.
"""

import json
import re
import threading
import time
import urllib.parse

import evidence
from timeutil import uk_time

# the kinds of stay a hotel can be (several may apply); the label is what the hotel sees
KINDS = [
    ("town", "Town or city hotel"), ("business", "Business and conference hotel"), ("airport", "Airport hotel"), ("resort", "Resort"),
    ("countryside", "Countryside retreat"), ("destination", "A destination in itself (nature, wildlife, an experience)"), ("spa", "Spa and wellness"),
    ("boutique", "Boutique or design hotel"), ("historic", "Historic or character building"), ("coastal", "Coast or beach"), ("family", "Family holidays"),
    ("budget", "Budget or value"), ("apartments", "Apartments or long stays"),
]
KIND_KEYS = [k for k, _l in KINDS]
PRICES = [("", "Not sure"), ("budget", "Budget"), ("midscale", "Mid-range"), ("upscale", "Upscale (4-star level)"), ("luxury", "Luxury (5-star level)")]
LANGS = ["English", "Swedish", "Norwegian", "Danish", "Finnish", "German", "Dutch", "French", "Spanish", "Italian", "Portuguese", "Polish", "Chinese", "Japanese", "Arabic"]
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "HotelDiscoverabilityAudit/1.0 (independent hotel visibility audit; respects usage limits)"
_drafting = set()
_lock = threading.Lock()


def audiences():
    import ai_niche
    return [(k, lbl) for k, lbl, *_r in ai_niche.AUDIENCES]


def empty():
    return {"status": "draft", "source": "", "address": "", "lat": None, "lon": None, "map_name": "", "town": "", "region": "", "area": "", "attractions": [], "kinds": [],
            "reasons": [], "audiences": [], "origins": "", "languages": ["English"], "price": "", "competitors": [], "suggested": [], "notes": "", "confirmed_at": "", "confirmed_by": ""}


def load(hotel):
    """The hotel's profile (a dict), or None when it has none yet."""
    raw = (hotel or {}).get("profile_json")
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except ValueError:
        return None
    return {**empty(), **p} if isinstance(p, dict) else None


def confirmed(hotel):
    p = load(hotel)
    return p if p and p.get("status") == "confirmed" else None


def save(db, hotel_id, profile):
    db.set_hotel(hotel_id, profile_json=json.dumps(profile, ensure_ascii=False))


def places(profile):
    """Every place name a prompt may be about: town, region, wider area and the attractions the hotel is or is near."""
    p = profile or {}
    out = [p.get("town"), p.get("region"), p.get("area")] + list(p.get("attractions") or [])
    seen, res = set(), []
    for x in out:
        x = " ".join(str(x or "").split())
        if x and evidence.fold(x) not in seen:
            seen.add(evidence.fold(x))
            res.append(x)
    return res


# ------------------------------------------------------------------------- reading the website

def _text_and_links(html, base):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        u = urllib.parse.urljoin(base, a["href"]).split("#")[0]
        links.append((u, a.get_text(" ", strip=True)))
    for t in soup(["script", "style", "noscript", "svg", "form"]):
        t.decompose()
    return " ".join(soup.get_text(" ").split()), links


PAGE_WORDS = re.compile(r"about|om-oss|uber|über|a-propos|rooms?|rum|zimmer|chambres|stay|bo|restaurant|ata|äta|eat|dining|food|meet|konferens|conference|event|wedding|brollop|bröllop|"
                        r"spa|activit|aktivitet|upplev|experience|safari|nature|natur|location|hitta|find-us|getting|contact|kontakt|family|familj|offers|erbjud", re.I)


def read_site(website, fetch=None, max_pages=6):
    """The hotel's home page and the few pages most likely to say what it is (about, rooms, food, meetings, activities, location), as [{url, text}]. Pages in any language."""
    import netguard
    fetch = fetch or (lambda u: netguard.get(u, headers={"User-Agent": UA}, timeout=15))
    base = website if "//" in website else "https://" + website
    try:
        r = fetch(base)
    except Exception:  # noqa: BLE001
        return []
    if r is None or getattr(r, "status_code", 0) != 200:
        return []
    final = getattr(r, "url", base) or base
    text, links = _text_and_links(r.text, final)
    pages = [{"url": final, "text": text}]
    host = urllib.parse.urlparse(final).netloc.lower()
    seen = {final}
    picks = []
    for u, label in links:
        p = urllib.parse.urlparse(u)
        if p.netloc.lower() != host or u in seen or re.search(r"\.(?:pdf|jpe?g|png|gif|zip)$", p.path, re.I):
            continue
        seen.add(u)
        if PAGE_WORDS.search(p.path) or PAGE_WORDS.search(label or ""):
            picks.append(u)
    for u in picks[:max_pages - 1]:
        try:
            r2 = fetch(u)
        except Exception:  # noqa: BLE001
            continue
        if r2 is not None and getattr(r2, "status_code", 0) == 200:
            pages.append({"url": u, "text": _text_and_links(r2.text, u)[0]})
    return pages


DRAFT_SYSTEM = ("You read a hotel's own web pages, in any language, and describe in English what kind of place it is and how its guests would search for it. "
                "Use only what the pages say for facts about the hotel. Reply with JSON only.")
DRAFT_PROMPT = """The hotel is called "{hotel}". The operator entered its town as "{town}". Its own pages:
{pages}

Fill in this profile. Rules:
- "town": the town or city travellers would actually search for to find this hotel (for a place outside a town, the nearest real town). Check the pages: the town entered may be wrong or ambiguous.
- "region": the county, province or region it is in. "area": the wider area people plan trips around (for example "southern Sweden", "the Cotswolds", "Côte d'Azur").
- "attractions": up to 5 named places the hotel IS or is close to and that guests come for (as named on the pages).
- "kinds": any of {kinds}.
- "reasons": up to 8 reasons guests choose it, each in a few English words, with "quote": a short quote copied word for word from the pages, in the page's own language.
- "audiences": any of {auds}.
- "origins": where its guests mostly come from, if the pages suggest it (for example "Sweden, Germany, Denmark"), else "".
- "languages": the languages its guests would search in (the site's languages are a clue).
- "price": one of budget, midscale, upscale, luxury, or "" if unclear.
- "competitors": up to 6 real hotels or places to stay that travellers would compare it with for the same kind of stay (not just the nearest hotels). Only names you are confident exist.
Reply: {{"town": "", "region": "", "area": "", "attractions": [], "kinds": [], "reasons": [{{"text": "", "quote": ""}}], "audiences": [], "origins": "", "languages": [], "price": "", "competitors": []}}"""


def _clean_list(xs, n, maxlen=80):
    out = []
    for x in xs if isinstance(xs, list) else []:
        x = " ".join(str(x or "").split())[:maxlen]
        if x and x not in out:
            out.append(x)
    return out[:n]


def draft_from_site(hotel, cfg, fetch=None, client=None):
    """
    A draft profile from the hotel's own website. With a Claude key: one call reads the pages (any language) and fills in the profile; reasons are kept only when their quote is on the pages.
    Without one, or if anything fails: the town entered and the map lookup only. Never raises. -> profile dict (status 'draft').
    """
    p = empty()
    p["source"] = "website"
    p["town"] = (hotel.get("city") or "").strip()
    try:
        pages = read_site(hotel["website"], fetch=fetch)
    except Exception:  # noqa: BLE001
        pages = []
    blob = ""
    for pg in pages:
        blob += f"[{pg['url']}] {pg['text'][:2500]}\n"
    blob = blob[:10000]
    key = getattr(cfg, "anthropic", None)
    if blob and (client is not None or key):
        try:
            import ai_sample
            import review_replies
            c = client or ai_sample._make_client(key, timeout=60.0)
            model = getattr(cfg, "anthropic_model", None) or ai_sample.MODEL_DEFAULT
            msg = DRAFT_PROMPT.format(hotel=hotel["name"], town=p["town"], pages=blob, kinds=", ".join(KIND_KEYS), auds=", ".join(k for k, _l in audiences()))
            resp = c.messages.create(model=model, max_tokens=1500, system=DRAFT_SYSTEM, messages=[{"role": "user", "content": msg}])
            text, _d, _s, tin, tout = ai_sample.parse_response(resp)
            try:
                import store
                store.record_usage(max(1, round(ai_sample.cost_usd(model, tin, tout, 0) * 1000)), service="claude")
            except Exception:  # noqa: BLE001
                pass
            d = review_replies.parse_json(text)
            if isinstance(d, dict):
                hay = " ".join(evidence.fold(blob).split())
                p["town"] = " ".join(str(d.get("town") or p["town"]).split())[:80]
                p["region"] = " ".join(str(d.get("region") or "").split())[:80]
                p["area"] = " ".join(str(d.get("area") or "").split())[:80]
                p["attractions"] = _clean_list(d.get("attractions"), 5)
                p["kinds"] = [k for k in d.get("kinds") or [] if k in KIND_KEYS]
                p["audiences"] = [k for k in d.get("audiences") or [] if k in {a for a, _l in audiences()}]
                p["origins"] = " ".join(str(d.get("origins") or "").split())[:120]
                langs = [x for x in _clean_list(d.get("languages"), 6, 20)]
                p["languages"] = langs or ["English"]
                p["price"] = d.get("price") if d.get("price") in {k for k, _l in PRICES} else ""
                reasons = []
                for r in d.get("reasons") or []:
                    if not isinstance(r, dict):
                        continue
                    q = " ".join(evidence.fold(str(r.get("quote") or "")).split())
                    t = " ".join(str(r.get("text") or "").split())[:80]
                    if t and len(q) >= 6 and q in hay:
                        reasons.append(t)
                p["reasons"] = reasons[:8]
                p["suggested"] = _clean_list(d.get("competitors"), 6)
        except Exception:  # noqa: BLE001 - the plain draft stands
            pass
    try:
        g = geocode(hotel["name"], p["town"])
        if g:
            p.update(g)
    except Exception:  # noqa: BLE001
        pass
    return p


def geocode(name, town, fetch=None):
    """One OpenStreetMap search for the hotel by name and town: {address, lat, lon, map_name} or None. The hotel confirms it is the right place."""
    import netguard
    fetch = fetch or (lambda u: netguard.get(u, headers={"User-Agent": UA}, timeout=10))
    for q in [f"{name}, {town}" if town else name, name]:
        try:
            r = fetch(NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "addressdetails": 1}))
            rows = r.json() if r is not None and r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            rows = []
        if rows:
            x = rows[0]
            try:
                return {"address": x.get("display_name", "")[:240], "map_name": x.get("display_name", "")[:240], "lat": round(float(x["lat"]), 5), "lon": round(float(x["lon"]), 5)}
            except (KeyError, ValueError, TypeError):
                return None
        time.sleep(1.0)                                 # Nominatim asks for at most one request a second
    return None


def map_link(p):
    if p and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float)):
        return f"https://www.openstreetmap.org/?mlat={p['lat']}&mlon={p['lon']}#map=14/{p['lat']}/{p['lon']}"
    return ""


def start_draft(db_url, hotel_id, cfg):
    """Write the hotel's draft profile in the background (a minute at most), once. Nothing happens if one is already being written or the hotel already has a profile, or without a Claude key
    (then the form starts from the town entered, and the map is looked up when it is saved)."""
    if not (db_url and getattr(cfg, "anthropic", None)):
        return False
    with _lock:
        if hotel_id in _drafting:
            return False
        _drafting.add(hotel_id)

    def work():
        try:
            import backend
            db = backend.open_store(db_url)
            h = db.get_hotel(hotel_id)
            if h and not load(h):
                prof = draft_from_site(h, cfg)
                h2 = db.get_hotel(hotel_id)
                if h2 and not load(h2):
                    save(db, hotel_id, prof)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _lock:
                _drafting.discard(hotel_id)
    threading.Thread(target=work, name="profile-draft", daemon=True).start()
    return True


def drafting(hotel_id):
    with _lock:
        return hotel_id in _drafting


# ------------------------------------------------------------------------- the form

def form_html(p, action, csrf, drafting_now=False, who="hotel"):
    """The profile form (the same for the hotel and the operator)."""
    esc = lambda s: __import__("html").escape(str(s or ""), quote=True)
    p = {**empty(), **(p or {})}
    aud = audiences()

    def checks(name, options, chosen):
        return "".join(f'<label style="display:inline-block;margin:4px 14px 4px 0"><input type="checkbox" name="{name}" value="{esc(k)}"{" checked" if k in chosen else ""}> {esc(lbl)}</label>' for k, lbl in options)
    langs = list(dict.fromkeys(LANGS + list(p["languages"] or [])))
    mp = map_link(p)
    top = ""
    if drafting_now:
        top = ('<div class="alert info">We are reading your website to fill this in for you. It takes about a minute: <a href="">refresh the page</a> in a moment, or start filling it in yourself.</div>')
    elif p.get("source") == "website" and p.get("status") != "confirmed":
        top = '<div class="alert info">We have filled this in from your website. Please check every part and correct anything that is wrong: everything we measure is built on it.</div>'
    sugg = ""
    if p.get("suggested"):
        sugg = ('<p class="caption">Suggested by the AI from what your website says (please check each one is a real competitor before adding it): '
                + ", ".join(f"<b>{esc(s)}</b>" for s in p["suggested"]) + ".</p>")
    return (f'<form method="post" action="{esc(action)}" class="panel profile-form">{top}<input type="hidden" name="csrf" value="{esc(csrf)}">'
            '<h4>1. Which hotel exactly</h4>'
            f'<label class="field"><span>Full address</span><input name="address" value="{esc(p["address"])}" required></label>'
            + (f'<p class="caption">We found it here on the map: <a href="{esc(mp)}" target="_blank" rel="noopener">open the map</a> ({esc(p["map_name"])}). If the pin is not your hotel, correct the address and save: we will look again.</p>'
               if mp else '<p class="caption">We could not place this on the map yet. Check the address and save: we will look again.</p>')
            + '<h4>2. Where guests search for you</h4><p class="caption">People search at different levels: the town, the region, the wider area, or a place they want to visit. Give each one you are found by.</p>'
            f'<label class="field"><span>Town (the real town travellers search for; for somewhere outside a town, the nearest one)</span><input name="town" value="{esc(p["town"])}" required></label>'
            f'<label class="field"><span>Region or county</span><input name="region" value="{esc(p["region"])}"></label>'
            f'<label class="field"><span>Wider area people plan trips around (for example: southern Sweden, the Cotswolds)</span><input name="area" value="{esc(p["area"])}"></label>'
            f'<label class="field"><span>Places your guests come for, one per line (attractions, a reserve, a venue, an airport)</span><textarea name="attractions" rows="3">{esc(chr(10).join(p["attractions"]))}</textarea></label>'
            '<h4>3. What kind of stay you are</h4>' + checks("kinds", KINDS, p["kinds"])
            + f'<label class="field"><span>Why guests choose you, one per line (for example: wildlife safaris, award-winning game restaurant, conferences in nature)</span><textarea name="reasons" rows="4">{esc(chr(10).join(p["reasons"]))}</textarea></label>'
            '<h4>4. Your guests</h4>' + checks("audiences", aud, p["audiences"])
            + f'<label class="field"><span>Where they mostly come from (for example: Sweden, Germany, Denmark)</span><input name="origins" value="{esc(p["origins"])}"></label>'
            '<p class="caption">Languages your guests search in:</p>' + checks("languages", [(x, x) for x in langs], p["languages"])
            + '<h4>5. Price level</h4><label class="field"><span>Price level</span><select name="price">'
            + "".join(f'<option value="{k}"{" selected" if k == p["price"] else ""}>{esc(lbl)}</option>' for k, lbl in PRICES) + '</select></label>'
            '<h4>6. Your competitors</h4><p class="caption">The places guests compare you with for the same kind of stay (not only the hotels next door). One per line.</p>'
            f'<label class="field"><span>Competitors</span><textarea name="competitors" rows="4">{esc(chr(10).join(p["competitors"]))}</textarea></label>' + sugg
            + f'<label class="field"><span>Anything else we should know (optional)</span><textarea name="notes" rows="2">{esc(p["notes"])}</textarea></label>'
            + '<button class="btn primary" type="submit">' + ("Confirm the profile and write our prompts" if who == "hotel" else "Save and confirm the profile") + '</button>'
            '<p class="caption">Saving writes a recommended set of prompts from this profile for you to check and confirm. ' + ("Confirming the prompts starts your first check." if who == "hotel" else "") + '</p></form>')


def from_form(form, old, who):
    """The submitted form -> (profile, error)."""
    lines = lambda k, n=12, m=80: _clean_list([x for x in (form.get(k) or "").splitlines()], n, m)
    p = {**empty(), **(old or {})}
    p.update(address=" ".join((form.get("address") or "").split())[:240], town=" ".join((form.get("town") or "").split())[:80],
             region=" ".join((form.get("region") or "").split())[:80], area=" ".join((form.get("area") or "").split())[:80],
             attractions=lines("attractions", 6), reasons=lines("reasons", 10), competitors=lines("competitors", 12, 100),
             kinds=[k for k in form.getlist("kinds") if k in KIND_KEYS], audiences=[k for k in form.getlist("audiences") if k in {a for a, _l in audiences()}],
             origins=" ".join((form.get("origins") or "").split())[:120], languages=_clean_list(form.getlist("languages"), 8, 20) or ["English"],
             price=form.get("price") if form.get("price") in {k for k, _l in PRICES} else "", notes=" ".join((form.get("notes") or "").split())[:400])
    if not p["town"]:
        return p, "Enter the town travellers search for."
    import urlscope
    if urlscope.is_country(p["town"]):
        return p, f"“{p['town']}” is a country. Enter the town (or the nearest town)."
    if not p["address"]:
        return p, "Enter the hotel's address."
    moved = (p["address"] != (old or {}).get("address")) or (p["town"] != (old or {}).get("town"))
    if moved or not isinstance(p.get("lat"), (int, float)):
        g = None
        try:
            g = geocode(p["address"], "")
        except Exception:  # noqa: BLE001
            g = None
        p.update(lat=g["lat"], lon=g["lon"], map_name=g["map_name"]) if g else p.update(lat=None, lon=None, map_name="")
    p.update(status="confirmed", confirmed_at=evidence.now_iso(), confirmed_by=who)
    return p, ""


def apply(db, hotel, profile):
    """Store the confirmed profile and copy what the checks already read from the hotel's record: its town, price level and audiences."""
    save(db, hotel["id"], profile)
    db.set_hotel(hotel["id"], city=profile["town"], tier=profile["price"] or None, audiences=",".join(profile["audiences"]))


# ------------------------------------------------------------------------- prompts from the profile

AUD_PHRASE = {"airport": "an overnight stay before a flight", "business": "a business trip", "meetings": "a team meeting or conference", "wellness": "a spa break", "family": "a family holiday",
              "couples": "a romantic getaway", "weddings": "a wedding with rooms for the guests", "long_stay": "a long stay", "groups": "a group trip", "pets": "a holiday with the dog",
              "food": "a food lover's weekend", "city_break": "a city break", "heritage": "a stay somewhere with history and character", "value": "a good-value stay", "luxury": "a luxury treat",
              "accessible": "an accessible stay"}
KIND_PHRASE = {"destination": "a weekend away that is an experience in itself", "countryside": "a quiet countryside break", "resort": "a resort holiday", "spa": "a spa weekend", "coastal": "a stay by the sea",
               "historic": "a stay in a historic building", "boutique": "a stylish boutique stay", "family": "a family holiday", "business": "a business trip", "airport": "a night near the airport",
               "town": "a short break", "budget": "a cheap but decent stay", "apartments": "a longer stay with a kitchen"}


_COMMON = {"a", "an", "the", "our", "its", "their", "great", "good", "award-winning", "wildlife", "fine", "coastal", "conferences", "weddings", "guided", "architect-designed", "after-dark",
           "quiet", "peaceful", "beautiful", "stunning", "luxury", "family", "dog-friendly", "free", "private", "outdoor", "indoor", "fresh", "local", "spa", "golf", "hiking", "walking", "cycling",
           "fishing", "food", "meetings", "events", "views", "sea", "lake", "forest", "nature", "rooms", "suites", "dining", "restaurant", "parties", "safaris", "safari"}


def template_prompts(profile, hotel):
    """Prompts from the profile without any AI: each reason, guest type and kind of stay, asked at the town, region and wider-area level, and about the places guests come for."""
    p = profile or {}
    town, region, area = p.get("town"), p.get("region"), p.get("area")
    lv = [x for x in (area, region, town) if x]
    out = []

    def add(text, angle, why):
        out.append({"text": text, "angle": angle, "why": why, "priority": "core", "kind": "niche", "source": "profile"})
    for i, r in enumerate(p.get("reasons") or []):
        where = lv[i % len(lv)] if lv else town
        first = r.split()[0] if r.split() else ""
        r_ = r[:1].lower() + r[1:] if first[:1].isupper() and first[1:].islower() and first.lower() in _COMMON else r      # 'Wildlife safaris' -> 'wildlife safaris', but "Scandinavia's" stays
        add(f"Which places to stay in {where} are known for {r_}?", "Traveller intent", f"Why guests choose the hotel (its profile): {r}.")
    for i, k in enumerate(p.get("audiences") or []):
        where = lv[(i + 1) % len(lv)] if lv else town
        add(f"Which hotels in {where} are best for {AUD_PHRASE.get(k, k)}?", {"business": "Business travel", "meetings": "Meetings and events", "family": "Families", "couples": "Couples", "weddings": "Weddings",
                                                                                "wellness": "Spa and wellness", "food": "Dining", "pets": "Pet-friendly", "groups": "Groups"}.get(k, "Traveller intent"), f"Its guests (profile): {k}.")
    for k in p.get("kinds") or []:
        for where in lv[:2]:
            add(f"Where should I stay in {where} for {KIND_PHRASE.get(k, 'a short break')}?", "Traveller intent", f"The kind of stay it is (profile): {k}.")
    for a in (p.get("attractions") or [])[:4]:
        add(f"Which hotels are closest to {a}?", "Near a landmark", f"A place its guests come for (profile): {a}.")
        add(f"Where is the best place to stay when visiting {a}?", "Near a landmark", f"A place its guests come for (profile): {a}.")
    if town:
        add(f"Which hotels near {town} do guests rate most highly?", "Neighbourhood", "The town guests search for (profile).")
    return out


PROMPTS_SYSTEM = "You write realistic prompts that travellers type into an AI assistant when choosing where to stay. Never name the hotel. Reply with JSON only."
PROMPTS_PROMPT = """A place to stay. Its owner describes it like this:
- kinds of stay: {kinds}
- why guests choose it: {reasons}
- its guests: {auds}; they come from: {origins}
- price level: {price}
- where it is: town {town}; region {region}; wider area {area}; places guests come for: {attractions}

Write {n} prompts real travellers would type into an AI assistant when they are looking for a stay like this one, WITHOUT knowing about this hotel. Spread them over the levels people search at:
the wider area or the experience itself, the region, the town, and the named places. Mix short searches and longer requests, occasions and constraints. Each must mention one of these places: {places}.
Never name the hotel. In English.
Reply: {{"prompts": [{{"text": "...", "level": "area | region | town | place", "angle": "a few words"}}]}}"""


def prompts_from_profile(profile, hotel_name, client=None, model=None, n=20):
    """
    The recommended set for a hotel from its confirmed profile: the template prompts plus (with a Claude key) AI-written ones, every one checked by the prompt rules (mentions one of the profile's places,
    never names the hotel), near-duplicates dropped, balanced by prompt_sets.recommend_set. -> [prompt dicts].
    """
    import prompt_sets
    p = profile or {}
    anchors = [{"name": x} for x in places(p)]
    pool = []
    if client is not None:
        try:
            import ai_sample
            import review_replies
            model = model or ai_sample.MODEL_DEFAULT
            msg = PROMPTS_PROMPT.format(kinds=", ".join(dict(KINDS).get(k, k) for k in p.get("kinds") or []) or "-", reasons="; ".join(p.get("reasons") or []) or "-",
                                        auds=", ".join(dict(audiences()).get(k, k) for k in p.get("audiences") or []) or "-", origins=p.get("origins") or "-",
                                        price=dict(PRICES).get(p.get("price") or "", "not given"), town=p.get("town") or "-", region=p.get("region") or "-", area=p.get("area") or "-",
                                        attractions=", ".join(p.get("attractions") or []) or "-", places=", ".join(places(p)), n=n + 6)
            resp = client.messages.create(model=model, max_tokens=1800, system=PROMPTS_SYSTEM, messages=[{"role": "user", "content": msg}])
            text, _d, _s, tin, tout = ai_sample.parse_response(resp)
            try:
                import store
                store.record_usage(max(1, round(ai_sample.cost_usd(model, tin, tout, 0) * 1000)), service="claude")
            except Exception:  # noqa: BLE001
                pass
            d = review_replies.parse_json(text)
            for r in (d.get("prompts") if isinstance(d, dict) else None) or []:
                if isinstance(r, dict) and r.get("text"):
                    lvl = str(r.get("level") or "")
                    pool.append({"text": " ".join(str(r["text"]).split()), "angle": {"place": "Near a landmark", "town": "Neighbourhood"}.get(lvl, "Traveller intent"),
                                 "why": f"Written from the hotel's profile ({lvl or 'general'} level).", "priority": "core", "kind": "niche", "source": "profile", "level": lvl})
        except Exception:  # noqa: BLE001 - the templates stand
            pass
    pool += template_prompts(p, hotel_name)
    ok = []
    for q in pool:
        t, err = prompt_sets.check_prompt(q["text"], hotel_name, p.get("town"), anchors)
        if not err:
            ok.append({**q, "text": t})
    return prompt_sets.recommend_set(ok, hotel_name, n=n)


def write_prompts(db, hotel, profile, cfg=None, client=None):
    """Replace the hotel's unconfirmed prompts with a set written from its profile (a confirmed set stays until the hotel confirms the new one). -> number of prompts written."""
    import prompt_sets
    if client is None and getattr(cfg, "anthropic", None):
        try:
            import ai_sample
            client = ai_sample._make_client(cfg.anthropic, timeout=60.0)
        except Exception:  # noqa: BLE001
            client = None
    chosen = prompts_from_profile(profile, hotel["name"], client=client, model=getattr(cfg, "anthropic_model", None))
    if len(chosen) < 3:
        return 0
    st = prompt_sets.state(db, hotel)
    for s in db.prompt_sets(hotel["id"]):
        if s["status"] == "draft":
            db.delete_prompt_set(s["id"])
    db.insert_prompt_set(hotel["id"], "draft", chosen, "profile", base_version=st["active"]["version"] if st["active"] else None)
    return len(chosen)


# ------------------------------------------------------------------------- what the checks use

def facts_for_audit(profile):
    """Owner-stated facts for the question engine ([{kind, text}]): the AI's proposals may rest on them. Marked as stated by the hotel, not verified by us."""
    p = profile or {}
    out = []
    for k in p.get("kinds") or []:
        out.append({"kind": "owner_kind", "text": f"kind of stay (stated by the hotel): {dict(KINDS).get(k, k).lower()}"})
    for r in p.get("reasons") or []:
        out.append({"kind": "owner_reason", "text": f"guests choose it for (stated by the hotel): {r}"})
    for a in p.get("audiences") or []:
        out.append({"kind": "owner_audience", "text": f"its guests (stated by the hotel): {dict(audiences()).get(a, a).lower()}"})
    for x in places(p)[1:]:
        out.append({"kind": "owner_place", "text": f"guests search for it in or near {x} (stated by the hotel)"})
    return out[:14]


def for_report(profile):
    """What a saved check records about the profile it was run with."""
    p = profile or {}
    return {k: p.get(k) for k in ("town", "region", "area", "attractions", "kinds", "reasons", "audiences", "origins", "languages", "price", "competitors", "lat", "lon", "confirmed_at")}


# ------------------------------------------------------------------------- set-up status

def status(db, hotel):
    """(key, label) of where the hotel is in setting up: not_invited, invited, profile, prompts, checked; or legacy hotels: running (with or without a reviewed profile)."""
    prof = load(hotel)
    if hotel.get("setup") != "pending" and hotel.get("setup") != "done":
        return ("running", "Running (set up before profiles)" + ("; profile confirmed" if prof and prof.get("status") == "confirmed" else "; profile to review"))
    runs = db.hotel_runs(hotel["hotel_key"])
    if hotel.get("setup") == "done":
        return ("checked", "First check done") if runs else ("prompts", "Prompts confirmed: first check running or due")
    if prof and prof.get("status") == "confirmed":
        return ("profile", "Profile done: prompts to confirm")
    if db.users_for_hotel(hotel["id"]):
        return ("invited", "Signed in: profile to complete")
    if db.open_invites(hotel["id"]):
        return ("invited", "Invited")
    return ("not_invited", "Not invited yet")


def summary_html(p):
    """The profile as a two-column table (the Settings pages). Empty string when there is no profile."""
    if not p:
        return ""
    import html as _h
    e = _h.escape
    kinds = ", ".join(dict(KINDS).get(k, k) for k in p.get("kinds") or [])
    auds = ", ".join(dict(audiences()).get(k, k) for k in p.get("audiences") or [])
    rows = (("Address", p.get("address")), ("Town", p.get("town")), ("Region", p.get("region")), ("Wider area", p.get("area")), ("Places guests come for", ", ".join(p.get("attractions") or [])),
            ("Kind of stay", kinds), ("Why guests choose you", "; ".join(p.get("reasons") or [])), ("Guests", auds), ("Where they come from", p.get("origins")),
            ("Languages", ", ".join(p.get("languages") or [])), ("Price level", dict(PRICES).get(p.get("price") or "", "")), ("Competitors", ", ".join(p.get("competitors") or [])))
    return ('<div class="table-wrap"><table class="table">' + "".join(f'<tr><th style="text-align:left;width:220px">{e(l)}</th><td>{e(v or "") or "<span class=hk-muted>not given</span>"}</td></tr>' for l, v in rows)
            + "</table></div>")


def last_change(profile):
    p = profile or {}
    return f'confirmed {uk_time(p["confirmed_at"])} by {p.get("confirmed_by") or "?"}' if p.get("confirmed_at") else "not confirmed yet"
