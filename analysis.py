"""
The admin Overview: an analysis of the whole portfolio, not a list of runs (the Runs tab has those).

  numbers      hotels, checks run (and in the last 30 days), actions completed, the average score now and how far it has moved, how many hotels are improving, flat or slipping
  by hotel     checks, score first -> latest and the change, actions completed / in progress / to do, AI visibility first -> latest
  charts       the five hotels with most actions completed, the five whose AI visibility grew most, the five whose score rose most, the five whose score fell most (who to call),
               checks per week, hotels by score band, actions across the portfolio, and the hotels that need attention (not checked lately, or the last check failed)

AI visibility here is how often the hotel was named in the AI answers of a check (named / answers asked). It moves with the prompts asked: while a hotel keeps its confirmed prompts the movement is
comparable; after the prompts change it starts a new baseline, which the Prompts tab warns about.
"""

import datetime as dt
import html

import portal_view
import progress
from charts import BAD, BRAND, GOOD, WARN, bars
from timeutil import uk_date

esc = html.escape


def _pct(c):
    return round(100 * c[0] / c[1]) if c and c[1] else None


def _parse(iso):
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def figures(db, runs_all=None, now=None):
    """-> everything the page shows, as plain data (so it can be tested): {"rows", "tiles", "weeks", "bands", "attention", "other_audits"}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    data = progress.portfolio_data(db)
    rows, tot = progress.portfolio_summary(db, data)
    for r in rows:
        r["cov0"], r["cov1"] = _pct(r["cov_first"]), _pct(r["cov_latest"])
        r["growth"] = (r["cov1"] - r["cov0"]) if (r["runs"] >= 2 and r["cov0"] is not None and r["cov1"] is not None) else None
        r["days_since"] = (now - _parse(r["last_run_at"])).days if r["last_run_at"] and _parse(r["last_run_at"]) else None
    checks = sum(r["runs"] for r in rows)
    recent = sum(1 for r in rows for p in data["hist"].get(r["hotel"]["hotel_key"], []) if _parse(p["run_at"]) and (now - _parse(p["run_at"])).days < 30)
    moved = [r["delta"] for r in rows if r["delta"] is not None]
    latest = [r["latest_score"] for r in rows if r["latest_score"] is not None]
    tiles = {"hotels": len(rows), "checks": checks, "recent": recent, "completed": tot["completed"], "verified": tot["verified"], "working": tot["working"], "todo": tot["todo"],
             "avg_now": round(sum(latest) / len(latest), 1) if latest else None, "avg_move": round(sum(moved) / len(moved), 1) if moved else None,
             "up": sum(1 for d in moved if d > 0), "down": sum(1 for d in moved if d < 0), "flat": sum(1 for d in moved if d == 0), "measured": len(moved)}
    weeks = {}
    for r in rows:
        for p in data["hist"].get(r["hotel"]["hotel_key"], []):
            d = _parse(p["run_at"])
            if d:
                wk = (d - dt.timedelta(days=d.weekday())).date().isoformat()
                weeks[wk] = weeks.get(wk, 0) + 1
    week_pts = [{"run_at": k + "T00:00:00+00:00", "score": v} for k, v in sorted(weeks.items())]
    bands = [("Under 50: needs work", sum(1 for s in latest if s < 50), BAD), ("50 to 64", sum(1 for s in latest if 50 <= s < 65), WARN), ("65 to 79", sum(1 for s in latest if 65 <= s < 80), BRAND), ("80 and over", sum(1 for s in latest if s >= 80), GOOD)]
    attention = []
    for r in rows:
        h = r["hotel"]
        if r["runs"] == 0:
            attention.append((r, "Never checked"))
        elif r["days_since"] is not None and r["days_since"] >= 14:
            attention.append((r, f"Not checked for {r['days_since']} days"))
        elif h.get("last_error"):
            attention.append((r, "The last check did not finish"))
        elif r["delta"] is not None and r["delta"] <= -5:
            attention.append((r, f"Score down {abs(r['delta']):g} points"))
    other = 0
    if runs_all is not None:
        mine = {r["hotel"]["hotel_key"] for r in rows}
        other = sum(1 for x in runs_all if x["hotel_key"] not in mine)
    return {"rows": rows, "tiles": tiles, "weeks": week_pts, "bands": bands, "attention": attention, "other_audits": other}


def _top(rows, key, n=5, descending=True, minimum=None, label_note=None, colour=None, suffix=""):
    pool = [r for r in rows if r.get(key) is not None and (minimum is None or r[key] >= minimum)] if descending else [r for r in rows if r.get(key) is not None and r[key] < 0]
    pool.sort(key=lambda r: -r[key] if descending else r[key])
    out = []
    for r in pool[:n]:
        v = r[key] if descending else abs(r[key])
        out.append({"label": r["hotel"]["name"], "value": v, "note": label_note(r) if label_note else None, "colour": colour or BRAND})
    return out, suffix


def _panel(title, rows, suffix="", empty="Nothing to show yet.", maximum=None, note=""):
    if not rows:
        return f'<section class="panel"><h4>{esc(title)}</h4><p class="caption">{esc(empty)}</p></section>'
    m = maximum or max(max(r["value"] for r in rows), 1)
    return f'<section class="panel"><h4>{esc(title)}</h4>{bars(rows, suffix=suffix, maximum=m)}' + (f'<p class="caption">{esc(note)}</p>' if note else "") + "</section>"


def page(db, runs_all, cost_this_month=None):
    f = figures(db, runs_all)
    t, rows = f["tiles"], f["rows"]
    if not rows:
        return '<div class="alert info">No hotels are registered yet. Add one under <a href="/admin/portfolio">Portfolio</a> and its analysis appears here.</div>'
    move = "" if t["avg_move"] is None else f"{t['avg_move']:+g} on average since the first check"
    tiles = ('<div class="kpis">'
             + portal_view.kpi("Hotels", t["hotels"], f"{t['up']} improving, {t['flat']} flat, {t['down']} slipping" if t["measured"] else "more checks are needed to show movement", BRAND)
             + portal_view.kpi("Checks run", t["checks"], f"{t['recent']} in the last 30 days", BRAND)
             + portal_view.kpi("Actions completed", t["completed"], f"{t['verified']} confirmed on the sites · {t['working']} in progress", GOOD)
             + portal_view.kpi("Average score now", "-" if t["avg_now"] is None else f"{t['avg_now']:g}", move or "across all hotels", GOOD if (t["avg_now"] or 0) >= 70 else WARN, "/100")
             + (portal_view.kpi("AI cost this month", f"${cost_this_month:.2f}", "estimated; the Usage tab has the detail", BRAND) if cost_this_month is not None else "") + "</div>")
    # by hotel
    def chg(v, unit=""):
        return "-" if v is None else f'<b style="color:{"#067647" if v > 0 else "#b42318" if v < 0 else "inherit"}">{v:+g}{unit}</b>'
    body = "".join(
        f'<tr><td><a href="/admin/hotel/{r["hotel"]["id"]}">{esc(r["hotel"]["name"])}</a><br><span class="hk-muted">{esc(r["hotel"]["city"] or "")}</span></td><td>{r["runs"]}</td>'
        f'<td>{"-" if r["first_score"] is None else format(r["first_score"], "g")} &rarr; {"-" if r["latest_score"] is None else format(r["latest_score"], "g")}</td><td>{chg(r["delta"])}</td>'
        f'<td>{r["actions"]["completed"]}</td><td>{r["actions"]["working"]}</td><td>{r["actions"]["todo"] + r["actions"]["still_flagged"]}</td>'
        f'<td>{"-" if r["cov0"] is None else str(r["cov0"]) + "%"} &rarr; {"-" if r["cov1"] is None else str(r["cov1"]) + "%"}</td><td>{chg(r["growth"], " pts")}</td></tr>'
        for r in sorted(rows, key=lambda r: -(r["delta"] if r["delta"] is not None else -999)))
    table = ('<div class="table-wrap"><table class="table"><thead><tr><th>Hotel</th><th>Checks</th><th>Score: first &rarr; latest</th><th>Movement</th><th>Actions done</th><th>In progress</th><th>To do</th>'
             '<th>AI visibility: first &rarr; latest</th><th>Movement</th></tr></thead><tbody>' + body + "</tbody></table></div>")
    # charts
    actions_rows = [{"label": r["hotel"]["name"], "value": r["actions"]["completed"], "colour": GOOD, "note": f"{r['actions']['verified']} confirmed on the site"} for r in sorted(rows, key=lambda r: -r["actions"]["completed"])[:5] if r["actions"]["completed"]]
    growth_rows, _ = _top(rows, "growth", minimum=0.5, label_note=lambda r: f"{r['cov0']}% to {r['cov1']}%", colour=BRAND, suffix=" pts")
    gain_rows, _ = _top(rows, "delta", minimum=0.5, label_note=lambda r: f"{r['first_score']:g} to {r['latest_score']:g}", colour=GOOD, suffix=" pts")
    drop_rows, _ = _top(rows, "delta", descending=False, label_note=lambda r: f"{r['first_score']:g} to {r['latest_score']:g}", colour=BAD, suffix=" pts")
    charts = ('<div class="ov-grid even">' + _panel("Most actions completed (top 5)", actions_rows, empty="No action has been completed yet.")
              + _panel("Biggest growth in AI visibility (top 5)", growth_rows, " pts", "No hotel's AI visibility has grown yet, or only one check each so far.", note="Points of coverage gained: how much more often the hotel is named in the AI answers than at its first check.") + "</div>"
              '<div class="ov-grid even">' + _panel("Biggest readiness score gains (top 5)", gain_rows, " pts", "No hotel's score has risen yet.")
              + _panel("Biggest score drops: who to call", drop_rows, " pts", "No hotel's score has fallen.") + "</div>")
    weeks = ('<div class="ov-grid even"><section class="panel"><h4>Checks run per week</h4>' + (portal_view.trend_svg(f["weeks"], maximum=max(4, max(p["score"] for p in f["weeks"])), name="Checks per week") if f["weeks"] else '<p class="caption">No checks yet.</p>') + "</section>"
             + _panel("Hotels by readiness score", [{"label": n, "value": v, "colour": c} for n, v, c in f["bands"]], empty="No scores yet.", maximum=max(t["hotels"], 1)) + "</div>")
    status = _panel("Actions across the portfolio", [{"label": "Completed", "value": t["completed"], "colour": GOOD}, {"label": "In progress", "value": t["working"], "colour": BRAND}, {"label": "To do", "value": t["todo"], "colour": WARN}],
                    maximum=max(t["completed"] + t["working"] + t["todo"], 1))
    att = ""
    if f["attention"]:
        att = ('<section class="panel"><h4>Hotels that need attention</h4><ul class="wl">' + "".join(f'<li><a href="/admin/hotel/{r["hotel"]["id"]}">{esc(r["hotel"]["name"])}</a> <span class="hk-muted">{esc(why)}'
                                                                                                    + (f', last check {esc(uk_date(r["last_run_at"]))}' if r["last_run_at"] else "") + "</span></li>" for r, why in f["attention"]) + "</ul></section>")
    other = f'<p class="caption">{f["other_audits"]} other audit(s) are of websites that are not registered as hotels; they are in the Runs tab.</p>' if f["other_audits"] else ""
    return (tiles + '<div class="sec-head"><h3>Hotel by hotel</h3></div>' + table + '<p class="caption">AI visibility is how often the hotel was named in the AI answers of a check. It is comparable while a hotel keeps the same confirmed prompts. Times are UK time.</p>'
            + '<div class="sec-head"><h3>Who is moving</h3></div>' + charts + '<div class="sec-head"><h3>Activity and spread</h3></div>' + weeks + '<div class="ov-grid even">' + status + (att or '<section class="panel"><h4>Hotels that need attention</h4><p class="caption">None: every hotel was checked in the last 14 days.</p></section>') + "</div>" + other)
