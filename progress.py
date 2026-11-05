"""
Progress for a hotel over time: its action list, kept up to date from every audit, and the numbers that show what has changed.

The action list
  Every recommendation of every audit of the hotel becomes an ACTION (matched to the same action from earlier audits by what it is about, not by its number, which changes). A hotel user can mark an
  action to do / working on it / done / not relevant. After each new audit:
    - a recommendation seen before is updated (and an action marked done that is STILL flagged is shown as "still flagged in the latest check", not quietly accepted);
    - an action no longer flagged is marked fixed: "checked and fixed" when the thing is read from the hotel's own site, or only "not flagged this time" when it came from sampled AI answers or open
      forums (those vary from week to week, so their absence is not proof);
    - a recommendation not seen before is added as a new action.
  An audit that read too little of the site to judge changes nothing (it never marks things fixed because the crawler failed).

The numbers
  Readiness score first audit -> latest, actions completed (marked done and not still flagged, or checked and fixed), in progress, still to do, and the AI coverage first -> latest with its likely range.
  These show PROGRESS. They do not prove that the actions caused the score to move, and the screens say so.
"""

import difflib
import json
import re

import portal_db

NOISY_SOURCES = {"ai", "ai_gap", "direct", "reddit", "forums", "competitors"}      # sampled or open-web evidence: absence from one run is not proof of a fix
FUZZY = 0.78
MIN_PAGES = 2


def _words(title):
    t = re.sub(r"https?://\S+|/\S*|\d+|[^a-z\s]", " ", (title or "").lower())
    return " ".join(t.split()[:8])


def action_key(rec):
    return f"{rec.get('source', '')}|{rec.get('tag') or ''}|{_words(rec.get('title'))}"


def _snapshot(rec):
    keep = ("id", "title", "why", "action", "priority", "effort", "team", "kind", "source", "category", "confidence_label", "confidence", "evidence", "example", "short_title", "finding", "success_check", "expected_outcome")
    return json.dumps({k: rec.get(k) for k in keep if rec.get(k) is not None}, default=str)[:20000]


def _readable(report):
    """Did this audit read enough of the site to say that something is no longer wrong?"""
    cons = (report or {}).get("consultant") or {}
    if not cons or "recommendations" not in cons:
        return False
    pages = (cons.get("coverage") or {}).get("pages_read")
    return pages is None or pages >= MIN_PAGES


def sync(db, hotel, report, run_id):
    """Bring the hotel's action list up to date from a newly saved audit. -> {"new", "fixed", "reopened", "skipped"}. Never raises into the audit."""
    out = {"new": 0, "fixed": 0, "reopened": 0, "skipped": False}
    if not _readable(report):
        out["skipped"] = True
        return out
    when = (report.get("meta") or {}).get("run_at") or portal_db.now_iso()
    recs = (report.get("consultant") or {}).get("recommendations") or []
    existing = db.list_actions(hotel["id"])
    free = {a["id"]: a for a in existing}
    seen = set()
    for rec in recs:
        key = action_key(rec)
        a = next((x for x in free.values() if x["akey"] == key), None)
        if a is None:
            best, score = None, 0.0
            for x in free.values():
                if x["source"] != rec.get("source"):
                    continue
                r = difflib.SequenceMatcher(None, _words(x["title"]), _words(rec.get("title"))).ratio()
                if r > score:
                    best, score = x, r
            a = best if score >= FUZZY else None
        base = {"title": rec.get("title", ""), "source": rec.get("source", ""), "category": rec.get("category", ""), "priority": rec.get("priority", ""), "effort": rec.get("effort", ""),
                "team": rec.get("team", ""), "kind": rec.get("kind", ""), "rec_json": _snapshot(rec), "last_run_id": run_id, "last_seen": when}
        if a is None:
            db.insert_action(hotel["id"], {**base, "akey": key, "status": "todo", "state": "open", "first_run_id": run_id, "first_seen": when, "updated": when, "reopened": 0, "resolution": "", "note": ""})
            out["new"] += 1
            continue
        free.pop(a["id"], None)
        seen.add(a["id"])
        extra = {}
        if a["state"] == "resolved":
            extra.update(state="open", resolved_at="", resolution="", reopened=(a["reopened"] or 0) + 1)
            out["reopened"] += 1
        if a["status"] == "done" and (a["done_at"] or "") <= portal_db.now_iso() and not extra:
            extra["reopened"] = max(1, a["reopened"] or 0)            # marked done earlier and flagged again: say so
        db.update_action(a["id"], akey=key, **base, **extra)
    for a in free.values():                                            # not flagged this time
        if a["state"] == "open":
            db.update_action(a["id"], state="resolved", resolved_at=when, resolution=("not_flagged" if a["source"] in NOISY_SOURCES else "verified"), last_run_id=run_id)
            out["fixed"] += 1
    return out


def set_status(db, hotel_id, action_id, status, who="", note=None):
    """A hotel user's choice for one action. -> the updated action, or None when it is not this hotel's."""
    a = db.get_action(action_id)
    if not a or a["hotel_id"] != hotel_id or status not in ("todo", "working", "done", "not_relevant"):
        return None
    now = portal_db.now_iso()
    fields = {"status": status, "updated": now, "done_by": who}
    if status == "done":
        fields.update(done_at=now, reopened=0)
    else:
        fields["done_at"] = ""
    if note is not None:
        fields["note"] = note[:500]
    db.update_action(action_id, **fields)
    return db.get_action(action_id)


def classify(a):
    """Where an action sits for display: 'completed', 'working', 'todo', 'cleared' (not flagged this time, but only sampled evidence), 'not_relevant'."""
    fixed = a["state"] == "resolved"
    if a["status"] == "not_relevant":
        return "not_relevant"
    if fixed:
        return "completed" if (a["resolution"] == "verified" or a["status"] == "done") else "cleared"       # sampled evidence that is merely absent this time is not counted as a fix
    if a["status"] == "done" and not a["reopened"]:
        return "completed"
    if a["status"] == "working":
        return "working"
    return "todo"


def action_counts(actions):
    c = {"completed": 0, "verified": 0, "working": 0, "todo": 0, "cleared": 0, "not_relevant": 0, "still_flagged": 0, "total": 0}
    for a in actions:
        k = classify(a)
        c[k] += 1
        if k != "not_relevant":
            c["total"] += 1
        if k == "completed" and a["state"] == "resolved" and a["resolution"] == "verified":
            c["verified"] += 1
        if a["status"] == "done" and a["state"] == "open" and a["reopened"]:
            c["still_flagged"] += 1
    return c


def _cov(row):
    named = (row.get("ai_generic_named") or 0) + (row.get("ai_niche_named") or 0)
    asked = (row.get("ai_generic_asked") or 0) + (row.get("ai_niche_asked") or 0)
    return (named, asked) if asked else None


def completion_date(a):
    """When an action counts as completed: the check that found it fixed, or the day the hotel marked it done (and it is not flagged again). None when it is not completed."""
    if classify(a) != "completed":
        return None
    return (a["resolved_at"] if a["state"] == "resolved" else a["done_at"]) or a["done_at"] or a["resolved_at"] or None


def completed_series(actions, dates):
    """Actions completed so far at each date: [{"run_at", "score"}] (score is the count, so the same chart code draws it)."""
    done = sorted(d for d in (completion_date(a) for a in actions) if d)
    return [{"run_at": d, "score": sum(1 for x in done if x <= d)} for d in dates]


def hotel_summary(db, hotel, hist=None, actions=None):
    """Everything the dashboard and the portfolio need for one hotel. `hist` and `actions` can be passed in when they were already fetched for many hotels at once."""
    hist = list(hist) if hist is not None else [r for r in db.history(hotel["hotel_key"])]
    scored = [r for r in hist if r.get("headline_score") is not None]
    actions = actions if actions is not None else db.list_actions(hotel["id"])
    counts = action_counts(actions)
    first, last = (scored[0], scored[-1]) if scored else (None, None)
    delta = round(last["headline_score"] - first["headline_score"], 1) if first and last and first is not last else None
    cov0, cov1 = (_cov(first) if first else None), (_cov(last) if last else None)
    return {"hotel": hotel, "runs": len(hist), "first_run_at": first["run_at"] if first else None, "last_run_at": hist[-1]["run_at"] if hist else None,
            "first_score": first["headline_score"] if first else None, "latest_score": last["headline_score"] if last else None, "delta": delta,
            "points": [{"run_at": r["run_at"], "score": r["headline_score"], "id": r["id"]} for r in scored], "cov_first": cov0, "cov_latest": cov1, "actions": counts,
            "latest_run_id": hist[-1]["id"] if hist else None, "completed_points": completed_series(actions, [r["run_at"] for r in scored])}


def portfolio_data(db):
    """Everything the portfolio page needs, fetched in three queries however many hotels there are: {"hotels", "hist", "actions"}."""
    hotels = db.list_hotels(only_active=True)
    return {"hotels": hotels, "hist": db.runs_light([h["hotel_key"] for h in hotels]), "actions": db.actions_for_hotels([h["id"] for h in hotels])}


def portfolio_summary(db, data=None):
    data = data or portfolio_data(db)
    rows = [hotel_summary(db, h, data["hist"].get(h["hotel_key"], []), data["actions"].get(h["id"], [])) for h in data["hotels"]]
    with_change = [r for r in rows if r["delta"] is not None]
    tot = {"hotels": len(rows), "completed": sum(r["actions"]["completed"] for r in rows), "verified": sum(r["actions"]["verified"] for r in rows), "working": sum(r["actions"]["working"] for r in rows),
           "todo": sum(r["actions"]["todo"] for r in rows), "improved": sum(1 for r in with_change if r["delta"] > 0), "measured": len(with_change),
           "avg_first": round(sum(r["first_score"] for r in with_change) / len(with_change), 1) if with_change else None,
           "avg_latest": round(sum(r["latest_score"] for r in with_change) / len(with_change), 1) if with_change else None}
    return rows, tot


def portfolio_series(db, data=None):
    """The portfolio over time, one point per week that had a check: the average readiness score (each hotel's latest score as of that week) and the actions completed across all hotels so far."""
    import datetime as dt
    data = data or portfolio_data(db)
    hotels = data["hotels"]
    hist = {h["id"]: [r for r in data["hist"].get(h["hotel_key"], []) if r.get("headline_score") is not None] for h in hotels}
    allruns = sorted(r["run_at"] for rows in hist.values() for r in rows)
    if not allruns:
        return [], []
    def week_end(iso):
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
        return (d + dt.timedelta(days=6 - d.weekday())).isoformat() + "T23:59:59+00:00"
    ends = sorted({week_end(x) for x in allruns})
    actions = [a for h in hotels for a in data["actions"].get(h["id"], [])]
    avg = []
    for e in ends:
        latest = [max((r for r in rows if r["run_at"] <= e), key=lambda r: r["run_at"])["headline_score"] for rows in hist.values() if any(r["run_at"] <= e for r in rows)]
        avg.append({"run_at": e, "score": round(sum(latest) / len(latest), 1)})
    return avg, completed_series(actions, ends)


def ensure_actions(db, hotel):
    """
    A hotel added AFTER some audits of its website were saved has runs but no action list (the list is built when an audit is saved). When there are no actions yet and the hotel has saved runs, build the list
    from the newest run that can be read, so the dashboard shows its recommendations straight away. Returns the number of actions created. Never raises.
    """
    try:
        if db.list_actions(hotel["id"]):
            return 0
        for r in db.hotel_runs(hotel["hotel_key"]):
            rep = db.get_report(r["id"])
            if rep and _readable(rep):
                return sync(db, hotel, rep, r["id"])["new"]
    except Exception:  # noqa: BLE001 - the dashboard still shows
        return 0
    return 0


def actions_for(db, hotel):
    """The hotel's actions (built from its saved audits first when it has none yet), fetched once so a page does not ask again."""
    acts = db.list_actions(hotel["id"])
    if not acts and ensure_actions(db, hotel):
        acts = db.list_actions(hotel["id"])
    return acts


def on_run_saved(db, report, run_id):
    """Called after any audit is saved: when the audited website belongs to a registered hotel, update that hotel's actions. Never raises."""
    try:
        import backend
        hotel = db.hotel_by_key(backend.hotel_key(report))
        if hotel and hotel["active"]:
            return sync(db, hotel, report, run_id)
    except Exception:  # noqa: BLE001 - progress tracking must never break an audit
        return None
    return None
