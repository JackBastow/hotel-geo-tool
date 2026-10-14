"""
The admin page: every saved audit, how each hotel is doing over time, the market view across hotels, usage, and exports.

Opened with ?admin=1 on the app's address and protected by the ADMIN_PASSWORD secret. Nothing here is linked from the public page.
If the database or the password is not configured, the page says so and shows nothing.
"""

import hmac
import io
import json
import time
import zipfile

import streamlit as st

import backend
import ui_theme

PUB_COLS = ["id", "run_at", "hotel", "city", "headline_status", "headline_score", "coverage_pct", "ai_generic_named", "ai_generic_asked", "ai_niche_named",
            "ai_niche_asked", "ai_share", "ai_coverage_pct", "ai_sentiment", "ai_rank_in_table", "ai_top_competitor", "reviews_replied", "reviews_examined", "pagespeed_perf", "recs_total", "ai_cost_usd"]
NICE = {"run_at": "Run", "hotel": "Hotel", "city": "City", "headline_status": "Headline", "headline_score": "Readiness", "coverage_pct": "Readiness coverage %",
        "ai_generic_named": "Named (town)", "ai_generic_asked": "of", "ai_niche_named": "Named (niche)", "ai_niche_asked": "of ", "ai_share": "Share of names %",
        "ai_coverage_pct": "Coverage %", "ai_sentiment": "Net sentiment", "ai_rank_in_table": "Place in table", "ai_top_competitor": "Top competitor", "reviews_replied": "Replies seen", "reviews_examined": "Reviews examined",
        "pagespeed_perf": "Mobile speed", "recs_total": "Recommendations", "ai_cost_usd": "AI cost $", "id": "Run id"}


def _table(rows, cols=None, rename=NICE, height=None):
    if not rows:
        st.caption("Nothing to show yet.")
        return
    cols = cols or list(rows[0])
    data = [{rename.get(c, c): ("" if r.get(c) is None else (str(r[c]) if not isinstance(r[c], (int, float)) or isinstance(r[c], bool) else r[c])) for c in cols} for r in rows]
    st.dataframe(data, width="stretch", hide_index=True, **({"height": height} if height else {}))


def gate(password):
    """True once the visitor has typed the admin password. Wrong guesses are slowed down."""
    if not password:
        st.error("The admin page is switched off: no ADMIN_PASSWORD secret is set.")
        return False
    if st.session_state.get("admin_ok"):
        return True
    st.title("Admin")
    pw = st.text_input("Password", type="password")
    if pw:
        if hmac.compare_digest(pw.encode(), str(password).encode()):
            st.session_state["admin_ok"] = True
            st.rerun()
        time.sleep(1.5)
        st.error("Wrong password.")
    return False


def _reports_zip(store, rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in rows:
            rep = store.get_report(r["id"])
            if rep is not None:
                z.writestr(f"{backend.hotel_key(rep).replace('/', '_')}__{str(r['run_at'])[:10]}__{r['id']}.json", json.dumps(rep, indent=1, default=str))
    return buf.getvalue()


def page(database_url, password):
    if not gate(password):
        return
    if not database_url:
        st.title("Admin")
        st.warning("No database is connected (no DATABASE_URL secret), so no runs are being saved. See the README for the 5-minute setup.")
        return
    try:
        store = backend.open_store(database_url)
    except Exception as e:  # noqa: BLE001 - show the real reason to the operator
        st.title("Admin")
        st.error(f"The database could not be reached: {type(e).__name__}: {str(e)[:300]}")
        return

    st.title("Admin: saved audits")
    st.caption("Everything the app has saved. Only people with the password can see this. Hotel data here comes from public sources; the full report for any run can be reopened, compared or exported.")
    tabs = st.tabs(["Overview", "Runs", "Hotels", "Markets", "Usage", "Export"])

    with tabs[0]:
        runs = store.list_runs(limit=2000)
        month = time.strftime("%Y-%m")
        this = [r for r in runs if str(r["run_at"]).startswith(month)]
        a, b, c, d = st.columns(4)
        a.metric("Audits saved", len(runs))
        b.metric("Hotels", len({r["hotel_key"] for r in runs}))
        c.metric("Audits this month", len(this))
        d.metric("AI cost this month (est.)", f"${sum((r['ai_cost_usd'] or 0) for r in this):.2f}")
        st.markdown("##### Latest audits")
        _table(runs[:15], PUB_COLS[1:])

    with tabs[1]:
        c1, c2, c3 = st.columns(3)
        text = c1.text_input("Hotel or website contains")
        city = c2.selectbox("City", [""] + store.cities(), format_func=lambda x: x or "(all)")
        since = c3.text_input("Since (YYYY-MM-DD)")
        rows = store.list_runs(limit=500, text=text or None, city=city or None, since=since or None)
        st.caption(f"{len(rows)} run(s)")
        _table(rows, PUB_COLS, height=380)
        if rows:
            pick = st.selectbox("Open a run", [r["id"] for r in rows], format_func=lambda i: next(f"#{r['id']}  {str(r['run_at'])[:10]}  {r['hotel'] or r['hotel_key']}" for r in rows if r["id"] == i))
            rep = store.get_report(pick)
            if rep:
                st.markdown(f"**{(rep.get('meta') or {}).get('hotel', '')}** - {(rep.get('meta') or {}).get('website', '')}")
                h = rep.get("headline") or {}
                st.write(f"Headline: {h.get('status', '-')} {'' if h.get('score') is None else str(h['score']) + '/100'} (coverage {h.get('coverage_pct', '-')}%)")
                tops = [r for r in (rep.get("consultant") or {}).get("recommendations", []) if r["id"] in ((rep.get("consultant") or {}).get("top_actions") or [])]
                for r in tops:
                    st.markdown(f"- **{r['title']}** ({r['priority']}, {r['team']})")
                d1, d2, d3 = st.columns(3)
                d1.download_button("Report data (.json)", json.dumps(rep, indent=1, default=str), file_name=f"run-{pick}.json", mime="application/json", on_click="ignore")
                try:
                    import report_pdf
                    d2.download_button("Management report (PDF)", report_pdf.build_pdf(rep, "management"), file_name=f"run-{pick}-management.pdf", mime="application/pdf", on_click="ignore")
                    d3.download_button("Technical appendix (PDF)", report_pdf.build_pdf(rep, "appendix"), file_name=f"run-{pick}-appendix.pdf", mime="application/pdf", on_click="ignore")
                except Exception as e:  # noqa: BLE001
                    d2.caption(f"PDFs could not be rebuilt for this run ({type(e).__name__}).")
                with st.expander("Delete this run"):
                    st.caption("Removes the run and its market rows permanently.")
                    if st.checkbox(f"Yes, delete run #{pick}", key=f"del{pick}") and st.button("Delete", key=f"delb{pick}"):
                        store.delete_run(pick)
                        st.success("Deleted. Reload the page.")

    with tabs[2]:
        hs = store.hotels()
        st.caption("One row per hotel (the same website, or the same hotel folder on a chain's site). Changes compare the latest run with the one before.")
        _table(hs, ["hotel", "city", "runs", "last_run", "headline_score", "d_score", "ai_named", "ai_asked", "niche_named", "niche_asked", "ai_share", "d_share"],
               {"hotel": "Hotel", "city": "City", "runs": "Runs", "last_run": "Last run", "headline_score": "Readiness", "d_score": "Change", "ai_named": "Named (town)",
                "ai_asked": "of", "niche_named": "Named (niche)", "niche_asked": "of ", "ai_share": "Share of names %", "d_share": "Share change"})
        if hs:
            key = st.selectbox("Hotel history", [h["hotel_key"] for h in hs], format_func=lambda k: next((h["hotel"] or k) + (f" ({h['city']})" if h["city"] else "") for h in hs if h["hotel_key"] == k))
            hist = store.history(key)
            if len(hist) >= 2:
                try:
                    import pandas as pd
                    df = pd.DataFrame({"Readiness": [r["headline_score"] for r in hist], "Share of names %": [r["ai_share"] for r in hist]},
                                      index=[str(r["run_at"])[:10] for r in hist])
                    ui_theme.lines_chart(df)
                    named = pd.DataFrame({"Named, town-wide %": [100 * r["ai_generic_named"] / r["ai_generic_asked"] if r["ai_generic_asked"] else None for r in hist],
                                          "Named, niche markets %": [100 * r["ai_niche_named"] / r["ai_niche_asked"] if r["ai_niche_asked"] else None for r in hist]},
                                         index=[str(r["run_at"])[:10] for r in hist])
                    ui_theme.lines_chart(named)
                except Exception:  # noqa: BLE001
                    pass
            else:
                st.caption("A trend needs two or more runs of the same hotel.")
            ch = store.competitor_history(key)
            if len(ch["runs"]) >= 2 and ch["rows"]:
                st.markdown("**Coverage over time: this hotel and the hotels the assistant names most alongside it**")
                st.caption("The share of all answers that named each hotel, run by run. A rival not named in a run counts as 0% for that run. One model, one day per run: look for sustained moves.")
                try:
                    import pandas as pd
                    idx = [f"{str(r['run_at'])[:10]} #{r['run_id']}" for r in ch["runs"]]
                    ui_theme.lines_chart(pd.DataFrame({("→ " if r["is_target"] else "") + r["name"][:34]: [p["coverage_pct"] for p in r["points"]] for r in ch["rows"]}, index=idx))
                    sent = {r["name"][:34]: [p["sentiment"] for p in r["points"]] for r in ch["rows"] if any(p["sentiment"] is not None for p in r["points"])}
                    if sent:
                        st.markdown("**Net sentiment over time (-100 to +100, where named)**")
                        ui_theme.lines_chart(pd.DataFrame(sent, index=idx))
                except Exception:  # noqa: BLE001
                    pass
            elif ch["rows"]:
                st.caption("The competitors-over-time view appears once this hotel has two or more runs.")
            _table(list(reversed(hist)), PUB_COLS)

    with tabs[3]:
        city = st.selectbox("Market (city)", [""] + store.cities(), format_func=lambda x: x or "(all cities)", key="mk_city")
        st.caption("Across every hotel audited: who the assistant names, and which sites it relies on. One model, one day each, so read patterns, not single numbers.")
        a, b = st.columns(2)
        with a:
            st.markdown("**Hotels named most in town-wide answers**")
            _table(store.competitors(city or None, "generic"), ["competitor", "mentions", "runs", "avg_rank"], {"competitor": "Hotel", "mentions": "Mentions", "runs": "Audits", "avg_rank": "Avg position"})
        with b:
            st.markdown("**Hotels named most in niche markets**")
            _table(store.competitors(city or None, "niche"), ["competitor", "mentions", "runs", "avg_rank"], {"competitor": "Hotel", "mentions": "Mentions", "runs": "Audits", "avg_rank": "Avg position"})
        st.markdown("**Pages the assistant used most (exact pages)**")
        _table(store.pages(city or None), ["url", "domain", "cited", "questions", "runs", "names_hotel", "names_competitor"],
               {"url": "Page", "domain": "Site", "cited": "Times cited", "questions": "Question uses", "runs": "Audits", "names_hotel": "Audits where it names a hotel audited",
                "names_competitor": "A competitor it names"})
        st.markdown("**Sites the assistant relies on**")
        _table(store.sources(city or None), ["domain", "kind", "answers", "runs", "hotel_found", "hotel_missing"],
               {"domain": "Site", "kind": "Type", "answers": "Used in answers", "runs": "Audits", "hotel_found": "Hotel found there", "hotel_missing": "Hotel not found there"})

    with tabs[4]:
        st.markdown("##### By month")
        _table(store.usage_by_month(), ["month", "runs", "hotels", "ai_cost_usd"], {"month": "Month", "runs": "Audits", "hotels": "Hotels", "ai_cost_usd": "Estimated AI cost $"})
        st.caption("Costs are the app's own estimates from reported token use and searches. The Anthropic Console is the source of truth for what was charged.")

    with tabs[5]:
        st.markdown("##### Pull the data")
        rows = store.export_rows()
        st.download_button(f"All {len(rows)} runs, summary table (.csv)", backend.to_csv(rows), file_name="hotel-audit-runs.csv", mime="text/csv", on_click="ignore")
        st.download_button("Hotels named by the assistant, all audits (.csv)", backend.to_csv(store.competitors(None, "generic", limit=100000) + store.competitors(None, "niche", limit=100000)),
                           file_name="hotel-audit-competitors.csv", mime="text/csv", on_click="ignore")
        st.download_button("Pages the assistant used (.csv)", backend.to_csv(store.pages(None, limit=100000)), file_name="hotel-audit-pages.csv", mime="text/csv", on_click="ignore")
        st.download_button("Sites the assistant relies on (.csv)", backend.to_csv(store.sources(None, limit=100000)), file_name="hotel-audit-sources.csv", mime="text/csv", on_click="ignore")
        st.markdown("##### Monthly pack (Excel)")
        st.caption("One workbook with every audit in the period: scores and why, AI rankings and competitors, the top 3 actions per hotel, and the change since each hotel's "
                   "previous run. Built for reading, and for feeding to a dashboard.")
        months = sorted({str(r["run_at"])[:7] for r in rows})
        if months:
            a, b = st.columns(2)
            default = months[-2] if len(months) > 1 and months[-1] == time.strftime("%Y-%m") else months[-1]
            m_from = a.selectbox("From month", months, index=months.index(default), key="pk_from")
            m_to = b.selectbox("To month", months, index=months.index(default), key="pk_to")
            if m_from > m_to:
                st.warning("The 'to' month is before the 'from' month.")
            else:
                in_range = store.runs_in_months(m_from, m_to)
                st.caption(f"{len(in_range)} audit(s), {len({r['hotel_key'] for r in in_range})} hotel(s).")
                if in_range and st.button("Build the monthly pack"):
                    import monthly_pack
                    with st.spinner("Building the workbook..."):
                        st.session_state["pack"] = (monthly_pack.filename(m_from, m_to),
                                                    monthly_pack.build_workbook([(r, store.get_report(r["id"])) for r in in_range if store.get_report(r["id"])], store.list_runs(limit=100000)))
                if st.session_state.get("pack"):
                    st.download_button("Download " + st.session_state["pack"][0], st.session_state["pack"][1], file_name=st.session_state["pack"][0],
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore")
        else:
            st.caption("No audits saved yet.")
        st.markdown("##### Full reports")
        n = st.number_input("How many of the latest runs", min_value=1, max_value=500, value=min(50, max(1, len(rows))))
        if st.button("Build a zip of the full reports (.json)"):
            st.session_state["admin_zip"] = _reports_zip(store, rows[: int(n)])
        if st.session_state.get("admin_zip"):
            st.download_button("Download the zip", st.session_state["admin_zip"], file_name="hotel-audit-reports.zip", mime="application/zip", on_click="ignore")
