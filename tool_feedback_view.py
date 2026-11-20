"""
The feedback hotel users send about the tool (the Feedback button on their dashboard), as the admin pages show it: the main admin sees the Westmont portfolio hotels', the individual-hotels
admin sees the individual hotels'. Each can be marked seen or done.
"""

import html

from timeutil import uk_time

esc = html.escape
KIND = {"idea": ("Idea", "brand"), "problem": ("Something wrong", "bad"), "question": ("Question", "warn"), "praise": ("Praise", "good")}
STATUS = {"new": "New", "seen": "Seen", "done": "Done"}
DONE_STYLE = ' style="opacity:.6"'


def panel(rows, post_base, csrf, whose):
    new = sum(1 for r in rows if (r.get("status") or "new") == "new")
    head = (f'<h3 class="grp" style="margin-top:4px">Feedback from hotels <small>{new} new</small></h3>'
            f'<p class="caption">What users of {esc(whose)} sent with the Feedback button on their dashboard: ideas, problems, questions and praise, newest first.</p>')
    if not rows:
        return head + '<div class="alert info">No feedback yet. Hotel users see a Feedback button at the bottom right of their dashboard.</div>'

    def buttons(r):
        out = ""
        for st, label in (("seen", "Mark seen"), ("done", "Mark done"), ("new", "Mark new")):
            if (r.get("status") or "new") != st:
                out += (f'<form method="post" action="{esc(post_base)}/{r["id"]}/{st}" style="display:inline"><input type="hidden" name="csrf" value="{esc(csrf)}">'
                        f'<button class="btn small" type="submit">{label}</button></form> ')
        return out
    body = "".join(
        f'<tr{DONE_STYLE if r.get("status") == "done" else ""}><td>{esc(uk_time(r["created"]))}</td><td><b>{esc(r.get("hotel") or "-")}</b><br><span class="hk-muted">{esc(r.get("email") or "")}</span></td>'
        f'<td><span class="hk-chip {KIND.get(r["kind"], ("", ""))[1]}">{esc(KIND.get(r["kind"], (r["kind"], ""))[0])}</span></td><td style="white-space:pre-wrap">{esc(r["message"])}'
        + (f'<br><span class="hk-muted">on {esc(r["page"])}</span>' if r.get("page") else "") + f'</td><td>{esc(STATUS.get(r.get("status") or "new", "New"))}</td><td>{buttons(r)}</td></tr>'
        for r in rows)
    return (head + '<div class="table-wrap"><table class="table"><thead><tr><th>When (UK time)</th><th>Hotel</th><th>Kind</th><th>Feedback</th><th>Status</th><th></th></tr></thead>'
            f"<tbody>{body}</tbody></table></div>")
