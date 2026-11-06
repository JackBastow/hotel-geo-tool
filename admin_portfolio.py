"""
The operator's portfolio pages (inside /admin): every registered hotel with its progress, a page per hotel showing exactly what the hotel sees plus the controls (invite a user, reset a password, switch
weekly checks, run a check now), and the roll-up across the portfolio.

Hotel users never see any of this: they only have /portal.
"""

import hmac
import html

from flask import abort, redirect, request, session

import accounts
import ai_dash
import backend
import netguard
import portal_view
import progress
import prompt_sets
import prompts_view
import urlscope
from timeutil import uk_date, uk_time

esc = html.escape


def _key_for(website):
    return backend.hotel_key({"meta": {"base": urlscope.normalise(website)[0]}})


def _latest_report(s, runs):
    try:
        return s.get_report(runs[0]["id"]) if runs else None
    except Exception:  # noqa: BLE001
        return None


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001
        return None


def register(app, cfg, guard, shell, store_or_msg, csrf):
    def checked_post():
        g = guard()
        if g:
            return g, None
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
            abort(400)
        s, msg = store_or_msg()
        if s is None:
            return shell("portfolio", "Portfolio", f'<div class="alert warning">{esc(msg)}</div>'), None
        return None, s

    def delta_cell(d):
        return "-" if d is None else f'<b style="color:{"#067647" if d > 0 else "#b42318" if d < 0 else "inherit"}">{d:+g}</b>'

    @app.get("/admin/portfolio")
    def admin_portfolio():
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("portfolio", "Portfolio", f'<div class="alert warning">{esc(msg)}</div>')
        data = progress.portfolio_data(s)
        rows, tot = progress.portfolio_summary(s, data)
        if tot["measured"]:
            line = (f'<div class="pt-progress"><b>{tot["hotels"]} hotels.</b> {tot["completed"]} actions completed ({tot["verified"]} checked and confirmed on the sites), {tot["working"]} in progress. '
                    f'Of the {tot["measured"]} hotels with more than one check, <b>{tot["improved"]}</b> have a higher readiness score; the average has moved from <b>{tot["avg_first"]:g}</b> to <b>{tot["avg_latest"]:g}</b>.</div>')
        else:
            line = f'<div class="pt-progress"><b>{tot["hotels"]} hotel{"s" if tot["hotels"] != 1 else ""}.</b> Progress across the portfolio shows here once hotels have been checked more than once.</div>'
        avg, comp = progress.portfolio_series(s, data)
        charts = ""
        if avg:
            charts = ('<div class="ov-grid even"><section class="panel"><h4>Average readiness score, all hotels</h4>' + portal_view.trend_svg(avg) + '</section>'
                      '<section class="panel"><h4>Actions completed, all hotels</h4>' + portal_view.trend_svg(comp, maximum=max(4, max(p["score"] for p in comp)), name="Actions completed") + '</section></div>')
        W = app.extensions["weekly"]
        states = {r["hotel"]["id"]: W.hotel_state(r["hotel"]["id"]) for r in rows}
        any_active = any(st["state"] in ("queued", "running") for st in states.values())

        def status_cell(hid):
            st = states[hid]
            if st["state"] in ("queued", "running"):
                last = esc((st["messages"] or [""])[-1])
                return f'<b style="color:#3730a3">{"Waiting" if st["state"] == "queued" else "Running"}</b> <span class="hk-muted">({st["elapsed"] // 60}m {st["elapsed"] % 60}s) {last}</span>'
            if st["state"] == "done":
                return '<b style="color:#067647">Finished</b>'
            if st["state"] == "error":
                return '<b style="color:#b42318">Did not finish</b>'
            return ""
        body = "".join(
            f'<tr><td><a href="/admin/hotel/{r["hotel"]["id"]}">{esc(r["hotel"]["name"])}</a><br><span class="hk-muted">{esc(r["hotel"]["city"] or "")}</span></td><td>{esc(uk_date(r["last_run_at"])) or "not yet"}</td><td>{r["runs"]}</td>'
            f'<td>{"-" if r["first_score"] is None else format(r["first_score"], "g")}</td><td>{"-" if r["latest_score"] is None else format(r["latest_score"], "g")}</td><td>{delta_cell(r["delta"])}</td>'
            f'<td>{r["actions"]["completed"]}</td><td>{r["actions"]["working"]}</td><td>{r["actions"]["todo"] + r["actions"]["still_flagged"]}</td><td>{"weekly" if r["hotel"]["weekly"] else "off"}</td>'
            f'<td>{status_cell(r["hotel"]["id"])}</td><td>{esc(uk_time(r["hotel"]["last_attempt"])) or "-"}</td><td>{esc(r["hotel"]["last_error"] or "")}</td></tr>' for r in rows)
        table = ('<div class="table-wrap"><table class="table"><thead><tr><th>Hotel</th><th>Last check</th><th>Checks</th><th>First score</th><th>Latest score</th><th>Change</th><th>Actions done</th>'
                 '<th>Working on</th><th>To do</th><th>Weekly</th><th>Right now</th><th>Last attempt (UK time)</th><th>Last problem</th></tr></thead><tbody>' + (body or '<tr><td colspan="13">No hotels registered yet.</td></tr>') + "</tbody></table></div>")
        c_ = csrf()
        runs = (f'<p><form method="post" action="/admin/portfolio/run-all" style="display:inline"><input type="hidden" name="csrf" value="{c_}"><button class="btn primary" type="submit">Run a check on every hotel now</button></form> '
                f'<form method="post" action="/admin/portfolio/run-due" style="display:inline"><input type="hidden" name="csrf" value="{c_}"><button class="btn" type="submit">Run only the checks that are due</button></form></p>'
                '<p class="caption">Each hotel is checked one after another; open a hotel to watch its check live. The weekly job does the same every Monday.</p>')
        add = (f'<h5>Add a hotel</h5><form class="filters" method="post" action="/admin/portfolio/add"><input type="hidden" name="csrf" value="{csrf()}">'
               '<label class="field"><span>Hotel name</span><input name="name" required></label><label class="field"><span>Website address</span><input name="website" placeholder="hotel-site.com/the-hotel" required></label>'
               '<label class="field"><span>Town or city</span><input name="city" required></label><button class="btn primary" type="submit">Add hotel</button></form>'
               '<p class="caption">Adding a hotel does not run a check by itself: use &ldquo;Run a check now&rdquo; on its page, or the next weekly check picks it up. Audits already saved for the same website count as its history.</p>')
        msg = request.args.get("msg", "")
        notice = ""
        if msg.startswith("started:"):
            names = msg[8:].split("|")
            notice = f'<div class="alert success"><b>Started checks for {len(names)} hotel{"s" if len(names) != 1 else ""}:</b> {esc(", ".join(names))}. They run one after another; the &ldquo;Right now&rdquo; column updates by itself.</div>'
        elif msg == "none-due":
            notice = ('<div class="alert warning"><b>Nothing was due.</b> A hotel is due when its latest check is 6 or more days old and it has not been tried in the last 12 hours. '
                      'Use &ldquo;Run a check on every hotel now&rdquo; to check them all regardless.</div>')
        elif msg == "busy":
            notice = '<div class="alert warning">Those checks are already running or waiting.</div>'
        marker = '<div data-pf-active="1"></div>' if any_active else ""
        return shell("portfolio", "Portfolio", notice + marker + line + '<p class="caption">Progress, not proof: the score moving after actions were completed does not show the actions caused it. Times are UK time.</p>' + charts + runs + table + add)

    @app.post("/admin/portfolio/add")
    def admin_portfolio_add():
        bad, s = checked_post()
        if bad:
            return bad
        name, site, city = (request.form.get(k, "").strip()[:120] for k in ("name", "website", "city"))
        site = site if site and "." in site and not any(c in site for c in " \r\n\t") else ""
        if not (name and site and city) or not netguard.url_ok(site if "//" in site else "https://" + site):
            return shell("portfolio", "Portfolio", '<div class="alert warning">Enter the hotel&rsquo;s name, a public website address and the town or city.</div>')
        key = _key_for(site)
        have = s.hotel_by_key(key)
        if have:
            return redirect(f"/admin/hotel/{have['id']}")
        return redirect(f"/admin/hotel/{s.create_hotel(name, site, city, key)}")

    def hotel_page(s, hid, notice=""):
        h = s.get_hotel(hid)
        if not h:
            abort(404)
        acts = progress.actions_for(s, h)
        runs = s.hotel_runs(h["hotel_key"])
        sm = progress.hotel_summary(s, h, list(reversed(runs)), acts)
        prompt_sets.ensure_from_history(s, h)
        pst = prompt_sets.state(s, h)
        rep = _latest_report(s, runs)
        import opportunities
        import query_matrix
        import strategy_view
        have = [p["text"] for st_ in (pst["draft"], pst["active"]) if st_ for p in st_["prompts"]]
        since = sum(1 for r in runs if pst["active"] and r["run_at"] >= pst["active"]["confirmed_at"])
        users = s.users_for_hotel(hid)
        ut = "".join(f'<tr><td>{esc(u["email"])}</td><td>{esc(u["name"] or "")}</td><td>{esc(uk_time(u["last_login"])) or "never"}</td><td>{"active" if u["active"] else "switched off"}</td><td>'
                     f'<form method="post" action="/admin/hotel/{hid}/reset/{u["id"]}" style="display:inline"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn" type="submit">Make a password-reset link</button></form> '
                     f'<form method="post" action="/admin/hotel/{hid}/user/{u["id"]}/{"off" if u["active"] else "on"}" style="display:inline"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn" type="submit">{"Switch off" if u["active"] else "Switch on"}</button></form></td></tr>'
                     for u in users)
        invites = "".join(f'<li>{esc(i["email"])} ({esc(i["kind"])}), link valid until {esc(uk_time(i["expires"]))}</li>' for i in s.open_invites(hid))
        c = csrf()
        panel = (f'<section class="panel"><h4>Manage this hotel</h4>{notice}'
                 f'<p><form method="post" action="/admin/hotel/{hid}/run" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn primary" type="submit">Run a check now</button></form> '
                 f'<form method="post" action="/admin/hotel/{hid}/reset-prompts" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Reset its automatic prompts</button></form> '
                 f'<form method="post" action="/admin/hotel/{hid}/weekly" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Weekly checks are {"ON: switch off" if h["weekly"] else "OFF: switch on"}</button></form></p>'
                 + (f'<p class="caption">Last problem: {esc(h["last_error"])}</p>' if h["last_error"] else "")
                 + f'<h5>People who can sign in ({len(users)})</h5>' + (f'<div class="table-wrap"><table class="table"><thead><tr><th>Email</th><th>Name</th><th>Last sign-in (UK time)</th><th></th><th></th></tr></thead><tbody>{ut}</tbody></table></div>' if users else '<p class="caption">Nobody has a login yet.</p>')
                 + f'<form class="filters" method="post" action="/admin/hotel/{hid}/invite"><input type="hidden" name="csrf" value="{c}"><label class="field"><span>Invite someone (their email)</span><input type="email" name="email" required></label>'
                 '<button class="btn" type="submit">Make an invite link</button></form><p class="caption">There is no email service: you get a link to send them yourself. It works once and expires in 7 days.</p>'
                 + (f'<h6>Links still open</h6><ul>{invites}</ul>' if invites else "") + "</section>")
        view = portal_view.dashboard(sm, acts, runs, editable=False, csrf=csrf(), ai=ai_dash.panel(s, h), prompts=prompts_view.panel(pst, h, f"/admin/hotel/{hid}/prompts", True, since, (_safe(query_matrix.suggest, rep, have) or []) if rep else []),
                                     prompts_alert=bool(pst["draft"] and not pst["active"]), opps=(_safe(opportunities.build, rep) or []) if rep else [], strategy=(_safe(strategy_view.panel, rep) or "") if rep else "",
                                     live=app.extensions["weekly"].hotel_state(hid), live_url=f"/admin/hotel/{hid}/status")
        return shell("portfolio", h["name"], panel + '<p class="caption">Below is exactly what the hotel sees (read-only here).</p>' + view)

    @app.post("/admin/hotel/<int:hid>/prompts")
    def admin_hotel_prompts(hid):
        if not session.get("admin_ok"):
            return {"ok": False, "error": "Please sign in again."}, 401
        if not hmac.compare_digest(request.headers.get("X-CSRF", ""), session.get("csrf", "x")):
            return {"ok": False, "error": "Please reload the page and try again."}, 400
        s, msg = store_or_msg()
        h = s.get_hotel(hid) if s else None
        if not h:
            abort(404)
        st = prompt_sets.state(s, h)
        ok, res = prompt_sets.handle(s, h, "the operator", request.get_json(silent=True) or {}, prompt_sets.anchors_from(st["draft"], st["active"]))
        return {"ok": ok, **res}, (200 if ok else 400)

    @app.get("/admin/hotel/<int:hid>/status")
    def admin_hotel_status(hid):
        if not session.get("admin_ok"):
            return {"ok": False}, 401
        return {"ok": True, **app.extensions["weekly"].hotel_state(hid)}

    @app.post("/admin/portfolio/run-due")
    def admin_run_due():
        bad, s = checked_post()
        if bad:
            return bad
        W = app.extensions["weekly"]
        names = [h["name"] for h in W.due(s) if not W.active(h["id"])]
        W.start()
        return redirect("/admin/portfolio?msg=" + ("started:" + "|".join(names) if names else "none-due"))

    @app.post("/admin/portfolio/run-all")
    def admin_run_all():
        bad, s = checked_post()
        if bad:
            return bad
        W = app.extensions["weekly"]
        hs = [h for h in s.list_hotels(only_active=True) if not W.active(h["id"])]
        W.start(force_ids={h["id"] for h in hs})
        return redirect("/admin/portfolio?msg=" + ("started:" + "|".join(h["name"] for h in hs) if hs else "busy"))

    @app.get("/admin/hotel/<int:hid>")
    def admin_hotel_page(hid):
        g = guard()
        if g:
            return g
        s, msg = store_or_msg()
        if s is None:
            return shell("portfolio", "Portfolio", f'<div class="alert warning">{esc(msg)}</div>')
        return hotel_page(s, hid)

    def link_notice(token, email, what):
        url = request.host_url.rstrip("/") + "/portal/invite/" + token
        return (f'<div class="alert success"><b>{what} for {esc(email)}.</b> Send them this link. It is shown only now, works once, and expires in {accounts.INVITE_DAYS} days.'
                f'<br><code style="word-break:break-all">{esc(url)}</code></div>')

    @app.post("/admin/hotel/<int:hid>/invite")
    def admin_invite(hid):
        bad, s = checked_post()
        if bad:
            return bad
        email = accounts.clean_email(request.form.get("email"))
        if not email or not s.get_hotel(hid):
            return hotel_page(s, hid, '<div class="alert warning">Enter a valid email address.</div>')
        tok, h = accounts.new_token()
        s.create_invite(h, email, hid, None, "invite", accounts.INVITE_DAYS)
        return hotel_page(s, hid, link_notice(tok, email, "Invite link made"))

    @app.post("/admin/hotel/<int:hid>/reset/<int:uid>")
    def admin_reset(hid, uid):
        bad, s = checked_post()
        if bad:
            return bad
        u = s.user_by_id(uid)
        if not u or uid not in {x["id"] for x in s.users_for_hotel(hid)}:
            abort(404)
        tok, h = accounts.new_token()
        s.create_invite(h, u["email"], hid, uid, "reset", accounts.INVITE_DAYS)
        return hotel_page(s, hid, link_notice(tok, u["email"], "Password-reset link made"))

    @app.post("/admin/hotel/<int:hid>/user/<int:uid>/<state>")
    def admin_user_state(hid, uid, state):
        bad, s = checked_post()
        if bad:
            return bad
        if uid in {x["id"] for x in s.users_for_hotel(hid)} and state in ("on", "off"):
            s.set_user_active(uid, state == "on")
        return redirect(f"/admin/hotel/{hid}")

    @app.post("/admin/hotel/<int:hid>/reset-prompts")
    def admin_reset_prompts(hid):
        bad, s = checked_post()
        if bad:
            return bad
        h = s.get_hotel(hid)
        if not h:
            abort(404)
        s.clear_benchmark(h["hotel_key"])                                   # the prompts frozen at the first audit
        for p in s.prompt_sets(hid):
            if p["status"] == "draft":
                s.delete_prompt_set(p["id"])                                # an unconfirmed recommended set built from the old prompts
        has_confirmed = bool(s.confirmed_prompts_for_key(h["hotel_key"]))
        return hotel_page(s, hid, '<div class="alert success"><b>Prompts reset.</b> The next check writes a fresh recommended set from the current question engine, and the hotel is asked to confirm it.'
                                  + (' The hotel has a <i>confirmed</i> set, which is left as it is: the hotel can change it on its Prompts tab.' if has_confirmed else '') + '</div>')

    @app.post("/admin/hotel/<int:hid>/weekly")
    def admin_weekly_toggle(hid):
        bad, s = checked_post()
        if bad:
            return bad
        h = s.get_hotel(hid)
        if not h:
            abort(404)
        s.set_hotel(hid, weekly=0 if h["weekly"] else 1)
        return redirect(f"/admin/hotel/{hid}")

    @app.post("/admin/hotel/<int:hid>/run")
    def admin_run_now(hid):
        bad, s = checked_post()
        if bad:
            return bad
        if not s.get_hotel(hid):
            abort(404)
        started, n = app.extensions["weekly"].start(force_ids={hid})
        return redirect(f"/admin/hotel/{hid}")            # the page shows the check running, live
