"""
The last gate before a report goes out: one pass over the WHOLE report that looks for the ways its sections can contradict each other or mislead, and settles each one in the open.

The report is built by many independent checks. Each is right about what it looked at, but two can look at different pages or use different rules, and then the report says on one page that the spa is not mentioned
and on another that it is a strength. This module keeps ONE ledger of what the hotel's own pages show (the consultant layer's feature levels, the single source of truth), then scans every section's wording against it:

  states_missing_but_present   a finding says a facility is not mentioned / missing / absent, but the ledger shows the pages state it: the finding is set to 'Worth checking', says so, and is marked disputed
  assumes_offer_not_shown      advice to promote, describe or improve a facility the pages do not show (and the crawl was good enough to judge): removed, with the reason kept in the dropped list
  strength_and_fix_agree       a strength and a fix about the same facility cannot both stand (covered by the first rule, counted here)
  rival_sanity                 the hotel itself, a sibling of the same brand or a hotel too far away is not a comparable hotel; "N of M rivals" counts are recomputed from the rivals actually read
  prompt_places                a question that names a place the audit could not verify, or carries a scrap of page text, is reported (it should never have been asked)
  ai_numbers_agree             the counts of answers in different sections agree
  ai_zero_diagnosis            when the hotel was named in none of the answers: was it known when asked by name, are there answers that contain words of its name that were not counted, which kinds of question were asked

Every change is returned as a note and stored in report['gate'] with the checks run and how many items each looked at, so a reader can see the report was checked and what the check did. It never raises and never
invents a finding: it only downgrades, removes or annotates.
"""

import re

import evidence
import lexicon

ABSENCE = re.compile(r"\b(?:no mention|not mention\w*|does not (?:mention|state|say|list|describe|have|offer|include|show)|doesn'?t (?:mention|state|say|list|describe|have|offer|include|show)|"
                     r"is(?:n'?t| not) (?:mentioned|stated|described|listed|found|visible|shown)|not (?:stated|described|listed|found|visible|shown|mentioned)|missing|absent|lacks?|without|nothing (?:on|about))\b", re.I)
DETAIL_WORDS = re.compile(r"\b(?:details?|prices?|rates?|hours|times?|opening|capacity|sizes?|menus?|treatments?|booking|how to|policy|policies|address|contact|phone|email|map|photos?|images?|video|schema|markup)\b", re.I)
PROMOTE = re.compile(r"\b(?:add|create|improve|expand|promote|highlight|describe|detail|publish|optimi[sz]e|update|showcase|feature|build a page|dedicated page)\b", re.I)
CONDITIONAL = re.compile(r"\b(?:if|whether|state whether|check whether|where it exists|should the hotel|only if)\b", re.I)
RIVAL_MAX_KM = 15.0
NAME_NOISE = {"hotel", "hotels", "the", "and", "by", "spa", "resort", "inn", "suites", "london", "paris", "city", "centre", "center", "airport"}


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if s.strip()]


def _texts(item, keys=("title", "finding", "action", "why", "summary", "opportunity", "label", "proof", "evidence")):
    out = []
    for k in keys:
        v = item.get(k)
        if isinstance(v, str):
            out.append(v)
    return out


def _ledger(c, coverage):
    """What the hotel's own pages show, per facility: {key: {"label", "level", "pages", "pattern"}} plus whether an absence can be believed."""
    led = {}
    for f in c.get("features") or []:
        key = f.get("key")
        spec = lexicon.FEATURES.get(key)
        if not spec:
            continue
        led[key] = {"label": spec[0], "level": f.get("level"), "pages": f.get("pages") or 0, "pattern": spec[1]}
    judged_absence_ok = not (coverage.get("limited") or coverage.get("text_only")) and (coverage.get("pages_read") or c.get("pages_read") or 0) >= 3
    return led, judged_absence_ok


def _topic_in(sentence, led):
    return [k for k, v in led.items() if v["pattern"].search(sentence)]


def _downgrade(rec, note, advice):
    rec["disputed"] = True
    rec["confidence"] = advice.EXPER
    if note not in (rec.get("finding") or "") and not (note.startswith("Only ") and re.search(r"pages could be read", rec.get("finding") or "")):     # the coverage caveat once, not twice
        rec["finding"] = (rec.get("finding") or "") + " " + note


def _check_text_vs_ledger(rec, led, absence_ok):
    """-> ("dispute", topic, sentence) | ("drop", topic, sentence) | None"""
    for key in ("finding", "title", "why", "action"):
        for s in _sentences(rec.get(key) if isinstance(rec.get(key), str) else ""):
            topics = _topic_in(s, led)
            if not topics:
                continue
            for t in topics:
                row = led[t]
                if ABSENCE.search(s) and not DETAIL_WORDS.search(s) and row["pages"] >= 1 and row["level"] in ("some", "strong"):
                    return "dispute", t, s
                if absence_ok and row["level"] in (None, "none") and row["pages"] == 0 and PROMOTE.search(s) and not CONDITIONAL.search(s) and not CONDITIONAL.search(rec.get("title") or ""):
                    return "drop", t, s
    return None


def _rival_names(rep):
    names = []
    for r in ((rep.get("competitors") or {}).get("competitors") or []):
        names.append(r.get("name", ""))
    for r in (((rep.get("ai_gap") or {}).get("comparison") or {}).get("rivals") or []):
        names.append(r.get("name", ""))
    return names


def _fold_tokens(name):
    return {t for t in re.split(r"[^a-z0-9]+", evidence.fold(name or "")) if t and t not in NAME_NOISE}


def check(rep):
    """Runs every check on the finished report, changing it in place where a section contradicts the ledger. -> rep (with rep['gate'])."""
    import advice
    gate = {"checks": [], "changes": [], "version": 2, "needs_review": []}
    import ranking
    ranking.fill_report(rep)                    # a recommendation added after the ranking (the former name) carries the fields every page and PDF sorts by

    def done(name, looked, found, summary):
        gate["checks"].append({"name": name, "looked_at": looked, "found": found, "summary": summary})

    try:
        c = rep.get("consultant") or {}
        coverage = c.get("coverage") or {}
        led, absence_ok = _ledger(c, coverage)
        recs = c.get("recommendations") or []
        by_id = {r.get("id"): r for r in recs}
        for r in rep.get("recommendations") or []:
            by_id.setdefault(r.get("id"), r)
        pool = list(by_id.values())

        # 1 and 2: wording against the ledger
        disputed, dropped = [], []
        for r in pool:
            if r.get("disputed"):
                continue
            hit = _check_text_vs_ledger(r, led, absence_ok)
            if not hit:
                continue
            verdict, topic, sent = hit
            lab = led[topic]["label"]
            if verdict == "dispute":
                _downgrade(r, f"Another part of this report found “{lab}” stated on {led[topic]['pages']} page(s) of the hotel's own site, so the two disagree: look at the pages before acting.", advice)
                disputed.append(r["id"])
                gate["changes"].append({"check": "states_missing_but_present", "id": r.get("id"), "topic": lab, "what": "set to Worth checking, marked disputed", "text": sent[:200]})
            else:
                dropped.append(r["id"])
                gate["changes"].append({"check": "assumes_offer_not_shown", "id": r.get("id"), "topic": lab, "what": "removed: the pages do not show the hotel offers it", "text": sent[:200]})
        if dropped:
            for lst in (c.get("recommendations"), rep.get("recommendations")):
                if isinstance(lst, list):
                    lst[:] = [r for r in lst if r.get("id") not in set(dropped)]
            for key in ("top_actions", "quick_wins", "required_fixes", "opportunity_recs"):
                if isinstance(c.get(key), list):
                    c[key] = [i for i in c[key] if i not in set(dropped)]
            gone = set(dropped)
            if isinstance(rep.get("top_fixes"), list):
                rep["top_fixes"] = [t for t in rep["top_fixes"] if (t.get("id") if isinstance(t, dict) else t) not in gone]
            if isinstance(c.get("plan"), dict):
                c["plan"] = {k: [i for i in v if i not in gone] if isinstance(v, list) else v for k, v in c["plan"].items()}
            c.setdefault("dropped_recommendations", [])
            if isinstance(c["dropped_recommendations"], list):
                c["dropped_recommendations"] += [{"id": i, "why": "assumes the hotel offers something its pages do not show"} for i in dropped]
        done("states_missing_but_present", len(pool), len(disputed), "findings that say a facility is missing while the hotel's pages state it")
        done("assumes_offer_not_shown", len(pool), len(dropped), "advice about a facility the pages do not show")

        # differentiation: a strength and a fix about the same facility
        diff = c.get("differentiation") or {}
        clash = 0
        for st in diff.get("strengths") or []:
            for r in pool:
                if r.get("id") in disputed and st.get("key") in _topic_in(" ".join(_texts(r)), led):
                    clash += 1
        done("strength_and_fix_agree", len(diff.get("strengths") or []), clash, "a strength and a fix about the same facility (settled by the first rule)")
        for key in ("underexplained", "opportunities", "advantages"):
            rows = diff.get(key) or []
            keep = []
            for o in rows:
                row = led.get(str(o.get("key", "")).split(":")[-1])
                if row and absence_ok and row["level"] in (None, "none") and row["pages"] == 0 and key != "opportunities":
                    gate["changes"].append({"check": "assumes_offer_not_shown", "id": f"diff:{key}:{o.get('key')}", "topic": row["label"], "what": "removed from the differentiation view"})
                    continue
                keep.append(o)
            if len(keep) != len(rows):
                diff[key] = keep

        # 4: rivals
        own = _fold_tokens(((rep.get("meta") or {}).get("hotel")) or "")
        own_dom = re.sub(r"^www\.", "", re.sub(r"^https?://", "", ((rep.get("meta") or {}).get("base") or "")).split("/")[0].lower())
        removed = []
        comp = rep.get("competitors") or {}
        keep = []
        for r in comp.get("competitors") or []:
            toks = _fold_tokens(r.get("name"))
            dom = re.sub(r"^www\.", "", re.sub(r"^https?://", "", r.get("url") or "").split("/")[0].lower())
            if (own and toks and toks == own) or (own_dom and dom == own_dom):
                removed.append((r.get("name"), "is the hotel itself"))
            elif (r.get("km") or 0) > RIVAL_MAX_KM:
                removed.append((r.get("name"), f"is {r['km']} km away"))
            else:
                keep.append(r)
        if removed and comp:
            comp["competitors"] = keep
            for n, why in removed:
                gate["changes"].append({"check": "rival_sanity", "id": n, "what": f"taken out of the comparable hotels: it {why}"})
        cmp_ = (rep.get("ai_gap") or {}).get("comparison") or {}
        rivals = cmp_.get("rivals") or []
        read = [r for r in rivals if (r.get("pages_read") or 0) >= 1]
        recount = 0
        for a in diff.get("advantages") or []:
            n_read = len([r for r in read])
            if a.get("read") != n_read and a.get("read") is not None:
                a["read"] = n_read
                recount += 1
        done("rival_sanity", len(comp.get("competitors") or []) + len(removed) + len(rivals), len(removed) + recount, "the hotel itself, a hotel too far away, or a rival count that did not match the rivals read")

        # 5: the places the questions name
        import placenames
        prompts = [i.get("text", "") for i in (rep.get("ai_sample") or {}).get("items") or [] if i.get("text")]
        prompts += [p for p in rep.get("custom_prompts") or []]
        uniq = list(dict.fromkeys(prompts))
        scrappy = [p for p in uniq if placenames.has_scrap(p)]
        for p in scrappy:
            gate["changes"].append({"check": "prompt_places", "id": p[:80], "what": "a question carries a scrap of page text where a place should be: it should not be read as a fair test"})
        done("prompt_places", len(uniq), len(scrappy), "questions naming a place the audit could not verify")

        # 6 and 7: the AI answers
        ai = rep.get("ai_sample") or {}
        items = [i for i in ai.get("items") or [] if i.get("mentioned") is not None]
        summ = ai.get("summary") or {}
        asked = len(items)
        named = sum(1 for i in items if i.get("mentioned"))
        mismatch = 0
        if summ.get("asked") is not None and summ.get("asked") != len([i for i in ai.get("items") or [] if i.get("mentioned") is not None]):
            mismatch += 1
        gm = sum((m.get("of") or 0) for m in (rep.get("ai_gap") or {}).get("markets") or [])
        if gm > asked and asked:
            mismatch += 1
        if mismatch:
            gate["changes"].append({"check": "ai_numbers_agree", "id": "ai", "what": f"the answer counts differ between sections (sample {asked}, gap view {gm})"})
        done("ai_numbers_agree", 3, mismatch, "the number of answers counted in each section")

        diag = None
        if asked:
            hotel = (rep.get("meta") or {}).get("hotel") or ""
            direct = [i for i in items if i.get("kind") == "direct"]
            direct_named = sum(1 for i in direct if i.get("mentioned"))
            core = [t for t in _fold_tokens(hotel) if len(t) >= 5]
            missed = []
            if core:
                for i in items:
                    if i.get("mentioned") or not i.get("answer"):
                        continue
                    t = evidence.fold(i["answer"])
                    if any(re.search(r"\b" + re.escape(w), t) for w in core):
                        missed.append(i.get("text", "")[:100])
            kinds = {}
            for i in items:
                k = kinds.setdefault(i.get("kind") or "other", {"asked": 0, "named": 0})
                k["asked"] += 1
                k["named"] += 1 if i.get("mentioned") else 0
            diag = {"asked": asked, "named": named, "direct_asked": len(direct), "direct_named": direct_named, "possible_missed": len(missed), "examples": missed[:3], "by_kind": kinds}
            if named == 0:
                if direct and direct_named == 0:
                    diag["reading"] = ("The assistant did not name the hotel even when asked about it by name. That can mean it does not know the hotel, or that the hotel is written differently in the answers (the name forms are checked in "
                                       "the outside-sources section). Treat the zero as a real finding about recognition, not as a measure of how good the hotel is.")
                elif direct_named:
                    diag["reading"] = ("The assistant knew the hotel when asked about it by name but did not suggest it for any general search. That is typical of a hotel with little coverage on the sites assistants draw on, and it is the gap "
                                       "to work on; the searches asked were a sample, so one day's zero is not a permanent verdict.")
                else:
                    diag["reading"] = "None of the questions asked about the hotel by name, so this zero only shows it was not suggested for general searches in this sample."
                if missed:
                    diag["reading"] += f" {len(missed)} answer(s) contain a word from the hotel's name but were not counted as naming it: read them before relying on the zero."
                gate["changes"].append({"check": "ai_zero_diagnosis", "id": "ai", "what": diag["reading"][:240]})
            gate["ai_diagnosis"] = diag
        done("ai_zero_diagnosis", asked, 1 if (diag and named == 0) else 0, "when the hotel was named in none of the answers, what that does and does not show")
        check_more(rep, gate, done)
    except Exception as e:  # noqa: BLE001 - the report must never fail because of its own check
        gate["error"] = f"{type(e).__name__}: {e}"
    gate["summary"] = f"{len(gate['checks'])} consistency checks ran across the report; {len([x for x in gate['changes'] if x['check'] != 'ai_zero_diagnosis'])} contradiction(s) or misleading item(s) were settled."
    rep["gate"] = gate
    return rep


# ----------------------------------------------------------------------------- more checks, from the errors found in real reports (THE NICI Newquay, Nov 2026)

_ABSENCE_SOURCES = {"questions", "traveller", "facility", "hidden", "location", "structured"}      # machine findings (a title, a meta tag) are about pages that were read, so coverage does not weaken them
_LISTING_ABSENT = re.compile(r"\b(?:not|never|isn'?t|is not|no)\s+(?:\w+\s+){0,3}(?:listed|found|present|on)\s+(?:\w+\s+){0,2}(booking\.com|booking|expedia|tripadvisor|hotels\.com|trivago|agoda|kayak|trip\.com)\b", re.I)
_LEAK = re.compile(r"\{[a-z_]+\}|\bNone\b|\bnan\b|\[object|\bundefined\b|\bnull\b")
_TAG = re.compile(r"</?(?:b|i|u|em|strong|br|span|a|p|div|small)\b[^>]*>", re.I)
_INVIS = re.compile(r"[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_TEXT_KEYS = ("title", "finding", "action", "why", "summary", "example", "success_check")


def _clean_text(s):
    import html as _h
    if not isinstance(s, str) or ("<" not in s and "&" not in s):
        return s
    return _TAG.sub("", _h.unescape(s))


def _remove(rep, ids, why, gate, check):
    """Take recommendations out of every list that holds them, keeping the reason."""
    c = rep.get("consultant") or {}
    gone = set(ids)
    if not gone:
        return
    for lst in (c.get("recommendations"), rep.get("recommendations")):
        if isinstance(lst, list):
            lst[:] = [r for r in lst if r.get("id") not in gone]
    for key in ("top_actions", "quick_wins", "required_fixes", "opportunity_recs"):
        if isinstance(c.get(key), list):
            c[key] = [i for i in c[key] if i not in gone]
    if isinstance(c.get("plan"), dict):
        c["plan"] = {k: [i for i in v if i not in gone] if isinstance(v, list) else v for k, v in c["plan"].items()}
    if isinstance(rep.get("top_fixes"), list):
        rep["top_fixes"] = [t for t in rep["top_fixes"] if (t.get("id") if isinstance(t, dict) else t) not in gone]
    c.setdefault("dropped_recommendations", [])
    if isinstance(c["dropped_recommendations"], list):
        c["dropped_recommendations"] += [{"id": i, "why": why} for i in gone]
    for i in gone:
        gate["changes"].append({"check": check, "id": i, "what": "removed: " + why})


def check_more(rep, gate, done):
    """The run checks added after the NICI review. Each fixes what it safely can, downgrades what it cannot prove, and lists what a person should look at (gate['needs_review'])."""
    import advice
    c = rep.get("consultant") or {}
    cov = c.get("coverage") or {}
    meta = rep.get("meta") or {}
    recs = c.get("recommendations") or []
    review = gate.setdefault("needs_review", [])

    # 8. evidence from another hotel's pages: a brand site's other sections, or another website, never supports a finding about this hotel's own site
    scope = ((rep.get("site") or {}).get("meta") or {}).get("scope") or ""
    base = meta.get("base") or ""
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", base).split("/")[0].lower())
    outside, emptied = 0, []
    for r in recs:
        if r.get("source") not in _ABSENCE_SOURCES | {"consistency"}:
            continue
        keep = []
        for e in r.get("evidence") or []:
            u = e.get("url") or ""
            if u.startswith("http"):
                h = re.sub(r"^www\.", "", re.sub(r"^https?://", "", u).split("/")[0].lower())
                path = "/" + "/".join(re.sub(r"^https?://", "", u).split("/")[1:])
                is_file = bool(re.search(r"\.(?:pdf|jpe?g|png|gif|webp|docx?)(?:$|\?)|/(?:wp-content|uploads|media|assets|files)/", path, re.I))      # a brochure or menu in the site's shared uploads folder is still the hotel's
                if (host and h != host) or (scope and not is_file and not path.lower().startswith(scope.lower())):
                    outside += 1
                    continue
            keep.append(e)
        if len(keep) != len(r.get("evidence") or []):
            r["evidence"] = keep
            if not keep:
                emptied.append(r.get("id"))
    _remove(rep, emptied, "its only evidence came from pages that are not this hotel's (another hotel of the brand, or another website)", gate, "evidence_in_scope")
    done("evidence_in_scope", len(recs), outside, "evidence taken from pages outside this hotel's own website or section")

    # 9. 'X is missing' after reading too little of the site: downgraded, never stated as fact
    ratio = cov.get("ratio")
    low = ratio is not None and ratio < 0.5
    down = 0
    if low:
        for r in c.get("recommendations") or []:
            if r.get("source") in _ABSENCE_SOURCES and ABSENCE.search(" ".join(str(r.get(k) or "") for k in ("title", "finding"))) and r.get("confidence") != advice.EXPER:
                _downgrade(r, f"Only {cov.get('pages_read')} of {cov.get('pages_attempted')} pages could be read, so this may be stated on a page that was not read.", advice)
                if r.get("priority") in ("critical", "high"):
                    r["priority"] = "medium"
                down += 1
        if down:
            gate["changes"].append({"check": "absence_low_coverage", "id": "coverage", "what": f"{down} 'not stated' finding(s) set to Worth checking: only {cov.get('pages_read')} of {cov.get('pages_attempted')} pages were read"})
    done("absence_low_coverage", len(c.get("recommendations") or []), down, "'not stated' findings made after reading less than half the site")

    # 10. priority must match how sure we are: nothing uncertain is critical or high
    capped = 0
    for r in c.get("recommendations") or []:
        if r.get("priority") in ("critical", "high") and (r.get("confidence_label") == "Worth checking" or r.get("confidence") == advice.EXPER) and r.get("tag") not in ("site-check", "former-name"):
            r["priority"] = "medium"
            capped += 1
    if capped:
        gate["changes"].append({"check": "priority_vs_confidence", "id": "priority", "what": f"{capped} uncertain finding(s) lowered from high to medium priority"})
    done("priority_vs_confidence", len(c.get("recommendations") or []), capped, "high-priority findings that rest on uncertain evidence")

    # 11. never 'not on Booking.com': we do not read booking sites, so absence is never claimed
    reworded = 0
    for r in c.get("recommendations") or []:
        for k in ("title", "finding", "action"):
            v = r.get(k)
            if isinstance(v, str) and _LISTING_ABSENT.search(v):
                r[k] = _LISTING_ABSENT.sub(lambda m: f"not found by our searches on {m.group(1)}", v)
                reworded += 1
    if reworded:
        gate["changes"].append({"check": "listing_claims", "id": "listings", "what": f"{reworded} claim(s) that the hotel is not on a booking site reworded to 'not found by our searches'"})
    done("listing_claims", len(c.get("recommendations") or []), reworded, "claims that the hotel is missing from a booking site (those sites are not read)")

    # 12 and 13. text a hotel would see: no web markup, no broken placeholders, no duplicates
    cleaned, broken, dup, seen = 0, [], [], {}
    for r in c.get("recommendations") or []:
        for k in _TEXT_KEYS:
            v = r.get(k)
            nv = _clean_text(v)
            if nv != v:
                r[k] = nv
                cleaned += 1
        for st in r.get("steps") or []:
            if isinstance(st, dict):
                for k in ("title", "detail"):
                    if isinstance(st.get(k), str):
                        st[k] = _clean_text(st[k])
        for e in r.get("evidence") or []:
            if isinstance(e.get("snippet"), str):
                e["snippet"] = _INVIS.sub("", e["snippet"])
        title = (r.get("title") or "").strip()
        if not title or _LEAK.search(title) or _LEAK.search(r.get("action") or ""):
            broken.append(r.get("id"))
            continue
        key = evidence.fold(title)
        if key in seen:
            dup.append(r.get("id"))
        else:
            seen[key] = r.get("id")
    _remove(rep, broken, "its wording was incomplete (an unfilled placeholder)", gate, "text_quality")
    _remove(rep, dup, "the same recommendation appeared twice", gate, "text_quality")
    if broken:
        review.append({"what": f"{len(broken)} recommendation(s) had unfilled placeholders and were removed: a bug to look at", "ids": broken})
    done("text_quality", len(c.get("recommendations") or []) + len(broken) + len(dup), cleaned + len(broken) + len(dup), "web markup, unfilled placeholders and duplicate recommendations")

    # 14. the hotel's tracked prompts must have been asked
    ai = rep.get("ai_sample") or {}
    bench = [b for b in ((rep.get("benchmark") or {}).get("prompts") or []) if b.get("text")]
    asked_tracked = any(i.get("source") == "benchmark" for i in ai.get("items") or [])
    plan_err = (rep.get("question_plan") or {}).get("error")
    tracked_ok = not ((rep.get("benchmark") or {}).get("reused") and bench and ai.get("status") == "ok" and not asked_tracked)
    if not tracked_ok:
        review.append({"what": "The hotel's tracked prompts were not asked in this check, so it cannot be compared with earlier ones."})
    if plan_err:
        review.append({"what": f"The step that writes this hotel's questions failed ({plan_err[:100]}); fewer questions than usual were asked."})
    if (rep.get("ai_insights") or {}).get("unanalysed"):
        review.append({"what": f"{rep['ai_insights']['unanalysed']} AI answer(s) could not be analysed for the hotels they name; the rival figures leave them out."})
    if ai.get("round2_error"):
        review.append({"what": ai["round2_error"] + " Its answers are not in this report."})
    if tracked_ok and bench and asked_tracked:
        want = {evidence.fold(b["text"]) for b in bench}
        got = {evidence.fold(i.get("text") or "") for i in ai.get("items") or [] if i.get("source") == "benchmark"}
        missing = len(want - got)
        if missing:
            review.append({"what": f"{missing} of the hotel's {len(want)} tracked prompts got no answer in this check, so those prompts cannot be compared with earlier checks."})
    done("tracked_prompts_asked", 1, 0 if tracked_ok else 1, "the hotel's tracked prompts were asked")

    # 15. the hotel itself, or its own name, as a rival 'named instead'
    own = _fold_tokens(meta.get("hotel") or "")
    selfish = 0
    for m in (rep.get("ai_gap") or {}).get("markets") or []:
        rv = m.get("rivals") or []
        keep = [x for x in rv if not (own and _fold_tokens(x.get("name")) and (_fold_tokens(x.get("name")) <= own or own <= _fold_tokens(x.get("name"))))]
        if len(keep) != len(rv):
            selfish += len(rv) - len(keep)
            m["rivals"] = keep
    if selfish:
        gate["changes"].append({"check": "self_as_rival", "id": "rivals", "what": f"the hotel itself was listed {selfish} time(s) among the hotels 'named instead': removed"})
    done("self_as_rival", len((rep.get("ai_gap") or {}).get("markets") or []), selfish, "the hotel itself listed among the hotels named instead of it")

    # 16. things a person should look at before relying on the report
    if c.get("error"):
        review.append({"what": f"The website analysis crashed in this check ({str(c['error'])[:120]}), so the report has no findings about the website. A bug to look at."})
    errs = rep.get("step_errors") or []
    if errs:
        review.append({"what": f"{len(errs)} step(s) of this check failed and left their part of the report empty or partial: "
                               + "; ".join(f"{e.get('step')} ({e.get('error', '')[:80]})" for e in errs[:5]) + ("; and more" if len(errs) > 5 else "") + ". Details are in the service log."})
    steps = {"guest_questions": "guest questions", "intel": "hotel identity", "ai_gap": "AI gap", "citations": "AI citations", "external": "outside sources", "competitors": "competitors"}
    for k, label in steps.items():
        v = rep.get(k)
        if isinstance(v, dict) and v.get("error") and v.get("status") not in ("not_configured",):
            review.append({"what": f"The {label} step failed in this check ({str(v['error'])[:100]}), so that part of the report is missing or partial."})
    for r in c.get("recommendations") or []:
        if r.get("tag") == "site-check":
            review.append({"what": "The website read may not be the hotel's own: check the address before relying on this report."})
    if cov.get("unreadable"):
        review.append({"what": "The hotel's website could not be read in this check, so nothing about the website was assessed."})
    elif low:
        review.append({"what": f"Only {cov.get('pages_read')} of {cov.get('pages_attempted')} pages of the website could be read."})
    if (ai.get("status") not in (None, "ok", "not_configured")):
        review.append({"what": f"The AI answers were not collected in this check ({(ai.get('reason') or ai.get('status'))[:100]})."})
