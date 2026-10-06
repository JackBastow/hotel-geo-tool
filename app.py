"""
Hotel AI Discoverability Audit - public dashboard.

Run with:  streamlit run app.py

ONE ACTION, NO ACCOUNT. Type a website, press "Run audit", get a report.
Meant to be hosted somewhere with a public URL (Streamlit Community Cloud to
start) so anyone - no Claude access, no API keys of their own, nothing
installed - can just use it.

That public-and-free-to-the-VISITOR design shapes everything here:

  - No visitor ever sees, types, or needs an API key. Where a category CAN be
    backed by a genuinely free, no-card data source (Tavily for OTA presence
    and editorial mentions; Amadeus Hotel Ratings for review sentiment), the
    OPERATOR's own key - never the visitor's - is read from Streamlit's
    secrets store (st.secrets, configured in the app's dashboard, never
    committed to this repo) and used on the visitor's behalf. If no secret is
    configured, that category just reports "not assessed" - the app works
    identically either way, it only covers more of the model once keys exist.

  - A SHARED MONTHLY QUOTA PROTECTS those free keys from being exhausted by
    public traffic (see store.py's per-service quota tracking). Once a
    service's free monthly allowance is used up, the app stops calling it
    until the month rolls over, rather than erroring or (for a paid service)
    spending real money. This is a soft, best-effort limit - the counter
    lives on the host's own disk, which can be wiped on a restart - not a
    hard guarantee, same as it always was for the Gemini-only version of this.

  - Anything that costs real, uncapped money per request - Google Places,
    Gemini grounding - is deliberately NOT wired in here. Those would need an
    explicit decision to accept that risk on a page strangers can click, which
    hasn't been made. See full_audit.py and scoring.py's module docstrings for
    what each would take to add, if that decision changes.

  - No server-side history across visitors. store.py's run history writes to
    one shared folder on disk, which is fine for a single person running it
    locally, but on a shared public host every visitor's filesystem is the
    SAME filesystem - saving runs there would let one visitor type in
    another hotel's name and read a stranger's report. So nothing here calls
    store.save_run(). A visitor's result lives only in their own browser
    session (gone on refresh) and in the JSON they can download - never
    written to a shared file other visitors could read.
"""

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import streamlit as st


def _drop_stale_modules():
    """
    Streamlit keeps imported modules alive between reruns, and a redeploy can replace the files while
    the old process keeps running. The result is a NEW app.py calling OLD modules (seen live:
    "build_pdf() takes 1 positional argument but 2 were given"). So: fingerprint the project's .py
    files, and when the fingerprint changes, forget every project module so the imports below load
    the current code. It is a cheap check on every run and only does work after a code change.
    """
    here = Path(__file__).resolve().parent
    files = sorted(here.glob("*.py"))
    sig = hashlib.sha1("|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in files).encode()).hexdigest()
    if getattr(sys, "_hotel_audit_build", None) == sig:
        return
    mine = {p.stem for p in files} - {"app"}
    for name in list(sys.modules):
        if name in mine:
            del sys.modules[name]
    sys._hotel_audit_build = sig


_drop_stale_modules()

try:  # deprecated: scheduled for removal after 2026-06-01, kept only as a fallback
    import streamlit.components.v1 as components
except Exception:  # noqa: BLE001 - if it has been removed, st.iframe is used instead
    components = None

import ai_check
import compare
import dashboard
import full_audit
import headline
import report_pdf
import store
import ui_consult
import ui_intel

st.set_page_config(page_title="Hotel AI Discoverability Audit",
                   page_icon="H", layout="wide")


def _operator_secret(name):
    """
    Read an operator-held key from Streamlit's secrets store, never from the
    visitor. Returns None if it isn't configured - st.secrets raises if no
    secrets.toml/dashboard config exists at all (the normal case for a fresh
    local checkout), so that's treated the same as "not set" rather than an
    error that would break the page for every visitor.
    """
    try:
        return st.secrets.get(name) or None
    except Exception:  # noqa: BLE001 - st.secrets raising means "none configured"
        return None


TAVILY_KEY = _operator_secret("TAVILY_API_KEY")
AMADEUS_KEY = _operator_secret("AMADEUS_API_KEY")
AMADEUS_SECRET = _operator_secret("AMADEUS_API_SECRET")

# A FREE, UNGROUNDED Gemini key, used only to read and judge text Tavily has
# already fetched (see gemini_reader.py). This is a different cost profile
# from AI Visibility's paid grounding, and configuring it never enables or
# implies AI Visibility, which remains entirely absent from this public app.
GEMINI_READER_KEY = _operator_secret("GEMINI_READER_API_KEY")

# Optional: a YouTube Data API key (free quota, no billing account). Without it the
# video part of the report says so and is skipped.
YOUTUBE_KEY = _operator_secret("YOUTUBE_API_KEY")

# Optional: a Google PageSpeed Insights key (free, from a Google Cloud project with no billing account). Without
# it Google's shared quota is usually used up, so page speed and accessibility scores say they weren't measured.
PAGESPEED_KEY = _operator_secret("PAGESPEED_API_KEY")

# A full audit runs about a dozen Tavily searches (see collect.search_plan).
TAVILY_CREDITS_PER_AUDIT = 12


def _within_quota(service, planned=1):
    """True if this service's shared monthly allowance has room for one more
    audit. Checked before every run so public traffic can't silently exhaust
    an operator's free-tier key."""
    _, _, would_exceed = store.quota_status(planned_calls=planned, service=service)
    return not would_exceed


def _md_safe(s):
    """Escape Markdown characters in third-party text shown via st.markdown, so
    a review excerpt can't render as a link or an (tracking-pixel) image."""
    import re
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~])", r"\\\1", str(s or ""))


def render_comparison(cmp):
    """Native Streamlit rendering (plain-text tables) of compare.compare_reports()."""
    for w in cmp["warnings"]:
        st.warning(w)
    ov = cmp["overall"]
    c1, c2, c3 = st.columns(3)
    if ov.get("delta") is not None and ov["like_for_like"]:
        c1.metric("Overall score", ov["new"], delta=ov["delta"])
    else:
        c1.metric("Overall score", ov["new"] if ov["new"] is not None else "—")
    c2.metric("Things that improved", cmp["headline"]["improved"])
    c3.metric("Things that got worse", cmp["headline"]["declined"])
    st.caption(f"Earlier report: {cmp['old_date'] or 'unknown date'} · "
               f"this report: {cmp['new_date'] or 'unknown date'}")

    if cmp["categories"]:
        st.markdown("**Categories**")
        st.dataframe([{"Category": r["label"],
                       "Before": "—" if r["old"] is None else r["old"],
                       "Now": "—" if r["new"] is None else r["new"],
                       "Change": "" if r["delta"] is None else f"{r['delta']:+d}",
                       "Verdict": r["status"]} for r in cmp["categories"]],
                     width="stretch", hide_index=True)
    if cmp["guest"]:
        st.markdown("**Guest questions**")
        st.dataframe([{"Question": g["short"], "Before": g["old"], "Now": g["new"],
                       "Verdict": g["status"]} for g in cmp["guest"]],
                     width="stretch", hide_index=True)
    rc = cmp["recs"]
    if rc["resolved"] or rc["new"] or rc["still_open"]:
        st.markdown("**Recommendations**")
        st.dataframe(
            [{"Status": "Fixed since the earlier report", "Recommendation": a} for a in rc["resolved"]]
            + [{"Status": "New", "Recommendation": a} for a in rc["new"]]
            + [{"Status": "Still open", "Recommendation": a} for a in rc["still_open"]],
            width="stretch", hide_index=True)
    if cmp["facts"]:
        st.markdown("**Facts that changed**")
        st.dataframe(cmp["facts"], width="stretch", hide_index=True)


st.title("Hotel AI Discoverability Audit")
st.caption(
    "Find the gaps in the information AI search can use about your hotel. "
    "Free, no account, no API keys needed."
)

st.sidebar.title("About")
st.sidebar.caption(
    "This reads your hotel's own website and checks whether it answers the "
    "questions guests (and AI assistants) ask - parking, breakfast, "
    "check-in, pets, accessibility - showing the exact text it relied on. "
    "It also checks whether the hotel is a verified entity in open map and "
    "data sources, how fresh the content is, and how it appears in search "
    "results.\n\n"
    "It does **not** ask an AI assistant about your hotel, and does not read "
    "TripAdvisor or Booking.com directly - their Terms of Use prohibit "
    "automated collection. Anything it can't measure shows as 'not "
    "assessed', never as a made-up score.\n\n"
    "**Three different results you'll see:** *answered* (found it), *not "
    "found on the pages checked* (we looked, nothing there - but we only "
    "read some pages), and *couldn't check* (the page was blocked or "
    "unreadable - never counted against you)."
)

with st.form("full_audit_form"):
    fa_website = st.text_input(
        "Website *", placeholder="brooklandshotelsurrey.com",
        help="The only thing that's required.",
    )
    c1, c2 = st.columns(2)
    fa_hotel = c1.text_input(
        "Hotel name (optional)",
        help="Left blank, it's read from the site's own markup.",
    )
    fa_city = c2.text_input(
        "City (optional)",
        help="Left blank, it's worked out from the site's address, map link "
             "or postcode. Fill it in if the hotel shares its name with one "
             "somewhere else.",
    )
    fa_wider = st.checkbox(
        "Include the wider discovery (media coverage, listings, awards, local context)", value=True,
        help="Adds roughly 1-2 minutes. Untick for the quicker website-only audit.")
    fa_go = st.form_submit_button("Run audit", type="primary")

if fa_go:
    if not fa_website:
        st.error("Enter a website.")
        st.stop()
    prog = st.empty()
    # Only pass a key through if it's actually configured AND this month's
    # shared allowance isn't already used up - otherwise the category falls
    # back to "not assessed" for this run rather than erroring or (for a paid
    # service, if one is ever added here) spending money past a free cap.
    use_tavily = TAVILY_KEY if (TAVILY_KEY and _within_quota("tavily", TAVILY_CREDITS_PER_AUDIT)) else None
    use_amadeus_key = AMADEUS_KEY if (
        AMADEUS_KEY and AMADEUS_SECRET and _within_quota("amadeus")) else None
    use_amadeus_secret = AMADEUS_SECRET if use_amadeus_key else None
    use_gemini_reader = GEMINI_READER_KEY if (
        GEMINI_READER_KEY and _within_quota("gemini_reader")) else None
    try:
        fa_res = full_audit.run_full_audit(
            fa_website, fa_hotel, fa_city, progress=lambda m: prog.caption(m),
            tavily_api_key=use_tavily,
            amadeus_api_key=use_amadeus_key,
            amadeus_api_secret=use_amadeus_secret,
            gemini_reader_key=use_gemini_reader,
            youtube_api_key=YOUTUBE_KEY, wider=fa_wider, pagespeed_api_key=PAGESPEED_KEY,
        )
    except Exception as e:  # noqa: BLE001 - surface the real error
        prog.empty()
        st.error(f"Audit failed: {e}")
        st.stop()

    # Record actual usage against the shared monthly allowance. Tavily now
    # runs a multi-angle search (generic + segment-specific queries), so the
    # real count is however many queries actually ran, not a flat guess -
    # exact, not an estimate, since tavily_check.py reports it directly.
    # Amadeus still estimated at 2 calls (lookup + ratings) - consistent with
    # the original Gemini-only quota always being labelled a floor.
    tr = fa_res.get("tavily_result") or {}
    credits = ((fa_res.get("intel") or {}).get("methodology") or {}).get("tavily_credits_used")
    if tr.get("configured") or credits:
        # exact: the wider pass counts every search it ran; the older scan reuses them
        store.record_usage(credits or len(tr.get("queries_run") or []) or 1, service="tavily")
    if (fa_res.get("amadeus_result") or {}).get("configured"):
        store.record_usage(2, service="amadeus")
    # Exact count: only entries actually read via the LLM path count - a
    # fetch that failed or fell back to rule-based judgment used no quota.
    llm_reads = sum(
        1 for e in tr.get("editorial_hits", []) + tr.get("other_hits", [])
        if e.get("read", {}).get("via") == "llm"
    )
    if llm_reads:
        store.record_usage(llm_reads, service="gemini_reader")
    prog.empty()
    # Manual AI answers belong to one hotel: keep them if the same site is
    # re-audited (the point of re-running after fixes), drop them otherwise.
    prev = st.session_state.get("fa_res")
    if prev and compare._domain(prev["meta"].get("website", "")) != \
            compare._domain(fa_res["meta"].get("website", "")):
        st.session_state["ai_records"] = []
    st.session_state["fa_res"] = fa_res

fa_res = st.session_state.get("fa_res")
if fa_res:
    meta, loc = fa_res["meta"], fa_res["meta"]["location"]
    sc = fa_res["scorecard"]
    recs = fa_res["recommendations"]
    intel = fa_res.get("intel") or {}
    has_intel = bool(intel) and "error" not in intel
    consult = fa_res.get("consultant") or {}
    has_consult = bool(consult) and "error" not in consult

    # ---- downloads first: the PDF is built from the finished audit (no requests)
    json_bytes = json.dumps({**fa_res, "manual_ai_checks": st.session_state.get("ai_records", [])},
                            indent=2, default=str)
    headline.attach(fa_res)       # readiness score, coverage and per-category evidence strength (also for older reports)
    d0, d1, d2 = st.columns([2, 2, 2])
    pdf_key = (meta["run_at"], meta["website"])
    if st.session_state.get("pdf_key") != pdf_key:
        for part in ("management", "appendix"):
            try:
                st.session_state[f"pdf_{part}"] = report_pdf.build_pdf(fa_res, part)
                st.session_state[f"pdf_error_{part}"] = None
            except Exception as e:  # noqa: BLE001 - a PDF problem must never hide the report
                st.session_state[f"pdf_{part}"] = None
                st.session_state[f"pdf_error_{part}"] = f"{type(e).__name__}: {e}"
        st.session_state["pdf_key"] = pdf_key
    if st.session_state.get("pdf_management"):
        d0.download_button("Download management report (PDF)", st.session_state["pdf_management"],
                           file_name=report_pdf.filename(fa_res, "management"), mime="application/pdf",
                           type="primary", width="stretch",
                           help="A short, decision-oriented summary: the score and coverage, the top actions, gaps, risks and a 30/60/90-day plan.")
    else:
        d0.warning("The management report could not be built (" + str(st.session_state.get("pdf_error_management")) + ").")
    if st.session_state.get("pdf_appendix"):
        d1.download_button("Download technical & evidence appendix (PDF)", st.session_state["pdf_appendix"],
                           file_name=report_pdf.filename(fa_res, "appendix"), mime="application/pdf", width="stretch",
                           help="All the detail behind the management report: findings, quotes, URLs, methodology, structured-data examples.")
    else:
        d1.warning("The appendix could not be built (" + str(st.session_state.get("pdf_error_appendix")) + ").")
    d2.download_button(
        "Download report data (.json)", json_bytes,
        file_name=f"{store.slug(meta['hotel'] or meta['website'])}-audit-{str(meta['run_at'])[:10]}.json",
        mime="application/json", width="stretch",
        help="Keep it to compare with a future run (Tools tab).")
    st.caption(f"Run {meta['run_at'][:16].replace('T', ' ')} UTC · hotel name {meta['hotel_name_source']}"
               + (f" · location from {loc['source']}" if loc.get("source") else ""))

    if intel and not has_intel:
        st.warning("The wider discovery and reputation analysis failed for this run "
                   f"({intel.get('error')}). The website score and guest-question results below are unaffected.")

    names = ["Overview", "How AI sees your hotel", "Fix your website", "Beyond your website", "Scorecard", "Tools & method"]
    tabs = st.tabs(names)

    # ------------------------------------------------------------- the consultant view
    with tabs[0]:
        if has_consult:
            ui_consult.overview(consult, fa_res.get("headline"))
        elif has_intel:
            ui_intel.overview(intel)
        else:
            st.info("The analysis of what AI systems can understand about this hotel did not run for this audit. "
                    "The Scorecard tab still has the website results.")
    with tabs[1]:
        if has_consult:
            ui_consult.ai_view(consult)
        else:
            st.info("This section needs the consultant analysis, which did not run for this audit.")
    with tabs[2]:
        if has_consult:
            ui_consult.fix_site(consult, fa_res.get("web_signals"))
        else:
            st.info("This section needs the consultant analysis, which did not run for this audit.")

    # ------------------------------------------------------------- outside the hotel's own website
    with tabs[3]:
        st.caption("Evidence from outside the hotel's own website: where it is listed, how others describe it, and who covers it.")
        sub = st.tabs(["Identity & distribution", "Reviews & reputation", "Media & validation", "Traveller fit", "Social & local"])
        for t, fn in zip(sub, ("identity", "reviews", "media", "traveller", "social_local")):
            with t:
                if has_intel:
                    getattr(ui_intel, fn)(intel)
                else:
                    st.info("This section needs the wider discovery analysis, which did not run for this audit.")

    # ------------------------------------------------------------- the original scorecard
    with tabs[4]:
        st.caption("The original eight-category scorecard, with its coverage. The other tabs add evidence and recommendations; "
                   "this number is unchanged by them.")
        top = fa_res.get("top_fixes") or []
        top_codes = {r.get("code") for r in top}
        rest = [r for r in recs if r.get("code") not in top_codes]
        html_doc, est_height = dashboard.build(
            meta["hotel"], meta["website"], sc, rest,
            fa_res.get("guest_questions"), top, fa_res.get("headline"))
        # st.iframe replaces st.components.v1.html (removal date already passed) and
        # sizes itself to the content. It embeds the string as-is with JavaScript
        # and same-origin access, so the string must never contain untrusted
        # markup - dashboard.build escapes everything and test_dashboard.py checks it.
        if hasattr(st, "iframe"):
            st.iframe(html_doc, height="content")
        elif components is not None:
            components.html(html_doc, height=est_height, scrolling=True)
        else:
            st.error("This version of Streamlit can't display the dashboard. "
                     "Upgrade with: pip install -U streamlit")

        st.caption(
            f"run {meta['run_at']} · hotel name {meta['hotel_name_source']}"
            + (f" · location from {loc['source']}" if loc.get("source") else "")
        )
        st.info(f"**Read the score with its coverage.** {sc['caveat']}")

        # ---- per-category evidence, and what's not assessed - detail, not the
        # headline view the dashboard above already gives
        for c in sc["categories"]:
            if not c["assessed"]:
                continue
            label = f"{c['label']} — {c['score']}/100 (weight {c['weight']}%)"
            if c.get("partial"):
                label += "  ·  PARTIAL"
            with st.expander(label):
                st.caption(c["detail"])
                for e in c["evidence"]:
                    st.write(f"- {e}")

        not_assessed = [c for c in sc["categories"] if not c["assessed"]]
        if not_assessed:
            missing_weight = round(sum(c["weight"] for c in not_assessed), 1)
            with st.expander(
                f"⚠️ Not assessed — {missing_weight}% of the model "
                f"({len(not_assessed)} categories)"
            ):
                st.caption(
                    "Not measured at all. Neither helps nor hurts the score "
                    "above — but this is most of what the model weights, so "
                    "treat the score as partial evidence, not a final verdict."
                )
                for c in not_assessed:
                    st.markdown(
                        f"**{c['label']}** *(worth {c['weight']}%)*  \n"
                        f"{c['detail']}  \n\n"
                        f"*What this would take:* {c.get('how_to_enable', '')}"
                    )
                    st.divider()


        st.divider()
        if has_intel:
            ui_intel.website(intel)
        # ---- the fact sheet: what a machine could learn from this site, each
        # fact with the page it came from, so a wrong one can be traced and fixed
        gq_res = fa_res.get("guest_questions") or {}
        sheet = gq_res.get("fact_sheet") or []
        if sheet:
            st.subheader("What your website tells us about your hotel")
            st.caption(
                "Every fact below was read from your own pages, with the page it "
                "came from. If one is wrong or missing, that is what an AI "
                "assistant will repeat. Read by simple rules, not understanding - "
                "check anything that looks off."
            )
            for c in gq_res.get("conflicts") or []:
                vals = "; ".join(f"{v['value']} ({v['source_url']})" for v in c["values"])
                st.warning(f"**{c['fact']} differs between pages:** {vals}. {c['note']}.")
            st.dataframe(
                [{"Fact": r["fact"], "What the site says": r["value"],
                  "Where": r["source_url"], "How it was read": r["note"]} for r in sheet],
                column_config={"Where": st.column_config.LinkColumn("Page")},
                width="stretch", hide_index=True,
            )
            if fa_res.get("own_facts_source") == "page text":
                st.caption(
                    "This site publishes no structured data, so these page-text "
                    "facts were also used to cross-check OpenStreetMap and Wikidata."
                )


        # ---- supporting detail, collapsed - evidence trail, not a second thing
        # to operate
        st.subheader("Supporting detail")
        d1, d2 = st.columns(2)
        with d1:
            with st.expander("Entity presence (OpenStreetMap, Wikidata)"):
                for e in fa_res["entities"]:
                    if e.get("found") and e.get("match_confident") is True:
                        st.success(
                            f"**{e['source']}** — verified"
                            + (f" ({e['match_reason']})" if e.get("match_reason") else "")
                            + f"  \n[{(e.get('label') or e.get('display_name', ''))[:70]}]"
                              f"({e.get('url', '')})"
                        )
                    elif e.get("found"):
                        st.warning(f"**{e['source']}** — unverified  \n{e.get('note', '')}")
                    else:
                        st.error(f"**{e['source']}** — not found  \n"
                                f"{e.get('note') or e.get('error', '')}")
            with st.expander("Linked profiles"):
                profs = fa_res["discovery"]["profiles"]
                if profs:
                    st.dataframe(profs, width="stretch", hide_index=True)
                    st.caption("Declared in JSON-LD `sameAs`: "
                              + ("yes" if fa_res["discovery"]["declares_sameas"] else "no"))
                else:
                    st.info("No profiles linked from the hotel's own pages.")
        with d2:
            tr = fa_res.get("tavily_result") or {}
            if tr.get("configured"):
                with st.expander("Editorial, OTA & social search (Tavily)", expanded=True):
                    if tr.get("segments_detected"):
                        st.caption(
                            "Checked as: **" + ", ".join(tr["segments_detected"]) +
                            "** — detected from the hotel's own topic pages, so "
                            "the search angles were tailored to this hotel, not generic."
                        )
                    ota = ", ".join(h["platform"] for h in tr.get("ota_hits", [])) or "none found"
                    social = ", ".join(h["platform"] for h in tr.get("social_hits", [])) or "none found"
                    st.write(f"**OTAs found:** {ota}")
                    st.write(f"**Independently-found social presence:** {social}")

                    confirmed = [h for h in tr.get("editorial_hits", [])
                                if h.get("read", {}).get("confirmed") is True]
                    if confirmed:
                        st.write("**Editorial coverage — read and judged, not just found:**")
                        sentiment_icon = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
                        for h in confirmed:
                            r = h["read"]
                            icon = sentiment_icon.get(r.get("sentiment"), "⚪")
                            via = " · read by LLM" if r.get("via") == "llm" else " · rule-based read"
                            link = h["url"] if str(h["url"]).startswith(("http://", "https://")) else ""
                            st.markdown(
                                f"{icon} **[{_md_safe(h['platform'])}]({link})** — "
                                f"{_md_safe(r.get('substance', 'unknown'))}, "
                                f"{_md_safe(r.get('sentiment', 'unknown'))}"
                                f"*{via}*  \n{_md_safe(r.get('excerpt', ''))}"
                            )
                    else:
                        st.caption("No confirmed editorial coverage found in the searches run.")

                    if tr.get("error"):
                        st.caption(f"Note: one or more searches failed ({tr['error']}) — "
                                  f"results above are from whichever succeeded.")

            if fa_res["consistency"]:
                with st.expander("Fact consistency"):
                    st.dataframe(fa_res["consistency"], width="stretch",
                                 hide_index=True)
            if fa_res["blocked_sources"]:
                with st.expander(
                    f"Sources that refused automated access ({len(fa_res['blocked_sources'])})"
                ):
                    st.caption(
                        "These returned an error rather than a page — TripAdvisor "
                        "and Booking.com's Terms of Use prohibit automated "
                        "collection, so this tool doesn't attempt it. Check by "
                        "hand in a browser if you need what's on these pages."
                    )
                    st.dataframe(fa_res["blocked_sources"], width="stretch",
                                 hide_index=True)

        with st.expander("Website detail"):
            s = fa_res["site"]
            st.caption("These two lists are a guess from page addresses - the pages "
                       "were not read. The guest-question section above is the "
                       "evidence-based check.")
            st.write(f"**Topics with a matching page address:** {', '.join(s['topics_covered']) or 'none'}")
            st.write(f"**Topics with no matching page address:** "
                     f"{', '.join(s['topics_no_page_found']) or 'none'}")
            st.write(f"**Schema types found:** {', '.join(s['schema_types_found']) or 'none'}")
            st.dataframe(
                [{"url": p["url"], "status": p.get("status"),
                  "title": (p.get("title") or "")[:70]} for p in s["pages"]],
                width="stretch", hide_index=True,
            )



    with tabs[5]:
        st.subheader("Method: all 30 checks and what each source could and couldn't tell us")
        if has_intel:
            ui_intel.gaps(intel)
        else:
            st.info("The 30-check methodology table needs the wider analysis, which did not run.")


        st.divider()
        st.caption("Optional extras. Nothing here is part of the score.")
        # ---- the manual AI answer check. We don't call AI assistants (grounded
        # AI search costs real money and every free route was closed), but we can
        # make it easy for a person to run the test themselves and record it.
        st.subheader("Check what AI assistants actually say about your hotel")
        st.caption(
            "This tool doesn't ask AI assistants for you, but you can in a few "
            "minutes, free, in whichever assistant you use. Copy a prompt, paste it "
            "in, then record what came back. Each answer is **one sample** — an "
            "assistant can answer differently tomorrow, with web search on or off — "
            "so look for patterns across several answers, not a verdict from one. "
            "These records are not part of the score."
        )
        ai_prompts = ai_check.build_prompts(meta["hotel"], meta.get("city") or "",
                                            fa_res.get("segments"))
        ai_by_id = {p["id"]: p for p in ai_prompts}
        t_acc, t_dis = st.tabs(["Accuracy — does it get the facts right?",
                                "Discovery — does it suggest the hotel?"])
        with t_acc:
            st.caption("These name the hotel. Check each fact in the answer against your own site.")
            for p in (p for p in ai_prompts if p["kind"] == "accuracy"):
                st.markdown(f"**{p['label']}**")
                st.code(p["prompt"], language=None)
        with t_dis:
            st.caption("These never name the hotel — that is the test. Would someone who has "
                       "never heard of you be pointed to you?")
            disc = [p for p in ai_prompts if p["kind"] == "discovery"]
            if not disc:
                st.info("Add a city above to get discovery prompts (they need a place).")
            for p in disc:
                st.markdown(f"**{p['label']}**")
                st.code(p["prompt"], language=None)

        records = st.session_state.setdefault("ai_records", [])
        with st.expander("Record an answer you got", expanded=not records):
            with st.form("ai_record_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                prompt_choice = f1.selectbox(
                    "Which prompt did you use?", [p["id"] for p in ai_prompts],
                    format_func=lambda i: f"{ai_by_id[i]['kind'].title()}: {ai_by_id[i]['label']}")
                assistant = f2.selectbox("Which assistant?", ai_check.ASSISTANTS)
                custom_prompt = st.text_input("…or your own prompt (optional, overrides the choice above)")
                g1, g2, g3 = st.columns(3)
                web = g1.selectbox("Was web search on?", ai_check.WEB_SEARCH,
                                   format_func={"yes": "Yes", "no": "No", "unknown": "Don't know"}.get)
                when = g2.date_input("Date", value=dt.date.today())
                mention = g3.radio("Did it mention the hotel?", ai_check.MENTION,
                                   format_func=ai_check.MENTION_LABEL.get)
                facts = st.radio("Were the hotel's facts right?", ai_check.FACTS,
                                 format_func=ai_check.FACTS_LABEL.get, horizontal=True,
                                 help="For discovery prompts, choose \"Didn't state the facts\" "
                                      "unless it said something factual about your hotel.")
                wrong = st.text_area("If something was wrong, what?", height=70)
                srcs = st.text_area("Sources it cited (paste the links, one per line)", height=80)
                submitted = st.form_submit_button("Add this answer")
            if submitted:
                chosen = ai_by_id.get(prompt_choice)
                text = custom_prompt.strip() or (chosen["prompt"] if chosen else "")
                if not text:
                    st.error("Pick a prompt or type your own.")
                else:
                    if custom_prompt.strip():
                        named = bool(meta["hotel"]) and meta["hotel"].lower() in text.lower()
                        kind, pid = ("accuracy" if named else "discovery"), "custom"
                    else:
                        kind, pid = chosen["kind"], chosen["id"]
                    try:
                        records.append(ai_check.clean_record({
                            "assistant": assistant, "date": when.isoformat(), "kind": kind,
                            "prompt_id": pid, "prompt": text, "web_search": web,
                            "mention": mention, "facts": facts, "wrong_detail": wrong,
                            "sources": srcs}))
                        st.success("Added.")
                    except ValueError as e:
                        st.error(f"Couldn't save that: {e}")

        if records:
            st.dataframe(
                [{"Date": r["date"], "Assistant": r["assistant"], "Prompt": r["prompt"][:70],
                  "Web search": r["web_search"],
                  "Hotel": ai_check.MENTION_LABEL[r["mention"]],
                  "Facts": ai_check.FACTS_LABEL[r["facts"]],
                  "Sources": len(r["sources"])} for r in records],
                width="stretch", hide_index=True)
            summ = ai_check.summarise(records, meta["website"])
            m1, m2, m3 = st.columns(3)
            m1.metric("Answers recorded", summ["n"])
            m2.metric("Suggested your hotel (discovery)",
                      f"{summ['discovery_mentioned']} of {summ['n_discovery']}"
                      if summ["n_discovery"] else "—")
            m3.metric("Got facts wrong (accuracy)",
                      f"{len(summ['accuracy_wrong'])} of {summ['n_accuracy']}"
                      if summ["n_accuracy"] else "—")
            for cav in summ["caveats"]:
                st.warning(cav)
            if summ["accuracy_wrong"]:
                with st.expander("What the assistants got wrong"):
                    for r in summ["accuracy_wrong"]:
                        st.text(f"{r['assistant']} ({r['date']}): {r['wrong_detail'] or '(no detail given)'}")
            if summ["cited_domains"]:
                st.markdown("**Where the assistants got their information**")
                st.dataframe([{"Source": d, "Answers citing it": n} for d, n in summ["cited_domains"]],
                             width="stretch", hide_index=True)
                st.caption(f"Your own site was cited in {summ['own_cited']} of "
                           f"{summ['answers_with_sources']} answers that listed sources. If other "
                           f"sites are doing the talking, those are the pages to make accurate.")
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("Remove last"):
                records.pop()
                st.rerun()
            if b2.button("Clear all"):
                records.clear()
                st.rerun()

        st.info(
            "**Real citation data, if you own the website:** Bing Webmaster Tools has an "
            "*AI Performance* report showing how often your pages are cited in Microsoft "
            "Copilot and Bing's AI summaries (public preview). It does **not** cover "
            "ChatGPT, Gemini or Perplexity. "
            "[How it works](https://blogs.bing.com/webmaster/February-2026/"
            "Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview)"
        )


        # ---- compare with an earlier report. Nothing is stored on the server: the
        # visitor keeps their own dated file and brings it back.
        st.subheader("Compare with an earlier report")
        st.caption(
            "Run the audit again after making changes, then upload the .json you "
            "downloaded last time to see what moved. Your reports are never stored "
            "here — you keep the file."
        )
        prev_file = st.file_uploader("Upload an earlier report (.json)", type=["json"],
                                     key="prev_report")
        if prev_file is not None:
            if prev_file.size > compare.MAX_BYTES:
                st.error("That file is too large to be one of this tool's reports.")
            else:
                try:
                    prev_report = json.load(prev_file)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    prev_report = None
                    st.error("That file isn't valid JSON, so it can't be one of this "
                             "tool's reports.")
                if prev_report is not None:
                    try:
                        render_comparison(compare.compare_reports(prev_report, fa_res))
                    except ValueError as e:
                        st.error(str(e))

