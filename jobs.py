"""
Background audits. An audit takes minutes, longer than a web request may last, so the page starts a job and polls it.

State is in memory (a job lives for an hour after it finishes), and the finished report is handed to a callback that stores it (the database, or memory when none is set up). A host that
restarts loses only jobs in flight; a finished report is already stored. Two audits run at a time; others wait their turn, up to a limit, so one busy afternoon cannot exhaust memory
or the month's free allowances.
"""

import collections
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

KEEP_FINISHED_S = 3600
KEEPALIVE_S = 240
MAX_MESSAGES = 60


class Job:
    def __init__(self, params):
        self.id = secrets.token_urlsafe(16)
        self.params = params
        self.status = "queued"          # queued | running | done | error
        self.messages = []
        self.token = None               # the visitor's link to the finished report
        self.error = ""
        self.created = time.time()
        self.started = None
        self.finished = None

    def public(self):
        return {"status": self.status, "messages": self.messages[-MAX_MESSAGES:], "token": self.token, "error": self.error,
                "elapsed": round((self.finished or time.time()) - (self.started or self.created))}


class Manager:
    def __init__(self, run_fn, store_fn, workers=2, max_queue=6, per_hour=4):
        """run_fn(params, progress) -> report. store_fn(report) -> token."""
        self.run_fn, self.store_fn = run_fn, store_fn
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audit")
        self.max_queue, self.per_hour = max_queue, per_hour
        self.jobs = {}
        self.private = {}                # report token -> (time, data): the hotel's own review text from an upload at the start. Memory only, never stored, gone after an hour.
        self.by_visitor = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()
        self.awake = False               # a thread visiting our own address while audits run

    def _keepalive(self):
        """While any audit is queued or running, visit our own public address every few minutes, so the free host (which sleeps after ~15 minutes without a visit) does not stop an audit
        half way when nobody has the page open. Render sets RENDER_EXTERNAL_URL; without it (local use) nothing is done."""
        import os
        base = (os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
        try:
            while base:
                time.sleep(KEEPALIVE_S)
                with self.lock:
                    if not any(j.status in ("queued", "running") for j in self.jobs.values()):
                        return
                try:
                    import requests
                    requests.get(base + "/healthz", timeout=15)
                except Exception:  # noqa: BLE001 - a missed visit is harmless
                    pass
        finally:
            with self.lock:
                self.awake = False

    def _purge(self):
        now = time.time()
        for k in [k for k, j in self.jobs.items() if j.finished and now - j.finished > KEEP_FINISHED_S]:
            self.jobs.pop(k, None)
        for k in [k for k, (t, _d) in self.private.items() if now - t > KEEP_FINISHED_S]:
            self.private.pop(k, None)
        for dq in self.by_visitor.values():
            while dq and now - dq[0] > 3600:
                dq.popleft()

    def submit(self, params, visitor="?"):
        """-> (job or None, reason). Refuses when this visitor has had their share this hour, or when too many audits are waiting."""
        with self.lock:
            self._purge()
            waiting = sum(1 for j in self.jobs.values() if j.status in ("queued", "running"))
            if waiting >= self.max_queue:
                return None, "busy"
            dq = self.by_visitor[visitor]
            if len(dq) >= self.per_hour:
                return None, "limit"
            dq.append(time.time())
            job = Job(params)
            self.jobs[job.id] = job
        self.pool.submit(self._work, job)
        with self.lock:
            start = not self.awake
            self.awake = True
        if start:
            threading.Thread(target=self._keepalive, name="audit-keepalive", daemon=True).start()
        return job, ""

    def _work(self, job):
        job.status, job.started = "running", time.time()
        job.messages.append("Starting the audit...")
        try:
            report = self.run_fn(job.params, lambda m: job.messages.append(str(m)[:200]))
            private = report.pop("_review_private", None) if isinstance(report, dict) else None
            job.token = self.store_fn(report)
            if private:
                self.private[job.token] = (time.time(), private)
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - show the real reason, never a stack trace
            job.status, job.error = "error", f"{type(e).__name__}: {e}"[:300]
            import steps
            steps.failed("audit job", e)
        job.params.pop("review_rows", None)       # the review text is not kept once the audit has used it
        job.finished = time.time()

    def private_for(self, token):
        """The private review results for this report, while they are still held (an hour), else None."""
        hit = self.private.get(token)
        return hit[1] if hit and time.time() - hit[0] <= KEEP_FINISHED_S else None

    def get(self, job_id):
        return self.jobs.get(job_id)

    def position(self, job):
        if job.status != "queued":
            return 0
        return 1 + sum(1 for j in self.jobs.values() if j.status == "queued" and j.created < job.created)
