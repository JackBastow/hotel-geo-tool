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

import json

import streamlit as st

import full_audit
import store

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


def _within_quota(service):
    """True if this service's shared monthly allowance has room for one more
    audit. Checked before every run so public traffic can't silently exhaust
    an operator's free-tier key."""
    _, _, would_exceed = store.quota_status(planned_calls=1, service=service)
    return not would_exceed


st.title("Hotel AI Discoverability Audit")
st.caption(
    "How visible, and how correctly described, is a hotel to AI answer "
    "engines? Free, no account, no API keys needed."
)

st.sidebar.title("About")
st.sidebar.caption(
    "This checks the free, public signals of how machine-readable a hotel "
    "is: its own website, whether it's a verified entity in open map/data "
    "sources, and how fresh its content is.\n\n"
    "It does **not** automate asking an AI assistant about the hotel, and "
    "does not read TripAdvisor, Booking.com or similar listing sites "
    "directly - their Terms of Use explicitly prohibit automated "
    "collection, so this tool doesn't attempt it. Both of those show up as "
    "'not assessed' below, with an explanation, rather than a made-up score."
)

SEVERITY_UI = {
    "critical": ("🔴", st.error), "high": ("🟠", st.warning),
    "medium": ("🟡", st.warning), "low": ("⚪", st.info),
}

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
    use_tavily = TAVILY_KEY if (TAVILY_KEY and _within_quota("tavily")) else None
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
    if tr.get("configured"):
        store.record_usage(len(tr.get("queries_run") or []) or 1, service="tavily")
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
    st.session_state["fa_res"] = fa_res

fa_res = st.session_state.get("fa_res")
if fa_res:
    meta, loc = fa_res["meta"], fa_res["meta"]["location"]
    st.subheader(f"{meta['hotel'] or fa_res['meta']['website']}")
    st.caption(
        f"{meta['website']} · run {meta['run_at']} · "
        f"hotel name {meta['hotel_name_source']}"
        + (f" · location from {loc['source']}" if loc.get("source") else "")
    )

    sc = fa_res["scorecard"]
    recs = fa_res["recommendations"]

    m1, m2, m3 = st.columns([1, 1, 2])
    m1.metric("Score", sc["overall"],
              help="Weighted across the categories that could actually be "
                   "measured. Not a score out of 100 for the whole model.")
    m2.metric("Model covered", f"{sc['coverage_pct']}%",
              help="Share of the weighted model that was assessed.")
    m3.metric("Things to fix", len(recs),
              help="Prioritised recommendations, worst first.")

    st.progress(sc["coverage_pct"] / 100.0)
    st.error(f"**Read the score with its coverage.** {sc['caveat']}")

    # ---- category breakdown: the "why did it get that score" view
    st.subheader("How the score breaks down")
    st.dataframe(
        [{
            "Category": c["label"],
            "Weight": f"{c['weight']}%",
            "Score": c["score"] if c["assessed"] else "—",
            "Status": ("partial" if c.get("partial")
                       else ("assessed" if c["assessed"] else "not assessed")),
        } for c in sc["categories"]],
        use_container_width=True, hide_index=True,
    )

    for c in sc["categories"]:
        if not c["assessed"]:
            continue
        label = f"{c['label']} — {c['score']}/100 (weight {c['weight']}%)"
        if c.get("partial"):
            label += "  ·  PARTIAL"
        with st.expander(label, expanded=c["score"] < 60):
            st.caption(c["detail"])
            for e in c["evidence"]:
                st.write(f"- {e}")

    not_assessed = [c for c in sc["categories"] if not c["assessed"]]
    if not_assessed:
        missing_weight = round(sum(c["weight"] for c in not_assessed), 1)
        with st.expander(
            f"⚠️ Not assessed — {missing_weight}% of the model "
            f"({len(not_assessed)} categories)", expanded=True
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

    # ---- recommendations
    st.subheader("What to do, worst first")
    if not recs:
        st.success("No recommendations from the categories that were assessed.")
    for r in recs:
        icon, render = SEVERITY_UI.get(r["priority"], ("⚪", st.info))
        render(f"{icon} **{r['action']}**  \n*{r['category']}* — {r['why']}")

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
                st.dataframe(profs, use_container_width=True, hide_index=True)
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
                        st.markdown(
                            f"{icon} **[{h['platform']}]({h['url']})** — "
                            f"{r.get('substance', 'unknown')}, {r.get('sentiment', 'unknown')}"
                            f"*{via}*  \n{r.get('excerpt', '')}"
                        )
                else:
                    st.caption("No confirmed editorial coverage found in the searches run.")

                if tr.get("error"):
                    st.caption(f"Note: one or more searches failed ({tr['error']}) — "
                              f"results above are from whichever succeeded.")

        if fa_res["consistency"]:
            with st.expander("Fact consistency"):
                st.dataframe(fa_res["consistency"], use_container_width=True,
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
                st.dataframe(fa_res["blocked_sources"], use_container_width=True,
                             hide_index=True)

    with st.expander("Website detail"):
        s = fa_res["site"]
        st.write(f"**Topics with a page:** {', '.join(s['topics_covered']) or 'none'}")
        st.write(f"**Topics with no obvious page:** "
                 f"{', '.join(s['topics_no_page_found']) or 'none'}")
        st.write(f"**Schema types found:** {', '.join(s['schema_types_found']) or 'none'}")
        st.dataframe(
            [{"url": p["url"], "status": p.get("status"),
              "title": (p.get("title") or "")[:70]} for p in s["pages"]],
            use_container_width=True, hide_index=True,
        )

    st.download_button(
        "Download full findings (.json)",
        json.dumps(fa_res, indent=2),
        file_name=f"{store.slug(meta['hotel'] or meta['website'])}-audit.json",
        mime="application/json",
    )
