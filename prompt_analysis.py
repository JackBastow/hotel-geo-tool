"""
The Prompt analysis tab of a hotel's dashboard: every question put to the AI assistant in the latest check, one line each, for a marketing manager to read at a glance.

For each prompt: was the hotel named (n of m answers), who was named instead, the main reason the assistant gave for them, and ONE thing to do about it. The evidence behind each line (the rivals with
their reasons, what the hotel's own pages say, the pages the assistant cited) is one click away, not on the page. Prompts are grouped by kind (as on the Prompts tab), the hotel's tracked prompts first.

Honesty: a sample from one assistant on one day; 'what to do' follows from a difference in the evidence and is never presented as the cause of the assistant's choice. The same findings feed the
Recommendations (source 'ai_gap'), where they can be marked done.
"""

import html

import evidence

import portal_view
import prompt_sets
import textutil

esc = html.escape


def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _real(snippet):
    """A page quote that is a sentence, not a menu or footer strip."""
    return bool(snippet) and not (textutil.looks_like_nav(snippet) or textutil.looks_like_list(snippet))


def _todo(m, crit, arts):
    """One plain action for this prompt, and its kind (site | sources | none | watch)."""
    if m["status"] == "named":
        return "Nothing to do: named every time.", "none"
    if not m["rivals"]:
        if m.get("other_category"):
            return "Not a gap: the hotels named are a different price category.", "none"
        return "Nothing yet: no comparable hotel stood out.", "watch"
    weak = [c for c in crit if c["hotel"]["state"] == "not_found" or (c["hotel"]["state"] in ("strong", "mentioned") and not _real(c["hotel"].get("snippet")))]
    passing = [c for c in crit if c["hotel"]["state"] == "mentioned" and _real(c["hotel"].get("snippet"))]
    if weak or passing:
        c = (weak or passing)[0]
        return (f"State {c['label']} clearly on your website (if you offer it)." if weak else f"Give {c['label']} its own clear section on your website."), "site"
    missing = [a for a in arts if m["qid"] in (a.get("questions") or []) and a.get("read") == "ok" and a.get("rivals_in") and a.get("hotel_in") is False]
    if missing:
        a = missing[0]
        return f"Get featured on {a['domain']}: it lists {', '.join(a['rivals_in'][:2])}, not you.", "sources"
    if crit:
        return "Your site says it; get it onto the sites AI reads (see Competitors).", "sources"
    return f"See where {', '.join(r['name'] for r in m['rivals'][:2])} are featured (Competitors).", "watch"


def _cell_named(m):
    tone = "good" if m["status"] == "named" else "warn" if m["status"] == "sometimes" else "bad"
    word = "Yes" if m["status"] == "named" else "Sometimes" if m["status"] == "sometimes" else "No"
    return f'<span class="hk-chip {tone}">{word}</span><br><span class="hk-muted">{m["named"]} of {m["of"]}</span>'


ENGINE_NAMES = {"chatgpt": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity"}


def _engines_by_prompt(rep):
    """{folded prompt text: [(assistant, named, of)]} for the other assistants asked the tracked prompts."""
    out = {}
    for e, r in ((rep or {}).get("ai_engines") or {}).items():
        if not isinstance(r, dict) or r.get("status") != "ok":
            continue
        tally = {}
        for i in r.get("items") or []:
            if i.get("mentioned") is None:
                continue
            k = evidence.fold(i.get("text") or "")
            t = tally.setdefault(k, [0, 0])
            t[1] += 1
            t[0] += 1 if i.get("mentioned") else 0
        for k, (n, of) in tally.items():
            out.setdefault(k, []).append((ENGINE_NAMES.get(e, e), n, of))
    return out


def _engine_lines(rows):
    if not rows:
        return ""
    return "<br>" + "".join(f'<span class="hk-muted">{esc(name)} {n} of {of}</span><br>' for name, n, of in rows)


def _evidence(m, crit, obs, arts):
    """The detail behind one line, for whoever wants it."""
    rows = "".join(f'<tr><td>{esc(r["name"])}</td><td>{r["answers"]} of {r["of"]}</td><td>{esc(str(r.get("best_rank") or "-"))}</td><td>{esc("; ".join(r.get("reasons") or []) or "-")}</td></tr>' for r in m["rivals"])
    out = (f'<div class="table-wrap"><table class="table"><thead><tr><th>Named instead</th><th>Answers</th><th>Best place</th><th>The assistant&rsquo;s reason</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else "")
    if m.get("other_category"):
        out += '<p class="caption">Also named, in a different category (not treated as competitors): ' + esc(", ".join(r["name"] for r in m["other_category"])) + ".</p>"
    word = {"strong": "your pages state it clearly", "mentioned": "your pages mention it in passing", "not_found": "your pages do not mention it", "not_assessed": "not checked"}
    if crit:
        out += "<h6>Why they were picked, beside your own pages</h6><ul>" + "".join(
            f'<li><b>{esc(c["label"])}</b> ({esc(", ".join(c["rivals"][:3]))}): {esc(word.get(c["hotel"]["state"] if _real(c["hotel"].get("snippet")) or c["hotel"]["state"] == "not_found" else "not_found", "-"))}'
            + (f' &mdash; &ldquo;{esc(_short(c["hotel"]["snippet"], 120))}&rdquo;' if _real(c["hotel"].get("snippet")) else "") + "</li>" for c in crit) + "</ul>"
    src = [o for o in obs if o["kind"] in ("source", "facility")]
    if src:
        out += "<h6>Other differences seen (not proven causes)</h6><ul>" + "".join(
            f'<li>{esc(o["text"])} ' + " ".join(f'<a href="{esc(u, quote=True)}" target="_blank" rel="noopener">page</a>' for u in (o.get("urls") or []) if str(u).startswith(("http://", "https://"))) + "</li>" for o in src) + "</ul>"
    return out or '<p class="caption">No more detail for this prompt.</p>'


def panel(rep):
    if not rep:
        return '<div class="alert info">The prompt analysis appears after the first check.</div>'
    ai = rep.get("ai_sample") or {}
    gap = rep.get("ai_gap") or {}
    if ai.get("status") != "ok" or not ai.get("items"):
        return '<div class="alert info">No AI answers were collected in the latest check, so there is nothing to analyse yet.</div>'
    markets = [m for m in gap.get("markets") or [] if m.get("kind") != "direct"]
    if not markets:
        return '<div class="alert info">The answers of the latest check were not analysed for who was named instead. The next check will show it.</div>'
    # the hotel's tracked prompts: asked as such (a later check), or the set this check froze as the hotel's benchmark (its first check)
    bench = {evidence.fold(b.get("text", "")) for b in ((rep.get("benchmark") or {}).get("prompts") or []) if b.get("text")}
    tracked = {i.get("qid") or i["id"] for i in ai["items"] if i.get("source") == "benchmark" or evidence.fold(i.get("text", "")) in bench}
    crit_by, obs_by, arts = gap.get("criteria") or {}, gap.get("observations") or {}, gap.get("articles") or []
    n_named = sum(1 for m in markets if m["status"] == "named")
    n_some = sum(1 for m in markets if m["status"] == "sometimes")
    kinds = {"site": 0, "sources": 0}
    rows_by = {}
    by_engine = _engines_by_prompt(rep)               # the same tracked prompt, asked of ChatGPT, Gemini and Perplexity
    for m in markets:
        crit, obs = crit_by.get(m["qid"]) or [], obs_by.get(m["qid"]) or []
        todo, kind = _todo(m, crit, arts)
        kinds[kind] = kinds.get(kind, 0) + 1
        sec = prompt_sets.section_of({"angle": m.get("angle"), "text": m["question"]})
        who = ", ".join(f'{r["name"]} ({r["answers"]}/{r["of"]})' for r in m["rivals"][:2]) or ("hotels in another category" if m.get("other_category") and m["status"] != "named" else "-")
        why = (crit[0]["label"] if crit else _short((m["rivals"][0].get("reasons") or ["-"])[0], 70) if m["rivals"] else "-")
        row = (f'<tr><td><b>{esc(m["question"])}</b>' + (' <span class="hk-chip brand">tracked</span>' if m["qid"] in tracked else "") + f'</td><td>{_cell_named(m)}{_engine_lines(by_engine.get(evidence.fold(m["question"])))}</td><td>{esc(who)}</td><td>{esc(why)}</td>'
               f'<td>{esc(todo)}' + (f'<details class="details pa-ev"><summary>Evidence</summary><div class="details-body">{_evidence(m, crit, obs, arts)}</div></details>' if m["status"] != "named" else "") + "</td></tr>")
        rows_by.setdefault(sec, []).append((m["qid"] not in tracked, row))
    perr = ((rep.get("question_plan") or {}).get("error") or "")
    warn = (f'<div class="alert warning"><b>Fewer questions than usual in this check.</b> The step that writes the questions for this hotel did not finish ({esc(perr[:120])}), '
            'so only its tracked prompts and the standard town questions were asked. The next check tries again.</div>' if perr else "")
    head = warn + ('<p class="lede">Every question we put to the AI assistant in the latest check: whether it named you, who it named instead, why, and the one thing to do about it. '
            'Open &ldquo;Evidence&rdquo; on a line for the detail.</p>'
            + portal_view.kpis_raw([("Prompts asked", str(len(markets)), f"{len(tracked & {m['qid'] for m in markets})} of them your tracked prompts", portal_view.BRAND),
                                    ("Named every time", str(n_named), f"and sometimes in {n_some} more", portal_view.GOOD),
                                    ("Fix on your website", str(kinds.get("site", 0)), "prompts where your pages do not say why rivals were picked", portal_view.WARN),
                                    ("Fix on other sites", str(kinds.get("sources", 0)), "prompts where the gap is on the sites AI reads", portal_view.WARN)]))
    body = ""
    for key, title, blurb, _n in prompt_sets.SECTIONS:
        rs = sorted(rows_by.get(key) or [], key=lambda x: x[0])
        if not rs:
            continue
        body += (f'<h3 class="grp">{esc(title)} <span class="hk-muted">({len(rs)})</span></h3><div class="table-wrap"><table class="table pa"><thead><tr><th style="width:30%">Prompt</th><th>Named?</th>'
                 f'<th>Named instead</th><th>Why them</th><th style="width:30%">What to do</th></tr></thead><tbody>{"".join(r for _t, r in rs)}</tbody></table></div>')
    foot = ('<p class="caption">' + ("Claude with live web search answers every prompt; your tracked prompts are also put to the other assistants shown under &ldquo;Named?&rdquo;. " if by_engine else "One assistant (Claude with live web search). ")
            + 'A few answers per prompt, one day: a sample, not a ranking. &ldquo;Why them&rdquo; is the reason the assistant gave; '
            '&ldquo;What to do&rdquo; follows from a difference in the evidence, not a proven cause. These findings are also in your '
            '<button type="button" class="link" data-goto="actions">Actions</button>, where you can mark them done.</p>')
    return head + body + foot
