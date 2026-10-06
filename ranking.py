"""
One global ranking model for every finding in the audit.

Each recommendation is scored on four judgements, then divided (gently) by effort:

  risk         business / reputation risk if it is left alone        1-5
  traveller    how much a guest cares about it                       1-5
  visibility   how much it affects whether the hotel can be found,
               read or understood by search and AI systems           1-5
  confidence   how sure we are (established practice vs inference)   0.55-1.0

    value = 100 x (0.40 risk + 0.25 traveller + 0.20 visibility) / 4.25 x confidence
    rank  = value / sqrt(effort)

Risk is weighted highest on purpose: an operational or reputation problem
(a poor food-hygiene rating, a wrong phone number, a site that blocks
crawlers) must be able to outrank a cheap technical improvement such as
markup. Effort only moderates the order - it never lets a trivial fix bury a
serious one.

Every finding is also classed as a REQUIRED FIX (wrong or conflicting
information, missing important guest information, crawl/accessibility
problems, reputation risks, broken entity information) or a COMMERCIAL
OPPORTUNITY (strengthening a segment the hotel may not be targeting). Only
required fixes compete for the "most worth doing" list.

The numbers below are judgements, written down so they can be argued with.
"""

import math

EFFORT_COST = {"low": 1.0, "medium": 1.8, "high": 3.0}
CONF_FACTOR = {"Established good practice": 1.0, "Reasonable inference": 0.8, "Experimental": 0.55}

# (source, tag) -> (risk, traveller, visibility, kind)
F = {
    # contradictions inside the hotel's own pages
    ("consistency", "times"): (4, 5, 3, "fix"), ("consistency", "phone"): (4, 4, 3, "fix"),
    ("consistency", "postcode"): (4, 4, 3, "fix"), ("consistency", "address"): (2, 3, 2, "fix"),
    ("consistency", "name"): (2, 2, 3, "fix"), ("consistency", "rooms"): (2, 3, 2, "fix"),
    ("consistency", "hours"): (3, 4, 3, "fix"), ("consistency", "old_offer"): (3, 3, 2, "fix"),
    ("consistency", "amenity"): (3, 4, 3, "fix"),
    # strengths that are easy to miss: upside, not a defect
    ("hidden", "once"): (1, 3, 2, "opportunity"), ("hidden", "deep"): (1, 3, 3, "opportunity"),
    ("hidden", "pdf"): (1, 3, 2, "opportunity"), ("hidden", "pdf_menu"): (1, 2, 2, "opportunity"),
    ("hidden", "image"): (3, 3, 3, "fix"), ("hidden", "poorly_linked"): (1, 2, 3, "opportunity"),
    # crawl and accessibility
    ("machine", "robots_block_all"): (5, 3, 5, "fix"), ("machine", "noindex"): (4, 3, 5, "fix"),
    ("machine", "js_empty"): (4, 3, 5, "fix"), ("machine", "http_errors"): (3, 3, 3, "fix"),
    ("machine", "sitemap_missing"): (2, 1, 3, "fix"), ("machine", "ai_blocked"): (2, 2, 3, "fix"),
    ("machine", "canonical_other"): (2, 1, 3, "fix"), ("machine", "dup_titles"): (2, 1, 2, "fix"),
    ("machine", "dup_content"): (2, 1, 2, "fix"), ("machine", "home_title"): (2, 2, 3, "fix"),
    ("machine", "home_meta"): (1, 2, 2, "fix"), ("machine", "meta_missing"): (1, 1, 1, "fix"),
    ("machine", "h1"): (1, 1, 1, "fix"), ("machine", "alt"): (3, 3, 2, "fix"),
    ("machine", "entity_missing"): (3, 2, 4, "fix"), ("machine", "READ1"): (4, 3, 5, "fix"),
    ("machine", "cc_refused"): (3, 2, 4, "fix"), ("machine", "speed"): (3, 4, 3, "fix"), ("machine", "a11y"): (3, 3, 2, "fix"),
    # structured data - deliberately modest: accuracy and tidiness, not a ranking lever
    ("structured", "SD1"): (1, 2, 2, "fix"), ("structured", "SD2"): (3, 2, 3, "fix"),
    ("structured", "SD3"): (1, 1, 2, "fix"), ("structured", "SD4"): (1, 1, 2, "opportunity"),
    ("structured", "SD5"): (1, 1, 1, "opportunity"), ("structured", "SD6"): (1, 1, 1, "opportunity"),
    # findings that came from the outside-the-website evidence
    ("intel", "F1"): (5, 5, 2, "fix"),       # official food-hygiene rating below 4
    ("intel", "V1"): (5, 5, 2, "fix"),       # a verified low rating on a review platform
    ("intel", "V2"): (2, 3, 1, "fix"),       # a low rating that may belong to another hotel
    ("intel", "A1"): (3, 2, 1, "fix"),       # unverifiable award wording (advertising rules)
    ("intel", "A2"): (3, 2, 1, "fix"),       # award claimed but not confirmed by the issuer
    ("intel", "I1"): (2, 2, 3, "fix"),       # the hotel appears under more than one name
    ("intel", "I2"): (4, 4, 3, "fix"),       # a listing contradicts the website
    ("intel", "I3"): (2, 3, 2, "fix"),       # presence on major platforms unconfirmed
    ("intel", "I4"): (1, 2, 2, "opportunity"),
    ("intel", "M1"): (2, 3, 3, "opportunity"), ("intel", "M2"): (1, 3, 2, "opportunity"),
    ("intel", "M3"): (1, 1, 1, "opportunity"), ("intel", "M4"): (1, 2, 2, "opportunity"),
    ("intel", "M5"): (1, 1, 1, "opportunity"), ("intel", "W2"): (1, 1, 1, "opportunity"),
}
DEFAULT = {"questions": (3, 3, 3, "fix"), "location": (2, 4, 3, "fix"), "consistency": (2, 3, 2, "fix"),
           "hidden": (1, 3, 2, "opportunity"), "machine": (2, 2, 2, "fix"), "structured": (1, 2, 2, "fix"),
           "intel": (2, 2, 2, "fix")}


def tag_of(r):
    """The finding type behind a recommendation (so its factors can be looked up)."""
    if r.get("tag"):
        return r["tag"]
    rid = r["id"]
    if r["source"] == "machine":
        return rid[2:] if rid.startswith("M-") else rid
    if r["source"] == "intel":
        return rid[2:].split("-")[0] if rid.startswith("X-") else rid
    return rid


def factors(r, qmap):
    src = r["source"]
    if src == "questions":
        qs = [qmap[i] for i in r.get("question_ids", []) if i in qmap]
        standard = [q for q in qs if q.get("source") in ("standard", "location")]
        high = [q for q in qs if q.get("high_value")]
        risk = 4 if any(q["state"] in ("missing", "unclear") for q in high) else (3 if high else 2)
        trav = 5 if high else 3
        # detail for a segment the hotel offers (meeting rooms, weddings, spa...) matters if that segment is a target
        return risk, trav, 3, ("fix" if standard else "opportunity")
    if src == "location":
        return F.get(("location", tag_of(r)), DEFAULT["location"])
    return F.get((src, tag_of(r)), DEFAULT.get(src, (2, 2, 2, "fix")))


def label(value, risk, vis):
    if risk >= 5 and vis >= 4 and value >= 85:
        return "critical"
    if value >= 62:
        return "high"
    if value >= 38:
        return "medium"
    return "low"


def annotate(recs, questions):
    qmap = {q["id"]: q for q in questions or []}
    for r in recs:
        risk, trav, vis, kind = factors(r, qmap)
        conf = CONF_FACTOR.get(r["confidence"], 0.8)
        value = 100.0 * (0.40 * risk + 0.25 * trav + 0.20 * vis) / 4.25 * conf
        r["factors"] = {"risk": risk, "traveller": trav, "visibility": vis, "confidence": conf}
        r["kind"] = kind
        r["value"] = round(value, 1)
        r["rank"] = round(value / math.sqrt(EFFORT_COST[r["effort"]]), 1)
        r["priority"] = label(value, risk, vis)
        r["impact"] = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}[r["priority"]]
    return recs


def top_actions(recs, n=7, per_category=4, floor=35):
    """The few required fixes most worth doing, from the whole audit."""
    picked, used = [], {}
    for r in sorted((x for x in recs if x["kind"] == "fix" and x["value"] >= floor), key=lambda x: -x["rank"]):
        if len(picked) >= n:
            break
        if used.get(r["category"], 0) >= per_category:
            continue
        picked.append(r)
        used[r["category"]] = used.get(r["category"], 0) + 1
    return picked


def quick_wins(recs, exclude_ids=(), n=8):
    """Low-effort improvements not already in the top list."""
    pool = [r for r in recs if r["effort"] == "low" and r["id"] not in exclude_ids and r["value"] >= 28]
    return sorted(pool, key=lambda r: -r["rank"])[:n]


def plan_30_60_90(recs, top_ids):
    """A simple sequence: quick, serious things first; medium effort next; the rest later. Each item appears once."""
    plan = {"30": [], "60": [], "90": []}
    seen = set()

    def put(bucket, r):
        if r["id"] not in seen and len(plan[bucket]) < 7:
            plan[bucket].append(r["id"])
            seen.add(r["id"])
    ordered = sorted(recs, key=lambda r: -r["rank"])
    for r in ordered:
        if r["kind"] == "fix" and (r["priority"] in ("critical", "high") or (r["effort"] == "low" and r["value"] >= 40)):
            put("30", r)
    for r in ordered:
        if r["kind"] == "fix" and r["effort"] in ("low", "medium") and r["value"] >= 35:
            put("60", r)
    for r in ordered:
        if r["value"] >= 28:
            put("90", r)
    return plan


EXPECTED = {
    "questions": "The answers are published as plain text on the page, so guests and any system reading it can find them; the next audit should show these questions as answered.",
    "location": "The page states the distance or travel time to each place, so the location signal is specific; the next audit should show them as described with a distance.",
    "consistency": "One consistent value appears everywhere on the site; the next audit should report no contradiction.",
    "hidden": "The strength is reachable from the pages guests and crawlers visit first, and is not held only in a PDF or a single mention.",
    "structured": "The structured data matches the page text; the next audit should report it as correct.",
}


def expected_outcome(r):
    if r["source"] in EXPECTED:
        return EXPECTED[r["source"]]
    return r.get("success_check") or "The next audit no longer reports this."
