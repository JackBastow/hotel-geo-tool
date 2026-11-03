"""
The hotel portal: the pages a hotel's own staff use.

  /portal/signin            email and password (there is no public sign-up: the operator invites each person)
  /portal/invite/<token>    the invite (or password-reset) link: choose a password
  /portal                   the hotel's dashboard (or a list, for someone who looks after several hotels)
  /portal/hotel/<id>        one hotel's dashboard
  /portal/api/action        mark an action to do / working on it / done / not relevant

A hotel user sees only the hotels they are linked to, and only those hotels' reports. They have no access to the public audit form, other hotels, or the admin pages. The portal has its own
sign-in, separate from the site password and the admin password.
"""

import collections
import hmac
import secrets
import time

from flask import abort, jsonify, redirect, render_template, request, session

import accounts
import ai_dash
import backend
import portal_view
import progress

FAILS = collections.defaultdict(list)


def register(app, cfg):
    def db():
        if not cfg.database_url:
            return None
        try:
            return backend.open_store(cfg.database_url)
        except Exception:  # noqa: BLE001
            return None

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    def csrf_ok(value):
        return hmac.compare_digest(value or "", session.get("csrf", "x"))

    def current():
        """(user row, their hotels) for the signed-in hotel user, or (None, [])."""
        uid = session.get("uid")
        d = db()
        if not uid or d is None:
            return None, []
        u = d.user_by_id(uid)
        if not u or not u["active"]:
            session.pop("uid", None)
            return None, []
        return u, d.hotels_for_user(uid)

    def throttled(key):
        now = time.time()
        FAILS[key] = [t for t in FAILS[key] if now - t < 600]
        return len(FAILS[key]) >= 6

    def shell(title, content, user=None, hotels=()):
        return render_template("portal.html", title=title, content=content, user=user, hotels=hotels, csrf=csrf())

    def form(title, heading, intro, fields, button, error="", status=200):
        return render_template("portal_form.html", title=title, heading=heading, intro=intro, fields=fields, button=button, error=error, csrf=csrf()), status

    def unavailable():
        return render_template("portal_form.html", title="Hotel portal", heading="The hotel portal is not available", intro="This service has no database connected, so it cannot keep accounts.",
                               fields=[], button="", error="", csrf=""), 503

    # ---------------------------------------------------------------- sign in
    @app.route("/portal/signin", methods=["GET", "POST"])
    def portal_signin():
        d = db()
        if d is None:
            return unavailable()
        fields = [{"label": "Email", "name": "email", "type": "email", "auto": "username", "autofocus": True}, {"label": "Password", "name": "password", "type": "password", "auto": "current-password"}]
        if request.method == "POST":
            email = accounts.clean_email(request.form.get("email")) or ""
            ip = request.remote_addr or "?"
            if throttled(ip) or throttled("e:" + email):
                return form("Sign in", "Sign in", "Your hotel's progress dashboard.", fields, "Sign in", "Too many wrong attempts. Please try again in ten minutes.", 429)
            u = d.user_by_email(email) if email else None
            ok = bool(u and u["active"] and accounts.check_password(request.form.get("password", ""), u["pw_hash"]))
            if not u:
                accounts.check_password("x", "scrypt$00$00")           # spend similar time whether or not the account exists
            if not ok:
                FAILS[ip].append(time.time())
                FAILS["e:" + email].append(time.time())
                time.sleep(1.0)
                return form("Sign in", "Sign in", "Your hotel's progress dashboard.", fields, "Sign in", "That email and password do not match.", 200)
            keep = {k: True for k in ("admin_ok", "site_ok") if session.get(k) is True}
            session.clear()
            session.update(keep)
            session["uid"] = u["id"]
            session.permanent = True
            d.touch_login(u["id"])
            return redirect("/portal")
        return form("Sign in", "Sign in", "Your hotel's progress dashboard.", fields, "Sign in")

    @app.post("/portal/signout")
    def portal_signout():
        session.pop("uid", None)
        return redirect("/portal/signin")

    # ---------------------------------------------------------------- invites and resets
    @app.route("/portal/invite/<token>", methods=["GET", "POST"])
    def portal_invite(token):
        d = db()
        if d is None:
            return unavailable()
        inv = d.get_invite(accounts.token_hash(token))
        if not inv:
            return form("Link not valid", "This link has expired or was already used", "Ask the person who invited you for a new one.", [], "", "", 410)
        reset = inv["kind"] == "reset"
        fields = [{"label": "Email", "name": "email_shown", "type": "email", "value": inv["email"], "readonly": True, "auto": "username"}]
        if not reset:
            fields.append({"label": "Your name", "name": "name", "type": "text", "auto": "name", "autofocus": True})
        fields += [{"label": f"Choose a password (at least {accounts.MIN_PASSWORD} characters)", "name": "password", "type": "password", "auto": "new-password"},
                   {"label": "Repeat the password", "name": "password2", "type": "password", "auto": "new-password"}]
        title, heading = ("Reset your password", "Choose a new password") if reset else ("Create your login", "Create your login")
        hotel = d.get_hotel(inv["hotel_id"]) if inv["hotel_id"] else None
        intro = f"For {hotel['name']}." if hotel else ""
        if request.method == "POST":
            if not csrf_ok(request.form.get("csrf")):
                abort(400)
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            problem = accounts.password_problem(pw) or ("The two passwords are not the same." if pw != pw2 else "")
            if problem:
                return form(title, heading, intro, fields, "Save", problem)
            if reset and inv["user_id"]:
                uid = inv["user_id"]
                d.set_password(uid, accounts.hash_password(pw))
            else:
                existing = d.user_by_email(inv["email"])
                if existing:
                    uid = existing["id"]
                    d.set_password(uid, accounts.hash_password(pw))
                else:
                    uid = d.create_user(inv["email"], (request.form.get("name") or "").strip()[:80], accounts.hash_password(pw))
                if inv["hotel_id"]:
                    d.link_user(uid, inv["hotel_id"])
            d.use_invite(inv["id"])
            keep = {k: True for k in ("admin_ok", "site_ok") if session.get(k) is True}
            session.clear()
            session.update(keep)
            session["uid"] = uid
            session.permanent = True
            d.touch_login(uid)
            return redirect("/portal")
        return form(title, heading, intro, fields, "Save and continue")

    # ---------------------------------------------------------------- dashboard
    def dashboard_page(hotel, user, hotels):
        d = db()
        sm = progress.hotel_summary(d, hotel)
        body = portal_view.dashboard(sm, d.list_actions(hotel["id"]), d.hotel_runs(hotel["hotel_key"]), editable=True, csrf=csrf(), ai=ai_dash.panel(d, hotel))
        return shell(hotel["name"] + ": progress", body, user, hotels)

    @app.get("/portal")
    def portal_home():
        if db() is None:
            return unavailable()
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        if len(hotels) == 1:
            return dashboard_page(hotels[0], user, hotels)
        if not hotels:
            return shell("Your hotels", '<div class="alert info">No hotel is linked to this login yet. Please ask the person who invited you.</div>', user, hotels)
        cards = "".join(f'<a class="panel" style="display:block;margin:10px 0" href="/portal/hotel/{h["id"]}"><b>{portal_view.esc(h["name"])}</b> <span class="hk-muted">{portal_view.esc(h["city"] or "")}</span></a>' for h in hotels)
        return shell("Your hotels", f"<h1>Your hotels</h1>{cards}", user, hotels)

    @app.get("/portal/hotel/<int:hotel_id>")
    def portal_hotel(hotel_id):
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        h = next((x for x in hotels if x["id"] == hotel_id), None)
        if h is None:
            abort(404)
        return dashboard_page(h, user, hotels)

    @app.post("/portal/api/action")
    def portal_action():
        user, hotels = current()
        if not user:
            return jsonify(ok=False, error="Please sign in again."), 401
        if not csrf_ok(request.headers.get("X-CSRF", "")):
            return jsonify(ok=False, error="Please reload the page and try again."), 400
        d = db()
        data = request.get_json(silent=True) or {}
        try:
            aid = int(data.get("id"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Unknown action."), 400
        a = d.get_action(aid)
        if not a or a["hotel_id"] not in {h["id"] for h in hotels}:
            return jsonify(ok=False, error="Unknown action."), 404
        res = progress.set_status(d, a["hotel_id"], aid, str(data.get("status")), who=user["email"], note=(str(data["note"]) if "note" in data else None))
        if not res:
            return jsonify(ok=False, error="That is not a valid status."), 400
        return jsonify(ok=True, status=res["status"])

    def can_see_token(token):
        """May the signed-in hotel user open the report with this link? Only when it is a report of one of their hotels."""
        user, hotels = current()
        if not user:
            return False
        key = db().hotel_key_for_token(token) if db() else None
        return bool(key) and any(h["hotel_key"] == key for h in hotels)

    app.extensions["portal_can_see_token"] = can_see_token
    app.extensions["portal_current"] = current
