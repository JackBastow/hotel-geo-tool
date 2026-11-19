"""
A hotel whose own pages give the question engine few facts (often a site in another language, like a Swedish one) still gets questions about what it really offers, and always a recommended set of prompts.
Offline: the Claude calls are faked.
Run: python test_thin_sites.py
"""
import json
import os
import sys
import tempfile
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import ai_questions
import backend
import prompt_sets

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


H, C = "Eriksberg Hotel & Nature Reserve", "Karlshamn"
PAGES = [{"url": "https://eriksberg.se/", "text": "Välkommen till Eriksberg. Ett naturreservat i Blekinge strax väster om Karlshamn med visenter och kronhjortar. "
          "Följ med på en guidad safari i det 900 hektar stora reservatet."},
         {"url": "https://eriksberg.se/ata/", "text": "Eriksberg har utsetts till Sveriges bästa viltkrog. Restaurang Havsörnen serverar vilt från de egna markerna."},
         {"url": "https://eriksberg.se/konferens/", "text": "Konferens i naturen: mötesrum för upp till 60 personer."}]


class Fake:
    """Answers the site-facts call and the proposals call the way Claude would, one after the other."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.replies.pop(0) if self.replies else "{}"
        return NS(content=[NS(type="text", text=text)], usage=NS(input_tokens=1000, output_tokens=200))


FACTS = json.dumps({"facts": [
    {"text": "offers guided wildlife safaris in a nature reserve", "kind": "offer", "quote": "Följ med på en guidad safari"},
    {"text": "has a game restaurant named Sweden's best", "kind": "offer", "quote": "utsetts till Sveriges bästa viltkrog"},
    {"text": "has meeting rooms for up to 60 people", "kind": "audience", "quote": "mötesrum för upp till 60 personer"},
    {"text": "is just west of Karlshamn in Blekinge", "kind": "place", "place": "Blekinge", "quote": "i Blekinge strax väster om Karlshamn"},
    {"text": "has a heated outdoor pool", "kind": "offer", "quote": "uppvärmd utomhuspool"},                    # not on the pages: must be dropped
    {"text": "is near Stockholm", "kind": "place", "place": "Stockholm", "quote": "nära Stockholm"},             # not on the pages either
]})
PROPS = json.dumps({"prompts": [
    {"text": "Which hotels near Karlshamn offer wildlife safaris in a nature reserve?", "facts": ["f2"], "style": "occasion"},
    {"text": "Where can I stay in Blekinge with a great game restaurant?", "facts": ["f3"], "style": "conversational"},
    {"text": "Which hotels near Karlshamn have meeting rooms for a team of 40?", "facts": ["f4"], "style": "occasion"},
    {"text": "Which hotels in Karlshamn have a heated pool?", "facts": ["f2"], "style": "short search"},           # the pool is not a fact any more: rejected
]})

print("1. facts from the hotel's own pages, in any language")
facts, cost = ai_questions.site_facts(Fake([FACTS]), "m", PAGES, H, C)
texts = [f["text"] for f in facts]
check("facts whose quote is on the pages are kept, in English", any("safari" in t for t in texts) and any("restaurant" in t for t in texts) and any("meeting" in t for t in texts), texts)
check("a fact whose quote is not on the pages is dropped", not any("pool" in t or "Stockholm" in t for t in texts), texts)
check("a place the pages name is kept as a place", [f.get("place") for f in facts if f["kind"] == "site_place"] == ["Blekinge"])
check("no client or no page text: nothing, no error", ai_questions.site_facts(None, "m", PAGES, H, C) == ([], 0.0) and ai_questions.site_facts(Fake([FACTS]), "m", [], H, C) == ([], 0.0))
check("a reply that is not JSON: nothing, no error", ai_questions.site_facts(Fake(["sorry"]), "m", PAGES, H, C)[0] == [])

print("2. the question set for a hotel with thin facts")
prof = {"features": ["gym"], "strong_features": ["gym"], "tier": None, "classes": [], "audiences": [], "segments": []}
fake = Fake([FACTS, PROPS])
built = ai_questions.build(prof, H, C, [], client=fake, model="m", pages=PAGES)
qs = [q["text"] for q in built["questions"]]
check("the pages are read when the facts are thin", len(fake.calls) == 2 and "Blekinge" in fake.calls[0]["messages"][0]["content"])
check("questions about what the hotel really offers come out", any("safari" in q for q in qs) and any("game restaurant" in q for q in qs) and any("meeting rooms" in q for q in qs), qs)
check("a proposal about something the pages do not state is still rejected", not any("pool" in q for q in qs) and any("pool" in r["why"] or "pool" in r["text"] for r in built["rejected"]), built["rejected"])
check("a place the pages name counts as the place a question mentions", any("Blekinge" in q for q in qs))
check("and there are enough questions for a set", len([q for q in built["questions"] if q.get("kind") == "niche"]) >= 10, len(qs))
rich = {"features": ["gym"], "strong_features": ["gym"], "tier": None, "classes": [], "audiences": [], "segments": []}
fake2 = Fake([PROPS])
ai_questions.build({**rich, "tier": {"key": "upscale", "label": "Upscale", "why": "x"}, "district": "Old Town", "classes": ["business", "city_centre"], "audiences": [{"key": "business", "label": "Business travellers", "level": "strong", "why": "x"}]},
                   H, C, [{"name": "A Museum", "kind": "attraction", "km": 1, "source": "Wikipedia"}, {"name": "B Park", "kind": "attraction", "km": 2, "source": "Wikipedia"}], client=fake2, model="m", pages=PAGES)
check("a hotel with plenty of facts does not pay for the extra reading", len(fake2.calls) == 1 and "Verified facts" in fake2.calls[0]["messages"][0]["content"])
offline = ai_questions.build(prof, H, C, [], client=None)
check("with no Claude key at all, the town questions still give a full set", len([q for q in offline["questions"] if q.get("kind") == "niche"]) >= 8, len(offline["questions"]))
check("none of them names the hotel", all("Eriksberg Hotel" not in q["text"] for q in offline["questions"]))

print("3. a hotel already checked with too few questions gets a recommended set")
db = backend.open_store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db"))
rep = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
rep["meta"].update(base="https://eriksberg.se/", website="eriksberg.se", hotel=H, city=C, run_at="2026-11-19T15:19:00+00:00")
rep["question_plan"] = {"questions": [{"id": "q1", "kind": "niche", "angle": "Facilities", "text": "Which hotels in Karlshamn have a gym?", "priority": "core"}]}
rep.pop("benchmark", None)
key = backend.hotel_key(rep)
hid = db.create_hotel(H, "eriksberg.se", C, key, grp="individual")
db.save_run(rep)
hotel = db.get_hotel(hid)
for s in db.prompt_sets(hid):
    db.delete_prompt_set(s["id"])
prompt_sets.ensure_from_history(db, hotel)
st = prompt_sets.state(db, hotel)
check("the Prompts tab now has a recommended set to review", st["draft"] and len(st["draft"]["prompts"]) >= 8, st["draft"] and len(st["draft"]["prompts"]))
check("with the question the check did ask, and the town questions", st["draft"] and "Which hotels in Karlshamn have a gym?" in [p["text"] for p in st["draft"]["prompts"]]
      and any("weekend away" in p["text"] for p in st["draft"]["prompts"]))
errs = prompt_sets.check_set(st["draft"]["prompts"], H, C)[1] if st["draft"] else ["none"]
check("and every prompt passes the prompt rules", not errs, errs)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
