"""
Offline tests for entry.py and the address handling around it (the Pullman Cannes Mandelieu failure): a chain page whose real address ends in a file name (index.en.shtml) answers 200, while the folder it
sits in answers 404. A fake web stands in for the network, so the exact requests the audit makes can be listed.
Run: python test_entry.py
"""
from types import SimpleNamespace as NS

import entry
import guest_questions as gq
import insight_content as ic
import site_check
import urlscope

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


EXACT = "https://all.accor.com/hotel/1168/index.en.shtml"
FOLDER = "https://all.accor.com/hotel/1168/"
BODY = ("<html><head><title>Pullman Cannes Mandelieu Royal Casino</title></head><body><h1>Pullman Cannes Mandelieu Royal Casino</h1>"
        "<p>" + "Beachfront hotel with a spa, a casino and 190 rooms, near Cannes airport. Parking is available for guests at EUR 25 per night. " * 5 + "</p>"
        '<a href="/hotel/1168/services.en.shtml">Services</a> <a href="/hotel/1168/restaurants.en.shtml">Restaurants</a> <a href="/hotel/9999/index.en.shtml">Another hotel</a></body></html>')


class Web:
    """Answers 200 only for the addresses in `ok`; 404 for everything else on the host; records every request."""
    def __init__(self, ok, nothing=False, refuse=False):
        self.ok, self.nothing, self.refuse, self.calls = set(ok), nothing, refuse, []

    def get(self, url, timeout=25):
        self.calls.append(url)
        if self.nothing:
            return None
        if url in self.ok:
            return NS(status_code=200, text=BODY, url=url, headers={"Content-Type": "text/html"}, content=BODY.encode())
        return NS(status_code=403 if self.refuse else 404, text="Not found", url=url, headers={"Content-Type": "text/html"}, content=b"Not found")


print("1. the address is kept as pasted")
check("a file name and the page's own query survive; tracking and the fragment go", urlscope.clean_entry("https://All.Accor.com/hotel/1168/index.en.shtml?utm_source=x&msockid=abc&lang=en#top")
      == "https://all.accor.com/hotel/1168/index.en.shtml?lang=en")
check("no scheme: https is assumed and nothing else changes", urlscope.clean_entry("all.accor.com/hotel/1168/index.en.shtml") == EXACT)
check("the scope is still the hotel's own folder", urlscope.normalise(EXACT) == (FOLDER, "/hotel/1168/"))
forms = [u for u, _w in urlscope.address_forms(EXACT)]
check("other forms come after the exact one, in a fixed order, including the folder", forms[0] == EXACT and FOLDER in forms and forms.index(EXACT) < forms.index(FOLDER), forms)
check("a folder and its index file are one page", urlscope.canon_index("/hotel/1168/index.en.shtml") == "/hotel/1168/" and urlscope.canon_index("/rooms/index.php") == "/rooms/" and urlscope.canon_index("/rooms/") == "/rooms/")
check("so the site's own page lookup treats them as one (home page found whichever way it is written)", ic._key(EXACT) == ic._key(FOLDER))

print("2. the exact address is requested first, and when it works nothing else is needed")
w = Web([EXACT])
r = entry.resolve(EXACT, fetch=w.get)
check("it is the first request, and the only one", w.calls == [EXACT], w.calls)
check("it is the start page, via 'submitted', with no note", r["ok"] and r["home_url"] == EXACT and r["via"] == "submitted" and r["note"] == "", str(r))
check("the log records the request and the answer", r["log"][0]["url"] == EXACT and r["log"][0]["status"] == 200 and r["log"][0]["bytes"] > 0)

print("3. when the exact address fails, other forms are tried in order and logged")
w = Web([FOLDER])
r = entry.resolve(EXACT, fetch=w.get)
check("the exact one was tried first, then the folder", w.calls[0] == EXACT and FOLDER in w.calls and w.calls.index(FOLDER) > 0, w.calls)
check("the folder is used, and the report says why", r["ok"] and r["home_url"] == FOLDER and r["via"] == "variant" and "did not answer" in r["note"], str(r))

print("4. an alternative is taken only from the site's own sitemap, inside this hotel's folder")
SITEMAP = ["https://all.accor.com/hotel/9999/index.en.shtml", "https://all.accor.com/hotel/1168/services.en.shtml", "https://other.com/hotel/1168/x.html"]
w = Web(["https://all.accor.com/hotel/1168/services.en.shtml", "https://all.accor.com/hotel/9999/index.en.shtml"])
r = entry.resolve(EXACT, sitemap_urls=SITEMAP, fetch=w.get)
check("a page of this hotel from the sitemap is used", r["ok"] and r["via"] == "alternative" and r["home_url"].endswith("/hotel/1168/services.en.shtml"), str(r))
check("another hotel's page and another website's page are never tried", "https://all.accor.com/hotel/9999/index.en.shtml" not in w.calls and "https://other.com/hotel/1168/x.html" not in w.calls, w.calls)
check("the report names the page it used and where it came from", "sitemap" in r["note"] and "services.en.shtml" in r["note"])

print("5. when nothing can be read it says so, and blames the reader, not the hotel")
w = Web([])
r = entry.resolve(EXACT, sitemap_urls=[], fetch=w.get)
check("not ok, no start page, every request logged", not r["ok"] and r["home_url"] == "" and len(r["log"]) == len(w.calls) >= 2, str(r["log"]))
check("the note describes what this tool received and reports no broken page", "what this tool's reader received" in r["note"] and "no 'broken page' is reported" in r["note"])
r = entry.resolve(EXACT, fetch=Web([], nothing=True).get)
check("no answer at all is handled", not r["ok"] and all(x["status"] is None for x in r["log"]))

print("6. an ordinary site: the front page first (a pasted inner page means 'my website'), then the page as pasted")
HOTEL_PAGE = "https://www.somehotel.co.uk/rooms/deluxe.html"
w = Web([HOTEL_PAGE])
r = entry.resolve(HOTEL_PAGE, fetch=w.get)
check("front page asked first, the pasted page second, and used", w.calls[:2] == ["https://www.somehotel.co.uk/", HOTEL_PAGE] and r["ok"] and r["home_url"] == HOTEL_PAGE, w.calls)

print("7. the whole site check starts from the address as submitted and logs every request")
w = Web([EXACT, "https://all.accor.com/hotel/1168/services.en.shtml", "https://all.accor.com/hotel/1168/restaurants.en.shtml"])
site_check_get = site_check.get
site_check.get = w.get
try:
    st = site_check.run_site_check(EXACT)
finally:
    site_check.get = site_check_get
m = st["meta"]
check("the entry address is the one submitted, the start is the same page, the folder is only the scope", m["entry_url"] == EXACT and m["home_url"] == EXACT and m["base"] == FOLDER and m["scope"] == "/hotel/1168/", str(m))
check("the first page requested after robots.txt is the exact address", EXACT in w.calls and w.calls.index(EXACT) < w.calls.index(FOLDER) if FOLDER in w.calls else EXACT in w.calls, w.calls)
check("the fetch log is kept in the report", m["fetch_log"] and m["fetch_log"][0]["url"] == EXACT and m["fetch_log"][0]["status"] == 200)
check("the home page was read", st["pages"][0]["ok"] and st["pages"][0]["url"] == EXACT, str(st["pages"][0])[:200])

print("8. the crawl reads more than one page from there")
w = Web([EXACT, "https://all.accor.com/hotel/1168/services.en.shtml", "https://all.accor.com/hotel/1168/restaurants.en.shtml"])
gq_get = gq.get
gq.get = w.get
gq._CACHE.clear()
try:
    g = gq.run({"meta": {"home_url": EXACT, "entry_url": EXACT, "base": FOLDER, "scope": "/hotel/1168/"}, "sitemap_urls": []}, FOLDER, "Pullman Cannes Mandelieu Royal Casino")
finally:
    gq.get = gq_get
rows = {r["url"]: r for r in g["pages_meta"]}
check("the start page is the exact address, read OK, and flagged as the start", rows[EXACT]["ok"] and rows[EXACT]["is_start"] and rows[EXACT]["status"] == 200, str(rows.get(EXACT)))
check("the folder form was never requested", FOLDER not in w.calls and FOLDER.rstrip("/") not in w.calls, w.calls)
check("its own links were followed (and another hotel's page was not)", g["pages_ok"] >= 3 and "https://all.accor.com/hotel/9999/index.en.shtml" not in w.calls, f"{g['pages_ok']} {w.calls}")

print("9. a failed page is asked for again before it can be called broken, and only then if the audit could not be the cause")
rows_ = [{"url": EXACT, "ok": True, "status": 200, "is_start": True}, {"url": FOLDER + "gone.en.shtml", "ok": False, "status": 404, "retested": True},
         {"url": FOLDER + "x/", "ok": False, "status": 404}, {"url": FOLDER + "y/", "ok": False, "status": 403, "retested": True}]
check("404 asked for again and still failing: credible", entry.credible_error(rows_[1], rows_))
check("404 not asked for again: not credible", not entry.credible_error(rows_[2], rows_))
check("403 is bot protection: not credible", not entry.credible_error(rows_[3], rows_))
check("when the start page was not read, nothing is credible", not entry.credible_error(rows_[1], [dict(rows_[0], ok=False)] + rows_[1:]))
check("the start page itself is never reported", not entry.credible_error({"url": EXACT, "ok": False, "status": 404, "retested": True, "is_start": True}, rows_))
w = Web([FOLDER + "page"])
pg = {"url": FOLDER + "page/", "ok": False, "status": 404, "reason": "HTTP 404"}
got = entry.retest(pg, w.get, parse=gq._recover)
check("a page that answers in another form of its address is recovered and read", got and pg["ok"] and pg["status"] == 200 and pg["retested"], str(pg)[:200])

print("10. a hotel's own pages on its chain's other addresses are read, and only those")
LINKS = ["https://spa.accor.com/en/hotels/1168", "https://restaurantsandbars.accor.com/en/restaurant/1168_R002", "https://meetings.accor.com/hotel/1168/index.en.shtml#section-meetings",
         "https://meetings.accor.com/hotel/1168/index.en.shtml", "https://spa.accor.com/en/hotels/11680", "https://spa.accor.com/en/hotels/9999", "https://all.accor.com/hotel/1168/index.fr.shtml",
         "https://all.accor.com/booking/en/accor/hotel/1168?x=1", "https://www.facebook.com/1168", "https://all.accor.com/a/en/brands.html", "android-app://com.accor/hotel/1168",
         "https://www.example.com/hotel/1168/"]
sel = gq.select_pages(FOLDER, LINKS, [], 12, start=EXACT)
check("the start page, then the spa, restaurant and meetings pages that carry the hotel's id", sel == [EXACT, "https://restaurantsandbars.accor.com/en/restaurant/1168_R002", "https://spa.accor.com/en/hotels/1168",
                                                                                                       "https://meetings.accor.com/hotel/1168/index.en.shtml"], sel)
check("a longer id, another hotel, the same page in another language, booking paths, other websites and app links are not taken", len(sel) == 4)
check("the id must be a whole token", not urlscope.is_sibling("https://spa.accor.com/en/hotels/11680", "all.accor.com", "/hotel/1168/") and urlscope.is_sibling("https://spa.accor.com/en/hotels/1168", "all.accor.com", "/hotel/1168/"))
check("a site with no identifier in its folder gets no siblings", not urlscope.is_sibling("https://spa.accor.com/en/hotels/1168", "all.accor.com", None))
check("registered domains, including two-part endings", urlscope.registered_domain("spa.accor.com") == "accor.com" and urlscope.registered_domain("www.somehotel.co.uk") == "somehotel.co.uk")

print("11. a page that redirects to a booking tool is not judged as the hotel's page, and interface labels are not places")
import places
FUNNEL = "https://events.accor.com/funnel/en/hotel/1168"
MEET = "https://meetings.accor.com/hotel/1168/index.en.shtml"
class Redirect(Web):
    def get(self, url, timeout=25):
        self.calls.append(url)
        html = '<html><head><meta name="robots" content="noindex"></head><body><div id="app"></div></body></html>'
        return NS(status_code=200, text=html * 5, url=FUNNEL, headers={"Content-Type": "text/html"}, content=b"x")
gq_get = gq.get
gq.get = Redirect([]).get
gq._CACHE.clear()
try:
    pg = gq.fetch_page(MEET)
finally:
    gq.get = gq_get
check("the redirected page is not read, says why, and carries no noindex or script-shell signal", not pg["ok"] and "booking tool" in pg["reason"] and not pg["signals"].get("noindex") and not pg["signals"].get("js_shell"), str(pg)[:200])
check("'Filters Railway station' (a map filter label) is not a station", places.find("Filters Railway station Bus stop Airport", "station", "Pullman Cannes Mandelieu") == [])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
