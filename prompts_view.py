"""
The Prompts tab of a hotel's dashboard: the recommended prompts, an editor, the warning about changing them, and the confirmation. See prompt_sets.py for the rules and the reasons.
"""

import html

import prompt_sets as ps
from timeutil import uk_date

esc = html.escape


def _row(p, editable, i):
    chip = {"recommended": "Recommended", "own": "Yours"}.get(p.get("source"), "Recommended")
    tag = f'<span class="hk-chip {"brand" if p.get("source") == "own" else ""}">{esc(p.get("angle") or chip)}</span>'
    style = f'<span class="hk-chip">{esc(p["style"].capitalize())}</span>' if p.get("style") else ""
    why = f'<div class="prow-why">{esc(p.get("why") or "")}</div>' if p.get("why") else ""
    if editable:
        return (f'<div class="prow" data-id="{esc(p.get("id") or "")}" data-source="{esc(p.get("source") or "recommended")}" data-angle="{esc(p.get("angle") or "")}" data-style="{esc(p.get("style") or "")}">'
                f'<div class="prow-n">{i}</div><div class="prow-main"><textarea rows="2" maxlength="220" aria-label="Prompt {i}">{esc(p["text"])}</textarea>'
                f'<div class="prow-meta">{tag}{style}</div>{why}<div class="prow-err" hidden></div></div><button type="button" class="btn small pdel">Remove</button></div>')
    return (f'<div class="prow ro"><div class="prow-n">{i}</div><div class="prow-main"><div class="prow-text">{esc(p["text"])}</div><div class="prow-meta">{tag}{style}</div>{why}</div></div>')


def _suggestions(sug):
    if not sug:
        return ""
    rows = "".join(f'<div class="psug-row"><div><div class="psug-text">{esc(s["text"])}</div><div class="prow-why">Rests on: {esc("; ".join(s["rests_on"]))}. {esc(s["why"])}</div></div>'
                   f'<button type="button" class="btn small psugadd" data-text="{esc(s["text"], quote=True)}" data-why="{esc("Rests on: " + "; ".join(s["rests_on"]), quote=True)}">Add</button></div>' for s in sug)
    return ('<section class="panel psug"><h4>More specific prompts we could test</h4><p class="caption">Built from facts your own pages state (a place you are close to, a facility, a kind of traveller). Narrow searches show where the hotel '
            f'deserves to compete. Add the ones you want; nothing changes until you confirm.</p>{rows}</section>')


def panel(state, hotel, url, editable=True, runs_since=0, suggestions=None):
    """The whole tab as HTML. `state` is prompt_sets.state(); `url` is where changes are sent; `runs_since` is how many checks used the confirmed set."""
    active, draft = state["active"], state["draft"]
    warn = f'<div class="alert warning prompt-warn"><b>Before you confirm.</b> {esc(ps.WARNING)}</div>'
    guide = f'<p class="lede">{esc(ps.GUIDE)}</p>'
    head = '<h3 class="grp" style="margin-top:6px">The prompts we ask AI about your hotel</h3>'
    if not active and not draft:
        return (head + guide + '<div class="alert info">Your recommended prompts appear here after the first check of the hotel, written from what your website says and the places around it. '
                'You will be asked to review and confirm them.</div>')
    status = ""
    if active:
        status = (f'<div class="alert success"><b>Confirmed: version {active["version"]}</b>, on {esc(uk_date(active["confirmed_at"]))}' + (f' by {esc(active["confirmed_by"])}' if active.get("confirmed_by") else "")
                  + f'. {runs_since} check{"s" if runs_since != 1 else ""} {"has" if runs_since == 1 else "have"} used it so far. Every check asks exactly these {len(active["prompts"])} prompts.</div>')
    elif draft:
        status = ('<div class="alert warning"><b>Not confirmed yet.</b> Until you confirm, the checks use prompts chosen automatically, which may change from check to check. '
                  'Review the recommended set below, change anything you like, then confirm.</div>')
    attrs = f'data-url="{esc(url)}" data-min="{ps.MIN_PROMPTS}" data-max="{ps.MAX_PROMPTS}" data-rec="{ps.RECOMMENDED}" data-confirmed="{1 if active else 0}"'
    if draft and editable:
        rows = "".join(_row(p, True, i) for i, p in enumerate(draft["prompts"], 1))
        changing = bool(active)
        title = "Change your prompts" if changing else "Review the recommended prompts"
        change_note = (f'<div class="alert warning"><b>You are changing a confirmed set.</b> Version {active["version"]} stays in use until you confirm this new set. Results after the change start a new baseline.</div>' if changing else "")
        agree2 = ('<label class="agree"><input type="checkbox" id="agree-change"> I understand that changing the prompts makes results from before and after the change harder to compare.</label>' if changing else "")
        return (head + guide + status + change_note + warn
                + _suggestions(suggestions) + f'<section class="panel prompts" {attrs}><h4>{title}</h4><div class="pcount"></div><div id="prow-list">{rows}</div>'
                  '<div class="pbar"><button type="button" class="btn" id="padd">Add a prompt of your own</button></div>'
                  '<div class="pconfirm"><label class="agree"><input type="checkbox" id="agree"> I am happy with these prompts and I will keep them for a while.</label>' + agree2
                  + '<div class="pbtns"><button type="button" class="btn primary" id="pconfirm" disabled>Confirm these prompts</button> <button type="button" class="btn" id="psave">Save as a draft</button>'
                  + (' <button type="button" class="btn" id="pdiscard">Discard my changes</button>' if changing else "") + '</div><div class="pmsg" role="status"></div></div></section>')
    rows = "".join(_row(p, False, i) for i, p in enumerate(active["prompts"], 1))
    btn = (f'<section class="panel prompts" {attrs}><h4>Prompts in use (version {active["version"]})</h4><div id="prow-list">{rows}</div>'
           + ('<div class="pbar"><button type="button" class="btn" id="pchange">Change these prompts</button> <span class="hk-muted">You will see the warning again before you confirm.</span></div><div class="pmsg" role="status"></div>' if editable else "")
           + "</section>")
    hist = ""
    if len(state["history"]) > 1:
        hist = "<details class=\"details\"><summary>Earlier versions</summary><div class=\"details-body\"><ul>" + "".join(
            f'<li>Version {s["version"]}: {len(s["prompts"])} prompts, confirmed {esc(uk_date(s["confirmed_at"]))}</li>' for s in state["history"][1:]) + "</ul></div></details>"
    return head + guide + status + btn + hist
