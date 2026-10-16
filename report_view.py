"""
The report page for the Flask site: the same sections as the Streamlit report (Overview, How AI sees your hotel, Fix your website, Beyond your website, Scorecard, Tools & method),
built by running the existing screens (ui_consult.py, ui_intel.py, ui_theme.py) against htmlst.py, so every sentence and every honesty rule is the one already tested.

The interactive parts (the review-export upload, comparing with an earlier report) are small forms here; server.py answers them.
"""

import html

import ai_check
import dashboard
import htmlst
import ui_consult
import ui_intel
import ui_theme
from htmlst import st

htmlst.install()          # the screens were written against `streamlit`; inside this process they write HTML instead


def md_safe(s):
    return ui_intel.md_safe(s)


def _notices(fa_res):
    meta = fa_res["meta"]
    if (fa_res.get("site") or {}).get("meta", {}).get("scope_note"):
        st.info(fa_res["site"]["meta"]["scope_note"])
    if str(meta.get("hotel_name_source", "")).startswith("guessed from the web address"):
        st.info(("The site refused this tool's own reader, so the hotel was identified from its web address as "
                 if (fa_res.get("guest_questions") or {}).get("read_via")
                 else "The website could not be read, so the hotel was identified from its web address as ") + f"\"{meta['hotel']}\""
                + (f" in {meta['city']}" if meta.get("city") else "") + ". That is a guess: type the exact hotel name and city and run the audit again if it is wrong.")
    if meta.get("hotel") and not meta.get("city"):
        import urllib.parse
        link = "/?" + urllib.parse.urlencode({"website": meta.get("website", ""), "hotel": meta["hotel"]})
        st.warning("The town could not be worked out from the website or the hotel's name, so the AI answers, the listing lookup and the local-context checks were skipped. "
                   "Run it again with the town filled in to include them: it is the single biggest thing that changes what this report can measure.")
        st.raw(f'<p><a class="btn primary" href="{html.escape(link, quote=True)}">Run it again with the town filled in</a></p>')
    if not meta.get("hotel"):
        st.warning("The hotel's name couldn't be worked out from the website, so the outside checks (listings, media coverage, local context, open-data "
                   "lookups) could not run. Type the hotel name and city and run the audit again to include them.")
    intel = fa_res.get("intel") or {}
    if intel and "error" in intel:
        st.warning("The wider discovery and reputation analysis failed for this run "
                   f"({intel.get('error')}). The website score and guest-question results below are unaffected.")


def _scorecard(fa_res):
    meta, loc, sc = fa_res["meta"], fa_res["meta"]["location"], fa_res["scorecard"]
    intel = fa_res.get("intel") or {}
    has_intel = bool(intel) and "error" not in intel
    st.caption("The original eight-category scorecard, with its coverage. The other tabs add evidence and recommendations; this number is unchanged by them.")
    top = fa_res.get("top_fixes") or []
    top_codes = {r.get("code") for r in top}
    rest = [r for r in fa_res["recommendations"] if r.get("code") not in top_codes]
    doc, _h = dashboard.build(meta["hotel"], meta["website"], sc, rest, fa_res.get("guest_questions"), top, fa_res.get("headline"))
    doc = doc.replace(dashboard._RESIZE_JS, "")        # the page itself resizes the frame (the frame is sandboxed, so it must not run scripts)
    st.raw(f'<iframe class="dash" title="Scorecard" sandbox="allow-same-origin" srcdoc="{html.escape(doc, quote=True)}"></iframe>')
    st.caption(f"run {meta['run_at']} · hotel name {meta['hotel_name_source']}" + (f" · location from {loc['source']}" if loc.get("source") else ""))
    st.info(f"**Read the score with its coverage.** {sc['caveat']}")
    ui_consult.score_breakdown_card(fa_res)
    for c in sc["categories"]:
        if not c["assessed"]:
            continue
        label = f"{c['label']} — {c['score']}/100 (weight {c['weight']}%)" + ("  ·  PARTIAL" if c.get("partial") else "")
        with st.expander(label):
            st.caption(c["detail"])
            for e in c["evidence"]:
                st.write(f"- {e}")
    not_assessed = [c for c in sc["categories"] if not c["assessed"]]
    if not_assessed:
        missing_weight = round(sum(c["weight"] for c in not_assessed), 1)
        with st.expander(f"Not assessed — {missing_weight}% of the model ({len(not_assessed)} categories)"):
            st.caption("Not measured at all. Neither helps nor hurts the score above, but this is most of what the model weights, so treat the score as partial evidence, not a final verdict.")
            for c in not_assessed:
                st.markdown(f"**{md_safe(c['label'])}** *(worth {c['weight']}%)*  \n{md_safe(c['detail'])}  \n\n*What this would take:* {md_safe(c.get('how_to_enable', ''))}")
    st.divider()
    if has_intel:
        ui_intel.website(intel)
    gq = fa_res.get("guest_questions") or {}
    sheet = gq.get("fact_sheet") or []
    if sheet:
        st.subheader("What your website tells us about your hotel")
        st.caption("Every fact below was read from your own pages, with the page it came from. If one is wrong or missing, that is what an AI assistant will repeat. "
                   "Read by simple rules, not understanding - check anything that looks off.")
        for c in gq.get("conflicts") or []:
            vals = "; ".join(f"{v['value']} ({v['source_url']})" for v in c["values"])
            st.warning(f"**{md_safe(c['fact'])} differs between pages:** {md_safe(vals)}. {md_safe(c['note'])}.")
        st.dataframe([{"Fact": r["fact"], "What the site says": r["value"], "Where": r["source_url"], "How it was read": r["note"]} for r in sheet],
                     column_config={"Where": st.column_config.LinkColumn("Page")}, width="stretch", hide_index=True)
        if fa_res.get("own_facts_source") == "page text":
            st.caption("This site publishes no structured data, so these page-text facts were also used to cross-check OpenStreetMap and Wikidata.")
    st.subheader("Supporting detail")
    d1, d2 = st.columns(2)
    with d1:
        with st.expander("Entity presence (OpenStreetMap, Wikidata)"):
            for e in fa_res["entities"]:
                label = (e.get("label") or e.get("display_name", ""))[:70]
                link = e.get("url", "") if str(e.get("url", "")).startswith(("http://", "https://")) else ""
                if e.get("found") and e.get("match_confident") is True:
                    st.success(f"**{e['source']}** — verified" + (f" ({md_safe(e['match_reason'])})" if e.get("match_reason") else "") + (f"  \n[{md_safe(label)}]({link})" if link else f"  \n{md_safe(label)}"))
                elif e.get("found"):
                    st.warning(f"**{e['source']}** — unverified  \n{md_safe(e.get('note', ''))}")
                else:
                    st.error(f"**{e['source']}** — not found  \n{md_safe(e.get('note') or e.get('error', ''))}")
        with st.expander("Linked profiles"):
            profs = fa_res["discovery"]["profiles"]
            if profs:
                st.dataframe(profs, width="stretch", hide_index=True)
                st.caption("Declared in JSON-LD `sameAs`: " + ("yes" if fa_res["discovery"]["declares_sameas"] else "no"))
            else:
                st.info("No profiles linked from the hotel's own pages.")
    with d2:
        tr = fa_res.get("tavily_result") or {}
        if tr.get("configured"):
            with st.expander("Editorial, OTA & social search", expanded=True):
                if tr.get("segments_detected"):
                    st.caption("Checked as: **" + ", ".join(md_safe(x) for x in tr["segments_detected"]) + "** — detected from the hotel's own topic pages, so the search angles were tailored to this hotel, not generic.")
                st.write(f"**OTAs found:** {md_safe(', '.join(h['platform'] for h in tr.get('ota_hits', [])) or 'none found')}")
                st.write(f"**Independently-found social presence:** {md_safe(', '.join(h['platform'] for h in tr.get('social_hits', [])) or 'none found')}")
                confirmed = [h for h in tr.get("editorial_hits", []) if h.get("read", {}).get("confirmed") is True]
                if confirmed:
                    st.write("**Editorial coverage — read and judged, not just found:**")
                    icons = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
                    for h in confirmed:
                        r = h["read"]
                        link = h["url"] if str(h["url"]).startswith(("http://", "https://")) else ""
                        via = " · read by LLM" if r.get("via") == "llm" else " · rule-based read"
                        st.markdown(f"{icons.get(r.get('sentiment'), '⚪')} **[{md_safe(h['platform'])}]({link})** — {md_safe(r.get('substance', 'unknown'))}, {md_safe(r.get('sentiment', 'unknown'))}*{via}*  \n{md_safe(r.get('excerpt', ''))}")
                else:
                    st.caption("No confirmed editorial coverage found in the searches run.")
                if tr.get("error"):
                    st.caption(f"Note: one or more searches failed ({md_safe(tr['error'])}) — results above are from whichever succeeded.")
        if fa_res["consistency"]:
            with st.expander("Fact consistency"):
                st.dataframe(fa_res["consistency"], width="stretch", hide_index=True)
        if fa_res["blocked_sources"]:
            with st.expander(f"Sources that refused automated access ({len(fa_res['blocked_sources'])})"):
                st.caption("These returned an error rather than a page — TripAdvisor and Booking.com's Terms of Use prohibit automated collection, so this tool doesn't attempt it. "
                           "Check by hand in a browser if you need what's on these pages.")
                st.dataframe(fa_res["blocked_sources"], width="stretch", hide_index=True)
    with st.expander("Website detail"):
        s = fa_res["site"]
        st.caption("These two lists are a guess from page addresses - the pages were not read. The guest-question section above is the evidence-based check.")
        st.write(f"**Topics with a matching page address:** {md_safe(', '.join(s['topics_covered']) or 'none')}")
        st.write(f"**Topics with no matching page address:** {md_safe(', '.join(s['topics_no_page_found']) or 'none')}")
        st.write(f"**Schema types found:** {md_safe(', '.join(s['schema_types_found']) or 'none')}")
        st.dataframe([{"url": p["url"], "status": p.get("status"), "title": (p.get("title") or "")[:70]} for p in s["pages"]], width="stretch", hide_index=True)


REVIEW_FORM = """
<div class="rp-form" id="review-pack" data-token="{token}">
  <div class="rp-row"><input type="file" id="rp-file" accept=".csv,.xlsx"><input type="text" id="rp-platform" placeholder="Platform, if the file does not say (for example Booking.com)" maxlength="30">
  <button type="button" class="btn primary" id="rp-go">Analyse the file</button></div>
  <div class="rp-status" id="rp-status" role="status"></div>
  <div class="rp-result" id="rp-result"></div>
</div>"""

COMPARE_FORM = """
<div class="rp-form" id="compare" data-token="{token}">
  <div class="rp-row"><input type="file" id="cmp-file" accept=".json,application/json"><button type="button" class="btn primary" id="cmp-go">Compare</button></div>
  <div class="rp-status" id="cmp-status" role="status"></div>
  <div class="rp-result" id="cmp-result"></div>
</div>"""


def _review_pack_intro(fa_res, token, private=None):
    st.markdown("##### The hotel's own reviews: upload an export")
    st.caption("Booking.com, Tripadvisor, Google and Expedia all let the hotel export its reviews. Upload that file and every review and reply in it is analysed, instead of the handful "
               "that public search shows. Reviewer names are never read. The text of the reviews is analysed in this session and is not saved: only counts and rates are kept with the report.")
    with st.expander("Where to find the export"):
        st.markdown("- **Booking.com:** Extranet, Guest reviews, Download (a spreadsheet of review scores, positive and negative comments and your replies).\n"
                    "- **Tripadvisor:** Management Center, Reviews, export (or copy the reviews into a spreadsheet).\n"
                    "- **Google:** Business Profile, Reviews (export through Google Takeout, or copy into a spreadsheet).\n"
                    "- **Expedia:** Partner Central, Guest experience, Reviews, Download.\n"
                    "- **Any spreadsheet** works if it has a rating or a review text, and, where you have them, a reply and the dates. Column names are recognised in English.")
    if token:
        st.raw(REVIEW_FORM.format(token=html.escape(token, quote=True)))
    if private:
        st.markdown("##### The file uploaded with this audit")
        st.raw(pack_html(private["res"], private["mapping"], included=True))
    elif fa_res.get("review_pack"):
        st.markdown("##### The last analysis saved with this report")
        ui_consult._pack_public(fa_res["review_pack"])
        st.caption("Upload the file again to see the unanswered critical reviews and starting drafts, which are not saved.")


def _tools(fa_res, token):
    intel = fa_res.get("intel") or {}
    meta = fa_res["meta"]
    st.subheader("Method: all 30 checks and what each source could and couldn't tell us")
    if intel and "error" not in intel:
        ui_intel.gaps(intel)
    else:
        st.info("The 30-check methodology table needs the wider analysis, which did not run.")
    st.divider()
    st.caption("Optional extras. Nothing here is part of the score.")
    st.subheader("Check what AI assistants actually say about your hotel")
    st.caption("This tool doesn't ask AI assistants for you, but you can in a few minutes, free, in whichever assistant you use. Copy a prompt, paste it in, and look at what came back. "
               "Each answer is **one sample** — an assistant can answer differently tomorrow, with web search on or off — so look for patterns across several answers, not a verdict from one.")
    prompts = ai_check.build_prompts(meta["hotel"], meta.get("city") or "", fa_res.get("segments"))
    t_acc, t_dis = st.tabs(["Accuracy — does it get the facts right?", "Discovery — does it suggest the hotel?"])
    with t_acc:
        st.caption("These name the hotel. Check each fact in the answer against your own site.")
        for p in (p for p in prompts if p["kind"] == "accuracy"):
            st.markdown(f"**{md_safe(p['label'])}**")
            st.code(p["prompt"])
    with t_dis:
        st.caption("These never name the hotel — that is the test. Would someone who has never heard of you be pointed to you?")
        disc = [p for p in prompts if p["kind"] == "discovery"]
        if not disc:
            st.info("Add a city to get discovery prompts (they need a place).")
        for p in disc:
            st.markdown(f"**{md_safe(p['label'])}**")
            st.code(p["prompt"])
    st.info("**Real citation data, if you own the website:** Bing Webmaster Tools has an *AI Performance* report showing how often your pages are cited in Microsoft Copilot and Bing's AI summaries "
            "(public preview). It does **not** cover ChatGPT, Gemini or Perplexity. [How it works](https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview)")
    st.subheader("Compare with an earlier report")
    st.caption("Run the audit again after making changes, then upload the .json you downloaded last time to see what moved. Nothing you upload here is kept.")
    if token:
        st.raw(COMPARE_FORM.format(token=html.escape(token, quote=True)))


TABS = [("overview", "Overview"), ("action", "Action plan"), ("ai", "AI visibility"), ("site", "Your website"), ("reputation", "Reputation & listings"), ("score", "Scorecard"), ("tools", "Tools & method")]


def render(fa_res, token=None, prev=None, private=None):
    """
    -> the HTML of the report body (notices, then seven tabs) for a finished audit report. `prev` is the hotel's previous audit's summary row, when there is one, for 'since last audit'.
    The tabs are Overview and Action plan (dashboard_view.py, built for acting on) and the evidence tabs (the Streamlit screens drawn through htmlst).
    """
    import dashboard_view
    intel = fa_res.get("intel") or {}
    has_intel = bool(intel) and "error" not in intel
    consult = fa_res.get("consultant") or {}
    has_consult = bool(consult) and "error" not in consult
    no_consult = '<div class="alert info">This section needs the consultant analysis, which did not run for this audit.</div>'

    def overview():
        if has_consult:
            ui_consult.coverage_banner(consult)
            st.raw(dashboard_view.overview(fa_res, prev))
        elif has_intel:
            ui_intel.overview(intel)
        else:
            st.info("The analysis of what AI systems can understand about this hotel did not run for this audit. The Scorecard tab still has the website results.")

    def ai():
        if has_consult:
            ui_consult.ai_test_card(fa_res.get("ai_sample"), fa_res["meta"].get("hotel", ""))
            st.divider()
            ui_consult.ai_view(consult, fa_res.get("ai_sample"), fa_res.get("ai_insights"))
        else:
            st.raw(no_consult)

    def site():
        if has_consult:
            ui_consult.understanding_block(consult)
            ui_consult.traveller_card(consult.get("traveller"))
            st.divider()
            ui_consult.booking_card(consult.get("booking"))
            st.divider()
            ui_consult.competitor_card(consult.get("competitors"))
            st.divider()
            ui_consult.fix_site(consult, fa_res.get("web_signals"))
        else:
            st.raw(no_consult)

    def reputation():
        st.caption("Evidence from outside the hotel's own website: where it is listed, how others describe it, and who covers it.")
        subs = st.tabs(["Reviews & reputation", "Identity & distribution", "Media & validation", "Reddit", "Traveller fit", "Social & local"])
        for tab, fn in zip(subs, ("reviews", "identity", "media", "reddit", "traveller", "social_local")):
            with tab:
                if fn == "reviews":
                    _review_pack_intro(fa_res, token, private)
                    ui_consult.review_card(fa_res.get("review_snapshot"))
                if fn == "identity":
                    ui_consult.external_card(consult.get("external") if has_consult else None)
                    st.divider()
                    ui_consult.listing_checks_card(fa_res.get("listing_checks"))
                if fn == "reddit":
                    ui_consult.reddit_card(fa_res.get("reddit"))
                    continue
                if has_intel:
                    getattr(ui_intel, fn)(intel)
                else:
                    st.info("This section needs the wider discovery analysis, which did not run for this audit.")

    panels = {
        "overview": htmlst.build(overview),
        "action": dashboard_view.action_plan(fa_res),
        "ai": htmlst.build(ai),
        "site": htmlst.build(site),
        "reputation": htmlst.build(reputation),
        "score": htmlst.build(_scorecard, fa_res),
        "tools": htmlst.build(_tools, fa_res, token),
    }
    notices = htmlst.build(_notices, fa_res)
    nav = "".join(f'<button type="button" class="tab{" active" if i == 0 else ""}" data-tab="tab-{k}" data-name="{k}">{html.escape(label)}</button>' for i, (k, label) in enumerate(TABS))
    body = "".join(f'<div class="tab-panel{" active" if i == 0 else ""}" id="tab-{k}">{panels[k]}</div>' for i, (k, _l) in enumerate(TABS))
    return f'{notices}<div class="tabs top"><div class="tab-bar" role="tablist">{nav}</div>{body}</div>'


def pack_html(res, mapping, included=False):
    """The result of a review-export upload as HTML: the figures (counts and rates), then the unanswered critical reviews with starting drafts. Sent to the visitor's browser only; the review text is not stored."""
    import csv
    import io
    import urllib.parse

    def body():
        used = ", ".join(f"{k}: '{md_safe(v)}'" for k, v in mapping.items())
        st.caption("Columns used: " + used + ".")
        st.success("The Reviews & Reputation score, the plan and the readiness figure include this file." if included
                   else "The Reviews & Reputation score, the plan and the readiness figure now include this file. Reload the report to see them in the Scorecard and Overview.")
        ui_consult._pack_public(res["public"])
        un = res["private"]["unanswered"]
        if un:
            st.markdown(f"###### Critical reviews still unanswered ({res['public']['critical_unanswered']}), newest first")
            st.caption("Shown only to you, and not saved. Each draft is a skeleton to finish: it states only what the review raised and leaves the facts in [brackets]. "
                       "Never offer anything in return for a changed review.")
            for r in un:
                with st.expander(f"{r['date'] or 'undated'} · {r['platform']} · {r['rating']:g} out of 5" + (f" · {', '.join(r['topics'])}" if r["topics"] else "")):
                    st.markdown(md_safe(r["text"] or "(no text)"))
                    st.text_area("Draft reply to finish", r["draft"], height=210)
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["date", "platform", "rating", "topics", "review", "draft reply"])
            for r in un:
                w.writerow([r["date"], r["platform"], r["rating"], "; ".join(r["topics"]), r["text"], r["draft"]])
            st.raw('<p><a class="btn" download="unanswered-critical-reviews.csv" href="data:text/csv;charset=utf-8,' + urllib.parse.quote(buf.getvalue()) + '">Download the unanswered reviews and drafts (.csv)</a></p>')
        elif res["public"].get("has_replies_column"):
            st.success("Every critical review in the file has a reply.")
    return htmlst.build(body)


def comparison_html(cmp):
    """The 'compare with an earlier report' result as HTML (the same sections as the Streamlit page)."""
    def body():
        for w in cmp["warnings"]:
            st.warning(w)
        ov = cmp["overall"]
        c1, c2, c3 = st.columns(3)
        if ov.get("delta") is not None and ov["like_for_like"]:
            c1.metric("Overall score", ov["new"], delta=ov["delta"])
        else:
            c1.metric("Overall score", ov["new"] if ov["new"] is not None else "\u2014")
        c2.metric("Things that improved", cmp["headline"]["improved"])
        c3.metric("Things that got worse", cmp["headline"]["declined"])
        st.caption(f"Earlier report: {cmp['old_date'] or 'unknown date'} · this report: {cmp['new_date'] or 'unknown date'}")
        if cmp["categories"]:
            st.markdown("**Categories**")
            st.dataframe([{"Category": r["label"], "Before": "—" if r["old"] is None else r["old"], "Now": "—" if r["new"] is None else r["new"],
                           "Change": "" if r["delta"] is None else f"{r['delta']:+d}", "Verdict": r["status"]} for r in cmp["categories"]])
        if cmp["guest"]:
            st.markdown("**Guest questions**")
            st.dataframe([{"Question": g["short"], "Before": g["old"], "Now": g["new"], "Verdict": g["status"]} for g in cmp["guest"]])
        rc = cmp["recs"]
        if rc["resolved"] or rc["new"] or rc["still_open"]:
            st.markdown("**Recommendations**")
            st.dataframe([{"Status": "Fixed since the earlier report", "Recommendation": a} for a in rc["resolved"]]
                         + [{"Status": "New", "Recommendation": a} for a in rc["new"]] + [{"Status": "Still open", "Recommendation": a} for a in rc["still_open"]])
        ai = cmp.get("ai")
        if ai:
            st.markdown("**What an AI assistant said (a sample each time)**")
            o, n = ai["old"], ai["new"]
            a, b, c = st.columns(3)
            a.metric("Named in generic answers", f"{n['named']} of {n['asked']}", delta=(None if o["named"] is None or n["named"] is None else n["named"] - o["named"]))
            b.metric("Share of the names given", "-" if n["share"] is None else f"{n['share']}%", delta=(None if o["share"] is None or n["share"] is None else n["share"] - o["share"]))
            c.metric("Earlier run", f"{o['named']} of {o['asked']}")
            if n.get("coverage_pct") is not None and o.get("coverage_pct") is not None:
                d1, d2 = st.columns(2)
                d1.metric("Coverage (share of all answers naming the hotel)", f"{n['coverage_pct']}%", delta=n["coverage_pct"] - o["coverage_pct"])
                if n.get("sentiment") is not None and o.get("sentiment") is not None:
                    d2.metric("Net sentiment where named", f"{n['sentiment']:+d}", delta=n["sentiment"] - o["sentiment"])
            if ai["new_competitors"]:
                st.caption("Newly recommended instead: " + ", ".join(md_safe(x) for x in ai["new_competitors"][:6]))
            if ai["new_sources"]:
                st.caption("Newly relied on: " + ", ".join(md_safe(x) for x in ai["new_sources"][:6]))
            st.caption(ai["note"])
        if cmp["facts"]:
            st.markdown("**Facts that changed**")
            st.dataframe(cmp["facts"])
    return htmlst.build(body)
