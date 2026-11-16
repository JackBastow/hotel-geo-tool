"""
Offline test: the TripAdvisor Content API reader (tripadvisor_check.py) and how its listing joins the listing checks. Fake HTTP, no network, no real key.
Run: python test_tripadvisor.py
"""
import sys
import warnings

sys.modules["streamlit"] = None          # the screens draw through the HTML shim, as on the live site

warnings.filterwarnings("ignore")
import audit_service
import listing_facts
import store
import tripadvisor_check as ta

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


class R:
    def __init__(self, code=200, body=None):
        self.status_code, self._b, self.text = code, body, "SECRET-ECHO"

    def json(self):
        return self._b


sent = []


def fake_get(url, params=None, headers=None, timeout=None):
    sent.append((url, dict(params or {})))
    if url.endswith("/location/search"):
        return R(200, {"data": [{"location_id": "999", "name": "Some Other Hotel", "address_obj": {"city": "Zurich"}},
                                {"location_id": "123", "name": "Hotel Example Zurich", "address_obj": {"city": "Zurich", "postalcode": "8058", "address_string": "1 Main St, Zurich 8058"}}]})
    if url.endswith("/reviews"):
        return R(200, {"data": [{"title": "Great stay", "text": "Lovely breakfast and very helpful staff", "rating": 5, "published_date": "2026-10-20T10:00:00Z", "user": {"username": "PRIVATE NAME"}},
                                {"title": "Noisy", "text": "Noisy room and expensive parking", "rating": 2, "published_date": "2026-10-10T10:00:00Z", "user": {"username": "PRIVATE NAME 2"}}]})
    return R(200, {"location_id": "123", "name": "Hotel Example Zurich", "web_url": "https://www.tripadvisor.com/Hotel_Review-123", "phone": "+41 44 123 45 67", "rating": "4.5", "num_reviews": "812",
                   "ranking_data": {"ranking_string": "#12 of 140 hotels in Zurich"}, "address_obj": {"city": "Zurich", "postalcode": "8058", "address_string": "1 Main St, Zurich 8058"}})


site = {"name": "Hotel Example Zurich", "postcode": "8058", "phone": "41441234567", "place": "Zurich"}
res = ta.lookup("Hotel Example Zurich", "Zurich", 47.4, 8.5, api_key="KEY", site=site, get=fake_get)
li = res["listing"]
check("the right hotel is found among the search results, not the first one returned", res["status"] == "ok" and li["location_id"] == "123", res)
check("name, telephone, postcode, rating, review count, ranking and the link back are read", li["phone"] == "41441234567" and li["postcode"] == "8058" and li["rating"] == 4.5 and li["reviews"] == 812 and "of 140" in li["ranking"] and li["url"].startswith("https://www.tripadvisor.com/"))
check("three calls (search, details, recent reviews), counted", res["calls"] == 3 and [u.rsplit("/", 1)[-1] for u, _p in sent] == ["search", "details", "reviews"])
rc = li["recent"]
check("the recent reviews are summarised as praised and criticised topics, against what the site states", rc["reviews"] == 2 and any(t["topic"] == "breakfast" for t in rc["praised"]) and any(t["topic"] == "noise" for t in rc["criticised"]) and "most recent" in rc["note"], rc)
check("no review text and no reviewer name is kept", "PRIVATE" not in str(res) and "Lovely breakfast" not in str(res) and "expensive parking" not in str(res))
check("the search is limited to hotels and biased to the hotel's coordinates", sent[0][1]["category"] == "hotels" and sent[0][1]["latLong"] == "47.4,8.5")
check("the result names the source for attribution", res["source"] == ta.SOURCE and li["attribution"] == "Data from TripAdvisor")
check("the key is never in the result", "KEY" not in str(res))
import htmlst
import ui_consult
html_ = htmlst.build(ui_consult._tripadvisor_block, {"listing": li})
check("the report shows the rating, ranking, a link back, the source and the recent themes with their caveat", "4.5 of 5" in html_ and "of 140" in html_ and "Data from TripAdvisor" in html_ and "most recent reviews" in html_ and "Hotel_Review-123" in html_, html_[:300])
extra = ta.as_listing(res)
check("it becomes a TripAdvisor listing in the shape the listing checks use", extra["TripAdvisor"]["phone"] == "41441234567" and extra["TripAdvisor"]["official_api"])
lc = listing_facts.build(None, "Hotel Example Zurich", {"fact_sheet": [{"fact": "Telephone", "value": "+41 44 999 99 99"}, {"fact": "Address", "value": "1 Main St, 8058 Zurich"}]}, [], [], {"city": "Zurich", "postcode": "8058"}, extra=extra)
rows = {r["fact"]: r for r in lc["rows"]}
check("with no search passages at all, the official listing is still compared with the website: a different telephone number is reported", rows["Telephone"]["status"] == "differs" and rows["Hotel name"]["status"] == "matches", lc["rows"])
check("without passages and without it, there is nothing to build", listing_facts.build(None, "H", {}, [], [], {}) is None)
wrong = ta.lookup("Hotel Example Zurich", "Zurich", api_key="KEY", site=site, get=lambda *a, **k: R(200, {"data": [{"location_id": "5", "name": "Hotel Example Zurich", "address_obj": {"city": "Vienna", "postalcode": "1010"}}]}))
check("a hotel with the same name in another town is NOT taken for this one, and nothing is compared", wrong["status"] == "unconfirmed" and wrong["listing"] is None and ta.as_listing(wrong) == {})
check("no results is 'not found'", ta.lookup("H", "Z", api_key="K", get=lambda *a, **k: R(200, {"data": []}))["status"] == "not_found")
bad = ta.lookup("H", "Z", api_key="K", get=lambda *a, **k: R(403, None))
check("a refused key is 'unavailable', and the response text (which can echo the request) is not kept", bad["status"] == "unavailable" and "SECRET-ECHO" not in str(bad))
check("no key: not configured, no call, no error", ta.lookup("H", "Z")["status"] == "not_configured")
check("TRIPADVISOR_KEY works as the name too", audit_service.Config({"TRIPADVISOR_KEY": "tk"}).tripadvisor == "tk")
check("the key is read from the environment only, and capped below the free allowance", audit_service.Config({"TRIPADVISOR_API_KEY": "tk"}).tripadvisor == "tk" and audit_service.Config({}).tripadvisor is None and store.SERVICE_CAPS["tripadvisor"] <= 5000)
src = open("full_audit.py", encoding="utf8").read() + open("tripadvisor_check.py", encoding="utf8").read()
check("no key is in the code, and the blueprint has an empty slot for it", "TRIPADVISOR_API_KEY" in open("render.yaml", encoding="utf8").read() and "KEY=" not in src.replace("api_key=", ""))
print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
