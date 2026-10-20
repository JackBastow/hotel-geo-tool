"""
The AI visibility tab, built to be read in a minute and explored on demand.

  At a glance (always visible): one sentence on how often the assistant named the hotel (with the honest range), four numbers, a bar for every search showing how often the hotel was named and who was named
  instead, and up to four things that stand out.
  Everything else is a section that opens on demand, titled with what is inside it: who was named instead and why, the hotel's own prompts, the comparison with the last audit, where the assistant got its
  information, what it says about the hotel, the hotels named most, every question and answer, how the questions were chosen, and the by-hand checklist.

Nothing was removed from the tab: the long tables are still there, one click away. This module only decides the order and what is shown first.
"""

import ai_sample
import trend
import ui_consult
import ui_theme
from htmlst import st


def _short(text, n=100):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _search_rows(ai, gap):
    """One row per search put to the assistant: the question, how many answers named the hotel, and who was named instead (comparable hotels only)."""
    rows = []
    if gap and gap.get("markets"):
        order = {"niche": 0, "custom": 1, "generic": 2}
        for m in sorted(gap["markets"], key=lambda m: (m.get("priority") != "core", order.get(m["kind"], 3), m["qid"])):
            inst = ", ".join(r["name"] for r in m["rivals"][:2])
            note = ("Named instead: " + inst) if inst else ("Only hotels in a higher category were named" if m.get("other_category") else "")
            rows.append({"label": _short(m["question"], 90), "named": m["named"], "of": m["of"], "note": note})
    elif ai:
        for g in ai_sample.by_question([i for i in ai.get("items") or [] if i["kind"] != "direct"]):
            rows.append({"label": _short(g["text"], 90), "named": g["named"], "of": g["of"], "note": ""})
    return rows


def _stands_out(fa_res, gap, ins, prev_full):
    """Up to four plain sentences: the largest gap, the most useful piece of evidence for it, a statement the assistant got wrong, and a clear change since the last audit."""
    out = []
    ms = {m["qid"]: m for m in (gap or {}).get("markets") or []}
    gaps = sorted((ms[q] for q in (gap or {}).get("gaps") or [] if q in ms), key=lambda m: (not m["consistent"], m["qid"]))
    if gaps:
        m = gaps[0]
        names = ", ".join(r["name"] for r in m["rivals"][:3])
        out.append(f"Not named for “{_short(m['question'], 90)}” ({m['named']} of {m['of']} answers): {names} {'were' if len(m['rivals']) > 1 else 'was'}.")
        for o in ((gap.get("observations") or {}).get(m["qid"]) or []):
            if o["kind"] in ("criterion", "source"):
                out.append(_short(o["text"], 230))
                break
    elif gap and gap.get("status") == "ok" and any(m["status"] != "named" for m in gap["markets"]):
        out.append(_short(gap.get("reason") or "", 230))
    acc = (ins or {}).get("accuracy") or {}
    bad = [r for r in acc.get("rows", []) if r["status"] == "differs"]
    if bad:
        out.append(f"The assistant said something different from the hotel's own record: {bad[0]['claim']} (“{_short(bad[0]['assistant_says'], 40)}” against {_short(bad[0]['our_record'], 50)}).")
    if prev_full and (prev_full.get("ai_sample") or {}).get("status") == "ok":
        c = trend.compare((fa_res.get("ai_sample") or {}).get("items"), prev_full["ai_sample"].get("items"), [p["text"] for p in (fa_res.get("benchmark") or {}).get("prompts") or []] or None)
        if c["rows"] and c["change"] in ("more often", "less often"):
            out.append(f"Since the last audit the hotel is named {c['change']} in the prompts asked both times ({trend.describe(*c['now'])}; before: {c['before'][0]} of {c['before'][1]}).")
    return out[:4]


def _section(title, body, expanded=False):
    with st.expander(title, expanded=expanded):
        body()


def ai_tab(fa_res, consult, prev_full=None):
    ai, ins, gap = fa_res.get("ai_sample"), fa_res.get("ai_insights"), fa_res.get("ai_gap")
    prompts, bench = fa_res.get("custom_prompts"), fa_res.get("benchmark")
    if not ai or ai.get("status") != "ok":
        ui_consult.ai_test_card(ai, fa_res["meta"].get("hotel", ""))
        if prompts:
            ui_consult.custom_prompts_card(ai, prompts)
        return
    log = ai_sample.test_log(ai)
    s = ai["summary"]
    sm = (log or {}).get("summary") or {}
    n, named = sm.get("non_branded_answers", 0), sm.get("appeared", 0)

    # ---------------------------------------------------------------- at a glance
    st.markdown("#### Do AI assistants name this hotel?")
    if n:
        lo, hi = trend.wilson(named, n)
        st.markdown(f"**{trend.band(named, n).capitalize()}.** The assistant named the hotel in **{named} of {n} answers** to searches that do not mention it. From that many answers the true rate is plausibly "
                    f"{round(100 * lo)}% to {round(100 * hi)}%.")
    st.caption(f"One assistant ({ui_consult.md_safe(ai.get('model', ''))}) with live web search" + (f", searching as if from {ui_consult.md_safe(ai['search_country'])}," if ai.get("search_country") else "")
               + f" on {ui_consult.md_safe(ai.get('run_at', ''))}. A sample, not a ranking or a score. ChatGPT, Gemini and Copilot were not tested.")
    sb = (ins or {}).get("scoreboard") or {}
    osr = (ins or {}).get("own_site") or {}
    top = None
    if gap and gap.get("markets"):
        tally = {}
        for m in gap["markets"]:
            for r in m["rivals"]:
                tally[r["name"]] = tally.get(r["name"], 0) + r["answers"]
        top = max(tally.items(), key=lambda kv: kv[1]) if tally else None
    cols = st.columns(4)
    cols[0].metric("Named in", f"{named} of {n} answers" if n else "n/a", help="Answers to searches that do not name the hotel")
    cols[1].metric("In its own markets", f"{s['niche_named']} of {s['niche_asked']}" if s.get("niche_asked") else "n/a", help="Answers to the narrower searches written for this hotel's category, place and audiences")
    cols[2].metric("Most-named rival", f"{top[0]}" if top else (sb.get("top_competitor") or "none"), help="The hotel in the same category the assistant named most across the searches where this hotel was not named")
    cols[3].metric("Own website cited", (f"{osr['own_cited']} of {osr['answers']} answers" if osr.get("answers") else ("yes" if s.get("own_site_cited") else "no")), help="Whether the assistant used the hotel's own website as a source")
    rows = _search_rows(ai, gap)
    if rows:
        st.markdown('<span class="hk-label">How often each search named the hotel</span>', unsafe_allow_html=True)
        ui_theme.count_bars(rows)
    notes = _stands_out(fa_res, gap, ins, prev_full)
    if notes:
        st.markdown("**What stands out**")
        for t in notes:
            st.markdown("- " + ui_consult.md_safe(t))

    # ---------------------------------------------------------------- everything else, one click away
    gaps = (gap or {}).get("gaps") or []
    if gap and gap.get("status") == "ok":
        _section(f"Who was named instead, and what the evidence shows ({len(gaps)} search{'es' if len(gaps) != 1 else ''} with a gap)" if gaps else "Who was named instead", lambda: ui_consult.ai_gap_card(gap), expanded=bool(gaps))
    if prompts:
        _section(f"Your own prompts ({len(prompts)})", lambda: ui_consult.custom_prompts_card(ai, prompts), expanded=True)
    if prev_full and (prev_full.get("ai_sample") or {}).get("status") == "ok":
        _section("Compared with the last audit", lambda: ui_consult.ai_trend_card(ai, prev_full, bench))
    if ins and ins.get("status") in ("ok", "partial"):
        _section("Where the assistant got its information", lambda: ui_consult.ins_sections(ai, ins, only=("sources", "pages")) or ui_consult.own_site_note(ins))
        _section("What the assistant says about the hotel, and whether it is right", lambda: ui_consult.ins_sections(ai, ins, only=("about", "accuracy", "head_to_head", "hypotheses")))
        _section("The hotels named most often across all the answers", lambda: ui_consult.ins_sections(ai, ins, only=("brand", "leaderboard", "niche", "alternatives")))
    _section("Every question and answer", lambda: ui_consult.all_answers(ai, log, ins))
    _section("How the questions were chosen", lambda: (ui_consult.market_card(ai.get("market")), ui_consult.question_plan_card(fa_res.get("question_plan"))))
    _section("Test it by hand in ChatGPT, Gemini and Copilot", lambda: ui_consult.manual_checklist_card(ai, fa_res["meta"].get("hotel", "")))
