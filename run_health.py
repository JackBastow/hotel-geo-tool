"""
What did not work in a check, for the operator only (the admin hotel page and the admin run page). Hotels never see this: their report says, in plain words, what could not be
checked, and the technical reason lives here.

issues(rep) -> [{"level": "big" | "minor", "what": short headline, "detail": what happened and what it affects}], biggest first.
scrub(rep) -> a copy of the report with technical wording (readers, Firecrawl, API keys, timeouts, error names) taken out of the text a hotel sees.
"""

import copy
import re

# wording that belongs to the operator, not the hotel: how the pages were fetched, which service failed, error names
TECH = re.compile(r"Firecrawl|Anthropic|\bAPI\b|API key|\bquota\b|\bcredits?\b|this tool'?s own reader|our own reader|the (?:first|second|fallback) reader|fallback reader|second reader|page reader"
                  r"|refused (?:this tool|our reader|the reader)|rendered (?:by|through) |timed out|time limit|could not be started|did not finish|was not run\b|step error"
                  r"|\((?:[A-Z][A-Za-z]+(?:Error|Exception|Timeout)|Timeout\w*|ConnectionError|HTTPError)\)|\bHTTP \d{3}\b|\bstatus code\b|server error|stack trace", re.I)
_KEEP_KEYS = {"quote", "snippet", "text", "answer", "title", "url", "question", "says", "passage", "value", "name", "label", "evidence_quote"}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"'])")


def _clean(s):
    if not isinstance(s, str) or not TECH.search(s):
        return s
    kept = [x for x in _SENT.split(s) if not TECH.search(x)]
    return " ".join(kept).strip()


def _walk(o, key=""):
    if isinstance(o, dict):
        return {k: (v if k in _KEEP_KEYS else _walk(v, k)) for k, v in o.items()}
    if isinstance(o, list):
        return [_walk(x, key) for x in o]
    if isinstance(o, str):
        return _clean(o)
    return o


def scrub(rep):
    """The report as the hotel sees it: the same findings, without the operator's technical wording. The stored report is not changed."""
    out = _walk(copy.deepcopy(rep or {}))
    out.pop("step_errors", None)
    gq = out.get("guest_questions")
    if isinstance(gq, dict):
        for k in ("read_via", "own_reader_refused", "page_reader_note", "firecrawl", "fc_note"):
            gq.pop(k, None)
    return out


def issues(rep):
    """The things a person should know went wrong or ran thin in this check, biggest first."""
    rep = rep or {}
    out = []

    def add(level, what, detail):
        out.append({"level": level, "what": what, "detail": detail})

    meta = rep.get("meta") or {}
    loc = meta.get("location") or {}
    gq = rep.get("guest_questions") or {}
    cons = rep.get("consultant") or {}
    cov = cons.get("coverage") or {}
    ok, tried = gq.get("pages_ok") or 0, gq.get("pages_attempted") or 0
    # ---- reading the hotel's own site
    if tried and ok < 5:
        add("big", f"Only {ok} of the hotel's pages could be read", f"{ok} of {tried} pages read. Facts the hotel states on other pages are reported as 'could not check'. "
            + (f"Our reader was refused by the site ({', '.join(str(x) for x in (gq.get('own_reader_refused') or [])[:2])})." if gq.get("own_reader_refused") else ""))
    elif tried and ok < tried:
        add("minor", f"{tried - ok} of {tried} pages could not be read", ", ".join(str((p or {}).get("url", p))[-60:] for p in (gq.get("pages_failed") or [])[:4]))
    if gq.get("read_via"):
        add("minor", f"Pages read through {gq['read_via'].replace('_', ' ')}", (gq.get("page_reader_note") or gq.get("fc_note") or "the site refused this tool's own reader")[:300])
    fc = gq.get("firecrawl") or {}
    if fc and fc.get("status") not in (None, "ok"):
        add("big", "Firecrawl did not work", str(fc.get("reason") or fc.get("status"))[:300])
    # ---- the fact profile (one answer per facility)
    fp = rep.get("fact_profile") or {}
    if fp and fp.get("status") != "ok":
        add("big", "The facilities were judged by word rules, not the verified AI reading", str(fp.get("reason") or fp.get("status"))[:300])
    elif fp:
        if fp.get("rejected", 0) >= max(3, fp.get("kept", 0)):
            add("minor", f"{fp['rejected']} of the AI reading's answers failed the quotation check", "; ".join(f"{k}: {v}" for k, v in (fp.get("reasons") or {}).items()))
        said_both = [q["id"] for q in (gq.get("questions") or []) if q.get("contradiction")]
        if said_both:
            add("minor", "The hotel's pages contradict themselves about " + ", ".join(said_both), "Shown to the hotel as 'needs checking' with both quotations: "
                + "; ".join(f"“{q['contradiction']['says_offered'][:60]}” vs “{q['contradiction']['says_not'][:60]}”" for q in gq["questions"] if q.get("contradiction")))
        clash = [k for k, v in (fp.get("facilities") or {}).items() if v.get("conflict")]
        if clash:
            add("minor", "The pages contradict themselves about " + ", ".join(clash), "One page says the hotel has it, another that it does not. The word rules decided; worth checking on the site.")
        if fp.get("pages_truncated"):
            add("minor", f"{fp['pages_truncated']} long page(s) were cut short for the AI reading", "Facilities described late on a long page may be 'not stated'.")
    try:
        import profile_audit
        au = profile_audit.audit(rep)
        if au["violations"]:
            add("big", f"{len(au['violations'])} place(s) in the report disagree with the verified facts",
                "; ".join(f"{x['section']}: {x['facility']} ({x['profile']}) - {x['says'][:60]}" for x in au["violations"][:5]))
    except Exception:  # noqa: BLE001
        pass
    ax = gq.get("ai_extract") or {}
    if ax and ax.get("status") not in ("ok", None):
        add("minor", "The AI reading of the guest questions did not run", str(ax.get("reason") or ax.get("status"))[:300])
    # ---- where the hotel is
    if loc.get("lat") is None:
        add("big", "The hotel could not be placed on the map", "No postcode or map position was found, so distances, nearby places and how far rivals are could not be measured. "
            "Prompts name the town to keep the assistant in the right place. Add the address to the hotel's profile.")
    # ---- the AI test
    ai = rep.get("ai_sample") or {}
    if ai and ai.get("status") not in ("ok",):
        add("big", "The AI assistant test did not run", str(ai.get("reason") or ai.get("status"))[:300])
    elif ai.get("partial"):
        add("minor", "The AI assistant test ran only in part", str(ai.get("reason") or "")[:300])
    for k, label in (("ai_insights", "Breaking down the AI answers"), ("ai_gap", "Who was named instead, and the pages cited"), ("review_snapshot", "Review replies"),
                     ("forums", "Open conversations"), ("listing_lookup", "Listings search")):
        x = rep.get(k) or {}
        if x and x.get("status") in ("unavailable", "error", "failed"):
            add("minor", f"{label} did not finish", str(x.get("reason") or "")[:300])
    bm = rep.get("benchmark") or {}
    if bm.get("retired"):
        add("minor", f"{len(bm['retired'])} saved prompt(s) were replaced", "; ".join(f"“{r.get('text', '')[:70]}”: {r.get('why', '')}" for r in bm["retired"][:3]))
    # ---- steps that failed outright
    for e in (rep.get("step_errors") or [])[:6]:
        add("minor", f"A step failed: {str(e.get('step') or e.get('what') or '')[:80]}", str(e.get("error") or e.get("reason") or "")[:300])
    if (cov.get("ratio") or 1) < 0.5 and tried:
        add("minor", "Little of the site was read", f"Coverage ratio {cov.get('ratio')}: 'not stated' findings were softened to 'could not check'.")
    out.sort(key=lambda x: x["level"] != "big")
    return out


def panel_html(rep):
    """The admin block: nothing when nothing went wrong."""
    from html import escape as esc
    xs = issues(rep)
    if not xs:
        return '<p class="caption">Nothing went wrong in the latest check.</p>'
    big = [x for x in xs if x["level"] == "big"]
    return ((f'<div class="alert warning"><b>{len(big)} serious problem(s) in the latest check.</b> The hotel&rsquo;s report says only what could not be checked; the reasons are here.</div>' if big else "")
            + "<ul>" + "".join(f'<li>{"<b>" if x["level"] == "big" else ""}{esc(x["what"])}{"</b>" if x["level"] == "big" else ""}'
                               + (f'<br><span class="caption">{esc(x["detail"])}</span>' if x["detail"] else "") + "</li>" for x in xs) + "</ul>")
