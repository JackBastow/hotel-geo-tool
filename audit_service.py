"""
Running one audit for the web site: the operator's keys (read from the environment), the free-tier guards, and the usage bookkeeping. This is the logic that sat inline in the
Streamlit app, in one place that does not depend on any web framework.

Keys come only from environment variables set on the host; nothing a visitor types is ever used as a key.
"""

import os

import ai_niche
import full_audit
import store

TAVILY_CREDITS_PER_AUDIT = 12
CLAUDE_MILLIDOLLARS_PER_AUDIT = 4000      # reserved per audit ($4: the repeated sample, the niche round with its core prompts asked three times, the reviews snapshot, the analysis, the gap work)

TIERS = {"luxury": "luxury", "upscale": "upscale", "midscale": "midscale", "budget": "budget"}


def _env(name):
    v = os.environ.get(name, "").strip()
    return v or None


class Config:
    """The operator's settings. Read once at start-up."""

    def __init__(self, env=None):
        e = env if env is not None else os.environ
        get = lambda n: (e.get(n, "") or "").strip() or None      # noqa: E731
        self.tavily = get("TAVILY_API_KEY")
        self.amadeus_key, self.amadeus_secret = get("AMADEUS_API_KEY"), get("AMADEUS_API_SECRET")
        self.gemini_reader = get("GEMINI_READER_API_KEY")
        self.youtube = get("YOUTUBE_API_KEY")
        self.pagespeed = get("PAGESPEED_API_KEY")
        self.firecrawl = get("FIRECRAWL_API_KEY")              # optional second page reader when a hotel's site refuses ours
        self.google_places = get("GOOGLE_PLACES_API_KEY")      # optional: the hotel's Google place and the hotels around it
        self.anthropic = get("ANTHROPIC_API_KEY")
        self.anthropic_model = get("ANTHROPIC_MODEL")
        try:
            self.repeats = int(get("ANTHROPIC_REPEATS")) if get("ANTHROPIC_REPEATS") else None
        except ValueError:
            self.repeats = None
        self.database_url = get("DATABASE_URL")
        self.admin_password = get("ADMIN_PASSWORD")
        self.site_password = get("SITE_PASSWORD")          # when set, every page except /healthz asks for it first
        self.secret_key = get("SECRET_KEY")
        import depth as _depth
        self.ai_depth = _depth.clean(get("AI_DEPTH") or "deep")                 # manual and demo audits: the thorough test
        self.weekly_ai_depth = _depth.clean(get("WEEKLY_AI_DEPTH") or "standard")      # the weekly checks: the lighter test, so a portfolio of hotels stays affordable and quick
        self.cron_token = get("CRON_TOKEN")                # lets the scheduled weekly-check job call /internal/weekly; without it those routes do not exist
        try:
            self.audits_per_hour = int(get("AUDITS_PER_HOUR_PER_VISITOR") or 4)
        except ValueError:
            self.audits_per_hour = 4
        try:
            self.max_queue = int(get("MAX_QUEUED_AUDITS") or 6)
        except ValueError:
            self.max_queue = 6


def _within_quota(service, planned=1):
    _, _, would_exceed = store.quota_status(planned_calls=planned, service=service)
    return not would_exceed


def _with_review_export(fa_res, rows, mapping):
    """The hotel's own review export, uploaded with the audit: analysed against what its site says, the figures put into the report, the private part (review text, drafts) handed back under
    '_review_private' for the job manager to hold in memory only. A failure leaves the audit as it was."""
    import review_pack
    try:
        res = review_pack.analyse(rows, (fa_res.get("meta") or {}).get("hotel", ""), review_pack.site_states_from(fa_res.get("guest_questions")))
        if res:
            review_pack.apply(fa_res, res["public"])
            fa_res["_review_private"] = {"res": res, "mapping": mapping}
    except Exception:  # noqa: BLE001 - an extra; the audit stands without it
        pass
    return fa_res


def run(params, cfg, progress=None):
    """
    params: {"website", "hotel", "city", "wider" (bool), "tier" (a key or None), "audiences" ([keys])}. -> the finished report (a dict). Raises on a failed audit.
    Keys are passed through only when configured AND the month's allowance has room, so a public site cannot silently exhaust a free tier.
    """
    use_tavily = cfg.tavily if (cfg.tavily and _within_quota("tavily", TAVILY_CREDITS_PER_AUDIT)) else None
    use_amadeus = cfg.amadeus_key if (cfg.amadeus_key and cfg.amadeus_secret and _within_quota("amadeus")) else None
    use_gemini_reader = cfg.gemini_reader if (cfg.gemini_reader and _within_quota("gemini_reader")) else None
    import depth as _depth
    depth_name = _depth.clean(params.get("depth") or cfg.ai_depth)
    use_firecrawl = cfg.firecrawl if (cfg.firecrawl and _within_quota("firecrawl", 12)) else None
    use_places = cfg.google_places if (cfg.google_places and _within_quota("google_places", 3)) else None
    use_anthropic = cfg.anthropic if (cfg.anthropic and _within_quota("claude", max(CLAUDE_MILLIDOLLARS_PER_AUDIT, _depth.limits(depth_name)["reserve_millidollars"]))) else None
    benchmark = []
    if cfg.database_url:
        try:
            import backend
            import urlscope
            db = backend.open_store(cfg.database_url)
            _key = backend.hotel_key({"meta": {"base": urlscope.normalise(params["website"])[0]}})
            benchmark = (db.confirmed_prompts_for_key(_key) or db.get_benchmark(_key)) if db else []      # the prompts the hotel confirmed come first; otherwise the ones frozen at its first audit
            import placenames
            if benchmark and not db.confirmed_prompts_for_key(_key) and any(placenames.has_scrap(b.get("text")) for b in benchmark):
                db.clear_benchmark(_key)          # frozen prompts built on a scrap of page text ('Airports Rhine Park') are thrown away: this audit writes a clean set
                benchmark = []
        except Exception:  # noqa: BLE001 - without a stored benchmark the audit simply sets a new one
            benchmark = []
    valid_aud = {k for k, *_r in ai_niche.AUDIENCES}
    fa_res = full_audit.run_full_audit(
        params["website"], params.get("hotel", ""), params.get("city", ""), progress=progress,
        tavily_api_key=use_tavily, amadeus_api_key=use_amadeus, amadeus_api_secret=cfg.amadeus_secret if use_amadeus else None,
        gemini_reader_key=use_gemini_reader, youtube_api_key=cfg.youtube, wider=bool(params.get("wider", True)), pagespeed_api_key=cfg.pagespeed,
        anthropic_api_key=use_anthropic, anthropic_model=cfg.anthropic_model, anthropic_repeats=cfg.repeats, custom_prompts=params.get("prompts") or None, benchmark=benchmark or None, ai_depth=depth_name, firecrawl_api_key=use_firecrawl, places_nearby_key=use_places,
        market_hint={"tier": TIERS.get(params.get("tier")), "audiences": [a for a in params.get("audiences") or [] if a in valid_aud]})
    if params.get("review_rows"):
        fa_res = _with_review_export(fa_res, params["review_rows"], params.get("review_mapping") or {})
    # usage against the shared monthly allowances
    tr = fa_res.get("tavily_result") or {}
    credits = ((fa_res.get("intel") or {}).get("methodology") or {}).get("tavily_credits_used")
    if tr.get("configured") or credits:
        store.record_usage(credits or len(tr.get("queries_run") or []) or 1, service="tavily")
    if (fa_res.get("amadeus_result") or {}).get("configured"):
        store.record_usage(2, service="amadeus")
    if cfg.anthropic and not use_anthropic:       # key configured but this month's allowance is used: say so, rather than silently showing nothing
        import ai_sample
        import review_replies
        fa_res["ai_sample"] = ai_sample.budget_exhausted()
        fa_res["review_snapshot"] = review_replies.budget_exhausted()
    spent = (((fa_res.get("ai_sample") or {}).get("cost_usd") or 0) + ((fa_res.get("review_snapshot") or {}).get("cost_usd") or 0)
             + ((fa_res.get("guest_questions") or {}).get("reader_cost_usd") or 0) + (((fa_res.get("guest_questions") or {}).get("ai_extract") or {}).get("cost_usd") or 0) + ((fa_res.get("ai_insights") or {}).get("cost_usd") or 0)
             + ((fa_res.get("ai_gap") or {}).get("cost_usd") or 0) + ((fa_res.get("forums") or {}).get("cost_usd") or 0) + ((fa_res.get("listing_lookup") or {}).get("cost_usd") or 0) + ((fa_res.get("reddit") or {}).get("cost_usd") or 0))
    if spent:
        store.record_usage(max(1, round(spent * 1000)), service="claude")      # estimated spend, in thousandths of a dollar
    fc = (fa_res.get("guest_questions") or {}).get("firecrawl") or {}
    fc_credits = int(fc.get("credits") or 0) + int((fa_res.get("firecrawl_other") or {}).get("credits") or 0)
    if fc_credits:
        store.record_usage(fc_credits, service="firecrawl")
    if (fa_res.get("places_nearby") or {}).get("calls"):
        store.record_usage(int(fa_res["places_nearby"]["calls"]), service="google_places")
    llm_reads = sum(1 for e in tr.get("editorial_hits", []) + tr.get("other_hits", []) if e.get("read", {}).get("via") == "llm")
    if llm_reads:
        store.record_usage(llm_reads, service="gemini_reader")
    return fa_res
