"""
Adaptive reading (reading.py): what is still unverified after the first read, which pages to read for it, the page ledger, Firecrawl's site map, and merging the follow-up profile.
Offline. Run: python test_reading.py
"""
import sys
import warnings

warnings.filterwarnings("ignore")
import fact_profile
import guest_questions
import reading

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


print("1. one limit for every stage")
check("40 pages at most, 25 first (20 lost facts at The Gainsborough), the old fixed read kept for comparison", reading.LIMIT == 40 and reading.FIRST_BATCH == 25 and reading.STANDARD == 25)
import ai_extract
check("the fact profile and the AI reading use the same page limit", fact_profile.MAX_PAGES == reading.LIMIT == ai_extract.MAX_PAGES)

print("2. what is still unverified, and which pages to read for it")
guest = {"questions": [{"id": "cancellation", "state": "not_found"}, {"id": "parking", "state": "answered"}, {"id": "pets", "state": "partial"}]}
prof = {"facilities": {"parking": {"status": "on_site"}}}
feats = [{"key": "spa", "pages": 2}, {"key": "parking", "pages": 3}, {"key": "pool", "pages": 0}]
t = reading.unverified(guest, prof, feats)
check("an unanswered question, a partly answered one, and a facility the pages mention but the profile did not confirm", t == ["cancellation", "pets", "spa"], t)
cands = [{"url": "https://h.com/rooms/deluxe/"}, {"url": "https://h.com/terms-and-conditions/"}, {"url": "https://h.com/dog-friendly/"}, {"url": "https://h.com/spa/"},
         {"url": "https://h.com/spa/treatments/"}, {"url": "https://h.com/blog/x/"}]
urls, why = reading.follow_up(cands, ["https://h.com/", "https://h.com/rooms/deluxe/"], t, 10)
check("the terms page for cancellation, the dogs page for pets, the spa page for the spa", urls == ["https://h.com/terms-and-conditions/", "https://h.com/dog-friendly/", "https://h.com/spa/"], urls)
check("a page already read is never read again", "https://h.com/rooms/deluxe/" not in urls)
check("at most the room left under the limit", len(reading.follow_up(cands, [], t, 1)[0]) == 1)
check("each page says what it was read for", why["https://h.com/spa/"] == ["spa"])

_bad = [{"url": u} for u in ["https://www.carbisbayhotel.co.uk/carbis-bay-gift-shop", "https://g.co.uk/pages/special-offers-early-booking.html", "https://www.carbisbayhotel.co.uk/getting-here",
                              "https://g.co.uk/pages/terms-and-conditions.html"]]
_u, _w = reading.follow_up(_bad, [], ["parking", "cancellation"], 10)
check("a gift shop is never read for parking ('car' in 'carbis'), nor special offers for cancellation ('booking'): whole words only, shops and offers never",
      _u == ["https://www.carbisbayhotel.co.uk/getting-here", "https://g.co.uk/pages/terms-and-conditions.html"], _u)
check("a group's terms page outside the hotel's own section is a policy page; another hotel's is not",
      bool(reading.POLICY_PAGE.search("/terms-and-conditions/")) and bool(reading.OTHER_PROPERTY.search("/en-us/hotels/parlu-le-parisien/policies/")))

print("3. the page ledger")
led = reading.ledger([{"url": "https://h.com/", "ok": True}, {"url": "https://h.com/spa/", "ok": True}, {"url": "https://h.com/menu/", "ok": False, "reason": "HTTP 404"}],
                     ["https://h.com/spa/", "https://h.com/weddings/"], {"https://h.com/spa/": ["spa"]})
st = {x["url"]: (x["status"], x["why"]) for x in led}
check("read, failed (why) and not read (why) are all recorded", st["https://h.com/"][0] == "read" and st["https://h.com/menu/"] == ("failed", "HTTP 404")
      and st["https://h.com/weddings/"][0] == "not read" and "follow-up for spa" in st["https://h.com/spa/"][1], st)

print("4. Firecrawl's site map, kept to the hotel's own pages")


class _R:
    def __init__(self, code, js):
        self.status_code, self._j = code, js

    def json(self):
        return self._j


m = reading.firecrawl_map("https://www.marriott.com/en-us/hotels/parpo/overview/", "k",
                          post=lambda *a, **k: _R(200, {"success": True, "links": [{"url": "https://www.marriott.com/en-us/hotels/parpo/dining/", "title": "Dining"},
                                                                                   "https://www.marriott.com/en-us/hotels/parlu/overview/"]}))
check("the map's links are read (objects or plain addresses)", [x["url"] for x in m] == ["https://www.marriott.com/en-us/hotels/parpo/dining/", "https://www.marriott.com/en-us/hotels/parlu/overview/"], m)
sel = guest_questions.select_pages("https://www.marriott.com/en-us/hotels/parpo/overview/", [], [x["url"] for x in m], 40, start="https://www.marriott.com/en-us/hotels/parpo/overview/")
check("on a brand's website only the hotel's own section is chosen (never another Marriott hotel)", all("/parpo/" in u for u in sel), sel)
check("a failing map call gives nothing, never an error", reading.firecrawl_map("https://x.com/", "k", post=lambda *a, **k: _R(402, {})) == [])

print("5. the follow-up profile is merged into the first")
p1 = {"status": "ok", "facilities": {"parking": {"relations": [{"status": "not_offered", "quote": "No parking.", "url": "u", "note": ""}], "status": "not_offered"}}, "cost_usd": 0.05, "kept": 3, "rejected": 1, "pages_sent": 20}
p2 = {"status": "ok", "facilities": {"parking": {"relations": [{"status": "nearby", "quote": "A public car park is behind us.", "url": "v", "note": ""}]},
                                     "spa": {"relations": [{"status": "on_site", "quote": "Our spa has four treatment rooms.", "url": "w", "note": ""}]}}, "cost_usd": 0.02, "kept": 2, "rejected": 0, "pages_sent": 5}
fact_profile.merge(p1, p2)
check("relationships from both reads are kept, and a new facility is added", [r["status"] for r in p1["facilities"]["parking"]["relations"]] == ["not_offered", "nearby"]
      and p1["facilities"]["spa"]["status"] == "on_site", p1["facilities"])
check("costs and counts add up", p1["cost_usd"] == 0.07 and p1["pages_sent"] == 25 and p1["kept"] == 5)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
