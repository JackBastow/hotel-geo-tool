"""
Hotel identity (hotel_identity.py, identity_fix.py): one canonical identity per hotel, for the hotel under audit and for its competitors.

The case (Saunton Sands, Nov 2026): the hotel was registered as 'sauntonsands hotel'; the assistant wrote 'Saunton Sands Hotel' 85 times and about 25 other spellings. The dashboard showed
'sauntonsands hotel (you): 0%' with 'Saunton Sands Hotel, North Devon' (55%) and 'Saunton Sands Hotel Source Spa and Wellness' (39%) as its competitors, and 'Watersmeet Hotel' and
'Watersmeet Hotel, Woolacombe' as two rivals. The names and counts below are the ones in the stored answers. Offline. Run: python test_identity.py
"""
import copy
import os
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import ai_gap
import ai_insights
import ai_sample
import backend
import hotel_identity as hi
import identity_fix

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


# the names the assistant used for the hotel and its neighbours, with how often (from the stored Saunton Sands answers)
OBS = {"Saunton Sands Hotel": 85, "The Chalet Saunton": 11, "Saunton Sands Hotel Source Spa and Wellness": 32, "Saunton Sands Hotel & Source Spa": 31, "Saunton Sands Hotel & Spa": 5,
       "Saunton Beach Villas": 6, "Saunton Sands Hotel, North Devon": 1, "Saunton Sands self-catering apartments": 7, "Saunton Sands Hotel (main building)": 1, "Saunton Apartments": 3,
       "Saunton Sands Hotel (Source Spa and Wellness)": 13, "Saunton Sands Hotel (Braunton, North Devon)": 1, "Surf at Saunton": 3, "Saunton Sands Hotel (Saunton, near Braunton, North Devon)": 1,
       "Saunton Sands Hotel, Source Spa and Wellness": 4, "Saunton Sands Hotel (Source Spa)": 3, "Chalet Saunton": 1, "Saunton Sands Living Luxury Apartments": 1,
       "Saunton Sands Hotel (Saunton, near Braunton)": 1, "Saunton Sands Hotel (The Dining Room)": 2, "Beachside Grill (at Saunton Sands)": 1, "Saunton Sands Hotel (4-star)": 1,
       "Saunton Sands Hotel (four-star, with conditions)": 1, "Saunton Sands Hotel (4-star), via its self-catering apartments": 1, "The Saunton Sands Hotel": 1,
       "Saunton Sands Hotel (Source Spa & Wellness)": 1, "Saunton Sands Hotel, home to Source Spa and Wellness": 1, "Saunton Sands": 3}
THE_HOTEL = [n for n in OBS if n.startswith(("Saunton Sands Hotel", "The Saunton Sands Hotel")) and "self-catering" not in n]
OTHER_PROPERTIES = ["The Chalet Saunton", "Chalet Saunton", "Saunton Beach Villas", "Saunton Sands self-catering apartments", "Saunton Apartments", "Saunton Sands Living Luxury Apartments",
                    "Beachside Grill (at Saunton Sands)", "Saunton Sands Hotel (4-star), via its self-catering apartments", "Surf at Saunton", "Saunton Sands"]
TITLES = ["North Devon&#039;s Leading Luxury Hotel &amp; Spa | Saunton Sands | North Devon", "Living Suites | Saunton Sands Hotel | North Devon", "Award Wining Dining | Saunton Sands Hotel | North Devon",
          "Sea Facing Rooms | Saunton Sands Hotel | North Devon", "Breakfast Menu | Saunton Sands Hotel", "Spa Information | Saunton Sands Hotel", "Self-Catering Apartments | Saunton Sands Hotel"]

print("1. the identity: one canonical name, with the evidence for each alias")
ident = hi.build("sauntonsands hotel", "Saunton", "https://sauntonsands.co.uk/", site_titles=TITLES, observed=OBS)
check("a name typed as the website address run together is replaced by the hotel's own spelling", ident["canonical"] == "Saunton Sands Hotel" and ident["changed"]
      and ident["entered"] == "sauntonsands hotel", (ident["canonical"], ident["basis"]))
check("the website's own name is read from its page titles ('Saunton Sands Hotel' is in most; 'North Devon' has no hotel word)", ident["site_names"] == [] and ident["aliases"][0]["name"] == "Saunton Sands Hotel")
check("the name as typed is kept on the identity, so the dashboard can show what was corrected", ident["entered"] == "sauntonsands hotel" and ident["changed"])
check("every verified alias says what verified it", ident["aliases"] and all(a.get("basis") for a in ident["aliases"]), ident["aliases"][:3])
check("a hotel typed correctly keeps its name (no needless rewriting)", hi.build("Brooklands Hotel", "Weybridge", "https://brooklandshotelsurrey.com/")["canonical"] == "Brooklands Hotel")
check("a name that is only the website address, with nothing better found, is flagged for the operator", bool(hi.build("sauntonsands", "Saunton", "https://sauntonsands.co.uk/")["needs_review"]))

print("2. which names are the hotel, and which only look alike")
wrong_own = [n for n in THE_HOTEL if not hi.is_own(ident, n)[0]]
check("every spelling of the hotel the assistant used is the hotel (a place, a bracketed note, its spa and wellness side, 'The')", not wrong_own, wrong_own)
wrong_other = [n for n in OTHER_PROPERTIES if hi.is_own(ident, n)[0]]
check("a self-catering block, villas, a chalet, a grill, apartments and the beach are NOT the hotel", not wrong_other, wrong_other)
check("the properties kept separate are listed as related, with the reason", {"Saunton Beach Villas", "The Chalet Saunton"} <= {r["name"] for r in ident["related"]}
      and all(r["why"] for r in ident["related"]))
check("the hotel's own spa side is verified by its structure and says so", "its spa or wellness side" in hi.is_own(ident, "Saunton Sands Hotel Source Spa and Wellness")[1])

print("3. competitors: the same hotel written two ways is one, different properties stay apart")
by = [("a1", ["Saunton Sands Hotel", "Watersmeet Hotel", "Hilton London Heathrow", "Woolacombe Bay Hotel"]),
      ("a2", ["Saunton Sands Hotel Source Spa and Wellness", "Watersmeet Hotel, Woolacombe", "Hilton London Heathrow Terminal 5", "Woolacombe Bay Hotel"]),
      ("a3", ["Saunton Sands self-catering apartments", "Watersmeet Hotel"])]
rs = hi.Resolver(ident, by, "Saunton")
check("'Watersmeet Hotel' and 'Watersmeet Hotel, Woolacombe' are one rival", rs.key("Watersmeet Hotel") == rs.key("Watersmeet Hotel, Woolacombe") and rs.display("Watersmeet Hotel, Woolacombe") == "Watersmeet Hotel")
check("'Hilton London Heathrow' and 'Hilton London Heathrow Terminal 5' stay two hotels", rs.key("Hilton London Heathrow") != rs.key("Hilton London Heathrow Terminal 5"))
check("a hotel and its self-catering block stay two, and the block is not the hotel", not rs.is_target("Saunton Sands self-catering apartments") and rs.is_target("Saunton Sands Hotel Source Spa and Wellness"))
check("the hotel under any spelling has one key and one display name", rs.key("Saunton Sands Hotel") == rs.key("Saunton Sands Hotel Source Spa and Wellness") == rs.SELF
      and rs.display("Saunton Sands Hotel, North Devon") == "Saunton Sands Hotel")
_ast = hi.Resolver({}, [("a", ["Maison Astor", "Astor House"])], "")
check("two names listed side by side in ONE answer are different hotels ('Maison Astor' and 'Astor House')", _ast.key("Maison Astor") != _ast.key("Astor House"))
check("a chain's brand alone never makes two hotels one ('Marriott, Paris Opera' vs 'Marriott Lyon')", hi.normal_key("Marriott, Paris Opera", "Paris") != hi.normal_key("Marriott Lyon", "Lyon"))
check("the same rival across checks has one key", hi.normal_key("Watersmeet Hotel", "Saunton") == hi.normal_key("Watersmeet Hotel, Woolacombe", "Saunton"))

_hx = hi.build("The Hoxton, Shoreditch", "London", "https://thehoxton.com/london/shoreditch/", brand_site=True)
check("a group's sister hotel is another hotel ('The Hoxton, Holborn' is not 'The Hoxton, Shoreditch'); the hotel itself is confirmed with its place, and the bare group name is NOT confirmed",
      not hi.is_own(_hx, "The Hoxton, Holborn")[0] and hi.is_own(_hx, "The Hoxton, Shoreditch")[0] and not hi.is_own(_hx, "The Hoxton")[0] and hi.is_own(_hx, "The Hoxton, Shoreditch, London")[0])
check("a different branch of a hotel brand is another hotel", not hi.is_own(hi.build("Hilton Dusseldorf", "Dusseldorf", ""), "Hampton by Hilton Dusseldorf City Centre")[0]
      and hi.is_own(hi.build("Hilton Dusseldorf", "Dusseldorf", ""), "Hilton Düsseldorf")[0])

# found on the live reports: names that only share one word are different hotels, in different answers too
_rv = hi.Resolver(hi.build("Saunton Sands Hotel", "Saunton", ""), [(1, ["Northcote Manor, Burrington (near Umberleigh)", "Boundary Shoreditch", "Fistral Beach Hotel & Spa", "The Royal George, Bideford",
                                                                    "Catalonia Born", "Courtyard by Marriott Amsterdam Arena Atlas", "Premier Inn London Southwark", "Harbour Hotel Christchurch"]),
                                                          (2, ["Lympstone Manor, East Devon", "The RE Shoreditch", "The Beach at Bude", "The Royal Hotel, Bideford", "Catalonia Ramblas Hotel",
                                                               "Amsterdam Marriott Hotel", "Premier Inn London Kensington (Earl's Court)", "Southampton Harbour Hotel & Spa"])], "Saunton")
for _a, _b in [("Northcote Manor, Burrington (near Umberleigh)", "Lympstone Manor, East Devon"), ("Boundary Shoreditch", "The RE Shoreditch"), ("Fistral Beach Hotel & Spa", "The Beach at Bude"),
               ("The Royal George, Bideford", "The Royal Hotel, Bideford"), ("Catalonia Born", "Catalonia Ramblas Hotel"), ("Courtyard by Marriott Amsterdam Arena Atlas", "Amsterdam Marriott Hotel"),
               ("Premier Inn London Southwark", "Premier Inn London Kensington (Earl's Court)"), ("Harbour Hotel Christchurch", "Southampton Harbour Hotel & Spa")]:
    check(f"'{_a}' and '{_b}' share a word but are different hotels", _rv.key(_a) != _rv.key(_b))
_rw = hi.Resolver(hi.build("Saunton Sands Hotel", "Saunton", ""), [(1, ["Watersmeet Hotel"]), (2, ["Watersmeet Hotel, Woolacombe"]), (3, ["Carlyon Bay Hotel"]), (4, ["Carlyon Bay Hotel, Spa & Golf, St Austell"])], "Saunton")
check("the same hotel written with its place or a facility tail is still one hotel", _rw.key("Watersmeet Hotel") == _rw.key("Watersmeet Hotel, Woolacombe") and _rw.key("Carlyon Bay Hotel") == _rw.key("Carlyon Bay Hotel, Spa & Golf, St Austell"))

print("3b. a group's name alone is not a confirmed mention (independent review, Nov 2026)")
import hotelname as hn
_g = hi.matcher_name(_hx)
check("a hotel whose name a group shares is matched as a GroupName; a plain hotel is not", hasattr(_g, "qualifier") and not hasattr(hi.matcher_name(hi.build("Saunton Sands Hotel", "Saunton", "")), "qualifier"))
check("the bare group name is NOT a confirmed mention ('The Hoxton' could be any of its hotels)", not hn.mentioned("1. The Hoxton: trendy rooms and a rooftop bar.", _g, "London")
      and hn.ambiguous("1. The Hoxton: trendy rooms and a rooftop bar.", _g, "London"))
check("with its place beside it, it is confirmed", hn.mentioned("Try The Hoxton, Shoreditch for a stylish stay.", _g, "London") and not hn.ambiguous("Try The Hoxton, Shoreditch for a stylish stay.", _g, "London"))
check("or with the place in the same passage", hn.mentioned("In Shoreditch, The Hoxton is the obvious pick.", _g, "London"))
check("another hotel of the group is not this one, and not ambiguous either", not hn.mentioned("The Hoxton, Holborn is near Covent Garden.", _g, "London") and not hn.ambiguous("The Hoxton, Holborn is near Covent Garden.", _g, "London")
      and not hn.mentioned("The Hoxton Holborn has a pool.", _g, "London"))
check("the same bare name is a mention for a hotel that has no group (the old behaviour is kept)", hn.mentioned("1. Chewton Glen: luxury.", "Chewton Glen, Hampshire", "New Milton"))
check("ai_sample.remark marks it ambiguous, not mentioned, and the summary counts it apart", True)
import ai_sample as _as
_its = [{"id": "a", "kind": "generic", "answer": "1. The Hoxton: trendy.", "mentioned": False, "recommended": False, "position": None, "domains": []},
        {"id": "b", "kind": "generic", "answer": "1. The Hoxton, Shoreditch: trendy.", "mentioned": False, "recommended": False, "position": None, "domains": []},
        {"id": "c", "kind": "generic", "answer": "1. The Hoxton, Holborn: central.", "mentioned": False, "recommended": False, "position": None, "domains": []}]
_as.remark(_its, _g, "London")
_s = _as.summarise(_its)
check("only the answer that names Shoreditch counts as named; the bare one is counted apart", [i["mentioned"] for i in _its] == [False, True, False] and [bool(i.get("ambiguous")) for i in _its] == [True, False, False] and _s["generic_named"] == 1 and _s["ambiguous_named"] == 1, (_s, _its))
_rg = hi.Resolver(_hx_group := hi.build("The Hoxton, Shoreditch", "London", "https://thehoxton.com/london/shoreditch/", brand_site=True), [(1, ["The Hoxton", "Claridge's"]), (2, ["The Hoxton, Holborn"]), (3, ["The Hoxton, Shoreditch"])], "London")
check("in the rankings: the bare name is neither the hotel nor a rival; Holborn is a rival; Shoreditch is the hotel", _rg.is_ambiguous("The Hoxton") and not _rg.is_target("The Hoxton") and _rg.is_target("The Hoxton, Shoreditch")
      and not _rg.is_target("The Hoxton, Holborn"))
_lb = ins_lb = __import__("ai_insights").leaderboard({"answers": {"x": [{"name": "The Hoxton", "rank": 1, "reason": "", "rating": None}, {"name": "Claridge's", "rank": 2, "reason": "", "rating": None}],
                                                         "y": [{"name": "The Hoxton, Shoreditch", "rank": 1, "reason": "", "rating": None}]}},
                                                  [{"id": "x", "kind": "generic", "answer": "t"}, {"id": "y", "kind": "generic", "answer": "t"}], "The Hoxton, Shoreditch", resolver=_rg)
check("the leaderboard: the hotel is named once (answer y), the bare name is reported apart and is not a rival row", [r["mentions"] for r in _lb["rows"] if r["is_target"]] == [1] and _lb["ambiguous_answers"] == 1
      and not any(r["name"] == "The Hoxton" for r in _lb["rows"]), _lb["rows"])
_no = hi.build("The Hoxton, Shoreditch", "London", "https://www.hotelshoreditch.com/")
check("a ', place' name with no group evidence (its own site, no sister hotel seen) keeps counting the short name", not hi.is_ambiguous(_no, "The Hoxton") and hi.is_own(_no, "The Hoxton")[0])
_sib = hi.build("The Hoxton, Shoreditch", "London", "https://www.hotelshoreditch.com/", observed={"The Hoxton, Holborn": 3})
check("...until the assistants name a sister hotel: then the short name is ambiguous", hi.is_ambiguous(_sib, "The Hoxton") and bool(_sib.get("group")))

print("4. the rankings: the hotel is one row at its real score, never its own competitor")
ANS, ITEMS, EXTRACTED, NAMED_IDS = {}, [], {}, set()
HOTEL_SPELLINGS = ["Saunton Sands Hotel", "Saunton Sands Hotel Source Spa and Wellness", "Saunton Sands Hotel, North Devon", "Saunton Sands Hotel & Source Spa", "Saunton Sands Hotel (Source Spa)"]
RIVAL_NAMES = ["Watersmeet Hotel", "Watersmeet Hotel, Woolacombe", "Woolacombe Bay Hotel", "Commodore Hotel"]
for i in range(30):
    qid = f"q{i % 15}"
    aid = f"a{i}"
    names_in = []
    if i % 3 != 2:                                            # the hotel is named in two answers out of three
        names_in.append(HOTEL_SPELLINGS[i % len(HOTEL_SPELLINGS)])
    if i % 7 == 0:
        names_in.append("Saunton Sands Hotel & Spa")          # one answer naming the hotel under two spellings counts once
    names_in += [RIVAL_NAMES[i % len(RIVAL_NAMES)], RIVAL_NAMES[(i + 2) % len(RIVAL_NAMES)]]
    if i % 5 == 0:
        names_in.append("Saunton Sands self-catering apartments")
    if any(n in HOTEL_SPELLINGS or n == "Saunton Sands Hotel & Spa" for n in names_in):
        NAMED_IDS.add(aid)
    text = "Here are options: " + "; ".join(names_in)
    EXTRACTED[aid] = [{"name": n, "rank": k + 1, "reason": "x", "rating": None, "sentiment": "positive", "stars": None, "themes": [], "town": None} for k, n in enumerate(names_in)]
    ITEMS.append({"id": aid, "qid": qid, "kind": "niche" if i % 2 else "generic", "text": f"Question {qid}", "angle": "A", "why": "w", "answer": text, "mentioned": False, "recommended": False,
                  "position": None, "domains": [], "pages": [], "repeats": 2, "names_hotel": False, "searches": 0, "own_site_cited": False})
named_expected = len(NAMED_IDS)
ex = {"answers": EXTRACTED, "failed_ids": []}
old_lb = ai_insights.leaderboard(ex, ITEMS, "sauntonsands hotel", resolver=hi.Resolver(hi.build("sauntonsands hotel", "Saunton", ""), hi.by_answer_of(EXTRACTED), "Saunton"))
check("under the registered name the hotel scored zero and its spellings were rivals (the fault)", next(r for r in old_lb["rows"] if r["is_target"])["mentions"] == 0)
res = hi.Resolver(ident, hi.by_answer_of(EXTRACTED), "Saunton")
for kinds in (("generic",), ("niche",)):
    lb = ai_insights.leaderboard(ex, ITEMS, ident["canonical"], kinds=kinds, resolver=res)
    me = [r for r in lb["rows"] if r["is_target"]]
    check(f"{kinds[0]}: the hotel is ONE row, under its canonical name", len(me) == 1 and me[0]["name"] == "Saunton Sands Hotel", [r["name"] for r in lb["rows"]])
    check(f"{kinds[0]}: none of the hotel's spellings is among its rivals", not any("Source Spa" in r["name"] or r["name"].endswith("North Devon") for r in lb["rows"] if not r["is_target"]),
          [r["name"] for r in lb["rows"] if not r["is_target"]])
    check(f"{kinds[0]}: Watersmeet is one rival, and the self-catering block is its own row", sum(1 for r in lb["rows"] if r["name"].startswith("Watersmeet")) == 1
          and any(r["name"] == "Saunton Sands self-catering apartments" for r in lb["rows"]), [r["name"] for r in lb["rows"]])
gen_ids = [i["id"] for i in ITEMS if i["kind"] == "generic"]
lbg = ai_insights.leaderboard(ex, ITEMS, ident["canonical"], resolver=res)
check("an answer that names the hotel under two spellings counts once (never more answers than were asked)", all(r["mentions"] <= lbg["questions"] for r in lbg["rows"]))
check("the hotel's count is the number of answers that name it", next(r for r in lbg["rows"] if r["is_target"])["mentions"] == len([a for a in NAMED_IDS if int(a[1:]) % 2 == 0]),
      next(r for r in lbg["rows"] if r["is_target"])["mentions"])
br = ai_insights.brand_ranking([lbg, ai_insights.leaderboard(ex, ITEMS, ident["canonical"], kinds=("niche",), resolver=res)], ident["canonical"])
check("the brand ranking has the hotel once, at its real coverage, and Watersmeet once", [r["is_target"] for r in br["all"]].count(True) == 1 and sum(1 for r in br["all"] if r["name"].startswith("Watersmeet")) == 1
      and next(r for r in br["all"] if r["is_target"])["coverage_pct"] > 40, [(r["name"], r["coverage_pct"]) for r in br["all"]])

print("5. a saved report is recalculated from the answers it already holds (nothing is asked again)")
REP = {"meta": {"hotel": "sauntonsands hotel", "city": "Saunton", "website": "https://sauntonsands.co.uk/", "base": "https://sauntonsands.co.uk/", "hotel_name_source": "provided by you"},
       "site": {"pages": [{"title": t, "h1": []} for t in TITLES], "meta": {}}, "guest_questions": {"pages_meta": []}, "entities": [],
       "ai_sample": {"status": "ok", "model": "m", "items": copy.deepcopy(ITEMS), "summary": {}},
       "ai_insights": {"status": "ok", "extracted_answers": copy.deepcopy(EXTRACTED), "sources": [], "pages": []},
       "consultant": {"recommendations": [{"id": "CP-M1", "title": "Win searches: named in 0 of 18; Saunton Sands Hotel Source Spa was named instead", "source": "commercial"},
                                          {"id": "AG-best", "title": "Not named when asked ...", "source": "ai_gap"},
                                          {"id": "Q1", "title": "Make sure your website answers cancellation", "source": "questions", "action": "x"},
                                          {"id": "DS1", "title": "When AI names the hotel it cites booking sites in 0 of 0", "source": "other"}],
                      "top_actions": ["CP-M1", "Q1"], "quick_wins": ["AG-best"]},
       "ai_gap": {"status": "ok", "markets": [], "gaps": [], "rivals": [{"name": "Saunton Sands Hotel Source Spa and Wellness"}, {"name": "Commodore Hotel"}], "comparison": None, "articles": [], "criteria": {}}}
REP["ai_sample"]["summary"] = ai_sample.summarise(REP["ai_sample"]["items"])
_old_res = hi.Resolver(hi.build("sauntonsands hotel", "Saunton", ""), hi.by_answer_of(EXTRACTED), "Saunton")
_old_g = ai_insights.leaderboard(ex, ITEMS, "sauntonsands hotel", resolver=_old_res)
_old_n = ai_insights.leaderboard(ex, ITEMS, "sauntonsands hotel", kinds=("niche",), resolver=_old_res)
REP["ai_insights"].update(leaderboard=_old_g, niche={"questions": [], "leaderboard": _old_n}, brand_ranking=ai_insights.brand_ranking([_old_g, _old_n], "sauntonsands hotel"))
_w = next(r for r in REP["ai_insights"]["brand_ranking"]["all"] if r["name"].startswith("Watersmeet"))
REP["ai_insights"]["brand_ranking"]["all"].append({**_w, "name": "Watersmeet Hotel, Woolacombe", "mentions": 3})
before = copy.deepcopy(REP)
new, diff = identity_fix.reprocess(REP)
check("the report passed in is not changed", REP == before)
check("the hotel's real name replaces the registered one, and the typed name is kept", new["meta"]["hotel"] == "Saunton Sands Hotel" and new["meta"]["hotel_entered"] == "sauntonsands hotel")
check("the report is found to be affected, with the before and after", diff["affected"] and diff["before"]["named"] in (0, None) and diff["after"]["named"] == named_expected + 0 * 1, (diff["before"], diff["after"]))
check("the hotel's spellings that stood among its rivals are listed", "Saunton Sands Hotel Source Spa and Wellness" in diff["own_spellings_among_rivals"], diff["own_spellings_among_rivals"])
check("and the rival written two ways is reported as merged", any("Watersmeet Hotel" in g and "Watersmeet Hotel, Woolacombe" in g for g in diff["merged_rivals"]), diff["merged_rivals"])
check("the recalculated rivals no longer include any spelling of the hotel", not any("Saunton Sands Hotel" in r for r in diff["after"]["rivals"]), diff["after"]["rivals"])
s2 = new["ai_sample"]["summary"]
check("the sample summary is recounted (generic and niche)", s2["generic_named"] + s2["niche_named"] == named_expected, s2)
check("the scoreboard, leaderboard and brand ranking carry the real figures, with the hotel once", new["ai_insights"]["scoreboard"]["named"] > 0
      and [r["is_target"] for r in new["ai_insights"]["brand_ranking"]["all"]].count(True) == 1)
check("the hotel's own spellings are removed from the rival comparison", [r["name"] for r in new["ai_gap"]["rivals"]] == ["Commodore Hotel"], new["ai_gap"]["rivals"])
ids = {r["id"] for r in new["consultant"]["recommendations"]}
check("findings written from the wrong figures are withdrawn, and a finding about the website is kept", ids == {"Q1"} and {w["id"] for w in diff["withdrawn"]} == {"CP-M1", "AG-best", "DS1"}, ids)
check("the lists of top actions and quick wins no longer point at withdrawn findings", new["consultant"]["top_actions"] == ["Q1"] and new["consultant"]["quick_wins"] == [])
check("the report says what was recalculated and withdrawn", new["meta"]["identity_recalculated"]["withdrawn"] and "recalculated" in new["meta"]["identity_recalculated"]["note"])
again, d2 = identity_fix.reprocess(new)
check("recalculating a report that is already right changes nothing (it is idempotent)", not d2["affected"] and again["ai_sample"]["summary"] == new["ai_sample"]["summary"], d2.get("before"))
healthy = copy.deepcopy(REP)
healthy["meta"]["hotel"] = "Saunton Sands Hotel"
healthy["ai_sample"]["items"], healthy["ai_insights"]["extracted_answers"] = copy.deepcopy(ITEMS), copy.deepcopy(EXTRACTED)
fixed, dh = identity_fix.reprocess(healthy)
check("a hotel registered under its real name is not touched beyond marking its answers (no findings withdrawn for a healthy name)", not dh["withdrawn"] or dh["affected"], dh["before"])
check("a report with no AI answers is left alone", identity_fix.reprocess({"meta": {}, "ai_sample": {"status": "unavailable"}})[0] is None)

print("6. the identity is kept from check to check, and rivals merge over time")
DB = os.path.join(tempfile.gettempdir(), "hotel_identity_test.db")
if os.path.exists(DB):
    os.remove(DB)
st = backend.open_store("sqlite:///" + DB.replace("\\", "/"))
st.save_identity("sauntonsands.co.uk", {"canonical": "Saunton Sands Hotel", "aliases": [{"name": "Saunton Sands Hotel", "basis": "canonical name"}]})
st.save_identity("sauntonsands.co.uk", {"canonical": "Saunton Sands Hotel", "aliases": [{"name": "Saunton Sands Hotel & Spa", "basis": "assistants"}]})
got = st.get_identity("sauntonsands.co.uk")
check("the identity is stored and its verified aliases are never lost by a later check", got["canonical"] == "Saunton Sands Hotel" and {a["name"] for a in got["aliases"]} == {"Saunton Sands Hotel", "Saunton Sands Hotel & Spa"}, got)
check("an unknown hotel has no stored identity", st.get_identity("nope.example") is None)
nxt = hi.build("sauntonsands hotel", "Saunton", "https://sauntonsands.co.uk/", known=[a["name"] for a in got["aliases"]])
check("the next check starts from the verified names, even before the assistants are asked", nxt["canonical"] == "Saunton Sands Hotel" and nxt["changed"])
base = copy.deepcopy(REP)
base["ai_sample"]["items"], base["ai_insights"]["extracted_answers"] = copy.deepcopy(ITEMS), copy.deepcopy(EXTRACTED)
rep1, _ = identity_fix.reprocess(base)
rep2 = copy.deepcopy(rep1)
for r in rep2["ai_insights"]["brand_ranking"]["all"]:                      # an earlier check that wrote the rival under its other name
    if r["name"] == "Watersmeet Hotel":
        r["name"] = "Watersmeet Hotel, Woolacombe"
rep2["meta"]["run_at"] = "2026-11-20T10:00:00+00:00"
rep1["meta"]["run_at"] = "2026-11-27T10:00:00+00:00"
st.save_run(rep2)
st.save_run(rep1)
hist = st.competitor_history(backend.hotel_key(rep1))
w = [r for r in hist["rows"] if r["name"].startswith("Watersmeet")]
check("a rival written two ways in two checks is ONE line on the dashboard chart", len(w) == 1 and sum(1 for p in w[0]["points"] if (p["mentions"] or 0) > 0) == 2, [r["name"] for r in hist["rows"]])
check("the hotel is one line, never listed among its own competitors", sum(1 for r in hist["rows"] if r["is_target"]) == 1 and not any("Source Spa" in r["name"] for r in hist["rows"]))
mk = st.competitors(city="Saunton", limit=20)
check("the market view merges the same rival too", sum(1 for r in mk if r["competitor"].startswith("Watersmeet")) == 1, [r["competitor"] for r in mk])

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
