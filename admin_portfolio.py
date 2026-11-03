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
import urlscope
from timeutil import uk_date, uk_time

esc = html.escape


def _key_for(website):
    return backend.hotel_key({"meta": {"base": urlscope.normalise(website)[0]}})


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
        rows, tot = progress.portfolio_summary(s)
        if tot["measured"]:
            line = (f'<div class="pt-progress"><b>{tot["hotels"]} hotels.</b> {tot["completed"]} actions completed ({tot["verified"]} checked and confirmed on the sites), {tot["working"]} in progress. '
                    f'Of the {tot["measured"]} hotels with more than one check, <b>{tot["improved"]}</b> have a higher readiness score; the average has moved from <b>{tot["avg_first"]:g}</b> to <b>{tot["avg_latest"]:g}</b>.</div>')
        else:
            line = f'<div class="pt-progress"><b>{tot["hotels"]} hotel{"s" if tot["hotels"] != 1 else ""}.</b> Progress across the portfolio shows here once hotels have been checked more than once.</div>'
        avg, comp = progress.portfolio_series(s)
        charts = ""
        if avg:
            charts = ('<div class="ov-grid even"><section class="panel"><h4>Average readiness score, all hotels</h4>' + portal_view.trend_svg(avg) + '</section>'
                      '<section class="panel"><h4>Actions completed, all hotels</h4>' + portal_view.trend_svg(comp, maximum=max(4, max(p["score"] for p in comp)), name="Actions completed") + '</section></div>')
        body = "".join(
            f'<tr><td><a href="/admin/hotel/{r["hotel"]["id"]}">{esc(r["hotel"]["name"])}</a><br><span class="hk-muted">{esc(r["hotel"]["city"] or "")}</span></td><td>{esc(uk_date(r["last_run_at"])) or "not yet"}</td><td>{r["runs"]}</td>'
            f'<td>{"-" if r["first_score"] is None else format(r["first_score"], "g")}</td><td>{"-" if r["latest_score"] is None else format(r["latest_score"], "g")}</td><td>{delta_cell(r["delta"])}</td>'
            f'<td>{r["actions"]["completed"]}</td><td>{r["actions"]["working"]}</td><td>{r["actions"]["todo"] + r["actions"]["still_flagged"]}</td><td>{"weekly" if r["hotel"]["weekly"] else "off"}</td>'
            f'<td>{esc(r["hotel"]["last_error"] or "")}</td></tr>' for r in rows)
        table = ('<div class="table-wrap"><table class="table"><thead><tr><th>Hotel</th><th>Last check</th><th>Checks</th><th>First score</th><th>Latest score</th><th>Change</th><th>Actions done</th>'
                 '<th>Working on</th><th>To do</th><th>Weekly</th><th>Last problem</th></tr></thead><tbody>' + (body or '<tr><td colspan="11">No hotels registered yet.</td></tr>') + "</tbody></table></div>")
        add = (f'<h5>Add a hotel</h5><form class="filters" method="post" action="/admin/portfolio/add"><input type="hidden" name="csrf" value="{csrf()}">'
               '<label class="field"><span>Hotel name</span><input name="name" required></label><label class="field"><span>Website address</span><input name="website" placeholder="hotel-site.com/the-hotel" required></label>'
               '<label class="field"><span>Town or city</span><input name="city" required></label><button class="btn primary" type="submit">Add hotel</button></form>'
               '<p class="caption">Adding a hotel does not run a check by itself: use &ldquo;Run a check now&rdquo; on its page, or the next weekly check picks it up. Audits already saved for the same website count as its history.</p>')
        return shell("portfolio", "Portfolio", line + '<p class="caption">Progress, not proof: the score moving after actions were completed does not show the actions caused it. Times are UK time.</p>' + charts + table + add)

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
        sm = progress.hotel_summary(s, h)
        users = s.users_for_hotel(hid)
        ut = "".join(f'<tr><td>{esc(u["email"])}</td><td>{esc(u["name"] or "")}</td><td>{esc(uk_time(u["last_login"])) or "never"}</td><td>{"active" if u["active"] else "switched off"}</td><td>'
                     f'<form method="post" action="/admin/hotel/{hid}/reset/{u["id"]}" style="display:inline"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn" type="submit">Make a password-reset link</button></form> '
                     f'<form method="post" action="/admin/hotel/{hid}/user/{u["id"]}/{"off" if u["active"] else "on"}" style="display:inline"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn" type="submit">{"Switch off" if u["active"] else "Switch on"}</button></form></td></tr>'
                     for u in users)
        invites = "".join(f'<li>{esc(i["email"])} ({esc(i["kind"])}), link valid until {esc(uk_time(i["expires"]))}</li>' for i in s.open_invites(hid))
        c = csrf()
        panel = (f'<section class="panel"><h4>Manage this hotel</h4>{notice}'
                 f'<p><form method="post" action="/admin/hotel/{hid}/run" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn primary" type="submit">Run a check now</button></form> '
                 f'<form method="post" action="/admin/hotel/{hid}/weekly" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Weekly checks are {"ON: switch off" if h["weekly"] else "OFF: switch on"}</button></form></p>'
                 + (f'<p class="caption">Last problem: {esc(h["last_error"])}</p>' if h["last_error"] else "")
                 + f'<h5>People who can sign in ({len(users)})</h5>' + (f'<div class="table-wrap"><table class="table"><thead><tr><th>Email</th><th>Name</th><th>Last sign-in (UK time)</th><th></th><th></th></tr></thead><tbody>{ut}</tbody></table></div>' if users else '<p class="caption">Nobody has a login yet.</p>')
                 + f'<form class="filters" method="post" action="/admin/hotel/{hid}/invite"><input type="hidden" name="csrf" value="{c}"><label class="field"><span>Invite someone (their email)</span><input type="email" name="email" required></label>'
                 '<button class="btn" type="submit">Make an invite link</button></form><p class="caption">There is no email service: you get a link to send them yourself. It works once and expires in 7 days.</p>'
                 + (f'<h6>Links still open</h6><ul>{invites}</ul>' if invites else "") + "</section>")
        view = portal_view.dashboard(sm, s.list_actions(hid), s.hotel_runs(h["hotel_key"]), editable=False, csrf="", ai=ai_dash.panel(s, h))
        return shell("portfolio", h["name"], panel + '<p class="caption">Below is exactly what the hotel sees (read-only here).</p>' + view)

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
        note = ('<div class="alert success">A check has started. It takes a few minutes; reload this page to see it appear under &ldquo;Checks so far&rdquo;.</div>' if started
                else '<div class="alert warning">Another batch of checks is still running. Try again in a few minutes.</div>')
        return hotel_page(s, hid, note)
