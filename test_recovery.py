"""
Getting the data instead of giving up (code review, Nov 2026). Offline: stand-in fetchers.
  - the hotel's location: postcodes from the visible text only (never scripts or styles), never a registered office, and a map position from the postcode or the name and town;
  - page reading: no image pages, forms or booking widgets; a timeout is tried again; a page that still fails goes to the second reader; failed pages are replaced from a reserve, and a
    replaced page is not counted as a gap in what was read.
Run: python test_recovery.py
"""
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import guest_questions as gq
import locate

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


class Resp:
    def __init__(self, code, data):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


print("1. where the hotel is")
html = ('<script>var a="V8 3OH";</script><style>.x{content:"E8E 8EB"}</style><p>Christchurch Road, New Milton BH25 6QS</p>'
        '<footer>Registered office: 1 King St, London EC1V 9LT</footer>')
check("the postcode stated on the page is found; code strings and the registered office are not (Chewton Glen: 'V8 3OH' was taken for its postcode)",
      locate.postcode_from_pages([html], "New Milton") == "BH25 6QS")
check("a page with postcodes only inside scripts and styles gives none", locate.postcode_from_pages(['<script>"V8 3OH"</script><style>"E8E 8EB"</style>']) == "")
calls = []


def fake_get(url, timeout=10, **kw):
    calls.append(url)
    if "postcodes.io/postcodes/BH256QS" in url:
        return Resp(200, {"result": {"latitude": 50.7455, "longitude": -1.6814, "admin_district": "New Forest"}})
    return Resp(404, {})


loc = {"postcode": "BH25 6QS", "lat": None, "lon": None}
locate.fill_position(loc, "Chewton Glen", "New Milton", fake_get)
check("a postcode without a map position gets one from postcodes.io", loc["lat"] == 50.7455 and "postcodes.io" in loc["position_source"], loc)
loc2 = {"postcode": "", "lat": 51.1, "lon": -0.4}
locate.fill_position(loc2, "X", "Y", fake_get)
check("a position the hotel already has is kept", loc2["lat"] == 51.1)

print("2. which pages are read")
for path, skip in (("/rooms/sea-view-bedroom-jpg/", True), ("/img_2041-2/", True), ("/wedding-enquiry/", True), ("/kontakt/formular/", True), ("/nyhetsbrev/", True),
                   ("/booking/", True), ("/rooms/", False), ("/weddings/", False), ("/the-form-room/", False), ("/meetings-events/", False)):
    check(f"{path} is {'skipped' if skip else 'read'}", bool(gq._SKIP_PATH.search(path)) == skip)

print("3. a page that fails is recovered or replaced")
ok_text = "Our rooms have sea views and king beds. Breakfast is served from 7 to 10. " * 6


def page(url, ok=True, reason="", status=200):
    return {"url": url, "ok": ok, "reason": reason, "status": status if ok or status else None, "text": ok_text if ok else "", "title": "", "h1": [], "tels": [], "mails": [],
            "footer_text": "", "links": [], "signals": {}}


tries = {}
orig = gq.fetch_page


def fake_fetch(url, timeout=gq.FETCH_TIMEOUT):
    tries[url] = tries.get(url, 0) + 1
    if url.endswith("/slow/"):
        return page(url, ok=tries[url] > 1, reason="request failed or timed out", status=None)      # times out once, then answers
    if url.endswith("/script/"):
        return page(url, ok=False, reason="no readable text (probably built with JavaScript, so a plain fetch sees an empty page)")
    if url.endswith("/gone/"):
        return page(url, ok=False, reason="HTTP 500", status=500)
    return page(url)


gq.fetch_page = fake_fetch
tries["https://h.example/slow/"] = 1          # its first attempt (below) already timed out
try:
    pages = [dict(page("https://h.example/"), is_start=True), page("https://h.example/rooms/"),
             page("https://h.example/slow/", ok=False, reason="request failed or timed out", status=None),
             fake_fetch("https://h.example/script/"), fake_fetch("https://h.example/gone/")]
    second = lambda u: page(u) if u.endswith("/script/") else None      # noqa: E731 - the second reader renders the script-built page
    gq._recover_failed(pages, ["https://h.example/spare-1/", "https://h.example/spare-2/"], time.time(), 100, second, lambda m: None)
finally:
    gq.fetch_page = orig
by = {p["url"]: p for p in pages}
check("a page that timed out is asked for again, and read", by["https://h.example/slow/"]["ok"] and by["https://h.example/slow/"].get("retried"))
check("a script-built page goes to the second reader, and is read", by["https://h.example/script/"]["ok"] and by["https://h.example/script/"].get("via_second_reader"))
check("a page that still fails is replaced by the next-best page in reserve", by["https://h.example/gone/"].get("replaced") and any(p.get("replacement") for p in pages))
fin = gq._finish(pages, pages[0], time.time(), {"sitemap": {}}, "https://h.example/", "H", None, [])
check("a replaced page is not counted as a gap: every page attempted was read", fin["pages_attempted"] == fin["pages_ok"] and not fin["pages_failed"], (fin["pages_attempted"], fin["pages_ok"], fin["pages_failed"]))

print("4. a site in another language")
import consultant
_B = "https://www.eriksberg.example/"
_sv = ("Välkommen till Eriksberg Hotell och Naturreservat utanför Karlshamn. Våra rum har utsikt över skärgården och viltparken. Frukost serveras varje morgon i restaurangen. "
       "Boka ditt rum direkt hos oss. Vi har konferenslokaler och erbjuder safari i naturreservatet året runt. ") * 4
_pages = [{"url": _B + p, "title": "Eriksberg Hotell", "text": _sv, "h1": [], "tels": [], "mails": [], "links": [], "signals": {"lang": "sv"}, "footer_text": "", "ok": True}
          for p in ("", "rooms/", "dining/", "meetings/", "faq/", "contact/", "getting-here/", "family/", "accessibility/", "policies/")]


def _run(ai_status):
    guest = {"questions": gq.evaluate(_pages), "conflicts": [], "own_facts_node": {}, "pages_ok": len(_pages), "pages_attempted": len(_pages), "ai_extract": {"status": ai_status}}
    return consultant.analyse(own_pages=_pages, pages_meta=[{"url": p["url"], "ok": True, "status": 200, "title": p["title"], "lang": "sv"} for p in _pages], base=_B,
                              hotel="Eriksberg Hotel & Nature Reserve", city="Karlshamn", location={"lat": 56.17, "lon": 14.86}, guest=guest,
                              site={"robots": {"present": False, "status": 200}, "sitemap": {}}, entities=[], intel=None, osm_ctx=None)


_with = _run("ok")
_without = _run("not_configured")
_q_with = [r for r in _with.get("recommendations") or [] if r.get("source") == "questions"]
_q_without = [r for r in _without.get("recommendations") or [] if r.get("source") == "questions"]
check("with the AI reading (any language), the guest questions are kept, as worth checking, not dropped", _q_with and all(r.get("confidence_label") == "Worth checking" for r in _q_with),
      [(r.get("title"), r.get("confidence_label")) for r in _q_with][:3])
check("without it, a non-English site's unanswered questions are not claimed missing", not _q_without, [r.get("title") for r in _q_without][:3])

print("5. when the public map servers are down")
import sources
_orig_get, _orig_sleep = sources._get, sources.time.sleep


def _fake_get(url, params=None, method="GET", data=None, timeout=None, **kw):
    if "overpass" in url or "interpreter" in url:
        return None, None, "request failed: ReadTimeout"
    if "nominatim" in url and "hotel" == (params or {}).get("q"):
        return [{"osm_type": "way", "osm_id": 1, "lat": "50.746", "lon": "-1.680", "name": "Rival Country House Hotel", "category": "tourism", "type": "hotel", "extratags": {"stars": "4"}}], 200, None
    return [], 200, None


sources._get, sources.time.sleep = _fake_get, (lambda s: None)
sources._OSM_CACHE.clear()
try:
    _ctx = sources.osm_context(50.7455, -1.6814, "Chewton Glen")
finally:
    sources._get, sources.time.sleep = _orig_get, _orig_sleep
_it = (_ctx.get("items") or [{}])[0]
check("nearby hotels come from OpenStreetMap's search instead, and the report says so", _ctx.get("status") == "ok" and any(h["name"] == "Rival Country House Hotel" for h in _it.get("hotels", [])) and _it.get("via_search"),
      (_ctx.get("status"), _ctx.get("reason")))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
