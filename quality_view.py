"""
The 'Quality check' panel on the admin hotel page: what the run checks (report_gate) caught and settled in the latest report, and anything a person should look at before the hotel relies on it.
Operator-only: hotels never see this panel.
"""

from html import escape as esc

NAMES = {
    "evidence_in_scope": "Evidence from another hotel's pages or another website",
    "absence_low_coverage": "'Not stated' findings after reading too little of the site",
    "priority_vs_confidence": "High priority resting on uncertain evidence",
    "listing_claims": "Claims that the hotel is missing from a booking site",
    "text_quality": "Web markup, placeholders and duplicates",
    "tracked_prompts_asked": "The hotel's tracked prompts were asked",
    "self_as_rival": "The hotel listed among its own rivals",
    "ai_zero_diagnosis": "Hotel named in none of the AI answers",
}


def setup_problems(name, city, website=""):
    """-> [str] what is wrong with how the hotel was entered. Its name and town go into every question asked about it and every email the tool drafts, so 'brooklandshotelsurrey' or
    'Surrey/Weybridge' makes every prompt and every email wrong."""
    import re
    out = []
    n, c = (name or "").strip(), (city or "").strip()
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", website or "").split("/")[0].lower())
    if not n:
        out.append("The hotel has no name.")
    elif n.lower() in ("hilton", "marriott", "hyatt", "ihg", "accor", "radisson", "premier inn", "travelodge", "holiday inn", "best western", "novotel", "ibis"):
        out.append(f"The hotel's name is only the brand (“{n}”). AI assistants are asked about this one hotel by name, so use its full name (for example “Hilton Barcelona”).")
    elif (" " not in n and len(n) > 12) or re.search(r"\.(?:com|co\.uk|net|org|de|fr|es|se|it)\b|https?://", n, re.I) or (host and n.lower().replace(" ", "") == host.split(".")[0]):
        out.append(f"The hotel's name (“{n}”) looks like its web address, not its real name. It is used in every question asked about the hotel and every email drafted for it: change it to the name guests use.")
    if re.search(r"[/;|]|\band\b|&", c):
        out.append(f"The town (“{c}”) names more than one place. Every question asks about this town, so use the one town travellers search for.")
    elif not c:
        out.append("The hotel has no town.")
    return out


def review_items(rep, hotel=None):
    """-> [str] what a person should look at in this report (empty when nothing). `hotel`: the hotel row (name, city, website), whose set-up is checked too."""
    g = (rep or {}).get("gate") or {}
    out = [x.get("what", "") for x in g.get("needs_review") or [] if x.get("what")]
    if hotel:
        out = setup_problems(hotel.get("name"), hotel.get("city"), hotel.get("website") or "") + out
    if g.get("error"):
        out.append(f"The report's own checks stopped part-way ({g['error'][:120]}): some checks did not run. A bug to look at.")
    rel = (rep or {}).get("release") or {}
    if rel.get("state") in ("review", "blocked"):
        out.append(("BLOCKED: the hotel cannot see this report. " if rel["state"] == "blocked" else "WAITING FOR REVIEW: the hotel cannot see this report until it is approved. ")
                   + " ".join(f"[{x['level']}] {x['what']}" for x in rel.get("reasons") or []))
    ident = (rep or {}).get("identity") or {}
    if ident.get("changed") and ident.get("entered"):
        out.append(f"The hotel is registered as “{ident['entered']}”, but its real name is “{ident['canonical']}” ({ident.get('basis', '')}). Every question and match used the real name. "
                   "Change the name under 'Manage this hotel' so the dashboard shows it too.")
    elif ident.get("needs_review"):
        out.append(ident["needs_review"])
    rc = ((rep or {}).get("meta") or {}).get("identity_recalculated")
    if rc:
        out.append("This report's AI visibility was recalculated from the answers already collected, under the hotel's real name"
                   + (f"; {len(rc.get('withdrawn') or [])} finding(s) written from the earlier figures were withdrawn and are rebuilt at the next check." if rc.get("withdrawn") else "."))
    rel = ident.get("related") or []
    if rel:
        out.append("Kept separate from the hotel, as other properties: " + "; ".join(f"{r['name']} ({r['why']})" for r in rel[:5]) + ".")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def panel(rep, hotel=None):
    """-> HTML for the admin hotel page, or '' when there is nothing to show (no gate record, and the hotel's set-up looks right)."""
    g = (rep or {}).get("gate")
    if not g:
        probs = setup_problems(hotel.get("name"), hotel.get("city"), hotel.get("website") or "") if hotel else []
        return ('<section class="panel"><h4>Quality check</h4><div class="alert warning"><b>Fix this before the next check:</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in probs) + "</ul></div></section>") if probs else ""
    review = review_items(rep, hotel)
    changes = [c for c in g.get("changes") or [] if c.get("check") != "ai_zero_diagnosis"]
    checks = g.get("checks") or []
    head = (f'<div class="alert warning"><b>Look at this before the hotel relies on the report:</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in review) + "</ul></div>"
            if review else '<p class="caption">Nothing in the latest report needs a person to look at it.</p>')
    rows = "".join(f'<tr><td>{esc(NAMES.get(c.get("name"), (c.get("summary") or c.get("name") or "")[:80]))}</td><td>{c.get("looked_at", "")}</td>'
                   f'<td>{"<b>" + str(c.get("found")) + "</b>" if c.get("found") else "0"}</td></tr>' for c in checks)
    fixed = "".join(f'<li>{esc(NAMES.get(c.get("check"), c.get("check") or ""))}: {esc((c.get("what") or "")[:240])}</li>' for c in changes[:40])
    return ('<section class="panel"><h4>Quality check of the latest report</h4>' + head
            + f'<p class="caption">{esc(g.get("summary") or "")} The hotel sees the corrected report; this panel is only shown to you.</p>'
            + (f'<details class="details"><summary>What was corrected ({len(changes)})</summary><div class="details-body"><ul>{fixed}</ul></div></details>' if changes else "")
            + (f'<details class="details"><summary>Every check that ran ({len(checks)})</summary><div class="details-body"><div class="table-wrap"><table class="table">'
               f'<thead><tr><th>Check</th><th>Looked at</th><th>Found</th></tr></thead><tbody>{rows}</tbody></table></div></div></details>' if checks else "")
            + "</section>")
