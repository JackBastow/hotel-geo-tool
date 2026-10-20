"""
Streamlit rendering of the consultant report.

Native components only. Third-party text (page extracts) goes through
md_safe(), and links are limited to http/https, so nothing read from a web
page can inject markup or load an image.
"""

try:
    import streamlit as st
except ImportError:        # the Flask site draws these screens with htmlst.py instead of Streamlit
    from htmlst import st

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
        st.caption(f"{PRI_ICON[r['priority']]} {r['priority'].capitalize()} priority · effort: {r['effort']} · owner: {r.get('owner') or r['team'].capitalize()} · "
                   f"{r.get('confidence_label') or r['confidence']}")
        st.markdown(f"**Issue.** {md_safe(r['finding'])}")
        if r["evidence"]:
            st.markdown("**Evidence**")
            _evidence(r["evidence"])
        st.markdown(f"**Why it matters.** {md_safe(r['why'])}")
        st.markdown(f"**Action.** {md_safe(r['action'])}")
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


def understanding_block(c):
    """What AI currently understands the hotel to be, and the eight readiness measures with how sure we are of each."""
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


def overview(c, h=None):
    coverage_banner(c)
    if h:
        headline_strip(h)
    understanding_block(c)

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

def listing_checks_card(lc):
    """What each travel site shows about the hotel against the hotel's own site, and listings still carrying a former name. Read from quoted passages only."""
    st.markdown("##### What the travel sites show, against your own site")
    if not lc:
        st.caption("Not checked for this report: the listing lookup returned no quoted passages (it needs the AI key and the hotel's name and town).")
        return
    st.caption("Read from short passages quoted in public search results, not from the platforms' own pages (their terms prohibit automated reading). A difference is worth "
               "checking: the listing may be right and your site out of date, or the other way round. A fact a listing does not show is simply not shown here.")
    sm = lc["summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Listings quoted", sm["platforms_quoted"])
    c2.metric("Facts compared", sm["compared"])
    c3.metric("Differences", sm["differs"])
    if lc["rows"]:
        icon = {"matches": "🟢 matches", "differs": "🟠 differs"}
        df([{"Platform": r["platform"], "Fact": r["fact"], "The listing shows": r["listing_says"], "Your site says": r["site_says"], "Result": icon[r["status"]],
             "Listing": r["url"]} for r in sorted(lc["rows"], key=lambda r: (r["status"] != "differs", r["platform"]))], link_cols=("Listing",))
    elif sm["platforms_quoted"]:
        st.caption("The quoted passages did not show a fact your own site also states, so nothing could be compared.")
    for h in lc.get("former_name") or []:
        st.warning(f"**{md_safe(h['platform'])} still shows a former name, '{md_safe(h['name'])}'** (page title: {md_safe(h['title'] or 'not shown')}). "
                   "After a rebrand the old name lingers in listings and in AI answers.")


def reddit_card(rd):
    """What Reddit shows about the hotel and the town, and whether AI answers cite it. From public search results and the sampled answers, not from Reddit itself."""
    st.markdown("##### Reddit")
    st.caption("Reddit is one of the sources AI assistants cite most for where-to-stay questions. It cannot be read directly (access is blocked and the official API is paid), so this shows "
               "what one search of Reddit's public pages and the sampled AI answers turned up. A thread that search cannot see is not counted, so 'none found' never means 'nobody talks about the hotel'.")
    if not rd or rd.get("status") != "ok":
        st.info((rd or {}).get("reason") or "Reddit was not checked for this report: it needs the AI key and the hotel's name and town.")
        return
    sm = rd["summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Threads naming the hotel", "-" if sm["hotel_mentioned"] is None else sm["hotel_threads"], help="Found by searching Reddit's public pages")
    c2.metric("Traveller threads about the town", sm["town_threads"], help="Where-to-stay threads that turned up in the same searches")
    c3.metric("Sampled AI answers citing Reddit", f"{sm['ai_cited_reddit']} of {sm['ai_answers']}" if sm["ai_answers"] else "-", help="From the AI answers collected in this audit")
    if sm["hotel_mentioned"] is False:
        st.info("None of the threads found names the hotel. That is what these searches saw, not proof that it is never discussed.")

    def table(rows, title):
        if rows:
            st.markdown(f"###### {title}")
            tone = {"positive": "🟢 positive", "mixed": "🟠 mixed", "critical": "🔴 critical", "no clear tone": "no clear tone", None: ""}
            df([{"Subreddit": "r/" + t["subreddit"], "Thread": t["title"], "Tone (rule-based)": tone.get(t["tone"], ""), "What the search quoted": t["passage"][:220], "Link": t["url"]} for t in rows],
               link_cols=("Link",))
    table(rd.get("hotel_threads"), "Threads that name the hotel")
    table(rd.get("ai_threads"), "Reddit threads the AI assistant cited in its answers")
    table(rd.get("town_threads"), "Traveller threads about the town found by search")
    with st.expander("How to take part without it backfiring"):
        st.markdown("- Answer real questions in the town's subreddit from an account that says it is the hotel, and read the subreddit's rules on promotion first.\n"
                    "- Correct wrong facts (prices, facilities, location) politely and once.\n"
                    "- Never post as a guest, seed reviews, buy upvotes or ask for a thread to be removed: Reddit bans for it, and assistants learn to discount it.\n"
                    "- Do not offer anything in return for a post or a changed comment.")


def _pack_public(p):
    """The numbers from a review export: counts and rates only (this is what is saved with the report)."""
    n = p["reviews"]
    span = (f"{p['first_date']} to {p['last_date']}" if p.get("first_date") else "dates not found")
    st.caption(f"Every figure below is for the {n} review(s) in the file supplied ({span}), not for every review the hotel has on every platform.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reviews analysed", n, help=f"Average rating {p['avg_rating']} out of 5" if p.get("avg_rating") is not None else None)
    c2.metric("Reply rate", "-" if p.get("reply_rate") is None else f"{p['reply_rate']}%", help="Reviews in the file with a reply from the hotel" if p.get("has_replies_column") else "The file has no reply column")
    c3.metric("Critical reviews unanswered", "-" if p.get("critical_unanswered") is None else f"{p['critical_unanswered']} of {p['critical']}", help="Rated 2.5 or below out of 5, with no reply")
    rt = p.get("response_time") or {}
    c4.metric("Median time to reply", "-" if rt.get("median_days") is None else f"{rt['median_days']:g} days",
              help=f"{rt['measured']} replies had both dates" if rt.get("measured") else "Needs a review date and a reply date in the file")
    if p.get("latest_review_age_days") is not None and p["latest_review_age_days"] > 120:
        st.info(f"The latest review in this file is {p['latest_review_age_days'] // 30} months old. Recent reviews matter most; check the export covers the latest period.")
    if p.get("has_replies_column"):
        a, b = st.columns(2)
        with a:
            st.markdown('<span class="hk-label">Reply rate by platform</span>', unsafe_allow_html=True)
            ui_theme.ranked_chart([{"name": f"{k} ({v['reviews']})", "value": v["rate"] or 0, "is_target": False} for k, v in p["platforms"].items()][:8], fmt="{:.0f}%", domain_max=100)
        with b:
            st.markdown('<span class="hk-label">Reply rate by rating</span>', unsafe_allow_html=True)
            names = {"critical": "Critical (2.5 or below)", "mixed": "Mixed", "positive": "Positive (4 or above)"}
            ui_theme.ranked_chart([{"name": f"{names[k]} ({v['reviews']})", "value": v["rate"] or 0, "is_target": k == "critical"} for k, v in p["by_rating"].items() if v["reviews"]], fmt="{:.0f}%", domain_max=100)
        q = p.get("reply_quality") or {}
        labels = {"personal": "specific to the guest", "acknowledges": "thanks or apologises", "offers_action": "says what will be done", "signed": "signed by a role or team"}
        chips = [ui_theme.chip(f"{labels[k]}: {v['yes']} of {v['judged']}", "good" if v["yes"] / v["judged"] >= .6 else "warn" if v["yes"] / v["judged"] >= .34 else "bad") for k, v in q.items() if v["judged"]]
        t = p.get("templates") or {}
        if t.get("pct") is not None and t.get("replies_compared"):
            chips.append(ui_theme.chip(f"in repeated templates: {t['in_repeated_templates']} of {t['replies_compared']} ({t['pct']}%)", "bad" if t["pct"] >= 40 else "warn" if t["pct"] >= 20 else "good"))
        if rt.get("within_3_days_pct") is not None:
            chips.append(ui_theme.chip(f"within 3 days: {rt['within_3_days_pct']}%", "good" if rt["within_3_days_pct"] >= 70 else "warn"))
        st.markdown('<span class="hk-label">How the replies were written (a rule-based reading)</span><br>' + " ".join(chips), unsafe_allow_html=True)
    state = {"answered": "your site states it", "partial": "your site only partly states it", "not_found": "your site does not state it", "needs_checking": "your site only mentions it"}
    a, b = st.columns(2)
    for col, rows, label, kind, base in ((a, p.get("praised", []), "What guests praise", "good", p.get("positive_reviews")), (b, p.get("criticised", []), "What guests criticise", "bad", p.get("critical_reviews"))):
        with col:
            st.markdown(f'<span class="hk-label">{label} (share of {base or 0} reviews)</span><br>' + (" ".join(
                ui_theme.chip(f"{r['topic']} · {r['reviews']} ({r['pct']}%)" + (f" · {state[r['site']]}" if r.get("site") in state else ""),
                              "warn" if kind == "good" and r.get("site") in ("not_found", "partial", "needs_checking") else kind) for r in rows) or "-"), unsafe_allow_html=True)
    if len(p.get("trend", [])) >= 2:
        import pandas as pd
        st.markdown('<span class="hk-label">Average rating by month (out of 5)</span>', unsafe_allow_html=True)
        ui_theme.lines_chart(pd.DataFrame({"Average rating": [t["avg_rating"] for t in p["trend"]]}, index=[t["month"] for t in p["trend"]]), height=200)
        st.caption("Reviews per month: " + ", ".join(f"{t['month']} {t['reviews']}" for t in p["trend"]))


def review_pack_card(report, on_applied=None):
    """Upload the hotel's own review export; analyse it, fold the result into the report, and show it."""
    import hashlib
    import review_pack as rp
    st.markdown("##### The hotel's own reviews: upload an export")
    st.caption("Booking.com, Tripadvisor, Google and Expedia all let the hotel export its reviews. Upload that file and every review and reply in it is analysed, instead of the handful "
               "that public search shows. Reviewer names are never read. The text of the reviews is analysed in this session and is not saved: only counts and rates are kept with the report.")
    with st.expander("Where to find the export"):
        st.markdown("- **Booking.com:** Extranet, Guest reviews, Download (a spreadsheet of review scores, positive and negative comments and your replies).\\n"
                    "- **Tripadvisor:** Management Center, Reviews, export (or copy the reviews into a spreadsheet).\\n"
                    "- **Google:** Business Profile, Reviews (export through Google Takeout, or copy into a spreadsheet).\\n"
                    "- **Expedia:** Partner Central, Guest experience, Reviews, Download.\\n"
                    "- **Any spreadsheet** works if it has a rating or a review text, and, where you have them, a reply and the dates. Column names are recognised in English.")
    up = st.file_uploader("Review export (.csv or .xlsx)", type=["csv", "xlsx"], key="rp_upload")
    plat = st.text_input("Platform, if the file does not say (for example Booking.com)", key="rp_platform")
    run_key = report["meta"]["run_at"]
    state = st.session_state.get("rp_state")
    if up is not None:
        data = up.getvalue()
        h = hashlib.sha1(data + plat.strip().encode()).hexdigest()
        if not state or state["hash"] != h or state["run"] != run_key:
            rows, err = rp.read_table(data, up.name)
            if err:
                st.error(err)
                return
            mapping = rp.map_columns(list(rows[0]))
            if not any(mapping.get(k) for k in ("rating", "text", "reply", "positive", "negative")):
                st.error("No rating, review or reply column was recognised. The columns in the file are: " + ", ".join(md_safe(c) for c in list(rows[0])[:20]) + ".")
                return
            res = rp.analyse(rp.normalise(rows, mapping, plat.strip()), report["meta"]["hotel"], rp.site_states_from(report.get("guest_questions")))
            if not res:
                st.error("No reviews could be read from the file.")
                return
            rp.apply(report, res["public"])
            st.session_state["rp_state"] = {"hash": h, "run": run_key, "res": res, "mapping": mapping}
            if on_applied:
                on_applied(report)
            st.rerun()
        state = st.session_state["rp_state"]
    res = state["res"] if state and state["run"] == run_key else None
    if res is None and report.get("review_pack"):
        _pack_public(report["review_pack"])
        st.caption("Upload the file again to see the unanswered critical reviews and starting drafts, which are not saved.")
        return
    if res is None:
        return
    used = ", ".join(f"{k}: '{md_safe(v)}'" for k, v in state["mapping"].items())
    st.caption("Columns used: " + used + ".")
    st.success("The Reviews & Reputation score, the plan and the readiness figure now include this file.", icon=":material/check_circle:")
    _pack_public(res["public"])
    un = res["private"]["unanswered"]
    if un:
        st.markdown(f"###### Critical reviews still unanswered ({res['public']['critical_unanswered']}), newest first")
        st.caption("Shown only to you, in this session, and not saved. Each draft is a skeleton to finish: it states only what the review raised and leaves the facts in [brackets]. "
                   "Never offer anything in return for a changed review.")
        for i, r in enumerate(un):
            with st.expander(f"{r['date'] or 'undated'} · {r['platform']} · {r['rating']:g} out of 5" + (f" · {', '.join(r['topics'])}" if r["topics"] else "")):
                st.markdown(md_safe(r["text"] or "(no text)"))
                st.text_area("Draft reply to finish", r["draft"], height=210, key=f"rp_draft_{i}")
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "platform", "rating", "topics", "review", "draft reply"])
        for r in un:
            w.writerow([r["date"], r["platform"], r["rating"], "; ".join(r["topics"]), r["text"], r["draft"]])
        st.download_button("Download the unanswered reviews and drafts (.csv)", buf.getvalue(), file_name="unanswered-critical-reviews.csv", mime="text/csv", on_click="ignore")
    elif res["public"].get("has_replies_column"):
        st.success("Every critical review in the file has a reply.")


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
        _question_grid([m for m in ins["matrix"] if m["kind"] not in ("niche", "custom")])
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
        if m.get("venue"):
            st.caption(f"Near a venue: the hotel's own pages put {md_safe(m['venue']['name'])} close ({md_safe(m['venue']['distance'])}).")
        if m.get("anchors"):
            st.caption("**Places the questions are built around:** " + " · ".join(f"{md_safe(a['name'])} ({md_safe(a.get('distance') or (str(a['km']) + ' km'))}, {md_safe(a['source'])})" for a in m["anchors"][:3]))
        if m.get("skipped"):
            st.caption("**Considered but not asked, because the hotel's kind does not support it:** " + " · ".join(f"{md_safe(x['label'])}: {md_safe(x['why'])}" for x in m["skipped"]) + ". Add any of these as your own prompt if you want them tested.")


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
    st.caption(f"One model ({md_safe(ai.get('model', ''))}) with live web search" + (f", searching as if from {md_safe(ai['search_country'])}," if ai.get("search_country") else "") + f" was asked {asked_txt} on {md_safe(ai.get('run_at', ''))}. "
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
    for n in c.get("consistency_notes") or []:
        st.caption("Seen, and not flagged: " + md_safe(n["title"]) + ". " + md_safe(n["detail"]) + " " + "; ".join(f"{md_safe(v['value'][:90])} ({md_safe(_path(v['url']))})" for v in n["values"][:3] if v.get("url")))


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


# ----------------------------------------------------------- scoring, traveller requirements, outside sources, booking, competitors, AI test log

REQ_ICON = {"confirmed": "🟢 Confirmed", "partial": "🟡 Partially confirmed", "missing": "🔴 Missing", "unknown": "⚪ Unknown", "not_offered": "⚪ Stated as not available"}
EXT_ICON = {"verified": "🟢 Verified", "identified": "🟢 Identified, not read", "contradicts": "🔴 Contradicts the website", "unclear": "🟡 Found, identity unclear", "limited": "🟡 Found, limited coverage", "not_verified": "⚪ Not verified"}
BOOK_ICON = {"pass": "🟢 OK", "warn": "🟡 Check", "fail": "🔴 Problem", "not_verified": "⚪ Not verified"}


def hotel_type_card(c):
    """What kind of hotel the audit took this to be, with the reasons, and which traveller segments that makes core, optional or not worth assessing."""
    hc = (c or {}).get("hotel_class") or {}
    st.markdown("##### What kind of hotel this is")
    if not hc.get("classes"):
        st.caption("The pages did not show a clear type (airport, business, spa, resort...), so traveller segments are assessed only where the site itself describes the facilities.")
        return
    st.caption("From the hotel's name, its open map data and its own pages. A hotel can be several things. The type decides which traveller segments matter most: a gym is not a spa, a restaurant is not a wedding venue.")
    df([{"Type": x["label"], "Evidence": "; ".join(x["reasons"][:2])} for x in hc["classes"]])
    trv = (c or {}).get("traveller") or {}
    rows = [{"Segment": s["label"], "Relevance": "Core to this hotel" if s.get("relevance", "core") == "core" else "Secondary: offered, but not what the hotel is for"} for s in trv.get("segments", [])]
    if rows:
        df(rows)
    if trv.get("skipped"):
        st.caption("Not assessed, and no marketing advice given: " + ", ".join(s["label"] for s in trv["skipped"]) + ".")


def assessment_card(rep):
    """What was assessed, partly assessed and not assessed in this audit, from the evidence the audit holds."""
    import assessment
    a = assessment.assess(rep)
    st.markdown("##### What this audit actually assessed")
    st.caption("Stated from what the audit holds, not from what it set out to do: a site read as plain text cannot have its structured data, titles or images inspected, whatever a normal run checks.")
    for key, title, icon in (("assessed", "Assessed", "🟢"), ("partial", "Partly assessed", "🟡"), ("not_assessed", "Not assessed", "⚪")):
        with st.expander(f"{icon} {title} ({len(a[key])})", expanded=(key != "assessed")):
            for i in a[key]:
                st.markdown(f"- **{md_safe(i['what'])}**" + (f": {md_safe(i['detail'])}" if i["detail"] else ""))
    cnc = ((rep.get("consultant") or {}).get("could_not_confirm")) or []
    if cnc:
        st.markdown("**Could not be confirmed either way (no recommendation made):**")
        for x in cnc:
            st.markdown(f"- {md_safe(x['topic'])}: {md_safe(x['why'])}")


def score_breakdown_card(rep):
    """How the headline number is made: each assessed category's score, its weight, its share and the points it adds, so the rows add up to the score."""
    import scoring
    sc = rep.get("scorecard") or {}
    cats = sc.get("categories") or []
    if not cats:
        return
    t = scoring.totals_for(sc)
    st.markdown("##### How the readiness score is calculated")
    st.caption(t["method"])
    df([{"Category": b["label"] + (" (partial)" if b["partial"] else ""), "Score": b["score"], "Weight": f"{b['weight']:g}%", "Share of the measured weight": f"{b['share_pct']:g}%", "Points added": b["points"],
         "Why it has this weight": b["why"]} for b in t["breakdown"]])
    st.caption(f"Readiness = {t['overall']}. Categories that could not be measured are left out of the sum; they are never counted as zero. "
               "Readiness is how well the hotel is set up. It is not observed AI visibility, which is reported separately.")


def traveller_card(trv, coverage=None):
    """For each kind of traveller the hotel serves: what that traveller needs, and whether the hotel's own website states it."""
    st.markdown("##### Traveller recommendation readiness")
    st.caption("For each kind of traveller the hotel serves, does its own website state what they need to know before booking? **Confirmed** = clearly stated (quoted). **Partially confirmed** = some of it is. "
               "**Missing** = not found in pages that were read well enough to say so. **Unknown** = too little was read, a page had sections whose text could not be seen, or the hotel gives no sign it "
               "offers the thing, so nothing is recommended. Counted by requirement, not by how often a word appears.")
    segs = (trv or {}).get("segments") or []
    if not segs:
        st.info("No traveller segment could be assessed from the pages read." + (" " + (trv or {}).get("error", "") if (trv or {}).get("error") else ""))
        return
    sm = trv["summary"]
    if sm.get("judged"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Confirmed", sm["confirmed"])
        c2.metric("Partially confirmed", sm["partial"])
        c3.metric("Missing", sm["missing"])
        c4.metric("Unknown (not counted)", sm["unknown"])
    for seg in segs:
        cn = seg["counts"]
        with st.expander(f"{seg['label']}: {cn['confirmed']} confirmed, {cn['partial']} partly, {cn['missing']} missing" + (f", {cn['unknown']} unknown" if cn["unknown"] else "")):
            st.caption(f"Assessed because {seg['assessed_because']}.")
            for r in seg["requirements"]:
                st.markdown(f"**{md_safe(r['label'])}** - {REQ_ICON[r['state']]}")
                if r["found"]:
                    _evidence([{"url": f["url"], "snippet": f["snippet"]} for f in r["found"][:2]])
                if r["state"] in ("partial", "missing") and r["add"]:
                    w = r.get("where") or {}
                    st.markdown("Add: " + md_safe("; ".join(r["add"][:3])) + (f" - on [{md_safe(w['label'])}]({safe_url(w['url'])}) ({md_safe(w['reason'])})" if safe_url(w.get("url")) else (f" - on {md_safe(w.get('label', ''))}" if w.get("label") else "")))
                elif r.get("why"):
                    st.caption(md_safe(r["why"]))
    if trv.get("skipped"):
        st.caption("Not assessed, because the site shows no sign the hotel serves them: " + ", ".join(s["label"] for s in trv["skipped"]) + ".")


def external_card(ext):
    """Each outside source: can the right hotel be identified, do name and location agree, is there a link to the official site, does anything contradict the website."""
    st.markdown("##### The hotel on outside sources")
    if not ext or not ext.get("rows"):
        st.caption("Not checked for this report.")
        return
    st.caption("Identified = a page for the hotel was found in public search results and its title and address carry the hotel's name and town; the platform itself was not read (their terms prohibit it). "
               "Verified = read directly from open data and compared with the website. **Not verified = it cannot be checked reliably, which is never treated as missing or wrong.**")
    df([{"Source": r["source"], "Status": EXT_ICON[r["status"]], "Identified": {True: "yes", False: "no", None: "-"}[r["identified"]], "Name and location": r["name_location"] or "-",
         "Official site link": r["official_link"] or "not checked", "Differs from the website": "; ".join(r["contradictions"]) or "-", "Notes": r["note"], "Page": r["url"]} for r in ext["rows"]], link_cols=("Page",))
    pub = ext.get("publications") or {}
    if pub.get("rows"):
        with st.expander(f"Independent publications, weighed by quality ({pub['publishers']} publisher(s), {pub['strong']} substantial)"):
            st.caption("Each publisher counts once, by its best piece. A piece counts for more when it is independent editorial rather than a blog or a roundup, says a lot about the hotel, names it clearly and is recent. "
                       "Sponsored pieces count for nothing. The number of websites that mention the hotel is not a score.")
            df([{"Publisher": x["publisher"], "Kind": x["kind"], "Substance": x["substance"], "Freshness": x["freshness"], "Weight": x["weight"], "Page": x["url"]} for x in pub["rows"]], link_cols=("Page",))


def booking_card(bk):
    st.markdown("##### Booking readiness")
    if not bk or bk.get("status") != "ok":
        st.caption((bk or {}).get("reason") or "Not checked for this report.")
        return
    st.caption(" ".join(bk.get("limits", [])))
    df([{"Check": k["label"], "Result": BOOK_ICON.get(k["state"], k["state"]), "Detail": k["detail"], "Page": k.get("url", "")} for k in bk["checks"]], link_cols=("Page",))
    if bk.get("broken_links"):
        df([{"Broken link": b["url"], "HTTP status": b["status"]} for b in bk["broken_links"]])


def competitor_card(cp):
    st.markdown("##### Comparable hotels")
    if not cp:
        st.caption("Not looked at for this report.")
        return
    st.caption(" ".join(cp.get("limits", [])))
    if cp.get("status") != "ok":
        st.info(cp.get("reason") or "No comparison was made.")
        return
    df([{"Hotel": c["name"], "Why comparable": "; ".join(c["why_comparable"]), "Distance": f"{c['km']} km", "Pages read": c["pages_read"], "Website": c["url"]} for c in cp["competitors"]], link_cols=("Website",))
    for x in cp["comparisons"]:
        (st.warning if x["behind"] else st.success)(x["statement"])


def ai_trend_card(ai, prev_full, benchmark=None):
    """The same prompts now and at the hotel's last audit, with a change called only when the ranges do not overlap."""
    import trend
    prev_ai = (prev_full or {}).get("ai_sample") or {}
    cmp_ = trend.compare((ai or {}).get("items"), prev_ai.get("items"), [p["text"] for p in (benchmark or {}).get("prompts") or []] or None)
    st.markdown("##### Compared with the last audit")
    if not cmp_["rows"]:
        st.caption("No prompt was asked in both audits, so nothing can be compared yet. This audit's benchmark prompts are kept and asked again, word for word, next time.")
        return
    when = (prev_full.get("meta") or {}).get("run_at", "")[:10]
    st.caption(f"The prompts asked in both audits (the last was {md_safe(when)}), compared by their exact wording. A change is called a change only when the likely ranges do not overlap; with this few answers most changes are not clear, "
               "and that is stated rather than hidden. One assistant on one day each time.")
    st.markdown(f"**All these prompts together:** now {md_safe(trend.describe(*cmp_['now']))}; at the last audit {md_safe(trend.describe(*cmp_['before']))}. **{md_safe((cmp_['change'] or 'no clear change').capitalize())}.**")
    df([{"Prompt": r["text"], "Now": f"{r['now'][0]} of {r['now'][1]}", "Last audit": f"{r['before'][0]} of {r['before'][1]}", "Change": r["change"]} for r in cmp_["rows"]])


def custom_prompts_card(ai, prompts):
    """The prompts the person typed in before the audit, with what the assistant did with each. Nothing here is a score."""
    if not prompts:
        return
    st.markdown("##### Your own prompts")
    if not ai or ai.get("status") != "ok":
        st.warning("You entered " + str(len(prompts)) + " prompt(s), but they were not run: " + md_safe((ai or {}).get("reason") or "no AI assistant could be asked in this audit (it needs the hotel's name and town, and the service's Anthropic key).") + " Try them by hand in the assistants.")
        return
    import ai_sample
    groups = [g for g in ai_sample.by_question(ai.get("items") or []) if g["kind"] == "custom"]
    if not groups:
        st.info("Your prompts were not asked (the per-audit budget was used or the assistant did not answer).")
        return
    st.caption("Each prompt was put to one assistant (" + md_safe(ai.get("model", "")) + ") with live web search, exactly as you wrote it, " + ("twice" if max(len(g["answers"]) for g in groups) > 1 else "once")
               + ". It is a sample, not a ranking, and it is not part of any score.")
    for g in groups:
        a0 = g["answers"][0]
        rec = sum(1 for a in g["answers"] if a.get("recommended"))
        icon = "🟢" if g["named"] and g["named"] == g["of"] else "🟡" if g["named"] else "🔴"
        st.markdown(f"{icon} **{md_safe(g['text'])}**  \nNamed the hotel in {g['named']} of {g['of']} answer(s); recommended it in {rec}" + (f"; best place in the list: {g['best_position']}" if g["best_position"] else "") + ".")
        if a0.get("names_hotel"):
            st.caption("This prompt contains the hotel's name, so the answer shows what the assistant knows about the hotel, not whether it volunteers it.")
        with st.expander("What the assistant said"):
            for k, a in enumerate(g["answers"], 1):
                st.markdown(f"**Answer {k}**" + (" (the hotel is named)" if a.get("mentioned") else " (the hotel is not named)"))
                st.markdown(md_safe((a.get("answer") or "No answer text.")[:1500]))
                if a.get("domains"):
                    st.caption("Sources it used: " + ", ".join(md_safe(d) for d in a["domains"][:6]))


def rivals_label(rel):
    import rivals
    return rivals.RELATION_LABEL.get(rel, rel)


def ai_gap_card(gap):
    """Where the hotel was not named, who was named instead, the pages the assistant cited, and what the evidence shows. A sample with its limits stated: never a ranking and never a cause."""
    st.markdown("##### Who the assistant named instead")
    if not gap:
        st.caption("Not run for this report.")
        return
    if gap.get("status") != "ok":
        st.info(md_safe(gap.get("reason") or "Not run."))
        return
    quiet0 = [m for m in gap["markets"] if m["status"] != "named" and not m["gap"] and m.get("note")]
    if not gap.get("gaps"):
        (st.info if quiet0 else st.success)(md_safe(gap.get("reason") or "The hotel was named in every answer to every question."))
        if not quiet0:
            return
    st.caption("From the answers already collected: one assistant, a handful of answers, one day. 'n of m answers' counts answers that named a hotel. What is shown under each question is a difference in "
               "the evidence, not a proven reason for the assistant's choice.")
    ms = {m["qid"]: m for m in gap["markets"]}
    for q in gap["gaps"]:
        m = ms.get(q)
        if not m:
            continue
        icon = "🔴" if m["status"] == "not_named" else "🟡"
        st.markdown(f"{icon} **{md_safe(m['question'])}**  \nThe hotel was named in {m['named']} of {m['of']} answer(s)." + (" Every answer named the same leading hotel." if m.get("consistent") else ""))
        df([{"Named instead": r["name"] + (" (possibly the same hotel as " + ", ".join(r["aliases"]) + ")" if r.get("uncertain") and r.get("aliases") else ""), "Answers": f"{r['answers']} of {r['of']}",
             "Category": (r["tier"] or {}).get("label", "-") + ("" if r.get("relation") in ("same", "unknown") else " - " + rivals_label(r["relation"])), "Best place": r["best_rank"] or "-",
             "Rating quoted": "; ".join(r["ratings"]) or "-", "The assistant's reason": "; ".join(r["reasons"]) or "-"} for r in m["rivals"]])
        if m.get("other_category"):
            st.caption("Also named, but in a different category, so not treated as competitors: " + ", ".join(f"{md_safe(r['name'])} ({md_safe((r['tier'] or {}).get('label', ''))})" for r in m["other_category"]) + ".")
        crit = (gap.get("criteria") or {}).get(q) or []
        if crit:
            st.markdown("**Why they were recommended** *(the reasons the assistant gave, beside what the hotel's own pages show)*")
            word = {"strong": "states it clearly", "mentioned": "mentions it only in passing", "not_found": "does not mention it", "not_assessed": "not assessed"}
            df([{"Reason the assistant gave": c["label"], "Named for it": ", ".join(c["rivals"][:3]), "The hotel's own pages": word.get(c["hotel"]["state"], "-") + (": " + c["hotel"]["snippet"][:110] if c["hotel"].get("snippet") else "")} for c in crit])
        obs = (gap.get("observations") or {}).get(q) or []
        if obs:
            st.markdown("**Observed differences** *(not proven causes)*")
            for o in obs:
                links = " ".join(f"[page]({u})" for u in o.get("urls") or [] if str(u).startswith(("http://", "https://")))
                st.markdown(f"- {md_safe(o['text'])} {links}")
        steps = (gap.get("investigate") or {}).get(q) or []
        if steps:
            with st.expander("What to look into"):
                for s_ in steps:
                    st.markdown(f"- {md_safe(s_)}")
    quiet = [m for m in gap["markets"] if m["status"] != "named" and not m["gap"] and m.get("note")]
    if quiet:
        st.markdown("###### Named hotels in a different category (not a gap)")
        for m in quiet:
            st.markdown(f"- **{md_safe(m['question'])}** — " + ", ".join(f"{md_safe(r['name'])} ({md_safe((r['tier'] or {}).get('label', ''))})" for r in m["other_category"][:4]) + ". " + md_safe(m["note"]))
    arts = gap.get("articles") or []
    if arts:
        st.markdown("###### The pages the assistant cited for these questions")
        st.caption("Editorial pages were read politely (robots.txt respected) to see whether they mention the hotel. Review sites and booking platforms are listed but not read. A page the assistant cites shows what it read, not why it chose a hotel.")
        yn = {True: "yes", False: "no", None: "not read"}
        df([{"Page": a["title"][:70] or a["domain"], "Site": a["domain"], "Kind": a["kind"], "Cited": a["cited"], "Names the hotel": yn[a["hotel_in"]], "Names rivals": ", ".join(a["rivals_in"][:3]) or "-",
             "Opportunity": "an editorial list that omits the hotel" if a.get("opportunity") else (a.get("note") or "")[:80], "Link": a["url"]} for a in arts[:14]])
    comp = gap.get("comparison")
    if gap.get("rivals"):
        st.markdown("###### The rivals' own websites")
        df([{"Hotel": r["name"], "Named in": f"{r['answers']} answers", "Official site": r.get("url") or "not verified", "How found": r.get("via") or "-", "Check": r.get("why") or ""} for r in gap["rivals"]])
    if comp and comp.get("rows"):
        names = [r["name"] for r in comp["rivals"]]
        word = {"strong": "in detail", "some": "mentioned"}
        st.markdown("###### What each site says about its facilities")
        df([{"Facility": r["facility"], "The hotel": word.get(r["hotel"], "not mentioned"), **{n: word.get(r["rivals"].get(n), "not mentioned") for n in names}} for r in comp["rows"]])
        st.caption("Read from the pages of each site. 'Not mentioned' means not found on the pages read, which is not proof the hotel lacks it.")
    with st.expander("Limits of this analysis"):
        for l in gap.get("limits") or []:
            st.markdown(f"- {md_safe(l)}")


def ai_test_card(ai, hotel=""):
    """The genuine AI test log, and a checklist for the assistants this tool cannot query. Observed visibility stays NOT MEASURED for those."""
    import ai_sample
    st.markdown("##### AI recommendation tests: what was actually tested")
    log = ai_sample.test_log(ai)
    if not log:
        st.warning("**Observed AI visibility: not measured.** No AI assistant was asked about the hotel in this audit, so nothing here shows whether ChatGPT, Gemini, Copilot or any other assistant recommends it. "
                   "The checklist below lets you test by hand.")
    else:
        s = log["summary"]
        st.caption(f"Genuine tests of **one assistant only: {md_safe(log['platform'])}**, run on {md_safe(log['date'])}. **Not tested: {', '.join(log['not_tested'])}.** "
                   "Appeared = the hotel is named in the answer. Recommended = it is a line in a list of suggestions or a sentence recommends it (a rule-based reading; read the answer beside it). "
                   "One assistant on one day is a sample, not a ranking, and it is not part of the readiness score.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prompts that do not name the hotel", s["prompts"])
        c2.metric("Answers naming the hotel", f"{s['appeared']} of {s['non_branded_answers']}")
        c3.metric("Answers recommending it", f"{s['recommended']} of {s['non_branded_answers']}")
        c4.metric("Official site among the sources", f"{s['site_cited']} of {s['non_branded_answers']}")
        yn = lambda v: "-" if v is None else ("yes" if v else "no")      # noqa: E731
        with st.expander("The test log: every prompt, answer by answer"):
            df([{"Prompt": r["prompt"], "Names the hotel in the prompt": "yes" if r["branded"] else "no", "Platform": r["platform"], "Appeared": yn(r["appeared"]), "Recommended": yn(r["recommended"]),
                 "Place in list": r["position"] or "-", "Official site cited": yn(r["official_site_cited"]), "Date": r["date"]} for r in log["rows"]])
    ck = ai_sample.manual_checklist(ai, hotel)
    if ck["prompts"]:
        with st.expander("Checklist: test these prompts by hand in ChatGPT, Gemini and Copilot"):
            st.caption("This tool cannot ask those assistants, so their results are not measured here. Ask each prompt in a fresh chat and note the answer. Record: " + "; ".join(ck["fields"]) + ".")
            df([{"Prompt": p, **{a: "" for a in ck["assistants"]}} for p in ck["prompts"]])
