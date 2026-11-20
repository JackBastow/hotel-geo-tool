"""
The Competitors tab of a hotel's dashboard: who AI recommends instead of the hotel and how often, the competitors the hotel chose in its profile (named or not), why rivals are recommended, how their
own websites compare, and the sites AI relies on (where rivals are featured and the hotel is not). All from the hotel's latest check; a sample from one assistant, never a ranking.
"""

import html

import evidence
import hotel_profile
import strategy_view

esc = html.escape


def _same(a, b):
    fa, fb = evidence.fold(a), evidence.fold(b)
    return bool(fa and fb) and (fa in fb or fb in fa)


def leaderboard(rep):
    """[{name, prompts, answers, of, relation, tier, reasons}] across every prompt: comparable hotels only, most prompts first."""
    by = {}
    for m in ((rep or {}).get("ai_gap") or {}).get("markets") or []:
        for r in m.get("rivals") or []:
            d = by.setdefault(r["name"], {"name": r["name"], "prompts": 0, "answers": 0, "of": 0, "relation": r.get("relation"), "tier": (r.get("tier") or {}).get("label", ""), "reasons": []})
            d["prompts"] += 1
            d["answers"] += r.get("answers") or 0
            d["of"] += r.get("of") or 0
            for x in r.get("reasons") or []:
                if x not in d["reasons"]:
                    d["reasons"].append(x)
    return sorted(by.values(), key=lambda d: (-d["prompts"], -d["answers"], d["name"]))


def panel(rep, hotel=None):
    if not rep:
        return '<div class="alert info">The competitor view appears after the first check.</div>'
    gap = rep.get("ai_gap") or {}
    prof = hotel_profile.confirmed(hotel or {}) if hotel else None
    chosen = (prof or {}).get("competitors") or []
    n_prompts = len([m for m in gap.get("markets") or [] if m.get("kind") != "direct"])
    board = leaderboard(rep)
    out = ['<p class="lede">The hotels AI recommends instead of you, why, and the sites it reads about them. From the latest check: one assistant, a few answers per prompt.</p>']
    # 1 who AI recommends instead
    out.append('<h3 class="grp" style="margin-top:6px">Who AI recommends instead of you</h3>')
    if board:
        rows = "".join(
            f'<tr><td><b>{esc(d["name"])}</b>' + (' <span class="hk-chip brand">your competitor</span>' if any(_same(d["name"], c) for c in chosen) else "") + f'<br><span class="hk-muted">{esc(d["tier"] or "category not known")}</span></td>'
            f'<td>{d["prompts"]} of {n_prompts}</td><td>{d["answers"]}</td><td>{esc(d["reasons"][0][:140] if d["reasons"] else "-")}</td></tr>'
            for d in board[:12])
        out.append('<div class="table-wrap"><table class="table"><thead><tr><th>Hotel</th><th>Prompts it was named in</th><th>Answers</th><th>The assistant&rsquo;s main reason</th></tr></thead><tbody>' + rows + "</tbody></table></div>"
                   '<p class="caption">Comparable hotels only (the same price category, one step either way, or not known). Hotels in a different category are left out: they are not competing for the same guests.</p>')
    else:
        out.append('<p class="caption">No comparable hotel was named instead of you in this check.</p>')
    # 2 the competitors the hotel chose
    if chosen:
        items = []
        for c in chosen:
            hit = next((d for d in board if _same(d["name"], c)), None)
            items.append(f'<tr><td><b>{esc(c)}</b></td><td>' + (f'Named instead of you in <b>{hit["prompts"]} of {n_prompts}</b> prompts' if hit else '<span class="hk-muted">Not named in this check: for the prompts asked, AI does not treat it as an alternative to you</span>') + "</td></tr>")
        others = [d["name"] for d in board[:5] if not any(_same(d["name"], c) for c in chosen)]
        out.append('<h3 class="grp">Your chosen competitors</h3><p class="caption">From your hotel profile (Settings).</p><div class="table-wrap"><table class="table"><tbody>' + "".join(items) + "</tbody></table></div>"
                   + (f'<p class="caption">Named more often but not on your list: {esc(", ".join(others))}. Worth a look: AI treats them as your alternatives.</p>' if others else ""))
    else:
        out.append('<p class="caption">Add the hotels you compete with to your profile (Settings) and this tab shows how often AI names each of them instead of you.</p>')
    # 3 why
    out.append(strategy_view.rivals_html(rep))
    # 4 their sites vs yours
    comp = gap.get("comparison") or {}
    if comp.get("rows") and comp.get("rivals"):
        names = [r["name"] for r in comp["rivals"]][:4]
        word = {"strong": "in detail", "some": "mentioned"}
        rows = "".join(f'<tr><td>{esc(r["facility"])}</td><td>{esc(word.get(r["hotel"], "not mentioned"))}</td>' + "".join(f'<td>{esc(word.get(r["rivals"].get(n), "not mentioned"))}</td>' for n in names) + "</tr>" for r in comp["rows"])
        out.append('<h3 class="grp">What their websites say, beside yours</h3><div class="table-wrap"><table class="table"><thead><tr><th>Facility</th><th>You</th>'
                   + "".join(f"<th>{esc(n)}</th>" for n in names) + f"</tr></thead><tbody>{rows}</tbody></table></div>"
                   '<p class="caption">Read from the pages of each site. &ldquo;Not mentioned&rdquo; means not found on the pages read, which is not proof the hotel lacks it.</p>')
    # 5 key sources
    out.append(strategy_view.sources_html(rep))
    arts = [a for a in gap.get("articles") or [] if a.get("opportunity")]
    if arts:
        rows = "".join(f'<li><a href="{esc(a["url"], quote=True)}" target="_blank" rel="noopener">{esc(a.get("title") or a["domain"])}</a> <span class="hk-muted">{esc(a["domain"])}: lists {esc(", ".join(a.get("rivals_in") or [])[:120])}, not you</span></li>'
                       for a in arts[:10] if str(a.get("url", "")).startswith(("http://", "https://")))
        if rows:
            out.append('<h3 class="grp">Articles the assistant read that list rivals but not you</h3><ul class="wl">' + rows + "</ul>")
    return "".join(out)
