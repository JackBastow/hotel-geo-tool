"""
A restart no longer loses a hotel's check (code review, Nov 2026): every deploy restarts the service, and the queue of checks lived only in memory, so a check cut off half way waited
12 hours and the hotels not yet reached waited for the next Monday. Now a check that was started, has no result since and recorded no error is due again at once, and the service
picks up whatever is due a minute after it starts. Offline.
Run: python test_resume.py
"""
import datetime as dt
import sys
import warnings

warnings.filterwarnings("ignore")
import scheduler

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


now = dt.datetime(2026, 11, 24, 9, 0, tzinfo=dt.timezone.utc)
iso = lambda d: d.isoformat()          # noqa: E731
started = now - dt.timedelta(minutes=20)
week_ago = now - dt.timedelta(days=7)

check("started 20 minutes ago, no result since, no error: cut off, so due again now",
      scheduler.interrupted({"last_attempt": iso(started), "last_error": ""}, week_ago, now))
check("started and finished (a result after the start): not cut off",
      not scheduler.interrupted({"last_attempt": iso(started), "last_error": ""}, now - dt.timedelta(minutes=5), now))
check("started and failed with an error: not cut off (the 12-hour retry rule applies)",
      not scheduler.interrupted({"last_attempt": iso(started), "last_error": "TimeoutError: x"}, week_ago, now))
check("started more than a day ago: left to the normal weekly rule",
      not scheduler.interrupted({"last_attempt": iso(now - dt.timedelta(days=2)), "last_error": ""}, week_ago, now))
check("never started: not cut off", not scheduler.interrupted({"last_attempt": None, "last_error": ""}, week_ago, now))


class DB:
    def __init__(self, hotels, runs):
        self.hotels, self.runs = hotels, runs

    def list_hotels(self, only_active=True):
        return self.hotels

    def hotel_runs(self, key):
        return self.runs.get(key, [])


cut = {"id": 1, "hotel_key": "a", "weekly": 1, "setup": "", "last_attempt": iso(started), "last_error": ""}
recent = {"id": 2, "hotel_key": "b", "weekly": 1, "setup": "", "last_attempt": iso(now - dt.timedelta(days=1)), "last_error": ""}
db = DB([cut, recent], {"a": [{"run_at": iso(week_ago - dt.timedelta(days=3))}], "b": [{"run_at": iso(now - dt.timedelta(days=1, minutes=-10))}]})
w = scheduler.Weekly(type("C", (), {"database_url": None})(), None, None)
due = [h["id"] for h in w.due(db=db, now=now)]
check("the weekly list includes a cut-off check even inside the 12-hour retry window, and not a hotel checked yesterday", due == [1], due)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
