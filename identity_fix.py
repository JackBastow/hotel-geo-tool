"""
Recalculate a saved report's AI visibility from the answers it already holds, under the hotel's real identity. No assistant is asked again: it costs nothing.

A check saved before hotel_identity.py existed counted the hotel by the name it was registered under. When that name was not how the hotel is written (Saunton Sands: 'sauntonsands hotel',
the assistant wrote 'Saunton Sands Hotel' 85 times), the hotel scored 0% and its own spellings stood among its rivals. reprocess() rebuilds the identity from what the report holds (the name,
the hotel's own page titles, open map data, the names the assistants used), marks every answer again, and re-derives every figure that depends on which names are the hotel: the sample
summary, the leaderboards, the brand ranking, the question table, the rivals market by market, the AI-visibility score and the pages. diagnose() does the same on a copy and says what moved.

What cannot be recalculated without asking an assistant again is withdrawn, not left wrong: the plays and findings written FROM the wrong figures ('named in 0 of 18 answers; Saunton Sands
Hotel Source Spa was named instead'), and the AI's own explanation of the gap. They come back, correct, at the hotel's next check. The report says what was withdrawn.
"""

import copy
import datetime as dt
import html
import re
import urllib.parse

import hotel_identity

# findings written from the AI sample's figures about the hotel and its rivals
WITHDRAW_SOURCES = {"commercial", "sources", "ai_gap", "ai_facts"}
WITHDRAW_IDS = re.compile(r"^(?:AG-|AGO|CP-|DS\d|SG\d|AF-|AF$)")
WITHDRAW_KEYS_IN_INSIGHTS = ("explanation", "ledger", "head_to_head")


def _titles(rep):
    out = []
    for p in (rep.get("site") or {}).get("pages") or []:
        out += [p.get("title")] + list((p.get("h1") or [])[:1])
    for p in (rep.get("guest_questions") or {}).get("pages_meta") or []:
        out += [p.get("title")] + list((p.get("h1") or [])[:1])
    for p in (rep.get("ai_insights") or {}).get("pages") or []:
        if p.get("own_site"):
            out.append(p.get("title"))
    return [html.unescape(str(t)) for t in out if t]


def _entity_names(rep):
    out = []
    for e in rep.get("entities") or []:
        if e.get("found") and e.get("match_confident") is not False:
            n = e.get("label") or (e.get("facts") or {}).get("name") or (e.get("display_name") or "").split(",")[0]
            if n:
                out.append(str(n))
    return out


def identity_of(rep):
    """The identity a saved report implies."""
    meta = rep.get("meta") or {}
    typed = meta.get("hotel_entered") or meta.get("hotel") or ""
    answers = (rep.get("ai_insights") or {}).get("extracted_answers") or {}
    obs = {}
    for hs in answers.values():
        for h in hs:
            if h.get("name"):
                obs[h["name"]] = obs.get(h["name"], 0) + 1
    known = [a.get("name") for a in ((rep.get("identity") or {}).get("aliases") or []) if a.get("name")]
    names = [(rep.get("site") or {}).get("lodging_node", {}).get("name")] if isinstance((rep.get("site") or {}).get("lodging_node"), dict) else []
    return hotel_identity.build(typed, meta.get("city") or "", meta.get("website") or meta.get("base") or "", site_titles=_titles(rep), site_names=[n for n in names if n],
                                entity_names=_entity_names(rep), observed=obs, known=known, brand_site=bool((((rep.get("site") or {}).get("meta")) or {}).get("scope")))


def _strip_ids(o, ids):
    if isinstance(o, list):
        return [_strip_ids(x, ids) for x in o if not ((isinstance(x, str) and x in ids) or (isinstance(x, dict) and x.get("id") in ids and ("title" in x or "action" in x)))]
    if isinstance(o, dict):
        return {k: _strip_ids(v, ids) for k, v in o.items()}
    return o


def _counts(rep):
    import report_model
    c = report_model.ai_counts(rep) or {}
    sb = ((rep.get("ai_insights") or {}).get("scoreboard")) or {}
    br = ((rep.get("ai_insights") or {}).get("brand_ranking")) or {}
    return {"named": c.get("named"), "asked": c.get("asked"), "pct": c.get("pct"), "top_competitor": sb.get("top_competitor"),
            "rivals": [r.get("name") for r in (br.get("rows") or []) if not r.get("is_target")][:6]}


def reprocess(rep, withdraw=True):
    """
    -> (new report, diff) or (None, diff) when the report has no AI answers to recalculate from. The report passed in is not changed.
    diff: {"status", "affected", "canonical", "typed", "before", "after", "own_spellings_among_rivals", "merged_rivals", "related", "withdrawn", "identity"}.
    """
    import ai_gap
    import ai_insights
    import ai_sample
    import headline
    import report_model
    import scoring
    ai = (rep.get("ai_sample") or {})
    ins = (rep.get("ai_insights") or {})
    answers = ins.get("extracted_answers")
    if ai.get("status") != "ok" or not ai.get("items") or not isinstance(answers, dict) or not answers:
        return None, {"status": "no_ai_answers", "affected": False}
    new = copy.deepcopy(rep)
    ai, ins = new["ai_sample"], new["ai_insights"]
    meta = new.setdefault("meta", {})
    city = meta.get("city") or ""
    before = _counts(rep)
    old_names = {r.get("name"): bool(r.get("is_target")) for lb in (ins.get("leaderboard"), (ins.get("niche") or {}).get("leaderboard"), ins.get("brand_ranking")) for r in (lb or {}).get("rows", []) + (lb or {}).get("all", [])}
    ident = identity_of(new)
    canonical = ident["canonical"]
    res = hotel_identity.Resolver(ident, hotel_identity.by_answer_of(answers), city)
    # every answer marked again, under the hotel's real name and every verified spelling of it
    matcher = hotel_identity.matcher_name(ident) or canonical
    ai_sample.remark(ai["items"], matcher, city)
    for eng in (new.get("ai_engines") or {}).values():
        if isinstance(eng, dict) and eng.get("items"):
            ai_sample.remark(eng["items"], matcher, city)
    extracted = {"answers": answers, "failed_ids": [i["id"] for i in ai["items"] if i.get("answer") and i.get("kind") != "direct" and i["id"] not in answers]}
    ai_insights.reconcile(ai, extracted, canonical, res)
    ai["summary"] = {**(ai.get("summary") or {}), **ai_sample.summarise(ai["items"])}
    own_dir = urllib.parse.urlparse(meta.get("base") or meta.get("website") or "").netloc.lower()
    own_dir = own_dir[4:] if own_dir.startswith("www.") else own_dir
    ai_insights.derive(ins, ai, extracted, ai["items"], canonical, city, own_dir, res)
    ins["identity"] = ident
    # the rivals market by market, and the rival comparison: the hotel's own spellings are not rivals
    gap = new.get("ai_gap")
    if isinstance(gap, dict) and gap.get("status") == "ok":
        gap["markets"] = ai_gap.markets(ai["items"], answers, canonical, city, gap.get("hotel_tier"), identity=ident)
        gap["gaps"] = [m["qid"] for m in gap["markets"] if m.get("gap")]
        gap["rivals"] = [r for r in gap.get("rivals") or [] if not res.is_target(r.get("name", ""))]
        cmp_ = gap.get("comparison")
        if isinstance(cmp_, dict):
            cmp_["rivals"] = [r for r in cmp_.get("rivals") or [] if not res.is_target(r.get("name", ""))]
            gone = {r.get("name") for r in (gap.get("comparison") or {}).get("rivals") or []}
            for row in cmp_.get("rows") or []:
                if isinstance(row.get("rivals"), dict):
                    row["rivals"] = {k: v for k, v in row["rivals"].items() if not res.is_target(k)}
        for a in gap.get("articles") or []:
            a["rivals_in"] = [n for n in a.get("rivals_in") or [] if not res.is_target(n)]
        for qid, crit in (gap.get("criteria") or {}).items():
            for c in crit or []:
                c["rivals"] = [n for n in c.get("rivals") or [] if not res.is_target(n)]
    # the AI-visibility score from the recounted sample
    try:
        cat = scoring.score_ai_sample(ai)
        sc = new.get("scorecard")
        if isinstance(sc, dict) and cat:
            for i, c in enumerate(sc.get("categories") or []):
                if c.get("key") == "ai_visibility":
                    sc["categories"][i] = {**c, **cat}
            sc["observed_ai_visibility"] = next((c for c in sc.get("categories") or [] if c.get("key") == "ai_visibility"), sc.get("observed_ai_visibility"))
    except Exception:  # noqa: BLE001 - the figures above are what matter; the score follows at the next check
        pass
    meta["hotel"] = canonical
    if ident.get("changed"):
        meta["hotel_entered"] = ident["entered"]
        meta["hotel_name_source"] = "provided by you, corrected to the hotel's own spelling"
    new["identity"] = ident
    after_names = {r.get("name"): bool(r.get("is_target")) for lb in (ins.get("leaderboard"), (ins.get("niche") or {}).get("leaderboard"), ins.get("brand_ranking")) for r in (lb or {}).get("rows", []) + (lb or {}).get("all", [])}
    report_model.apply(new)
    import report_release
    report_release.assess(new)
    after = _counts(new)
    own_among_rivals = sorted(n for n in old_names if n and not old_names[n] and res.is_target(n))
    merged = []
    seen = {}
    for n in old_names:
        if n and not old_names[n] and not res.is_target(n):
            seen.setdefault(res.key(n), []).append(n)
    merged = [v for v in seen.values() if len(v) > 1]
    stored_name = (rep.get("meta") or {}).get("hotel") or ""
    name_now_changed = canonical != stored_name
    affected = bool(own_among_rivals) or before.get("named") != after.get("named") or name_now_changed
    withdrawn = []
    if affected and withdraw:
        ids = set()
        for r in (new.get("consultant") or {}).get("recommendations") or []:
            if r.get("source") in WITHDRAW_SOURCES or WITHDRAW_IDS.match(str(r.get("id") or "")):
                ids.add(r["id"])
                withdrawn.append({"id": r["id"], "title": r.get("title")})
        if ids:
            for k in ("consultant", "recommendations", "top_fixes"):
                if k in new:
                    new[k] = _strip_ids(new[k], ids)
        for k in WITHDRAW_KEYS_IN_INSIGHTS:
            ins.pop(k, None)
        report_model.apply(new)
    if affected:
        headline.attach(new)
        meta["identity_recalculated"] = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "from": {k: before.get(k) for k in ("named", "asked", "pct", "top_competitor")},
                                         "withdrawn": withdrawn,
                                         "note": ("AI visibility was recalculated from the answers already collected, under the hotel's real name. Findings written from the earlier figures were withdrawn "
                                                  "and are rebuilt at the next check.") if withdrawn else "AI visibility was recalculated from the answers already collected, under the hotel's real name."}
    diff = {"status": "ok", "affected": affected, "canonical": canonical, "typed": ident.get("entered"), "name_changed": name_now_changed, "before": before, "after": after,
            "own_spellings_among_rivals": own_among_rivals[:12], "merged_rivals": merged[:12], "related": ident.get("related", [])[:12], "withdrawn": withdrawn, "identity": ident}
    return new, diff
