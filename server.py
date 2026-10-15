"""
The Hotel AI Discoverability Audit as a Flask site (served by Waitress; see wsgi.py).

  /                      the form
  /api/audit             start an audit (a background job); /api/job/<id> to follow it
  /r/<token>             a finished report, for the visitor who ran it (an unguessable link; it is never listed or shown to anyone else)
  /r/<token>/...         the PDFs and the data file
  /api/r/<token>/...     the review-export upload and the comparison with an earlier report
  /admin ...             the operator's pages (password; admin.py)

All the audit logic is the same Python as before; this file is only the web layer. Keys come from environment variables on the host.
"""

import collections
import hashlib
import json
import os
import re
import secrets
import hmac
import threading
import time
import urllib.parse

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

import ai_niche
import audit_service
import compare
import headline
import jobs
import netguard
import report_pdf
import report_view
import review_pack
import store

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_RX = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
MEMORY_KEEP_S = 3 * 3600


class Reports:
    """Where finished reports live. The database when one is configured (so a link keeps working after a restart); always a small in-memory copy too."""

    def __init__(self, database_url=""):
        self.url = database_url or ""
        self.mem = {}                       # token -> (time, report)
        self.ids = {}                       # token -> run id
        self.pdfs = {}                      # (token, part, signature) -> bytes
        self.html = {}                      # token -> (signature, html)
        self.lock = threading.Lock()

    def _db(self):
        if not self.url:
            return None
        import backend
        return backend.open_store(self.url)

    def save(self, report):
        token = secrets.token_urlsafe(24)
        headline.attach(report)
        with self.lock:
            self.mem[token] = (time.time(), report)
        db = None
        try:
            db = self._db()
            if db:
                self.ids[token] = db.save_run(report, token=token)
        except Exception:  # noqa: BLE001 - saving must never break an audit
            self.ids.pop(token, None)
        self._trim()
        return token

    def load(self, token):
        if not token or not TOKEN_RX.match(token):
            return None
        with self.lock:
            hit = self.mem.get(token)
        if hit:
            return hit[1]
        try:
            db = self._db()
            if db:
                rid, rep = db.get_report_by_token(token)
                if rep:
                    with self.lock:
                        self.mem[token] = (time.time(), rep)
                        self.ids[token] = rid
                    return rep
        except Exception:  # noqa: BLE001
            return None
        return None

    def previous(self, token):
        """The hotel's previous audit (summary numbers), for 'since last audit'. None without a database or an earlier run."""
        rid = self.ids.get(token)
        try:
            db = self._db()
            return db.previous_run(rid) if (db and rid) else None
        except Exception:  # noqa: BLE001
            return None

    def update(self, token, report):
        with self.lock:
            self.mem[token] = (time.time(), report)
            self.html.pop(token, None)
        rid = self.ids.get(token)
        try:
            db = self._db()
            if db and rid:
                db.update_run(rid, report)
        except Exception:  # noqa: BLE001
            pass

    def _trim(self):
        now = time.time()
        with self.lock:
            for k in [k for k, (t, _r) in self.mem.items() if now - t > MEMORY_KEEP_S]:
                self.mem.pop(k, None)
                self.html.pop(k, None)
            if len(self.pdfs) > 40:
                self.pdfs.clear()


def signature(report):
    """Changes whenever what a rendered page or PDF would show changes (the audit itself, or a review export applied to it)."""
    return hashlib.sha1(f"{report['meta'].get('run_at')}|{json.dumps(report.get('review_pack'), sort_keys=True, default=str)}".encode()).hexdigest()[:16]


def visitor_id():
    return request.remote_addr or "?"


def valid_website(raw):
    raw = (raw or "").strip()
    if not raw or len(raw) > 300 or any(c in raw for c in "\r\n\t "):
        return None
    cand = raw if "//" in raw else "https://" + raw
    p = urllib.parse.urlparse(cand)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    return raw


def create_app(cfg=None, run_fn=None):
    cfg = cfg or audit_service.Config()
    app = Flask(__name__, template_folder=os.path.join(HERE, "web", "templates"), static_folder=os.path.join(HERE, "web", "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["PERMANENT_SESSION_LIFETIME"] = 30 * 24 * 3600
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER") or os.environ.get("SESSION_COOKIE_SECURE"))
    app.config["SECRET_KEY"] = cfg.secret_key or (hashlib.sha256(((cfg.admin_password or "") + "hotel-audit").encode()).hexdigest() if cfg.admin_password else secrets.token_hex(32))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    store.configure_db(cfg.database_url)
    reports = Reports(cfg.database_url)
    manager = jobs.Manager(run_fn or (lambda params, progress: audit_service.run(params, cfg, progress)), reports.save, workers=2, max_queue=cfg.max_queue, per_hour=cfg.audits_per_hour)
    app.extensions["cfg"], app.extensions["reports"], app.extensions["jobs"] = cfg, reports, manager

    # ---------------------------------------------------------------- site password
    # When SITE_PASSWORD is set the whole site (pages, reports, uploads, admin) needs it first, so that only people who were given it can use the service and spend its free allowances.
    # /healthz stays open for the uptime monitor, and so do the stylesheet and script the sign-in page itself needs. Wrong guesses are slowed and limited.
    failed = collections.defaultdict(list)

    @app.before_request
    def site_gate():
        if not cfg.site_password or session.get("site_ok") is True:
            return None
        if request.path in ("/healthz", "/login") or request.path.startswith("/static/"):
            return None
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="Please sign in first."), 401
        return redirect("/login?next=" + urllib.parse.quote(request.full_path.rstrip("?") if request.method == "GET" else "/", safe="/"))

    @app.route("/login", methods=["GET", "POST"])
    def site_login():
        if not cfg.site_password:
            return redirect("/")
        nxt = request.values.get("next") or "/"
        nxt = nxt if (nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt and not nxt.startswith("/login")) else "/"
        error = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            now = time.time()
            failed[ip] = [t for t in failed[ip] if now - t < 600]
            if len(failed[ip]) >= 6:
                error = "Too many wrong passwords. Please try again in ten minutes."
            elif hmac.compare_digest((request.form.get("password") or "").encode(), cfg.site_password.encode()):
                session.clear()
                session["site_ok"] = True
                session.permanent = True
                return redirect(nxt)
            else:
                failed[ip].append(now)
                time.sleep(1.2)
                error = "That password is not right."
        return render_template("login.html", error=error, nxt=nxt), (429 if error.startswith("Too many") else 200)

    @app.post("/logout")
    def site_logout():
        session.clear()
        return redirect("/login")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                                   "connect-src 'self'; frame-src 'self' about:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if request.path.startswith(("/r/", "/api/", "/admin")):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify(ok=False, error="That file is too large (the limit is 6 MB)."), 413

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        pre = {k: (request.args.get(k) or "").strip()[:300] for k in ("website", "hotel", "city")}
        return render_template("index.html", audiences=[(k, lbl) for k, lbl, *_r in ai_niche.AUDIENCES], saves=bool(cfg.database_url), pre=pre)

    @app.get("/healthz")
    def healthz():
        return "ok", 200, {"Cache-Control": "no-store"}

    @app.post("/api/audit")
    def api_audit():
        d = request.get_json(silent=True) or request.form
        site = valid_website(d.get("website"))
        rows, mapping = None, None
        f = request.files.get("reviews")
        if f and f.filename:
            rows, mapping, err = _read_reviews(f, (d.get("platform") or "").strip()[:30])
            if err:
                return jsonify(ok=False, error=err), 400
        if not site:
            return jsonify(ok=False, error="Enter the hotel's website address, for example brooklandshotelsurrey.com"), 400
        if not netguard.url_ok(site if "//" in site else "https://" + site):
            return jsonify(ok=False, error="That address is not on the public web, so it cannot be audited."), 400
        aud = d.getlist("audiences") if hasattr(d, "getlist") else d.get("audiences") or []
        params = {"website": site, "hotel": (d.get("hotel") or "").strip()[:120], "city": (d.get("city") or "").strip()[:120], "wider": str(d.get("wider", "1")).lower() not in ("0", "false", "off", ""),
                  "tier": (d.get("tier") or None) if (d.get("tier") or "") in audit_service.TIERS else None, "audiences": [a for a in (aud if isinstance(aud, list) else [])][:8]}
        if rows:
            params["review_rows"], params["review_mapping"] = rows, mapping        # held in memory for the job only; dropped when it finishes
        job, why = manager.submit(params, visitor_id())
        if job is None:
            msg = ("The service is busy with other audits. Please try again in a few minutes." if why == "busy"
                   else f"This service runs up to {cfg.audits_per_hour} audits an hour for each visitor. Please try again later.")
            return jsonify(ok=False, error=msg), 429
        return jsonify(ok=True, job=job.id)

    def _read_reviews(f, platform):
        """-> (normalised reviews, column mapping, error) for an uploaded review export."""
        rows, err = review_pack.read_table(f.read(), f.filename or "")
        if err:
            return None, None, err
        mapping = review_pack.map_columns(list(rows[0]))
        if not any(mapping.get(k) for k in ("rating", "text", "reply", "positive", "negative")):
            return None, None, "No rating, review or reply column was recognised in the review file. The columns in it are: " + ", ".join(list(rows[0])[:20]) + "."
        norm = review_pack.normalise(rows, mapping, platform)
        if not norm:
            return None, None, "No reviews could be read from the review file."
        return norm, mapping, ""

    @app.get("/api/job/<job_id>")
    def api_job(job_id):
        job = manager.get(job_id)
        if not job:
            return jsonify(ok=False, error="That audit is no longer available. Please start it again."), 404
        out = job.public()
        out.update(ok=True, position=manager.position(job))
        return jsonify(out)

    def _report_or_404(token):
        rep = reports.load(token)
        if rep is None:
            abort(404)
        return rep

    @app.get("/r/<token>")
    def report_page(token):
        rep = _report_or_404(token)
        sig = signature(rep)
        private = manager.private_for(token)
        hit = reports.html.get(token)
        if hit and hit[0] == sig and not private:
            body = hit[1]
        else:
            body = report_view.render(rep, token=token, prev=reports.previous(token), private=private)
            if not private:
                reports.html[token] = (sig, body)
        meta = rep["meta"]
        loc = meta.get("location") or {}
        chips = [f"Run {meta['run_at'][:16].replace('T', ' ')} UTC", f"Name {meta.get('hotel_name_source', '')}"]
        if loc.get("source"):
            chips.append(("Location " + str(loc["source"])) if str(loc["source"]).startswith(("provided", "inferred")) else ("Location from " + str(loc["source"])))
        if (rep.get("guest_questions") or {}).get("read_via"):
            chips.append("Read through a fallback reader")
        return render_template("report.html", rep=rep, meta=meta, chips=chips, body=body, token=token, saved=bool(cfg.database_url),
                               title=(meta.get("hotel") or meta.get("website") or "Report"))

    @app.get("/r/<token>/<part>.pdf")
    def report_pdf_route(token, part):
        if part not in ("management", "appendix"):
            abort(404)
        rep = _report_or_404(token)
        key = (token, part, signature(rep))
        data = reports.pdfs.get(key)
        if data is None:
            try:
                data = report_pdf.build_pdf(rep, part)
            except Exception:  # noqa: BLE001
                abort(500)
            reports.pdfs[key] = data
        name = report_pdf.filename(rep, part)
        return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/r/<token>/data.json")
    def report_json(token):
        rep = _report_or_404(token)
        name = f"{store.slug(rep['meta'].get('hotel') or rep['meta'].get('website'))}-audit-{str(rep['meta']['run_at'])[:10]}.json"
        return Response(json.dumps(rep, indent=2, default=str), mimetype="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------- uploads
    @app.post("/api/r/<token>/review-pack")
    def api_review_pack(token):
        rep = _report_or_404(token)
        f = request.files.get("file")
        if not f:
            return jsonify(ok=False, error="Choose a file first."), 400
        rows, err = review_pack.read_table(f.read(), f.filename or "")
        if err:
            return jsonify(ok=False, error=err), 400
        mapping = review_pack.map_columns(list(rows[0]))
        if not any(mapping.get(k) for k in ("rating", "text", "reply", "positive", "negative")):
            cols = ", ".join(list(rows[0])[:20])
            return jsonify(ok=False, error="No rating, review or reply column was recognised. The columns in the file are: " + cols + "."), 400
        res = review_pack.analyse(review_pack.normalise(rows, mapping, (request.form.get("platform") or "").strip()[:30]), rep["meta"].get("hotel", ""),
                                  review_pack.site_states_from(rep.get("guest_questions")))
        if not res:
            return jsonify(ok=False, error="No reviews could be read from the file."), 400
        review_pack.apply(rep, res["public"])
        reports.update(token, rep)
        return jsonify(ok=True, html=report_view.pack_html(res, mapping), columns=mapping)

    @app.post("/api/r/<token>/compare")
    def api_compare(token):
        rep = _report_or_404(token)
        f = request.files.get("file")
        if not f:
            return jsonify(ok=False, error="Choose a file first."), 400
        data = f.read(compare.MAX_BYTES + 1)
        if len(data) > compare.MAX_BYTES:
            return jsonify(ok=False, error="That file is too large to be one of this tool's reports."), 400
        try:
            prev = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return jsonify(ok=False, error="That file isn't valid JSON, so it can't be one of this tool's reports."), 400
        try:
            return jsonify(ok=True, html=report_view.comparison_html(compare.compare_reports(prev, rep)))
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    try:
        import admin
        admin.register(app, cfg)
    except ImportError:
        pass
    return app
