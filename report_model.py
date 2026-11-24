"""
One source of truth for the figures a hotel sees. Built once per check (and again whenever a saved report is read, so older checks get the same figures), stored in the report as
rep["model"], and read by every screen, PDF and stored summary instead of each working its own figure out.

Version 1: "named by AI".
  Before: five different counts (the summary columns, the test log, the brand ranking, town-wide only, per prompt). The same check showed 20 of 26 on one screen and 19 of 26 on the next,
  77% in the PDF and 73% on the page.
  Now: ONE definition, `ai_counts`. Every answer collected whose question did not already name the hotel (town-wide, the hotel's markets, its tracked and custom prompts), each answer
  counted once, using the marks after the check against the answer's own list of hotels (ai_insights.reconcile). Town-wide and market breakdowns are labelled parts of it, never a
  different headline. `apply()` also writes the figure into the report's older copies (the brand ranking's line for the hotel, the scoreboard), so code that still reads them agrees.
"""

MODEL_VERSION = 3          # 2: top priorities by one rule; stable recommendation ids. 3: tracked-prompt counts and the score's basis, so only like is compared with like


def ai_counts(rep):
    """-> {named, asked, pct, lo, hi, recommended, site_cited, by_kind: {generic|niche|custom: {named, asked}}} or None when no AI answers were collected."""
    ai = (rep or {}).get("ai_sample") or {}
    if ai.get("status") != "ok":
        return None
    import ai_sample
    import trend
    rows = [i for i in ai.get("items") or [] if i.get("mentioned") is not None and i.get("kind") != "direct" and not i.get("names_hotel")]
    if not rows:
        return None
    named = sum(1 for i in rows if i.get("mentioned"))
    asked = len(rows)
    lo, hi = trend.wilson(named, asked)
    by_kind = {}
    for i in rows:
        k = "custom" if i.get("kind") not in ("generic", "niche") else i["kind"]
        b = by_kind.setdefault(k, {"named": 0, "asked": 0})
        b["asked"] += 1
        b["named"] += 1 if i.get("mentioned") else 0
    return {"named": named, "asked": asked, "pct": round(100 * named / asked), "lo": round(100 * lo), "hi": round(100 * hi),
            "recommended": sum(1 for i in rows if i.get("recommended")), "site_cited": sum(1 for i in rows if i.get("own_site_cited")), "by_kind": by_kind,
            "basis": "every answer whose question did not name the hotel, each counted once"}


def tracked_counts(rep):
    """-> {named, asked, fp} for the hotel's tracked prompts only (the ones asked every week, so weeks can be compared), or None. `fp` identifies the set of prompts asked."""
    ai = (rep or {}).get("ai_sample") or {}
    if ai.get("status") != "ok":
        return None
    import hashlib
    import evidence
    rows = [i for i in ai.get("items") or [] if i.get("source") == "benchmark" and i.get("mentioned") is not None]
    if not rows:
        return None
    texts = sorted({evidence.fold(i.get("text") or "") for i in rows})
    return {"named": sum(1 for i in rows if i.get("mentioned")), "asked": len(rows), "fp": hashlib.sha1("|".join(texts).encode("utf8")).hexdigest()[:12]}


def ai_moved(before, now):
    """'up', 'down' or 'same' between two (named, asked) figures: a move counts only when the ranges the true rates plausibly lie in do not overlap (95%), because a sample of answers
    varies from week to week by itself. 1 of 8 then 3 of 8 now is 'same'."""
    import trend
    if not before or not now or not before[1] or not now[1]:
        return "same"
    lo0, hi0 = trend.wilson(*before)
    lo1, hi1 = trend.wilson(*now)
    if lo1 > hi0:
        return "up"
    if hi1 < lo0:
        return "down"
    return "same"


ENGINE_ORDER = ("claude", "chatgpt", "gemini", "perplexity")
ENGINE_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity"}


def _count(items):
    rows = [i for i in items or [] if i.get("mentioned") is not None and i.get("kind") != "direct" and not i.get("names_hotel")]
    if not rows:
        return None
    named = sum(1 for i in rows if i.get("mentioned"))
    return {"named": named, "asked": len(rows), "pct": round(100 * named / len(rows)), "recommended": sum(1 for i in rows if i.get("recommended")),
            "site_cited": sum(1 for i in rows if i.get("own_site_cited"))}


def engine_counts(rep):
    """-> [{engine, name, status, reason, named, asked, pct, recommended, site_cited}] for every assistant, Claude first, all on the hotel's TRACKED prompts (the same questions for each).
    An assistant that was not asked has status not_configured / over_budget / unavailable and no figures: 'not tested', never zero."""
    rep = rep or {}
    out = []
    ai = rep.get("ai_sample") or {}
    claude_items = [i for i in ai.get("items") or [] if i.get("source") == "benchmark"] if ai.get("status") == "ok" else []
    c = _count(claude_items)
    out.append({"engine": "claude", "name": "Claude", "status": "ok" if c else (ai.get("status") or "not_configured"), "reason": "" if c else (ai.get("reason") or "No tracked prompts were asked."),
                **(c or {})})
    eng = rep.get("ai_engines") or {}
    for e in ENGINE_ORDER[1:]:
        r = eng.get(e) or {}
        c = _count(r.get("items")) if r.get("status") == "ok" else None
        out.append({"engine": e, "name": ENGINE_NAMES[e], "status": "ok" if c else (r.get("status") or "not_configured"),
                    "reason": "" if c else (r.get("reason") or f"No key for {ENGINE_NAMES[e]} is set on the host, so it was not asked."), "model": r.get("model"), **(c or {})})
    return out


def depth_of(rep):
    """'deep', 'standard' or '' (no AI test). Recorded on checks since Nov 2026; older ones are recognised by their repeats (a deep test asks its core prompts 5 times)."""
    d = ((rep or {}).get("meta") or {}).get("ai_depth")
    if d in ("deep", "standard"):
        return d
    ai = (rep or {}).get("ai_sample") or {}
    if ai.get("status") != "ok":
        return ""
    most = max([int(i.get("repeats") or 1) for i in ai.get("items") or []] or [1])
    return "deep" if most >= 5 else "standard"


def score_basis(rep):
    """The areas the readiness score measured, as one string: two scores are comparable only when they measured the same areas."""
    cats = ((rep or {}).get("scorecard") or {}).get("categories") or []
    return ",".join(sorted(c.get("key", "") for c in cats if c.get("assessed") and c.get("score") is not None))


def priorities_of(cons, n=5):
    """The top priorities, by ONE rule used by the Overview, Start here, the management and consultant PDFs: the analysis's ranked top actions, leaving out what rests on
    uncertain evidence ('Worth checking'), topped up from the next-best ranked fixes. -> [recommendation ids] in order."""
    recs = [r for r in (cons or {}).get("recommendations") or [] if isinstance(r, dict)]
    by_id = {r.get("id"): r for r in recs}
    sure = lambda r: r is not None and r.get("confidence_label") != "Worth checking"      # noqa: E731
    out = [i for i in (cons or {}).get("top_actions") or [] if isinstance(i, str) and sure(by_id.get(i))]
    if len(out) < n:
        rest = sorted((r for r in recs if r.get("kind") == "fix" and sure(r) and r.get("id") not in out), key=lambda r: -(r.get("rank") or 0))
        out += [r["id"] for r in rest]
    return out[:n]


def apply(rep):
    """Build rep["model"] and make the report's older copies of the same figure agree with it. Safe to call again (on every read). -> rep"""
    if not isinstance(rep, dict):
        return rep
    try:
        ai = ai_counts(rep)
    except Exception:  # noqa: BLE001 - a report that cannot be modelled is shown as it was
        return rep
    try:
        top = priorities_of(rep.get("consultant") or {})
    except Exception:  # noqa: BLE001
        top = []
    try:
        tracked = tracked_counts(rep)
    except Exception:  # noqa: BLE001
        tracked = None
    try:
        engines = engine_counts(rep)
    except Exception:  # noqa: BLE001
        engines = []
    rep["model"] = {"version": MODEL_VERSION, "ai": ai, "tracked": tracked, "top_priorities": top, "score_basis": score_basis(rep), "engines": engines}
    if not ai:
        return rep
    ins = rep.get("ai_insights") if isinstance(rep.get("ai_insights"), dict) else None
    if ins:
        sb = ins.get("scoreboard")
        if isinstance(sb, dict):
            sb.update(coverage_pct=ai["pct"], named_all=ai["named"], asked_all=ai["asked"])
        br = ins.get("brand_ranking")
        if isinstance(br, dict):
            for key in ("rows", "all"):
                for r in br.get(key) or []:
                    if isinstance(r, dict) and r.get("is_target"):
                        r.update(mentions=ai["named"], of=ai["asked"], coverage_pct=ai["pct"])
    return rep


def named_line(rep):
    """'named in 20 of 26 sampled answers (77%)' or ''."""
    ai = ((rep or {}).get("model") or {}).get("ai") or ai_counts(rep)
    return f"named in {ai['named']} of {ai['asked']} sampled answers ({ai['pct']}%)" if ai else ""
