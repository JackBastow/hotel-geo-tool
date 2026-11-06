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
    if note not in (rec.get("finding") or ""):
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
    gate = {"checks": [], "changes": [], "version": 1}

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
    except Exception as e:  # noqa: BLE001 - the report must never fail because of its own check
        gate["error"] = f"{type(e).__name__}: {e}"
    gate["summary"] = f"{len(gate['checks'])} consistency checks ran across the report; {len([x for x in gate['changes'] if x['check'] != 'ai_zero_diagnosis'])} contradiction(s) or misleading item(s) were settled."
    rep["gate"] = gate
    return rep
