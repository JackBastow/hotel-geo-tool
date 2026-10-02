"""
Compare this audit with a previous one.

There is no server-side history on purpose: a public app with one shared
folder would let one visitor read another's report. Instead the visitor keeps
their own dated JSON file and uploads it next time. Nothing is stored here.

A previous report is untrusted input - it is whatever file the visitor
uploaded. So this reads only specific fields, checks their types, and never
executes or renders anything from it as markup. Reports from older versions of
this tool (no guest questions, no recommendation codes) still compare, using
what they do have.

Honest about comparability: if the share of the model that was assessed
changed between runs (e.g. a Tavily key was added), the overall scores are
NOT like-for-like, and this says so rather than reporting a misleading
"+12". Categories assessed in both runs still compare fine.
"""

import urllib.parse

# ordering of guest-question states, best first. couldnt_check is not on the
# ladder: no information, so it can neither improve nor decline.
STATE_RANK = {"answered": 4, "partial": 3, "needs_checking": 2, "not_found": 1}
STATE_LABEL = {"answered": "Answered", "partial": "Partly answered",
               "needs_checking": "Needs checking", "not_found": "Not found on pages checked",
               "couldnt_check": "Couldn't check"}

SIGNIFICANT = 5  # points of change before calling a category better or worse
MAX_BYTES = 5_000_000


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _domain(u):
    host = urllib.parse.urlparse(str(u)).netloc.lower()
    if not host:  # a bare 'example.com' has no scheme, so urlparse leaves netloc empty
        host = urllib.parse.urlparse("https://" + str(u)).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def validate(report):
    """Raise ValueError with a plain-English message if this isn't a report we can read."""
    if not isinstance(report, dict):
        raise ValueError("That file isn't an audit report (expected a JSON object).")
    if not isinstance(report.get("scorecard"), dict) or \
            not isinstance(report["scorecard"].get("categories"), list):
        raise ValueError("That file doesn't look like an audit report from this tool "
                         "(no scorecard found).")
    if not isinstance(report.get("meta"), dict):
        raise ValueError("That file doesn't look like an audit report from this tool "
                         "(no details block found).")
    return report


def _cats(report):
    out = {}
    for c in report["scorecard"]["categories"]:
        if isinstance(c, dict) and isinstance(c.get("key"), str):
            out[c["key"]] = {"label": str(c.get("label", c["key"])),
                             "assessed": bool(c.get("assessed")),
                             "score": _num(c.get("score"))}
    return out


def _guest(report):
    out = {}
    g = report.get("guest_questions")
    qs = g.get("questions") if isinstance(g, dict) else None
    for q in qs if isinstance(qs, list) else []:
        if isinstance(q, dict) and isinstance(q.get("id"), str):
            out[q["id"]] = {"short": str(q.get("short", q["id"])),
                            "state": str(q.get("state", ""))}
    return out


def _recs(report):
    """(code or None, action text) for each recommendation."""
    out = []
    recs = report.get("recommendations")
    for r in recs if isinstance(recs, list) else []:
        if isinstance(r, dict) and r.get("action"):
            code = r.get("code")
            out.append((str(code) if code else None, str(r["action"])))
    return out


def _same_rec(a, b):
    """Same recommendation if the codes match, or the wording does (older reports have no codes)."""
    return (a[0] is not None and a[0] == b[0]) or a[1] == b[1]


def _facts(report):
    out = {}
    g = report.get("guest_questions")
    rows = g.get("fact_sheet") if isinstance(g, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("fact") in (
                "Telephone", "Email", "Address", "Check-in time", "Check-out time"):
            out[str(r["fact"])] = str(r.get("value", ""))
    return out


def compare_reports(old, new):
    old, new = validate(old), validate(new)
    res = {"warnings": []}

    old_site = _domain(old["meta"].get("website", ""))
    new_site = _domain(new["meta"].get("website", ""))
    res["same_site"] = bool(old_site) and old_site == new_site
    if not res["same_site"]:
        res["warnings"].append(
            f"These look like different websites ({old_site or '?'} vs {new_site or '?'}), "
            f"so the comparison may not mean much.")
    res["old_date"] = str(old["meta"].get("run_at", ""))[:10]
    res["new_date"] = str(new["meta"].get("run_at", ""))[:10]

    # --- overall, with the comparability caveat
    o_sc, n_sc = old["scorecard"], new["scorecard"]
    ov = {"old": _num(o_sc.get("overall")), "new": _num(n_sc.get("overall")),
          "old_coverage": _num(o_sc.get("coverage_pct")),
          "new_coverage": _num(n_sc.get("coverage_pct"))}
    ov["like_for_like"] = (ov["old_coverage"] is not None
                           and ov["old_coverage"] == ov["new_coverage"])
    if ov["old"] is not None and ov["new"] is not None:
        ov["delta"] = ov["new"] - ov["old"]
    if not ov["like_for_like"]:
        res["warnings"].append(
            "The share of the model that was assessed changed between these runs "
            f"({ov['old_coverage']}% → {ov['new_coverage']}%), so the two overall "
            "scores aren't like-for-like. Compare the categories below instead.")
    res["overall"] = ov

    # --- categories
    oc, nc = _cats(old), _cats(new)
    rows = []
    for key in dict.fromkeys(list(nc) + list(oc)):
        o, n = oc.get(key), nc.get(key)
        label = (n or o)["label"]
        o_ok = bool(o and o["assessed"] and o["score"] is not None)
        n_ok = bool(n and n["assessed"] and n["score"] is not None)
        if o_ok and n_ok:
            d = n["score"] - o["score"]
            status = ("improved" if d >= SIGNIFICANT else
                      "declined" if d <= -SIGNIFICANT else "about the same")
            rows.append({"key": key, "label": label, "old": o["score"], "new": n["score"],
                         "delta": d, "status": status})
        elif n_ok:
            rows.append({"key": key, "label": label, "old": None, "new": n["score"],
                         "delta": None, "status": "newly assessed"})
        elif o_ok:
            rows.append({"key": key, "label": label, "old": o["score"], "new": None,
                         "delta": None, "status": "no longer assessed"})
    res["categories"] = rows

    # --- guest questions
    og, ng = _guest(old), _guest(new)
    grows = []
    for qid in ng:
        n_state = ng[qid]["state"]
        o_state = og.get(qid, {}).get("state")
        if o_state is None:
            status = "not in the earlier report"
        elif o_state == "couldnt_check" or n_state == "couldnt_check":
            status = "can't compare (one run couldn't check)"
        elif STATE_RANK.get(n_state, 0) > STATE_RANK.get(o_state, 0):
            status = "improved"
        elif STATE_RANK.get(n_state, 0) < STATE_RANK.get(o_state, 0):
            status = "declined"
        else:
            status = "same"
        grows.append({"id": qid, "short": ng[qid]["short"],
                      "old": STATE_LABEL.get(o_state, "—") if o_state else "—",
                      "new": STATE_LABEL.get(n_state, n_state), "status": status})
    res["guest"] = grows

    # --- recommendations: resolved / new / still open
    orr, nrr = _recs(old), _recs(new)
    res["recs"] = {
        "resolved": [o[1] for o in orr if not any(_same_rec(o, n) for n in nrr)],
        "new": [n[1] for n in nrr if not any(_same_rec(n, o) for o in orr)],
        "still_open": [n[1] for n in nrr if any(_same_rec(n, o) for o in orr)],
    }

    # --- key facts that changed
    of, nf = _facts(old), _facts(new)
    res["facts"] = [{"fact": k, "old": of.get(k, "—"), "new": nf.get(k, "—")}
                    for k in dict.fromkeys(list(nf) + list(of)) if of.get(k) != nf.get(k)]

    better = (sum(1 for r in rows if r["status"] == "improved")
              + sum(1 for g in grows if g["status"] == "improved")
              + len(res["recs"]["resolved"]))
    worse = (sum(1 for r in rows if r["status"] == "declined")
             + sum(1 for g in grows if g["status"] == "declined")
             + len(res["recs"]["new"]))
    res["headline"] = {"improved": better, "declined": worse}
    return res
