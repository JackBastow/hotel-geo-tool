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
    msg = f"**Read {cov['pages_read']} of {cov['pages_attempted']} pages.** {cov['note']}" + (f"  \nWhy pages failed: {why}." if why else "")
    (st.error if cov.get("unreadable") else st.warning)(msg)


def overview(c):
    coverage_banner(c)
    u = c["understanding"]
    st.markdown("#### AI currently understands this hotel as")
    if u["summary"]:
        st.info(u["summary"])
    else:
        st.warning("Too few pages could be read to say what a machine would understand about this hotel.")
    st.caption(f"Based on {u['pages_read']} page(s) from the hotel's own website. " + u["note"])

    st.markdown("#### AI visibility readiness")
    st.caption("Eight separate measures - deliberately not blended into one score. Each shows what drove it.")
    cols = st.columns(4)
    for i, p in enumerate(c["profile"]):
        with cols[i % 4]:
            with st.container(border=True):
                st.markdown(f"**{p['label']}**")
                if p["assessed"]:
                    st.progress(p["score"] / 100, text=f"{p['score']} / 100 - {p['band']}")
                else:
                    st.caption("Not assessed this run")
                for d in p["drivers"][:4]:
                    st.caption(md_safe(d))
    recs = {r["id"]: r for r in c["recommendations"]}
    st.markdown(f"#### The {len(c['top_actions'])} things most worth doing")
    st.caption("Ranked by likely impact against effort, and spread across the four kinds of problem. They come from what was found on "
               "this hotel's own pages - none is generic advice. Nothing here is a guarantee about what any AI assistant will recommend.")
    for i, rid in enumerate(c["top_actions"], 1):
        r = recs[rid]
        st.markdown(f"##### {i}. {md_safe(r['title'])}")
        rec_card(r)
    if c["quick_wins"]:
        st.markdown("#### Quick wins")
        st.caption("Low-effort improvements not already in the list above.")
        df([{"Quick win": recs[i]["title"], "Where": (recs[i]["page"] or {}).get("label", ""), "What to do": recs[i]["action"][:190],
             "Priority": recs[i]["priority"]} for i in c["quick_wins"]])
    if c["working"]:
        st.markdown("#### What the hotel is already doing well")
        for w in c["working"]:
            st.markdown("- " + md_safe(w["point"]))
    others = [r for r in c["recommendations"] if r["id"] not in c["top_actions"] and r["id"] not in c["quick_wins"]]
    if others:
        with st.expander(f"All other recommendations ({len(others)})"):
            for r in others:
                with st.expander(f"{PRI_ICON[r['priority']]} {r['title']}"):
                    rec_card(r, nested=True)


# ------------------------------------------------------------ how AI sees it

def ai_view(c):
    u = c["understanding"]
    st.caption("What a machine could learn from this hotel's own pages, what it would struggle with, and where each gap should be fixed. "
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

def fix_site(c):
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
