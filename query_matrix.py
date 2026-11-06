"""
More specific traveller prompts, built from what the audit has VERIFIED about the hotel: location + kind of traveller + facility + requirement.

Testing 20 generic searches for the town measures how the assistant treats the town. The more useful test is the narrow search the hotel can credibly satisfy ('hotels near the department stores with a gym', 'a venue for a
corporate workshop of 80 people near the Opera'): each is a different customer need, some are irrelevant to a given hotel and some are real commercial opportunities. Every suggestion here:
  * rests on at least two verified attributes (a place near the hotel, and a facility, a kind of traveller or a requirement the hotel's own pages state), named in 'rests_on';
  * never names the hotel and mentions the town or a place near it (the same rules as any prompt, see prompt_sets.check_prompt);
  * is a SUGGESTION: the hotel chooses which to add, and a confirmed prompt set only changes when the hotel confirms it.
"""

import re

import ai_niche
import ai_questions
import prompt_sets

SHOP = re.compile(r"galeries|lafayette|printemps|harrods|selfridges|bloomingdale|macy|mall|market|shopping|department store|kadewe|ku'?damm|oxford street|fifth avenue|king'?s road", re.I)
FACILITY_ASK = {"gym": "a gym", "pool": "a swimming pool", "spa": "a spa", "parking": "parking", "restaurant": "a good restaurant", "ev": "EV charging", "pets": "dog-friendly rooms", "accessible": "step-free accessible rooms",
                "meeting_rooms": "meeting rooms", "family": "rooms for a family"}


def _capacity(c):
    """The largest capacity the hotel's own pages state for an event or meeting space, as a plain number (None when none is stated)."""
    best = None
    for f in c.get("facility_depth") or []:
        if f.get("key") != "events":
            continue
        for d in f.get("found") or []:
            if d.get("key") == "capacity":
                m = re.search(r"(\d{2,4})", d.get("match", "") or d.get("quote", ""))
                if m:
                    best = max(best or 0, int(m.group(1)))
    return best


def suggest(rep, existing=(), n=8):
    """-> [{text, rests_on: [...], why}], most specific first. `existing` are the prompts already in the hotel's set (near-duplicates are left out)."""
    c = (rep or {}).get("consultant") or {}
    meta = (rep or {}).get("meta") or {}
    hotel, city = meta.get("hotel", ""), (meta.get("city") or "").split("/")[-1].split(",")[0].strip()
    plan = (rep or {}).get("question_plan") or {}
    anchors = [a for a in plan.get("anchors") or [] if a.get("kind") in ("attraction", "venue") and a.get("name")][:3]
    if not hotel or not city or not anchors:
        return []
    mk = ((rep or {}).get("ai_sample") or {}).get("market") or {}
    try:
        tp = ai_niche._tier_phrase(mk.get("tier") if isinstance(mk.get("tier"), dict) else None, mk.get("stars"))
    except Exception:  # noqa: BLE001
        tp = ""
    level = {f["key"]: f.get("level") for f in c.get("features") or []}
    segs = {i["key"]: i.get("level") for i in c.get("intents") or []}
    strong = [k for k, v in level.items() if v == "strong"]
    out = []

    def add(text, rests, why):
        out.append({"text": text, "rests_on": rests, "why": why})
    a0, a1 = anchors[0], anchors[1] if len(anchors) > 1 else anchors[0]
    cap = _capacity(c)
    if "meeting_rooms" in strong and cap and cap >= 30:
        n_ = (cap // 10) * 10
        add(f"Which {tp}hotels near {a0['name']} can host a corporate workshop for {n_} people?", [f"near {a0['name']}", f"meeting space stated for {cap}", "business"], "The hotel states its meeting capacity, so this is a search it can credibly answer.")
    if "meeting_rooms" in strong:
        add(f"Which hotels in {city} have conference facilities near {a1['name']}?", [f"near {a1['name']}", "meeting rooms stated"], "Meeting rooms are described strongly on the hotel's own pages.")
    for k in ("gym", "pool", "spa", "parking", "accessible", "pets", "ev"):
        if k in strong:
            a = next((x for x in anchors if SHOP.search(x["name"])), a1)
            add(f"Which {tp}hotels near {a['name']} have {FACILITY_ASK[k]}?", [f"near {a['name']}", FACILITY_ASK[k] + " stated"], f"{FACILITY_ASK[k].capitalize()} is stated on the hotel's own pages, and {a['name']} is a place it is close to.")
    if segs.get("business") in ("strong", "some") or "meeting_rooms" in strong:
        add(f"Which {tp}hotels within walking distance of {a0['name']} suit a business traveller who needs a quiet room to work?", [f"near {a0['name']}", "business travel stated"], "The hotel's pages speak to business travellers.")
    if segs.get("couples") in ("strong", "some") or ("spa" in strong and "restaurant" in strong):
        add(f"Which hotels near {a0['name']} are best for a romantic weekend, with a spa and a good restaurant?", [f"near {a0['name']}", "spa and dining stated"], "The hotel's pages support a couples' stay.")
    if a0.get("views", 0) >= 2000 or a0.get("source", "").startswith("Wikipedia"):
        add(f"Which {tp}hotels near {a0['name']} suit first-time visitors to {city}?", [f"near {a0['name']} (a well-known place)", "location"], f"{a0['name']} is a well-known place the hotel is close to.")
    if "family" in strong:
        add(f"Which hotels near {a1['name']} have rooms for three adults or a family of four?", [f"near {a1['name']}", "family rooms stated"], "Family rooms are described on the hotel's own pages.")
    # keep only what passes the rules every prompt must pass, and what is not already asked
    ok, seen = [], list(existing or [])
    for s in out:
        t, err = prompt_sets.check_prompt(s["text"], hotel, city, [{"name": a["name"]} for a in anchors])
        if err or any(ai_questions._similar(t, e, 0.7) for e in seen):
            continue
        seen.append(t)
        ok.append({**s, "text": t})
    return ok[:n]
