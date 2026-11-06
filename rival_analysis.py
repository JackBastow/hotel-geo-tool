"""
Why are the rival hotels recommended instead of this one? For the few comparable hotels the assistant named most, this puts together what the audit holds about each:

  what the assistant said about it   the themes and reasons it gave when naming the hotel
  what it cited                      the sites whose pages named the rival (and whether they named this hotel)
  what its own site shows            the facilities the audit could read on the rival's website
  how this hotel compares            for each theme the assistant gave, whether this hotel's own pages state it clearly, in passing, or not at all

A statement is called SUPPORTED only when at least two of those kinds of evidence point the same way (for example the assistant's reason and a cited page); otherwise it is a HYPOTHESIS to investigate. None of it
describes how the model decides: it is what one assistant said and cited in one sample.
"""

import rivals as rivals_mod


def _domains(urls):
    import re
    return sorted({re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower() for u in urls if u})


def build(rep, limit=3):
    gap = (rep or {}).get("ai_gap") or {}
    ins = (rep or {}).get("ai_insights") or {}
    if gap.get("status") != "ok":
        return []
    agg = {}
    for m in gap.get("markets") or []:
        for r in m.get("rivals") or []:
            if r.get("relation") not in rivals_mod.COMPARABLE:
                continue
            a = agg.setdefault(r["name"], {"name": r["name"], "answers": 0, "of": 0, "themes": {}, "reasons": [], "markets": [], "best_rank": None})
            a["answers"] += r.get("answers") or 0
            a["of"] += r.get("of") or 0
            for t in r.get("themes") or []:
                a["themes"][t] = a["themes"].get(t, 0) + 1
            a["reasons"] += [x for x in (r.get("reasons") or []) if x not in a["reasons"]]
            a["markets"].append(m["qid"])
            if r.get("best_rank") is not None:
                a["best_rank"] = r["best_rank"] if a["best_rank"] is None else min(a["best_rank"], r["best_rank"])
    cmp_ = {r["name"]: r for r in (gap.get("comparison") or {}).get("rivals") or []}
    arts = gap.get("articles") or []
    pages = ins.get("pages") or []
    crit = gap.get("criteria") or {}
    out = []
    for a in sorted(agg.values(), key=lambda a: -a["answers"])[:limit]:
        src = [x["url"] for x in arts if a["name"] in (x.get("rivals_in") or []) and x.get("hotel_in") in (None, False)]
        src += [p["url"] for p in pages if p.get("names_competitor") == a["name"] and not p.get("names_hotel")]
        site = [k.replace("_", " ") for k, v in (cmp_.get(a["name"], {}).get("levels") or {}).items() if v in ("strong", "some")]
        themes = [t for t, _n in sorted(a["themes"].items(), key=lambda kv: -kv[1])][:2]
        comp = []
        for q in a["markets"]:
            for c in crit.get(q) or []:
                if a["name"] in (c.get("rivals") or []) and c["theme"] not in [x["theme"] for x in comp]:
                    comp.append({"theme": c["theme"], "label": c["label"], "state": (c.get("hotel") or {}).get("state")})
        kinds = sum(1 for x in (a["reasons"], src, site) if x)
        state_word = {"strong": "states it clearly", "mentioned": "mentions it only in passing", "not_found": "does not mention it"}
        text = f"{a['name']} was named in {a['answers']} answers across these searches" + (f", most often for {' and '.join(themes)}" if themes else "") + "."
        if a["reasons"]:
            text += f" The assistant's reason: {a['reasons'][0]}."
        if comp:
            text += " This hotel's pages: " + "; ".join(f"{c['label'].lower()}: {state_word.get(c['state'], 'not compared')}" for c in comp[:3]) + "."
        out.append({"name": a["name"], "answers": a["answers"], "of": a["of"], "themes": themes, "reasons": a["reasons"][:2], "sources": _domains(src)[:4], "site_facts": site[:5], "comparison": comp[:4],
                    "label": "Supported" if kinds >= 2 else "Hypothesis", "statement": text})
    return out
