"""
The Strategy tab of a hotel's dashboard: the opportunities, what makes the hotel different, why rivals are recommended instead, and which sites to get listed on, all from the hotel's latest check.
Every claim carries its label (Confirmed, Likely, Worth checking, Supported, Hypothesis) and the page says what it cannot prove.
"""

import html

import differentiation
import opportunities
import rival_analysis
import source_actions

esc = html.escape
CHIP = {"Confirmed": "good", "Likely": "", "Worth checking": "warn", "Supported": "good", "Hypothesis": "warn"}


def _chip(text):
    return f'<span class="hk-chip {CHIP.get(text, "")}">{esc(text)}</span>'


def panel(rep):
    if not rep:
        return '<div class="alert info">The strategy view appears after the first check.</div>'
    c = rep.get("consultant") or {}
    ops = opportunities.build(rep)
    d = c.get("differentiation") or differentiation.build(rep)
    rivals = c.get("rival_analysis") or rival_analysis.build(rep)
    srcs = c.get("source_actions") or source_actions.build(rep)
    out = []
    # 1 opportunities
    out.append('<h3 class="grp" style="margin-top:6px">Your biggest AI discovery opportunities</h3>')
    if ops:
        out.append('<div class="prios">' + "".join(
            f'<article class="prio"><div class="prio-n">{i}</div><div><h4>{esc(o["title"])}</h4><p class="prio-why">{esc(opportunities.sentence(o))}</p>'
            + (f'<div class="prio-do"><b>Reasons the assistant gave</b> {esc(" ".join(o["reasons"][:1]))}</div>' if o["reasons"] else "")
            + (f'<div class="prio-do"><b>Supporting actions</b> {esc("; ".join(x["title"] for x in o["supporting"][:3]))}</div>' if o["supporting"] else "") + "</div></article>" for i, o in enumerate(ops, 1)) + "</div>")
    else:
        out.append('<p class="caption">No search was found where this hotel is a credible choice, is not being named, and comparable hotels are. A wider sample may find more.</p>')
    # 2 differentiation
    out.append('<h3 class="grp">What makes this hotel different</h3>')
    rows = ""
    for s in d.get("strengths", [])[:5]:
        rows += f'<tr><td>Verified strength</td><td><b>{esc(s["label"])}</b></td><td>{esc(s["proof"])}</td><td>{_chip(s["confidence"])}</td></tr>'
    for a in d.get("advantages", [])[:4]:
        rows += f'<tr><td>Advantage over comparable hotels</td><td><b>{esc(a["label"])}</b></td><td>{esc(a["proof"])}</td><td>{_chip(a["confidence"])}</td></tr>'
    for u in d.get("underexplained", [])[:4]:
        rows += f'<tr><td>Under-explained</td><td><b>{esc(u["label"])}</b></td><td>{esc(u["why"])}</td><td>{_chip(u["confidence"])}</td></tr>'
    out.append(('<div class="table-wrap"><table class="table"><thead><tr><th>Kind</th><th>What</th><th>Evidence</th><th>How sure</th></tr></thead><tbody>' + rows + "</tbody></table></div>") if rows
               else '<p class="caption">Nothing distinctive could be established from the pages and sources read.</p>')
    if d.get("opportunities"):
        out.append('<h4>Where this could matter</h4><ul class="wl">' + "".join(
            f'<li><span><b>{esc(o["theme_label"].capitalize())}</b>: {esc(o["finding"])} {esc(o["ai_result"])} <i>{esc(o["action"])}</i></span> {_chip(o["confidence"])}</li>' for o in d["opportunities"][:4]) + "</ul>")
    out.append(f'<p class="caption">{esc(d.get("limits", ""))}</p>')
    # 3 rivals
    out.append('<h3 class="grp">Why rivals are recommended instead</h3>')
    if rivals:
        out.append('<div class="threads">' + "".join(
            f'<article class="thread"><div class="chips"><span class="hk-chip brand">{esc(r["name"])}</span>{_chip(r["label"])}</div><p class="th-ask">{esc(r["statement"])}</p>'
            + (f'<p class="th-why">Cited alongside: {esc(", ".join(r["sources"]))}.</p>' if r["sources"] else "") + (f'<p class="th-why">Facilities noted on its own site: {esc(", ".join(r["site_facts"]))}.</p>' if r["site_facts"] else "")
            + "</article>" for r in rivals) + "</div>")
        out.append('<p class="caption">Supported means at least two kinds of evidence agree (what the assistant said, what it cited, what the rival\'s site shows). A hypothesis is something to investigate. None of it describes how the model decides.</p>')
    else:
        out.append('<p class="caption">No comparable rival stood out in this sample.</p>')
    # 4 where to get listed
    out.append('<h3 class="grp">Where to get listed: the sites AI relies on</h3>')
    if srcs:
        rows = "".join(f'<tr><td><b>{esc(s["domain"])}</b><br><span class="hk-muted">{esc(s["type_label"])}, used {s["cited"]} time(s)</span></td><td>{"Yes" if s["hotel_appears"] else "No"}</td><td>{esc(", ".join(s["rivals"]) or "-")}</td>'
                       f'<td>{esc(s["route"])}</td><td>{esc(s["action"])}<br><span class="hk-muted">{esc(s["why_now"])}</span></td></tr>' for s in srcs)
        out.append('<div class="table-wrap"><table class="table"><thead><tr><th>Site</th><th>Hotel there?</th><th>Rivals featured</th><th>Route to inclusion</th><th>Suggested action</th></tr></thead><tbody>' + rows + "</tbody></table></div>"
                   '<p class="caption">Being listed or covered does not guarantee that any AI assistant will recommend the hotel, and paying for placement is not recommended. Check each site suits the hotel first.</p>')
    else:
        out.append('<p class="caption">No site was found that names rival hotels and not this one.</p>')
    return "".join(out)
