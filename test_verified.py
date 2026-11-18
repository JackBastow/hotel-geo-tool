"""
Verified actions: an action the hotel marked done moves to 'Verified' only when a later check confirms it is gone (from the hotel's own site: the next check; from sampled AI answers: two checks in a row).
Run: python test_verified.py
"""
import copy
import json
import os
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import backend
import portal_view
import progress

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


db = backend.open_store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "v.db"))
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
SITE = dict(BASE["consultant"]["recommendations"][0], id="Q1", title="Fill the gaps on the FAQ page: parking and breakfast", source="questions", tag="Q1")
AI = dict(BASE["consultant"]["recommendations"][0], id="AF-parking", title="AI tells travellers something wrong about the hotel: parking", source="ai", tag="AF")
OTHER = dict(BASE["consultant"]["recommendations"][0], id="L1", title="Say how far the hotel is from the station", source="location", tag="L1")


def rep(day, recs):
    r = copy.deepcopy(BASE)
    r["meta"].update(base="https://www.v-hotel.example/", website="v-hotel.example", hotel="V Hotel", run_at=f"2026-11-{day:02d}T05:00:00+00:00")
    r["consultant"]["recommendations"] = recs
    r["consultant"]["coverage"] = {"pages_read": 8, "pages_attempted": 8}
    return r


hid = db.create_hotel("V Hotel", "v-hotel.example", "Weybridge", backend.hotel_key(rep(1, [])))
hotel = db.get_hotel(hid)


def run(day, recs):
    r = rep(day, recs)
    return progress.sync(db, hotel, r, db.save_run(r))


def act(source):
    return next(a for a in db.list_actions(hid) if a["source"] == source)


run(2, [SITE, AI, OTHER])
progress.set_status(db, hid, act("questions")["id"], "done", "gm")
progress.set_status(db, hid, act("ai")["id"], "done", "gm")
check("marked done, before any check: in 'waiting for a check to confirm', not verified", progress.board_group(act("questions")) == "completed" and not progress.is_verified(act("questions")))

run(9, [OTHER])                                   # both gone from the next check
check("a website problem gone from the next check is verified", progress.board_group(act("questions")) == "verified" and act("questions")["resolution"] == "verified")
check("an AI-answer problem gone once is NOT yet verified (answers vary)", progress.board_group(act("ai")) == "completed" and act("ai")["resolution"] == "not_flagged")

run(16, [OTHER])                                  # still gone a second time
check("gone two checks in a row, the AI-answer problem is verified", progress.board_group(act("ai")) == "verified" and act("ai")["resolution"] == "verified_repeat")
c = progress.action_counts(db.list_actions(hid))
check("both still count as completed, and both as verified", c["completed"] == 2 and c["verified"] == 2, c)

run(23, [OTHER, AI])                              # the AI says it again
check("if it comes back, it leaves Verified and is shown as still flagged", progress.board_group(act("ai")) == "todo" and act("ai")["state"] == "open" and act("ai")["reopened"], dict(act("ai")))

print("the board")
sm = {"latest_run_id": None, "runs": 4}
board = portal_view.action_board(sm, db.list_actions(hid), True)
check("the actions board has a Verified section with the confirmed action in it", "Verified: done and confirmed by a check" in board and "Verified: the check on" in board)
check("the waiting section is named for what it is", "Marked done, waiting for a check to confirm" not in board or "the next check will confirm it" in board)
cleared = dict(act("location"), status="todo", state="resolved", resolution="verified")
check("something nobody marked done is never verified, however long it stays gone", progress.board_group(cleared) == "cleared" and not progress.is_verified(cleared))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
