"""
Two things happening at once to the same hotel (code review, Nov 2026): a manual and a weekly check finishing together, or two people opening a new hotel's dashboard at the same moment,
used to make two copies of every action and two draft prompt sets. Offline (a temporary SQLite database).
Run: python test_concurrency.py
"""
import collections
import copy
import json
import os
import sys
import tempfile
import threading
import warnings

warnings.filterwarnings("ignore")
import backend
import progress

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "c.db")
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
db = backend.open_store(URL)
hid = db.create_hotel("Hotel A", "hotel-a.com", "Paris", "hotel-a.com")


def rep(run_at):
    r = copy.deepcopy(BASE)
    r["meta"].update(base="https://www.hotel-a.com/", website="hotel-a.com", hotel="Hotel A", run_at=run_at)
    r["consultant"]["coverage"] = {"pages_read": 8, "pages_attempted": 8}
    return r


print("1. two checks of one hotel finishing together")
r1, r2 = rep("2026-10-01T09:00:00+00:00"), rep("2026-10-01T09:05:00+00:00")
id1, id2 = db.save_run(r1), db.save_run(r2)
barrier = threading.Barrier(2)
orig = db.list_actions


def slow_list(hotel_id):
    out = orig(hotel_id)
    try:
        barrier.wait(timeout=1)          # both read the empty list before either writes: the window a slow database opens
    except threading.BrokenBarrierError:
        pass
    return out


db.list_actions = slow_list
ts = [threading.Thread(target=progress.on_run_saved, args=(db, r, i)) for r, i in ((r1, id1), (r2, id2))]
[t.start() for t in ts]
[t.join() for t in ts]
db.list_actions = orig
keys = collections.Counter(a["akey"] for a in db.list_actions(hid))
check("each action is on the list once", keys and max(keys.values()) == 1, keys.most_common(3))
check("one draft prompt set, not two", len([s for s in db.prompt_sets(hid) if s["status"] == "draft"]) <= 1)

print("2. copies made before this fix")
a0 = db.list_actions(hid)[0]
conn = db._connect()
try:
    db._run(conn, "DROP INDEX IF EXISTS actions_hotel_key")
    conn.commit()
finally:
    conn.close()
cols = {k: v for k, v in a0.items() if k != "id"}
db.update_action(a0["id"], status="done", done_at="2026-10-02T09:00:00+00:00")
copy_id = db.insert_action(hid, {**cols, "status": "todo"})
check("(an old database can hold a second copy)", copy_id is not None)
conn = db._connect()
try:
    db._dedupe_actions(conn)
finally:
    conn.close()
left = [a for a in db.list_actions(hid) if a["akey"] == a0["akey"]]
check("are merged into one, keeping the copy the hotel marked done", len(left) == 1 and left[0]["status"] == "done", [(a["id"], a["status"]) for a in left])
check("and the database then refuses a new copy", db.insert_action(hid, {**cols, "status": "todo"}) is None)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
