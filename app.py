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

import html as html_lib
import json

import streamlit as st
import streamlit.components.v1 as components

import full_audit
import store


def _esc(s):
    """
    Escape dynamic text before it goes into raw HTML. Needed because some of
    it - review excerpts, article judgments - originates from third-party web
    pages Tavily found, not just our own code. Once a block is rendered with
    unsafe_allow_html=True, Streamlit stops escaping for us, so a hostile or
    just-messy page's content could otherwise inject markup into the
    dashboard rather than just being displayed as text.
    """
    return html_lib.escape(str(s if s is not None else ""))


CARD_COLOR = {
    "good": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "mute": "#9ca3af",
}
SEVERITY_DOT = {
    "critical": CARD_COLOR["bad"], "high": "#f97316",
    "medium": CARD_COLOR["warn"], "low": CARD_COLOR["mute"],
}


def _score_color(score):
    if score is None:
        return CARD_COLOR["mute"]
    if score >= 70:
        return CARD_COLOR["good"]
    if score >= 40:
        return CARD_COLOR["warn"]
    return CARD_COLOR["bad"]


# state -> (chip text, colour). Five different states on purpose: "not found on
# the pages checked" and "couldn't check" are NOT the same as "missing".
GUEST_STATE_STYLE = {
    "answered": ("Answered", "#16a34a"),
    "partial": ("Partly answered", "#d97706"),
    "needs_checking": ("Needs checking", "#2563eb"),
    "not_found": ("Not found on pages checked", "#475569"),
    "couldnt_check": ("Couldn't check", "#9ca3af"),
}


def _safe_url(u):
    """Only http(s) links go into the page; anything else is dropped."""
    return u if str(u).lower().startswith(("http://", "https://")) else ""


def _guest_html(guest):
    """The guest-question section: each question, its state, what's missing,
    and the exact text relied on with a link to the page it came from."""
    if not guest or not guest.get("questions"):
        return ""
    n_ok, n_all = guest.get("pages_ok", 0), guest.get("pages_attempted", 0)
    total = guest.get("sitemap_total") or 0
    scope = f"We read {n_ok} of {n_all} pages"
    if total > n_all:
        scope += f" (the site lists about {total})"
    rows = ""
    for q in guest["questions"]:
        chip, color = GUEST_STATE_STYLE.get(q["state"], ("", "#9ca3af"))
        detail = ""
        if q["state"] == "partial" and q["missing"]:
            detail = f'<div class="gmiss">Missing: {_esc(", ".join(q["missing"]))}</div>'
        if q.get("note"):
            detail += f'<div class="gmiss">{_esc(q["note"])}</div>'
        quote = ""
        if q["snippet"]:
            url = _safe_url(q["source_url"])
            link = (f' <a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">'
                    f'view page ↗</a>') if url else ""
            quote = f'<div class="gquote">“{_esc(q["snippet"])}”{link}</div>'
        rows += f"""
        <div class="grow">
          <div class="gtop"><b>{_esc(q['label'])}</b>
            <span class="chip" style="background:{color}1f;color:{color}">{_esc(chip)}</span></div>
          {detail}{quote}
        </div>"""
    return f"""
      <h2>What your website tells guests</h2>
      <p class="gscope">{_esc(scope)}. “Not found” means not found on those pages —
      it does not prove the information is missing. “Couldn't check” is never
      counted against you.</p>
      {rows}"""


def render_dashboard(hotel_name, website, sc, recs, guest=None):
    """
    The real dashboard render, replacing the plain Streamlit default table -
    a score ring, colour-coded category cards, and a clean recommendations
    list, all built from the real scorecard data (nothing hardcoded - this
    is the same design validated as a mockup earlier, now actually wired to
    full_audit.py's real output instead of being a one-off demo).
    """
    overall = sc["overall"]
    coverage = sc["coverage_pct"]
    circumference = 213.6  # 2*pi*34, matching the SVG radius below
    offset = circumference * (1 - min(max(overall, 0), 100) / 100)

    cards_html = ""
    for c in sc["categories"]:
        assessed = c["assessed"]
        score = c["score"] if assessed else None
        color = _score_color(score) if assessed else CARD_COLOR["mute"]
        tag = ""
        if c.get("partial"):
            tag = f'<span class="tag" style="background:{color}22;color:{color}">partial</span>'
        elif not assessed:
            tag = '<span class="tag mute">not assessed</span>'
        cards_html += f"""
        <div class="card {'na' if not assessed else ''}">
          <div class="top">
            <span class="cat">{_esc(c['label'])}</span>
            <span class="wt">{c['weight']}%</span>
            {tag}
          </div>
          <div class="scoreline">
            <b style="color:{color}">{score if assessed else '—'}</b>
            {'<small>/100</small>' if assessed else ''}
          </div>
          <div class="bar"><i style="width:{score or 0}%;background:{color}"></i></div>
        </div>"""

    recs_html = ""
    for r in recs:
        dot = SEVERITY_DOT.get(r["priority"], CARD_COLOR["mute"])
        recs_html += f"""
        <div class="rec">
          <div class="dot" style="background:{dot}"></div>
          <div><b>{_esc(r['action'])}</b>
          <p><i>{_esc(r['category'])}</i> — {_esc(r['why'])}</p></div>
        </div>"""
    if not recs_html:
        recs_html = '<p style="color:var(--sub);font-size:12.5px">No recommendations from the categories that were assessed.</p>'

    # components.html (raw iframe render) rather than st.markdown: Streamlit's
    # markdown path runs this HTML through a Markdown parser first even with
    # unsafe_allow_html=True, and a blank line inside a multi-line HTML block
    # was enough to break it mid-render (confirmed live: later <div>s leaked
    # into the page as literal text instead of being parsed). components.html
    # drops the string into an iframe with no reinterpretation.
    guest_html = _guest_html(guest)
    n_cards = len(sc["categories"])
    card_rows = -(-n_cards // 4)  # ceil division, ~4 cards per row at this width
    height = 160 + card_rows * 95 + 40 + len(recs) * 70 + 40
    if guest_html:
        height += 150 + len(guest["questions"]) * 108

    html_doc = f"""
    <div class="dash">
      <style>
        html, body {{ margin:0; padding:0; background:#f7f8fa; }}
        @media (prefers-color-scheme: dark) {{ html, body {{ background:#15161c; }} }}
        .dash {{
          --bg: #f7f8fa; --card: #ffffff; --border: #e7e9ee;
          --ink: #1a1d29; --sub: #6b7280; --accent: #2563eb;
          font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
          background: var(--bg); color: var(--ink); padding: 20px;
          border-radius: 12px; margin: 0;
          box-sizing: border-box;
        }}
        @media (prefers-color-scheme: dark) {{
          .dash {{ --bg:#15161c; --card:#1d1f28; --border:#2a2d38; --ink:#eef0f4; --sub:#9aa0ad; }}
        }}
        .dash .head {{ display:flex; justify-content:space-between; align-items:flex-start;
                      margin-bottom:18px; flex-wrap:wrap; gap:14px; }}
        .dash h1 {{ font-size:19px; font-weight:700; margin:0 0 3px; }}
        .dash .meta {{ font-size:12.5px; color:var(--sub); }}
        .dash .scorewrap {{ display:flex; align-items:center; gap:14px; }}
        .dash .ring {{ position:relative; width:76px; height:76px; flex:none; }}
        .dash .ring svg {{ transform: rotate(-90deg); width:100%; height:100%; }}
        .dash .ring .bgring {{ stroke:var(--border); }}
        .dash .ring .fgring {{ stroke:var(--accent); stroke-linecap:round; }}
        .dash .ring .num {{ position:absolute; inset:0; display:flex; align-items:center;
                           justify-content:center; flex-direction:column; }}
        .dash .ring .num b {{ font-size:22px; line-height:1; }}
        .dash .ring .num span {{ font-size:9.5px; color:var(--sub); }}
        .dash .covnote {{ font-size:11.5px; color:var(--sub); max-width:170px; }}
        .dash .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(165px,1fr));
                      gap:10px; margin-bottom:18px; }}
        .dash .card {{ background:var(--card); border:1px solid var(--border);
                      border-radius:10px; padding:11px 12px; }}
        .dash .card .top {{ display:flex; justify-content:space-between; align-items:center;
                            margin-bottom:6px; gap:4px; }}
        .dash .card .cat {{ font-size:12px; font-weight:600; }}
        .dash .card .wt {{ font-size:10.5px; color:var(--sub); }}
        .dash .card .scoreline {{ display:flex; align-items:baseline; gap:5px; margin-bottom:6px; }}
        .dash .card .scoreline b {{ font-size:19px; }}
        .dash .card .scoreline small {{ font-size:10px; color:var(--sub); }}
        .dash .bar {{ height:5px; border-radius:3px; background:var(--border); overflow:hidden; }}
        .dash .bar i {{ display:block; height:100%; border-radius:3px; }}
        .dash .card.na {{ opacity:.6; }}
        .dash .tag {{ font-size:9.5px; padding:1px 6px; border-radius:20px; font-weight:600; }}
        .dash .tag.mute {{ background:var(--border); color:var(--sub); }}
        .dash h2 {{ font-size:13px; margin:18px 0 9px; color:var(--sub);
                   text-transform:uppercase; letter-spacing:.04em; }}
        .dash .rec {{ display:flex; gap:9px; padding:9px 0; border-top:1px solid var(--border); }}
        .dash .rec:first-child {{ border-top:none; }}
        .dash .dot {{ width:8px; height:8px; border-radius:50%; margin-top:5px; flex:none; }}
        .dash .rec b {{ font-size:12.5px; display:block; }}
        .dash .rec p {{ font-size:11.5px; color:var(--sub); margin:2px 0 0; }}
        .dash .gscope {{ font-size:11.5px; color:var(--sub); margin:0 0 10px; }}
        .dash .grow {{ padding:10px 0; border-top:1px solid var(--border); }}
        .dash .grow:first-of-type {{ border-top:none; }}
        .dash .gtop {{ display:flex; justify-content:space-between; align-items:center;
                      gap:10px; flex-wrap:wrap; }}
        .dash .gtop b {{ font-size:12.5px; }}
        .dash .chip {{ font-size:10.5px; font-weight:600; padding:2px 8px;
                      border-radius:20px; white-space:nowrap; }}
        .dash .gmiss {{ font-size:11.5px; color:#d97706; margin-top:3px; }}
        .dash .gquote {{ font-size:11.5px; color:var(--sub); margin-top:4px;
                        font-style:italic; line-height:1.45; }}
        .dash .gquote a {{ font-style:normal; color:var(--accent); text-decoration:none;
                          white-space:nowrap; }}
      </style>

      <div class="head">
        <div>
          <h1>{_esc(hotel_name or website)}</h1>
          <div class="meta">{_esc(website)}</div>
        </div>
        <div class="scorewrap">
          <div class="ring">
            <svg viewBox="0 0 80 80">
              <circle class="bgring" cx="40" cy="40" r="34" fill="none" stroke-width="7"/>
              <circle class="fgring" cx="40" cy="40" r="34" fill="none" stroke-width="7"
                stroke-dasharray="{circumference}" stroke-dashoffset="{offset}" />
            </svg>
            <div class="num"><b>{overall}</b><span>SCORE</span></div>
          </div>
          <div class="covnote">Weighted across <b style="color:var(--ink)">{coverage}%</b> of the model.</div>
        </div>
      </div>

      <div class="grid">{cards_html}</div>

      <h2>What to fix, worst first</h2>
      {recs_html}
      {guest_html}
    </div>
    """
    components.html(html_doc, height=height, scrolling=True)

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
    sc = fa_res["scorecard"]
    recs = fa_res["recommendations"]

    render_dashboard(meta["hotel"], meta["website"], sc, recs,
                     fa_res.get("guest_questions"))

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
            use_container_width=True, hide_index=True,
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
