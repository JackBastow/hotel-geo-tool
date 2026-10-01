"""
Local storage: quota tracking and result caching.

Two jobs, both about not wasting the free-tier allowance:

  QUOTA  - Gemini's free tier gives 5,000 grounded search requests per month,
           counted per Google Cloud PROJECT, not per key. One audit uses ~40.
           This tracks usage locally so the app can warn before it hits the
           wall rather than handing the user a 429.

           This is a local estimate, not Google's own counter. If you run the
           scripts outside this app, or share the project with another tool,
           the real number will be higher. Treat it as a floor.

  CACHE  - Re-auditing the same hotel a day later tells you nothing new and
           costs 40 requests. Cached runs are reused inside a window unless
           the user explicitly forces a refresh.
"""

import datetime as dt
import hashlib
import json
import os
import re

APP_DIR = os.path.join(os.path.expanduser("~"), ".hotel_geo_tool")
RUNS_DIR = os.path.join(APP_DIR, "runs")
QUOTA_FILE = os.path.join(APP_DIR, "quota.json")

# Grounding with Google Search is NOT available on the Gemini free tier -
# verified live in Sept 2026: ungrounded calls return 200, while every grounded
# call on a project without billing returns 429, on every model and both API
# transports. The models that used to carry a free daily grounding allowance
# (the 2.5 family) now return "no longer available to new users".
#
# On a BILLING-ENABLED project, Gemini 3.x includes 5,000 search requests a
# month (shared across all 3.x models), then $14 per 1,000.
#
# This counts SEARCHES EXECUTED, not questions asked: Gemini 3 bills per search
# the model decides to run, and one question can trigger several.
INCLUDED_MONTHLY_SEARCHES = 5000

# Old name kept so any external script still importing it keeps working.
FREE_TIER_MONTHLY_SEARCHES = INCLUDED_MONTHLY_SEARCHES


def _ensure():
    os.makedirs(RUNS_DIR, exist_ok=True)


def _month_key(when=None):
    when = when or dt.datetime.now(dt.timezone.utc)
    return when.strftime("%Y-%m")


# ----------------------------------------------------------------- quota

def read_quota():
    _ensure()
    if not os.path.exists(QUOTA_FILE):
        return {"month": _month_key(), "grounded_calls": 0, "audits": 0}
    try:
        with open(QUOTA_FILE) as f:
            q = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"month": _month_key(), "grounded_calls": 0, "audits": 0}
    if q.get("month") != _month_key():
        return {"month": _month_key(), "grounded_calls": 0, "audits": 0}
    return q


def record_usage(grounded_calls, audits=1):
    q = read_quota()
    q["grounded_calls"] = q.get("grounded_calls", 0) + int(grounded_calls)
    q["audits"] = q.get("audits", 0) + int(audits)
    q["month"] = _month_key()
    q["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _ensure()
    with open(QUOTA_FILE, "w") as f:
        json.dump(q, f, indent=2)
    return q


def quota_status(planned_calls=0):
    """Returns (used, remaining, would_exceed)."""
    q = read_quota()
    used = q.get("grounded_calls", 0)
    remaining = max(INCLUDED_MONTHLY_SEARCHES - used, 0)
    return used, remaining, (used + planned_calls) > INCLUDED_MONTHLY_SEARCHES


# ----------------------------------------------------------------- cache

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def run_id(hotel, city):
    h = hashlib.sha1(f"{hotel}|{city}".encode()).hexdigest()[:8]
    return f"{slug(hotel)}-{h}"


def save_run(payload):
    """Final, permanent save - one timestamped file per completed audit."""
    _ensure()
    meta = payload["meta"]
    rid = run_id(meta["hotel"], meta["city"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RUNS_DIR, f"{rid}__{stamp}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    clear_checkpoint(meta["hotel"], meta["city"])
    return path


def checkpoint_path(hotel, city):
    _ensure()
    return os.path.join(RUNS_DIR, f"_checkpoint__{run_id(hotel, city)}.json")


def save_checkpoint(payload):
    """
    In-progress save, overwritten on every query rather than accumulating a
    new file each time. Survives a crash or closed tab; superseded and
    removed once save_run() writes the final result.
    """
    _ensure()
    meta = payload["meta"]
    path = checkpoint_path(meta["hotel"], meta["city"])
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def clear_checkpoint(hotel, city):
    path = checkpoint_path(hotel, city)
    if os.path.exists(path):
        os.remove(path)


def find_checkpoint(hotel, city):
    """Returns the in-progress payload for this hotel, or None."""
    path = checkpoint_path(hotel, city)
    if not os.path.exists(path):
        return None
    try:
        return load_run(path)
    except (json.JSONDecodeError, OSError):
        return None


def list_runs(hotel=None, city=None):
    _ensure()
    prefix = run_id(hotel, city) + "__" if hotel else ""
    out = []
    for name in sorted(os.listdir(RUNS_DIR), reverse=True):
        if not name.endswith(".json") or name.startswith("_checkpoint__"):
            continue
        if prefix and not name.startswith(prefix):
            continue
        out.append(os.path.join(RUNS_DIR, name))
    return out


def load_run(path):
    with open(path) as f:
        return json.load(f)


def recent_run(hotel, city, max_age_days=30):
    """Most recent cached run for this hotel inside the window, or None."""
    for path in list_runs(hotel, city):
        try:
            payload = load_run(path)
        except (json.JSONDecodeError, OSError):
            continue
        ts = payload.get("meta", {}).get("run_at")
        if not ts:
            continue
        try:
            when = dt.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - when).days
        if age <= max_age_days:
            return payload, path, age
    return None


def history(hotel, city, limit=12):
    """
    Trend across past runs - the point of running this monthly.

    Two payload shapes are saved under this hotel: the old AI-visibility-only
    CLI/tab format (a flat "metrics" dict) and the current one-button audit's
    scorecard format ("scorecard" with per-category scores). Both are read so
    older saved runs still show up rather than silently vanishing from the
    trend the day the format changed.
    """
    rows = []
    for path in list_runs(hotel, city)[:limit]:
        try:
            p = load_run(path)
        except (json.JSONDecodeError, OSError):
            continue

        sc = p.get("scorecard")
        if sc is not None:
            cat_scores = {c["key"]: c["score"] for c in sc.get("categories", [])
                         if c.get("assessed")}
            row = {
                "run_at": p.get("meta", {}).get("run_at"),
                "overall_score": sc.get("overall"),
                "coverage_pct": sc.get("coverage_pct"),
                "ai_visibility": cat_scores.get("ai_visibility"),
                "website": cat_scores.get("website"),
                "reviews": cat_scores.get("reviews"),
                "entity": cat_scores.get("entity"),
                "path": path,
            }
            rows.append(row)
            continue

        # legacy shape - the old AI-visibility-only tab/CLI
        m = p.get("metrics", {})
        rows.append({
            "run_at": p.get("meta", {}).get("run_at"),
            "mention_rate": m.get("mention_rate"),
            "top3_rate": m.get("top3_rate"),
            "recommendation_rate": m.get("recommendation_rate"),
            "share_of_voice": m.get("share_of_voice"),
            "first_party_citation_rate": m.get("first_party_citation_rate"),
            "branded_confident_rate": m.get("branded_confident_rate"),
            "path": path,
        })
    return list(reversed(rows))


# ----------------------------------------------------------------- status
#
# A full audit runs 20-45+ minutes. Nobody should have to sit and watch a
# browser tab that whole time. The app starts the audit in a background
# thread inside the same long-lived process (the one run.bat starts), writes
# progress here as it goes, and the UI just reads this file back. Close the
# browser tab, reopen the app later, and the run is either still going or
# finished - as long as the run.bat window itself is still open.

def status_path(hotel, city):
    _ensure()
    return os.path.join(RUNS_DIR, f"_status__{run_id(hotel, city)}.json")


def write_status(hotel, city, **fields):
    _ensure()
    path = status_path(hotel, city)
    data = {"hotel": hotel, "city": city,
            "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    data.update(fields)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)  # atomic - the UI thread never reads a half-written file
    return data


def read_status(hotel, city):
    path = status_path(hotel, city)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_status(hotel, city):
    path = status_path(hotel, city)
    if os.path.exists(path):
        os.remove(path)


def list_active_statuses():
    """
    Every in-progress or just-finished run, disk-based rather than tied to a
    browser session - so a run started in one tab is still visible after
    that tab is closed and the app is reopened later, as long as the
    underlying run.bat window is still running.
    """
    _ensure()
    out = []
    for name in os.listdir(RUNS_DIR):
        if not name.startswith("_status__") or not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, name)) as f:
                out.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    out.sort(key=lambda d: d.get("updated", ""), reverse=True)
    return out
