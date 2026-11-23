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

MODEL_VERSION = 1


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


def apply(rep):
    """Build rep["model"] and make the report's older copies of the same figure agree with it. Safe to call again (on every read). -> rep"""
    if not isinstance(rep, dict):
        return rep
    try:
        ai = ai_counts(rep)
    except Exception:  # noqa: BLE001 - a report that cannot be modelled is shown as it was
        return rep
    rep["model"] = {"version": MODEL_VERSION, "ai": ai}
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
