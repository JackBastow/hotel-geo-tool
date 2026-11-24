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
import re
import secrets
import time

from flask import abort, jsonify, redirect, render_template, request, session

import accounts
import ai_dash
import backend
import hotel_profile
import portal_view
import start_here
import progress
import prompt_sets
import prompts_view

FAILS = collections.defaultdict(list)
FEEDBACK_KINDS = {"idea": "An idea", "problem": "Something is wrong", "question": "A question", "praise": "Something I like"}


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
        if not u or not u["active"] or int(u.get("session_ver") or 0) != int(session.get("sv") or 0):
            session.pop("uid", None)                       # switched off, or the password was changed / everyone signed out since this sign-in
            session.pop("sv", None)
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
            keep = {k: session[k] for k in ("admin_ok", "admin_until", "site_ok", "ind_ok", "ind_until", "csrf") if session.get(k)}
            session.clear()
            session.update(keep)
            session["uid"] = u["id"]
            session["sv"] = int((d.user_by_id(u["id"]) or {}).get("session_ver") or 0)      # this sign-in belongs to the login as it is now
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
        existing = None if reset else d.user_by_email(inv["email"])
        if existing:
            # This person already has a login. An invite link must never set their password: anyone holding the link (whoever made it, or anyone it was forwarded to) could
            # otherwise take over the account and every hotel it can see. They prove who they are with their current password, and the hotel is added to their login.
            hotel = d.get_hotel(inv["hotel_id"]) if inv["hotel_id"] else None
            fields_x = fields + [{"label": "Your current password", "name": "password", "type": "password", "auto": "current-password", "autofocus": True}]
            intro_x = (f"You already have a login. Sign in with your current password to add {hotel['name']} to it." if hotel else "You already have a login. Sign in with your current password.")
            if request.method == "POST":
                if not csrf_ok(request.form.get("csrf")):
                    abort(400)
                if throttled("e:" + inv["email"]) or throttled(request.remote_addr or "?"):
                    return form("Add a hotel", "Add a hotel to your login", intro_x, fields_x, "Sign in and add", "Too many attempts. Wait ten minutes and try again.", 429)
                if not existing.get("active") or not accounts.check_password(request.form.get("password", ""), existing.get("pw_hash") or ""):
                    FAILS["e:" + inv["email"]].append(time.time())
                    FAILS[request.remote_addr or "?"].append(time.time())
                    time.sleep(1.0)
                    return form("Add a hotel", "Add a hotel to your login", intro_x, fields_x, "Sign in and add", "That password is not right. Use the password you already sign in with, or ask for a password-reset link.")
                if not d.use_invite(inv["id"]):
                    return form("Link not valid", "This link has expired or was already used", "Ask the person who invited you for a new one.", [], "", "", 410)
                if inv["hotel_id"]:
                    d.link_user(existing["id"], inv["hotel_id"])
                keep = {k: session[k] for k in ("admin_ok", "admin_until", "site_ok", "ind_ok", "ind_until", "csrf") if session.get(k)}
                session.clear()
                session.update(keep)
                session["uid"] = existing["id"]
                session["sv"] = int((d.user_by_id(existing["id"]) or {}).get("session_ver") or 0)      # this sign-in belongs to the login as it is now
                session.permanent = True
                d.touch_login(existing["id"])
                return redirect("/portal")
            return form("Add a hotel", "Add a hotel to your login", intro_x, fields_x, "Sign in and add")
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
            if not d.use_invite(inv["id"]):          # claimed first: one link, one use, even when two requests arrive together
                return form("Link not valid", "This link has expired or was already used", "Ask the person who invited you for a new one.", [], "", "", 410)
            if reset and inv["user_id"]:
                uid = inv["user_id"]
                d.set_password(uid, accounts.hash_password(pw))
            else:
                if d.user_by_email(inv["email"]):              # a login was created for this email meanwhile: never set its password from a link
                    return form("Login already exists", "A login already exists for this email", "Sign in with its password, or ask for a password-reset link.", [], "", "", 409)
                uid = d.create_user(inv["email"], (request.form.get("name") or "").strip()[:80], accounts.hash_password(pw))
                if inv["hotel_id"]:
                    d.link_user(uid, inv["hotel_id"])
            try:        # the first time anyone sets up a login for a hotel that has never been checked, start its first check, so the dashboard is full when they land on it
                hh = d.get_hotel(inv["hotel_id"]) if inv["hotel_id"] else None
                if hh and hh["active"] and hh.get("setup") != "pending" and not d.hotel_runs(hh["hotel_key"]):
                    app.extensions["weekly"].start(force_ids={hh["id"]})
            except Exception:  # noqa: BLE001 - never block the sign-up
                pass
            keep = {k: session[k] for k in ("admin_ok", "admin_until", "site_ok", "ind_ok", "ind_until", "csrf") if session.get(k)}
            session.clear()
            session.update(keep)
            session["uid"] = uid
            session["sv"] = int((d.user_by_id(uid) or {}).get("session_ver") or 0)      # this sign-in belongs to the login as it is now
            session.permanent = True
            d.touch_login(uid)
            return redirect("/portal")
        return form(title, heading, intro, fields, "Save and continue")

    # ---------------------------------------------------------------- dashboard
    def _latest(d, runs):
        try:
            return d.get_report(runs[0]["id"]) if runs else None
        except Exception:  # noqa: BLE001 - the dashboard still shows
            return None

    def _opps(rep):
        try:
            import opportunities
            return opportunities.build(rep) if rep else []
        except Exception:  # noqa: BLE001
            return []

    def _strategy(rep):
        try:
            import strategy_view
            return strategy_view.panel(rep)
        except Exception:  # noqa: BLE001
            return ""

    def _suggestions(rep, pst):
        try:
            import query_matrix
            have = [p["text"] for s in (pst["draft"], pst["active"]) if s for p in s["prompts"]]
            return query_matrix.suggest(rep, have) if rep else []
        except Exception:  # noqa: BLE001
            return []

    def _from_results(d, hotel, pst):
        try:
            import exploration
            have = [p["text"] for s in (pst["draft"], pst["active"]) if s for p in s["prompts"]]
            return exploration.suggest(d, hotel, have) if pst["draft"] else []          # offered while the set is being edited, where the Add button works
        except Exception:  # noqa: BLE001
            return []

    def profile_banner(hotel):
        """A hotel set up before profiles: ask it to review the profile drafted for it (its checks carry on meanwhile)."""
        if hotel.get("setup") in ("pending", "done") or hotel_profile.confirmed(hotel):
            return ""
        return (f'<section class="talk-callout"><div><h3>Check your hotel profile</h3><p>Tell us exactly what kind of place you are, why guests come and where they search for you. '
                f'We use it to ask AI assistants the right questions and compare you with the right competitors.</p></div><a class="btn primary" href="/portal/hotel/{hotel["id"]}/profile">Check the profile &rarr;</a></section>')

    def extra_tabs(rep, hotel):
        """The Prompt analysis, Competitors and Join the conversation tabs, from the latest check. A problem in one leaves that tab saying so, never the page."""
        import competitors_view
        import dashboard_view
        import prompt_analysis
        out = {}
        if rep:
            import glance
            try:
                import manual_checks
                d_ = db()
                saved_ = d_.manual_checks(hotel["id"], manual_checks.ENGINE) if d_ is not None and hotel else []
                if saved_:
                    rep = {**rep, "manual_checks": saved_}
            except Exception:  # noqa: BLE001
                pass

            def glance_html(prev=None):
                parts = []
                for fn in (lambda: dashboard_view.readiness_banner(rep, prev), lambda: dashboard_view.at_a_glance(rep), lambda: glance.scorecard_html(rep), lambda: glance.engines_html(rep), lambda: glance.strengths_html(rep)):
                    try:
                        parts.append(fn() or "")
                    except Exception:  # noqa: BLE001 - one part that fails is left out; the rest of the Overview shows
                        pass
                return "".join(parts)
            out["glance"] = glance_html
        for k, fn in (("analysis", lambda: prompt_analysis.panel(rep)), ("competitors", lambda: competitors_view.panel(rep, hotel)), ("talk", lambda: dashboard_view.talk_tab(rep) if rep else "")):
            try:
                out[k] = fn()
            except Exception:  # noqa: BLE001
                out[k] = '<div class="alert warning">This part could not be shown for the latest check.</div>'
        return out

    app.extensions["extra_tabs"] = extra_tabs

    def dashboard_page(hotel, user, hotels):
        d = db()
        if hotel.get("setup") == "pending" and not hotel_profile.confirmed(hotel):
            return redirect(f"/portal/hotel/{hotel['id']}/profile")          # a new hotel starts by setting up its profile
        if not hotel_profile.load(hotel) and cfg.database_url:
            hotel_profile.start_draft(cfg.database_url, hotel["id"], cfg)     # a hotel set up before profiles: draft one to review
        acts = progress.actions_for(d, hotel)
        runs = d.hotel_runs(hotel["hotel_key"])                       # newest first; the same rows give the summary (oldest first) and the history table
        sm = progress.hotel_summary(d, hotel, list(reversed(runs)), acts)
        prompt_sets.ensure_from_history(d, hotel)
        pst = prompt_sets.state(d, hotel)
        rep = _latest(d, d.hotel_runs(hotel["hotel_key"]))
        since = sum(1 for r in runs if pst["active"] and r["run_at"] >= pst["active"]["confirmed_at"])
        body = portal_view.dashboard(sm, acts, runs, editable=True, csrf=csrf(), start=start_here.safe(d, hotel, sm, acts, runs, True, pst), ai=ai_dash.panel(d, hotel),
                                     prompts_alert=bool(pst["draft"] and not pst["active"]), opps=_opps(rep), strategy=_strategy(rep), **extra_tabs(rep, hotel),
                                     live=app.extensions["weekly"].hotel_state(hotel["id"]), live_url=f"/portal/api/status/{hotel['id']}", settings_url=f"/portal/hotel/{hotel['id']}/settings",
                                     research_html=research_html(hotel, f"/portal/hotel/{hotel['id']}/research"))
        if hotel.get("setup") == "done" and not runs and not app.extensions["weekly"].active(hotel["id"]):
            body = '<div class="alert info"><b>Your first check is on its way.</b> It starts as soon as there is room and takes about 15 minutes; this page fills in when it is done.</div>' + body
        return shell(hotel["name"] + ": progress", profile_banner(hotel) + body, user, hotels)

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

    @app.post("/portal/api/prompts/<int:hotel_id>")
    def portal_prompts(hotel_id):
        user, hotels = current()
        if not user or hotel_id not in {h["id"] for h in hotels}:
            return jsonify(ok=False, error="Please sign in again."), 401
        if not csrf_ok(request.headers.get("X-CSRF", "")):
            return jsonify(ok=False, error="Please reload the page and try again."), 400
        d = db()
        hotel = next(h for h in hotels if h["id"] == hotel_id)
        st = prompt_sets.state(d, hotel)
        payload = request.get_json(silent=True) or {}
        ok, res = prompt_sets.handle(d, hotel, user["email"], payload, prompt_sets.anchors_from(st["draft"], st["active"]) + [{"name": x} for x in hotel_profile.places(hotel_profile.confirmed(hotel))])
        if ok and payload.get("action") == "confirm":
            res = {**res, **first_check(d, hotel)}
        return jsonify(ok=ok, **res), (200 if ok else 400)

    def first_check(d, hotel):
        """Confirming the prompts of a new hotel finishes its set-up and starts its first check."""
        h = d.get_hotel(hotel["id"])
        if h and h.get("setup") == "pending":
            d.set_hotel(h["id"], setup="done")
            try:
                app.extensions["weekly"].start(force_ids={h["id"]})
            except Exception:  # noqa: BLE001
                pass
            return {"message": "Prompts confirmed. Your first check has started: it takes about 15 minutes, and this page fills in when it is done."}
        return {}

    app.extensions["first_check"] = first_check

    @app.get("/portal/settings")
    def portal_settings_home():
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        if len(hotels) == 1:
            return redirect(f"/portal/hotel/{hotels[0]['id']}/settings")
        cards = "".join(f'<a class="panel" style="display:block;margin:10px 0" href="/portal/hotel/{h["id"]}/settings"><b>{portal_view.esc(h["name"])}</b></a>' for h in hotels)
        return shell("Settings", "<h1>Settings</h1><p class=\"lede\">Choose a hotel.</p>" + (cards or '<div class="alert info">No hotel is linked to this login yet.</div>'), user, hotels)

    @app.get("/portal/hotel/<int:hotel_id>/settings")
    def portal_settings(hotel_id):
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        h = next((x for x in hotels if x["id"] == hotel_id), None)
        if h is None:
            abort(404)
        esc = portal_view.esc
        p = hotel_profile.load(h)
        rows = []
        if p:
            kinds = ", ".join(dict(hotel_profile.KINDS).get(k, k) for k in p["kinds"])
            auds = ", ".join(dict(hotel_profile.audiences()).get(k, k) for k in p["audiences"])
            for label, val in (("Address", p["address"]), ("Town", p["town"]), ("Region", p["region"]), ("Wider area", p["area"]), ("Places guests come for", ", ".join(p["attractions"])),
                               ("Kind of stay", kinds), ("Why guests choose you", "; ".join(p["reasons"])), ("Guests", auds), ("Where they come from", p["origins"]),
                               ("Languages", ", ".join(p["languages"])), ("Price level", dict(hotel_profile.PRICES).get(p["price"], "")), ("Competitors", ", ".join(p["competitors"]))):
                rows.append(f'<tr><th style="text-align:left;width:220px">{esc(label)}</th><td>{esc(val) or "<span class=hk-muted>not given</span>"}</td></tr>')
        status = ("Confirmed: " + esc(hotel_profile.last_change(p))) if p and p.get("status") == "confirmed" else ("A draft from your website, not confirmed yet." if p else "Not filled in yet.")
        profile = (f'<section class="panel"><h4>Hotel profile</h4><p class="caption">What kind of place you are and how guests find you. Every check is built on it: the questions we ask AI assistants, '
                   f'the places they mention and the competitors we compare you with. {status}</p>'
                   + (f'<div class="table-wrap"><table class="table">{"".join(rows)}</table></div>' if rows else "")
                   + f'<p><a class="btn primary" href="/portal/hotel/{h["id"]}/profile">Edit the profile</a></p>'
                   '<p class="caption">Saving a changed profile writes a new recommended set of prompts for you to check. Your current prompts stay in use until you confirm the new set.</p></section>')
        d = db()
        prompt_sets.ensure_from_history(d, h)
        pst = prompt_sets.state(d, h)
        runs = d.hotel_runs(h["hotel_key"])
        rep = _latest(d, runs)
        since = sum(1 for r in runs if pst["active"] and r["run_at"] >= pst["active"]["confirmed_at"])
        prompts = prompts_view.panel(pst, h, "/portal/api/prompts/" + str(h["id"]), True, since, _suggestions(rep, pst), _from_results(d, h, pst))
        history = f'<p class="caption">Every check of this hotel, newest first.</p>{portal_view.history_table(runs) or "<p class=caption>No checks yet.</p>"}'
        login = f'<section class="panel"><h4>Your login</h4><p>{esc(user["email"])}</p><p class="caption">To change your password, sign out and ask the person who invited you for a password-reset link.</p></section>'
        tabs = [("profile", "Hotel profile", profile), ("prompts", "Prompts" + (" (to confirm)" if pst["draft"] and not pst["active"] else ""), prompts), ("history", "History", history), ("login", "Your login", login)]
        nav = "".join(f'<button type="button" class="tab{" active" if i == 0 else ""}" data-tab="tab-{k}" data-name="{k}">{esc(lbl)}</button>' for i, (k, lbl, _b) in enumerate(tabs))
        panels = "".join(f'<div class="tab-panel{" active" if i == 0 else ""}" id="tab-{k}">{b}</div>' for i, (k, _l, b) in enumerate(tabs))
        body = (f'<div class="pt" data-csrf="{esc(csrf())}"><p><a href="/portal/hotel/{h["id"]}">&larr; Back to the dashboard</a></p><h1>Settings</h1>'
                f'<div class="tabs top"><div class="tab-bar" role="tablist">{nav}</div>{panels}</div></div>')
        return shell(h["name"] + ": settings", body, user, hotels)

    @app.route("/portal/hotel/<int:hotel_id>/profile", methods=["GET", "POST"])
    def portal_profile(hotel_id):
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        h = next((x for x in hotels if x["id"] == hotel_id), None)
        if h is None:
            abort(404)
        d = db()
        old = hotel_profile.load(h)
        if not old and not hotel_profile.drafting(h["id"]):
            hotel_profile.start_draft(cfg.database_url, h["id"], cfg)
        error = ""
        if request.method == "POST":
            if not csrf_ok(request.form.get("csrf")):
                abort(400)
            prof, error = hotel_profile.from_form(request.form, old, user["email"])
            if not error:
                hotel_profile.apply(d, h, prof)
                n = hotel_profile.write_prompts(d, d.get_hotel(h["id"]), prof, cfg)
                import strategy_research
                strategy_research.start(cfg.database_url, h["id"], cfg)          # the specific sources for the market the hotel just described
                return redirect(f"/portal/hotel/{h['id']}/settings#prompts" if n else f"/portal/hotel/{h['id']}?profile=saved")
            old = prof
        new = h.get("setup") == "pending"
        intro = ('<h1>Set up your hotel</h1><p class="lede">Before we measure anything, tell us exactly which hotel you are and how your guests find you. '
                 'Then we write the prompts to ask AI assistants about places like yours; you check them, and confirming them starts your first check.</p>' if new else
                 f'<p><a href="/portal/hotel/{h["id"]}/settings">&larr; Back to settings</a></p><h1>Your hotel profile</h1><p class="lede">What kind of place you are and how guests find you. Everything we measure is built on it. ({portal_view.esc(hotel_profile.last_change(old))})</p>')
        steps = ('<p class="caption"><b>Step 1 of 3: your profile</b> &rarr; 2: check the prompts &rarr; 3: your first check runs.</p>' if new else "")
        err = f'<div class="alert warning">{portal_view.esc(error)}</div>' if error else ""
        return shell(h["name"] + ": profile", intro + steps + err + hotel_profile.form_html(old or {**hotel_profile.empty(), "town": h.get("city") or ""}, f"/portal/hotel/{h['id']}/profile", csrf(), drafting_now=hotel_profile.drafting(h["id"]) and not old), user, hotels)

    @app.get("/portal/api/status/<int:hotel_id>")
    def portal_status(hotel_id):
        user, hotels = current()
        if not user or hotel_id not in {h["id"] for h in hotels}:
            return jsonify(ok=False), 404
        return jsonify(ok=True, **app.extensions["weekly"].hotel_state(hotel_id))

    @app.post("/portal/api/tool-feedback")
    def portal_tool_feedback():
        """Feedback about the tool from a signed-in hotel user: what kind, their words, and the page they were on. Kept short; a few an hour at most."""
        user, hotels = current()
        if not user:
            return jsonify(ok=False, error="Please sign in again."), 401
        if not csrf_ok(request.headers.get("X-CSRF", "")):
            return jsonify(ok=False, error="Please reload the page and try again."), 400
        data = request.get_json(silent=True) or {}
        kind = str(data.get("kind") or "")
        msg = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", str(data.get("message") or "")).strip()[:2000]
        page = str(data.get("page") or "")[:200]
        if kind not in FEEDBACK_KINDS or len(msg) < 3:
            return jsonify(ok=False, error="Write a few words first."), 400
        key = f"fb:{user['id']}"
        now = time.time()
        FAILS[key] = [t for t in FAILS[key] if now - t < 3600]
        if len(FAILS[key]) >= 20:
            return jsonify(ok=False, error="Thank you: that is plenty of feedback for one hour."), 429
        FAILS[key].append(now)
        m = re.search(r"/portal/hotel/(\d+)", page)
        hid = int(m.group(1)) if m and int(m.group(1)) in {h["id"] for h in hotels} else (hotels[0]["id"] if hotels else None)
        db().add_tool_feedback(hid, user["id"], user["email"], kind, msg, page)
        return jsonify(ok=True, message="Thank you. Your feedback has been sent.")

    @app.post("/portal/api/action-step")
    def portal_action_step():
        """Tick (or untick) one step of an action."""
        user, hotels = current()
        if not user:
            return jsonify(ok=False, error="Please sign in again."), 401
        if not csrf_ok(request.headers.get("X-CSRF", "")):
            return jsonify(ok=False, error="Please reload the page and try again."), 400
        d = db()
        data = request.get_json(silent=True) or {}
        try:
            aid, step = int(data.get("id")), int(data.get("step"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Unknown step."), 400
        a = d.get_action(aid)
        if not a or a["hotel_id"] not in {h["id"] for h in hotels} or not 0 <= step < 20:
            return jsonify(ok=False, error="Unknown step."), 404
        done = {int(x) for x in str(a.get("steps_done") or "").split(",") if x.strip().isdigit()}
        (done.add if data.get("done") else done.discard)(step)
        d.update_action(aid, steps_done=",".join(str(x) for x in sorted(done)))
        return jsonify(ok=True, done=sorted(done))

    @app.post("/portal/hotel/<int:hotel_id>/research")
    def portal_research(hotel_id):
        user, hotels = current()
        if not user:
            return redirect("/portal/signin")
        if hotel_id not in {h["id"] for h in hotels}:
            abort(404)
        if not csrf_ok(request.form.get("csrf")):
            abort(400)
        import strategy_research
        h = next(x for x in hotels if x["id"] == hotel_id)
        if strategy_research.recent(h, hours=6):
            return redirect(f"/portal/hotel/{hotel_id}#actions")          # a hotel's own button runs it at most every 6 hours: each run is a paid web search
        strategy_research.start(cfg.database_url, hotel_id, cfg)
        return redirect(f"/portal/hotel/{hotel_id}#actions")

    def research_html(hotel, post_url):
        """The Strategy section's research line, starting the research by itself when the hotel has a confirmed profile and none (or an old one)."""
        import strategy_research
        if hotel_profile.confirmed(hotel) and strategy_research.stale(hotel) and not strategy_research.running(hotel["id"]):
            strategy_research.start(cfg.database_url, hotel["id"], cfg)
        return portal_view.research_box(strategy_research.load(hotel), strategy_research.running(hotel["id"]), post_url, csrf(), can_run=bool(getattr(cfg, "anthropic", None)))

    app.extensions["research_html"] = research_html

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
