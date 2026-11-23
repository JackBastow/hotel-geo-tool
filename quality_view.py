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


def review_items(rep):
    """-> [str] what a person should look at in this report (empty when nothing)."""
    g = (rep or {}).get("gate") or {}
    out = [x.get("what", "") for x in g.get("needs_review") or [] if x.get("what")]
    if g.get("error"):
        out.append(f"The report's own checks stopped part-way ({g['error'][:120]}): some checks did not run. A bug to look at.")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def panel(rep):
    """-> HTML for the admin hotel page, or '' when the report has no gate record (made before the checks existed)."""
    g = (rep or {}).get("gate")
    if not g:
        return ""
    review = review_items(rep)
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
