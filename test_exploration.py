"""
The exploratory questions put to work (exploration.py): prompts worth tracking from the results of recent checks, and the gap map by kind of question. Offline, against SQLite.
Run: python test_exploration.py
"""
import copy
import json
import os
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import backend
import exploration
import prompts_view
import ai_dash

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


H, C = "Brooklands Hotel", "Weybridge"
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "e.db")
db = backend.open_store(URL)
BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))

Q_MEET = "Which hotels near Mercedes-Benz World in Weybridge have meeting rooms for a team workshop?"
Q_SPA = "Which hotels in Weybridge have a spa for a relaxing weekend break?"
Q_ONCE = "Which hotels near Brooklands Museum in Weybridge are best for a car enthusiast weekend?"
Q_TRACKED = "Which 4-star hotels in Weybridge are good value for a weekend?"


def answer(aid, q, text, mentioned, rivals, quoted=(), source="new", angle="Meetings and events", kind="niche"):
    return ({"id": aid, "qid": aid.split("#")[0], "kind": kind, "text": q, "angle": angle, "source": source, "answer": text, "mentioned": mentioned,
             "pages": [{"url": f"https://www.{d}/list", "cited": True} for d in quoted]}, {aid: [{"name": n} for n in rivals] + ([{"name": H}] if mentioned else [])})


def report(run_at, rows):
    r = copy.deepcopy(BASE)
    r["meta"].update(base="https://www.brooklands.example/", website="brooklands.example", hotel=H, city=C, run_at=run_at)
    items, ext = [], {}
    for it, ex in rows:
        items.append(it)
        ext.update(ex)
    r["ai_sample"] = {"status": "ok", "items": items}
    r["ai_insights"] = {"status": "ok", "extracted_answers": ext, "facts_check": {"status": "ok", "passages": 2, "matches": 1, "rows": [
        {"topic": "parking", "label": "Parking", "status": "differs", "says": "parking is not available on site", "times": 2, "url": "", "our_record": "The hotel's website states it."}]}}
    return r


def week(n, me_meet, me_spa):
    return [answer(f"m{n}", Q_MEET, "...", me_meet, ["Oatlands Park Hotel"], ["hotels.example", "eventvenues.example"]),
            answer(f"m{n}#2", Q_MEET, "...", False, ["Oatlands Park Hotel", "The Runnymede"], ["hotels.example"]),
            answer(f"s{n}", Q_SPA, "...", me_spa, ["Pennyhill Park"], [], angle="Spa and wellness"),
            answer(f"t{n}", Q_TRACKED, "...", False, ["Oatlands Park Hotel"], ["booking.com"], source="benchmark", angle="Price level")]


key = backend.hotel_key(report("2026-11-01T05:00:00+00:00", []))
hid = db.create_hotel(H, "brooklands.example", C, key)
hotel = db.get_hotel(hid)
db.save_run(report("2026-11-02T05:00:00+00:00", week(1, False, True) + [answer("o1", Q_ONCE, "...", True, [], angle="Near a landmark")]))
db.save_run(report("2026-11-09T05:00:00+00:00", week(2, False, True)))
db.save_run(report("2026-11-16T05:00:00+00:00", week(3, False, False)))

print("1. prompts worth tracking, from the results")
sug = exploration.suggest(db, hotel, have=[Q_TRACKED])
texts = [s["text"] for s in sug]
check("a question that named the hotel in two or more checks is suggested, first", texts and texts[0] == Q_SPA, sug)
check("a question that kept naming the same rival is suggested, saying who", Q_MEET in texts and "Oatlands Park Hotel" in next(s["why"] for s in sug if s["text"] == Q_MEET))
check("a question asked only once is not suggested", Q_ONCE not in texts)
check("a question already tracked is never suggested", Q_TRACKED not in texts)
check("a hotel with a single check gets no suggestions yet", exploration.suggest(db, {**hotel, "hotel_key": "nobody"}, []) == [])

print("2. the gap map")
rep = exploration.recent(db, hotel, 1)[0][1]
gm = exploration.gap_map(rep, H, C, "brooklands.example")
by = {g["key"]: g for g in gm}
check("questions are grouped like the Prompts tab, tracked and exploratory together", set(by) == {"who", "offer", "place"}, list(by))
w = by["who"]
check("each kind says how often the hotel was named, and who was named instead", w["named"] == 0 and w["answers"] == 2 and w["rivals"][0] == ("Oatlands Park Hotel", 2))
check("the sites quoted when a rival was named and the hotel was not are listed, most quoted first", [d for d, _k, _c in w["quoted"]][:2] == ["hotels.example", "eventvenues.example"], w["quoted"])
check("and the brief names the rivals and the sites, with an example question", "Oatlands Park Hotel" in w["brief"] and "hotels.example" in w["brief"] and w["example"] == Q_MEET)
html_ = exploration.gap_map_html(gm, "16 Nov")
check("the panel says it is a sample and a pointer, not a ranking", "not a ranking" in html_ and "named in 0 of 2 answers" in html_)

print("3. on the hotel's dashboard")
tab = ai_dash.panel(db, hotel)
check("the AI visibility tab shows the fact-check and the gap map", "What AI says about the hotel" in tab and "parking is not available on site" in tab and "Where the hotel is missing out" in tab)
pv = prompts_view.panel({"active": None, "draft": {"prompts": [{"id": "p1", "text": Q_TRACKED, "angle": "Price level", "source": "recommended"}], "version": 0}, "history": []}, hotel, "/x", True, 0, [], sug)
check("the Prompts tab offers them with an Add button", "Exploratory questions worth tracking" in pv and pv.count("psugadd") >= len(sug))
check("each Add button says which section the prompt goes in (a spa question under 'What it offers', not 'Other prompts')",
      'data-sec="offer" data-text="' + Q_SPA in pv and 'data-sec="who" data-text="' + Q_MEET in pv and 'psugadd" data-sec="own"' not in pv, pv[pv.find("psugadd"):][:300])

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
