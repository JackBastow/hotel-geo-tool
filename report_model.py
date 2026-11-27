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


RANKINGS_MIN_ANALYSED = 0.7           # the share of the answers that must have been read for the hotels they name before the rival tables are shown as a market view


def rankings_state(rep):
    """
    Is the competitor ranking built on enough of the answers to be shown as a view of the market? -> {reliable, analysed, eligible, share, note}.
    Every rival figure comes from the answers whose hotels could be read out. With 4 of 28 read (Brooks Guesthouse), the table says who happened to appear in those 4, not who the assistants recommend,
    so it is not presented as a ranking. The hotel's own count is not affected: it also rests on the text match over every answer.
    """
    rep = rep or {}
    eligible = [i for i in (rep.get("ai_sample") or {}).get("items") or [] if i.get("answer") and i.get("kind") != "direct" and not i.get("names_hotel")]
    ins = rep.get("ai_insights")
    if isinstance(ins, dict) and "extracted_answers" not in ins and (ins.get("brand_ranking") or ins.get("leaderboard")):
        return {"reliable": True, "analysed": None, "eligible": len(eligible), "share": None, "note": "", "unknown": True}      # a check saved before the analysed answers were kept: its rankings stand as they were
    read = (ins or {}).get("extracted_answers") or {}
    analysed = sum(1 for i in eligible if i.get("id") in read)
    n = len(eligible)
    share = analysed / n if n else 0.0
    ok = n > 0 and share >= RANKINGS_MIN_ANALYSED
    if ok:
        note = ""
    elif not n or not analysed:
        note = "No answer could be analysed for the hotels it names, so there is no competitor ranking."
    else:
        note = (f"Only {analysed} of {n} answers could be analysed for the hotels they name, so the competitor table is not shown as a ranking: "
                "it would only describe those few answers, not what the assistants recommend.")
    return {"reliable": ok, "analysed": analysed, "eligible": n, "share": round(share, 2), "note": note}


def withhold_rankings(rep):
    """
    When too few answers were read for the hotels they name (rankings_state), take the rival rows out of every ranking the report carries, so no screen or PDF shows them as a view of the market, and say why.
    The rows are kept under `withheld_rows` (nothing is lost; a later re-reading of the answers can restore them). Safe to call again. -> the note, or None when the rankings stand.
    """
    st = rankings_state(rep)
    ins = (rep or {}).get("ai_insights")
    if st["reliable"] or not isinstance(ins, dict) or not (ins.get("brand_ranking") or ins.get("leaderboard")):
        return None
    lbs = [ins.get("leaderboard"), (ins.get("niche") or {}).get("leaderboard")]
    for key in ("rows", "all"):
        for box in [ins.get("brand_ranking")] + lbs:
            if isinstance(box, dict) and isinstance(box.get(key), list):
                rivals = [r for r in box[key] if isinstance(r, dict) and not r.get("is_target")]
                if rivals:
                    box.setdefault("withheld_rows", {})[key] = rivals
                    box[key] = [r for r in box[key] if not (isinstance(r, dict) and not r.get("is_target"))]
    for box in [ins.get("brand_ranking")] + lbs:
        if isinstance(box, dict):
            box["withheld"] = st["note"]
    sb = ins.get("scoreboard")
    if isinstance(sb, dict):
        sb.update(top_competitor=None, rank_in_table=None, table_size=None, place=None)
    ins["rankings_withheld"] = st["note"]
    return st["note"]


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


def known_rivals(rep):
    """The rival hotels this check found (Claude's analysis of its answers: the brand ranking and the market-by-market rivals), names only."""
    rep = rep or {}
    ins = rep.get("ai_insights") or {}
    names = [r.get("name") for r in ((ins.get("brand_ranking") or {}).get("rows") or []) if not r.get("is_target")]
    for m in ((rep.get("ai_gap") or {}).get("markets") or []):
        names += [x.get("name") for x in m.get("rivals") or []]
    seen, out = set(), []
    for n in names:
        k = (n or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(n.strip())
    return out[:40]


def rivals_in(items, rivals, city=""):
    """-> [(name, answers naming it)] of the known rivals named in these answers, most first."""
    import hotelname
    counts = {}
    for i in items or []:
        a = i.get("answer") or ""
        if not a or i.get("names_hotel"):
            continue
        for n in rivals:
            if hotelname.mentioned(a, n, city):
                counts[n] = counts.get(n, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


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
    try:
        rivals = known_rivals(rep)
        city = ((rep.get("meta") or {}).get("city")) or ""
        if out[0]["status"] == "ok":
            out[0]["instead"] = rivals_in(claude_items, rivals, city)[:3]
    except Exception:  # noqa: BLE001
        rivals, city = [], ""
    for e in ENGINE_ORDER[1:]:
        r = eng.get(e) or {}
        c = _count(r.get("items")) if r.get("status") == "ok" else None
        if c:
            try:
                c["instead"] = rivals_in(r.get("items"), rivals, city)[:3]
            except Exception:  # noqa: BLE001
                c["instead"] = []
        out.append({"engine": e, "name": ENGINE_NAMES[e], "status": "ok" if c else (r.get("status") or "not_configured"),
                    "reason": "" if c else (r.get("reason") or f"No key for {ENGINE_NAMES[e]} is set on the host, so it was not asked."), "model": r.get("model"), **(c or {})})
    if rep.get("manual_checks"):
        import manual_checks
        row = manual_checks.as_engine_row(rep["manual_checks"])
        if row:
            out.append(row)
    return out


ENGINE_HOW = {"chatgpt": "through OpenAI's API with web search; the ChatGPT app may answer differently", "gemini": "through Google's API with Google Search grounding",
              "perplexity": "through Perplexity's API"}


def assistants_asked(rep):
    """-> ['Claude (claude-x) with web search', 'ChatGPT (gpt-5.4-mini through OpenAI's API with web search; ...)'] for every assistant actually asked in this check. Hand-made checks are not included."""
    rep = rep or {}
    out = []
    ai = rep.get("ai_sample") or {}
    if ai.get("status") == "ok":
        out.append(f"Claude ({ai.get('model', '')}) with web search" if ai.get("model") else "Claude with web search")
    for r in engine_counts(rep)[1:]:
        if r.get("status") == "ok" and not r.get("manual"):
            out.append(f"{r['name']} ({(r.get('model') + ' ') if r.get('model') else ''}{ENGINE_HOW.get(r['engine'], 'through its API')})")
    return out


def assistants_phrase(rep):
    """'one assistant only: Claude (...)' or '2 assistants: Claude (...) and ChatGPT (...)'."""
    a = assistants_asked(rep)
    if not a:
        return "no assistant"
    if len(a) == 1:
        return f"one assistant only: {a[0]}"
    return f"{len(a)} assistants: {', '.join(a[:-1])} and {a[-1]}"


def engines_json(rep):
    """Every assistant's figure on the tracked prompts, as stored with each check (runs.ai_engines): '{"claude": [4, 8], "chatgpt": [3, 8]}'. Hand-made checks are not included."""
    import json
    try:
        return json.dumps({r["engine"]: [r["named"], r["asked"]] for r in engine_counts(rep) if r.get("status") == "ok" and not r.get("manual")}, sort_keys=True)
    except Exception:  # noqa: BLE001
        return "{}"


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
    import commercial
    lead = [r["id"] for r in commercial.top(recs, 3)]                  # the plays most likely to win bookings come first, on repeated evidence (Paris Marriott review)
    high_fix = [i for i in (cons or {}).get("top_actions") or [] if isinstance(i, str) and sure(by_id.get(i)) and (by_id[i].get("factors") or {}).get("risk", 0) >= 4]
    out = high_fix[:2] + [i for i in lead if i not in high_fix]       # a serious fix (wrong facts, a blocked site) still comes first
    out += [i for i in (cons or {}).get("top_actions") or [] if isinstance(i, str) and sure(by_id.get(i)) and i not in out]
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
    try:
        rankings = rankings_state(rep)
    except Exception:  # noqa: BLE001
        rankings = None
    rep["model"] = {"version": MODEL_VERSION, "ai": ai, "tracked": tracked, "top_priorities": top, "score_basis": score_basis(rep), "engines": engines, "rankings": rankings}
    try:
        withhold_rankings(rep)
    except Exception:  # noqa: BLE001 - a report that cannot be checked is shown as it was
        pass
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
