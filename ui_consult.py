"""
Streamlit rendering of the consultant report.

Native components only. Third-party text (page extracts) goes through
md_safe(), and links are limited to http/https, so nothing read from a web
page can inject markup or load an image.
"""

import streamlit as st

from ai_insights import sentiment_label
import ui_theme
from ui_intel import df, md_safe, safe_url

PRI_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
LEVEL_ICON = {"strong": "🟢", "some": "🟡", "weak": "🟠", "none": "⚪"}
LEVEL_LABEL = {"strong": "Strongly supported", "some": "Some evidence", "weak": "Weak / unclear", "none": "No evidence found"}
STATE_ICON = {"missing": "🔴", "unclear": "🟠", "partial": "🟡"}
STATUS_ICON = {"present": "🟢", "could_improve": "🟡", "missing": "🔴", "incorrect": "🟠"}
BUCKET = {"access": ("Machine access", "Can AI and search crawlers reach the information?"),
          "understanding": ("Machine understanding", "Can the hotel, its facts and its amenities be understood?"),
          "content": ("Content gaps", "Is important traveller information missing?"),
          "authority": ("Authority and outside evidence", "Where might external validation be lacking?")}


def _path(u):
    from urllib.parse import urlparse
    p = urlparse(u or "")
    if p.netloc.endswith(("pagespeed.web.dev", "commoncrawl.org")):     # outside tools: show the tool, not a meaningless path
        return p.netloc
    return p.path or "/"


def _evidence(rows):
    for e in rows:
        quote = md_safe(e["snippet"][:240]) if e.get("snippet") else ""
        if e.get("url") and safe_url(e["url"]):
            st.markdown(f"- [{md_safe(_path(e['url']))}]({safe_url(e['url'])})" + (f": “{quote}”" if quote else ""))
        elif quote:
            st.markdown(f"- {quote}")


def rec_card(r, nested=False):
    """One recommendation in the Finding / Why / Evidence / Action / Example shape."""
    with st.container(border=True):
        st.markdown(f"**{md_safe(r['title'])}**")
        st.caption(f"{PRI_ICON[r['priority']]} {r['priority'].capitalize()} priority · effort: {r['effort']} · team: {r['team']} · "
                   f"confidence: {r['confidence'].lower()}")
        st.markdown(f"**What we found.** {md_safe(r['finding'])}")
        st.markdown(f"**Why it matters.** {md_safe(r['why'])}")
        if r["evidence"]:
            st.markdown("**Evidence**")
            _evidence(r["evidence"])
        st.markdown(f"**What to do.** {md_safe(r['action'])}")
        if r.get("page") and (r["page"].get("url") or r["page"].get("label")):
            p = r["page"]
            st.markdown("**Where.** " + (f"[{md_safe(p['label'])}]({safe_url(p['url'])})" if safe_url(p.get("url")) else md_safe(p["label"])))
        if r.get("additions"):
            st.markdown("**Add:**")
            for a in r["additions"]:
                st.markdown("- " + md_safe(a))
        if r.get("example"):
            st.markdown("**Example**")
            st.code(r["example"], language="html" if r["example"].lstrip().startswith("<") else None)
        detail = (r["technical"] or "No further technical detail.")
        if nested:      # Streamlit does not allow an expander inside an expander
            st.markdown("**Technical detail:** " + md_safe(detail))
            st.caption(f"Basis: {r['confidence']}. Success check: {r['success_check']}")
        else:
            with st.expander("Technical detail"):
                st.write(detail)
                st.caption(f"Basis: {r['confidence']}. Success check: {r['success_check']}")


# ------------------------------------------------------------------- overview

def coverage_banner(c):
    """Say plainly how much of the site was read - every 'missing' finding depends on it."""
    cov = c.get("coverage") or {}
    if not (cov.get("limited") or cov.get("text_only")):
        return
    why = "; ".join(f"{n} × {r}" for r, n in (cov.get("failure_reasons") or {}).items())
    head = "" if (cov.get("unreadable") or str(cov.get("note", "")).startswith("We could read")) else f"**Read {cov['pages_read']} of {cov['pages_attempted']} pages.** "
    msg = f"{head}{cov['note']}" + (f"  \nWhy pages failed: {why}." if why else "")
    (st.error if cov.get("unreadable") else st.warning if cov.get("limited") else st.info)(msg)


EVIDENCE_ICON = {"high": "\U0001F7E2", "medium": "\U0001F7E1", "low": "\U0001F534"}


def headline_strip(h):
    """The readiness score, how much of the model it rests on, and what was NOT measured - always together."""
    with st.container(border=True):
        c1, c2 = st.columns([1, 4], vertical_alignment="center")
        with c1:
            st.markdown(ui_theme.ring(h["score"], "of 100", size=124), unsafe_allow_html=True)
        with c2:
            st.markdown("**AI discoverability readiness** &nbsp;" + ui_theme.chip(h["badge"].capitalize(), "brand"), unsafe_allow_html=True)
            st.progress(min(max(h["coverage_pct"], 0), 100) / 100, text=f"Measurement coverage: {h['coverage_pct']:.0f}% of the full model assessed")
            st.caption(h["explanation"])
            if h["unassessed"]:
                st.markdown('<span class="hk-label">Not measured</span> &nbsp;' + " ".join(ui_theme.chip(f"{u['label']} · {u['weight']:g}%", "warn") for u in h["unassessed"]),
                            unsafe_allow_html=True)


PRI_CHIP = {"critical": "bad", "high": "bad", "medium": "warn", "low": ""}


def top_card(i, r):
    """A top action: the issue and why it matters at a glance, the exact action highlighted, the rest one click away."""
    with st.container(border=True):
        st.markdown(f"##### {i}. {md_safe(r['title'])}")
        st.markdown(" ".join([ui_theme.chip(f"{r['priority'].capitalize()} priority", PRI_CHIP.get(r["priority"], "")), ui_theme.chip(f"Effort: {r['effort']}"),
                              ui_theme.chip(f"Owner: {r['team']}"), ui_theme.chip(f"Confidence: {r['confidence'].lower()}"), ui_theme.chip(r["ref"])]), unsafe_allow_html=True)
        a, b = st.columns(2)
        a.markdown(f"**Issue.** {md_safe(_short(r['finding'], 300))}")
        b.markdown(f"**Why it matters.** {md_safe(_short(r['why'], 260))}")
        st.success(f"**Exact action.** {md_safe(_short(r['action'], 320))}", icon=":material/task_alt:")
        with st.expander("Evidence, expected outcome and example wording"):
            if r["evidence"]:
                st.markdown("**Evidence**")
                _evidence(r["evidence"][:1])
            st.markdown(f"**Expected outcome.** {md_safe(_short(r['expected_outcome'], 240))}")
            rec_card(r, nested=True)


def _short(text, n):
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    i = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(" "))
    return cut[: i if i > n * 0.5 else n].rstrip(" ;,.") + "..."


def overview(c, h=None):
    coverage_banner(c)
    if h:
        headline_strip(h)
    u = c["understanding"]
    st.markdown("#### AI currently understands this hotel as")
    if u["summary"]:
        st.info(u["summary"])
    else:
        st.warning("Too few pages could be read to say what automated systems could understand about this hotel.")
    st.caption(f"Based on {u['pages_read']} page(s) from the hotel's own website. " + u["note"])

    st.markdown("#### Readiness, measure by measure")
    st.caption("Eight separate measures, deliberately not blended into one score. Each shows how much evidence stands behind it: "
               "a high score on thin evidence is not the same as a high score on solid evidence.")
    ui_theme.bars([{"label": p["label"], "score": p["score"] if p["assessed"] else None,
                    "note": ((f"{(p.get('evidence') or {}).get('level', '?')} evidence" + (" \u00b7 provisional" if p["band"] == "provisional" else "")) if p["assessed"] else "not assessed this run")}
                   for p in c["profile"]])
    with st.expander("What drives each measure, and how sure we are"):
        for p in c["profile"]:
            ev = p.get("evidence") or {}
            st.markdown(f"**{p['label']}** &nbsp; " + (ui_theme.chip(f"{ev.get('level', '?')} evidence", {"high": "good", "medium": "warn", "low": "bad"}.get(ev.get("level"), "")) if p["assessed"] else ui_theme.chip("Not assessed")),
                        unsafe_allow_html=True)
            if p["assessed"] and ev.get("why"):
                st.caption(md_safe(ev["why"]))
            for d in p["drivers"][:3]:
                st.caption("\u2022 " + md_safe(d))

    recs = {r["id"]: r for r in c["recommendations"]}
    fixes = [recs[i] for i in c.get("required_fixes", [])]
    opps = [recs[i] for i in c.get("opportunity_recs", [])]
    top = [recs[i] for i in c["top_actions"]]
    st.markdown(f"#### The {len(top)} things most worth doing")
    st.caption("Chosen from the whole audit by one ranking model: business and reputation risk, how much travellers care, how much it affects "
               "discoverability and how sure we are - moderated by effort. Required fixes only. Nothing here is a guarantee about what any AI "
               "assistant will recommend.")
    if not top:
        st.success("Nothing in this audit met the bar for a required fix.")
    for i, r in enumerate(top, 1):
        top_card(i, r)

    t_fix, t_opp, t_quick, t_plan = st.tabs([f"Other required fixes ({max(len(fixes) - len(top), 0)})",
                                             f"Commercial opportunities ({len(c.get('opportunities', [])) + len(opps)})",
                                             f"Quick wins ({len(c['quick_wins'])})", "30 / 60 / 90-day plan"])
    with t_fix:
        st.caption("Wrong or conflicting information, missing guest information, crawl and accessibility problems, reputation risks and "
                   "entity problems.")
        rest = [r for r in fixes if r["id"] not in c["top_actions"]]
        if not rest:
            st.write("None beyond the top actions.")
        for r in rest:
            with st.expander(f"{PRI_ICON[r['priority']]} {r['title']}"):
                rec_card(r, nested=True)
    with t_opp:
        st.caption("Not defects. A weak signal matters only if the segment is one the hotel wants to attract.")
        for o in c.get("opportunities", []):
            with st.container(border=True):
                st.markdown(md_safe(o["statement"]))
                st.caption(o["suggestion"])
                _evidence(o["evidence"][:2])
        for r in opps:
            with st.expander(f"\U0001F4A1 {r['title']}"):
                rec_card(r, nested=True)
        if not c.get("opportunities") and not opps:
            st.write("No clear opportunity stood out.")
    with t_quick:
        st.caption("Low-effort improvements not already in the top list.")
        if c["quick_wins"]:
            df([{"Quick win": recs[i]["title"], "Where": (recs[i]["page"] or {}).get("label", ""),
                 "What to do": _short(recs[i]["action"], 190), "Priority": recs[i]["priority"]} for i in c["quick_wins"]])
        else:
            st.write("No further quick wins.")
    with t_plan:
        plan = c["plan"]
        st.caption("30 days: serious and quick items. 60 days: medium-effort required fixes. 90 days: opportunities and larger work. "
                   "Re-run the audit afterwards to check what changed.")
        p1, p2, p3 = st.columns(3)
        for col, key, title in ((p1, "30", "First 30 days"), (p2, "60", "Days 31-60"), (p3, "90", "Days 61-90")):
            with col:
                st.markdown(f"**{title}**")
                for rid in plan[key]:
                    r = recs[rid]
                    st.markdown(f"- {md_safe(r.get('short_title') or r['title'])} *({r['team']}, {r['ref']})*")
                if not plan[key]:
                    st.caption("-")
    if c["working"]:
        st.markdown("#### " + ("What we could establish without reading the website" if c.get("working_is_outside") else "What the hotel is already doing well"))
        for w in c["working"]:
            st.markdown("- " + md_safe(w["point"]))


# ------------------------------------------------------------ how AI sees it

def review_card(rs):
    """An indicative reading of public reviews and the hotel's replies. A sample with its limits stated; never scored."""
    st.markdown("##### Reviews and replies: an indicative snapshot")
    if not rs:
        st.caption("Not run for this report.")
        return
    if rs.get("status") != "ok":
        st.info(md_safe(rs.get("reason", "Not run.")))
        for n in (rs.get("not_found") or [])[:4]:
            st.caption("Not found: " + md_safe(n))
        return
    s = rs["summary"]
    st.caption("One AI model with web search read the review pages that appear in public search results. Every item below links to a page that was in "
               "those results; anything it could not confirm was dropped. This is a small, unrepresentative sample: it shows replies SEEN on reviews "
               "EXAMINED, not the hotel's reply rate. Reviews are paraphrased and nobody is named. It is not part of any score. "
               "The platforms prohibit automated collection by this tool; the searching is done by Anthropic's search service.")
    a, b, c = st.columns(3)
    a.metric("Reviews examined", s["examined"], help=f"{s['reviews_seen']} seen; {s['unclear']} where it could not tell whether the hotel replied")
    b.metric("With a reply from the hotel", f"{s['replied']} of {s['examined']}")
    c.metric("Critical reviews with a reply", f"{s['negative_replied']} of {s['negative_examined']}")
    if rs.get("platforms"):
        df([{"Platform": p["platform"], "Rating shown": "-" if p["rating"] is None else p["rating"],
             "Reviews": "-" if p["review_count"] is None else p["review_count"], "Page": p["url"]} for p in rs["platforms"]], link_cols=("Page",))
    rq = s.get("reply_quality") or {}
    labels = {"personal": "specific to the guest", "acknowledges": "thanks or apologises", "offers_action": "says what will be done", "signed": "signed by a role or team"}
    if any(v["judged"] for v in rq.values()):
        st.markdown('<span class="hk-label">How the replies were written (an AI reading)</span><br>' + " ".join(
            ui_theme.chip(f"{labels[k]}: {v['yes']} of {v['judged']}", "good" if v["yes"] / v["judged"] >= .6 else "warn" if v["yes"] / v["judged"] >= .34 else "bad")
            for k, v in rq.items() if v["judged"]), unsafe_allow_html=True)
    if s.get("praised") or s.get("criticised"):
        a_, b_ = st.columns(2)
        a_.markdown('<span class="hk-label">What positive reviews were about</span><br>' + (" ".join(ui_theme.chip(f"{t['topic']} · {t['reviews']}", "good") for t in s.get("praised", [])) or "-"), unsafe_allow_html=True)
        b_.markdown('<span class="hk-label">What critical or mixed reviews were about</span><br>' + (" ".join(ui_theme.chip(f"{t['topic']} · {t['reviews']}", "bad") for t in s.get("criticised", [])) or "-"), unsafe_allow_html=True)
    if s["tones"]:
        st.markdown("**Tone of the replies (an AI's reading):** " + ", ".join(f"{md_safe(k)} x{v}" for k, v in sorted(s["tones"].items(), key=lambda kv: -kv[1])))
    with st.expander(f"The {len(rs['items'])} reviews it could see"):
        df([{"Platform": i["platform"], "Review date": i["review_date"] or "-", "Review": i["sentiment"] or "-",
             "Hotel replied": {True: "yes", False: "no", None: "can't tell"}[i["owner_replied"]], "By": i["reply_by"] or "-",
             "Tone": i["reply_tone"] or "-", "What the reply said (paraphrase)": i["reply_summary"] or "-", "Page": i["url"]} for i in rs["items"]],
           link_cols=("Page",))
    for n in rs.get("not_found") or []:
        st.caption("Not found: " + md_safe(n))
    if rs.get("dropped"):
        st.caption(f"{rs['dropped']} item(s) the assistant reported were dropped because their pages were not among the search results.")


def _sentiment_chart(rows):
    """Net sentiment per hotel as diverging bars (green to the right, red to the left). Hotels never judged are left out."""
    import altair as alt
    data = [{"name": str(r["name"])[:34], "value": r["sentiment"], "me": bool(r["is_target"])} for r in rows if r.get("sentiment") is not None]
    if not data:
        st.caption("No sentiment could be judged: the hotels were named without enough said about them.")
        return
    order = [d["name"] for d in data]
    for d in data:
        d["label"] = f"{d['value']:+d}" if d["value"] else "0"
    base = alt.Chart(alt.Data(values=data)).encode(y=alt.Y("name:N", sort=order, title=None, axis=alt.Axis(labelLimit=240, ticks=False, domain=False, labelFontSize=12, labelColor=ui_theme.INK)))
    bar = base.mark_bar(cornerRadius=4, size=14).encode(
        x=alt.X("value:Q", title=None, scale=alt.Scale(domain=[-100, 100]), axis=alt.Axis(grid=True, gridColor="#EEF0F6", domain=False, ticks=False, labelColor=ui_theme.MUTED, values=[-100, 0, 100])),
        color=alt.condition(alt.datum.value >= 0, alt.value(ui_theme.GOOD), alt.value(ui_theme.BAD)), tooltip=[alt.Tooltip("name:N", title="Hotel"), alt.Tooltip("value:Q", title="Net sentiment")])
    txt = base.mark_text(align="left", dx=5, fontSize=12, fontWeight=600, color=ui_theme.INK).encode(x=alt.X("value:Q", scale=alt.Scale(domain=[-100, 100])), text=alt.Text("label:N"))
    for d in data:
        d["label"] = f"{d['value']:+d}" if d["value"] else "0"
    st.altair_chart((bar + txt).configure(background="rgba(0,0,0,0)").configure_view(stroke=None).properties(height=34 * len(data) + 28), width="stretch")


def _question_grid(rows):
    """Prompt performance: each question, whether the hotel was named in each answer (filled dot = named), the best position, and who was named."""
    import html
    kind = {"generic": ("Town-wide", ""), "niche": ("Niche market", "brand"), "direct": ("About the hotel", "")}
    out = []
    for m in rows:
        k, cls = kind.get(m["kind"], (m["kind"], ""))
        if m["kind"] in ("generic", "niche") and m.get("of"):
            res = ui_theme.dots(m["named"], m["of"]) + f'<span class="hk-muted">{m["named"]} of {m["of"]} answer{"" if m["of"] == 1 else "s"}</span>'
        elif m["kind"] == "direct":
            res = '<span class="hk-muted">asked about the hotel</span>'
        else:
            res = '<span class="hk-muted">n/a</span>'
        pos = f' &nbsp;<span class="hk-chip">best position {m["position"]}</span>' if m.get("position") else ""
        who = ", ".join(html.escape(str(h)) for h in (m.get("hotels_named") or [])[:4])
        why = f'<div class="hk-muted" style="font-size:.78rem;margin-top:.15rem">Why we asked: {html.escape(str(m["why"]))}</div>' if m.get("why") else ""
        angle = f' {ui_theme.chip(m["angle"])}' if m.get("angle") else ""
        out.append(f'<div class="hk-row"><div><div style="font-weight:600">{html.escape(str(m["question"]))}</div>{why}'
                   f'<div style="margin-top:.35rem">{ui_theme.chip(k, cls)}{angle}</div></div>'
                   f'<div style="white-space:nowrap">{res}{pos}</div>'
                   f'<div class="hk-muted" style="font-size:.82rem">{("Named: " + who) if who else "No hotels named"}</div></div>')
    st.markdown(f'<div class="hk-grid">{"".join(out)}</div>', unsafe_allow_html=True)


def _ins_sections(ai, ins):
    """The analysis of the sampled answers: brand ranking, prompts, sources, pages, why, perception, accuracy, head-to-head."""
    if not ins or ins.get("status") not in ("ok", "partial"):
        if ins and ins.get("reason"):
            st.caption(md_safe(ins["reason"]))
        return
    if ins.get("status") == "partial":
        st.caption(md_safe(ins.get("reason", "")))
    lb, sb = ins.get("leaderboard"), ins.get("scoreboard")
    br = ins.get("brand_ranking")
    if br and br.get("rows"):
        st.markdown("###### Brand ranking: the hotel and the hotels named most")
        st.caption("Counts describe this one sample, not the market.")
        ui_theme.note("Across every answer in this sample. **Coverage** is the share of answers that named the hotel; **position** is where it appeared in the assistant's list; "
                      "**sentiment** is the net of positive minus negative mentions (-100 to +100), an AI's reading of how each answer spoke of that hotel. "
                      "It describes this one sample, not the market.")
        a, b = st.columns(2)
        with a:
            st.markdown('<span class="hk-label">Coverage: share of answers naming the hotel</span>', unsafe_allow_html=True)
            ui_theme.ranked_chart([{"name": r["name"], "value": r["coverage_pct"], "is_target": r["is_target"]} for r in br["rows"]], fmt="{:.0f}%", domain_max=100)
        with b:
            st.markdown('<span class="hk-label">Net sentiment where named</span>', unsafe_allow_html=True)
            _sentiment_chart(br["rows"])
        with st.expander("Table view"):
            df([{"Place": r["place"], "": "YOU" if r["is_target"] else "", "Hotel": r["name"], "Coverage": f"{r['coverage_pct']}%",
                 "Average position": "-" if r["avg_rank"] is None else r["avg_rank"],
                 "Sentiment": "-" if r["sentiment"] is None else f"{r['sentiment']:+d} ({sentiment_label(r['sentiment'])})",
                 "Positive / neutral / negative": f"{r['positive']} / {r['neutral']} / {r['negative']}"} for r in br["rows"]])
    if lb and sb:
        st.markdown("###### Who the assistant recommends instead")
        st.markdown(" ".join([ui_theme.chip(f"Share of the names given: {sb['share']}%", "brand"), ui_theme.chip(f"Your place in that table: {sb['rank_in_table']} of {sb['table_size']}"),
                              ui_theme.chip("Average position when named: " + ("-" if sb["avg_rank"] is None else str(sb["avg_rank"])))]), unsafe_allow_html=True)
        st.caption("Hotels named across the generic 'where to stay' questions, with the reason the assistant gave. 'Share' is each hotel's part of all the hotel names given.")
        df([{"": "YOU" if r["is_target"] else "", "Hotel": r["name"], "Named in": f"{r['mentions']} of {r['of']} answers", "Share": f"{r['share']}%",
             "Average position": "-" if r["avg_rank"] is None else r["avg_rank"], "Sentiment": "-" if r.get("sentiment") is None else f"{r['sentiment']:+d}",
             "Why the assistant gave it": "; ".join(r["reasons"]) or "-"} for r in lb["rows"][:12]])
    nn = ins.get("niche")
    if nn:
        st.markdown("###### Where the hotel actually competes")
        st.caption("A hotel is chosen in its own market, not against every hotel in a city. These narrower questions were written from facts this audit holds about the "
                   "hotel (its location, price level, what it is known for). None names the hotel.")
        _question_grid(nn["questions"])
        if nn.get("leaderboard"):
            top = [r for r in nn["leaderboard"]["rows"] if not r["is_target"]][:6]
            if top:
                st.markdown('<span class="hk-label">Who the assistant names in those markets</span><br>' + " ".join(ui_theme.chip(f"{r['name']} · {r['mentions']} of {r['of']}") for r in top),
                            unsafe_allow_html=True)
    if ins.get("alternatives"):
        st.markdown("**The assistant's view of your competitive set** *(asked which hotels are similar)*: " + ", ".join(md_safe(h["name"]) for h in ins["alternatives"]))
    if ins.get("matrix"):
        st.markdown("###### Question by question")
        st.caption("A filled dot is an answer that named the hotel.")
        _question_grid([m for m in ins["matrix"] if m["kind"] != "niche"])
    if ins.get("sources"):
        st.markdown("###### Where the assistant got its information")
        st.caption("The sites it used and how often. Purple: this audit found the hotel there. Grey: not found there, which can also be a search gap.")
        ui_theme.ranked_chart([{"name": f"{x['domain']}", "value": x["answers"], "is_target": bool(x["hotel_evidenced"])} for x in ins["sources"][:10]], fmt=lambda v: f"{v:.0f} answer" + ("" if v == 1 else "s"))
        with st.expander("Table view"):
            icon = {True: "🟢 found", False: "🔴 not found", None: "⚪ not checked"}
            df([{"Site": x["domain"], "Type": x["kind"], "Used in": f"{x['answers']} answers", "Hotel there?": icon[x["hotel_evidenced"]]} for x in ins["sources"][:12]])
    if ins.get("pages"):
        st.markdown("###### The exact pages the assistant used")
        st.caption("The pages the assistant cited or searched, most cited first. 'Names the hotel' and 'Names a competitor' are judged only from the page title and the short "
                   "passage the assistant quoted, because we do not read these pages: 'no' means not visible in what we hold, not that the page leaves the hotel out.")
        df([{"Page": p["url"], "Site": p["domain"], "Title": p["title"] or "-", "Cited": p["cited"], "Used in": f"{p['questions']} question(s)",
             "Names the hotel": "yes" if p["names_hotel"] else "not seen", "Names a competitor": p["names_competitor"] or "not seen", "Your own site": "yes" if p["own_site"] else ""}
            for p in ins["pages"][:15]], link_cols=("Page",))
    exp = ins.get("explanation")
    if exp and exp.get("hypotheses"):
        st.markdown("###### Why the hotel may not be named: hypotheses")
        st.warning("The assistant cannot show its reasoning and neither can we. These are differences visible in the evidence below, offered as hypotheses to check, "
                   "not as causes.")
        st.markdown(md_safe(exp.get("summary", "")))
        for h in exp["hypotheses"]:
            with st.container(border=True):
                st.markdown(f"{md_safe(h['text'])} *(evidence {', '.join(h['evidence'])})*")
                if h.get("action"):
                    st.markdown(f"**Worth checking:** {md_safe(h['action'])}")
        with st.expander("The evidence these rest on"):
            for e in ins.get("ledger", []):
                st.markdown(f"**{e['id']}** {md_safe(e['text'])}")
    ab, pc = ins.get("about"), ins.get("perception")
    if ab and (ab.get("strengths") or ab.get("weaknesses")):
        st.markdown("###### What the assistant says about the hotel")
        a, b = st.columns(2)
        with a:
            st.markdown('<span class="hk-label">Positives it gave</span><br>' + (" ".join(ui_theme.chip(x, "good") for x in ab["strengths"][:6]) or '<span class="hk-muted">none</span>'), unsafe_allow_html=True)
        with b:
            st.markdown('<span class="hk-label">Drawbacks it gave</span><br>' + (" ".join(ui_theme.chip(x, "bad") for x in ab["weaknesses"][:6]) or '<span class="hk-muted">none</span>'), unsafe_allow_html=True)
        st.caption(f"Overall tone of its description: {ab.get('tone', 'unclear')} (an AI's reading).")
        if pc and pc.get("not_in_assistant_description"):
            st.info("Emphasised on your website but not in the assistant's description: " + ", ".join(md_safe(x) for x in pc["not_in_assistant_description"]) + ".")
    acc = ins.get("accuracy")
    if acc and (acc["rows"] or acc["unchecked"]):
        st.markdown("###### Is what it said correct?")
        if acc["rows"]:
            df([{"Detail": r["claim"], "The assistant said": r["assistant_says"], "Our record": r["our_record"], "Source of our record": r["source"] or "-",
                 "Result": {"matches": "🟢 matches", "differs": "🟠 differs"}[r["status"]]} for r in acc["rows"]])
        st.caption(f"{acc['unchecked']} other statement(s) could not be checked against anything we hold, which is not the same as being wrong.")
    h2h = ins.get("head_to_head")
    if h2h:
        with st.expander(f"Head to head: the hotel against {h2h['rival']}"):
            st.markdown(md_safe(h2h["answer"]))
            if h2h.get("domains"):
                st.caption("Sources: " + ", ".join(md_safe(d) for d in h2h["domains"][:8]))
    for n in ins.get("notes") or []:
        st.caption(md_safe(n))


def market_card(m):
    """How we read the hotel's market (price level, kind, audiences), which is what decides the questions put to the assistant."""
    if not m:
        return
    with st.container(border=True):
        st.markdown(f"**How we read this hotel's market:** {md_safe(m['summary'])}")
        chips = []
        if m.get("tier"):
            chips.append(ui_theme.chip(f"Price level: {m['tier']['label']}", "brand"))
        if m.get("airport"):
            chips.append(ui_theme.chip(f"{m['airport']['name']} · {m['airport']['km']:g} km"))
        if m.get("district"):
            chips.append(ui_theme.chip(f"Neighbourhood: {m['district']}"))
        for a in m.get("audiences", [])[:8]:
            chips.append(ui_theme.chip(a["label"], "good" if a["level"] == "stated" else "brand" if a["level"] == "strong" else ""))
        st.markdown(" ".join(chips), unsafe_allow_html=True)
        why = [f"{a['label']}: {a['why']}" for a in m.get("audiences", [])[:8]]
        if m.get("tier"):
            why.insert(0, f"Price level: {m['tier']['why']}")
        st.caption("The questions below were written for this market, not for 'the best hotels in town'. Why each applies: " + " · ".join(md_safe(w) for w in why)
                   + ". Brand level is an inference; correct it with 'Who is the hotel for?' when you run the audit.")


def ai_sample_card(ai, ins=None):
    """What one AI model said when asked ordinary traveller questions. A sample with its limits stated, never a score."""
    st.markdown("##### What an AI assistant said (a sample)")
    if not ai:
        st.caption("Not run for this report.")
        return
    if ai.get("status") != "ok":
        st.info(md_safe(ai.get("reason", "Not run.")))
        return
    s = ai["summary"]
    reps = s.get("repeats", 1)
    asked_txt = (f"{s['asked']} questions" if reps <= 1 else f"{s.get('questions', s['asked'])} different questions ({s['asked']} answers, the town-wide and niche ones asked {reps} times each so one odd answer does not decide it)")
    st.caption(f"One model ({md_safe(ai.get('model', ''))}) with live web search was asked {asked_txt} on {md_safe(ai.get('run_at', ''))}. "
               "This is a sample: answers change between runs and between assistants, and it is not a ranking. It is not part of any score.")
    market_card(ai.get("market"))
    sb = (ins or {}).get("scoreboard") or {}
    br = (ins or {}).get("brand_ranking") or {}
    n_cols = 3 + (1 if s.get("niche_asked") else 0) + (1 if sb.get("coverage_pct") is not None else 0)
    cols = st.columns(n_cols)
    k = 0
    if sb.get("coverage_pct") is not None:
        cols[k].metric("Coverage", f"{sb['coverage_pct']}%", help=f"the hotel was named in {sb.get('named', 0) + sb.get('niche_named', 0)} of {sb.get('asked_all', 0)} answers")
        k += 1
    cols[k].metric("Town-wide", f"{s['generic_named']} of {s['generic_asked']}", help="Named in this many of the answers to the general 'where to stay' questions")        # answers, not questions, once repeats are asked
    k += 1
    if s.get("niche_asked"):
        cols[k].metric("Niche markets", f"{s['niche_named']} of {s['niche_asked']}", help="Named in this many answers to narrower questions drawn from the hotel's location, price level and what it is known for")
        k += 1
    if sb.get("coverage_pct") is not None:
        cols[k].metric("Sentiment", "-" if sb.get("sentiment") is None else f"{sb['sentiment']:+d}", help="net positive minus negative, where the hotel was named")
        k += 1
    cols[k].metric("Known directly", help="whether the assistant knew the hotel when asked about it by name", value={True: "Yes", False: "No", None: "n/a"}[s["direct_known"]])
    st.markdown(" ".join([ui_theme.chip("Own website cited: " + ("yes" if s["own_site_cited"] else "no"), "good" if s["own_site_cited"] else ""),
                          ui_theme.chip(f"Your place: {sb['place']} of {len(br.get('rows', []))}") if sb.get("place") else ""]), unsafe_allow_html=True)
    osr = (ins or {}).get("own_site")
    if osr and osr["answers"]:
        inst = ", ".join(f"{md_safe(x['domain'])} ({x['cited']})" for x in osr["instead"][:4])
        msg = (f"**Your own website was among the sources in {osr['own_cited']} of {osr['answers']} answers** to the town and market questions."
               + (f" Pages from other sites were cited instead: {inst}." if inst else "")
               + " If an answer is not on your site in plain language, the assistant finds it elsewhere and cites elsewhere.")
        (st.success if osr["own_cited"] / osr["answers"] >= 0.5 else st.info)(msg, icon=":material/link:")
    if s["top_domains"]:
        st.markdown("**Sources the assistant relied on:** " + ", ".join(md_safe(d) for d in s["top_domains"]))
    if ai.get("partial"):
        st.caption(md_safe(ai.get("reason", "")))
    _ins_sections(ai, ins)
    st.markdown("###### All the answers")
    for i in ai["items"]:
        mark = {True: "named", False: "not named", None: "no answer"}[i["mentioned"]]
        with st.expander(f"{i['text']}" + (f" (answer {i['repeat']} of {i['repeats']})" if i.get("repeats", 1) > 1 else "") + f" - hotel {mark}"
                         + (f" (#{i['position']} in the list)" if i.get("position") else "")):
            st.markdown(md_safe(i["answer"] or "(no answer text)"))
            if i["domains"]:
                st.caption("Sources: " + ", ".join(md_safe(d) for d in i["domains"][:8]))
            cited = [p for p in i.get("pages") or [] if p.get("cited")][:5]
            if cited:
                st.caption("Pages it cited: " + "; ".join(f"[{md_safe(p['title'] or p['url'][:50])}]({safe_url(p['url'])})" for p in cited if safe_url(p["url"])))


def ai_view(c, ai=None, ins=None):
    ai_sample_card(ai, ins)
    u = c["understanding"]
    st.caption("What automated systems could learn from this hotel's own pages, where they may be less certain, and where each gap should be fixed. "
               "Built only from wording found on the pages read.")
    a, b = st.columns(2)
    with a:
        st.markdown("##### Strong signals")
        for s in u["strong_signals"] or ["(none stood out)"]:
            st.markdown("- " + md_safe(s))
    with b:
        st.markdown("##### Weak or unclear signals")
        for w in u["weak_signals"] or [{"label": "(none)", "why": ""}]:
            st.markdown(f"- {md_safe(w['label'])} - *{md_safe(w['why'])}*" if w["why"] else "- " + md_safe(w["label"]))

    st.markdown("##### Traveller searches this content supports")
    st.caption("Which kinds of hotel search the existing pages give evidence for, and why each was classed that way. "
               "Not every type matters to every hotel.")
    shown = [r for r in c["intents"] if r["level"] != "none"]
    order = {"strong": 0, "some": 1, "weak": 2}
    df([{"Traveller type": r["label"], "Evidence": f"{LEVEL_ICON[r['level']]} {LEVEL_LABEL[r['level']]}", "Pages": r["pages"],
         "Why": r["reason"], "Page": (r["evidence"][0]["url"] if r["evidence"] else "")}
        for r in sorted(shown, key=lambda r: order[r["level"]])], link_cols=("Page",))
    none = [r["label"] for r in c["intents"] if r["level"] == "none"]
    if none:
        st.caption("No evidence found (may simply not apply to this hotel): " + ", ".join(none) + ".")
    st.caption("A weak signal is not automatically a problem: it matters only if the hotel wants to attract that audience. "
               "See Commercial opportunities on the Overview.")

    st.markdown("##### Questions AI may struggle to answer")
    st.caption("Traveller questions the pages leave unclear or unanswered - only those that apply to this hotel, with where to add each answer.")
    if not c["questions"]:
        if (c.get("coverage") or {}).get("unreadable"):
            st.info("Not assessed: the website could not be read, so nothing can be said about this either way.")
        else:
            st.success("Nothing important is unclear: the common traveller questions are answered on the pages read.")
    for q in c["questions"]:
        with st.expander(f"{STATE_ICON[q['state']]} {q['question']}"):
            st.markdown(f"**Status:** {q['state']}" + (f" - the pages already cover: {md_safe(', '.join(q['found']))}" if q["found"] else ""))
            if q["missing"]:
                st.markdown("**Not clearly stated:** " + md_safe(", ".join(q["missing"])))
            if q["evidence"]:
                st.markdown("**What the pages say now**")
                _evidence(q["evidence"])
            w = q["where"]
            st.markdown("**Where to add it:** " + (f"[{md_safe(w['label'])}]({safe_url(w['url'])})" if safe_url(w["url"]) else md_safe(w["label"]))
                        + f" - {md_safe(w['reason'])}")
            if q.get("example"):
                st.markdown("**Example wording** *(fill in the brackets with your real details)*")
                st.code(q["example"], language=None)

    st.markdown("##### Location")
    loc = c["location"]
    if loc["items"]:
        df([{"Place": i["place"] or i["label"], "Type": i["label"],
             "On the website": {"stated": "🟢 described with a distance/time", "mentioned_no_distance": "🟡 mentioned, no distance",
                                "not_mentioned": "⚪ not mentioned"}[i["state"]],
             "What to do": i["suggestion"], "Page": (i["evidence"][0]["url"] if i["evidence"] else "")} for i in loc["items"]], link_cols=("Page",))
    else:
        st.info("The pages read don't tie the hotel to any named transport link, airport or landmark, and no nearby places could be mapped.")
    st.caption(loc["note"])

    if c["hidden"]:
        st.markdown("##### Strengths that are easy to miss")
        for h in c["hidden"]:
            with st.container(border=True):
                st.markdown(md_safe(h["finding"]))
                st.caption("Suggestion: " + h["suggestion"])
                _evidence(h["evidence"])
    st.markdown("##### Consistency across the hotel's own pages")
    if c["consistency"]:
        for k in c["consistency"]:
            with st.container(border=True):
                st.markdown(f"{PRI_ICON[k['severity']]} **{md_safe(k['title'])}**")
                for v in k["values"][:4]:
                    link = f" ([{md_safe(_path(v['url']))}]({safe_url(v['url'])}))" if safe_url(v.get("url")) else ""
                    st.markdown(f"- {md_safe(v['value'][:150])}{link}")
                st.caption(k["detail"] + " **Fix:** " + k["fix"])
    else:
        st.success("No contradictions found between the pages read (check-in times, phone numbers, address, hotel name, hours, offers).")


# --------------------------------------------------------------- fix the site

def web_card(web):
    """How automated visitors meet the site: AI-crawler policy, Common Crawl, llms.txt, PageSpeed. Each says plainly if it wasn't measured."""
    if not web:
        return
    st.markdown("##### How crawlers and phones meet the website")
    st.caption("Four free checks. None of them shows what any AI assistant says about the hotel; they show whether the door is open and how fast it opens.")
    pol = web.get("ai_policy") or {}
    with st.container(border=True):
        st.markdown("**AI crawlers and robots.txt**")
        st.markdown(md_safe(pol.get("summary", "")))
        for key, label in (("training", "Training"), ("search", "AI search"), ("user", "Live look-up")):
            g = (pol.get("groups") or {}).get(key)
            if g:
                st.markdown(f"- {label} ({md_safe(g['what'].lower())}): "
                            + (("asked to stay away: " + ", ".join(g["blocked"])) if g["blocked"] else "not singled out"))
        st.caption(pol.get("caveat", ""))
    cc = web.get("commoncrawl") or {}
    with st.container(border=True):
        st.markdown("**Common Crawl (public web archive behind much AI training data)**")
        if cc.get("status") == "ok":
            for i in cc["items"]:
                c = i["counts"]
                st.markdown(f"- {i['crawl']}: {i['captures']}{'+' if i['capped'] else ''} capture(s) - {c['ok']} readable, {c['refused']} refused, "
                            f"{c['redirect']} redirect(s), {c['error']} error(s)" + (f"; robots.txt answered HTTP {i['robots_status']}" if i.get("robots_status") else ""))
            if cc.get("state") == "refused":
                st.warning("The site answered the archive's crawler with 'forbidden' or 'too many requests' rather than its pages. "
                           "See the Machine access findings below.")
        else:
            st.markdown(("ℹ️ " if cc.get("status") != "no_results" else "") + md_safe(cc.get("reason", "Not assessed.")))
        st.caption("Being in the archive is not evidence that any AI model knows or recommends the hotel.")
    ll = web.get("llms_txt") or {}
    with st.container(border=True):
        st.markdown("**llms.txt**")
        if ll.get("present"):
            st.markdown(f"🟢 The site publishes one ({ll.get('bytes', 0)} bytes, {ll.get('link_count', 0)} link(s)).")
        else:
            st.markdown(md_safe(ll.get("reason", "Not assessed.")))
        st.caption(ll.get("note", ""))
    ps = web.get("pagespeed") or {}
    with st.container(border=True):
        st.markdown("**Mobile speed and accessibility (Google PageSpeed Insights)**")
        if ps.get("status") == "ok":
            sc = ps["scores"]
            cols = st.columns(4)
            for col, (k, label) in zip(cols, (("performance", "Performance"), ("accessibility", "Accessibility"), ("seo", "SEO"), ("best-practices", "Best practice"))):
                col.metric(label, "n/a" if sc.get(k) is None else f"{sc[k]}/100")
            if ps.get("metrics"):
                st.markdown("; ".join(f"{md_safe(m['label'])}: {md_safe(m['value'])}" for m in ps["metrics"]))
            if ps.get("weak"):
                st.markdown("**Main things Google flagged:** " + "; ".join(md_safe(w["title"]) for w in ps["weak"][:5]))
            st.caption("A lab test of the homepage only, on a simulated mid-range phone. Scores vary run to run and are not what every guest experiences."
                       + (f" Real-user data for the site: {ps['field_category'].lower()}." if ps.get("field_category") else ""))
        else:
            st.markdown("ℹ️ " + md_safe(ps.get("reason", "Not assessed.")))


def fix_site(c, web=None):
    web_card(web)
    st.caption("The technical side, in four separate groups because they need different people and different fixes.")
    for key, (title, q) in BUCKET.items():
        rows = [f for f in c["machine"] if f["bucket"] == key]
        issues = [f for f in rows if f["status"] == "issue"]
        st.markdown(f"##### {title}")
        st.caption(q)
        if not rows:
            st.caption("Nothing to report.")
        for f in sorted(rows, key=lambda f: {"issue": 0, "info": 1, "ok": 2}[f["status"]]):
            icon = {"issue": PRI_ICON.get(f["severity"], "🟠"), "info": "🔵", "ok": "🟢"}[f["status"]]
            if f["status"] == "ok":
                st.markdown(f"{icon} {md_safe(f['title'])}")
                continue
            with st.expander(f"{icon} {f['title']}"):
                st.markdown(md_safe(f["detail"]))
                if f["consequence"]:
                    st.markdown(f"**Why it matters:** {md_safe(f['consequence'])}")
                if f["fix"]:
                    st.markdown(f"**What to do:** {md_safe(f['fix'])}")
                _evidence(f["evidence"])
                st.caption(f"Basis: {f['confidence'].lower()}")
        if not issues and rows:
            st.caption("No problems found in this group.")
    sd = c["structured"]
    st.markdown("##### Structured data")
    st.caption(sd["caution"])
    df([{"Item": i["item"], "Status": f"{STATUS_ICON[i['status']]} {i['status'].replace('_', ' ')}", "Detail": i["detail"],
         "Advice": i["advice"], "Confidence": i["confidence"] + (" (optional)" if i["optional"] else "")} for i in sd["items"]])
    with st.expander(f"All {len(c['recommendations'])} recommendations, grouped"):
        for cat, (title, _q) in BUCKET.items():
            rs = [r for r in c["recommendations"] if r["category"] == cat]
            if not rs:
                continue
            st.markdown(f"**{title}** ({len(rs)})")
            for r in rs:
                with st.expander(f"{PRI_ICON[r['priority']]} {r['title']}"):
                    rec_card(r, nested=True)
