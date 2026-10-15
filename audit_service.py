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
CLAUDE_MILLIDOLLARS_PER_AUDIT = 1500      # reserved per audit ($1.50: the repeated sample, the niche round, the reviews snapshot, the analysis; about $0.60 in practice)

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


def run(params, cfg, progress=None):
    """
    params: {"website", "hotel", "city", "wider" (bool), "tier" (a key or None), "audiences" ([keys])}. -> the finished report (a dict). Raises on a failed audit.
    Keys are passed through only when configured AND the month's allowance has room, so a public site cannot silently exhaust a free tier.
    """
    use_tavily = cfg.tavily if (cfg.tavily and _within_quota("tavily", TAVILY_CREDITS_PER_AUDIT)) else None
    use_amadeus = cfg.amadeus_key if (cfg.amadeus_key and cfg.amadeus_secret and _within_quota("amadeus")) else None
    use_gemini_reader = cfg.gemini_reader if (cfg.gemini_reader and _within_quota("gemini_reader")) else None
    use_anthropic = cfg.anthropic if (cfg.anthropic and _within_quota("claude", CLAUDE_MILLIDOLLARS_PER_AUDIT)) else None
    valid_aud = {k for k, *_r in ai_niche.AUDIENCES}
    fa_res = full_audit.run_full_audit(
        params["website"], params.get("hotel", ""), params.get("city", ""), progress=progress,
        tavily_api_key=use_tavily, amadeus_api_key=use_amadeus, amadeus_api_secret=cfg.amadeus_secret if use_amadeus else None,
        gemini_reader_key=use_gemini_reader, youtube_api_key=cfg.youtube, wider=bool(params.get("wider", True)), pagespeed_api_key=cfg.pagespeed,
        anthropic_api_key=use_anthropic, anthropic_model=cfg.anthropic_model, anthropic_repeats=cfg.repeats,
        market_hint={"tier": TIERS.get(params.get("tier")), "audiences": [a for a in params.get("audiences") or [] if a in valid_aud]})
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
             + ((fa_res.get("guest_questions") or {}).get("reader_cost_usd") or 0) + ((fa_res.get("ai_insights") or {}).get("cost_usd") or 0)
             + ((fa_res.get("listing_lookup") or {}).get("cost_usd") or 0))
    if spent:
        store.record_usage(max(1, round(spent * 1000)), service="claude")      # estimated spend, in thousandths of a dollar
    llm_reads = sum(1 for e in tr.get("editorial_hits", []) + tr.get("other_hits", []) if e.get("read", {}).get("via") == "llm")
    if llm_reads:
        store.record_usage(llm_reads, service="gemini_reader")
    return fa_res
