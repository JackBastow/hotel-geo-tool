"""
Hotel AI Discoverability Audit - public dashboard.

Run with:  streamlit run app.py

ONE ACTION, NO ACCOUNT, NO KEYS. Type a website, press "Run audit", get a
report. This is meant to be hosted somewhere with a public URL (Streamlit
Community Cloud to start) so anyone - no Claude access, no API keys of their
own, nothing installed - can just use it.

That public-and-free design shapes everything here:

  - No API keys anywhere in this file, and none asked of the visitor. A
    public page that collected strangers' API keys would be a bad idea on
    its own; a public page that spent an OPERATOR's paid API keys every time
    a stranger clicked a button would be worse. So this build only ever
    calls full_audit.run_full_audit() with no optional integrations - the
    free, keyless pipeline (Website & Technical, Entity Consistency,
    Freshness, Social presence). AI visibility, OTA presence, Reviews and
    Editorial coverage are real categories in the model but need a paid or
    keyed data source each; they report "not assessed" here, honestly, with
    an explanation rather than a wrong number. See full_audit.py and
    scoring.py's module docstrings for what each would take to add back for
    a private/self-hosted deployment.

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
    try:
        # No optional keys passed - this is the permanent free/keyless path.
        fa_res = full_audit.run_full_audit(
            fa_website, fa_hotel, fa_city, progress=lambda m: prog.caption(m),
        )
    except Exception as e:  # noqa: BLE001 - surface the real error
        prog.empty()
        st.error(f"Audit failed: {e}")
        st.stop()
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
