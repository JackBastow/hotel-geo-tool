"""
When a step fails, say so. Every check used to swallow its own errors: a failed step left an empty section that looked like "nothing found", and nothing was logged anywhere.
Now a failure is (1) written to the service log with its traceback (Render keeps the log), and (2) recorded in the report being built, so the report gate puts it in the operator's
Quality check panel instead of the hotel reading an empty result as a finding.

    steps.begin()                      # at the start of a check (on the thread that builds the report)
    try: ...
    except Exception as e:
        steps.failed("former names", e)
    rep["step_errors"] = steps.collected()
"""

import logging
import threading
import traceback

log = logging.getLogger("presencepro")
_tl = threading.local()


def setup():
    """Plain timestamped lines on standard output, which Render shows under Logs. Safe to call more than once."""
    root = logging.getLogger()
    if not any(getattr(h, "_presencepro", False) for h in root.handlers):
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        h._presencepro = True
        root.addHandler(h)
        root.setLevel(logging.INFO)


def begin():
    _tl.errors = []


def failed(step, exc, quiet=False):
    """Log a failed step with its traceback and record it for the report being built on this thread. `quiet`: expected now and then (a site that refuses), logged without the traceback."""
    msg = f"{type(exc).__name__}: {exc}"[:300]
    if quiet:
        log.warning("step failed: %s: %s", step, msg)
    else:
        log.error("step failed: %s: %s\n%s", step, msg, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:])
    errs = getattr(_tl, "errors", None)
    if errs is not None and not any(e["step"] == step for e in errs):
        errs.append({"step": step, "error": msg})


def collected():
    return list(getattr(_tl, "errors", None) or [])
