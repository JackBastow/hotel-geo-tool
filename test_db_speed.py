"""
Offline test for the database speed fix behind the slow admin pages: the schema check runs once per process (it used to run on every page view), a connection is reused for the next query on the same thread
instead of opening a new one each time, an idle connection is tested before use, and a connection the host dropped is replaced. A stand-in for the Postgres driver counts what is done: no network.
Run: python test_db_speed.py
"""
import sys
import threading
import types
import warnings

warnings.filterwarnings("ignore")

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


# ---- a stand-in for psycopg that counts connections and statements
stats = {"connects": 0, "statements": [], "dead": set()}


class Cur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        if self.conn.id in stats["dead"]:
            raise RuntimeError("server closed the connection")
        stats["statements"].append(sql)

    def fetchall(self):
        return []

    def fetchone(self):
        return {"id": 1}


class Conn:
    def __init__(self):
        stats["connects"] += 1
        self.id, self.closed = stats["connects"], False

    def cursor(self):
        return Cur(self)

    def execute(self, sql, params=()):
        Cur(self).execute(sql, params)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


fake = types.ModuleType("psycopg")
fake.connect = lambda url, **kw: Conn()
fake.rows = types.ModuleType("psycopg.rows")
fake.rows.dict_row = object()
sys.modules["psycopg"], sys.modules["psycopg.rows"] = fake, fake.rows

import backend

URL = "postgresql://user:pw@host/db"
print("1. the schema check runs once per process")
s1 = backend.open_store(URL)
n_init = len(stats["statements"])
check("opening the store the first time runs the schema statements", n_init > 10, n_init)
c_after_init = stats["connects"]
s2 = backend.open_store(URL)
s3 = backend.open_store(URL)
check("opening it again, which every admin page and every report view does, runs nothing and returns the same store", s1 is s2 is s3 and len(stats["statements"]) == n_init and stats["connects"] == c_after_init)
check("a local file database is still checked each time (it is cheap, and the file may be replaced)", backend.open_store("sqlite:///" + __import__("os").path.join(__import__("tempfile").gettempdir(), "speed_a.db")) is not backend.open_store("sqlite:///" + __import__("os").path.join(__import__("tempfile").gettempdir(), "speed_a.db")))

print("2. a connection is reused")
before = stats["connects"]
for _ in range(6):
    s1._rows("SELECT 1")
check("six queries on one thread use one connection, not six", stats["connects"] - before <= 1, stats["connects"] - before)

print("3. an idle connection is tested; a dropped one is replaced")
s1._tl.used -= backend.IDLE_PING_S + 5
k = len(stats["statements"])
s1._rows("SELECT 2")
check("after a pause the connection is tested with one cheap query first", "SELECT 1" in stats["statements"][k:k + 2], stats["statements"][k:k + 3])
live = s1._tl.conn.id
stats["dead"].add(live)
s1._tl.used -= backend.IDLE_PING_S + 5
before = stats["connects"]
try:
    s1._rows("SELECT 3")
    ok = True
except Exception as e:  # noqa: BLE001
    ok = False
check("when the host has dropped it, a new connection is opened and the query still works", ok and stats["connects"] == before + 1 and s1._tl.conn.id != live)

print("4. each thread has its own connection")
seen = []
t = threading.Thread(target=lambda: (s1._rows("SELECT 4"), seen.append(s1._tl.conn.id)))
t.start()
t.join()
check("a second thread does not share the first thread's connection", seen and seen[0] != s1._tl.conn.id)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
