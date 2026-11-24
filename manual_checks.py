"""
Google AI Overviews, checked by hand (Nov 2026). Google offers no official way for software to read AI Overviews, and the third-party services that do it scrape Google against its
terms, which this tool does not do. So a person checks the hotel's tracked prompts in Google and records three things per prompt: did an AI Overview appear, was the hotel named
in it, which sites did it cite. The result sits beside the assistants asked automatically, always labelled 'checked by hand' with the date and who checked.

Stored per hotel and per check (portal_db table manual_checks); the Overview shows the latest set.
"""

import json
import urllib.parse
from html import escape as esc

ENGINE = "google_ai_overview"
NAME = "Google AI Overviews"


def tracked_prompts(rep, limit=15):
    """The hotel's tracked prompts from a check: [{id, text}] (the same ones the assistants were asked)."""
    seen, out = set(), []
    for i in ((rep or {}).get("ai_sample") or {}).get("items") or []:
        if i.get("source") == "benchmark" and i.get("text") and (i.get("qid") or i.get("id")) not in seen and not i.get("names_hotel"):
            seen.add(i.get("qid") or i.get("id"))
            out.append({"id": i.get("qid") or i.get("id"), "text": i["text"]})
    return out[:limit]


def google_link(text, country=None):
    q = {"q": text}
    if country:
        q["gl"] = country.lower()
    return "https://www.google.com/search?" + urllib.parse.urlencode(q)


def counts(rows):
    """-> {"checked", "shown", "named", "date", "by"} from the saved rows of one set, or None."""
    rows = [r for r in rows or [] if r.get("prompt")]
    if not rows:
        return None
    shown = [r for r in rows if r.get("shown")]
    return {"checked": len(rows), "shown": len(shown), "named": sum(1 for r in shown if r.get("named")), "date": max((r.get("checked_at") or "")[:10] for r in rows),
            "by": rows[0].get("checked_by") or "", "sources": sorted({d.strip() for r in shown for d in (r.get("sources") or "").replace(";", ",").split(",") if d.strip()})[:12]}


def form_html(rep, saved, post_url, csrf, country=None):
    """The admin's form: each tracked prompt with a link to search it in Google and the three answers to record."""
    prompts = tracked_prompts(rep)
    if not prompts:
        return '<p class="caption">This check has no tracked prompts to check by hand yet.</p>'
    prev = {r["prompt"]: r for r in saved or []}
    rows = ""
    for k, p in enumerate(prompts):
        s = prev.get(p["text"]) or {}
        rows += (f'<tr><td><a href="{esc(google_link(p["text"], country), quote=True)}" target="_blank" rel="noopener">{esc(p["text"])}</a><input type="hidden" name="p{k}" value="{esc(p["text"], quote=True)}"></td>'
                 f'<td><select name="s{k}"><option value="">-</option><option value="1"{" selected" if s.get("shown") == 1 else ""}>Yes</option><option value="0"{" selected" if s.get("shown") == 0 else ""}>No</option></select></td>'
                 f'<td><select name="n{k}"><option value="">-</option><option value="1"{" selected" if s.get("named") == 1 else ""}>Yes</option><option value="0"{" selected" if s.get("named") == 0 else ""}>No</option></select></td>'
                 f'<td><input name="c{k}" value="{esc(s.get("sources") or "", quote=True)}" placeholder="e.g. tripadvisor.co.uk, visitsurrey.com" style="width:100%"></td></tr>')
    c = counts(saved)
    head = (f'<p class="caption">Last checked {esc(c["date"])}{" by " + esc(c["by"]) if c["by"] else ""}: an AI Overview appeared for {c["shown"]} of {c["checked"]} prompts and named the hotel in '
            f'{c["named"]} of them.</p>' if c else "")
    return (f'<details class="details"><summary>Google AI Overviews: check by hand</summary><div class="details-body"><p class="caption">Google offers no official way for software to read '
            'AI Overviews, so these are checked by hand. Open each prompt (a private window, signed out of Google, gives the most neutral result), then record whether an AI Overview '
            'appeared, whether it named the hotel, and the sites it cited. About ten minutes. The result is shown beside the other assistants, labelled as checked by hand.</p>'
            f'{head}<form method="post" action="{esc(post_url, quote=True)}"><input type="hidden" name="csrf" value="{esc(csrf, quote=True)}"><input type="hidden" name="n" value="{len(prompts)}">'
            '<div class="table-wrap"><table class="table"><thead><tr><th>Prompt (opens Google)</th><th>AI Overview shown?</th><th>Hotel named?</th><th>Sites it cited</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div><button class="btn primary" type="submit">Save the check</button></form></div></details>')


def rows_from_form(form):
    """The posted form -> [{prompt, shown, named, sources}] for the prompts that were answered."""
    out = []
    try:
        n = min(int(form.get("n") or 0), 30)
    except ValueError:
        n = 0
    for k in range(n):
        p = (form.get(f"p{k}") or "").strip()[:300]
        s, nm = form.get(f"s{k}"), form.get(f"n{k}")
        if not p or s not in ("0", "1"):
            continue
        out.append({"prompt": p, "shown": int(s), "named": int(nm) if (s == "1" and nm in ("0", "1")) else 0, "sources": (form.get(f"c{k}") or "").strip()[:300]})
    return out


def as_engine_row(saved):
    """The row for report_model.engine_counts / the Overview table, or None."""
    c = counts(saved)
    if not c:
        return None
    if not c["shown"]:
        return {"engine": ENGINE, "name": NAME, "status": "none_shown", "manual": True, "date": c["date"],
                "reason": f"Checked by hand on {c['date']}: no AI Overview appeared for any of the {c['checked']} prompts."}
    return {"engine": ENGINE, "name": NAME, "status": "ok", "manual": True, "date": c["date"], "named": c["named"], "asked": c["shown"], "pct": round(100 * c["named"] / c["shown"]),
            "recommended": None, "site_cited": None, "shown": c["shown"], "checked": c["checked"], "sources": c["sources"]}
