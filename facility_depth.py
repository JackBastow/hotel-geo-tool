"""
How much DETAIL the hotel's own pages give about the facilities it has.

A site that says "we have event space" but gives no sizes, capacities or the kinds of events hosted leaves an AI assistant (and a planner) with nothing to quote: asked "which hotels near X can host a 120-person
gala dinner?", it can only name a hotel whose pages say so. This finds the facilities the pages mention (event and meeting space, spa, restaurant and bar, rooms), then checks which of the details a traveller or an
assistant would need are actually stated, with the exact words found as proof, and lists what is missing. A facility whose pages state most of the details is reported as doing well.

Only what the pages say is used: a detail is "stated" only when a match is found in the text; nothing is guessed, and the example wording uses placeholders for every fact the pages do not give.
"""

import re
import urllib.parse

I = re.I
AREA = r"\b\d[\d,\.]*\s?(?:m²|m2|sq\.?\s?m\b|sqm|square\s?(?:metres|meters|feet|foot)|sq\.?\s?ft|sqft)"
CAPACITY = r"\b(?:up to|seats?|accommodat\w+|capacity(?: of)?|holds?|for)?\s*\d{2,4}\s*(?:guests|delegates|people|persons|pax|seated|standing|covers|attendees)\b"

FACILITIES = {
    "events": {
        "label": "Meeting and event space", "short": "the event space", "min_ok": 5, "min_hits": 2,
        "trigger": r"meeting rooms?|conference (?:rooms?|facilit\w+|centre|center|suites?)|event spaces?|events? (?:venue|rooms?|facilit\w+)|banquet\w*|ballrooms?|function rooms?|boardrooms?|wedding (?:venue|suite|room)|private dining|meetings? (?:and|&) events?|events? (?:and|&) meetings?",
        "path": r"meeting|event|conference|wedding|function|banquet|venue|celebrat|private-?dining|ballroom",
        "details": [
            ("size", "The size of each space", AREA, "[room name]: [x] m² ([y] sq ft)"),
            ("capacity", "How many people each space holds", CAPACITY, "capacity [n] guests"),
            ("layouts", "Capacity by layout (theatre, boardroom, banquet, cabaret, reception)", r"\b(?:theat(?:re|er)|boardroom|classroom|cabaret|u-?shape|banquet|reception|hollow square|dinner)\b[^.]{0,40}\d{2,4}|\d{2,4}[^.]{0,40}\b(?:theat(?:re|er)|boardroom|classroom|cabaret|u-?shape|banquet|reception)\b", "theatre [n], boardroom [n], banquet [n], cabaret [n], reception [n]"),
            ("types", "The kinds of events hosted (weddings, galas, conferences, launches, dinners)", r"(?:weddings?|galas?|conferences?|exhibitions?|product launch\w*|awards? (?:dinner|ceremon\w+)|birthday|christening|bar mitzvah|private dinners?|workshops?|seminars?|training (?:days?|courses?)|team[- ]building|christmas parties|anniversar\w+)", "weddings, galas, conferences, product launches, private dinners"),
            ("names", "Each space named, so it can be asked about by name", r"\b[A-Z][a-zé]+(?:\s[A-Z][a-zé]+)?\s(?:Room|Suite|Hall|Ballroom|Salon|Boardroom|Terrace|Pavilion|Lounge|Studio)\b", "[name of room]"),
            ("av", "Equipment included (screens, projector, microphones, stage, Wi-Fi)", r"\b(?:projector|screens?|audio[- ]?visual|\bAV\b|microphones?|stage|lectern|flip ?chart|video[- ]?conferenc\w+|PA system|wi-?fi|lighting)\b", "[equipment included]"),
            ("catering", "Catering for events (menus, coffee breaks, canapés, buffet)", r"\b(?:catering|coffee breaks?|buffet|canap[eé]s?|banquet menus?|set menus?|lunch|drinks reception|packages?)\b", "[catering options]"),
            ("enquire", "A named way to enquire, or a capacity chart or brochure to download", r"\b(?:events team|sales team|enquir\w+|request a (?:proposal|quote|brochure)|capacity chart|floor ?plans?|fact ?sheet|brochure|download)\b", "[events email or phone] / [link to capacity chart]"),
        ]},
    "spa": {
        "label": "Spa and wellness", "short": "the spa", "min_ok": 3, "min_hits": 4,
        "trigger": r"\bspa\b|wellness|massages?|saunas?|steam rooms?|treatments?",
        "path": r"spa|wellness|treatment",
        "details": [
            ("treatments", "The treatments offered", r"\b(?:massages?|facials?|body (?:wraps?|scrubs?)|manicures?|pedicures?|aromatherapy|reflexology)\b", "[list of treatments]"),
            ("hours", "Opening hours", r"\b(?:open|opening hours|daily|monday|from)\b[^.]{0,40}\b\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)?\s?(?:-|to|until|–)\s?\d{1,2}", "open [days], [hh:mm] to [hh:mm]"),
            ("prices", "Prices or a price list", r"[£€$]\s?\d{2,4}", "from [price]"),
            ("facilities", "The facilities (pool, sauna, steam room, hot tub, gym)", r"\b(?:pool|sauna|steam room|hot tub|jacuzzi|relaxation (?:room|area)|thermal)\b", "[pool, sauna, steam room]"),
            ("access", "Whether non-residents can book, and how", r"\b(?:non-?residents?|day (?:guests?|pass|spa)|external guests?|book(?:ing)?(?: in advance| a treatment| online)?|reserv\w+)\b", "open to [residents / day guests]; book [how]"),
            ("rules", "Age limits and what to bring", r"\b(?:over \d+|aged \d+|under \d+|age limit|minimum age|bring|robes?|towels?)\b", "[age policy]; [robes and towels provided]"),
        ]},
    "restaurant": {
        "label": "Restaurant and bar", "short": "the restaurant", "min_ok": 3, "min_hits": 4,
        "trigger": r"\brestaurants?\b|\bbrasserie\b|\bbistro\b|\bdining\b|\bbar and grill\b|\blounge bar\b",
        "path": r"dining|restaurant|bar|eat|food|menu|brasserie",
        "details": [
            ("cuisine", "The style of food", r"\b(?:cuisine|british|french|italian|asian|mediterranean|seasonal|locally sourced|grill|steak|seafood|tapas|fine dining|a la carte|à la carte)\b", "[style of food]"),
            ("hours", "Opening hours and breakfast, lunch, dinner times", r"\b(?:breakfast|lunch|dinner|served|open)\b[^.]{0,50}\b\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)?\s?(?:-|to|until|–)\s?\d{1,2}", "breakfast [times], lunch [times], dinner [times]"),
            ("menu", "A menu, or example dishes and prices", r"\b(?:menus?|a la carte|à la carte|tasting menu|set menu|sample menu)\b|[£€$]\s?\d{1,3}", "[link to menu]"),
            ("diet", "Dietary options (vegetarian, vegan, gluten-free, allergies)", r"\b(?:vegetarian|vegan|gluten[- ]free|allerg\w+|halal|kosher|dairy[- ]free)\b", "[dietary options]"),
            ("booking", "How to book a table, and whether non-residents are welcome", r"\b(?:reserv\w+|book (?:a )?table|table booking|non-?residents?|walk-?ins?|open to the public)\b", "book [how]; open to non-residents"),
            ("awards", "Awards, ratings or the chef (what makes it worth choosing)", r"\b(?:rosette|michelin|award[- ]winning|chef|head chef|aa\b|good food guide)\b", "[chef / award]"),
        ]},
    "rooms": {
        "label": "Rooms and suites", "short": "the rooms", "min_ok": 3, "min_hits": 999,          # only judged from a page about the rooms themselves
        "trigger": r"\b(?:rooms?|suites?|accommodation)\b",
        "path": r"room|suite|accommodation|stay",
        "details": [
            ("types", "Each room type named", r"\b(?:deluxe|superior|executive|classic|standard|family|twin|double|junior suite|signature|premier|studio)\s(?:room|suite|king|queen|twin|double)", "[room type]"),
            ("size", "The size of each room type", AREA, "[x] m² ([y] sq ft)"),
            ("beds", "The beds in each type (king, queen, twin, sofa bed)", r"\b(?:king|queen|twin|double|single|sofa ?bed|bunk)(?:[- ]size(?:d)?)?\s(?:beds?|bed)\b|\b(?:king|queen)-?size\b", "[bed type]"),
            ("occupancy", "How many people each type sleeps", r"\b(?:sleeps?|up to \d+ (?:guests|adults|people)|max(?:imum)? occupancy|\d+ adults?)\b", "sleeps [n]"),
            ("features", "In-room features (air conditioning, desk, bath, view, balcony)", r"\b(?:air[- ]?con\w*|desk|bathtub|walk-in shower|balcony|terrace|view|minibar|safe|kettle|nespresso)\b", "[features]"),
        ]},
}


def _norm(t):
    return " ".join(str(t or "").split())


def _context(text, m, before=90, after=190):
    a, b = max(0, m.start() - before), min(len(text), m.end() + after)
    seg = text[a:b]
    if a > 0:
        seg = seg[seg.find(" ") + 1:] if " " in seg[:40] else seg
    if b < len(text) and " " in seg:
        seg = seg[: seg.rfind(" ")]                      # never end on half a word
    return _norm(seg)


def analyse(site):
    """-> [{key, label, short, pages: [urls], dedicated: bool, found: [{key, label, quote, url}], missing: [{key, label, example}], total, thin, quote, url, names: [...]}], one per facility the pages mention.
    `site` is insight_content.Site (its content_pages carry each page's text)."""
    out = []
    pages = [(p["url"], _norm(p.get("text") or "")) for p in getattr(site, "content_pages", []) if p.get("text")]
    for key, f in FACILITIES.items():
        trig = re.compile(f["trigger"], I)
        pth = re.compile(f["path"], I)
        hits = []
        for url, text in pages:
            n = len(trig.findall(text))
            if n:
                hits.append((url, text, n, bool(pth.search(urllib.parse.urlparse(url).path))))
        if not hits:
            continue
        dedicated = [h for h in hits if h[3] and h[2] >= 1]
        total_hits = sum(h[2] for h in hits)
        if not dedicated and total_hits < f["min_hits"]:
            continue                                                     # a single passing mention is not a facility the hotel promotes
        use = dedicated or sorted(hits, key=lambda h: -h[2])[:3]        # the page(s) about the facility; the details must be there
        found, missing, names = [], [], []
        for dkey, dlabel, rx, example in f["details"]:
            rg = re.compile(rx) if dkey == "names" else re.compile(rx, I)
            hit = None
            for url, text, _n, _d in use:
                m = rg.search(text)
                if m:
                    hit = (url, _context(text, m), m.group(0))
                    break
            if hit:
                found.append({"key": dkey, "label": dlabel, "quote": hit[1], "url": hit[0], "match": hit[2]})
            else:
                missing.append({"key": dkey, "label": dlabel, "example": example})
            if dkey == "names":
                names = sorted({re.sub(r"^(?:The|Our)\s+", "", m.group(0)) for url, text, _n, _d in use for m in rg.finditer(text)})[:6]
        url0, text0, _n0, _d0 = use[0]
        m0 = trig.search(text0)
        out.append({"key": key, "label": f["label"], "short": f["short"], "pages": [u for u, *_r in use][:4], "dedicated": bool(dedicated), "found": found, "missing": missing,
                    "total": len(f["details"]), "thin": len(found) < f["min_ok"], "quote": _context(text0, m0) if m0 else "", "url": url0, "names": names})
    return out
