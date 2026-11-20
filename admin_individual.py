"""
The individual-hotels admin, at /hotels-admin: its own address and its own password (INDIVIDUAL_ADMIN_PASSWORD), separate from the main admin.

Someone signed in here can add individual hotels, make invite and password-reset links, switch weekly checks, run checks and edit prompts, exactly like the main admin's hotel pages,
but only ever for hotels in the "individual" group. Portfolio hotels, the Overview, runs, usage, exports and the quick audit are not reachable from here, and a portfolio hotel's page answers
"not found". The main admin still sees and manages every hotel, including these.

Without INDIVIDUAL_ADMIN_PASSWORD set, none of these pages exist.
"""

import collections
import hmac
import secrets
import time

from flask import abort, redirect, render_template, request, session

import admin_portfolio
import backend
import portal_db

BASE = "/hotels-admin"
HOURS = 8
_failed = collections.defaultdict(list)


def register(app, cfg):
    def password():
        return getattr(cfg, "individual_admin_password", "") or ""

    def authed():
        return bool(password()) and session.get("ind_ok") is True and (session.get("ind_until") or 0) > time.time()

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    def shell(_active, title, content):
        return render_template("hotels_admin.html", title=title, content=content, base=BASE)

    def store_or_msg():
        if not cfg.database_url:
            return None, "No database is connected."
        try:
            return backend.open_store(cfg.database_url), ""
        except Exception as e:  # noqa: BLE001
            return None, f"The database could not be reached: {type(e).__name__}"

    def guard():
        if not password():
            abort(404)
        if not authed():
            return redirect(BASE + "/login")
        return None

    @app.route(BASE + "/login", methods=["GET", "POST"])
    def hotels_admin_login():
        if not password():
            abort(404)
        error = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            now = time.time()
            _failed[ip] = [t for t in _failed[ip] if now - t < 600]
            if len(_failed[ip]) >= 5:
                error = "Too many wrong passwords. Try again in ten minutes."
            elif hmac.compare_digest((request.form.get("password") or "").encode(), str(password()).encode()):
                session["ind_ok"] = True                                    # other sign-ins in the same browser (site, main admin, a hotel login) are left as they are
                session["ind_until"] = time.time() + HOURS * 3600
                session.permanent = True
                return redirect(BASE)
            else:
                _failed[ip].append(now)
                time.sleep(1.5)
                error = "Wrong password."
        return render_template("hotels_admin_login.html", error=error, base=BASE)

    @app.post(BASE + "/logout")
    def hotels_admin_logout():
        session.pop("ind_ok", None)
        session.pop("ind_until", None)
        return redirect(BASE + "/login")

    def can_see_token(token):
        """May the person signed in here open the report with this link? Only a report of an individual hotel."""
        if not authed() or not cfg.database_url:
            return False
        try:
            s = backend.open_store(cfg.database_url)
            key = s.hotel_key_for_token(token)
            h = s.hotel_by_key(key) if key else None
        except Exception:  # noqa: BLE001
            return False
        return bool(h) and portal_db.group_of(h) == "individual"

    app.extensions["hotels_admin_can_see_token"] = can_see_token

    @app.get(BASE + "/feedback")
    def hotels_admin_feedback():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("feedback", "Feedback", f'<div class="alert warning">{msg}</div>')
        import tool_feedback_view
        return shell("feedback", "Feedback", tool_feedback_view.panel(s.tool_feedback(grp="individual"), BASE + "/feedback", csrf(), "the individual hotels"))

    @app.post(BASE + "/feedback/<int:fid>/<status>")
    def hotels_admin_feedback_status(fid, status):
        g = guard()
        if g:
            return g
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")) or status not in ("new", "seen", "done"):
            abort(400)
        s, _m = store_or_msg()
        f = s.get_tool_feedback(fid) if s else None
        if not f or portal_db.group_of(f) != "individual":
            abort(404)                                                # never another group's feedback
        s.set_tool_feedback_status(fid, status)
        return redirect(BASE + "/feedback")

    sc = admin_portfolio.Scope("individual", guard, shell, store_or_msg, csrf, authed, ("individual",), {"individual": BASE}, BASE, BASE + "/hotel", False)
    admin_portfolio.register_scope(app, sc)
