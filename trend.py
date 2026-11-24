"""
Reading AI-test counts honestly: how often, with how much doubt, and whether a change since the last audit is more than noise.

A handful of answers cannot give a precise rate. 'Named in 3 of 9 sampled answers' is shown with a plain band (no 'true rate' range: the answers are not independent searches; the Wilson interval at 95% is used only to judge change), a plain band
('not appearing', 'rarely', 'sometimes', 'usually'), and the number of answers behind it. A change between two audits is called a change ONLY when those ranges do not overlap; otherwise it is 'no clear
change'. Prompts are compared by their wording, which is why each hotel's benchmark prompts are frozen at its first audit and asked again word for word.
"""

import math
import re

import evidence

Z95 = 1.96


def wilson(k, n, z=Z95):
    """The range (low, high) as fractions that the true rate plausibly lies in, given k named of n answers. (0, 1) when there are no answers."""
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def band(named, n):
    """A plain word for how often the hotel was named: 'no answers', 'not appearing', 'rarely', 'sometimes' or 'usually'. Never says 'always' or 'never': the sample is too small."""
    if not n:
        return "no answers"
    r = named / n
    return "not appearing" if named == 0 else "rarely" if r <= 0.25 else "sometimes" if r < 0.75 else "usually"


SAMPLE_NOTE = ("The answers are repeated asks of the same assistants on one day, not independent traveller searches, so they show a pattern across the tested prompts, "
               "not a rate for all AI searches.")


def describe(named, n):
    """'named in 3 of 9 sampled answers (sometimes)'. The count and a plain band: no 'true rate' range, because repeated asks of one assistant on one day are not independent samples of
    traveller searches (Paris Marriott review). The interval is still used inside, to decide whether a change between checks is more than noise (report_model.ai_moved)."""
    if not n:
        return "no answers were judged"
    return f"named in {named} of {n} sampled answers ({band(named, n)})"


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", evidence.fold(text))).strip()


def per_prompt(items):
    """{normalised prompt: {"text", "named", "n"}} from the answers of one audit (answers judged only; 'about the hotel' questions excluded)."""
    out = {}
    for i in items or []:
        if i.get("kind") == "direct" or i.get("mentioned") is None:
            continue
        d = out.setdefault(_norm(i["text"]), {"text": i["text"], "named": 0, "n": 0})
        d["n"] += 1
        d["named"] += 1 if i["mentioned"] else 0
    return out


def compare(cur_items, prev_items, benchmark_texts=None):
    """
    The same prompts, now and at the last audit. -> {"rows": [{text, now: (named, n), before: (named, n), change}], "now": (named, n), "before": (named, n), "change", "prompts"}.
    change is 'more often', 'less often' or 'no clear change' (ranges overlap). Only prompts asked in BOTH audits are compared; with benchmark_texts, only those.
    """
    cur, prev = per_prompt(cur_items), per_prompt(prev_items)
    keys = [k for k in cur if k in prev and (not benchmark_texts or k in {_norm(t) for t in benchmark_texts})]
    rows = []
    for k in keys:
        a, b = cur[k], prev[k]
        rows.append({"text": a["text"], "now": (a["named"], a["n"]), "before": (b["named"], b["n"]), "change": _change((a["named"], a["n"]), (b["named"], b["n"]))})
    now = (sum(r["now"][0] for r in rows), sum(r["now"][1] for r in rows))
    before = (sum(r["before"][0] for r in rows), sum(r["before"][1] for r in rows))
    return {"rows": rows, "now": now, "before": before, "change": _change(now, before) if rows else None, "prompts": len(rows)}


def _change(now, before):
    if not now[1] or not before[1]:
        return "no clear change"
    (l1, h1), (l2, h2) = wilson(*now), wilson(*before)
    return "more often" if l1 > h2 else "less often" if h1 < l2 else "no clear change"
