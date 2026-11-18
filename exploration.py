"""
What the exploratory questions are for, beyond the one check they were asked in. Built only from what the checks already saved (the answers, who each named, the pages each quoted): no extra AI calls.

  suggest()   Exploratory questions worth TRACKING: asked in two or more of the hotel's recent checks and either naming the hotel, or naming the same rival each time. Shown on the Prompts tab with an Add
              button; nothing changes until the hotel confirms its set.
  gap_map()   For each kind of question (the Prompts tab's sections): how often the hotel was named, who was named instead, and which websites the answers quoted when a rival was named and the hotel was not.
              That is a concrete brief: the kind of question to answer on the hotel's own site, and the sites to be listed on. The pages are ones the assistant quoted; nothing is guessed.

Honest by construction: counts are 'n of m answers' or 'n of m checks', from one assistant; a gap is a sample, never a ranking or a cause.
"""

import collections
import html
import re
import urllib.parse

import ai_insights as ains
import ai_questions
import ai_sample
import prompt_sets as ps

esc = html.escape
CHECKS = 4                 # how many recent checks to look across
SIMILAR = 0.8              # the same question, allowing a word or two to differ between checks


def _dom(url):
    d = urllib.parse.urlparse(url or "").netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _is_me(name, hotel, city=""):
    return ai_sample.mentioned(name, hotel, city) and not ains._sibling(name, hotel)


def questions(rep, hotel, city=""):
    """One row per question asked in a check (repeats merged): [{text, angle, kind, tracked, section, named, of, rivals: Counter, rival_answers, quoted: Counter}]. Questions about the hotel itself are left out."""
    items = ((rep or {}).get("ai_sample") or {}).get("items") or []
    extracted = ((rep or {}).get("ai_insights") or {}).get("extracted_answers") or {}
    out = []
    for g in ai_sample.by_question(items):
        if g["kind"] == "direct":
            continue
        first = g["answers"][0] if g["answers"] else {}
        rivals, quoted, rival_answers = collections.Counter(), collections.Counter(), 0
        for a in g["answers"]:
            names = {h["name"] for h in (extracted.get(a["id"]) or []) if h.get("name") and not _is_me(h["name"], hotel, city)}
            for n in names:
                rivals[n] += 1
            if names and not a.get("mentioned"):
                rival_answers += 1
                for d in {_dom(p.get("url")) for p in (a.get("pages") or []) if p.get("cited") and p.get("url")}:
                    if d:
                        quoted[d] += 1
        row = {"text": g["text"], "angle": g.get("angle") or "", "kind": g["kind"], "style": first.get("style") or "", "tracked": first.get("source") == "benchmark",
               "named": g["named"], "of": g["of"], "rivals": rivals, "rival_answers": rival_answers, "quoted": quoted}
        row["section"] = ps.section_of(row)
        out.append(row)
    return out


def recent(db, hotel, n=CHECKS):
    """[(run_at, report)] for the hotel's newest n checks that have AI answers, newest first."""
    out = []
    for r in db.hotel_runs(hotel["hotel_key"]):
        if len(out) >= n:
            break
        try:
            rep = db.get_report(r["id"])
        except Exception:  # noqa: BLE001
            continue
        if ((rep or {}).get("ai_sample") or {}).get("items"):
            out.append((r["run_at"], rep))
    return out


def suggest(db, hotel, have=(), n=CHECKS, limit=6):
    """
    Exploratory questions worth adding to the tracked set: [{text, rests_on: [...], why, section}] for the Prompts tab. A question qualifies when it was asked in at least two of the recent checks, is not
    already in the set (`have`), passes the prompt rules, and either named the hotel in two or more checks, or named the same rival in two or more checks while not naming the hotel.
    """
    checks = recent(db, hotel, n)
    if len(checks) < 2:
        return []
    groups = []                            # [{text, section, checks: [{named, of, rivals}]}]
    for _at, rep in checks:
        for q in questions(rep, hotel["name"], hotel.get("city") or ""):
            if q["tracked"] or q["kind"] != "niche":
                continue
            g = next((g for g in groups if ai_questions._similar(g["text"], q["text"], SIMILAR)), None)
            if g is None:
                g = {"text": q["text"], "section": q["section"], "angle": q["angle"], "checks": []}
                groups.append(g)
            g["checks"].append(q)
    out = []
    for g in groups:
        seen = len(g["checks"])
        if seen < 2 or any(ai_questions._similar(g["text"], h, SIMILAR) for h in have or ()):
            continue
        _t, err = ps.check_prompt(g["text"], hotel["name"], hotel.get("city") or "", ps.anchors_from({"prompts": [{"text": g["text"]}]}))
        if err:
            continue
        me = sum(1 for c in g["checks"] if c["named"])
        rival_checks = collections.Counter(r for c in g["checks"] if not c["named"] for r in c["rivals"])
        rival, rn = rival_checks.most_common(1)[0] if rival_checks else ("", 0)
        if me >= 2:
            why = f"Named the hotel in {me} of the last {seen} checks it was asked in. Tracking it shows whether that holds."
            score = (0, -me)
        elif rn >= 2:
            why = f"Named {rival} in {rn} of the last {seen} checks, and the hotel {'never' if not me else f'in only {me}'}. Tracking it shows whether the work closes that gap."
            score = (1, -rn)
        else:
            continue
        out.append({"text": g["text"], "rests_on": [f"{seen} recent checks"], "why": why, "section": g["section"], "_score": score})
    out.sort(key=lambda s: s["_score"])
    return [{k: v for k, v in s.items() if k != "_score"} for s in out[:limit]]


def gap_map(rep, hotel, city="", own_domain=""):
    """
    -> [{key, title, questions, answers, named, rivals: [(name, answers)], quoted: [(domain, kind, answers)], example, brief}] per kind of question, from one check. Kinds with no questions are left out.
    'quoted' counts the answers that named a rival, did not name the hotel, and quoted that site.
    """
    rows = questions(rep, hotel, city)
    if not rows:
        return []
    out = []
    for key, title, _blurb, _n in ps.SECTIONS:
        qs = [q for q in rows if q["section"] == key]
        if not qs:
            continue
        answers, named = sum(q["of"] for q in qs), sum(q["named"] for q in qs)
        rivals, quoted = collections.Counter(), collections.Counter()
        for q in qs:
            rivals.update(q["rivals"])
            quoted.update(q["quoted"])
        own = (own_domain or "").lower()
        quoted_rows = [(d, ains.source_kind(d, own), c) for d, c in quoted.most_common() if not (own and (d == own or d.endswith("." + own)))][:4]
        missed = sorted([q for q in qs if q["named"] < q["of"] and q["rivals"]], key=lambda q: (q["named"] / max(1, q["of"]), -sum(q["rivals"].values())))
        example = missed[0]["text"] if missed else ""
        brief = ""
        if missed:
            top = ", ".join(n for n, _c in rivals.most_common(2))
            brief = (f"Questions like this named {top} more often than the hotel. Make sure the hotel's own site answers it in plain words a guest would use"
                     + (", and check the hotel is listed, with current facts, on " + ", ".join(d for d, _k, _c in quoted_rows[:2]) + ", which those answers quoted." if quoted_rows else "."))
        out.append({"key": key, "title": title, "questions": len(qs), "answers": answers, "named": named, "rivals": rivals.most_common(3), "quoted": quoted_rows, "example": example, "brief": brief})
    return out


def gap_map_html(gm, checked_on=""):
    """The gap map as a panel for the AI visibility tab."""
    if not gm:
        return ""
    rows = []
    for g in gm:
        pct = round(100 * g["named"] / g["answers"]) if g["answers"] else 0
        tone = "good" if pct >= 50 else "warn" if pct >= 20 else "bad"
        rivals = ", ".join(f"{esc(n)} ({c})" for n, c in g["rivals"]) or "none named"
        quoted = ", ".join(f"{esc(d)} <span class=\"hk-muted\">({esc(k.lower())})</span>" for d, k, _c in g["quoted"]) or "none"
        rows.append(f'<div class="gm-row"><div class="gm-h"><h5>{esc(g["title"])}</h5><span class="gm-pct {tone}">named in {g["named"]} of {g["answers"]} answers</span></div>'
                    f'<div class="gm-meter"><span style="width:{pct}%"></span></div>'
                    f'<p class="caption">{g["questions"]} question{"s" if g["questions"] != 1 else ""}. Named instead: {rivals}. Sites quoted when a rival was named and the hotel was not: {quoted}.</p>'
                    + (f'<p class="gm-brief"><b>Brief.</b> {esc(g["brief"])}' + (f' For example: <i>&ldquo;{esc(g["example"])}&rdquo;</i>' if g["example"] else "") + "</p>" if g["brief"] else "")
                    + "</div>")
    return ('<section class="panel gap-map"><h4>Where the hotel is missing out, by kind of question</h4>'
            f'<p class="caption">From the latest check{(" (" + esc(checked_on) + ")") if checked_on else ""}: every question asked, tracked and exploratory, grouped like the Prompts tab. One assistant, a sample of answers: a pointer to where to work, not a ranking.</p>'
            + "".join(rows) + "</section>")


def facts_html(rep):
    """What the assistant said about the hotel that its website contradicts or does not support (ai_facts), for the AI visibility tab."""
    fc = ((rep or {}).get("ai_insights") or {}).get("facts_check") or {}
    if fc.get("status") != "ok":
        return ""
    rows = fc.get("rows") or []
    if not rows:
        return (f'<section class="panel"><h4>What AI says about the hotel</h4><p class="caption">In the latest check {fc.get("passages", 0)} answer passage{"s" if fc.get("passages") != 1 else ""} described the hotel; '
                f'nothing in them contradicted its website ({fc.get("matches", 0)} statement{"s" if fc.get("matches") != 1 else ""} matched).</p></section>')
    lab = {"differs": ("Wrong", "bad"), "check": ("Check", "warn")}
    body = "".join(f'<tr><td><span class="pill {lab[r["status"]][1]}">{lab[r["status"]][0]}</span></td><td>{esc(r["label"])}</td><td>&ldquo;{esc(r["says"])}&rdquo;'
                   + (f' <span class="hk-muted">({r["times"]} answers)</span>' if r.get("times", 1) > 1 else "") + f'</td><td>{esc(r["our_record"])}</td></tr>' for r in rows)
    return ('<section class="panel"><h4>What AI says about the hotel</h4><p class="caption">Statements from the answers that named the hotel, compared with its own website. '
            '"Wrong" means the website clearly says otherwise; "Check" means the website does not confirm it. Each one is also an action.</p>'
            f'<div class="table-wrap"><table class="table"><thead><tr><th></th><th>About</th><th>The assistant said</th><th>The website</th></tr></thead><tbody>{body}</tbody></table></div></section>')
