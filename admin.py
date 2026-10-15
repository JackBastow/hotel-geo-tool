"""
The operator's pages at /admin: every saved audit, how each hotel is doing over time, the market view across hotels, usage, and exports (including the monthly Excel pack).

Protected by the ADMIN_PASSWORD environment variable (a signed session cookie after a correct password; wrong guesses are slowed and limited) and by a CSRF token on the one
action that changes anything (deleting a run). Not linked from the public pages. If the password or the database is not set, the page says so and shows nothing.
"""

import collections
import hmac
import io
import json
import secrets
import time
import zipfile

from flask import Response, abort, redirect, render_template, request, session, url_for

import backend
import htmlst
import ui_theme
from htmlst import st

NAV = [("overview", "Overview"), ("runs", "Runs"), ("hotels", "Hotels"), ("markets", "Markets"), ("usage", "Usage"), ("export", "Export")]
PUB_COLS = ["id", "run_at", "hotel", "city", "headline_status", "headline_score", "coverage_pct", "ai_generic_named", "ai_generic_asked", "ai_niche_named", "ai_niche_asked",
            "ai_share", "ai_coverage_pct", "ai_sentiment", "ai_rank_in_table", "ai_top_competitor", "reviews_replied", "reviews_examined", "pack_reviews", "pack_reply_rate", "pagespeed_perf",
            "recs_total", "ai_cost_usd"]
NICE = {"run_at": "Run", "hotel": "Hotel", "city": "City", "headline_status": "Headline", "headline_score": "Readiness", "coverage_pct": "Readiness coverage %", "ai_generic_named": "Named (town)",
        "ai_generic_asked": "of", "ai_niche_named": "Named (niche)", "ai_niche_asked": "of ", "ai_share": "Share of names %", "ai_coverage_pct": "Coverage %", "ai_sentiment": "Net sentiment",
        "ai_rank_in_table": "Place in table", "ai_top_competitor": "Top competitor", "reviews_replied": "Replies seen", "reviews_examined": "Reviews examined", "pack_reviews": "Reviews in export",
        "pack_reply_rate": "Export reply rate %", "pagespeed_perf": "Mobile speed", "recs_total": "Recommendations", "ai_cost_usd": "AI cost $", "id": "Run id"}
_failed = collections.defaultdict(list)


def _table(rows, cols=None, rename=NICE):
    """An HTML table of dict rows (empty -> 'Nothing to show yet'). Cells are escaped."""
    def body():
        if not rows:
            st.caption("Nothing to show yet.")
            return
        use = cols or list(rows[0])
        st.dataframe([{rename.get(c, c): ("" if r.get(c) is None else r[c]) for c in use} for r in rows])
    return htmlst.build(body)


def _page(title, fn):
    return htmlst.build(lambda: (st.title(title), fn()))


def register(app, cfg):
    def password():
        return cfg.admin_password

    def authed():
        return bool(password()) and session.get("admin_ok") is True

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    def shell(active, title, content):
        return render_template("admin.html", nav=NAV, active=active, title=title, content=content, csrf=csrf())

    def store_or_msg():
        if not cfg.database_url:
            return None, "No database is connected (no DATABASE_URL), so no runs are being saved. See the README for the 5-minute setup."
        try:
            return backend.open_store(cfg.database_url), ""
        except Exception as e:  # noqa: BLE001 - show the real reason to the operator
            return None, f"The database could not be reached: {type(e).__name__}: {str(e)[:300]}"

    def guard():
        if not password():
            return render_template("admin_login.html", off=True, error="", csrf=""), 403
        if not authed():
            return redirect(url_for("admin_login"))
        return None

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if not password():
            return render_template("admin_login.html", off=True, error="", csrf=""), 403
        error = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            now = time.time()
            _failed[ip] = [t for t in _failed[ip] if now - t < 600]
            if len(_failed[ip]) >= 5:
                error = "Too many wrong passwords. Try again in ten minutes."
            elif hmac.compare_digest((request.form.get("password") or "").encode(), str(password()).encode()):
                session.clear()
                session["admin_ok"] = True
                session.permanent = True
                app.permanent_session_lifetime = 8 * 3600
                return redirect(url_for("admin_overview"))
            else:
                _failed[ip].append(now)
                time.sleep(1.5)
                error = "Wrong password."
        return render_template("admin_login.html", off=False, error=error, csrf="")

    @app.post("/admin/logout")
    def admin_logout():
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @app.get("/admin/overview")
    def admin_overview():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("overview", "Admin", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        runs = s.list_runs(limit=2000)
        month = time.strftime("%Y-%m")
        this = [r for r in runs if str(r["run_at"]).startswith(month)]

        def body():
            a, b, c, d = st.columns(4)
            a.metric("Audits saved", len(runs))
            b.metric("Hotels", len({r["hotel_key"] for r in runs}))
            c.metric("Audits this month", len(this))
            d.metric("AI cost this month (est.)", f"${sum((r['ai_cost_usd'] or 0) for r in this):.2f}")
            st.markdown("##### Latest audits")
        return shell("overview", "Admin: saved audits", _page_body(body) + _table(runs[:15], PUB_COLS[1:]))

    def _page_body(fn):
        return htmlst.build(fn)

    @app.get("/admin/runs")
    def admin_runs():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("runs", "Runs", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        text, city, since = (request.args.get(k, "").strip() for k in ("q", "city", "since"))
        rows = s.list_runs(limit=500, text=text or None, city=city or None, since=since or None)
        opts = "".join(f'<option value="{htmlst.html.escape(c, quote=True)}"{" selected" if c == city else ""}>{htmlst.html.escape(c)}</option>' for c in [""] + s.cities())
        form = (f'<form class="filters" method="get"><label class="field"><span>Hotel or website contains</span><input type="search" name="q" value="{htmlst.html.escape(text, quote=True)}"></label>'
                f'<label class="field"><span>City</span><select name="city">{opts}</select></label><label class="field"><span>Since (YYYY-MM-DD)</span>'
                f'<input type="text" name="since" value="{htmlst.html.escape(since, quote=True)}"></label><button class="btn primary" type="submit">Filter</button></form>')
        links = "".join(f'<tr><td><a href="/admin/run/{r["id"]}">#{r["id"]}</a></td><td>{htmlst.html.escape(str(r["run_at"])[:10])}</td><td>{htmlst.html.escape(r["hotel"] or r["hotel_key"])}</td></tr>' for r in rows[:60])
        return shell("runs", "Runs", form + f'<p class="caption">{len(rows)} run(s)</p>' + _table(rows, PUB_COLS)
                     + '<h5>Open a run</h5><div class="table-wrap"><table class="table"><thead><tr><th>Run</th><th>Date</th><th>Hotel</th></tr></thead><tbody>' + links + '</tbody></table></div>')

    @app.get("/admin/run/<int:run_id>")
    def admin_run(run_id):
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("runs", "Run", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        rep = s.get_report(run_id)
        if not rep:
            abort(404)
        meta, h = rep.get("meta") or {}, rep.get("headline") or {}
        cons = rep.get("consultant") or {}
        tops = [r for r in cons.get("recommendations", []) if r["id"] in (cons.get("top_actions") or [])]

        def body():
            st.markdown(f"**{ui_theme_safe(meta.get('hotel', ''))}** · {ui_theme_safe(meta.get('website', ''))}")
            st.write(f"Headline: {h.get('status', '-')} {'' if h.get('score') is None else str(h['score']) + '/100'} (coverage {h.get('coverage_pct', '-')}%)")
            for r in tops:
                st.markdown(f"- **{ui_theme_safe(r['title'])}** ({r['priority']}, {ui_theme_safe(r['team'])})")
        links = (f'<p><a class="btn" href="/admin/run/{run_id}/report">Open the full report</a> <a class="btn" href="/admin/run/{run_id}/data.json">Report data (.json)</a> '
                 f'<a class="btn" href="/admin/run/{run_id}/management.pdf">Management report (PDF)</a> <a class="btn" href="/admin/run/{run_id}/appendix.pdf">Technical appendix (PDF)</a></p>')
        delete = (f'<details class="details"><summary>Delete this run</summary><div class="details-body"><p class="caption">Removes the run and its market rows permanently.</p>'
                  f'<form method="post" action="/admin/run/{run_id}/delete"><input type="hidden" name="csrf" value="{csrf()}"><label><input type="checkbox" name="confirm" value="yes"> Yes, delete run #{run_id}</label> '
                  f'<button class="btn" type="submit">Delete</button></form></div></details>')
        return shell("runs", f"Run #{run_id}", htmlst.build(body) + links + delete)

    def ui_theme_safe(x):
        from ui_intel import md_safe
        return md_safe(x)

    @app.get("/admin/run/<int:run_id>/report")
    def admin_run_report(run_id):
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        rep = s.get_report(run_id) if s else None
        if not rep:
            abort(404)
        import report_view
        return shell("runs", f"Run #{run_id}: the report", report_view.render(rep, token=None))

    @app.get("/admin/run/<int:run_id>/<part>.<ext>")
    def admin_run_file(run_id, part, ext):
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        rep = s.get_report(run_id) if s else None
        if not rep:
            abort(404)
        if part == "data" and ext == "json":
            return Response(json.dumps(rep, indent=1, default=str), mimetype="application/json", headers={"Content-Disposition": f'attachment; filename="run-{run_id}.json"'})
        if part in ("management", "appendix") and ext == "pdf":
            import report_pdf
            return Response(report_pdf.build_pdf(rep, part), mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="run-{run_id}-{part}.pdf"'})
        abort(404)

    @app.post("/admin/run/<int:run_id>/delete")
    def admin_delete(run_id):
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")) or request.form.get("confirm") != "yes":
            abort(400)
        s, _m = store_or_msg()
        if s:
            s.delete_run(run_id)
        return redirect(url_for("admin_runs"))

    @app.get("/admin/hotels")
    def admin_hotels():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("hotels", "Hotels", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        hs = s.hotels()
        key = request.args.get("key", "")
        cols = ["hotel", "city", "runs", "last_run", "headline_score", "d_score", "ai_named", "ai_asked", "niche_named", "niche_asked", "ai_share", "d_share"]
        names = {"hotel": "Hotel", "city": "City", "runs": "Runs", "last_run": "Last run", "headline_score": "Readiness", "d_score": "Change", "ai_named": "Named (town)", "ai_asked": "of",
                 "niche_named": "Named (niche)", "niche_asked": "of ", "ai_share": "Share of names %", "d_share": "Share change"}
        out = '<p class="caption">One row per hotel (the same website, or the same hotel folder on a chain\'s site). Changes compare the latest run with the one before.</p>' + _table(hs, cols, names)
        picks = "".join(f'<option value="{htmlst.html.escape(h["hotel_key"], quote=True)}"{" selected" if h["hotel_key"] == key else ""}>{htmlst.html.escape((h["hotel"] or h["hotel_key"]) + (" (" + h["city"] + ")" if h["city"] else ""))}</option>' for h in hs)
        out += f'<form class="filters" method="get"><label class="field"><span>Hotel history</span><select name="key" onchange="this.form.submit()">{picks}</select></label></form>' if hs else ""
        key = key or (hs[0]["hotel_key"] if hs else "")
        if key:
            hist = s.history(key)

            def charts():
                import pandas as pd
                if len(hist) >= 2:
                    idx = [str(r["run_at"])[:10] for r in hist]
                    ui_theme.lines_chart(pd.DataFrame({"Readiness": [r["headline_score"] for r in hist], "Share of names %": [r["ai_share"] for r in hist]}, index=idx))
                    ui_theme.lines_chart(pd.DataFrame({"Named, town-wide %": [100 * r["ai_generic_named"] / r["ai_generic_asked"] if r["ai_generic_asked"] else None for r in hist],
                                                       "Named, niche markets %": [100 * r["ai_niche_named"] / r["ai_niche_asked"] if r["ai_niche_asked"] else None for r in hist]}, index=idx))
                else:
                    st.caption("A trend needs two or more runs of the same hotel.")
                ch = s.competitor_history(key)
                if len(ch["runs"]) >= 2 and ch["rows"]:
                    st.markdown("**Coverage over time: this hotel and the hotels the assistant names most alongside it**")
                    st.caption("The share of all answers that named each hotel, run by run. A rival not named in a run counts as 0% for that run. One model, one day per run: look for sustained moves.")
                    idx = [f"{str(r['run_at'])[:10]} #{r['run_id']}" for r in ch["runs"]]
                    ui_theme.lines_chart(pd.DataFrame({("→ " if r["is_target"] else "") + r["name"][:34]: [p["coverage_pct"] for p in r["points"]] for r in ch["rows"]}, index=idx))
                    sent = {r["name"][:34]: [p["sentiment"] for p in r["points"]] for r in ch["rows"] if any(p["sentiment"] is not None for p in r["points"])}
                    if sent:
                        st.markdown("**Net sentiment over time (-100 to +100, where named)**")
                        ui_theme.lines_chart(pd.DataFrame(sent, index=idx))
            out += htmlst.build(charts) + _table(list(reversed(hist)), PUB_COLS)
        return shell("hotels", "Hotels", out)

    @app.get("/admin/markets")
    def admin_markets():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("markets", "Markets", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        city = request.args.get("city", "")
        opts = "".join(f'<option value="{htmlst.html.escape(c, quote=True)}"{" selected" if c == city else ""}>{htmlst.html.escape(c or "(all cities)")}</option>' for c in [""] + s.cities())
        cc = ["competitor", "mentions", "runs", "avg_rank"]
        cn = {"competitor": "Hotel", "mentions": "Mentions", "runs": "Audits", "avg_rank": "Avg position"}
        out = (f'<form class="filters" method="get"><label class="field"><span>Market (city)</span><select name="city" onchange="this.form.submit()">{opts}</select></label></form>'
               '<p class="caption">Across every hotel audited: who the assistant names, and which sites it relies on. One model, one day each, so read patterns, not single numbers.</p>'
               '<div class="cols" style="grid-template-columns:1fr 1fr"><div class="col"><b>Hotels named most in town-wide answers</b>' + _table(s.competitors(city or None, "generic"), cc, cn)
               + '</div><div class="col"><b>Hotels named most in niche markets</b>' + _table(s.competitors(city or None, "niche"), cc, cn) + '</div></div>'
               + '<h5>Pages the assistant used most (exact pages)</h5>' + _table(s.pages(city or None), ["url", "domain", "cited", "questions", "runs", "names_hotel", "names_competitor"],
                                                                                {"url": "Page", "domain": "Site", "cited": "Times cited", "questions": "Question uses", "runs": "Audits", "names_hotel": "Audits where it names a hotel audited", "names_competitor": "A competitor it names"})
               + '<h5>Sites the assistant relies on</h5>' + _table(s.sources(city or None), ["domain", "kind", "answers", "runs", "hotel_found", "hotel_missing"],
                                                                   {"domain": "Site", "kind": "Type", "answers": "Used in answers", "runs": "Audits", "hotel_found": "Hotel found there", "hotel_missing": "Hotel not found there"}))
        return shell("markets", "Markets", out)

    @app.get("/admin/usage")
    def admin_usage():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("usage", "Usage", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        import store as quota
        lines = []
        for svc in ("tavily", "claude", "gemini_reader", "amadeus"):
            used, remaining, _w = quota.quota_status(service=svc)
            lines.append({"Service": svc, "Used this month": used, "Allowance": quota.SERVICE_CAPS.get(svc), "Left": remaining})
        out = ("<h5>By month</h5>" + _table(s.usage_by_month(), ["month", "runs", "hotels", "ai_cost_usd"], {"month": "Month", "runs": "Audits", "hotels": "Hotels", "ai_cost_usd": "Estimated AI cost $"})
               + '<p class="caption">Costs are the app\'s own estimates from reported token use and searches. The Anthropic Console is the source of truth for what was charged.</p>'
               + "<h5>Free-tier guards this month</h5>" + _table(lines) + '<p class="caption">Claude is counted in thousandths of a US dollar. These guards stop the service calling a key once its monthly allowance is used; the workspace spend limit in the Anthropic Console is the hard stop.</p>')
        return shell("usage", "Usage", out)

    @app.get("/admin/export")
    def admin_export():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("export", "Export", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        rows = s.export_rows()
        months = sorted({str(r["run_at"])[:7] for r in rows})
        links = ('<h5>Pull the data</h5><p>'
                 f'<a class="btn" href="/admin/export/runs.csv">All {len(rows)} runs, summary table (.csv)</a> <a class="btn" href="/admin/export/competitors.csv">Hotels named by the assistant (.csv)</a> '
                 '<a class="btn" href="/admin/export/pages.csv">Pages the assistant used (.csv)</a> <a class="btn" href="/admin/export/sources.csv">Sites the assistant relies on (.csv)</a></p>')
        if months:
            default = months[-2] if len(months) > 1 and months[-1] == time.strftime("%Y-%m") else months[-1]
            opt = lambda sel: "".join(f'<option value="{m}"{" selected" if m == sel else ""}>{m}</option>' for m in months)       # noqa: E731
            pack = ('<h5>Monthly pack (Excel)</h5><p class="caption">One workbook with every audit in the period: scores and why, AI rankings and competitors, the top 3 actions per hotel, and the change since each hotel\'s '
                    'previous run. Built for reading, and for feeding to a dashboard.</p><form class="filters" method="get" action="/admin/export/pack.xlsx"><label class="field"><span>From month</span>'
                    f'<select name="from">{opt(default)}</select></label><label class="field"><span>To month</span><select name="to">{opt(default)}</select></label><button class="btn primary" type="submit">Build and download the monthly pack</button></form>')
        else:
            pack = '<p class="caption">No audits saved yet.</p>'
        zipf = ('<h5>Full reports</h5><form class="filters" method="get" action="/admin/export/reports.zip"><label class="field"><span>How many of the latest runs</span>'
                f'<input type="text" name="n" value="{min(50, max(1, len(rows)))}"></label><button class="btn" type="submit">Download a zip of the full reports (.json)</button></form>')
        return shell("export", "Export", links + pack + zipf)

    @app.get("/admin/export/<name>")
    def admin_export_file(name):
        g = guard()
        if g:
            return g
        s, _m = store_or_msg()
        if s is None:
            abort(404)
        csvh = lambda text, fn: Response(text, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{fn}"'})       # noqa: E731
        if name == "runs.csv":
            return csvh(backend.to_csv(s.export_rows()), "hotel-audit-runs.csv")
        if name == "competitors.csv":
            return csvh(backend.to_csv(s.competitors(None, "generic", limit=100000) + s.competitors(None, "niche", limit=100000)), "hotel-audit-competitors.csv")
        if name == "pages.csv":
            return csvh(backend.to_csv(s.pages(None, limit=100000)), "hotel-audit-pages.csv")
        if name == "sources.csv":
            return csvh(backend.to_csv(s.sources(None, limit=100000)), "hotel-audit-sources.csv")
        if name == "pack.xlsx":
            import monthly_pack
            a, b = request.args.get("from", ""), request.args.get("to", "")
            if not a or not b or a > b:
                abort(400)
            in_range = s.runs_in_months(a, b)
            data = monthly_pack.build_workbook([(r, s.get_report(r["id"])) for r in in_range if s.get_report(r["id"])], s.list_runs(limit=100000))
            return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{monthly_pack.filename(a, b)}"'})
        if name == "reports.zip":
            try:
                n = max(1, min(500, int(request.args.get("n", "50"))))
            except ValueError:
                n = 50
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for r in s.export_rows()[:n]:
                    rep = s.get_report(r["id"])
                    if rep is not None:
                        z.writestr(f"{backend.hotel_key(rep).replace('/', '_')}__{str(r['run_at'])[:10]}__{r['id']}.json", json.dumps(rep, indent=1, default=str))
            return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="hotel-audit-reports.zip"'})
        abort(404)
