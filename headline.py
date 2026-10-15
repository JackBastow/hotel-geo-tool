"""
The headline number, stated honestly.

The scorecard averages only the categories that could be assessed. Showing
that average on its own ("83/100") reads as a verdict on how visible the hotel
is to AI - which it is not, because the largest parts of the model (what AI
assistants actually say, and guest reviews) cannot be measured by this free
tool. So the headline always carries three things together:

  * a READINESS score - how well set up the hotel is, on the factors measured
  * MEASUREMENT COVERAGE - how much of the full model that score rests on
  * what was NOT measured, and why

Below 30% coverage no single number is given at all; below 70% it is marked
provisional. Each category score also carries an EVIDENCE STRENGTH (high /
medium / low): a score and the evidence behind it are different things.
"""

WITHHOLD_BELOW = 30.0
PROVISIONAL_BELOW = 70.0

SAMPLED_NOTE = ("A small sample of what one AI assistant says was collected for this report (see 'How AI sees your hotel'). "
                "It is not scored: one model on one day is not a measure of AI visibility.")

WHY_NOT = {
    "ai_visibility": "What AI assistants actually say about the hotel is not measured by this tool (it needs a paid, grounded search). "
                     "You can sample it yourself in the Tools tab.",
    "reviews": "Guest reviews are not read from the platforms (their terms prohibit automated collection), so they are not scored unless the hotel uploads its own review export "
               "(Beyond your website, Reviews & reputation). An indicative snapshot of public reviews and the hotel's replies is shown separately when it could be obtained.",
}


def _lvl(n, high, medium):
    return "high" if n >= high else ("medium" if n >= medium else "low")


def category_evidence(rep):
    """key -> (level, note) for each scorecard category."""
    g = rep.get("guest_questions") or {}
    site = rep.get("site") or {}
    ents = rep.get("entities") or []
    tav = rep.get("tavily_result") or {}
    confident = sum(1 for e in ents if e.get("found") and e.get("match_confident") is True)
    cmp_n = len(rep.get("consistency") or [])
    lastmods = len((site.get("sitemap") or {}).get("lastmods") or [])
    pages_ok, pages_att = g.get("pages_ok", 0), g.get("pages_attempted", 0)
    confirmed = sum(1 for h in tav.get("editorial_hits", []) if (h.get("read") or {}).get("confirmed") is True)
    otas = len(tav.get("ota_hits") or [])
    ai = rep.get("ai_sample") or {}
    ai_s = ai.get("summary") or {}
    return {
        "ai_visibility": ("low", f"one AI model, {ai_s.get('asked', 0)} questions, one day"),
        "website": (_lvl(pages_ok, 15, 8), f"{pages_ok} of {pages_att} pages read"),
        "entity": ("high" if confident >= 2 and cmp_n >= 3 else ("medium" if confident >= 1 else "low"),
                   f"{confident} open-data source(s) matched; {cmp_n} fact comparison(s)"),
        "freshness": (_lvl(lastmods, 20, 5), f"{lastmods} page dates in the sitemap"),
        # found through a search index, never by reading the platforms, so never better than medium
        "otas": ("medium" if otas >= 3 else "low", f"{otas} platform(s) seen in search results (platforms themselves are not read)"),
        "editorial": (_lvl(confirmed, 5, 2), f"{confirmed} article(s) read and confirmed"),
        "social": ("low", "profile links only; activity is not measured"),
        **({"reviews": (_lvl((rep.get("review_pack") or {}).get("reviews", 0), 100, 30),
                        f"{(rep.get('review_pack') or {}).get('reviews', 0)} review(s) from the hotel's own export, for that file only")} if rep.get("review_pack") else {}),
    }


def build(rep):
    sampled = (rep.get("ai_sample") or {}).get("status") == "ok"
    sc = rep.get("scorecard") or {}
    overall, cov = sc.get("overall"), sc.get("coverage_pct") or 0.0
    cats = sc.get("categories") or []
    ev = category_evidence(rep)
    unassessed = [{"key": c["key"], "label": c["label"], "weight": c["weight"],
                   "why": (SAMPLED_NOTE if sampled and c["key"] == "ai_visibility" else WHY_NOT.get(c["key"], c.get("detail", "")))} for c in cats if not c.get("assessed")]
    miss_w = round(sum(u["weight"] for u in unassessed), 1)
    crawl = (rep.get("consultant") or {}).get("coverage") or {}
    if overall is None or cov < WITHHOLD_BELOW or crawl.get("unreadable"):
        status = "withheld"
    elif cov < PROVISIONAL_BELOW or crawl.get("limited"):
        status = "provisional"
    else:
        status = "assessed"
    names = ", ".join(u["label"] for u in sorted(unassessed, key=lambda u: -u["weight"])[:3])
    if status == "withheld" and crawl.get("unreadable"):
        n = crawl.get("pages_read", 0)
        expl = (("None of the website's pages" if not n else f"Only {n} page(s) of the website") + " could be read, which is too few to give a meaningful readiness "
                "score: a score on a site we could not read would be misleading. Findings that do not depend on reading the site "
                "(official registers, open data, outside coverage) are still shown.")
    elif status == "withheld":
        expl = (f"Only {cov:.0f}% of the full model could be assessed, which is too little for a single score. "
                "The category results below are shown on their own.")
    else:
        expl = (f"{overall}/100 is the average of the categories that could be assessed, which is {cov:.0f}% of the full model. "
                f"The other {miss_w:g}% is not measured ({names}). Read it as an indicator of how well the hotel is set up"
                + (". It includes a small sample of one AI assistant's answers, which is a clue about visibility, not a measurement of it."
                   if any(c.get("key") == "ai_visibility" and c.get("assessed") for c in cats)
                   else ", not as a measure of how visible it is to AI assistants."))
    return {"title": "AI discoverability readiness (assessed factors)", "score": None if status == "withheld" else overall,
            "coverage_pct": cov, "status": status, "unassessed": unassessed, "unassessed_weight": miss_w,
            "explanation": expl,
            "badge": {"withheld": "not enough measured for a score", "provisional": "provisional", "assessed": "on assessed factors"}[status],
            "category_evidence": {k: {"level": v[0], "note": v[1]} for k, v in ev.items()}}


def attach(rep):
    """Store the headline and per-category evidence strength in the report (idempotent)."""
    if not rep.get("scorecard"):
        return rep
    h = build(rep)
    rep["headline"] = h
    for c in rep["scorecard"].get("categories", []):
        e = h["category_evidence"].get(c["key"])
        if c.get("assessed") and e:
            c["evidence_level"], c["evidence_note"] = e["level"], e["note"]
    return rep
