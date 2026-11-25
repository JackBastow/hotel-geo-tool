"""
Does every part of a finished report agree with the verified fact profile? -> audit(rep) = {"checked": [...sections], "violations": [{section, facility, profile, says}], "word_rule_sections": [...]}

The profile (rep["fact_profile"]) says, per facility, whether the hotel has it itself. A section that treats a facility as the hotel's own when the profile says it is not offered, only
nearby or a partner's, or that the profile does not confirm, is a violation. Used on the admin run page and in the regression test of the 10 hotels; never shown to a hotel.
"""

import re

import lexicon

# which intents and audiences rest on which facility
_INTENT_FAC = {"spa": "spa", "food": "restaurant", "meetings": "meeting_rooms", "weddings": "weddings", "pet": "pets", "accessible": "accessible"}
_AUD_FAC = {"spa": "spa", "food": "restaurant", "dining": "restaurant", "meetings": "meeting_rooms", "business_meetings": "meeting_rooms", "weddings": "weddings", "pets": "pets",
            "dog": "pets", "wellness": "spa"}
_PROMPT_FAC = {"spa": r"\bspa\b|wellness|massage", "pool": r"\bpool\b|swim", "restaurant": r"restaurant|fine dining|michelin", "parking": r"\bparking\b|car park",
               "gym": r"\bgym\b|fitness", "meeting_rooms": r"meeting|conference|offsite", "weddings": r"wedding", "pets": r"\bdogs?\b|\bpets?\b|dog[- ]friendly", "ev": r"\bev\b|electric|charging"}
_PROMOTE = re.compile(r"\b(?:promote|highlight|showcase|feature|describe your|add (?:a|the) (?:page|section) (?:on|about)|strength)\b", re.I)


def _denied(rep):
    """{facility: profile status} for every facility the hotel does not have itself, by the profile; plus the facilities the profile does not confirm (None)."""
    fp = (rep or {}).get("fact_profile") or {}
    if fp.get("status") != "ok":
        return None
    facs = fp.get("facilities") or {}
    out = {}
    for k in lexicon.FEATURES:
        st = (facs.get(k) or {}).get("status")
        if st != "on_site":
            out[k] = st or "not confirmed"
    return out


def audit(rep):
    den = _denied(rep)
    if den is None:
        return {"status": "no_profile", "checked": [], "violations": [], "note": "The facilities were judged by the word rules alone in this check (no verified profile)."}
    v, checked = [], []

    def bad(section, fac, says):
        v.append({"section": section, "facility": fac, "profile": den[fac], "says": str(says)[:200]})

    c = rep.get("consultant") or {}
    checked.append("facilities (consultant.features)")
    for f in c.get("features") or []:
        if f.get("key") in den and f.get("level") in ("some", "strong"):
            bad("facilities", f["key"], f"level {f['level']}")
    checked.append("kinds of guest (consultant.intents)")
    for i in c.get("intents") or []:
        fac = _INTENT_FAC.get(i.get("key"))
        if fac in den and i.get("level") in ("some", "strong"):
            bad("kinds of guest", fac, f"{i['label']}: {i['level']}")
    checked.append("what AI can pick up (understanding.strong_signals)")
    lab = {lexicon.INTENTS[k][0]: _INTENT_FAC[k] for k in _INTENT_FAC if k in lexicon.INTENTS}
    for s in (c.get("understanding") or {}).get("strong_signals") or []:
        if lab.get(s) in den:
            bad("strong signals", lab[s], s)
    checked.append("market profile (audiences)")
    for a in (rep.get("market_profile") or {}).get("audiences") or []:
        fac = _AUD_FAC.get(a.get("key"))
        if fac in den and a.get("level") in ("some", "strong"):
            bad("market audiences", fac, f"{a['label']}: {a['level']}")
    checked.append("kind of hotel (hotel_class)")
    for k, fac in (("spa_hotel", "spa"), ("conference", "meeting_rooms")):
        if k in ((c.get("hotel_class") or {}).get("keys") or []) and fac in den:
            bad("kind of hotel", fac, k)
    checked.append("facility detail (facility_depth)")
    for r in c.get("facility_depth") or []:
        fac = {"spa": "spa", "restaurant": "restaurant", "events": "meeting_rooms"}.get(r.get("key"))
        if fac in den:
            bad("facility detail", fac, r.get("label"))
    checked.append("strengths and advantages (differentiation)")
    d = c.get("differentiation") or {}
    for k in ("strengths", "advantages"):
        for r in d.get(k) or []:
            fac = str(r.get("key") or "").split(":")[-1]
            if fac in den:
                bad(f"differentiation {k}", fac, r.get("label") or r.get("key"))
    checked.append("comparison with rivals (ai_gap.comparison.own)")
    for fac, lv in (((rep.get("ai_gap") or {}).get("comparison") or {}).get("own") or {}).get("levels", {}).items():
        if fac in den and lv in ("some", "strong"):
            bad("rival comparison", fac, f"own level {lv}")
    checked.append("AI test questions (question_plan)")
    for q in (rep.get("question_plan") or {}).get("questions") or []:
        for fac, rx in _PROMPT_FAC.items():
            if fac in den and den[fac] != "not confirmed" and re.search(rx, q.get("text") or "", re.I):
                bad("AI test question", fac, q["text"])
    checked.append("guest questions")
    qk = {"parking": "parking", "pets": "pets", "ev": "ev", "accessibility": "accessible"}
    for q in (rep.get("guest_questions") or {}).get("questions") or []:
        fac = qk.get(q.get("id"))
        if fac in den and den[fac] == "not_offered" and q.get("state") == "answered" and not q.get("not_offered"):
            bad("guest question", fac, f"answered as offered: {q.get('snippet', '')[:120]}")
    # who the hotel is for: a kind of guest shown as strong or some must be one the profile confirms, and never one the pages say the hotel is not for
    pos = ((rep.get("fact_profile") or {}).get("positioning"))
    if isinstance(pos, dict):
        checked.append("who the hotel is for (consultant.intents vs the profile's positioning)")
        for i in c.get("intents") or []:
            k, lv = i.get("key"), i.get("level")
            if lv not in ("some", "strong"):
                continue
            ps = (pos.get(k) or {}).get("status")
            if ps == "not_for" or (ps is None and k not in _INTENT_FAC):
                v.append({"section": "kinds of guest", "facility": k, "profile": ps or "not confirmed", "says": f"{i.get('label')}: {lv}"})
        checked.append("kind of hotel vs positioning (airport, family)")
        for cls, k in (("airport", "airport"), ("family_focused", "family")):
            ps = (pos.get(k) or {}).get("status")
            if cls in ((c.get("hotel_class") or {}).get("keys") or []) and ps in (None, "not_for") and not re.search(r"airport", (rep.get("meta") or {}).get("hotel") or "", re.I):
                v.append({"section": "kind of hotel", "facility": k, "profile": ps or "not confirmed", "says": cls})
    checked.append("recommendations (title, action, example)")
    for r in c.get("recommendations") or []:
        text = " ".join(str(r.get(k) or "") for k in ("title", "action", "example"))
        for fac, rx in _PROMPT_FAC.items():
            if fac in den and den[fac] in ("not_offered", "nearby", "partner") and re.search(rx, text, re.I) and _PROMOTE.search(text) and not r.get("id", "").startswith("AF-"):
                bad("recommendation", fac, f"{r.get('id')}: {r.get('title')}")
    return {"status": "ok", "checked": checked, "violations": v,
            "word_rule_sections": ["who the hotel is for beyond facilities (luxury, budget, couples, airport, city breaks, beach)", "rival hotels' facilities (their own sites)"]}
