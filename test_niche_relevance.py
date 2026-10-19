"""
Offline tests for the AI test questions' relevance (Holiday Inn Amsterdam Arena Towers review) and for the person's own prompts. A hotel beside a stadium, 18.6 km from Schiphol, with meeting rooms and a gym,
must not be asked about airport stays, spa breaks, city-centre sights, families or dining destinations just because its pages mention those words.
Run: python test_niche_relevance.py
"""
import json
from types import SimpleNamespace as NS

import ai_niche
import ai_sample

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HOTEL, CITY = "Holiday Inn Amsterdam Arena Towers", "Amsterdam"
TEXT = ("Holiday Inn Amsterdam - Arena Towers is a 4-star hotel in Amsterdam Zuidoost. The Johan Cruijff ArenA is a 5 minute walk from the hotel. Amsterdam Schiphol Airport is 18.6 km away. "
        "Our meeting rooms suit workshops and conferences. Enjoy the fitness centre and a relaxing pool area. Kids stay free. Our restaurant serves breakfast and dinner. EV charging is available in the car park. "
        "Explore the city of Amsterdam and the city centre sights by metro.")
PAGES = [{"url": "https://www.ihg.com/holidayinn/hotels/us/en/amsterdam/amshi/hoteldetail", "text": TEXT}]
LEVEL = lambda *keys: [{"key": k, "label": k, "level": "strong"} for k in keys]      # noqa: E731
INTENTS = LEVEL("meetings", "business", "spa", "family", "food", "city_break", "airport")
FEATS = LEVEL("meeting_rooms", "spa", "pool", "family", "restaurant", "ev")


def build(classes):
    prof = ai_niche.profile(HOTEL, CITY, [], None, PAGES, FEATS, INTENTS, domain="ihg.com", classes=classes)
    return prof, ai_niche.questions(prof, HOTEL, CITY, n=8)


print("1. the hotel's kind decides which markets are asked about")
prof, qs = build(["business"])
keys = [a["key"] for a in prof["audiences"]]
text = " | ".join(q["text"] for q in qs)
check("an airport 18.6 km away is not an airport market, and the reason is recorded", "airport" not in keys and "Schiphol" not in text and any(s["key"] == "airport" and "18.6 km" in s["why"] for s in prof["skipped"]), str(prof["skipped"]))
check("a pool and a gym do not make a spa market", "wellness" not in keys and "spa and a pool" not in text and any(s["key"] == "wellness" for s in prof["skipped"]))
check("a family room does not make a family market", "family" not in keys and "young children" not in text)
check("mentioning 'the city' does not make a city-centre break 'close to the main sights'", "city_break" not in keys and "main sights" not in text and any(s["key"] == "city_break" for s in prof["skipped"]))
check("a restaurant does not make a dining destination", "food" not in keys and "good restaurant" not in text)
check("meetings are asked, because the hotel is a business hotel with strong meeting evidence", "meetings" in keys and "meeting rooms" in text)
check("EV charging, a fact the pages state strongly, is still asked", "ev" in keys)
check("the stadium the pages put five minutes away becomes a question, with the evidence", prof["venue"] and "ArenA" in prof["venue"]["name"] and any(q["id"] == "niche_venue" and "event at" in q["text"] and "5 minute" in q["why"] for q in qs), str(prof["venue"]))
check("no question names the hotel", all("arena towers" not in q["text"].lower() for q in qs))
check("every question still says why it was asked", all(q["why"] for q in qs))

print("2. the same pages for a hotel that IS those things")
spa_prof, spa_qs = build(["spa_hotel", "business", "city_centre"])
spa_keys = [a["key"] for a in spa_prof["audiences"]]
check("with the evidence of a spa hotel the spa and city-break markets are asked", "wellness" in spa_keys and "city_break" in spa_keys)
near = ai_niche.profile(HOTEL, CITY, [], {"airports": [{"name": "Schiphol", "km": 9.0}], "attractions": []}, [{"url": "u", "text": TEXT.replace("18.6 km", "9 km")}], FEATS, INTENTS, classes=["airport"])
check("an airport within 15 km is an airport market", "airport" in [a["key"] for a in near["audiences"]])
old = ai_niche.profile(HOTEL, CITY, [], None, PAGES, FEATS, INTENTS, domain="ihg.com", classes=None)
check("when the hotel's kind is unknown the old behaviour stands (no class gate), but the airport rule still applies", "airport" not in [a["key"] for a in old["audiences"]] and "wellness" in [a["key"] for a in old["audiences"]])
stated = ai_niche.profile(HOTEL, CITY, [], None, PAGES, FEATS, INTENTS, hint={"audiences": ["wellness"]}, classes=["business"])
check("an audience the person says the hotel wants is asked even when the pages do not show it", "wellness" in [a["key"] for a in stated["audiences"]])

print("3. the person's own prompts")
raw = "1. Which hotels near the Johan Cruijff ArenA are good for a concert weekend?\n\n- Best 4-star hotel in Amsterdam Zuidoost with free parking?\nhi\nWhich hotels near the Johan Cruijff ArenA are good for a concert weekend?\n" + "x" * 300 + "\nIs Holiday Inn Arena Towers good for families?\nline5 is long enough\nline6 is long enough"
cl = ai_niche.clean_prompts(raw)
check("prompts are trimmed, numbered bullets removed, too short, too long and repeated ones dropped, at most five", cl == ["Which hotels near the Johan Cruijff ArenA are good for a concert weekend?", "Best 4-star hotel in Amsterdam Zuidoost with free parking?",
                                                                                                                  "Is Holiday Inn Arena Towers good for families?", "line5 is long enough", "line6 is long enough"], cl)
check("control characters are removed", ai_niche.clean_prompts(["Which hotels\x00 near\x1b the arena?"]) == ["Which hotels near the arena?"])
check("a list works as well as text", ai_niche.clean_prompts(["Best hotel near the arena?", "  "]) == ["Best hotel near the arena?"])
cq = ai_niche.custom_questions(raw)
check("they become 'custom' questions, labelled as the person's, with the text untouched", [q["kind"] for q in cq] == ["custom"] * 5 and cq[0]["text"] == cl[0] and "Entered by the person" in cq[0]["why"])


class Fake:
    def __init__(self):
        self.messages, self.calls = self, []

    def create(self, **kw):
        self.calls.append(kw)
        q = kw["messages"][0]["content"]
        txt = "1. Holiday Inn Amsterdam Arena Towers is a good choice. 2. Other Hotel." if "Arena Towers" in q else "1. Other Hotel. 2. Another Hotel."
        return NS(content=[NS(type="text", text=txt, citations=None)], stop_reason="end_turn", usage=NS(input_tokens=500, output_tokens=80, server_tool_use=NS(web_search_requests=1)))


fk = Fake()
res = ai_sample.run_extra(HOTEL, CITY, ai_niche.custom_questions(["Is Holiday Inn Arena Towers good for families?", "Which hotels near the arena suit a concert weekend?"]), client=fk, model="claude-haiku-5-5")
items = res["items"]
check("each custom prompt is asked as written, twice, and sent without rewording", len(items) == 4 and {c["messages"][0]["content"] for c in fk.calls} == {"Is Holiday Inn Arena Towers good for families?", "Which hotels near the arena suit a concert weekend?"})
named = [i for i in items if i["text"].startswith("Is Holiday")]
check("a prompt that names the hotel is flagged as such", all(i["names_hotel"] for i in named) and not any(i["names_hotel"] for i in items if i not in named))
sm = ai_sample.summarise(items)
check("custom answers are counted on their own and never in the town-wide or niche counts", sm["custom_asked"] == 4 and sm["custom_named"] == 2 and sm["generic_asked"] == 0 and sm["niche_asked"] == 0, str(sm))
ai = {"status": "ok", "model": "claude-haiku-5-5", "items": items, "summary": sm, "run_at": "2026-10-20"}
log = ai_sample.test_log(ai)
check("the test log marks the named prompt as branded, so it is not counted as the hotel being volunteered", sum(1 for r in log["rows"] if r["branded"]) == 2 and log["summary"]["appeared"] == 0, str(log["summary"]))

print("4. the form and the report")
html = open("web/templates/index.html", encoding="utf8").read()
check("the start page has the prompts box inside the form, before the optional sections", 'name="prompts"' in html and html.index('name="prompts"') < html.index("Your own reviews"))
js = open("web/static/app.js", encoding="utf8").read()
check("both submit paths send the prompts", js.count("prompts") >= 2)
import report_view  # noqa: F401
import ui_consult
check("the report has a card for them", hasattr(ui_consult, "custom_prompts_card"))
import scoring
check("the observed-visibility score ignores custom prompts", scoring.score_ai_sample({"status": "ok", "items": items, "summary": sm}) is None)

print("5. a hotel whose structured data holds its address as a record no longer crashes the report")
import textutil
check("a PostalAddress record, a list of them and a plain string all become one line of text", textutil.address_text({"@type": "PostalAddress", "streetAddress": "605 Avenue du General de Gaulle", "addressLocality": "Mandelieu", "postalCode": "06210", "addressCountry": {"name": "France"}})
      == "605 Avenue du General de Gaulle, Mandelieu, 06210, France" and textutil.address_text([{"addressLocality": "Cannes"}]) == "Cannes" and textutil.address_text("  1 High St ") == "1 High St" and textutil.address_text(None) == "")
import ui_intel, report_pdf
src = open("ui_intel.py", encoding="utf8").read() + open("report_pdf.py", encoding="utf8").read()
check("the identity table in the web report and the PDF read the address through that helper", src.count("textutil.address_text(s.get(\"place\"))") == 2)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
