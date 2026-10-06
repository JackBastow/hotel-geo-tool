"""
Streamlit rendering of the consultant report.

Native components only. Third-party text (page extracts) goes through
md_safe(), and links are limited to http/https, so nothing read from a web
page can inject markup or load an image.
"""

import streamlit as st

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
    return urlparse(u or "").path or "/"


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
    if not cov.get("limited"):
        return
    why = "; ".join(f"{n} × {r}" for r, n in (cov.get("failure_reasons") or {}).items())
    head = "" if cov["pages_attempted"] <= cov["pages_read"] and cov.get("unreadable") else f"**Read {cov['pages_read']} of {cov['pages_attempted']} pages.** "
    msg = f"{head}{cov['note']}" + (f"  \nWhy pages failed: {why}." if why else "")
    (st.error if cov.get("unreadable") else st.warning)(msg)


EVIDENCE_ICON = {"high": "\U0001F7E2", "medium": "\U0001F7E1", "low": "\U0001F534"}


def headline_strip(h):
    """The readiness score, how much of the model it rests on, and what was NOT measured - always together."""
    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric("AI discoverability readiness", "\u2014" if h["score"] is None else f"{h['score']} / 100",
                      help="The average of the categories that could be assessed - an indicator of how well the hotel is set up, "
                           "not a measure of how visible it is to AI assistants.")
            st.caption(h["badge"].capitalize())
        with c2:
            st.progress(min(max(h["coverage_pct"], 0), 100) / 100, text=f"Measurement coverage: {h['coverage_pct']:.0f}% of the full model assessed")
            st.caption(h["explanation"])
            if h["unassessed"]:
                st.markdown("**Not measured:** " + "; ".join(f"{u['label']} ({u['weight']:g}%)" for u in h["unassessed"]))


def top_card(i, r):
    """A top action, concise: Issue / Why it matters / Evidence / Exact action / Owner / Priority / Effort / Confidence / Expected outcome."""
    with st.container(border=True):
        st.markdown(f"**{i}. {md_safe(r['title'])}**")
        st.caption(f"{PRI_ICON[r['priority']]} {r['priority'].capitalize()} priority \u00b7 effort: {r['effort']} \u00b7 "
                   f"confidence: {r['confidence'].lower()} \u00b7 owner: {r['team']} \u00b7 ref {r['ref']}")
        st.markdown(f"**Issue.** {md_safe(_short(r['finding'], 300))}")
        st.markdown(f"**Why it matters.** {md_safe(_short(r['why'], 260))}")
        if r["evidence"]:
            st.markdown("**Evidence**")
            _evidence(r["evidence"][:1])
        st.markdown(f"**Exact action.** {md_safe(_short(r['action'], 320))}")
        st.markdown(f"**Expected outcome.** {md_safe(_short(r['expected_outcome'], 240))}")
        with st.expander("Where, what to add, and example wording"):
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
    cols = st.columns(4)
    for i, p in enumerate(c["profile"]):
        with cols[i % 4]:
            with st.container(border=True):
                st.markdown(f"**{p['label']}**")
                ev = p.get("evidence") or {}
                if p["assessed"]:
                    st.progress(p["score"] / 100, text=f"{p['score']} / 100")
                    st.caption(f"{EVIDENCE_ICON.get(ev.get('level'), '')} {ev.get('level', '?')} evidence"
                               + (" \u00b7 provisional" if p["band"] == "provisional" else "") + f" \u2014 {md_safe(ev.get('why', ''))}")
                else:
                    st.caption("Not assessed this run")
                for d in p["drivers"][:3]:
                    st.caption(md_safe(d))

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
        st.markdown("#### What the hotel is already doing well")
        for w in c["working"]:
            st.markdown("- " + md_safe(w["point"]))


# ------------------------------------------------------------ how AI sees it

def ai_view(c):
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
