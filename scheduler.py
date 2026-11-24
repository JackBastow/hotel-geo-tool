"""
The weekly check of every registered hotel.

The web host (a free Render instance) sleeps when nobody visits and has no scheduler of its own, so something outside wakes it: a scheduled GitHub Actions job (.github/workflows/weekly-checks.yml) calls
POST /internal/weekly with a secret token (the CRON_TOKEN environment variable), then polls GET /internal/weekly/status, which also keeps the instance awake until the checks finish.

What a weekly check is: exactly the same audit a person would run from the form, for the hotel's saved website, name, city, tier and audiences, with the hotel's frozen benchmark prompts. The result is saved like
any other run (so it appears in the hotel's history), and the hotel's action list is updated from it (progress.sync). Hotels run one at a time, so a busy week cannot exhaust the month's allowances; the
audit's own free-tier guards still apply, and a hotel that fails is retried at most every 12 hours.

A hotel is DUE when weekly checks are on, it is active, and its latest saved audit (from any source) is at least 6 days old.
"""

import datetime as dt
import hmac
import threading
import time

from flask import jsonify, request

import backend
import portal_db
import progress

KEEPALIVE_S = 240          # while checks run, the site visits its own address this often, so the free host (which sleeps after ~15 minutes without a visit) does not stop a check half way
DUE_DAYS = 6.0
RETRY_HOURS = 12.0


def _parse(iso):
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def interrupted(h, last_run, now):
    """A check that was started (last_attempt) less than a day ago, has no saved result since, and recorded no error: the process stopped under it."""
    tried = _parse(h.get("last_attempt")) if h.get("last_attempt") else None
    if not tried or h.get("last_error") or (now - tried).total_seconds() > 86400:
        return False
    return last_run is None or last_run < tried


class Weekly:
    def __init__(self, cfg, reports, run_fn):
        """run_fn(params, progress) -> a finished report; reports.save(report) -> token."""
        self.cfg, self.reports, self.run_fn = cfg, reports, run_fn
        self.lock = threading.Lock()
        self.running = False
        self.current = ""
        self.queue = []
        self.done = []
        self.started = None
        self.live = {}                  # hotel id -> {"state": queued|running|done|error, "messages": [...], "started", "finished", "error", "manual"}: what the admin and hotel pages show while a check runs
        self.resumed = set()            # hotels whose cut-off check is being run again: marked, so a check that itself brings the service down is not retried at every restart
        self.manual = set()             # hotels asked for by a person (a button or a new account): these get the thorough test; the Monday batch gets the lighter one

    def _db(self):
        return backend.open_store(self.cfg.database_url) if self.cfg.database_url else None

    def due(self, db=None, now=None, force_ids=None):
        db = db or self._db()
        now = now or dt.datetime.now(dt.timezone.utc)
        out = []
        hotels = db.list_hotels(only_active=True) if db else []
        try:
            light = db.runs_light([h["hotel_key"] for h in hotels]) if hasattr(db, "runs_light") else None      # every hotel's checks in one query
        except Exception:  # noqa: BLE001
            light = None
        for h in hotels:
            if force_ids is not None:
                if h["id"] in force_ids:
                    out.append(h)
                continue
            if not h["weekly"] or h.get("setup") == "pending":
                continue                       # a new hotel is not checked until its profile and prompts are confirmed (confirming the prompts starts its first check)
            hist = list(reversed(light.get(h["hotel_key"], []))) if light is not None else db.hotel_runs(h["hotel_key"])
            last = _parse(hist[0]["run_at"]) if hist else None
            tried = _parse(h["last_attempt"]) if h["last_attempt"] else None
            if interrupted(h, last, now):
                out.append(h)                  # started, never finished, never failed: the service restarted under it (a deploy); it is run again rather than waiting a week
                self.resumed.add(h["id"])
                continue
            if last and (now - last).total_seconds() < DUE_DAYS * 86400:
                continue
            if tried and (now - tried).total_seconds() < RETRY_HOURS * 3600:
                continue
            out.append(h)
        return out

    def active(self, hotel_id):
        s = (self.live.get(hotel_id) or {}).get("state")
        return s in ("queued", "running")

    def start(self, force_ids=None):
        """
        Begin checks in the background. -> (started, how many hotels were added). A hotel asked for by name (force_ids) joins the queue even while a batch is running, unless it is already queued or running;
        with no ids it queues every hotel that is due.
        """
        candidates = self.due(force_ids=force_ids)              # the database work happens before taking the lock the dashboards also need
        with self.lock:
            hotels = [h for h in candidates if not self.active(h["id"])]
            if not hotels:
                return True, 0
            for h in hotels:
                self.live[h["id"]] = {"state": "queued", "messages": ["Waiting for its turn..."], "started": time.time(), "finished": None, "error": "", "manual": force_ids is not None}
                if force_ids is not None:
                    self.manual.add(h["id"])
            if self.running:
                self.queue += [h["id"] for h in hotels]
                return True, len(hotels)
            self.running, self.queue, self.done, self.started, self.current = True, [h["id"] for h in hotels], [], time.time(), ""
        threading.Thread(target=self._loop, name="weekly", daemon=True).start()
        threading.Thread(target=self._keepalive, name="keepalive", daemon=True).start()
        return True, len(hotels)

    def _keepalive(self):
        """Visit our own public address now and then while any check is queued or running. Render sets RENDER_EXTERNAL_URL; without it (local use) nothing is done."""
        import os
        base = (os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
        while base:
            time.sleep(KEEPALIVE_S)
            with self.lock:
                if not self.running:
                    return
            try:
                import requests
                requests.get(base + "/healthz", timeout=15)
            except Exception:  # noqa: BLE001 - a missed ping is harmless
                pass

    def hotel_state(self, hotel_id):
        """What to show for one hotel's check: {"state": idle|queued|running|done|error, "messages": [last few], "elapsed", "error"}."""
        with self.lock:
            s = self.live.get(hotel_id)
            if not s:
                return {"state": "idle", "messages": [], "elapsed": 0, "error": ""}
            return {"state": s["state"], "messages": list(s["messages"][-8:]), "elapsed": round((s["finished"] or time.time()) - s["started"]), "error": s["error"]}

    def params_for(self, h, manual=False, db=None):
        # deep while the hotel has no deep check on record (its baseline: the first check, or the next one after a deep check was deleted); the weekly depth (standard) otherwise
        depth = getattr(self.cfg, "weekly_ai_depth", "standard")
        try:
            db = db or self._db()
            if db is not None and not any(r.get("ai_depth") == "deep" for r in db.hotel_runs(h["hotel_key"])):
                depth = "deep"
        except Exception:  # noqa: BLE001
            pass
        import hotel_profile
        return {"website": h["website"], "hotel": h["name"], "city": h["city"], "wider": True, "tier": h["tier"] or None,
                "audiences": [a for a in (h["audiences"] or "").split(",") if a], "depth": depth, "profile": hotel_profile.confirmed(h)}

    def check_one(self, hotel_id):
        """Run one hotel's audit now and save it. -> {"hotel", "ok", "token" or "error"}. Never raises."""
        db = self._db()
        h = db.get_hotel(hotel_id)
        res = {"hotel": h["name"] if h else str(hotel_id), "ok": False}
        if not h:
            res["error"] = "unknown hotel"
            return res
        import progress
        progress.rekey_all(db)                          # a hotel whose own section of a brand site is now recognised keeps its history under its new key
        h = db.get_hotel(hotel_id) or h
        if hotel_id in self.resumed:
            self.resumed.discard(hotel_id)
            # a second cut-off of the same check then counts as a failure (12-hour retry), never a loop of restarts
            db.set_hotel(hotel_id, last_attempt=portal_db.now_iso(), last_error="The previous check was cut off by a restart; this is the second attempt.")
        else:
            db.set_hotel(hotel_id, last_attempt=portal_db.now_iso())
        with self.lock:
            st = self.live.setdefault(hotel_id, {"state": "running", "messages": [], "started": time.time(), "finished": None, "error": "", "manual": False})
            st.update(state="running", started=st["started"] or time.time())
            st["messages"] = ["Starting the check..."]
            manual = hotel_id in self.manual
            self.manual.discard(hotel_id)

        def progress(msg):
            with self.lock:
                st["messages"].append(str(msg)[:200])
                del st["messages"][:-30]
        try:
            rep = self.run_fn(self.params_for(h, manual, db), progress)
            res["token"] = self.reports.save(rep)
            res["ok"] = True
            db.set_hotel(hotel_id, last_error="")
        except Exception as e:  # noqa: BLE001 - one hotel failing must not stop the others
            res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            db.set_hotel(hotel_id, last_error=res["error"])
        with self.lock:
            st.update(state="done" if res["ok"] else "error", finished=time.time(), error=res.get("error", ""))
            st["messages"].append("Finished." if res["ok"] else "The check did not finish: " + res.get("error", ""))
        return res

    def _loop(self):
        try:
            while True:
                with self.lock:
                    if not self.queue:
                        break
                    hid = self.queue.pop(0)
                    self.current = str(hid)
                r = self.check_one(hid)
                with self.lock:
                    self.done.append(r)
        finally:
            with self.lock:
                self.running, self.current = False, ""

    def status(self):
        with self.lock:
            return {"running": self.running, "current": self.current, "remaining": len(self.queue), "done": list(self.done), "elapsed": round(time.time() - self.started) if self.started else 0}


def resume_soon(weekly, delay_s=60):
    """A restart (every deploy) stops checks half way and empties the queue, which lived only in memory. A minute after the service starts, whatever is due, a cut-off check included,
    is started again, so nothing waits for the next scheduled run."""
    def go():
        time.sleep(delay_s)
        try:
            started, n = weekly.start()
            if n:
                import steps
                steps.log.info("resumed %s due hotel check(s) after the service started", n)
        except Exception as e:  # noqa: BLE001
            import steps
            steps.failed("resuming due checks after a restart", e, quiet=True)
    threading.Thread(target=go, name="weekly-resume", daemon=True).start()


def register(app, cfg, weekly):
    token = getattr(cfg, "cron_token", None)
    import os
    if getattr(cfg, "database_url", None) and os.environ.get("RENDER"):          # the live service only (a test or a local copy never starts checks by itself)
        resume_soon(weekly)

    def allowed():
        got = (request.headers.get("Authorization") or "")
        got = got[7:] if got.lower().startswith("bearer ") else ""
        return bool(token) and hmac.compare_digest(got.encode(), token.encode())

    @app.post("/internal/weekly")
    def internal_weekly():
        if not allowed():
            return jsonify(ok=False, error="not found"), 404
        started, n = weekly.start()
        return jsonify(ok=True, started=started, hotels=n, status=weekly.status()), 202

    @app.get("/internal/weekly/status")
    def internal_weekly_status():
        if not allowed():
            return jsonify(ok=False, error="not found"), 404
        return jsonify(ok=True, **weekly.status())
