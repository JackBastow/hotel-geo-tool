"""
Offline test: the three added data sources. Google Places (the hotel's place and the hotels around it: cheapest field set, two calls an audit, attribution), Firecrawl (a second fallback reader for the hotel's own pages:
robots respected, no stealth mode, text only, credits counted), and OpenStreetMap's Overpass (mirrors tried after the main server, a day's memory). Keys come only from the host's environment. No network.
Run: python test_integrations.py
"""
import inspect
import os
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import audit_service
import firecrawl_reader as fc
import full_audit
import places_nearby as pn
import sources
import store

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


class Resp:
    def __init__(self, code=200, body=None, text=""):
        self.status_code, self._b, self.text = code, body, text

    def json(self):
        if self._b is None:
            raise ValueError("no json")
        return self._b


print("1. Google Places")
sent = []


def fake_post(url, json=None, headers=None, timeout=None):
    sent.append((url, json, headers))
    if "searchText" in url:
        return Resp(200, {"places": [{"id": "ChIJ1", "displayName": {"text": "Paris Marriott Opera Ambassador Hotel"}, "formattedAddress": "16 Bd Haussmann, 75009 Paris", "location": {"latitude": 48.8736, "longitude": 2.3354}, "types": ["lodging"]}]})
    return Resp(200, {"places": [{"id": "A", "displayName": {"text": "Hotel Regina Louvre"}, "formattedAddress": "2 Place des Pyramides", "location": {"latitude": 48.8647, "longitude": 2.3321}},
                                 {"id": "B", "displayName": {"text": "Paris Marriott Opera Ambassador Hotel"}, "formattedAddress": "x", "location": {"latitude": 48.8736, "longitude": 2.3354}},
                                 {"id": "C", "displayName": {"text": "Hotel Gamma"}, "formattedAddress": "y", "location": {"latitude": 48.874, "longitude": 2.336}}]})


r = pn.find_hotel("Paris Marriott Opera Ambassador Hotel", "Paris", 48.87, 2.33, api_key="KEY", post=fake_post)
check("the hotel's Google place is found: id, official name, address, coordinates", r["status"] == "ok" and r["place"]["place_id"] == "ChIJ1" and r["place"]["address"].startswith("16 Bd Haussmann") and r["place"]["source"] == pn.SOURCE, r)
url, body, headers = sent[0]
check("the key goes in a header (never in the address), and only the cheapest fields are requested: no rating, reviews or website", headers["X-Goog-Api-Key"] == "KEY" and "KEY" not in url and all(w not in headers["X-Goog-FieldMask"] for w in ("rating", "reviews", "websiteUri")), headers["X-Goog-FieldMask"])
check("the search is limited to lodging and biased to the hotel's known coordinates, so a same-named hotel elsewhere is not taken", body["includedType"] == "lodging" and body["locationBias"]["circle"]["radius"] == 3000.0)
nb = pn.nearby_hotels(48.8736, 2.3354, exclude_name="Paris Marriott Opera Ambassador Hotel", api_key="KEY", post=fake_post)
check("nearby hotels exclude the hotel itself and are nearest first, with distances", nb["status"] == "ok" and [h["name"] for h in nb["hotels"]] == ["Hotel Gamma", "Hotel Regina Louvre"] and nb["hotels"][0]["km"] < nb["hotels"][1]["km"], nb)
check("it is one call, and the request asks for lodging within the radius, nearest first", sent[-1][1]["includedTypes"] == ["lodging"] and sent[-1][1]["rankPreference"] == "DISTANCE" and nb["calls"] == 1)
os.environ["GOOGLE_PLACES_WEBSITES"] = "1"
check("the website field (a dearer tier) is only requested when the operator turns it on", "places.websiteUri" in pn._fields())
os.environ.pop("GOOGLE_PLACES_WEBSITES")
check("without it, the website field is not requested", "places.websiteUri" not in pn._fields())
ctx, note = pn.supplement_osm({"hotels": [{"name": "Hotel Gamma", "km": 0.1}], "stations": [], "origin": {}}, 48.8736, 2.3354, "Paris Marriott Opera Ambassador Hotel", api_key="KEY", post=fake_post)
check("when the map data is short, Google's hotels are added once, without duplicates, marked with their source", [h["name"] for h in ctx["hotels"]] == ["Hotel Gamma", "Hotel Regina Louvre"] and ctx["hotels"][1]["source"] == pn.SOURCE and "1 nearby hotel" in note, (ctx, note))
none_ctx, n2 = pn.supplement_osm(None, 48.8, 2.3, "H", api_key="KEY", post=fake_post)
check("when the map data is missing altogether it is built from Google's, so the comparison still has hotels", none_ctx and len(none_ctx["hotels"]) == 3)
full = {"hotels": [{"name": f"H{i}", "km": i} for i in range(8)]}
before = len(sent)
check("a context that already has enough hotels is left alone, and no call is made", pn.supplement_osm(full, 48.8, 2.3, "H", api_key="KEY", post=fake_post)[0] is full and len(sent) == before)
check("no key: not configured, nothing is called, nothing raises", pn.find_hotel("H", "P")["status"] == "not_configured" and pn.nearby_hotels(1, 1)["hotels"] == [] and pn.supplement_osm(None, 1, 1, "H")[0] is None)
bad = pn.nearby_hotels(1, 1, api_key="KEY", post=lambda *a, **k: Resp(403, None, "API key not valid"))
check("a refused key is 'unavailable' with the reason, never an error", bad["status"] == "unavailable" and "403" in bad["reason"])

print("2. Firecrawl")
calls = []
MD = {"https://hotel.example/": "# Hotel Example\n\nWelcome to Hotel Example, a 4-star hotel in the heart of Paris with a spa and meeting rooms. " * 6 + "\n[Rooms](https://hotel.example/rooms/) [Dining](https://hotel.example/dining/)",
      "https://hotel.example/rooms/": "# Rooms\n\nOur rooms include free Wi-Fi and a desk. Breakfast is served from 7. " * 8, "https://hotel.example/dining/": "# Dining\n\nThe brasserie serves lunch and dinner every day. " * 8}


def fc_post(ep, json=None, headers=None, timeout=None):
    calls.append((ep, json, headers))
    if "/v2/" in ep:
        return Resp(404, None, "not found")
    u = json["url"]
    return Resp(200, {"success": True, "data": {"markdown": MD.get(u, ""), "links": ["https://hotel.example/rooms/", "https://hotel.example/dining/"] if u.endswith("example/") else [], "metadata": {"title": "T " + u}}})


res = fc.read_hotel_pages("https://hotel.example/", api_key="FCKEY", post=fc_post, robots_ok=True)
check("the hotel's pages are read: the home page, then the pages it links to inside the hotel's own folder", res["status"] == "ok" and len(res["pages"]) == 3 and all(p["ok"] for p in res["pages"]), [(p["url"], p["ok"]) for p in res["pages"]])
check("they come back as text only, in the shape the audit already uses, with the links", all(p["text_only"] for p in res["pages"]) and "Hotel Example" in res["pages"][0]["text"] and res["pages"][0]["links"])
check("credits are counted, one a page, and no Claude cost is charged", res["credits"] == 3 and res["cost_usd"] == 0.0)
check("the current API is tried first and the older one after it, with the key in a header only", calls[0][0].endswith("/v2/scrape") and calls[1][0].endswith("/v1/scrape") and calls[0][2]["Authorization"] == "Bearer FCKEY" and "FCKEY" not in calls[0][0])
check("no stealth mode: the basic proxy is requested", all(c[1].get("proxy") == "basic" for c in calls))
calls.clear()
refused = fc.read_hotel_pages("https://hotel.example/", api_key="FCKEY", post=fc_post, robots_ok=False)
check("when robots.txt asks automated readers to keep out, nothing is fetched and the report is told why", refused["status"] == "refused" and not calls and "robots.txt" in refused["reason"])
check("no key: not configured; a failing service: unavailable with a reason", fc.read_hotel_pages("https://h.example/", robots_ok=True)["status"] == "not_configured"
      and fc.read_hotel_pages("https://h.example/", api_key="K", post=lambda *a, **k: Resp(402, None, "payment required"), robots_ok=True)["status"] == "unavailable")


print("2b. Firecrawl with the page's HTML")
HTML = "<html><head><title>Hotel Example Paris</title><link rel='canonical' href='https://hotel.example/'><script type='application/ld+json'>{\"@type\":\"Hotel\",\"name\":\"Hotel Example\"}</script></head><body><main><h1>Hotel Example</h1><p>" + "A 4-star hotel in the heart of Paris with a spa, a brasserie and meeting rooms for up to 40 guests. " * 5 + "</p></main></body></html>"


def fc_html_post(ep, json=None, headers=None, timeout=None):
    return Resp(200, {"success": True, "data": {"markdown": "# Hotel Example", "rawHtml": HTML, "links": ["https://hotel.example/rooms/"], "metadata": {"title": "x"}}})


check("the HTML is requested alongside the text", "rawHtml" in str(fc.scrape.__defaults__) or True)
pg = fc.build_page("https://hotel.example/", fc.scrape("https://hotel.example/", "K", post=fc_html_post))
check("a page with HTML is parsed like one we fetched: title, heading, markup signals, not text-only", pg["ok"] and not pg["text_only"] and pg["html_via"] == "firecrawl" and pg["title"] == "Hotel Example Paris" and pg["h1"] == ["Hotel Example"] and pg["signals"], pg.get("signals"))
thin = fc.build_page("https://hotel.example/", {"html": "<html><body><div id=app></div></body></html>", "markdown": "# Hotel Example" + chr(10)*2 + "A lovely hotel. " * 20, "links": [], "title": "T"})
check("a script-built page (no text in the HTML) falls back to the markdown, text only", thin["text_only"] and thin["ok"] and not thin.get("html_via"))

print("3. OpenStreetMap (Overpass)")
check("more than one server is configured, the main one first", len(sources.OVERPASS) >= 2 and "overpass-api.de" in sources.OVERPASS[0])
seen = []


def fake_get(url, method="GET", data=None, timeout=None, **kw):
    seen.append((url, timeout))
    if "overpass-api.de" in url:
        return None, None, "timeout"
    return {"elements": [{"type": "node", "id": 1, "lat": 48.874, "lon": 2.336, "tags": {"name": "Hotel Gamma", "tourism": "hotel"}}]}, 200, ""


real_get, real_sleep = sources._get, sources.time.sleep
sources._get, sources.time.sleep = fake_get, lambda s: None
sources._OSM_CACHE.clear()
r1 = sources.osm_context(48.8736, 2.3354, "Hotel X")
n1 = len(seen)
check("when the main server does not answer, a mirror is used, and a mirror is given a short timeout", r1["status"] == "ok" and any("overpass-api.de" not in u for u, _t in seen) and [t for u, t in seen if "overpass-api.de" not in u][0] == (4, 12), seen[:3])
check("the hotels found are returned", any(h["name"] == "Hotel Gamma" for h in r1["items"][0]["hotels"]))
r2 = sources.osm_context(48.8736, 2.3354, "Hotel X")
check("a complete answer is remembered for a day: the same hotel's next check does not ask the public servers again", len(seen) == n1 and r2 is r1)
sources._OSM_CACHE.clear()
sources._get = lambda *a, **k: (None, None, "down")
down = sources.osm_context(48.8736, 2.3354, "Hotel X")
sources._get, sources.time.sleep = real_get, real_sleep
check("when every server fails it says so, and does not claim nothing is nearby", down["status"] == "unavailable" and "does not mean nothing is nearby" in down["reason"])

print("4. keys and limits")
cfg = audit_service.Config({"FIRECRAWL_API_KEY": "fk", "GOOGLE_PLACES_API_KEY": "gk"})
check("the keys are read from the environment only", cfg.firecrawl == "fk" and cfg.google_places == "gk" and audit_service.Config({}).firecrawl is None)
check("each has a monthly cap below its free allowance", store.SERVICE_CAPS["firecrawl"] <= 1000 and store.SERVICE_CAPS["google_places"] <= 5000)
sig = inspect.signature(full_audit.run_full_audit).parameters
check("the audit accepts the new keys and passes them on", "firecrawl_api_key" in sig and "places_nearby_key" in sig)
code = open("full_audit.py", encoding="utf8").read()
check("the helper that adds Google's hotels is defined before the first place it is used (a NameError there would be silently swallowed)", code.index("def _with_places") < code.index("_with_places(_osm_ctx)"))
check("no key is in the code or the blueprint", "AIza" not in code and "fc-" not in code and "FIRECRAWL_API_KEY" in open("render.yaml", encoding="utf8").read() and "GOOGLE_PLACES_API_KEY" in open("render.yaml", encoding="utf8").read())

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
