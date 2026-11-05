"""
One check across the findings before a report goes out, so two sections never say opposite things about the same fact.

The report is built by several independent checks (guest questions, traveller requirements, facility detail, outside sources, scores). Each is right about what it looked at, but they can look at different pages or use
different rules, and then the report says, on one page, that the spa is barely described and, on another, that its treatments, facilities and opening times are confirmed. A general manager who sees that once stops
trusting the rest. This reconciles the cases we know of and records each one:

  facility detail vs traveller requirements   the facility-detail finding (for example 'the spa states 1 of 6 details') is set to 'Worth checking' and marked disputed when the traveller check read the same facility as
                                              stated; the report then shows a lead to look at, not a confirmed problem
  open-data match                             a score driver that says the hotel was 'matched in open map data' is corrected when the outside-source check could only make an uncertain match (a match needs the name and
                                              one more identifier)

Every reconciliation is returned as a note, so the methodology can say what was reconciled.
"""

import re

import advice
import ranking

FD_TO_REQUIREMENT = {"spa": r"\bspa\b", "restaurant": r"dining|restaurant", "events": r"meeting|event"}
OPEN_DATA = ("OpenStreetMap", "Wikidata")


def reconcile(recs, facility, travel, profile, external):
    """Changes `recs`, `facility` and `profile` in place. -> [note strings]."""
    notes = []
    for f in facility or []:
        rx = FD_TO_REQUIREMENT.get(f.get("key"))
        if not rx or not f.get("thin"):
            continue
        hit = next((r for seg in (travel or {}).get("segments", []) for r in seg.get("requirements", []) if r.get("state") == "confirmed" and re.search(rx, r.get("label", ""), re.I)), None)
        if not hit:
            continue
        f["disputed"] = True
        said = "; ".join(x.get("fact", "") for x in (hit.get("found") or [])[:2]) or "stated"
        rec = next((x for x in recs if x.get("id") == f"FD-{f['key']}"), None)
        if rec:
            rec["finding"] = rec["finding"] + f" Another check in this report read the website as stating “{hit['label']}” ({said}), so the two checks disagree: look at the pages before acting."
            rec["confidence"] = advice.EXPER                      # evidence_label() turns this into 'Worth checking'
            ranking.relabel([rec])
        notes.append(f"{f['label']}: the facility-detail check found it thinly described, but the traveller check read “{hit['label']}” as stated. Shown as a lead to check, not a confirmed problem.")
    rows = [r for r in (external or {}).get("rows") or [] if r.get("source") in OPEN_DATA]
    if rows and not any(r.get("status") == "verified" for r in rows):
        for p in profile or []:
            if p.get("key") == "entity" and p.get("assessed") and p.get("score") is not None and any("matched in open map" in d for d in p.get("drivers") or []):
                p["drivers"] = [("~ found by name in open data, but not verified (a match needs the name and one more identifier)" if "matched in open map" in d else d) for d in p["drivers"]]
                p["score"] = max(0, p["score"] - 20)
                ev = p.get("evidence") or {}
                if ev.get("why"):
                    ev["why"] = ev["why"].replace("open-data match confirmed", "open-data match not verified")
                notes.append("Entity clarity: the open-data match is uncertain (name only), so it is not described as confirmed and its 20 points are taken off.")
    return notes
