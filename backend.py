"""
The back end: every completed audit, kept so the people running the service can see how hotels are doing and pull the data.

Storage is a SQL database reached through one connection string (the DATABASE_URL secret):
  postgresql://...   - a hosted Postgres (Neon's free plan needs no card), the normal way to run this
  sqlite:///path.db  - a local file, for development and the tests (NOT durable on Streamlit Community Cloud, whose disk is wiped)

Nothing here is reachable by visitors: the only readers are the admin page (ui_admin.py, behind a password) and anything
else with the connection string. A failure to save never fails an audit; the app simply says it could not save.

Tables
  runs           one row per audit: who/what/when, the headline, every category score, the AI-visibility and reviews
                 numbers, cost, and the full report as JSON (so any run can be re-opened, compared or turned back into a PDF)
  ai_competitors one row per hotel the assistant named, per run and per kind (generic / niche): the market-level data
  ai_sources     one row per site the assistant used, per run: which sites AI leans on in a market

The summary columns exist so questions can be answered with a plain query (or a spreadsheet) without opening the JSON.
"""

import datetime as dt
import decimal
import json
import re
import sqlite3
import urllib.parse

SCHEMA_VERSION = 1

RUN_COLS = [
    "run_at", "hotel", "hotel_key", "city", "website", "domain", "hotel_name_source", "headline_status", "headline_score", "coverage_pct",
    "read_via", "pages_read", "pages_attempted", "cat_scores", "ai_status", "ai_model", "ai_generic_named", "ai_generic_asked", "ai_niche_named",
    "ai_niche_asked", "ai_direct_known", "ai_share", "ai_rank_in_table", "ai_table_size", "ai_top_competitor", "reviews_status", "reviews_examined",
    "reviews_replied", "reviews_neg_examined", "reviews_neg_replied", "pagespeed_perf", "pagespeed_a11y", "commoncrawl_state", "recs_total",
    "top_actions", "ai_cost_usd", "schema_version",
]


# --------------------------------------------------------------------- summary

def hotel_key(rep):
    """A stable identity for 'the same hotel' across runs: the website's host plus, for a chain's page, the hotel's own folder."""
    base = ((rep.get("meta") or {}).get("base") or (rep.get("meta") or {}).get("website") or "")
    p = urllib.parse.urlparse(base if "//" in base else "https://" + base)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = p.path.rstrip("/")
    return (host + (path if path and path != "/" else "")).lower()[:200]


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def summarise(rep):
    """The row for `runs`, read defensively from a report of any age."""
    meta = rep.get("meta") or {}
    head = rep.get("headline") or {}
    sc = rep.get("scorecard") or {}
    cons = rep.get("consultant") or {}
    cov = cons.get("coverage") or {}
    ai = rep.get("ai_sample") or {}
    s = ai.get("summary") or {}
    ins = rep.get("ai_insights") or {}
    sb = ins.get("scoreboard") or {}
    rv = rep.get("review_snapshot") or {}
    rs = rv.get("summary") or {}
    web = rep.get("web_signals") or {}
    ps = (web.get("pagespeed") or {}).get("scores") or {}
    recs = cons.get("recommendations") or []
    by_id = {r.get("id"): r.get("title", "") for r in recs}
    cats = {c["key"]: c.get("score") for c in sc.get("categories", []) if c.get("assessed") and c.get("score") is not None}
    ai_cost = sum(_num(x.get("cost_usd")) or 0 for x in (ai, ins, rv)) + _num((rep.get("guest_questions") or {}).get("reader_cost_usd") or 0)
    return {
        "run_at": str(meta.get("run_at") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
        "hotel": meta.get("hotel") or "", "hotel_key": hotel_key(rep), "city": meta.get("city") or "", "website": meta.get("website") or "",
        "domain": hotel_key(rep).split("/")[0], "hotel_name_source": meta.get("hotel_name_source") or "",
        "headline_status": head.get("status") or "", "headline_score": _num(head.get("score")), "coverage_pct": _num(head.get("coverage_pct")),
        "read_via": (rep.get("guest_questions") or {}).get("read_via") or "", "pages_read": cov.get("pages_read"), "pages_attempted": cov.get("pages_attempted"),
        "cat_scores": json.dumps(cats, sort_keys=True),
        "ai_status": ai.get("status") or "", "ai_model": ai.get("model") or "", "ai_generic_named": s.get("generic_named"), "ai_generic_asked": s.get("generic_asked"),
        "ai_niche_named": s.get("niche_named"), "ai_niche_asked": s.get("niche_asked"),
        "ai_direct_known": None if s.get("direct_known") is None else int(bool(s.get("direct_known"))),
        "ai_share": sb.get("share"), "ai_rank_in_table": sb.get("rank_in_table"), "ai_table_size": sb.get("table_size"), "ai_top_competitor": sb.get("top_competitor") or "",
        "reviews_status": rv.get("status") or "", "reviews_examined": rs.get("examined"), "reviews_replied": rs.get("replied"),
        "reviews_neg_examined": rs.get("negative_examined"), "reviews_neg_replied": rs.get("negative_replied"),
        "pagespeed_perf": ps.get("performance"), "pagespeed_a11y": ps.get("accessibility"), "commoncrawl_state": (web.get("commoncrawl") or {}).get("state") or "",
        "recs_total": len(recs), "top_actions": " | ".join(by_id.get(i, i) for i in (cons.get("top_actions") or []))[:1500],
        "ai_cost_usd": round(ai_cost, 5), "schema_version": SCHEMA_VERSION,
    }


def children(rep):
    """(competitor rows, source rows) for the market-level tables."""
    ins = rep.get("ai_insights") or {}
    comps = []
    for kind, lb in (("generic", ins.get("leaderboard")), (("niche"), (ins.get("niche") or {}).get("leaderboard"))):
        for r in (lb or {}).get("rows", []):
            comps.append({"kind": kind, "competitor": r["name"][:120], "is_target": int(bool(r.get("is_target"))), "mentions": r["mentions"], "asked": r["of"],
                          "avg_rank": r.get("avg_rank")})
    srcs = [{"domain": x["domain"][:120], "source_kind": x["kind"], "answers": x["answers"],
             "hotel_evidenced": None if x["hotel_evidenced"] is None else int(bool(x["hotel_evidenced"]))} for x in ins.get("sources", [])]
    return comps, srcs


# ------------------------------------------------------------------- the store

class Store:
    def __init__(self, url):
        self.url = url or ""
        self.kind = "sqlite" if self.url.startswith("sqlite") else "postgres"

    # connection ---------------------------------------------------------------
    def _connect(self):
        if self.kind == "sqlite":
            path = self.url.split("sqlite:///", 1)[-1] or ":memory:"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10)

    def _sql(self, sql):
        return sql if self.kind == "sqlite" else sql.replace("?", "%s")

    def _run(self, conn, sql, params=()):
        cur = conn.cursor()
        cur.execute(self._sql(sql), params)
        return cur

    def _rows(self, sql, params=()):
        conn = self._connect()
        try:
            cur = self._run(conn, sql, params)
            return [{k: (float(v) if isinstance(v, decimal.Decimal) else v) for k, v in dict(r).items()} for r in cur.fetchall()]
        finally:
            conn.close()

    def _insert(self, conn, table, row):
        cols = list(row)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        if self.kind == "sqlite":
            cur = self._run(conn, sql, [row[c] for c in cols])
            return cur.lastrowid
        cur = self._run(conn, sql + " RETURNING id", [row[c] for c in cols])
        return cur.fetchone()["id"]

    # schema ------------------------------------------------------------------
    def init(self):
        pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if self.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
        text_cols = {"run_at", "hotel", "hotel_key", "city", "website", "domain", "hotel_name_source", "headline_status", "read_via", "cat_scores", "ai_status", "ai_model",
                     "ai_top_competitor", "reviews_status", "commoncrawl_state", "top_actions"}
        real_cols = {"headline_score", "coverage_pct", "ai_cost_usd"}
        ddl = ", ".join(f"{c} " + ("TEXT" if c in text_cols else "DOUBLE PRECISION" if (c in real_cols and self.kind != "sqlite") else "REAL" if c in real_cols else "INTEGER")
                        for c in RUN_COLS)
        conn = self._connect()
        try:
            self._run(conn, f"CREATE TABLE IF NOT EXISTS runs (id {pk}, {ddl}, report_json TEXT)")
            self._run(conn, f"CREATE TABLE IF NOT EXISTS ai_competitors (id {pk}, run_id INTEGER, kind TEXT, competitor TEXT, is_target INTEGER, mentions INTEGER, asked INTEGER, avg_rank REAL)")
            self._run(conn, f"CREATE TABLE IF NOT EXISTS ai_sources (id {pk}, run_id INTEGER, domain TEXT, source_kind TEXT, answers INTEGER, hotel_evidenced INTEGER)")
            for sql in ("CREATE INDEX IF NOT EXISTS runs_key ON runs (hotel_key, run_at)", "CREATE INDEX IF NOT EXISTS runs_city ON runs (city)",
                        "CREATE INDEX IF NOT EXISTS comp_run ON ai_competitors (run_id)", "CREATE INDEX IF NOT EXISTS src_run ON ai_sources (run_id)"):
                self._run(conn, sql)
            conn.commit()
        finally:
            conn.close()

    # writes ------------------------------------------------------------------
    def save_run(self, rep):
        """Store one finished audit and its market-level rows. -> the new run id."""
        row = summarise(rep)
        row["report_json"] = json.dumps(rep, default=str)
        comps, srcs = children(rep)
        conn = self._connect()
        try:
            rid = self._insert(conn, "runs", row)
            for c in comps:
                self._insert(conn, "ai_competitors", {"run_id": rid, **c})
            for s in srcs:
                self._insert(conn, "ai_sources", {"run_id": rid, **s})
            conn.commit()
            return rid
        finally:
            conn.close()

    def delete_run(self, run_id):
        conn = self._connect()
        try:
            for t, col in (("ai_competitors", "run_id"), ("ai_sources", "run_id"), ("runs", "id")):
                self._run(conn, f"DELETE FROM {t} WHERE {col} = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()

    # reads -------------------------------------------------------------------
    def list_runs(self, limit=1000, text=None, city=None, since=None):
        where, args = [], []
        if text:
            where.append("(LOWER(hotel) LIKE ? OR LOWER(website) LIKE ? OR LOWER(hotel_key) LIKE ?)")
            args += [f"%{text.lower()}%"] * 3
        if city:
            where.append("LOWER(city) = ?")
            args.append(city.lower())
        if since:
            where.append("run_at >= ?")
            args.append(since)
        cols = "id, " + ", ".join(RUN_COLS)
        return self._rows(f"SELECT {cols} FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY run_at DESC, id DESC LIMIT ?", args + [int(limit)])

    def get_report(self, run_id):
        rows = self._rows("SELECT report_json FROM runs WHERE id = ?", (run_id,))
        return json.loads(rows[0]["report_json"]) if rows else None

    def history(self, key):
        cols = "id, " + ", ".join(RUN_COLS)
        return self._rows(f"SELECT {cols} FROM runs WHERE hotel_key = ? ORDER BY run_at ASC, id ASC", (key,))

    def hotels(self):
        """One row per hotel: how many runs, the latest numbers, and the change since the run before."""
        out = []
        for r in self._rows("SELECT hotel_key, MAX(hotel) AS hotel, MAX(city) AS city, COUNT(*) AS runs, MAX(run_at) AS last_run FROM runs GROUP BY hotel_key ORDER BY MAX(run_at) DESC"):
            h = self.history(r["hotel_key"])
            last, prev = h[-1], (h[-2] if len(h) > 1 else None)
            d = lambda k: (None if prev is None or last.get(k) is None or prev.get(k) is None else round(last[k] - prev[k], 1))  # noqa: E731
            out.append({**r, "headline_score": last["headline_score"], "ai_share": last["ai_share"], "ai_named": last["ai_generic_named"], "ai_asked": last["ai_generic_asked"],
                        "niche_named": last["ai_niche_named"], "niche_asked": last["ai_niche_asked"], "d_score": d("headline_score"), "d_share": d("ai_share")})
        return out

    def competitors(self, city=None, kind="generic", limit=30):
        """Who the assistant names most across every hotel audited (optionally in one city) - the market view."""
        where, args = ["c.is_target = 0", "c.kind = ?"], [kind]
        if city:
            where.append("LOWER(r.city) = ?")
            args.append(city.lower())
        return self._rows(
            "SELECT c.competitor AS competitor, SUM(c.mentions) AS mentions, COUNT(DISTINCT c.run_id) AS runs, ROUND(CAST(AVG(c.avg_rank) AS NUMERIC), 1) AS avg_rank "
            "FROM ai_competitors c JOIN runs r ON r.id = c.run_id WHERE " + " AND ".join(where) + " GROUP BY c.competitor ORDER BY SUM(c.mentions) DESC, c.competitor LIMIT ?", args + [int(limit)])

    def sources(self, city=None, limit=30):
        where, args = ["1=1"], []
        if city:
            where.append("LOWER(r.city) = ?")
            args.append(city.lower())
        return self._rows(
            "SELECT s.domain AS domain, MAX(s.source_kind) AS kind, SUM(s.answers) AS answers, COUNT(DISTINCT s.run_id) AS runs, "
            "SUM(CASE WHEN s.hotel_evidenced = 0 THEN 1 ELSE 0 END) AS hotel_missing, SUM(CASE WHEN s.hotel_evidenced = 1 THEN 1 ELSE 0 END) AS hotel_found "
            "FROM ai_sources s JOIN runs r ON r.id = s.run_id WHERE " + " AND ".join(where) + " GROUP BY s.domain ORDER BY SUM(s.answers) DESC, s.domain LIMIT ?", args + [int(limit)])

    def cities(self):
        return [r["city"] for r in self._rows("SELECT DISTINCT city FROM runs WHERE city <> '' ORDER BY city")]

    def usage_by_month(self):
        return self._rows("SELECT SUBSTR(run_at, 1, 7) AS month, COUNT(*) AS runs, ROUND(CAST(SUM(ai_cost_usd) AS NUMERIC), 3) AS ai_cost_usd, COUNT(DISTINCT hotel_key) AS hotels "
                          "FROM runs GROUP BY SUBSTR(run_at, 1, 7) ORDER BY month DESC")

    def count(self):
        return self._rows("SELECT COUNT(*) AS n FROM runs")[0]["n"]

    def export_rows(self):
        cols = ", ".join(RUN_COLS)
        return self._rows(f"SELECT id, {cols} FROM runs ORDER BY run_at DESC, id DESC")


def open_store(url):
    """A ready Store for the connection string, or None when none is configured. The schema is created on first use."""
    if not url:
        return None
    s = Store(url)
    s.init()
    return s


def to_csv(rows):
    """Plain CSV text (UTF-8) for a list of dicts."""
    import csv
    import io
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()
