"""
The hotel differentiation engine: what is genuinely distinctive about this hotel, what it under-explains, what it has that comparable hotels' pages do not state, and the traveller searches where that could matter.

It reads only evidence the audit already holds and says how strong each claim is:

  verified strengths        the hotel's own pages state the facility clearly, on several pages (quote and page count as proof)
  advantages                the hotel states a facility that comparable hotels' pages (the ones the audit could read) do not; a rival page that is silent is NOT proof the rival lacks it, so this is 'supported by the pages
                            read', never 'proven'
  under-explained strengths what the hotel has but explains thinly (the facility-detail check), what its site emphasises but the assistant did not pick up when asked about the hotel, and strengths a segment would
                            need that no page connects into a proposition
  opportunities             each of the above tied to the kind of traveller search it could matter for, with what the assistant did for that search in this sample (named N of M), the action (make verified facts easy to
                            find) and a label: Likely (two kinds of evidence agree) or Worth checking (a hypothesis).

Nothing here says an advantage WILL win recommendations, and nothing is invented: a claim with no evidence is not made.
"""

import re

THEME_OF_FEATURE = {"meeting_rooms": "business", "spa": "romantic", "pool": "romantic", "weddings": "weddings", "family": "family", "airport_transfer": "airport", "restaurant": "dining", "bar": "dining",
                    "accessible": "accessible", "pets": "pets"}
THEME_LABEL = {"business": "business travellers and conference enquiries", "romantic": "romantic breaks and couples", "weddings": "weddings and celebrations", "family": "families", "airport": "airport and transit stays",
               "dining": "hotels known for dining", "accessible": "accessible stays", "pets": "pet-friendly stays", "location": "hotels near a landmark or area"}
FD_FEATURE = {"events": "meeting_rooms", "spa": "spa", "restaurant": "restaurant"}


def _label(features, key):
    return next((f["label"] for f in features if f["key"] == key), key.replace("_", " "))


def build(rep):
    """-> {"strengths", "advantages", "underexplained", "opportunities", "limits"} for a stored report of any age; sections that cannot be judged are empty."""
    c = (rep or {}).get("consultant") or {}
    gap = (rep or {}).get("ai_gap") or {}
    ins = (rep or {}).get("ai_insights") or {}
    features = c.get("features") or []
    level = {f["key"]: f.get("level") for f in features}
    pages_of = {f["key"]: f.get("pages") for f in features}
    fd = {FD_FEATURE.get(f["key"], f["key"]): f for f in c.get("facility_depth") or []}
    strengths, adv, under = [], [], []
    for f in features:
        if f.get("level") == "strong" and (f.get("pages") or 0) >= 2:
            d = fd.get(f["key"])
            proof = f"stated on {f['pages']} pages of the hotel's own site" + (f"; {len(d['found'])} of {d['total']} details are given" if d else "")
            strengths.append({"key": f["key"], "label": f["label"], "proof": proof, "theme": THEME_OF_FEATURE.get(f["key"]), "confidence": "Confirmed"})
    cmp_ = gap.get("comparison") or {}
    own_levels = (cmp_.get("own") or {}).get("levels") or {}
    for key, own in own_levels.items():
        if own not in ("strong", "some"):
            continue
        lacking = [r["name"] for r in cmp_.get("rivals") or [] if (r.get("levels") or {}).get(key) == "none" and (r.get("pages_read") or 0) >= 1]
        read = [r["name"] for r in cmp_.get("rivals") or [] if (r.get("pages_read") or 0) >= 1]
        if lacking and read:
            adv.append({"key": key, "label": _label(features, key), "own": own, "lacking": lacking[:3], "read": len(read), "theme": THEME_OF_FEATURE.get(key), "confidence": "Likely",
                        "proof": f"the hotel's pages state it ({own}); {len(lacking)} of {len(read)} comparable hotels' pages read do not mention it ({', '.join(lacking[:3])}). A silent page does not prove the hotel's rival lacks it."})
    for k, f in fd.items():
        if f.get("thin") and not f.get("disputed"):
            under.append({"key": f["key"], "label": f["label"], "why": f"it is mentioned but only {len(f['found'])} of {f['total']} details are stated: " + "; ".join(m["label"] for m in f["missing"][:3]),
                          "theme": THEME_OF_FEATURE.get(FD_FEATURE.get(f["key"], f["key"])), "confidence": "Likely", "evidence": f.get("quote") or ""})
    per = ins.get("perception") or {}
    for lab in per.get("not_in_assistant_description") or []:
        under.append({"key": "perception:" + lab, "label": lab, "why": f"the hotel's website emphasises it, but the assistant did not mention it when asked to describe the hotel", "theme": None, "confidence": "Worth checking", "evidence": ""})
    for o in c.get("opportunities") or []:
        if o.get("assets") and o.get("level") in ("none", "weak", None):
            under.append({"key": "segment:" + o["key"], "label": o.get("label", o["key"]), "why": f"the hotel has {', '.join(a.lower() for a in o['assets'][:3])}, but no page connects them into a clear proposition for this audience", "theme": o["key"] if o["key"] in THEME_LABEL else
                          ("business" if "business" in o["key"] else None), "confidence": "Likely", "evidence": o.get("statement", "")})
    # tie each to a kind of search, and to what the assistant did for it in this sample
    themes = {}
    for m in gap.get("markets") or []:
        import opportunities
        th = opportunities.theme_of(m.get("question", ""))
        t = themes.setdefault(th, {"named": 0, "of": 0})
        t["named"] += m.get("named") or 0
        t["of"] += m.get("of") or 0
    opps, seen = [], set()
    for kind, rows in (("advantage", adv), ("under-explained", under), ("strength", strengths)):
        for r in rows:
            th = r.get("theme")
            if not th or (th, kind) in seen:
                continue
            seen.add((th, kind))
            res = themes.get(th)
            ai = f"In this sample the assistant named the hotel in {res['named']} of {res['of']} answers to searches of this kind." if res and res["of"] else "No search of this kind was in this sample."
            gapped = bool(res and res["of"] and res["named"] / res["of"] < 0.5)
            if kind == "advantage":
                finding = f"The hotel states {r['label'].lower()}, and {len(r['lacking'])} comparable hotel(s) whose pages were read do not."
                action = f"Make the verified facts about {r['label'].lower()} (what exists, sizes or capacities, who it suits, how to book) easy to find on one page, in plain text, and use them in how the hotel is described to {THEME_LABEL.get(th, 'this kind of traveller')}."
            elif kind == "under-explained":
                finding = f"The hotel has {r['label'].lower()} but explains it thinly: {r['why']}."
                action = f"State the missing details in plain text on the page about {r['label'].lower()}, using only facts the hotel can stand behind."
            else:
                finding = f"{r['label']} is a clear strength on the hotel's own site ({r['proof']})."
                action = f"Keep it prominent and consistent, and check the sources the assistant cites describe it too."
            opps.append({"theme": th, "theme_label": THEME_LABEL.get(th, th), "kind": kind, "finding": finding, "opportunity": f"Position the hotel for {THEME_LABEL.get(th, th)}.", "action": action, "ai_result": ai, "gap": gapped,
                         "confidence": r.get("confidence", "Likely") if kind != "advantage" or len(r.get("lacking", [])) else "Worth checking", "evidence": r.get("proof") or r.get("why") or ""})
    opps.sort(key=lambda o: (not o["gap"], o["kind"] != "advantage", o["kind"] != "under-explained"))
    return {"strengths": strengths[:8], "advantages": adv[:6], "underexplained": under[:6], "opportunities": opps[:6],
            "limits": "Based on the hotel's own pages and the comparable hotels' pages the audit could read, and on one assistant's answers on one day. A page that is silent about a facility does not prove the facility is missing. "
                      "Reviews and destination sites are not searched separately here."}
