"""
Database side of the hotel portal: users, hotels, who may see which hotel, invite links, and the action list for each hotel. Mixed into backend.Store, so it works on the same
connection handling and on both SQLite (tests) and Postgres (the site).

A hotel is identified, as in the rest of the tool, by its hotel_key (the website host plus the hotel's folder for a chain's page), so every audit of that website, whoever ran it, is part of the
hotel's history.
"""

import datetime as dt

HOTEL_COLS = ("name", "website", "city", "tier", "audiences", "weekly", "active", "last_attempt", "last_error")
ACTION_COLS = ("akey", "title", "source", "category", "priority", "effort", "team", "kind", "status", "state", "first_run_id", "last_run_id", "first_seen", "last_seen", "updated", "done_at",
               "resolved_at", "resolution", "reopened", "note", "rec_json", "done_by")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class PortalMixin:
    def _init_portal(self, conn, pk):
        self._run(conn, f"CREATE TABLE IF NOT EXISTS users (id {pk}, email TEXT UNIQUE, name TEXT, pw_hash TEXT, role TEXT, active INTEGER, created TEXT, last_login TEXT)")
        self._run(conn, f"CREATE TABLE IF NOT EXISTS hotels (id {pk}, name TEXT, website TEXT, city TEXT, hotel_key TEXT UNIQUE, tier TEXT, audiences TEXT, weekly INTEGER, active INTEGER, "
                        "created TEXT, last_attempt TEXT, last_error TEXT)")
        self._run(conn, "CREATE TABLE IF NOT EXISTS hotel_users (user_id INTEGER, hotel_id INTEGER, PRIMARY KEY (user_id, hotel_id))")
        self._run(conn, f"CREATE TABLE IF NOT EXISTS invites (id {pk}, token_hash TEXT UNIQUE, email TEXT, hotel_id INTEGER, user_id INTEGER, kind TEXT, created TEXT, expires TEXT, used TEXT)")
        self._run(conn, f"CREATE TABLE IF NOT EXISTS actions (id {pk}, hotel_id INTEGER, akey TEXT, title TEXT, source TEXT, category TEXT, priority TEXT, effort TEXT, team TEXT, kind TEXT, "
                        "status TEXT, state TEXT, first_run_id INTEGER, last_run_id INTEGER, first_seen TEXT, last_seen TEXT, updated TEXT, done_at TEXT, resolved_at TEXT, resolution TEXT, "
                        "reopened INTEGER, note TEXT, rec_json TEXT, done_by TEXT)")
        for sql in ("CREATE INDEX IF NOT EXISTS actions_hotel ON actions (hotel_id)", "CREATE INDEX IF NOT EXISTS hu_hotel ON hotel_users (hotel_id)", "CREATE INDEX IF NOT EXISTS inv_hash ON invites (token_hash)"):
            self._run(conn, sql)

    def _exec(self, sql, params=()):
        conn = self._connect()
        try:
            self._run(conn, sql, params)
            conn.commit()
        finally:
            conn.close()

    # hotels ------------------------------------------------------------------
    def create_hotel(self, name, website, city, hotel_key, tier=None, audiences="", weekly=1):
        conn = self._connect()
        try:
            hid = self._insert(conn, "hotels", {"name": name, "website": website, "city": city, "hotel_key": hotel_key, "tier": tier or "", "audiences": audiences or "", "weekly": int(bool(weekly)),
                                                "active": 1, "created": now_iso(), "last_attempt": "", "last_error": ""})
            conn.commit()
            return hid
        finally:
            conn.close()

    def get_hotel(self, hotel_id):
        r = self._rows("SELECT * FROM hotels WHERE id = ?", (hotel_id,))
        return r[0] if r else None

    def hotel_by_key(self, key):
        r = self._rows("SELECT * FROM hotels WHERE hotel_key = ?", (key,))
        return r[0] if r else None

    def list_hotels(self, only_active=False):
        return self._rows("SELECT * FROM hotels" + (" WHERE active = 1" if only_active else "") + " ORDER BY name")

    def set_hotel(self, hotel_id, **fields):
        use = {k: v for k, v in fields.items() if k in HOTEL_COLS}
        if use:
            self._exec(f"UPDATE hotels SET {', '.join(k + ' = ?' for k in use)} WHERE id = ?", list(use.values()) + [hotel_id])

    # users -------------------------------------------------------------------
    def create_user(self, email, name, pw_hash, role="hotel"):
        conn = self._connect()
        try:
            uid = self._insert(conn, "users", {"email": email, "name": name or "", "pw_hash": pw_hash, "role": role, "active": 1, "created": now_iso(), "last_login": ""})
            conn.commit()
            return uid
        finally:
            conn.close()

    def user_by_email(self, email):
        r = self._rows("SELECT * FROM users WHERE email = ?", ((email or "").lower(),))
        return r[0] if r else None

    def user_by_id(self, uid):
        r = self._rows("SELECT * FROM users WHERE id = ?", (uid,))
        return r[0] if r else None

    def set_password(self, uid, pw_hash):
        self._exec("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, uid))

    def set_user_active(self, uid, active):
        self._exec("UPDATE users SET active = ? WHERE id = ?", (int(bool(active)), uid))

    def touch_login(self, uid):
        self._exec("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), uid))

    def link_user(self, uid, hotel_id):
        conn = self._connect()
        try:
            if not self._rows("SELECT 1 AS x FROM hotel_users WHERE user_id = ? AND hotel_id = ?", (uid, hotel_id)):
                self._run(conn, "INSERT INTO hotel_users (user_id, hotel_id) VALUES (?, ?)", (uid, hotel_id))
                conn.commit()
        finally:
            conn.close()

    def hotels_for_user(self, uid):
        return self._rows("SELECT h.* FROM hotels h JOIN hotel_users hu ON hu.hotel_id = h.id WHERE hu.user_id = ? AND h.active = 1 ORDER BY h.name", (uid,))

    def users_for_hotel(self, hotel_id):
        return self._rows("SELECT u.id, u.email, u.name, u.active, u.last_login, u.created FROM users u JOIN hotel_users hu ON hu.user_id = u.id WHERE hu.hotel_id = ? ORDER BY u.email", (hotel_id,))

    # invites and resets --------------------------------------------------------
    def create_invite(self, token_hash, email, hotel_id, user_id, kind, days):
        exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            self._insert(conn, "invites", {"token_hash": token_hash, "email": email, "hotel_id": hotel_id, "user_id": user_id, "kind": kind, "created": now_iso(), "expires": exp, "used": ""})
            conn.commit()
        finally:
            conn.close()

    def get_invite(self, token_hash):
        """The invite when it exists, has not been used and has not expired; otherwise None."""
        r = self._rows("SELECT * FROM invites WHERE token_hash = ?", (token_hash,))
        if not r or r[0]["used"] or r[0]["expires"] < now_iso():
            return None
        return r[0]

    def use_invite(self, invite_id):
        self._exec("UPDATE invites SET used = ? WHERE id = ?", (now_iso(), invite_id))

    def open_invites(self, hotel_id):
        return self._rows("SELECT id, email, kind, created, expires FROM invites WHERE hotel_id = ? AND used = '' AND expires > ? ORDER BY id DESC", (hotel_id, now_iso()))

    # actions -----------------------------------------------------------------
    def list_actions(self, hotel_id):
        return self._rows("SELECT * FROM actions WHERE hotel_id = ? ORDER BY id", (hotel_id,))

    def get_action(self, action_id):
        r = self._rows("SELECT * FROM actions WHERE id = ?", (action_id,))
        return r[0] if r else None

    def insert_action(self, hotel_id, row):
        conn = self._connect()
        try:
            aid = self._insert(conn, "actions", {"hotel_id": hotel_id, **{k: v for k, v in row.items() if k in ACTION_COLS}})
            conn.commit()
            return aid
        finally:
            conn.close()

    def update_action(self, action_id, **fields):
        use = {k: v for k, v in fields.items() if k in ACTION_COLS}
        if use:
            self._exec(f"UPDATE actions SET {', '.join(k + ' = ?' for k in use)} WHERE id = ?", list(use.values()) + [action_id])

    # runs, as the portal needs them ---------------------------------------------
    def hotel_runs(self, key):
        """The hotel's saved audits, newest first: id, run time, the link token, the score and the AI coverage."""
        return self._rows("SELECT id, run_at, access_token, headline_score, headline_status, coverage_pct, ai_generic_named, ai_generic_asked, ai_niche_named, ai_niche_asked, recs_total "
                          "FROM runs WHERE hotel_key = ? ORDER BY run_at DESC, id DESC", (key,))

    def run_pages(self, run_id):
        """The pages the assistant cited in one audit: url, domain, title, how many answers cited it, whether it names the hotel or a competitor, whether it is the hotel's own site."""
        return self._rows("SELECT url, domain, title, cited, questions, names_hotel, names_competitor, own_site FROM ai_pages WHERE run_id = ?", (run_id,))

    def hotel_key_for_token(self, token):
        r = self._rows("SELECT hotel_key FROM runs WHERE access_token = ?", (token,))
        return r[0]["hotel_key"] if r else None

    def run_token(self, run_id):
        r = self._rows("SELECT access_token FROM runs WHERE id = ?", (run_id,))
        return r[0]["access_token"] if r else None
