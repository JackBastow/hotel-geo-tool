"""
The operator's pages at /admin: every saved audit, how each hotel is doing over time, the market view across hotels, usage, and exports (including the monthly Excel pack).

Protected by the ADMIN_PASSWORD environment variable (a signed session cookie after a correct password; wrong guesses are slowed and limited) and by a CSRF token on the one
action that changes anything (deleting a run). Not linked from the public pages. If the password or the database is not set, the page says so and shows nothing.
"""

import collections
import hmac
import io
import json
import re
import secrets
import time
import urllib.parse
import zipfile

from flask import Response, abort, redirect, render_template, request, session, url_for

import backend
import htmlst
import ui_theme
from timeutil import uk_time
from htmlst import st

ADMIN_HOURS = 8
NAV = [("overview", "Overview"), ("portfolio", "Portfolio"), ("audit", "Quick audit"), ("runs", "Runs"), ("hotels", "Hotels"), ("markets", "Markets"), ("usage", "Usage"), ("speed", "Speed"), ("feedback", "Feedback"), ("export", "Export")]
PUB_COLS = ["id", "run_at", "hotel", "city", "ai_depth", "headline_status", "headline_score", "coverage_pct", "ai_generic_named", "ai_generic_asked", "ai_niche_named", "ai_niche_asked",
            "ai_share", "ai_coverage_pct", "ai_sentiment", "ai_rank_in_table", "ai_top_competitor", "reviews_replied", "reviews_examined", "pack_reviews", "pack_reply_rate", "pagespeed_perf",
            "recs_total", "ai_cost_usd"]
NICE = {"run_at": "Run", "hotel": "Hotel", "city": "City", "ai_depth": "AI test", "headline_status": "Headline", "headline_score": "Readiness", "coverage_pct": "Readiness coverage %", "ai_generic_named": "Named (town)",
        "ai_generic_asked": "of", "ai_niche_named": "Named (niche)", "ai_niche_asked": "of ", "ai_share": "Share of names %", "ai_coverage_pct": "Coverage %", "ai_sentiment": "Net sentiment",
        "ai_rank_in_table": "Place in table", "ai_top_competitor": "Top competitor", "reviews_replied": "Replies seen", "reviews_examined": "Reviews examined", "pack_reviews": "Reviews in export",
        "pack_reply_rate": "Export reply rate %", "pagespeed_perf": "Mobile speed", "recs_total": "Recommendations", "ai_cost_usd": "AI cost $", "id": "Run id"}
_failed = collections.defaultdict(list)
TIME_COLS = ("run_at", "created")



def _table(rows, cols=None, rename=NICE):
    """An HTML table of dict rows (empty -> 'Nothing to show yet'). Cells are escaped."""
    def body():
        if not rows:
            st.caption("Nothing to show yet.")
            return
        use = cols or list(rows[0])
        st.dataframe([{rename.get(c, c) + (" (UK time)" if c in TIME_COLS else ""): (uk_time(r.get(c)) if c in TIME_COLS else ("" if r.get(c) is None else r[c])) for c in use} for r in rows])
    return htmlst.build(body)


def _page(title, fn):
    return htmlst.build(lambda: (st.title(title), fn()))


def register(app, cfg):
    def password():
        return cfg.admin_password

    def authed():
        return bool(password()) and session.get("admin_ok") is True and (session.get("admin_until") or 0) > time.time()

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
                keep = {k: session[k] for k in ("site_ok", "ind_ok", "ind_until", "csrf") if session.get(k)}      # signing in to the admin pages must not sign you out of the site: with a site password set that sent you straight back to its sign-in
                session.clear()
                session.update(keep)
                session["admin_ok"] = True
                session["admin_until"] = time.time() + ADMIN_HOURS * 3600       # the admin sign-in lasts a working day; hotel users' sign-ins keep their own 30 days
                session.permanent = True
                return redirect(url_for("admin_overview"))
            else:
                _failed[ip].append(now)
                time.sleep(1.5)
                error = "Wrong password."
        return render_template("admin_login.html", off=False, error=error, csrf="")

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("admin_ok", None)                 # leaves the site sign-in alone, and the form token other open pages (the hotels admin, a hotel login) still use
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
        cost = sum((r["ai_cost_usd"] or 0) for r in runs if str(r["run_at"]).startswith(month))
        import analysis
        return shell("overview", "Overview: how the portfolio is moving", analysis.page(s, runs, cost))

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
        links = "".join(f'<tr><td><a href="/admin/run/{r["id"]}">#{r["id"]}</a></td><td>{htmlst.html.escape(uk_time(r["run_at"]))}</td><td>{htmlst.html.escape(r["hotel"] or r["hotel_key"])}</td></tr>' for r in rows[:60])
        return shell("runs", "Runs", form + f'<p class="caption">{len(rows)} run(s)</p>' + _table(rows, PUB_COLS)
                     + '<h5>Open a run</h5><div class="table-wrap"><table class="table"><thead><tr><th>Run</th><th>Date and time (UK time)</th><th>Hotel</th></tr></thead><tbody>' + links + '</tbody></table></div>')

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
            st.write("Run: " + uk_time(meta.get("run_at")) + " (UK time)")
            st.write(f"Headline: {h.get('status', '-')} {'' if h.get('score') is None else str(h['score']) + '/100'} (coverage {h.get('coverage_pct', '-')}%)")
            for r in tops:
                st.markdown(f"- **{ui_theme_safe(r['title'])}** ({r['priority']}, {ui_theme_safe(r['team'])})")
            import run_health
            probs = run_health.issues(rep)
            if probs:
                st.markdown("**What did not work in this check** (only you see this)")
                for x in probs:
                    st.markdown(f"- {'**' if x['level'] == 'big' else ''}{ui_theme_safe(x['what'])}{'**' if x['level'] == 'big' else ''}: {ui_theme_safe(x['detail'])}")
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
        if part == "profile-audit" and ext == "json":
            # does every part of this report agree with its verified fact profile? (operator only; used by the 10-hotel regression)
            import profile_audit
            import run_health
            fp = rep.get("fact_profile") or {}
            body = {"run": run_id, "hotel": (rep.get("meta") or {}).get("hotel"), "audit": profile_audit.audit(rep), "health": run_health.issues(rep),
                    "profile": {k: {"status": v.get("status"), "relations": [r.get("status") for r in v.get("relations") or []]} for k, v in (fp.get("facilities") or {}).items()},
                    "reading": {k: fp.get(k) for k in ("pages_sent", "pages_truncated", "pages_left_out", "pages_failed", "kept", "rejected", "cost_usd")},
                    "pages": {"ok": (rep.get("guest_questions") or {}).get("pages_ok"), "attempted": (rep.get("guest_questions") or {}).get("pages_attempted")},
                    "follow_up": fp.get("follow_up"), "discovery": (rep.get("guest_questions") or {}).get("discovery"),
                    "ledger": {st: sum(1 for x in (rep.get("guest_questions") or {}).get("page_ledger") or [] if x.get("status") == st) for st in ("read", "failed", "not read")},
                    "guest_states": {q.get("id"): q.get("state") for q in (rep.get("guest_questions") or {}).get("questions") or []},
                    "cost_usd": __import__("costs").report_usd(rep)}
            return Response(json.dumps(body, indent=1, default=str), mimetype="application/json")
        if part in ("management", "appendix") and ext == "pdf":
            import report_pdf
            return Response(report_pdf.build_pdf(rep, part), mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="run-{run_id}-{part}.pdf"'})
        abort(404)

    # ----------------------------------------------------------------- hotel identity: find and repair checks that counted the hotel under the wrong name
    def _identity_row(run, s):
        import identity_fix
        rep = s.get_report(run["id"])
        if not rep:
            return {"run_id": run["id"], "status": "unreadable"}
        _new, d = identity_fix.reprocess(rep)
        out = {"run_id": run["id"], "hotel": run["hotel"], "city": run["city"], "run_at": str(run["run_at"])[:16], "status": d.get("status"), "affected": bool(d.get("affected"))}
        if d.get("status") == "ok":
            out.update(typed=d["typed"], canonical=d["canonical"], name_changed=d["name_changed"], before=d["before"], after=d["after"], own_spellings_among_rivals=d["own_spellings_among_rivals"],
                       merged_rivals=d["merged_rivals"], related=[r["name"] + " (" + r["why"] + ")" for r in d["related"]][:8], withdrawn=len(d["withdrawn"]))
        return out

    @app.get("/admin/identity/scan.json")
    def admin_identity_scan():
        """Read-only: for saved checks, would recalculating the AI visibility under the hotel's real identity change anything? scope=latest (each hotel's newest check) or all; offset/limit page through."""
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        scope = request.args.get("scope") or "latest"
        offset = max(0, int(request.args.get("offset") or 0))
        limit = min(25, max(1, int(request.args.get("limit") or 12)))
        runs = [r for r in s.list_runs(limit=5000) if r.get("ai_status") == "ok"]
        if scope == "latest":
            seen, latest = set(), []
            for r in runs:
                if r["hotel_key"] not in seen:
                    seen.add(r["hotel_key"])
                    latest.append(r)
            runs = latest
        page = runs[offset: offset + limit]
        rows = []
        for r in page:
            try:
                rows.append(_identity_row(r, s))
            except Exception as e:  # noqa: BLE001 - one unreadable report must not stop the scan
                rows.append({"run_id": r["id"], "hotel": r["hotel"], "status": f"error: {type(e).__name__}: {str(e)[:120]}"})
        return Response(json.dumps({"scope": scope, "total": len(runs), "offset": offset, "next": offset + limit if offset + limit < len(runs) else None, "rows": rows,
                                    "affected": [x["run_id"] for x in rows if x.get("affected")]}, indent=1, default=str), mimetype="application/json")

    @app.post("/admin/identity/apply")
    def admin_identity_apply():
        """Recalculate the AI visibility of the named saved checks under the hotel's real identity, and save them (their run ids and dates stay). No assistant is asked."""
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        import identity_fix
        done = []
        for rid in [int(x) for x in re.findall(r"\d+", request.form.get("run_ids") or "")][:25]:
            rep = s.get_report(rid)
            if not rep:
                continue
            new, d = identity_fix.reprocess(rep)
            if new is None or not d.get("affected"):
                done.append({"run_id": rid, "result": "unchanged" if new is not None else d.get("status")})
                continue
            s.update_run(rid, new)
            try:
                import backend
                s.save_identity(backend.hotel_key(new), new.get("identity"))
            except Exception:  # noqa: BLE001
                pass
            done.append({"run_id": rid, "result": "recalculated", "before": d["before"], "after": d["after"], "canonical": d["canonical"], "withdrawn": len(d["withdrawn"])})
        return Response(json.dumps({"done": done}, indent=1, default=str), mimetype="application/json")

    @app.get("/admin/release/scan.json")
    def admin_release_scan():
        """Read-only: the release state (ready / review / blocked) every saved check would get, and why. scope=latest or all; offset/limit page through (max 25)."""
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        import report_release
        runs = s.list_runs(limit=5000)
        if (request.args.get("scope") or "latest") == "latest":
            seen, latest = set(), []
            for r in runs:
                if r["hotel_key"] not in seen:
                    seen.add(r["hotel_key"])
                    latest.append(r)
            runs = latest
        offset = max(0, int(request.args.get("offset") or 0))
        limit = min(25, max(1, int(request.args.get("limit") or 12)))
        rows = []
        for r in runs[offset: offset + limit]:
            try:
                rep = s.get_report(r["id"])
                rel = report_release.assess(dict(rep), legacy=True)["release"] if rep else {"state": "unreadable", "reasons": []}
                rows.append({"run_id": r["id"], "hotel": r["hotel"], "run_at": str(r["run_at"])[:16], "stored": (r.get("release_state") or None), "state": rel["state"],
                             "reasons": [f"{x['level']}: {x['what']}" for x in rel["reasons"]]})
            except Exception as e:  # noqa: BLE001
                rows.append({"run_id": r["id"], "hotel": r["hotel"], "state": f"error: {type(e).__name__}: {str(e)[:100]}"})
        counts = {}
        for x in rows:
            counts[x["state"]] = counts.get(x["state"], 0) + 1
        return Response(json.dumps({"total": len(runs), "offset": offset, "next": offset + limit if offset + limit < len(runs) else None, "counts": counts, "rows": rows}, indent=1, default=str),
                        mimetype="application/json")

    @app.get("/admin/run/<int:run_id>/prompt-audit.json")
    def admin_prompt_audit(run_id):
        """Read-only: for a saved check, what each prompt assumes and whether the hotel's verified facts support it (prompt_audit.py), the same answers grouped by scope, kind and segment, and the audiences placed
        as verified / operator-confirmed / contradicted. Asks no assistant, changes nothing."""
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        import prompt_audit
        rep = s.get_report(run_id)
        if not rep:
            abort(404)
        a = prompt_audit.audit(rep, limit=120)
        rows = [{k: v for k, v in r.items() if k not in ("why_asked",)} for r in a["prompts"]]
        return Response(json.dumps({"run_id": run_id, "hotel": (rep.get("meta") or {}).get("hotel"), "summary": a["summary"], "breakdown": prompt_audit.breakdown(rep),
                                    "audiences": prompt_audit.audience_status(rep), "prompts": rows}, indent=1, default=str), mimetype="application/json")

    @app.post("/admin/run/<int:run_id>/extraction/probe")
    def admin_extraction_probe(run_id):
        """Why were answers of this saved check not read? Asks the extraction model ONE call, on one group of the check's STORED answers (no web search, no new answers), and returns how that reply
        went: stop reason, tokens, blocks, how it parsed, the start and end of the reply. Nothing is saved or changed. `batch` = which group (default: the first that was lost)."""
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        if not cfg.anthropic:
            return Response(json.dumps({"error": "no Anthropic key on this host"}), mimetype="application/json", status=503)
        import ai_insights
        import ai_sample
        rep = s.get_report(run_id)
        if not rep:
            abort(404)
        its = [i for i in (rep.get("ai_sample") or {}).get("items") or [] if i.get("answer")]
        ordered = sorted(its, key=lambda i: i["kind"] != "direct")
        batches = [ordered[k:k + ai_insights.BATCH] for k in range(0, len(ordered), ai_insights.BATCH)]
        read = (rep.get("ai_insights") or {}).get("extracted_answers") or {}
        lost = [k for k, b in enumerate(batches) if not any(i["id"] in read for i in b)]
        k = int(request.form.get("batch") or (lost[0] if lost else 0))
        if not 0 <= k < len(batches):
            abort(400)
        size = int(request.form.get("size") or 0)
        batch = batches[k][:size] if size else batches[k]
        meta = rep.get("meta") or {}
        diag = {}
        try:
            client = ai_sample._make_client(cfg.anthropic, timeout=120.0)
            _think = {"type": "disabled"} if request.form.get("thinking") == "disabled" else None
            d, (tin, tout) = ai_insights._extract_batch(client, request.form.get("model") or ai_sample.MODEL_DEFAULT, batch, meta.get("hotel") or "", meta.get("city") or "", diag,
                                                        max_tokens=int(request.form.get("max_tokens") or 0) or None, thinking=_think)
            result = {"answers_in_reply": len((d or {}).get("answers") or []), "asked": len(batch)}
        except Exception as e:  # noqa: BLE001
            result = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
        return Response(json.dumps({"run_id": run_id, "batch": k, "lost_batches": lost, "size": len(batch), "answer_chars": sum(min(1800, len(i["answer"])) for i in batch), **result, "diag": diag,
                                    "max_tokens": ai_insights.MAX_TOKENS}, indent=1, default=str), mimetype="application/json")

    @app.post("/admin/release/assess")
    def admin_release_assess():
        """Work out and SAVE the release state of the named saved checks (checks made before release states existed have none). No assistant is asked."""
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        import report_release
        done = []
        for rid in [int(x) for x in re.findall(r"\d+", request.form.get("run_ids") or "")][:25]:
            rep = s.get_report(rid)
            if not rep:
                continue
            report_release.assess(rep, legacy=True)
            s.update_run(rid, rep)
            done.append({"run_id": rid, "state": rep["release"]["state"], "reasons": [x["code"] for x in rep["release"]["reasons"]]})
        return Response(json.dumps({"done": done}, indent=1, default=str), mimetype="application/json")

    @app.post("/admin/run/<int:run_id>/release/approve")
    def admin_release_approve(run_id):
        """Accept the reasons a report is waiting for review (a blocked report cannot be approved)."""
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
        s, msg = store_or_msg()
        if s is None:
            abort(503)
        import report_release
        rep = s.get_report(run_id)
        if not rep:
            abort(404)
        ok, message = report_release.approve(rep, "admin")
        if ok:
            s.update_run(run_id, rep)
        return Response(json.dumps({"run_id": run_id, "approved": ok, "message": message, "state": (rep.get("release") or {}).get("state")}, indent=1), mimetype="application/json")

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

    import admin_portfolio
    admin_portfolio.register(app, cfg, guard, shell, store_or_msg, csrf)

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

    @app.get("/admin/speed")
    def admin_speed():
        """Why pages are slow: how long one database request takes from this host, where the database is, what is running now, and the slowest recent pages with their database share."""
        g = guard()
        if g:
            return g
        esc = htmlst.html.escape
        s, msg = store_or_msg()
        out = []
        if s is None:
            out.append(f'<div class="alert warning">{esc(msg)}</div>')
        else:
            pings = []
            for _i in range(5):
                t0 = time.perf_counter()
                try:
                    s._rows("SELECT 1 AS x")
                except Exception as e:  # noqa: BLE001
                    out.append(f'<div class="alert warning">The database did not answer: {esc(type(e).__name__)}</div>')
                    break
                pings.append((time.perf_counter() - t0) * 1000)
            host = (urllib.parse.urlparse(cfg.database_url).hostname or "") if cfg.database_url else ""
            region = ".".join(host.split(".")[1:]) if host.count(".") >= 3 else host          # e.g. eu-central-1.aws.neon.tech (never the password or user)
            if pings:
                ms = sorted(pings)[len(pings) // 2]
                verdict = ("fast: the app and the database are close together" if ms < 15 else "slow-ish" if ms < 60 else
                           "SLOW: every page makes dozens of database requests, so this alone adds seconds. The app and the database are probably in different parts of the world")
                out.append(f'<section class="panel"><h4>Database</h4><p>One request from the app to the database takes <b>{ms:.0f} ms</b> (middle of 5) &mdash; {esc(verdict)}.</p>'
                           f'<p class="caption">Database location: <b>{esc(region or "-")}</b>. App location: see Render &rarr; your app &rarr; Settings &rarr; Region. They should be in the same region.</p></section>')
        W = app.extensions.get("weekly")
        running = [hid for hid, st in (getattr(W, "live", {}) or {}).items() if st.get("state") in ("queued", "running")] if W else []
        mgr = app.extensions.get("jobs")
        quick = sum(1 for j in (getattr(mgr, "jobs", {}) or {}).values() if j.status in ("queued", "running")) if mgr else 0
        out.append(f'<section class="panel"><h4>Running now</h4><p>{len(running)} hotel check{"s" if len(running) != 1 else ""} and {quick} quick audit{"s" if quick != 1 else ""}. '
                   'While these run they share the app&rsquo;s processor with every page.</p></section>')
        rows = sorted(app.extensions.get("slow_log") or [], key=lambda r: -r["when"])[:40]
        body = "".join(f'<tr><td>{esc(uk_time(time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(r["when"]))))}</td><td>{esc(r["method"])} {esc(r["path"])}</td><td>{r["total"]:.1f}s</td>'
                       f'<td>{r["queries"]}</td><td>{r["db"]:.1f}s ({(r["db"] / r["total"] * 100) if r["total"] else 0:.0f}%)</td></tr>' for r in rows)
        out.append('<section class="panel"><h4>Slowest recent pages (over 0.4 s, since the app last started)</h4>'
                   + (f'<div class="table-wrap"><table class="table"><thead><tr><th>When (UK time)</th><th>Page</th><th>Took</th><th>Database requests</th><th>Of which database</th></tr></thead><tbody>{body}</tbody></table></div>'
                      if body else '<p class="caption">None yet: open a few pages and come back.</p>')
                   + '<p class="caption">If most of the time is database, the app and database are too far apart (or the database was waking up). If little of it is, the app&rsquo;s processor is the limit '
                     '(the free plan, or checks running at the same time).</p></section>')
        return shell("speed", "Speed", "".join(out))

    @app.get("/admin/read")
    def admin_read():
        """
        Diagnostic: one page through Firecrawl, then every stage of our pipeline, so a wrong finding can be traced to where it went wrong (Paris Marriott review): what Firecrawl returned, the text the
        page reader made of it, and what each guest question extracted, with the exact sentence quoted. ?url=...  &raw=html|markdown returns that copy as a file (for a test fixture). One Firecrawl credit.
        """
        g = guard()
        if g:
            return g
        import os
        import firecrawl_reader
        import guest_questions as gq
        import store as quota
        url = (request.args.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            return Response(json.dumps({"error": "give ?url=https://... (the page to read)"}), status=400, mimetype="application/json")
        key = os.environ.get("FIRECRAWL_API_KEY")
        if not key:
            return Response(json.dumps({"error": "FIRECRAWL_API_KEY is not set on this host"}), status=400, mimetype="application/json")
        res = firecrawl_reader.scrape(url, key)
        quota.record_usage(1, audits=0, service="firecrawl")
        raw = request.args.get("raw")
        if raw in ("html", "markdown"):
            body = res.get("html" if raw == "html" else "markdown") or ""
            name = re.sub(r"[^a-z0-9]+", "-", urllib.parse.urlparse(url).path.lower()).strip("-")[:60] or "page"
            return Response(body, mimetype="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.{"html" if raw == "html" else "md"}"'})
        out = {"url": url, "firecrawl": {"ok": res.get("ok"), "reason": res.get("reason"), "title": res.get("title"), "markdown_chars": len(res.get("markdown") or ""), "html_chars": len(res.get("html") or ""),
                                         "links": len(res.get("links") or []), "markdown": (res.get("markdown") or "")[:20000]}}
        if res.get("ok") and request.args.get("compare"):
            both = {}
            for name, flag in (("old", False), ("new", True)):
                pg = firecrawl_reader.build_page(url, res, lines=flag)
                qs = gq.evaluate([dict(pg, ok=True)])
                both[name] = {"lines": (pg.get("text") or "").count("\n") + 1, "text": (pg.get("text") or "")[:12000],
                              "questions": {q["id"]: {"state": q.get("state"), "missing": q.get("missing"), "not_offered": [n.get("label") for n in q.get("not_offered") or []],
                                                      "quoted": [[f.get("label"), (f.get("snippet") or "")[:240]] for f in q.get("fact_snippets") or []]} for q in qs}}
            out["compare"] = both
            out["firecrawl"].pop("markdown", None)
            if request.args.get("find"):
                try:
                    rx_ = re.compile(request.args["find"], re.I)
                except re.error:
                    rx_ = re.compile(re.escape(request.args["find"]), re.I)
                for name, flag in (("old", False), ("new", True)):
                    full = firecrawl_reader.build_page(url, res, lines=flag).get("text") or ""
                    ls = full.split("\n")
                    out["compare"][name]["found"] = [" | ".join(ls[max(0, i - 2): i + 3])[:600] for i, ln in enumerate(ls) if rx_.search(ln)][:15] if flag else \
                        [full[max(0, m.start() - 200): m.end() + 200] for m in rx_.finditer(full)][:15]
            return Response(json.dumps(out, indent=1, ensure_ascii=False), mimetype="application/json")
        if res.get("ok"):
            page = firecrawl_reader.build_page(url, res)
            out["page"] = {"built_from": "html" if page.get("html_via") else "markdown", "text_chars": len(page.get("text") or ""), "lines": (page.get("text") or "").count("\n") + 1,
                           "title": page.get("title"), "h1": page.get("h1"), "text": (page.get("text") or "")[:20000]}
            qs = gq.evaluate([dict(page, ok=True)])
            out["questions"] = [{"id": q["id"], "state": q.get("state"), "found": q.get("found"), "missing": q.get("missing"), "not_offered": q.get("not_offered"),
                                 "quoted": [{"fact": f.get("label"), "sentence": f.get("snippet")} for f in q.get("fact_snippets") or []] or ([{"fact": "-", "sentence": q.get("snippet")}] if q.get("snippet") else [])}
                                for q in qs]
        return Response(json.dumps(out, indent=1, ensure_ascii=False), mimetype="application/json")

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
        names = {"claude": "Claude ($, thousandths)", "ai_chatgpt_usd": "ChatGPT ($, thousandths)", "ai_gemini_usd": "Gemini ($, thousandths)", "ai_perplexity_usd": "Perplexity ($, thousandths)"}
        for svc in ("tavily", "claude", "ai_chatgpt_usd", "ai_gemini_usd", "ai_perplexity_usd", "firecrawl", "google_places", "tripadvisor", "chat", "gemini_reader", "amadeus"):     # every metered service, Firecrawl pages included
            used, remaining, _w = quota.quota_status(service=svc)
            lines.append({"Service": names.get(svc, svc), "Used this month": used, "Allowance": quota.SERVICE_CAPS.get(svc), "Left": remaining})
        out = ("<h5>By month</h5>" + _table(s.usage_by_month(), ["month", "runs", "hotels", "ai_cost_usd"], {"month": "Month", "runs": "Audits", "hotels": "Hotels", "ai_cost_usd": "Estimated AI cost $"})
               + '<p class="caption">Costs are the app\'s own estimates from reported token use and searches. The Anthropic Console is the source of truth for what was charged.</p>'
               + "<h5>Free-tier guards this month</h5>" + _table(lines) + '<p class="caption">Claude is counted in thousandths of a US dollar. These guards stop the service calling a key once its monthly allowance is used; the workspace spend limit in the Anthropic Console is the hard stop.</p>')
        return shell("usage", "Usage", out)

    @app.get("/admin/feedback")
    def admin_feedback():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("feedback", "Feedback", f'<div class="alert warning">{htmlst.html.escape(msg)}</div>')
        out = ('<p class="caption">Visitors mark each recommendation Useful or Wrong. If the evidence labels mean anything, Confirmed should be marked useful more often than Likely, and Likely more often than Worth checking. '
               'Small numbers say little: read these as a check on the labels once there are a few dozen marks, not before.</p>'
               + "<h5>How each evidence label was marked</h5>" + _table(s.feedback_summary(), ["label", "marked", "useful", "wrong", "useful_pct"], {"label": "Label", "marked": "Marked", "useful": "Useful", "wrong": "Wrong", "useful_pct": "% useful"})
               + "<h5>Most recent</h5>" + _table(s.recent_feedback(), ["created", "ref", "verdict", "label", "title", "note"], {"created": "When", "ref": "Ref", "verdict": "Verdict", "label": "Label", "title": "Recommendation", "note": "Note"}))
        import tool_feedback_view
        return shell("feedback", "Feedback", tool_feedback_view.panel(s.tool_feedback(grp="portfolio"), "/admin/tool-feedback", csrf(), "the Westmont portfolio hotels")
                     + "<h3 class=\"grp\">Marks on report recommendations</h3>" + out)

    @app.post("/admin/tool-feedback/<int:fid>/<status>")
    def admin_tool_feedback_status(fid, status):
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")) or status not in ("new", "seen", "done"):
            abort(400)
        s, _m = store_or_msg()
        f = s.get_tool_feedback(fid) if s else None
        import portal_db
        if not f or portal_db.group_of(f) != "portfolio":
            abort(404)
        s.set_tool_feedback_status(fid, status)
        return redirect(url_for("admin_feedback"))

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
