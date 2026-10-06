"""
Three free, bounded checks about how automated visitors meet the hotel's website.

  1. AI-crawler policy   - what robots.txt tells AI crawlers, in plain English (no new request).
  2. llms.txt            - whether the site publishes one (one request). It is an informal proposal,
                           not a standard anyone has to follow, so its absence is never a defect.
  3. Common Crawl        - whether the site's pages are in the public web archive that much AI
                           training data is drawn from, and whether that crawler was REFUSED.
  4. PageSpeed Insights  - mobile speed, accessibility and SEO as Google's Lighthouse measures them.
                           Needs a free key (no billing); without one it reports why and carries on.

What none of this proves: it says nothing about what any AI assistant actually says about the
hotel. Presence in a crawl is not evidence a model "knows" the hotel; a robots.txt rule is a
request that well-behaved crawlers follow, not a lock. The wording below keeps to that.

Every check returns the same envelope as sources.py (status ok / no_results / unavailable /
not_configured, always with a reason) and never raises - a failed check is a gap in what was
assessed, never a failed audit.
"""

import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

import site_check

UA = site_check.UA

# --------------------------------------------------------------- AI-crawler policy

# What each crawler is for - the distinction that decides whether blocking it matters.
AGENT_GROUPS = {
    "training": ("Collects pages to train or improve AI models",
                 ["GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider",
                  "meta-externalagent"]),
    "search": ("Builds the index an AI search or assistant answers from",
               ["OAI-SearchBot", "PerplexityBot", "Amazonbot"]),
    "user": ("Fetches a page live when a person asks an assistant about it",
             ["ChatGPT-User", "Claude-User", "Perplexity-User"]),
}


def ai_policy(robots):
    """Plain-English reading of robots.txt for AI crawlers. Built from the robots check already made."""
    robots = robots or {}
    rules = robots.get("ai_agent_rules") or {}
    out = {"robots_present": bool(robots.get("present")), "blocks_everything": bool(robots.get("blocks_all")), "groups": {}}
    for key, (what, agents) in AGENT_GROUPS.items():
        blocked = [a for a in agents if (rules.get(a) or {}).get("blocked_entirely")]
        out["groups"][key] = {"what": what, "agents": agents, "blocked": blocked}
    g = out["groups"]
    train, search, user = (bool(g[k]["blocked"]) for k in ("training", "search", "user"))
    if not robots.get("present"):
        stance, text = "no_rules", "There is no robots.txt, so no AI crawler has been told to stay away."
    elif robots.get("blocks_all"):
        stance, text = "blocks_all", "robots.txt asks every crawler, including AI crawlers, to stay out of the whole site."
    elif not (train or search or user):
        stance, text = "open", "robots.txt does not single out any AI crawler, so none has been asked to stay away."
    elif train and not (search or user):
        stance, text = ("training_blocked",
                        "robots.txt asks AI training crawlers to stay away but leaves AI search and live-lookup crawlers alone. "
                        "That is a common, deliberate choice about content use.")
    else:
        stance, text = ("search_blocked",
                        "robots.txt asks at least some AI search or live-lookup crawlers to stay away"
                        + (" as well as training crawlers" if train else "")
                        + ", so those assistants may be less able to read the site directly.")
    out["stance"], out["summary"] = stance, text
    out["caveat"] = ("robots.txt is a request that well-behaved crawlers follow, not a lock. A site's firewall can refuse crawlers "
                     "whatever it says, and it cannot tell us what any assistant actually uses.")
    return out


# ------------------------------------------------------------------------ llms.txt

LLMS_NOTE = ("llms.txt is an informal proposal for giving language models a plain-text summary of a site. It is not a standard, "
             "and we found no evidence that the major AI search tools rely on it, so not having one is not a defect.")


def llms_txt(base):
    url = urllib.parse.urljoin(base, "/llms.txt")
    r = site_check.get(url, timeout=15)
    out = {"url": url, "note": LLMS_NOTE}
    if r is None:
        return {**out, "status": "unavailable", "present": None, "reason": "The request for /llms.txt failed, so this was not assessed."}
    ctype = r.headers.get("content-type", "")
    if r.status_code == 200 and "html" not in ctype.lower() and len(r.text.strip()) > 20:
        text = r.text
        links = re.findall(r"\[[^\]]+\]\((https?://[^)\s]+|/[^)\s]*)\)", text)
        return {**out, "status": "ok", "present": True, "reason": "", "bytes": len(text.encode("utf-8", "ignore")),
                "link_count": len(links), "excerpt": text.strip()[:400],
                "has_title": text.lstrip().startswith("#")}
    if r.status_code in (403, 429):
        return {**out, "status": "unavailable", "present": None, "reason": f"The site refused the request (HTTP {r.status_code}), so this was not assessed."}
    return {**out, "status": "no_results", "present": False, "reason": "No llms.txt was found at the usual address."}


# ----------------------------------------------------------------- Common Crawl

CC_ACCESS = (
    "Common Crawl index - free, no key. A public, non-profit archive of the web that many AI training datasets are built from. "
    "We ask it which of this site's pages it captured and what the site answered its crawler. Being captured is not evidence that "
    "any AI model knows or recommends the hotel, and being absent can simply mean the site is small or new.")
CC_INDEX = "https://index.commoncrawl.org/"
CC_LIMIT = 400                      # captures sampled per crawl; enough to see the pattern, bounded on purpose
_CRAWLS_CACHE = {"at": 0.0, "ids": []}


def _crawl_ids(n=2):
    """The most recent crawls, newest first. Cached for an hour - the list changes about monthly."""
    if _CRAWLS_CACHE["ids"] and time.time() - _CRAWLS_CACHE["at"] < 3600:
        return _CRAWLS_CACHE["ids"][:n]
    try:
        r = requests.get(CC_INDEX + "collinfo.json", headers={"User-Agent": UA}, timeout=20)
        ids = [c["id"] for c in r.json() if c.get("id")] if r.status_code == 200 else []
    except (requests.RequestException, ValueError, KeyError):
        ids = []
    if ids:
        _CRAWLS_CACHE.update(at=time.time(), ids=ids)
    return ids[:n]


def _cdx(crawl_id, domain, limit=CC_LIMIT, timeout=40, attempts=3):
    """
    -> (rows or None, error or None). The public index is slow and sheds load with 5xx answers (503 means "slow down"),
    so it is retried with a growing pause. One request at a time: asking for several at once is what gets throttled.
    """
    params = {"url": domain, "matchType": "domain", "output": "json", "limit": limit, "fl": "url,status,timestamp,mime"}
    err = None
    for i in range(attempts):
        try:
            r = requests.get(f"{CC_INDEX}{crawl_id}-index", params=params, headers={"User-Agent": UA}, timeout=timeout)
        except requests.RequestException as e:
            err = f"request failed ({type(e).__name__})"
            time.sleep(3 * (i + 1)) if i < attempts - 1 else None
            continue
        if r.status_code == 404:
            return [], None                              # the index answers 404 when it holds nothing for the domain
        if r.status_code == 200:
            rows = []
            for line in r.text.splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows, None
        err = f"HTTP {r.status_code}"
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(4 * (i + 1)) if i < attempts - 1 else None
    return None, err


def _bucket(status):
    s = str(status or "")
    if s == "200":
        return "ok"
    if s.startswith("3"):
        return "redirect"
    if s in ("401", "403", "429", "451"):
        return "refused"
    if s in ("404", "410"):
        return "notfound"
    if s.startswith("5"):
        return "error"
    return "other"


def summarise_crawl(crawl_id, rows, limit=CC_LIMIT):
    counts = {"ok": 0, "redirect": 0, "refused": 0, "notfound": 0, "error": 0, "other": 0}
    robots_status, home, stamps, paths = None, False, [], set()
    for r in rows:
        b = _bucket(r.get("status"))
        counts[b] += 1
        path = urllib.parse.urlparse(r.get("url", "")).path or "/"
        if path.lower() == "/robots.txt":
            robots_status = str(r.get("status"))
        elif b == "ok" and path in ("/", "/index.html"):
            home = True
        if b == "ok" and path != "/robots.txt" and ("html" in (r.get("mime") or "") or not r.get("mime")):
            paths.add(path)
        if r.get("timestamp"):
            stamps.append(r["timestamp"])
    return {"crawl": crawl_id, "captures": len(rows), "capped": len(rows) >= limit, "counts": counts,
            "robots_status": robots_status, "homepage_captured": home, "pages_captured": len(paths),
            "latest": max(stamps)[:8] if stamps else ""}


def commoncrawl(base, budget_s=40, crawls=2):
    host = (urllib.parse.urlparse(base).netloc or base).lower().split(":")[0]
    domain = host[4:] if host.startswith("www.") else host
    ids = _crawl_ids(crawls)
    if not ids:
        return {"source": "Common Crawl", "status": "unavailable", "access": CC_ACCESS, "items": [], "domain": domain,
                "reason": "Common Crawl's list of crawls could not be reached, so this was not assessed."}
    items, errors, started = [], [], time.time()
    for cid in ids:
        if items and time.time() - started > budget_s:       # the newest crawl is the one that matters; the second only confirms it
            break
        rows, err = _cdx(cid, domain)
        if rows is None:
            errors.append(f"{cid}: {err}")
            continue
        items.append(summarise_crawl(cid, rows))
    if not items:
        return {"source": "Common Crawl", "status": "unavailable", "access": CC_ACCESS, "items": [], "domain": domain,
                "reason": "Common Crawl's index did not answer (" + "; ".join(errors) + "). It is a busy public service, so running the audit again may "
                          "work. This was not assessed."}
    ok = sum(i["counts"]["ok"] for i in items)
    refused = sum(i["counts"]["refused"] for i in items)
    total = sum(i["captures"] for i in items)
    if total == 0:
        return {"source": "Common Crawl", "status": "no_results", "access": CC_ACCESS, "items": items, "domain": domain,
                "reason": f"Common Crawl holds no captures of {domain} in its latest {len(items)} crawl(s). That can mean the site is small "
                          "or new, or that its crawler could not get in; it does not show what any AI model knows."}
    state = "refused" if refused and refused >= ok else ("captured" if ok else "other")
    return {"source": "Common Crawl", "status": "ok", "access": CC_ACCESS, "items": items, "domain": domain, "state": state,
            "pages_captured": max(i["pages_captured"] for i in items), "refused": refused, "reason": "",
            "partial": bool(errors)}


# ------------------------------------------------------------ PageSpeed Insights

PSI_ACCESS = (
    "Google PageSpeed Insights API (Lighthouse) - free; needs a free API key from a Google Cloud project with NO billing account. "
    "Runs a lab test of the homepage on a simulated mid-range phone and reports performance, accessibility, SEO and best-practice "
    "scores. It is one page, one test, one moment: scores vary run to run, and a lab test is not what real guests experience.")
PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_METRICS = (("first-contentful-paint", "First content shown"), ("largest-contentful-paint", "Main content shown"),
            ("total-blocking-time", "Time the page is unresponsive"), ("cumulative-layout-shift", "Layout shift"),
            ("speed-index", "Speed index"))


def pagespeed(url, api_key=None, timeout=75):
    params = [("url", url), ("strategy", "mobile")] + [("category", c) for c in ("PERFORMANCE", "ACCESSIBILITY", "SEO", "BEST_PRACTICES")]
    if api_key:
        params.append(("key", api_key))
    data, code, err = None, None, None
    for attempt in range(2):
        try:
            r = requests.get(PSI_URL, params=params, headers={"User-Agent": UA}, timeout=timeout)
        except requests.RequestException as e:
            code, err = None, f"request failed ({type(e).__name__})"
            continue
        code = r.status_code
        if code == 200:
            try:
                data = r.json()
                err = None
            except ValueError:
                err = "response was not JSON"
            break
        err = f"HTTP {code}"
        if code != 500:                               # 500 is Lighthouse failing on the page; worth one more go
            break
    if data is None:
        if code == 429:
            why = ("Google's PageSpeed quota was used up. " + ("The configured key's daily quota is exhausted."
                                                              if api_key else "A free API key gives this tool its own quota."))
        elif code in (400, 403) and api_key:
            why = "Google rejected the PageSpeed key (check it is correct and that the PageSpeed Insights API is enabled for its project)."
        elif code == 400:
            why = "Google could not test this page (it may be blocking Google's test or not publicly reachable)."
        else:
            why = f"PageSpeed Insights did not answer ({err})."
        status = "not_configured" if (code == 429 and not api_key) else "unavailable"
        if status == "not_configured":
            why += " Page speed and accessibility scores were not assessed."
        return {"source": "PageSpeed Insights", "status": status, "reason": why, "access": PSI_ACCESS, "items": [], "url": url}
    lh = data.get("lighthouseResult") or {}
    cats = lh.get("categories") or {}
    if not cats:
        return {"source": "PageSpeed Insights", "status": "unavailable", "access": PSI_ACCESS, "items": [], "url": url,
                "reason": "Google returned no scores for this page, so speed was not assessed."}
    scores = {k: (None if (cats.get(k) or {}).get("score") is None else int(round(cats[k]["score"] * 100)))
              for k in ("performance", "accessibility", "seo", "best-practices")}
    audits = lh.get("audits") or {}
    metrics = []
    for aid, label in _METRICS:
        a = audits.get(aid) or {}
        if a.get("displayValue"):
            metrics.append({"id": aid, "label": label, "value": a["displayValue"], "score": a.get("score")})
    weak = []
    for ref in (cats.get("accessibility") or {}).get("auditRefs", []) + (cats.get("seo") or {}).get("auditRefs", []) \
            + (cats.get("performance") or {}).get("auditRefs", []):
        a = audits.get(ref.get("id")) or {}
        if a.get("score") is not None and a["score"] < 0.5 and a.get("scoreDisplayMode") in ("binary", "numeric") and ref.get("weight", 0) > 0:
            weak.append({"id": ref["id"], "title": a.get("title", ref["id"]), "group": ref.get("group", ""), "weight": ref.get("weight", 0)})
    weak.sort(key=lambda w: -w["weight"])
    field = (data.get("loadingExperience") or {}).get("overall_category")
    return {"source": "PageSpeed Insights", "status": "ok", "reason": "", "access": PSI_ACCESS, "url": url,
            "final_url": lh.get("finalUrl") or url, "strategy": "mobile", "scores": scores, "metrics": metrics, "weak": weak[:6],
            "field_category": field, "fetched": (lh.get("fetchTime") or "")[:10],
            "items": [scores]}


# ------------------------------------------------------------------ orchestration

def run(base, robots, pagespeed_key=None, progress=None):
    """All of the above, in parallel (PageSpeed and Common Crawl are the slow ones). Never raises."""
    def say(m):
        if progress:
            progress(m)

    def safe(fn, name, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 - a failed extra check must not fail the audit
            return {"source": name, "status": "unavailable", "items": [], "present": None,
                    "reason": f"This check failed unexpectedly ({type(e).__name__}) and was skipped."}

    say("Checking AI-crawler access, Common Crawl and page speed...")
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_cc = ex.submit(safe, commoncrawl, "Common Crawl", base)
        f_ps = ex.submit(safe, pagespeed, "PageSpeed Insights", base, pagespeed_key)
        f_llms = ex.submit(safe, llms_txt, "llms.txt", base)
        res = {"ai_policy": ai_policy(robots), "llms_txt": f_llms.result(), "commoncrawl": f_cc.result(), "pagespeed": f_ps.result()}
    res["version"] = 1
    return res
