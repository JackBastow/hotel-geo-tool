"""
The report at a glance, as plain data: the scorecard (every area of the readiness score with a verdict, plus the AI sample against its aim) and the two lists a manager reads first
(where the hotel does well, where it does not). The management PDF and the dashboard's Overview both draw from here, so they always show the same areas, numbers and lists.
"""

AREA_MEANING = {"ai_visibility": "How often AI assistants name the hotel (sampled)", "otas": "Found on booking platforms (presence only)", "reviews": "Guest reviews and the hotel's replies",
                "editorial": "Coverage by travel writers and blogs", "website": "The hotel's own website: content and technical set-up", "social": "Social media and community presence",
                "entity": "Outside sources agree on name, address and phone", "freshness": "How up to date the published information is"}
AI_AIM_PCT = 30            # the owner's aim for how often the hotel is named; shown as an aim, never forced
SCALE_NOTE = "Strong is 75 or more, partly there 50 to 74, weak under 50. AI visibility is a sample of answers from the assistants asked and is not part of the readiness score."


def short(text, n):
    """Trim to a sentence or word boundary, never mid-word."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    for sep in (". ", "; ", ", ", " "):
        i = cut.rfind(sep)
        if i > n * 0.55:
            return cut[:i].rstrip(" .;,") + "..."
    return cut.rstrip() + "..."


def verdict(score):
    """-> (word, tone) where tone is 'good', 'warn', 'bad' or 'grey'."""
    if score is None:
        return "Not measured", "grey"
    return ("Strong", "good") if score >= 75 else ("Partly there", "warn") if score >= 50 else ("Weak", "bad")


def ai_named(rep):
    """(named, asked) from the report's one count of the AI sample (the reconciled marks every page uses), or None when no answers were collected."""
    import report_model
    try:
        ai = report_model.ai_counts(rep)
    except Exception:  # noqa: BLE001
        return None
    return (ai["named"], ai["asked"]) if ai else None


def scorecard(rep):
    """-> {"rows": [{label, score, verdict, tone, meaning, partial}], "ai": {pct, named, asked, ok} or None}. Rows are strongest first, unmeasured last."""
    cats = ((rep or {}).get("scorecard") or {}).get("categories") or []
    rows = []
    for c in cats:
        if c.get("key") == "ai_visibility":
            continue
        score = c.get("score") if c.get("assessed") else None
        word, tone = verdict(score)
        rows.append({"label": c.get("label", ""), "score": score, "verdict": word, "tone": tone, "meaning": AREA_MEANING.get(c.get("key"), ""), "partial": bool(c.get("partial"))})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    ai = None
    n = ai_named(rep)
    if n:
        pct = round(100 * n[0] / n[1])
        ai = {"pct": pct, "named": n[0], "asked": n[1], "ok": pct >= AI_AIM_PCT}
    return {"rows": rows, "ai": ai}


def top_fixes(c, n=5):
    """The top required fixes the report is sure of (the same ones the management report lists)."""
    import report_model
    recs = {r.get("id"): r for r in (c or {}).get("recommendations") or []}
    return [recs[i] for i in report_model.priorities_of(c, n) if i in recs]


def strengths_weaknesses(rep, top=None):
    """-> (good, bad): two plain lists, each item concrete and taken from the audit."""
    rep = rep or {}
    c = rep.get("consultant") or {}
    if top is None:
        top = top_fixes(c)
    good, bad = [], []
    for cat_ in (rep.get("scorecard") or {}).get("categories") or []:
        if cat_.get("assessed") and cat_.get("score") is not None and cat_.get("key") != "ai_visibility":
            line = f"{cat_['label']}: {cat_['score']}/100. {short(AREA_MEANING.get(cat_['key'], ''), 80)}"
            (good if cat_["score"] >= 75 else bad if cat_["score"] < 60 else []).append(line)
    for sig in (c.get("understanding") or {}).get("strong_signals", [])[:2]:
        good.append(f"The website clearly shows: {short(sig, 90)}")
    for seg in (c.get("traveller") or {}).get("segments", []):
        cn = seg.get("counts") or {}
        tot = cn.get("confirmed", 0) + cn.get("partial", 0) + cn.get("missing", 0)
        if tot and cn["confirmed"] >= max(2, tot * 0.6):
            good.append(f"{seg['label']}: {cn['confirmed']} of {tot} things travellers need to know are stated on the website")
        elif tot and cn["missing"] >= max(2, tot * 0.4):
            miss = [r["label"] for r in seg.get("requirements") or [] if r.get("state") == "missing"][:3]
            bad.append(f"{seg['label']}: {cn['missing']} of {tot} things travellers need to know are missing ({', '.join(miss)})")
    for f in c.get("facility_depth") or []:
        n_ = len(f.get("found") or [])
        if f.get("disputed"):
            continue                                 # another check read this facility as stated: it is a lead in the plan, not a verdict here
        if f.get("thin"):
            bad.append(f"{f['label']} is mentioned but only {n_} of {f['total']} details are stated (missing: {', '.join(m['label'].split(' (')[0].lower() for m in f['missing'][:3])})")
        else:
            good.append(f"{f['label']}: {n_} of {f['total']} details are stated on the website")
    gap = rep.get("ai_gap") or {}
    for m in (gap.get("markets") or []):
        q = short(m.get("question"), 80)
        if m.get("named") and m["named"] >= m["of"] / 2:
            good.append(f"AI names the hotel for “{q}” ({m['named']} of {m['of']} answers)")
        elif m.get("gap") and m.get("rivals"):
            bad.append(f"AI does not name the hotel for “{q}” ({m['named']} of {m['of']}); it names {m['rivals'][0]['name']} instead")
    cit = rep.get("citations") or {}
    if cit.get("basis") == "named" and cit.get("answers"):
        if cit.get("own_answers", 0) >= cit["answers"] / 2:
            good.append(f"The hotel's own website is one of the sources AI uses when it names the hotel ({cit['own_answers']} of {cit['answers']} answers)")
        elif cit.get("ota_answers", 0) > cit.get("own_answers", 0):
            bad.append(f"When AI names the hotel it cites booking sites in {cit['ota_answers']} of {cit['answers']} answers and the hotel's own website in {cit.get('own_answers', 0)}")
    for r in top[:3]:
        bad.append(short(r.get("short_title") or r.get("title"), 120))
    serious = [r for r in c.get("recommendations") or [] if r.get("source") == "intel" and r.get("kind") == "fix" and r.get("priority") in ("critical", "high")]
    if not any("hygiene" in b.lower() or "risk" in b.lower() for b in bad) and not serious:
        good.append("No serious reputation or consistency problem was found in the outside sources checked")
    seen = set()
    good = [x for x in good if not (x in seen or seen.add(x))][:6]
    bad = list(dict.fromkeys(bad))[:7]
    return good, bad


# ----------------------------------------------------------------------------- the dashboard's version (HTML)

def scorecard_html(rep):
    from html import escape as esc
    sc = scorecard(rep)
    if not sc["rows"] and not sc["ai"]:
        return ""
    colour = {"good": "#2e7d4f", "warn": "#a3700b", "bad": "#b3362c", "grey": "#8a8f9c"}

    def bar(score, tone):
        w = 0 if score is None else max(0, min(100, score))
        return f'<div class="p-track" style="height:8px;min-width:90px"><div class="p-fill" style="width:{w}%;background:{colour[tone]}"></div></div>'
    body = "".join(f'<tr><td>{esc(r["label"])}{" (partial)" if r["partial"] else ""}</td><td><b>{"-" if r["score"] is None else r["score"]}</b></td><td>{bar(r["score"], r["tone"])}</td>'
                   f'<td style="color:{colour[r["tone"]]}">{esc(r["verdict"])}</td><td class="hk-muted">{esc(r["meaning"])}</td></tr>' for r in sc["rows"])
    if sc["ai"]:
        a = sc["ai"]
        tone = "good" if a["ok"] else "warn"
        body += (f'<tr><td><b>AI visibility (sampled)</b></td><td><b>{a["pct"]}%</b></td><td>{bar(a["pct"], tone)}</td><td style="color:{colour[tone]}">{"Meets the aim" if a["ok"] else "Below the aim"}</td>'
                 f'<td class="hk-muted">Named in {a["named"]} of {a["asked"]} answers (aim: about {AI_AIM_PCT}%)</td></tr>')
    return ('<div class="sec-head"><h3>Scorecard at a glance</h3></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>Area</th><th>Score</th><th></th><th>Verdict</th>'
            f'<th>What it covers</th></tr></thead><tbody>{body}</tbody></table></div><p class="caption">{SCALE_NOTE}</p></section>')


def engines_html(rep):
    """'Named by each assistant' on the Overview: the hotel's tracked prompts put to every assistant asked, one row each; an assistant not asked says why, never 0%."""
    from html import escape as esc
    import report_model
    rows = report_model.engine_counts(rep)
    if not any(r["status"] in ("ok", "none_shown") for r in rows[1:]):
        return ""                                     # only Claude was asked: the rest of the Overview already shows it
    body = ""
    for r in rows:
        if r.get("manual"):
            if r["status"] == "ok":
                body += (f'<tr><td><b>{esc(r["name"])}</b><br><span class="hk-muted">checked by hand, {esc(r["date"])}</span></td><td><b>{r["pct"]}%</b></td>'
                         f'<td>{r["named"]} of {r["asked"]} Overviews shown ({r["checked"]} prompt{"s" if r["checked"] != 1 else ""} checked)</td><td>-</td><td class="hk-muted">{esc(", ".join(r.get("sources") or [])[:80])}</td><td>-</td></tr>')
            else:
                body += f'<tr><td>{esc(r["name"])}</td><td colspan="5" class="hk-muted">{esc(r.get("reason") or "")}</td></tr>'
        elif r["status"] == "ok":
            inst = ", ".join(f"{n} ({k})" for n, k in (r.get("instead") or [])) or "-"
            body += (f'<tr><td><b>{esc(r["name"])}</b></td><td><b>{r["pct"]}%</b></td><td>{r["named"]} of {r["asked"]}</td><td>{r["recommended"]}</td>'
                     f'<td>{r.get("site_cited", 0)}</td><td class="hk-muted">{esc(inst)}</td></tr>')
        else:
            body += f'<tr><td>{esc(r["name"])}</td><td colspan="5" class="hk-muted">Not tested: {esc(short(r.get("reason") or "", 120))}</td></tr>'
    return ('<div class="sec-head"><h3>Named by each AI assistant</h3></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>Assistant</th><th>Named</th>'
            '<th>Answers</th><th>Recommended</th><th>Cited your site</th><th>Named instead (answers)</th></tr></thead><tbody>' + body + '</tbody></table></div><p class="caption">The hotel&rsquo;s tracked prompts, put to each assistant '
            'through its official API with live web search, the same questions for each. A sample of answers on the day of the check, not a ranking; the apps people use can differ a little '
            '(memory, account history). Google AI Overviews have no official API, so they are checked by hand, on the date shown.</p></section>')


def strengths_html(rep):
    from html import escape as esc
    good, bad = strengths_weaknesses(rep)
    if not good and not bad:
        return ""

    def col(title, items, cls, empty):
        li = "".join(f"<li>{esc(x)}</li>" for x in items) or f'<li class="hk-muted">{esc(empty)}</li>'
        return f'<section class="panel sw {cls}"><h4>{title}</h4><ul>{li}</ul></section>'
    return ('<div class="ov-grid even sw-grid">' + col("Where the hotel does well", good, "sw-good", "Nothing stood out as strong in what could be measured.")
            + col("Where it does not", bad, "sw-bad", "No clear weakness was found.") + "</div>")
