"""
Is this report fit to go to the hotel? One of three answers, decided from what the report's own validation (report_gate) found, stored in report['release'] and in the runs table (release_state).

  ready    nothing in the validation puts a core finding in doubt: the hotel may see it.
  review   the report is usable but a person should look first (a step failed, less than half the site was read, a count disagrees, answers that only named the hotel's group): the hotel does not see it
           until an admin has looked and approved exactly those reasons. A later check with a different reason is not covered by an earlier approval.
  blocked  a core finding is unreliable and approving it would not fix it: the validation itself did not complete, the website was not read or may not be the hotel's, the hotel's name could not be
           resolved, the hotel appears among its own rivals, answers contain the hotel's name but were not counted. Never shown to the hotel. The fix is to recalculate or re-run it.

report_gate repairs what it safely can (downgrades, removes, annotates). This module decides what is still not safe to hand over. It reads the report and nothing else: no network, no cost.
A report with no stored release (a check made before this existed) is assessed on the spot, so it is never shown on trust.
"""

import datetime as dt

READY, REVIEW, BLOCKED, NOTE = "ready", "review", "blocked", "note"
STATES = (READY, REVIEW, BLOCKED)

# validation notes the checks below already say in their own words
_COVERED = ("The website read may not be the hotel's own", "The hotel's website could not be read", "Only ", "The website analysis crashed", "step(s) of this check failed")


def _reasons(rep, legacy=False):
    """legacy=True: a check saved before report validation existed. Having no validation is then only a note (its history stays visible); every other reason still applies."""
    out = []

    def add(level, code, what):
        out.append({"level": level, "code": code, "what": what})

    rep = rep or {}
    meta = rep.get("meta") or {}
    gate = rep.get("gate")
    if not isinstance(gate, dict):
        if legacy:
            add(NOTE, "pre_validation", "This check was made before report validation existed.")
        else:
            add(BLOCKED, "validation_missing", "The report's validation did not run, so none of its findings were checked.")
        gate = {}
    elif gate.get("error"):
        add(BLOCKED, "validation_failed", f"The report's validation stopped part-way ({str(gate['error'])[:100]}), so its findings were not fully checked.")

    if not meta.get("hotel"):
        add(BLOCKED, "empty_report", "The report has no hotel in it.")
    c = rep.get("consultant") or {}
    cov = c.get("coverage") or {}
    if c.get("error"):
        add(BLOCKED, "website_analysis_failed", "The website analysis failed, so the report has no findings about the website.")
    if cov.get("unreadable"):
        add(BLOCKED, "website_unreadable", "The hotel's website could not be read, so nothing about it was assessed.")
    else:
        ratio, read = cov.get("ratio"), cov.get("pages_read") or 0
        if ratio is not None and ratio < 0.2 and read < 5:
            add(BLOCKED, "website_barely_read", f"Only {read} page(s) of the website were read: too little to judge what it says.")
        elif ratio is not None and ratio < 0.5:
            add(REVIEW, "website_partly_read", f"Only {cov.get('pages_read')} of {cov.get('pages_attempted')} pages of the website could be read.")
    if any(r.get("tag") == "site-check" for r in c.get("recommendations") or []):
        add(BLOCKED, "wrong_website", "The website that was read may not be the hotel's own.")

    ident = rep.get("identity") or {}
    if ident.get("needs_review"):
        add(BLOCKED, "identity_unresolved", "The hotel's name could not be resolved (it still looks like a web address), so the AI answers cannot be matched to it reliably.")

    ai = rep.get("ai_sample") or {}
    items = [i for i in ai.get("items") or [] if i.get("mentioned") is not None]
    if ai.get("status") not in (None, "ok", "not_configured"):
        add(REVIEW, "ai_check_failed", "The AI check did not complete, so AI visibility is missing or partial.")
    if items:
        named = sum(1 for i in items if i.get("mentioned"))
        diag = gate.get("ai_diagnosis") or {}
        if named == 0 and (diag.get("possible_missed") or 0) > 0:
            add(BLOCKED, "ai_names_not_counted", f"{diag['possible_missed']} answer(s) contain words from the hotel's name but were not counted as naming it: the zero cannot be relied on.")
        own_rows = _own_among_rivals(rep, ident)
        if own_rows:
            add(BLOCKED, "hotel_among_rivals", "The hotel appears among its own competitors under another spelling (" + "; ".join(own_rows[:3]) + "): its AI visibility and the rival figures are wrong.")
        amb = (ai.get("summary") or {}).get("ambiguous_named") or 0
        if amb:
            add(REVIEW, "ambiguous_mentions", f"{amb} answer(s) named the hotel's group without saying which hotel; they are not counted as this hotel. Read them before relying on the figure.")
    if any(x.get("check") == "ai_numbers_agree" for x in gate.get("changes") or []):
        add(REVIEW, "ai_counts_disagree", "The number of AI answers differs between sections of the report.")

    for n in gate.get("needs_review") or []:
        text = str(n.get("what") or "")
        if text and not text.startswith(_COVERED[:4]) and _COVERED[4] not in text:
            add(REVIEW, "needs_review", text)
    if rep.get("step_errors") and not any(_COVERED[4] in str(n.get("what") or "") for n in gate.get("needs_review") or []):
        add(REVIEW, "steps_failed", f"{len(rep['step_errors'])} step(s) of this check failed and left their part of the report partial.")

    recs = (c.get("recommendations") or [])
    disputed = sum(1 for r in recs if r.get("disputed"))
    if len(recs) >= 4 and disputed / len(recs) > 0.25:
        add(REVIEW, "many_disputed", f"{disputed} of {len(recs)} findings contradict what the hotel's own pages show.")
    return out


def _own_among_rivals(rep, ident):
    """Names in the rival rankings that are the hotel itself under another spelling (the Saunton Sands failure). Uses the identity the report carries, or the one its name and website give."""
    try:
        import hotel_identity
        ident = ident if ident.get("canonical") else hotel_identity.build((rep.get("meta") or {}).get("hotel") or "", (rep.get("meta") or {}).get("city") or "", (rep.get("meta") or {}).get("website") or "")
        ins = rep.get("ai_insights") or {}
        names = []
        for lb in (ins.get("leaderboard"), (ins.get("niche") or {}).get("leaderboard"), ins.get("brand_ranking")):
            for r in (lb or {}).get("rows", []) + (lb or {}).get("all", []):
                if not r.get("is_target") and r.get("name") and hotel_identity.is_own(ident, r["name"])[0]:
                    names.append(r["name"])
        return sorted(set(names))
    except Exception:  # noqa: BLE001 - an unreadable ranking is not a reason on its own
        return []


def assess(rep, legacy=False):
    """Works out the release state of a report and stores it in rep['release']. -> rep. Never raises. legacy=True for a saved check from before validation existed (see _reasons)."""
    try:
        reasons = _reasons(rep, legacy)
    except Exception as e:  # noqa: BLE001 - a check that cannot run is a reason not to hand the report over
        reasons = [{"level": BLOCKED, "code": "release_check_failed", "what": f"The release check could not run ({type(e).__name__})."}]
    prev = (rep.get("release") or {}) if isinstance(rep, dict) else {}
    state = BLOCKED if any(r["level"] == BLOCKED for r in reasons) else REVIEW if any(r["level"] == REVIEW for r in reasons) else READY
    approved = prev.get("approved") or None
    if state == REVIEW and approved and {r["code"] for r in reasons if r["level"] == REVIEW} <= set(approved.get("codes") or []):
        state = READY                                   # an admin has already looked at exactly these reasons
    else:
        approved = None if state != READY else approved
    rep["release"] = {"state": state, "reasons": reasons, "assessed": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **({"approved": approved} if approved else {})}
    return rep


def state_of(rep):
    """The stored state, or one worked out now for a report that has none (a check made before this existed)."""
    st = ((rep or {}).get("release") or {}).get("state")
    if st in STATES:
        return st
    return assess(dict(rep or {}), legacy=True)["release"]["state"]


def approve(rep, who):
    """An admin has looked at a report in 'review' and accepts exactly its current reasons. -> (ok, message). A blocked report cannot be approved."""
    rel = (rep or {}).get("release") or {}
    if rel.get("state") == BLOCKED:
        return False, "A blocked report cannot be approved: recalculate or re-run it."
    if rel.get("state") != REVIEW:
        return False, "Only a report waiting for review can be approved."
    rel["approved"] = {"by": who, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "codes": sorted({r["code"] for r in rel.get("reasons") or [] if r["level"] == REVIEW})}
    rel["state"] = READY
    return True, "Approved: the hotel can now see this report."


def customer_ready(rep):
    return state_of(rep) == READY


HOLD_TEXT = ("<h1>This report is being checked</h1><p>We check every report before it is shared, and this one has not finished that check. "
             "It will appear here as soon as it has. You do not need to do anything.</p>")
