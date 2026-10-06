"""
Offline tests for web_signals.py: AI-crawler policy, llms.txt, Common Crawl, PageSpeed.
No network: requests and site_check.get are replaced. Run: python test_websignals.py
"""
import json

import web_signals as w

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


class Resp:
    def __init__(self, status=200, text="", headers=None, payload=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def rules(**blocked):
    return {a: {"declared": True, "blocked_entirely": True, "rules": [("disallow", "/")]} for a in blocked}


print("1. AI-crawler policy, in plain English")
p = w.ai_policy({"present": False})
check("no robots.txt: nothing has been asked to stay away", p["stance"] == "no_rules" and "no robots.txt" in p["summary"])
p = w.ai_policy({"present": True, "blocks_all": True, "ai_agent_rules": {}})
check("a blanket Disallow is reported as keeping every crawler out", p["stance"] == "blocks_all")
p = w.ai_policy({"present": True, "blocks_all": False, "ai_agent_rules": {}})
check("robots.txt that never names an AI crawler leaves them all alone", p["stance"] == "open")
p = w.ai_policy({"present": True, "ai_agent_rules": rules(GPTBot=1, CCBot=1, ClaudeBot=1)})
check("blocking only training crawlers is called a deliberate choice, not a defect",
      p["stance"] == "training_blocked" and "deliberate" in p["summary"] and p["groups"]["training"]["blocked"] == ["GPTBot", "ClaudeBot", "CCBot"])
p = w.ai_policy({"present": True, "ai_agent_rules": rules(GPTBot=1, PerplexityBot=1)})
check("blocking an AI search crawler is flagged as making direct reading harder", p["stance"] == "search_blocked" and "may be less able" in p["summary"])
check("the policy always carries the 'a request, not a lock' caveat", "not a lock" in p["caveat"])

print("2. llms.txt")
orig_get = w.site_check.get
w.site_check.get = lambda url, timeout=15: Resp(200, "# Hotel\n> A hotel in Surrey\n- [Rooms](https://x.com/rooms)\n", {"content-type": "text/plain"})
r = w.llms_txt("https://x.com/")
check("a real llms.txt is recognised, with its links counted", r["present"] and r["link_count"] == 1 and r["has_title"])
w.site_check.get = lambda url, timeout=15: Resp(200, "<html>" + "x" * 50 + "</html>", {"content-type": "text/html"})
check("a soft-404 HTML page is NOT mistaken for llms.txt", w.llms_txt("https://x.com/")["present"] is False)
w.site_check.get = lambda url, timeout=15: Resp(404)
r = w.llms_txt("https://x.com/")
check("a missing llms.txt is 'no_results' and the note says that is not a defect", r["status"] == "no_results" and "not a defect" in r["note"])
w.site_check.get = lambda url, timeout=15: Resp(403)
check("a refusal is 'unavailable', never 'absent'", w.llms_txt("https://x.com/")["status"] == "unavailable")
w.site_check.get = lambda url, timeout=15: None
check("a failed request is 'unavailable'", w.llms_txt("https://x.com/")["status"] == "unavailable")
w.site_check.get = orig_get

print("3. Common Crawl")
rows_refused = [{"url": "https://x.com/robots.txt", "status": "403", "timestamp": "20260912070826", "mime": "unk"},
                {"url": "https://x.com/", "status": "403", "timestamp": "20260912070827", "mime": "unk"}]
rows_ok = [{"url": "https://x.com/", "status": "200", "timestamp": "20260910", "mime": "text/html"},
           {"url": "https://x.com/rooms/", "status": "200", "timestamp": "20260910", "mime": "text/html"},
           {"url": "https://x.com/robots.txt", "status": "200", "timestamp": "20260910", "mime": "text/plain"},
           {"url": "https://x.com/old", "status": "301", "timestamp": "20260910", "mime": "text/html"}]
oc, od = w._crawl_ids, w._cdx
w._crawl_ids = lambda n=2: ["CC-MAIN-2026-39", "CC-MAIN-2026-34"]
w._cdx = lambda cid, dom, limit=400, timeout=45, attempts=2: (rows_refused, None)
r = w.commoncrawl("https://www.x.com/")
check("a site that only ever answers the crawler 'forbidden' is reported as refused", r["status"] == "ok" and r["state"] == "refused" and r["refused"] == 4, r)
check("the domain is queried without www", r["domain"] == "x.com")
w._cdx = lambda cid, dom, limit=400, timeout=45, attempts=2: (rows_ok, None)
r = w.commoncrawl("https://x.com/")
check("readable captures are counted per page, excluding robots.txt and redirects", r["state"] == "captured" and r["pages_captured"] == 2, r)
check("the homepage capture is noticed", r["items"][0]["homepage_captured"])
w._cdx = lambda cid, dom, limit=400, timeout=45, attempts=2: ([], None)
r = w.commoncrawl("https://x.com/")
check("no captures is 'no_results' and the wording does not claim AI doesn't know the hotel",
      r["status"] == "no_results" and "does not show what any AI model knows" in r["reason"])
w._cdx = lambda cid, dom, limit=400, timeout=45, attempts=2: (None, "HTTP 504")
r = w.commoncrawl("https://x.com/")
check("an index that times out is 'unavailable', not 'no captures'", r["status"] == "unavailable" and "HTTP 504" in r["reason"])
w._cdx = lambda cid, dom, limit=400, timeout=45, attempts=2: ((rows_ok, None) if cid.endswith("39") else (None, "HTTP 504"))
r = w.commoncrawl("https://x.com/")
check("one crawl answering is enough, and the result is marked partial", r["status"] == "ok" and r["partial"] and len(r["items"]) == 1)
w._crawl_ids = lambda n=2: []
check("no crawl list at all is 'unavailable'", w.commoncrawl("https://x.com/")["status"] == "unavailable")
w._crawl_ids, w._cdx = oc, od

orig_req = w.requests.get
w.requests.get = lambda *a, **k: Resp(404)
check("the index's 404 means 'nothing held for this domain', not an error", w._cdx("CC-MAIN-2026-39", "x.com") == ([], None))
calls = []
w.requests.get = lambda *a, **k: (calls.append(1), Resp(504))[1]
w.time.sleep = lambda s: None
rows, err = w._cdx("CC-MAIN-2026-39", "x.com")
check("a 504 is retried with backoff (three tries), then reported", rows is None and err == "HTTP 504" and len(calls) == 3)
w.requests.get = lambda *a, **k: Resp(200, "\n".join(json.dumps(x) for x in rows_ok))
check("the index's one-JSON-object-per-line output is parsed", len(w._cdx("CC-MAIN-2026-39", "x.com")[0]) == 4)

print("4. PageSpeed Insights")
w.requests.get = lambda *a, **k: Resp(429)
r = w.pagespeed("https://x.com/", None)
check("shared quota exhausted and no key: reported as not configured, with how to fix it",
      r["status"] == "not_configured" and "free API key" in r["reason"] and "not assessed" in r["reason"])
r = w.pagespeed("https://x.com/", "KEY")
check("quota exhausted even WITH a key: unavailable, and the key is never echoed", r["status"] == "unavailable" and "KEY" not in r["reason"])
w.requests.get = lambda *a, **k: Resp(403)
check("a rejected key says so", "rejected" in w.pagespeed("https://x.com/", "KEY")["reason"])
payload = {"lighthouseResult": {
    "finalUrl": "https://x.com/", "fetchTime": "2026-10-06T10:00:00Z",
    "categories": {"performance": {"score": 0.42, "auditRefs": [{"id": "lcp", "weight": 25, "group": "metrics"}]},
                   "accessibility": {"score": 0.77, "auditRefs": [{"id": "color-contrast", "weight": 7, "group": "a11y-color-contrast"}]},
                   "seo": {"score": 0.92, "auditRefs": []}, "best-practices": {"score": 1.0, "auditRefs": []}},
    "audits": {"largest-contentful-paint": {"displayValue": "6.1 s", "score": 0.1},
               "total-blocking-time": {"displayValue": "900 ms", "score": 0.2},
               "color-contrast": {"title": "Low contrast text", "score": 0, "scoreDisplayMode": "binary"},
               "lcp": {"title": "Largest Contentful Paint", "score": 0.1, "scoreDisplayMode": "numeric"}}},
    "loadingExperience": {"overall_category": "SLOW"}}
w.requests.get = lambda *a, **k: Resp(200, payload=payload)
r = w.pagespeed("https://x.com/", "KEY")
check("scores are converted to 0-100", r["status"] == "ok" and r["scores"] == {"performance": 42, "accessibility": 77, "seo": 92, "best-practices": 100}, r.get("scores"))
check("headline metrics and the failing audits are extracted", r["metrics"][0]["value"] == "6.1 s" and any(x["title"] == "Low contrast text" for x in r["weak"]))
check("real-user data is carried when Google has it", r["field_category"] == "SLOW")
check("it is labelled a mobile lab test of one page", r["strategy"] == "mobile" and "lab test" in r["access"])
w.requests.get = lambda *a, **k: Resp(200, payload={"lighthouseResult": {}})
check("an empty answer is 'unavailable', not a zero score", w.pagespeed("https://x.com/", "KEY")["status"] == "unavailable")
w.requests.get = orig_req

print("5. the whole run never raises and never fails the audit")
def boom(*a, **k):
    raise RuntimeError("down")
oc, op, ol = w.commoncrawl, w.pagespeed, w.llms_txt
w.commoncrawl, w.pagespeed, w.llms_txt = boom, boom, boom
res = w.run("https://x.com/", {"present": True, "ai_agent_rules": {}})
check("every check failing still returns a full structure with reasons",
      all(res[k]["status"] == "unavailable" and res[k]["reason"] for k in ("commoncrawl", "pagespeed", "llms_txt")) and res["ai_policy"]["stance"] == "open")
w.commoncrawl, w.pagespeed, w.llms_txt = oc, op, ol
json.dumps(res)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
