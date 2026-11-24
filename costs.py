"""
What the AI calls really cost (code review, Nov 2026). Spend used to be added up from the parts of a finished check that reported a cost, which left out about 15% (the gap analysis,
forums, Reddit, the AI page reading, the question writer) and anything spent by a check that then failed. Now every Claude answer is metered where it is received: ai_sample._make_client
returns a client whose answers are priced from the tokens and searches the API reports, and the total is added to the month's spend (store.record_usage, service 'claude', in thousandths
of a dollar) a little at a time.

    costs.metered(client)            # what ai_sample._make_client returns
    costs.flush()                    # at the end of a check (also done every 5 cents or 60 seconds)
    costs.report_usd(rep)            # a check's AI cost as recorded in its report (shown per check in the admin)
"""

import threading
import time

_lock = threading.Lock()
_pending = {"milli": 0.0, "since": time.time()}
FLUSH_MILLI = 50          # record at least every 5 cents...
FLUSH_S = 60              # ...or every minute


def add(usd, service="claude"):
    """Add one call's cost; recorded to the month's spend in small batches."""
    if not usd or usd <= 0:
        return
    with _lock:
        _pending["milli"] += usd * 1000
        due = _pending["milli"] >= FLUSH_MILLI or time.time() - _pending["since"] >= FLUSH_S
    if due:
        flush(service)


def flush(service="claude"):
    with _lock:
        milli = _pending["milli"]
        _pending["milli"], _pending["since"] = 0.0, time.time()
    if milli >= 0.5:
        try:
            import store
            store.record_usage(max(1, round(milli)), audits=0, service=service)
        except Exception:  # noqa: BLE001 - never fail a call because its cost could not be written
            with _lock:
                _pending["milli"] += milli


class _Messages:
    def __init__(self, messages):
        self._m = messages

    def create(self, **kw):
        r = self._m.create(**kw)
        try:
            import ai_sample
            _a, _d, searches, tin, tout = ai_sample.parse_response(r)
            add(ai_sample.cost_usd(kw.get("model") or "", tin, tout, searches))
        except Exception:  # noqa: BLE001
            pass
        return r

    def __getattr__(self, name):
        return getattr(self._m, name)


class Metered:
    """A Claude client whose every answer is priced and added to the month's spend. Everything else is the real client."""

    def __init__(self, client):
        self._c = client
        self.messages = _Messages(client.messages)

    def __getattr__(self, name):
        return getattr(self._c, name)


def metered(client):
    return client if isinstance(client, Metered) else Metered(client)


SECTIONS = (("ai_sample",), ("review_snapshot",), ("ai_insights",), ("ai_gap",), ("forums",), ("listing_lookup",), ("reddit",), ("question_plan",),
            ("guest_questions", "ai_extract"))


def report_usd(rep):
    """A check's AI cost from its report: every part that reports one (the page reader's cost included)."""
    rep = rep or {}
    total = 0.0
    for path in SECTIONS:
        o = rep
        for k in path:
            o = o.get(k) if isinstance(o, dict) else None
        if isinstance(o, dict):
            try:
                total += float(o.get("cost_usd") or 0)
            except (TypeError, ValueError):
                pass
    try:
        total += float((rep.get("guest_questions") or {}).get("reader_cost_usd") or 0)
    except (TypeError, ValueError):
        pass
    return round(total, 5)
