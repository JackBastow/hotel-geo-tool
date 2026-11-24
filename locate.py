"""
Where the hotel is, found instead of given up on (code review, Nov 2026).

Six of seven test runs had no map position: the last-resort postcode search ran over the whole page code, scripts and styles included, and took strings like 'V8 3OH' and 'E8E 8EB'
(from minified JavaScript and CSS) for postcodes. Chewton Glen's real OpenStreetMap entry was then rejected because its postcode did not match the fake one, and the hotel was told it
was not on the map. Without a position, nearby competitors and local context were missing from almost every report.

Now:
  1. postcodes are read only from the text a visitor sees, and only in a valid UK format; a registered-office or company address is not the hotel's;
  2. a postcode with no map position is turned into one by postcodes.io (free, official UK postcode data);
  3. otherwise the hotel's name and town are looked up on OpenStreetMap's search (anchors.geocode, which only accepts a result in the hotel's town);
  4. the hotel's own confirmed pin in its profile always wins (full_audit).
"""

import re

_OUT = r"(?:[A-PR-UWYZ][0-9][0-9]?|[A-PR-UWYZ][A-HK-Y][0-9][0-9]?|[A-PR-UWYZ][0-9][A-HJKPSTUW]|[A-PR-UWYZ][A-HK-Y][0-9][ABEHMNPRVWXY])"
_IN = r"[0-9][ABD-HJLNP-UW-Z]{2}"
UK_POSTCODE = re.compile(r"\b(" + _OUT + r")\s?(" + _IN + r")\b")
_HIDDEN = re.compile(r"<(script|style|noscript|svg|template)\b.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_CORPORATE = re.compile(r"registered (?:office|in england|in scotland|in wales|address|company|no\b|number)|company (?:no|number|reg)|vat (?:no|number|reg)|trading as|incorporated", re.I)


def visible_text(html):
    """The words a visitor sees: no scripts, styles, comments or tags."""
    t = _HIDDEN.sub(" ", html or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def postcode_from_pages(pages_html, city=""):
    """-> the hotel's UK postcode ('KT13 0SL') from its pages' visible text, or ''. A postcode near company-registration wording is the company's, not the hotel's; one next to the
    hotel's town is preferred; otherwise the one stated most often."""
    town = (city or "").split(",")[0].strip().upper()
    seen = {}
    for html in pages_html or []:
        t = visible_text(html).upper()
        for m in UK_POSTCODE.finditer(t):
            around = t[max(0, m.start() - 160):m.start()]          # 'Registered office: ...' comes BEFORE the company's postcode
            if _CORPORATE.search(around):
                continue
            pc = f"{m.group(1)} {m.group(2)}"
            s = seen.setdefault(pc, {"n": 0, "town": False})
            s["n"] += 1
            if town and town in t[max(0, m.start() - 80):m.start()]:
                s["town"] = True
    if not seen:
        return ""
    return max(seen.items(), key=lambda kv: (kv[1]["town"], kv[1]["n"]))[0]


def postcode_position(pc, fetch):
    """(lat, lon, town) for a UK postcode from postcodes.io, or None."""
    if not pc or not UK_POSTCODE.fullmatch(pc.upper().strip()):
        return None
    try:
        r = fetch("https://api.postcodes.io/postcodes/" + pc.replace(" ", ""), timeout=10)
        if r.status_code != 200:
            return None
        res = (r.json() or {}).get("result") or {}
        if res.get("latitude") is None:
            return None
        return float(res["latitude"]), float(res["longitude"]), (res.get("admin_district") or res.get("parish") or "")
    except Exception:  # noqa: BLE001
        return None


def fill_position(location, hotel, city, fetch):
    """Give `location` a map position when it has none: from its postcode (postcodes.io), else from the hotel's name and town (OpenStreetMap search). Changes it in place. -> location"""
    if location is None or location.get("lat") is not None:
        return location
    pos = postcode_position(location.get("postcode") or "", fetch)
    if pos:
        location["lat"], location["lon"] = pos[0], pos[1]
        location["position_source"] = "the hotel's postcode (postcodes.io)"
        return location
    if hotel and city:
        try:
            import anchors
            hit = {}
            xy = anchors.geocode(hotel, city, fetch, found=hit)
            if xy and hit:
                location["osm_entry"] = hit
        except Exception:  # noqa: BLE001
            xy = None
        if xy:
            location["lat"], location["lon"] = xy[0], xy[1]
            location["position_source"] = "the hotel's name and town (OpenStreetMap search)"
    return location
