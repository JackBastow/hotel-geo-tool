"""
The operator's portfolio pages (inside /admin): every registered hotel with its progress, a page per hotel showing exactly what the hotel sees plus the controls (invite a user, reset a password, switch
weekly checks, run a check now), and the roll-up across the portfolio.

The same pages also serve the separate individual-hotels admin (/hotels-admin, admin_individual.py): its own address and password, and it can only ever see and manage the individual hotels.
Each set of pages is a "scope": which groups of hotels it may touch, its addresses, and its own sign-in.

Hotel users never see any of this: they only have /portal.
"""

import hmac
import html

from flask import Blueprint, abort, redirect, request, session

import accounts
import ai_dash
import backend
import exploration
import hotel_profile
import netguard
import portal_db
import portal_view
import start_here
import progress
import prompt_sets
import prompts_view
import urlscope
from timeutil import uk_date, uk_time

esc = html.escape
GROUP = {"portfolio": ("Portfolio", "/admin/portfolio"), "individual": ("Individual hotels", "/admin/individual")}


def _key_for(website, hotel="", city=""):
    return backend.hotel_key({"meta": {"base": urlscope.normalise(website, hotel, city)[0]}})


def _latest_report(s, runs):
    try:
        return s.get_report(runs[0]["id"]) if runs else None
    except Exception:  # noqa: BLE001
        return None


def _setup_flag(h):
    """A short warning in the hotel list when the hotel's name or town is wrongly entered (they go into every prompt and every drafted email)."""
    import quality_view
    probs = _safe(quality_view.setup_problems, h.get("name"), h.get("city"), h.get("website") or "") or []
    return ("".join(f'<div class="caption" style="color:#a3540b">&#9888; {esc(p.split(".")[0])}.</div>' for p in probs)) if probs else ""


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001
        return None


class Scope:
    """One set of hotel-management pages: the main admin (every group) or the individual-hotels admin (that group only)."""

    def __init__(self, name, guard, shell, store_or_msg, csrf, authed, groups, list_urls, list_base, hotel_base, can_move):
        self.name, self.guard, self.shell, self.store_or_msg, self.csrf, self.authed = name, guard, shell, store_or_msg, csrf, authed
        self.groups = groups                    # the groups this scope may see and manage; the first is the default
        self.list_urls = list_urls              # group -> the address of its list page
        self.list_base = list_base              # where the add / run-all / run-due forms post
        self.hotel_base = hotel_base            # /<hotel_base>/<id> is a hotel's page
        self.can_move = can_move                # the main (Westmont) admin: its titles and wording

    def title(self, grp):
        return GROUP[grp][0] if self.can_move else "Hotels"


def register(app, cfg, guard, shell, store_or_msg, csrf):
    sc = Scope("main", guard, shell, store_or_msg, csrf, lambda: session.get("admin_ok") is True,
               ("portfolio",), {"portfolio": "/admin/portfolio", "individual": "/hotels-admin"}, "/admin/portfolio", "/admin/hotel", True)
    register_scope(app, sc)

    @app.get("/admin/individual")
    def admin_individual_moved():
        return redirect("/hotels-admin")            # individual hotels have their own admin now


def register_scope(app, sc):
    bp = Blueprint("pf_" + sc.name, __name__)
    LB, HB = sc.list_base, sc.hotel_base
    main = sc.can_move

    def own(s, hid):
        """The hotel, if this scope may see it; otherwise 'not found' (the individual-hotels admin never learns a portfolio hotel exists)."""
        h = s.get_hotel(hid)
        if not h or portal_db.group_of(h) not in sc.groups:
            abort(404)
        return h

    def checked_post():
        g = sc.guard()
        if g:
            return g, None
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
            abort(400)
        s, msg = sc.store_or_msg()
        if s is None:
            return sc.shell(sc.groups[0], sc.title(sc.groups[0]), f'<div class="alert warning">{esc(msg)}</div>'), None
        return None, s

    def setup_cell(s, h):
        key, label = hotel_profile.status(s, h)
        colour = {"not_invited": "#b42318", "invited": "#b54708", "profile": "#3730a3", "prompts": "#3730a3", "checked": "#067647"}.get(key, "inherit")
        return f'<span style="color:{colour}">{esc(label)}</span>'

    def delta_cell(d):
        return "-" if d is None else f'<b style="color:{"#067647" if d > 0 else "#b42318" if d < 0 else "inherit"}">{d:+g}</b>'

    def grp_arg():
        g_ = request.values.get("grp", sc.groups[0])
        return g_ if g_ in sc.groups else sc.groups[0]

    if main:
        @bp.get("/admin/portfolio")
        def admin_portfolio():
            return list_page("portfolio")
    else:
        @bp.get(sc.list_urls["individual"])
        def hotels_list():
            return list_page("individual")

    def list_page(grp):
        """The Westmont portfolio, or the individual hotels: the same page and controls, each with only its own hotels and its own totals."""
        title = sc.title(grp)
        g = sc.guard()
        if g:
            return g
        s, msg = sc.store_or_msg()
        if s is None:
            return sc.shell(grp, title, f'<div class="alert warning">{esc(msg)}</div>')
        data = progress.portfolio_data(s, grp)
        rows, tot = progress.portfolio_summary(s, data)
        intro = ""
        across = "the portfolio" if grp == "portfolio" else "these hotels"
        if tot["measured"]:
            line = (f'<div class="pt-progress"><b>{tot["hotels"]} hotel{"s" if tot["hotels"] != 1 else ""}.</b> {tot["completed"]} actions marked done by hotels ({tot["verified"]} also confirmed by the checks), {tot["cleared_site"]} more no longer flagged by the checks but never marked done, {tot["working"]} in progress. '
                    f'Of the {tot["measured"]} hotels with more than one check, <b>{tot["improved"]}</b> have a higher readiness score; the average has moved from <b>{tot["avg_first"]:g}</b> to <b>{tot["avg_latest"]:g}</b>.</div>')
        else:
            line = f'<div class="pt-progress"><b>{tot["hotels"]} hotel{"s" if tot["hotels"] != 1 else ""}.</b> Progress across {across} shows here once hotels have been checked more than once.</div>'
        avg, comp = progress.portfolio_series(s, data)
        charts = ""
        all_ = "individual hotels" if (grp == "individual" and main) else "hotels"
        if avg:
            charts = ('<div class="ov-grid even"><section class="panel"><h4>Average readiness score, all ' + all_ + '</h4>' + portal_view.trend_svg(avg) + '</section>'
                      '<section class="panel"><h4>Actions completed, all ' + all_ + '</h4>' + portal_view.trend_svg(comp, maximum=max(4, max(p["score"] for p in comp)), name="Actions completed") + '</section></div>')
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
            f'<tr><td><a href="{HB}/{r["hotel"]["id"]}">{esc(r["hotel"]["name"])}</a><br><span class="hk-muted">{esc(r["hotel"]["city"] or "")}</span></td><td>{esc(uk_date(r["last_run_at"])) or "not yet"}</td><td>{r["runs"]}</td>'
            f'<td>{"-" if r["first_score"] is None else format(r["first_score"], "g")}</td><td>{"-" if r["latest_score"] is None else format(r["latest_score"], "g")}</td><td>{delta_cell(r["delta"])}</td>'
            f'<td>{r["actions"]["completed"]}</td><td>{r["actions"]["working"]}</td><td>{r["actions"]["todo"] + r["actions"]["still_flagged"]}</td><td>{"weekly" if r["hotel"]["weekly"] else "off"}</td>'
            f'<td>{status_cell(r["hotel"]["id"])}</td><td>{setup_cell(s, r["hotel"])}</td><td>{esc(uk_time(r["hotel"]["last_attempt"])) or "-"}</td><td>{esc(r["hotel"]["last_error"] or "")}{_setup_flag(r["hotel"])}</td></tr>' for r in rows)
        empty = "No individual hotels yet: add one below." if grp == "individual" else "No hotels registered yet."
        table = ('<div class="table-wrap"><table class="table"><thead><tr><th>Hotel</th><th>Last check</th><th>Checks</th><th>First score</th><th>Latest score</th><th>Change</th><th>Actions done</th>'
                 '<th>Working on</th><th>To do</th><th>Weekly</th><th>Right now</th><th>Set-up</th><th>Last attempt (UK time)</th><th>Last problem</th></tr></thead><tbody>' + (body or f'<tr><td colspan="14">{empty}</td></tr>') + "</tbody></table></div>")
        c_ = sc.csrf()
        hid_ = f'<input type="hidden" name="csrf" value="{c_}"><input type="hidden" name="grp" value="{grp}">'
        every = "individual hotel" if (grp == "individual" and main) else "hotel"
        runs = (f'<p><form method="post" action="{LB}/run-all" style="display:inline">{hid_}<button class="btn primary" type="submit">Run a check on every {every} now</button></form> '
                f'<form method="post" action="{LB}/run-due" style="display:inline">{hid_}<button class="btn" type="submit">Run only the checks that are due</button></form></p>'
                '<p class="caption">Each hotel is checked one after another; open a hotel to watch its check live. The weekly job does the same every Monday.</p>')
        add_t = ("Add an individual hotel" if grp == "individual" else "Add a hotel to the portfolio") if main else "Add a hotel"
        add = (f'<h5>{add_t}</h5><form class="filters" method="post" action="{LB}/add">{hid_}'
               '<label class="field"><span>Hotel name</span><input name="name" required></label><label class="field"><span>Website address</span><input name="website" placeholder="hotel-site.com/the-hotel" required></label>'
               '<label class="field"><span>Town or city</span><input name="city" required></label><button class="btn primary" type="submit">Add hotel</button></form>'
               '<p class="caption">Then open the hotel and use &ldquo;Make an invite link&rdquo;. When they first sign in they set up the hotel&rsquo;s profile, check the prompts written from it, '
               'and confirming the prompts starts the first check; weekly checks follow. Nothing is checked before that (you can still use &ldquo;Run a check now&rdquo;, or fill in the profile yourself). '
               'Audits already saved for the same website count as its history.</p>')
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
        elif msg == "taken":
            notice = ('<div class="alert warning"><b>That website is already registered as an individual hotel</b>, so it was not added to the portfolio. It is managed in the Hotels admin (/hotels-admin).</div>' if main else
                      '<div class="alert warning"><b>That website is already registered</b> with this service, so it was not added here.</div>')
        marker = '<div data-pf-active="1"></div>' if any_active else ""
        return sc.shell(grp, title, intro + notice + marker + line + '<p class="caption">Progress, not proof: the score moving after actions were completed does not show the actions caused it. Times are UK time.</p>' + charts + runs + table + add)

    @bp.post(LB + "/add")
    def hotel_add():
        bad, s = checked_post()
        if bad:
            return bad
        name, site, city = (request.form.get(k, "").strip()[:120] for k in ("name", "website", "city"))
        site = site if site and "." in site and not any(c in site for c in " \r\n\t") else ""
        grp = grp_arg()
        if city and urlscope.is_country(city):
            return sc.shell(grp, sc.title(grp), '<div class="alert warning">&ldquo;' + esc(city) + '&rdquo; is a country. Enter the <b>town or city</b> the hotel is in (for example Paris, or Roissy-en-France): the questions put to AI assistants are about hotels in a town.</div>')
        if not (name and site and city) or not netguard.url_ok(site if "//" in site else "https://" + site):
            return sc.shell(grp, sc.title(grp), '<div class="alert warning">Enter the hotel&rsquo;s name, a public website address and the town or city.</div>')
        key = _key_for(site, name, city)
        have = s.hotel_by_key(key)
        if have:
            if portal_db.group_of(have) not in sc.groups:
                return redirect(sc.list_urls[grp] + "?msg=taken")              # a hotel this scope may not see: say so without opening (or naming) it
            return redirect(f"{HB}/{have['id']}?msg=exists")          # already registered (in whichever group): its page says which, and can move it
        hid = s.create_hotel(name, site, city, key, grp=grp, setup="pending")
        W = app.extensions["weekly"]
        if getattr(W.cfg, "database_url", None):
            hotel_profile.start_draft(W.cfg.database_url, hid, W.cfg)         # read its website for a draft profile while the invite is sent
        return redirect(f"{HB}/{hid}")

    def hotel_page(s, hid, notice=""):
        h = own(s, hid)
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
        c = sc.csrf()
        ut = "".join(f'<tr><td>{esc(u["email"])}</td><td>{esc(u["name"] or "")}</td><td>{esc(uk_time(u["last_login"])) or "never"}</td><td>{"active" if u["active"] else "switched off"}</td><td>'
                     f'<form method="post" action="{HB}/{hid}/reset/{u["id"]}" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Make a password-reset link</button></form> '
                     f'<form method="post" action="{HB}/{hid}/user/{u["id"]}/{"off" if u["active"] else "on"}" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">{"Switch off" if u["active"] else "Switch on"}</button></form></td></tr>'
                     for u in users)
        invites = "".join(f'<li>{esc(i["email"])} ({esc(i["kind"])}), link valid until {esc(uk_time(i["expires"]))}</li>' for i in s.open_invites(hid))
        grp = portal_db.group_of(h)
        if request.args.get("msg") == "exists" and not notice:
            notice = '<div class="alert warning">That website is already registered, as this hotel. Nothing new was added.</div>'
        where = f'<p><a href="{sc.list_urls[grp]}">&larr; All hotels</a></p>'
        prof = hotel_profile.load(h)
        skey, slabel = hotel_profile.status(s, h)
        mp = hotel_profile.map_link(prof)
        profile_box = (f'<p><b>Set-up:</b> {esc(slabel)}. <b>Profile:</b> {esc(hotel_profile.last_change(prof)) if prof else ("being drafted from the website" if hotel_profile.drafting(hid) else "none yet")}'
                       + (f' &middot; <a href="{esc(mp, quote=True)}" target="_blank" rel="noopener">map</a>' if mp else "")
                       + f' &middot; <a class="btn small" href="{HB}/{hid}/profile">{"Open the profile" if prof else "Fill in the profile"}</a></p>'
                       + (f'<p class="caption">{esc(", ".join(dict(hotel_profile.KINDS).get(k, k) for k in prof["kinds"]))}{" &middot; " if prof["kinds"] else ""}town {esc(prof["town"] or "-")}, region {esc(prof["region"] or "-")}, area {esc(prof["area"] or "-")}'
                          + (f' &middot; competitors: {esc(", ".join(prof["competitors"]))}' if prof["competitors"] else "") + '</p>' if prof else "")
                       + ('<p class="caption">Not checked weekly until its prompts are confirmed (by the hotel or by you on the Prompts tab below).</p>' if h.get("setup") == "pending" else ""))
        panel = (f'<section class="panel"><h4>Manage this hotel</h4>{notice}{where}{profile_box}'
                 f'<p><form method="post" action="{HB}/{hid}/run" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn primary" type="submit">Run a check now</button></form> '
                 f'<a class="btn" href="{HB}/{hid}/settings">Settings: profile, prompts, history</a> '
                 f'<form method="post" action="{HB}/{hid}/reset-prompts" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Reset its automatic prompts</button></form> '
                 f'<form method="post" action="{HB}/{hid}/weekly" style="display:inline"><input type="hidden" name="csrf" value="{c}"><button class="btn" type="submit">Weekly checks are {"ON: switch off" if h["weekly"] else "OFF: switch on"}</button></form></p>'
                 + (f'<p class="caption">Last problem: {esc(h["last_error"])}</p>' if h["last_error"] else "")
                 + f'<form class="filters" method="post" action="{HB}/{hid}/details"><input type="hidden" name="csrf" value="{c}">'
                 f'<label class="field"><span>Hotel name</span><input name="name" value="{esc(h["name"] or "", quote=True)}" required></label>'
                 f'<label class="field"><span>Town or city</span><input name="city" value="{esc(h["city"] or "", quote=True)}" required></label>'
                 '<button class="btn" type="submit">Save name and town</button></form>'
                 '<p class="caption">The town is what every question to the AI assistant is about, so it must be the real town travellers search for (a hotel on an estate outside a town: use that town). '
                 'Changing it makes fresh recommended prompts at the next check; a set the hotel has confirmed is left alone.</p>'
                 + (('<details class="details"><summary>Delete a check</summary><div class="details-body"><p class="caption">For a check that should never have counted (for example one run with the wrong town). '
                     'It is removed for good, with the recommendations it alone raised; the hotel&rsquo;s other checks, and anything the hotel has marked done or is working on, stay.</p><ul>'
                     + "".join(f'<li>{esc(uk_time(r["run_at"]))}, town {esc(r.get("city") or "-")}, score {"-" if r.get("headline_score") is None else format(r["headline_score"], "g")} '
                               f'<form method="post" action="{HB}/{hid}/delete-run/{r["id"]}" style="display:inline" data-confirm="{esc("Delete the check of " + uk_time(r["run_at"]) + " for good?", quote=True)}">'
                               f'<input type="hidden" name="csrf" value="{c}"><button class="btn small" type="submit">Delete this check</button></form></li>' for r in runs[:20])
                     + '</ul></div></details>') if runs else "")
                 + f'<h5>People who can sign in ({len(users)})</h5>' + (f'<div class="table-wrap"><table class="table"><thead><tr><th>Email</th><th>Name</th><th>Last sign-in (UK time)</th><th></th><th></th></tr></thead><tbody>{ut}</tbody></table></div>' if users else '<p class="caption">Nobody has a login yet.</p>')
                 + f'<form class="filters" method="post" action="{HB}/{hid}/invite"><input type="hidden" name="csrf" value="{c}"><label class="field"><span>Invite someone (their email)</span><input type="email" name="email" required></label>'
                 '<button class="btn" type="submit">Make an invite link</button></form><p class="caption">There is no email service: you get a link to send them yourself. It works once and expires in 7 days.</p>'
                 + (f'<h6>Links still open</h6><ul>{invites}</ul>' if invites else "") + "</section>")
        view = portal_view.dashboard(sm, acts, runs, editable=False, csrf=c, start=start_here.safe(s, h, sm, acts, runs, False, pst), ai=ai_dash.panel(s, h), settings_url=f"{HB}/{hid}/settings",
                                     prompts_alert=bool(pst["draft"] and not pst["active"]), opps=(_safe(opportunities.build, rep) or []) if rep else [], strategy=(_safe(strategy_view.panel, rep) or "") if rep else "",
                                     **(app.extensions["extra_tabs"](rep, h) if "extra_tabs" in app.extensions else {}),
                                     research_html=(app.extensions["research_html"](h, f"{HB}/{hid}/research") if "research_html" in app.extensions else ""),
                                     live=app.extensions["weekly"].hotel_state(hid), live_url=f"{HB}/{hid}/status")
        import quality_view
        panel += _safe(quality_view.panel, rep, h) or ""
        return sc.shell(grp, h["name"], panel + '<p class="caption">Below is exactly what the hotel sees (read-only here).</p>' + view)

    @bp.post(HB + "/<int:hid>/prompts")
    def hotel_prompts(hid):
        if not sc.authed():
            return {"ok": False, "error": "Please sign in again."}, 401
        if not hmac.compare_digest(request.headers.get("X-CSRF", ""), session.get("csrf", "x")):
            return {"ok": False, "error": "Please reload the page and try again."}, 400
        s, msg = sc.store_or_msg()
        if not s:
            abort(404)
        h = own(s, hid)
        st = prompt_sets.state(s, h)
        payload = request.get_json(silent=True) or {}
        ok, res = prompt_sets.handle(s, h, "the operator", payload, prompt_sets.anchors_from(st["draft"], st["active"]) + [{"name": x} for x in hotel_profile.places(hotel_profile.confirmed(h))])
        if ok and payload.get("action") == "confirm" and "first_check" in app.extensions:
            res = {**res, **app.extensions["first_check"](s, h)}
        return {"ok": ok, **res}, (200 if ok else 400)

    @bp.get(HB + "/<int:hid>/settings")
    def hotel_settings(hid):
        """The hotel's Settings, as the hotel sees them (its profile, prompts and history), editable by the operator."""
        g = sc.guard()
        if g:
            return g
        s, msg = sc.store_or_msg()
        if s is None:
            return sc.shell(sc.groups[0], sc.title(sc.groups[0]), f'<div class="alert warning">{esc(msg)}</div>')
        h = own(s, hid)
        import query_matrix
        p = hotel_profile.load(h)
        prompt_sets.ensure_from_history(s, h)
        pst = prompt_sets.state(s, h)
        runs = s.hotel_runs(h["hotel_key"])
        rep = _latest_report(s, runs)
        have = [x["text"] for st_ in (pst["draft"], pst["active"]) if st_ for x in st_["prompts"]]
        since = sum(1 for r in runs if pst["active"] and r["run_at"] >= pst["active"]["confirmed_at"])
        status = ("Confirmed: " + esc(hotel_profile.last_change(p))) if p and p.get("status") == "confirmed" else ("A draft from the website, not confirmed yet." if p else "Not filled in yet.")
        profile = (f'<section class="panel"><h4>Hotel profile</h4><p class="caption">{status}</p>{hotel_profile.summary_html(p)}'
                   f'<p><a class="btn primary" href="{HB}/{hid}/profile">{"Edit the profile" if p else "Fill in the profile"}</a></p></section>')
        prompts = prompts_view.panel(pst, h, f"{HB}/{hid}/prompts", True, since, (_safe(query_matrix.suggest, rep, have) or []) if rep else [], (_safe(exploration.suggest, s, h, have) or []) if pst["draft"] else [])
        history = f'<p class="caption">Every check of this hotel, newest first.</p>{portal_view.history_table(runs) or "<p class=caption>No checks yet.</p>"}'
        tabs = [("profile", "Hotel profile", profile), ("prompts", "Prompts" + (" (to confirm)" if pst["draft"] and not pst["active"] else ""), prompts), ("history", "History", history)]
        nav = "".join(f'<button type="button" class="tab{" active" if i == 0 else ""}" data-tab="tab-{k}" data-name="{k}">{esc(lbl)}</button>' for i, (k, lbl, _b) in enumerate(tabs))
        panels = "".join(f'<div class="tab-panel{" active" if i == 0 else ""}" id="tab-{k}">{b}</div>' for i, (k, _l, b) in enumerate(tabs))
        body = (f'<div class="pt" data-csrf="{esc(sc.csrf())}"><p><a href="{HB}/{hid}">&larr; Back to the hotel</a></p><p class="caption">The hotel&rsquo;s Settings, as the hotel sees them. You can edit them here on its behalf.</p>'
                f'<div class="tabs top"><div class="tab-bar" role="tablist">{nav}</div>{panels}</div></div>')
        return sc.shell(portal_db.group_of(h), h["name"] + ": settings", body)

    @bp.route(HB + "/<int:hid>/profile", methods=["GET", "POST"])
    def hotel_profile_page(hid):
        g = sc.guard()
        if g:
            return g
        s, msg = sc.store_or_msg()
        if s is None:
            return sc.shell(sc.groups[0], sc.title(sc.groups[0]), f'<div class="alert warning">{esc(msg)}</div>')
        h = own(s, hid)
        old = hotel_profile.load(h)
        W = app.extensions["weekly"]
        if not old and getattr(W.cfg, "database_url", None):
            hotel_profile.start_draft(W.cfg.database_url, hid, W.cfg)
        error = ""
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
                abort(400)
            prof, error = hotel_profile.from_form(request.form, old, "the operator")
            if not error:
                hotel_profile.apply(s, h, prof)
                n = hotel_profile.write_prompts(s, s.get_hotel(hid), prof, W.cfg)
                import strategy_research
                strategy_research.start(W.cfg.database_url, hid, W.cfg)
                return redirect(f"{HB}/{hid}/settings#prompts" if n else f"{HB}/{hid}")
            old = prof
        head = (f'<p><a href="{HB}/{hid}">&larr; Back to the hotel</a></p><p class="caption">The hotel normally fills this in when it first signs in. Saving here confirms it on the hotel&rsquo;s behalf and writes a '
                'recommended set of prompts from it (the hotel&rsquo;s confirmed prompts are not replaced until someone confirms the new set).</p>')
        err = f'<div class="alert warning">{esc(error)}</div>' if error else ""
        return sc.shell(portal_db.group_of(h), h["name"] + ": profile", head + err + hotel_profile.form_html(old or {**hotel_profile.empty(), "town": h.get("city") or ""}, f"{HB}/{hid}/profile", sc.csrf(),
                                                                                                     drafting_now=hotel_profile.drafting(hid) and not old, who="operator"))

    @bp.get(HB + "/<int:hid>/status")
    def hotel_status(hid):
        if not sc.authed():
            return {"ok": False}, 401
        if not main:
            s, _m = sc.store_or_msg()
            if not s:
                abort(404)
            own(s, hid)
        return {"ok": True, **app.extensions["weekly"].hotel_state(hid)}

    @bp.post(LB + "/run-due")
    def run_due():
        bad, s = checked_post()
        if bad:
            return bad
        W = app.extensions["weekly"]
        grp = grp_arg()
        hs = [h for h in W.due(s) if not W.active(h["id"]) and portal_db.group_of(h) == grp]
        if hs:
            W.start(force_ids={h["id"] for h in hs})
        return redirect(sc.list_urls[grp] + "?msg=" + ("started:" + "|".join(h["name"] for h in hs) if hs else "none-due"))

    @bp.post(LB + "/run-all")
    def run_all():
        bad, s = checked_post()
        if bad:
            return bad
        W = app.extensions["weekly"]
        grp = grp_arg()
        hs = [h for h in s.list_hotels(only_active=True, grp=grp) if not W.active(h["id"]) and h.get("setup") != "pending"]
        W.start(force_ids={h["id"] for h in hs})
        return redirect(sc.list_urls[grp] + "?msg=" + ("started:" + "|".join(h["name"] for h in hs) if hs else "busy"))

    @bp.get(HB + "/<int:hid>")
    def hotel_view(hid):
        g = sc.guard()
        if g:
            return g
        s, msg = sc.store_or_msg()
        if s is None:
            return sc.shell(sc.groups[0], sc.title(sc.groups[0]), f'<div class="alert warning">{esc(msg)}</div>')
        return hotel_page(s, hid)

    def link_notice(token, email, what):
        url = request.host_url.rstrip("/") + "/portal/invite/" + token
        return (f'<div class="alert success"><b>{what} for {esc(email)}.</b> Send them this link. It is shown only now, works once, and expires in {accounts.INVITE_DAYS} days.'
                f'<br><code style="word-break:break-all">{esc(url)}</code></div>')

    @bp.post(HB + "/<int:hid>/invite")
    def hotel_invite(hid):
        bad, s = checked_post()
        if bad:
            return bad
        own(s, hid)
        email = accounts.clean_email(request.form.get("email"))
        if not email:
            return hotel_page(s, hid, '<div class="alert warning">Enter a valid email address.</div>')
        tok, h = accounts.new_token()
        s.create_invite(h, email, hid, None, "invite", accounts.INVITE_DAYS)
        return hotel_page(s, hid, link_notice(tok, email, "Invite link made"))

    def user_in_scope(s, hid, uid):
        """The user belongs to this hotel AND every hotel they can see is one this admin manages. The individual-hotels admin must never reset the password of, or switch off,
        someone who also signs in to portfolio hotels."""
        if uid not in {x["id"] for x in s.users_for_hotel(hid)}:
            return False
        return all(portal_db.group_of(h) in sc.groups for h in s.hotels_linked(uid))

    @bp.post(HB + "/<int:hid>/reset/<int:uid>")
    def hotel_reset(hid, uid):
        bad, s = checked_post()
        if bad:
            return bad
        own(s, hid)
        u = s.user_by_id(uid)
        if not u or not user_in_scope(s, hid, uid):
            return hotel_page(s, hid, '<div class="alert warning">This person also signs in to hotels managed from the main admin, so their password can only be reset there.</div>') if u else abort(404)
        tok, h = accounts.new_token()
        s.create_invite(h, u["email"], hid, uid, "reset", accounts.INVITE_DAYS)
        return hotel_page(s, hid, link_notice(tok, u["email"], "Password-reset link made"))

    @bp.post(HB + "/<int:hid>/user/<int:uid>/<state>")
    def hotel_user_state(hid, uid, state):
        bad, s = checked_post()
        if bad:
            return bad
        own(s, hid)
        if user_in_scope(s, hid, uid) and state in ("on", "off"):
            s.set_user_active(uid, state == "on")
        return redirect(f"{HB}/{hid}")

    @bp.post(HB + "/<int:hid>/reset-prompts")
    def hotel_reset_prompts(hid):
        bad, s = checked_post()
        if bad:
            return bad
        h = own(s, hid)
        s.clear_benchmark(h["hotel_key"])                                   # the prompts frozen at the first audit
        for p in s.prompt_sets(hid):
            if p["status"] == "draft":
                s.delete_prompt_set(p["id"])                                # an unconfirmed recommended set built from the old prompts
        has_confirmed = bool(s.confirmed_prompts_for_key(h["hotel_key"]))
        return hotel_page(s, hid, '<div class="alert success"><b>Prompts reset.</b> The next check writes a fresh recommended set from the current question engine, and the hotel is asked to confirm it.'
                                  + (' The hotel has a <i>confirmed</i> set, which is left as it is: the hotel can change it on its Prompts tab.' if has_confirmed else '') + '</div>')

    @bp.post(HB + "/<int:hid>/details")
    def hotel_details(hid):
        bad, s = checked_post()
        if bad:
            return bad
        h = own(s, hid)
        name, city = (" ".join(request.form.get(k, "").split())[:120] for k in ("name", "city"))
        if not (name and city):
            return hotel_page(s, hid, '<div class="alert warning">Enter the hotel&rsquo;s name and its town or city.</div>')
        if urlscope.is_country(city):
            return hotel_page(s, hid, '<div class="alert warning">&ldquo;' + esc(city) + '&rdquo; is a country. Enter the <b>town or city</b> the hotel is in.</div>')
        moved = city != (h["city"] or "")
        s.set_hotel(hid, name=name, city=city)
        msg = '<div class="alert success"><b>Saved.</b>'
        if moved:                                                           # the old town's questions are no use: the next check writes fresh ones for the new town
            s.clear_benchmark(h["hotel_key"])
            for p in s.prompt_sets(hid):
                if p["status"] == "draft":
                    s.delete_prompt_set(p["id"])
            msg += (f' The town is now <b>{esc(city)}</b>. Run a check so the questions are about {esc(city)}; it writes a fresh recommended set of prompts.'
                    + (' The hotel&rsquo;s <i>confirmed</i> prompts still name the old town: change them on the Prompts tab.' if s.confirmed_prompts_for_key(h["hotel_key"]) else ''))
        return hotel_page(s, hid, msg + '</div>')

    @bp.post(HB + "/<int:hid>/delete-run/<int:rid>")
    def hotel_delete_run(hid, rid):
        bad, s = checked_post()
        if bad:
            return bad
        h = own(s, hid)
        if rid not in {r["id"] for r in s.hotel_runs(h["hotel_key"])}:
            abort(404)                                                     # only a check of this hotel
        if app.extensions["weekly"].active(hid):
            return hotel_page(s, hid, '<div class="alert warning">A check is running for this hotel. Delete once it has finished.</div>')
        s.delete_run(rid)
        for a in s.list_actions(hid):                                      # what only that check raised, and the hotel has not acted on
            if a["first_run_id"] == rid and a["last_run_id"] == rid and a["status"] not in ("done", "working") and not (a["note"] or "").strip():
                s.delete_action(a["id"])
        for p in s.prompt_sets(hid):
            if p["status"] == "draft":
                s.delete_prompt_set(p["id"])                               # rebuilt from the checks that remain
        left = s.hotel_runs(h["hotel_key"])
        if not left:
            s.clear_benchmark(h["hotel_key"])
        return hotel_page(s, hid, '<div class="alert success"><b>Check deleted.</b> ' + (f'{len(left)} check{"s" if len(left) != 1 else ""} left for this hotel.' if left else
                                  'This hotel has no checks now: run one to fill its dashboard.') + '</div>')

    @bp.post(HB + "/<int:hid>/research")
    def hotel_research(hid):
        bad, s = checked_post()
        if bad:
            return bad
        own(s, hid)
        import strategy_research
        W = app.extensions["weekly"]
        strategy_research.start(W.cfg.database_url, hid, W.cfg)
        return redirect(f"{HB}/{hid}#actions")

    @bp.post(HB + "/<int:hid>/weekly")
    def hotel_weekly_toggle(hid):
        bad, s = checked_post()
        if bad:
            return bad
        h = own(s, hid)
        s.set_hotel(hid, weekly=0 if h["weekly"] else 1)
        return redirect(f"{HB}/{hid}")

    @bp.post(HB + "/<int:hid>/run")
    def hotel_run_now(hid):
        bad, s = checked_post()
        if bad:
            return bad
        own(s, hid)
        app.extensions["weekly"].start(force_ids={hid})
        return redirect(f"{HB}/{hid}")            # the page shows the check running, live

    app.register_blueprint(bp)
