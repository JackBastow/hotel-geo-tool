"""
Streamlit rendering of the discovery & reputation report (the `intel` block).

Native components only - st.dataframe cells are plain text, and any
third-party text shown through st.markdown goes through md_safe() - so nothing
read from the web can inject markup or load an image.
"""

import re

import streamlit as st

STATUS_LABEL = {"assessed": "Assessed", "partial": "Partial", "not_assessed": "Not assessed"}
STATUS_ICON = {"assessed": "🟢", "partial": "🟡", "not_assessed": "🔴"}
PRIORITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
SOURCE_ICON = {"ok": "🟢", "no_results": "🟡", "unavailable": "🔴", "not_configured": "⚪"}


def md_safe(s):
    """Escape Markdown so third-party text can't become a link or an image."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~])", r"\\\1", str(s or ""))


def safe_url(u):
    u = str(u or "")
    return u if u.startswith(("http://", "https://")) else ""


def df(rows, link_cols=(), widths=None, height=None):
    """Plain-text table; columns named in link_cols become clickable (http/https only)."""
    if not rows:
        return
    clean = []
    for r in rows:
        r = dict(r)
        for c in link_cols:
            if c in r:
                r[c] = safe_url(r[c]) or None
        clean.append(r)
    cfg = {c: st.column_config.LinkColumn(c, display_text="open") for c in link_cols}
    kw = {"height": height} if height else {}
    st.dataframe(clean, column_config=cfg, width="stretch", hide_index=True, **kw)


def ev(ids):
    return ("Evidence: " + ", ".join(ids)) if ids else ""


# ------------------------------------------------------------------- overview

def overview(intel):
    cc = intel["methodology"]["check_counts"]
    md = intel["media"]["summary"]
    fp = intel["identity"]["footprint"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Checks assessed", f"{cc.get('assessed', 0)} of 30")
    c2.metric("Partial / not assessed", f"{cc.get('partial', 0)} / {cc.get('not_assessed', 0)}")
    c3.metric("Independent publishers", md["independent_publishers"],
              help="Publishing groups counted once; sponsored, syndicated and press-release pieces excluded.")
    c4.metric("Listings discovered", sum(1 for r in fp if r["discovered"] and r["type"] != "map / open data"))
    c5.metric("Evidence records", len(intel["ledger"]))

    recs = {r["id"]: r for r in intel["recommendations"]}
    st.subheader("Five priority actions")
    st.caption("Chosen by priority, spread across areas. Priority reflects what travellers can see and the effort "
               "involved - not a promise that any action changes what an AI assistant recommends.")
    for i, rid in enumerate(intel["priority_actions"], 1):
        r = recs[rid]
        with st.container(border=True):
            st.markdown(f"**{i}. {md_safe(r['title'])}**  \n"
                        f"{PRIORITY_ICON[r['priority']]} {r['priority']} · team: **{r['team']}** · "
                        f"basis: *{r['basis']}*")
            st.write(r["action"])
            st.caption(f"Why: {r['why_it_matters']}  \nSuccess check: {r['success_check']}  \n{ev(r['evidence_ids'])}")
    with st.expander(f"All {len(intel['recommendations'])} recommendations"):
        recommendations_table(intel)


def recommendations_table(intel):
    order = {s["id"]: i for i, s in enumerate(intel["sections"])}
    titles = {s["id"]: s["title"] for s in intel["sections"]}
    recs = sorted(intel["recommendations"], key=lambda r: (order.get(r["section"], 99),))
    for r in recs:
        with st.expander(f"{PRIORITY_ICON[r['priority']]} {r['title']} — {r['team']}"):
            st.markdown(f"**Area:** {titles.get(r['section'], r['section'])} · **Priority:** {r['priority']} · "
                        f"**Basis:** {r['basis']}")
            st.markdown(f"**Problem / opportunity:** {md_safe(r['problem'])}")
            st.markdown(f"**Why it matters:** {md_safe(r['why_it_matters'])}")
            st.markdown(f"**Action:** {md_safe(r['action'])}")
            st.markdown(f"**Priority rationale:** {md_safe(r['priority_why'])}")
            st.markdown(f"**How to check success:** {md_safe(r['success_check'])}")
            if r["basis_note"]:
                st.caption(r["basis_note"])
            if r["evidence_ids"]:
                st.caption(ev(r["evidence_ids"]))
            if r.get("example"):
                st.code(r["example"], language="html")


# ------------------------------------------------------------------- identity

def identity(intel):
    idn = intel["identity"]
    st.caption("Do the sources agree on who and where this hotel is, where is it listed, and does what is listed "
               "match the website? *Discovered* = a page exists; *content assessed* = we were allowed to read it.")
    st.markdown("##### Cross-source identity")
    df([{"Source": s["source"], "Name seen": s.get("name") or "", "Place / address": (s.get("place") or "")[:100],
         "Location": {True: "verified", False: "possible different hotel", None: ""}.get(s.get("confident"), "")}
        for s in idn["sources_compared"]])
    if idn["name_variants"]:
        st.markdown("**Name forms in use**")
        df([{"Form": v["variant"], "Mentions": v["count"], "Seen in": ", ".join(v["sources"])} for v in idn["name_variants"]])
    if idn["namesakes"]:
        st.markdown("**Possible namesakes — not this hotel**")
        df([{"Name": n["name"], "Where": n["where"], "Why flagged": n["why"], "Page": n["url"]} for n in idn["namesakes"]],
           link_cols=("Page",))
    if idn["former_names"]:
        st.markdown("**Possible former names** *(inference)*")
        df([{"Name": f["name"], "Basis": f["basis"], "Source": f["source"], "Page": f["url"]} for f in idn["former_names"]],
           link_cols=("Page",))
    else:
        st.caption("No former name or rebrand found in the sources read — that is not proof there was none.")

    st.markdown("##### Public listing footprint")
    df([{"Platform": r["platform"], "Type": r["type"],
         "Discovered": "yes" if r["discovered"] else "not found by our searches",
         "Content assessed": "yes" if r["content_assessed"] else ("no" if r["discovered"] else ""),
         "Location confirmed": {True: "yes", False: "no", None: ""}[r["location_confirmed"]] if r["discovered"] else "",
         "Note": (r.get("note") or "")[:110], "Page": r["url"]} for r in idn["footprint"]], link_cols=("Page",))
    st.caption("“Not found by our searches” never means “not listed” — a search index isn't a platform directory. "
               "TripAdvisor, Booking.com, Expedia and similar sites prohibit automated reading, so their content is never assessed here.")

    st.markdown("##### Listing consistency")
    cons = idn["consistency"]
    if cons["rows"]:
        for r in cons["rows"]:
            st.warning(f"**{r['field']}** — website: {md_safe(r['own'])} · {md_safe(r['source'])}: {md_safe(r['other'])}  \n"
                       f"[{r['source']}]({safe_url(r['url'])}) · {r['evidence_id']}")
    elif cons["pages_compared"]:
        st.success(f"{cons['pages_compared']} listing page(s) could be read; no contradictory telephone, postcode or star rating found.")
    else:
        st.info("No listing page could lawfully be read, so descriptions and facilities were not compared.")

    st.markdown("##### Destination organisation")
    d = idn["destination"]
    if d["body"]:
        st.write(f"**{d['body']['name']}** ({d['body'].get('scope', '')}) — {safe_url(d['body']['url'])}")
        if d["listing_found"]:
            for p in d["pages_naming_hotel"][:3]:
                st.markdown(f"- A page naming the hotel: [{md_safe(p['title'][:80] or p['url'])}]({safe_url(p['url'])})")
        else:
            st.write("No page naming the hotel was found on the pages read.")
        st.caption(d["route"])
    else:
        st.write("No official destination site was identified by the searches.")

    st.markdown("##### Booking and distribution")
    dist = idn["distribution"]
    st.write("**Booking links on the hotel's own pages:** " +
             (", ".join(f"{b['engine']} ({b['domain']})" for b in dist["booking_links_on_site"]) or "none recognised"))
    st.write("**Platforms discovered:** " + (", ".join(dist["platforms_discovered"]) or "none"))
    st.caption(dist["statement"])


# -------------------------------------------------------------------- reviews

def reviews(intel):
    rv = intel["reviews"]
    st.info(rv["why_no_reviews"])
    st.markdown("##### Available review sample")
    st.write(rv["sample"]["statement"])
    if rv["ratings"]:
        st.markdown("**Aggregate ratings third parties display** *(numbers shown by others — not reviews we could read)*")
        df([{"Source": r["source"], "Rating": f"{r['value']} / {r['scale']}",
             "Based on": f"{r['count']} ratings" if r["count"] else "count not shown", "Seen in": r["where"],
             "Hotel match": "town named beside hotel" if r["verified_location"] else "UNVERIFIED — may be another hotel",
             "Page": r["url"]} for r in rv["ratings"]], link_cols=("Page",))
    if rv["editorial_reviews"]:
        st.markdown("**Editorial review articles** *(a writer's account of a stay — not guest reviews)*")
        df([{"Date": r["date"] or "undated", "Publisher": r["publisher"], "Title": (r["title"] or "")[:90],
             "Freshness": r["freshness"], "Page": r["url"]} for r in rv["editorial_reviews"]], link_cols=("Page",))
    fsa = [e for e in intel["ledger"] if e["source_type"] == "government_register"]
    if fsa:
        st.markdown("**Official register: food hygiene (UK FSA)**")
        df([{"Evidence": e["id"], "Record": e["extract"], "Page": e["url"]} for e in fsa], link_cols=("Page",))
    st.markdown("##### Not assessed, and why")
    df([{"#": c["n"], "Check": c["name"], "Status": f"{STATUS_ICON[c['status']]} {STATUS_LABEL[c['status']]}",
         "What we can say": c["summary"], "Why / limits": c["reason"]}
        for c in intel["checks"] if 7 <= c["n"] <= 14])
    pos = rv["positioning"]
    st.markdown("##### Reputation versus positioning *(independent sources only)*")
    if pos["supported"]:
        df([{"Theme the hotel claims": s["theme"], "Independent publishers": s["independent_publishers"],
             "Example": (s["extract"].get("text", "")[:180] if s["extract"] else "")} for s in pos["supported"]])
    if pos["claimed_only_by_hotel"]:
        st.write("**Claimed only on the hotel's own pages:** " + ", ".join(pos["claimed_only_by_hotel"]))
    if pos["described_by_others_not_by_hotel"]:
        st.write("**Described by others but not by the hotel:** " + ", ".join(pos["described_by_others_not_by_hotel"]))
    st.caption(pos["limit"])


# ---------------------------------------------------------------------- media

def media(intel):
    md = intel["media"]
    cov = md["summary"]
    st.caption("Only pages that name the hotel in full count as coverage of it. Look-alikes are rejected and listed. "
               "Search results vary between runs, so absence of a piece is not proof it doesn't exist.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pages naming the hotel", cov["articles"])
    c2.metric("Distinct stories", cov["stories"], help=f"{cov['duplicates_removed']} duplicate copies collapsed")
    c3.metric("Independent publishers", cov["independent_publishers"])
    c4.metric("Recent (12 months)", cov["recent_independent"])
    g = md["gdelt"]
    if g["status"] != "ok":
        st.caption(f"GDELT news monitor: **{g['status'].replace('_', ' ')}** — {g['reason']}")

    st.markdown("##### Named coverage")
    if md["articles"]:
        df([{"Date": a["date"] or "undated", "Publisher": a["publisher"],
             "Type (inferred)": a["type"] + (f" ({a['cue_text']})" if a.get("cue_text") else ""),
             "Freshness": a["freshness"], "How much": a["substance"], "Language": a["lang"] or "?",
             "Title": (a["title"] or "")[:80], "Evidence": a["id"], "Page": a["url"]} for a in md["articles"]],
           link_cols=("Page",))
        for a in md["articles"]:
            if a.get("date_note"):
                st.caption(f"Note on {a['publisher']}: {a['date_note']}.")
        syn = [c for c in md["clusters"] if c["size"] > 1]
        for c in syn:
            st.caption(f"{c['size']} copies of one story collapsed ("
                       f"{'shared across different publishers — treated as syndicated, not independent' if c.get('syndicated') else 'one publishing group'}).")
    else:
        st.info("No page naming the hotel could be read.")
    if md["rejected"]:
        with st.expander(f"{len(md['rejected'])} page(s) rejected as not about this hotel"):
            df([{"Page": r["url"], "Title": (r["title"] or "")[:80], "Match": r["level"], "Why": r["why"]}
                for r in md["rejected"]], link_cols=("Page",))
    if md["unread"]:
        with st.expander(f"{len(md['unread'])} page(s) could not be read, so are not counted"):
            df([{"Site": u["domain"], "Title": (u["title"] or "")[:80], "Why not read": u["why_unread"], "Page": u["url"]}
                for u in md["unread"]], link_cols=("Page",))

    st.markdown("##### Awards and accreditation")
    if md["awards"]:
        df([{"Issuer": a["issuer"], "Year(s)": ", ".join(a["years"]) or "—", "Status": a["status"],
             "Hotel says": (a["claims"][0]["text"][:120] if a["claims"] else ""),
             "Independent source says": (a["independent"][0]["text"][:120] if a["independent"] else "")}
            for a in md["awards"]])
        st.caption("*Confirmed* requires a page on the issuer's own site naming the hotel. Until then a claim on "
                   "the hotel's own site remains the hotel's claim.")
    else:
        st.write("No award or accreditation wording found on the hotel's pages or in the coverage read.")

    st.markdown("##### Media narrative")
    th = md["themes"]
    if th["themes"]:
        rows = []
        for t in th["themes"][:12]:
            ex = t["independent_extracts"][0] if t["independent_extracts"] else None
            rows.append({"Theme": t["theme"], "Hotel's own pages": t["own_pages"],
                         "Independent publishers": t["independent_publishers"],
                         "What an independent source says": (ex["text"][:200] + f" — {ex['publisher']}") if ex else "",
                         "Page": ex["url"] if ex else ""})
        df(rows, link_cols=("Page",))
        for d in th["disagreements"]:
            st.warning("Sources disagree: " + " vs ".join(d["themes"]))
        st.caption("Themes are read only from text around the hotel's name, so a roundup's words about other hotels "
                   "are not attributed to this one. Matching is by wording, not meaning.")

    st.markdown("##### Comparison hotels in guides")
    if md["comparison"]:
        df([{"Comparable nearby hotel": c["hotel"], "Guides featuring it": "; ".join(p["publisher"] for p in c["featured_in"]),
             "Why valid": "named in a guide for the same area"} for c in md["comparison"]])
    st.caption("Fewer than three validated comparison hotels is too few to compare against. Hotels are compared only "
               "when mapped nearby or named in a guide about the same area — never because they are famous.")

    st.markdown("##### Media and organisation targets")
    if md["targets"]:
        df([{"Outlet / body": t["name"], "Kind": t["kind"], "Supporting page": (t["page_title"] or "")[:70],
             "Date": t["date"] or "", "Audience fit": t["audience_fit"], "Why relevant": t["why_relevant"],
             "Confidence": t["confidence"], "Page": t["url"]} for t in md["targets"]], link_cols=("Page",))
        st.caption("Each row is named because a real, relevant page supports it. Whether an outlet would cover the "
                   "hotel is not something this tool can know. No journalist names or contact details are produced.")
    else:
        st.info("Discovery coverage was insufficient to name outlets from evidence. These are **research directions, "
                "not a researched shortlist**:")
        df([{"Direction": d["category"], "Why": d["why"], "How to look": d["how"]} for d in md["research_directions"]])

    st.markdown("##### Pitch angles grounded in the hotel's own pages")
    if md["angles"]:
        df([{"Angle": a["angle"], "Fact found": a["fact"][:240], "Evidence still missing": "; ".join(a["missing_evidence"]),
             "Source": a["source_url"]} for a in md["angles"]], link_cols=("Source",))
        st.caption("Candidates only. Newsworthiness is not assumed; each needs the missing evidence, and independent "
                   "confirmation, before it is pitched.")
    else:
        st.write("No documented, pitch-worthy fact was found on the pages read, so no angle is suggested.")


# ------------------------------------------------------------------- traveller

def traveller(intel):
    tr = intel["traveller"]
    st.caption("What evidence exists for each kind of traveller across the hotel's own pages, independent coverage and "
               "open data. This assesses evidence; it does not measure any AI ranking.")
    st.markdown("##### Traveller-need coverage")
    df([{"Traveller": n["segment"], "Evidence": n["status"], "Own pages": n["own_pages"],
         "Independent publishers": n["independent_publishers"],
         "Gaps / notes": "; ".join(n["gaps"] + n["open_data"])[:220]} for n in tr["needs"]])
    st.markdown("##### Recommendation opportunities")
    st.caption("Realistic traveller questions the hotel has some evidence to fit — opportunities, not measured rankings.")
    df([{"Traveller question": o["question"], "Supporting facts": "; ".join(o["supporting_facts"])[:240],
         "Missing evidence": "; ".join(o["missing_evidence"])[:220] or "none identified"} for o in tr["opportunities"]])
    pos = tr["positioning"]
    st.markdown("##### Distinctive positioning")
    if pos["candidates"]:
        df([{"Feature": c["feature"], "Independent publishers": c["independent_publishers"],
             "Assessment": c["assessment"] + (f" ({c['comparison_share']})" if c["comparison_share"] else "")}
            for c in pos["candidates"]])
    if pos["local_anchors"]:
        st.write("**Local anchors independent writers connect with the hotel:** " + "; ".join(
            f"{a['place']} ({a['km']} km straight line — named by {', '.join(a['named_by'][:2])})" for a in pos["local_anchors"]))
    if pos["generic_note"]:
        st.warning(pos["generic_note"])
    if not pos["comparison_available"]:
        st.caption("Fewer than three comparable hotels could be validated, so 'distinctive' rests on what independent "
                   "sources emphasise, not on a comparison with other hotels.")
    t = tr["terminology"]
    st.markdown("##### Language and terminology")
    if t["labels"]:
        df([{"Label in use": l["term"], "Sources using it": ", ".join(l["used_by"])} for l in t["labels"]])
    for c in t["conflicts"]:
        st.warning(c)
    if t["words_others_use"]:
        st.write("**Words independent writers use that the hotel's pages never do** — consider only where true and "
                 "useful to a guest: " + ", ".join(f"“{w['word']}” ({w['publisher']})" for w in t["words_others_use"][:8]))
    st.caption(t["guest_wording"] + ". " + t["caution"])


# --------------------------------------------------------------- social + local

def social_local(intel):
    so, lo = intel["social"], intel["local"]
    st.markdown("##### Public social and video evidence")
    if so["profiles"]:
        df([{"Platform": p["platform"], "Evidence": p["evidence"], "Note": p["note"], "Profile": p["url"]}
            for p in so["profiles"]], link_cols=("Profile",))
    else:
        st.write("No official social profile was found linked from the website.")
    if so["videos"]:
        df([{"Date": v.get("published") or "", "Channel": v["channel"], "Video": v["title"][:90], "Page": v["url"]}
            for v in so["videos"]], link_cols=("Page",))
    elif so.get("youtube_reason"):
        st.caption("Video: " + so["youtube_reason"])
    st.caption(so["note"])
    st.markdown("##### Location and local partnerships")
    if lo["available"]:
        for title, key in (("Transport", "stations"), ("Attractions", "attractions"),
                           ("Event / meeting venues", "venues"), ("Airports", "airports")):
            if lo[key]:
                st.write(f"**{title}:** " + "; ".join(f"{x['name']} — {x['km']} km" for x in lo[key]))
        if lo["failed_parts"]:
            st.warning("Not retrieved from the public map servers this run: " + ", ".join(lo["failed_parts"]) +
                       ". Absence here does not mean nothing is nearby.")
    else:
        st.info(lo["reason"] or "Local context was not assessed.")
    st.caption(lo["label"])
    if lo["partnerships"]:
        df([{"Partner": p["partner"], "Relationship": p["relationship"], "Status": p["status"], "Source": p["source_url"]}
            for p in lo["partnerships"]], link_cols=("Source",))
    else:
        st.caption("No partnership or destination-link statement was found in the pages read.")


# ---------------------------------------------------------------------- website

def website(intel):
    ws = intel["website"]
    st.caption("Does the website explain the strengths, policies and facts found elsewhere, and can public crawlers read it?")
    st.markdown("##### Claims made elsewhere that the website doesn't back up")
    if ws["external_facts_missing_on_site"]:
        df([{"Others say": r["item"], "Hint": r["action_hint"]} for r in ws["external_facts_missing_on_site"]])
    else:
        st.success("Nothing found in independent coverage that the website fails to say.")
    ca = ws["crawler_access"]
    c1, c2, c3 = st.columns(3)
    c1.metric("robots.txt", "present" if ca["robots_txt_present"] else "missing")
    c2.metric("Sitemap", "yes" if ca["sitemap"] else "not found")
    c3.metric("Hotel structured data", "yes" if ca["structured_data_found"] else "not found")
    if ca["ai_crawlers_blocked"]:
        st.warning("AI crawlers blocked in robots.txt: " + ", ".join(ca["ai_crawlers_blocked"]))
    if not ws["has_press_or_awards_page"]:
        st.caption("No press, news or awards page was found among the pages read.")


# --------------------------------------------------------------------- methodology

def gaps(intel):
    m = intel["methodology"]
    st.markdown("##### All 30 checks")
    df([{"#": c["n"], "Check": c["name"] + (" (inferred)" if c["inference"] else ""),
         "Status": f"{STATUS_ICON[c['status']]} {STATUS_LABEL[c['status']]}", "Result": c["summary"],
         "Why / limits": c["reason"]} for c in intel["checks"]], height=560)
    st.markdown("##### Sources used in this run")
    df([{"Source": s["source"], "Status": f"{SOURCE_ICON.get(s['status'], '')} {s['status'].replace('_', ' ')}",
         "Items": s["items"], "Note": s["reason"]} for s in m["sources_this_run"]])
    if m["queries"]:
        st.caption(f"Searches run: {len(m['queries'])} ({m['tavily_credits_used']} Tavily free-plan credits).")
        with st.expander("The searches"):
            df([{"Purpose": q["role"], "Query": q["query"], "Results": q["n_results"], "Error": q["error"] or ""}
                for q in m["queries"]])
    r = m["reads"]
    if r:
        st.caption(f"Pages read: {r.get('ok', 0)} read · {r.get('robots_blocked', 0)} declined by robots.txt · "
                   f"{r.get('failed', 0)} failed" + (" · time budget reached" if r.get("budget_hit") else ""))
    for n in m["notes"]:
        st.warning(n)
    st.markdown("##### Principles")
    for p in m["principles"]:
        st.markdown("- " + md_safe(p))
    with st.expander("What each source returns, its limits and cost"):
        df([{"Source": s["name"], "Cost": s["cost"], "Needs": s["needs"], "Returns": s["returns"], "Limits": s["limits"]}
            for s in m["source_catalogue"]])
    with st.expander("Sources deliberately not used"):
        df([{"Source": x["name"], "Why not": x["why"]} for x in m["excluded_sources"]])
    with st.expander(f"Evidence appendix ({len(intel['ledger'])} records)"):
        df([{"ID": e["id"], "Source": e["source"], "Type": e["source_type"].replace("_", " "),
             "Published": e["published"] or "", "Collected": (e["collected_at"] or "")[:10],
             "Match": e["match"], "Kind": e["kind"], "Extract": e["extract"][:240], "URL": e["url"]}
            for e in intel["ledger"]], link_cols=("URL",), height=480)
