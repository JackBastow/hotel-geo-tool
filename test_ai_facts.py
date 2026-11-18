"""
The fact-check of what the AI assistant says about the hotel (ai_facts.py) and the actions it makes, with a fake model. Offline.
Run: python test_ai_facts.py
"""
import json
import sys

import advice
import ai_facts

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


H, C = "Brooklands Hotel", "Weybridge"
ANSWER = ("Here are some options in Weybridge:\n\n"
          "1. **Oatlands Park Hotel** - a historic hotel with a big garden and free parking.\n"
          "2. **Brooklands Hotel** - a modern 3-star hotel next to Mercedes-Benz World. There is no swimming pool, and parking is not available on site. It has a spa.\n"
          "3. **The Runnymede** - on the Thames with an outdoor pool.\n")
items = [
    {"id": "a1", "kind": "niche", "text": "Hotels near Mercedes-Benz World?", "answer": ANSWER, "mentioned": True},
    {"id": "a2", "kind": "niche", "text": "Spa hotels in Surrey?", "answer": "Try Pennyhill Park or the Runnymede, both with spas.", "mentioned": False},
    {"id": "a3", "kind": "direct", "text": "Tell me about Brooklands Hotel", "answer": "Brooklands Hotel is closed for refurbishment until spring. It used to have a restaurant.", "mentioned": True},
]

print("1. the passage about the hotel")
p = ai_facts.passage(ANSWER, H)
check("only the hotel's own list entry is taken, not the rivals'", "3-star" in p and "Oatlands" not in p and "Runnymede" not in p, p)
snips = ai_facts.passages(items, H)
check("answers that do not name the hotel are skipped; a direct question's whole answer is used, first", [s["text"][:20] for s in snips] == ["Brooklands Hotel is ", p[:20]], snips)


class Fake:
    """Returns a fixed reply; one claim is invented (its quote is not in the passage) and must be dropped."""
    def __init__(self, claims):
        self.claims = claims
        self.messages = self

    def create(self, **kw):
        self.prompt = kw["messages"][0]["content"]
        txt = json.dumps({"claims": self.claims})
        return type("R", (), {"content": [type("B", (), {"type": "text", "text": txt})()], "usage": type("U", (), {"input_tokens": 1000, "output_tokens": 200})()})()


claims = [
    {"passage": "P2", "topic": "pool", "stance": "lacks", "value": "", "quote": "There is no swimming pool"},
    {"passage": "P2", "topic": "parking", "stance": "lacks", "value": "", "quote": "parking is not available on site"},
    {"passage": "P2", "topic": "spa", "stance": "has", "value": "", "quote": "It has a spa"},
    {"passage": "P2", "topic": "stars", "stance": "value", "value": "3", "quote": "a modern 3-star hotel"},
    {"passage": "P1", "topic": "status", "stance": "value", "value": "refurbishment", "quote": "closed for refurbishment until spring"},
    {"passage": "P2", "topic": "gym", "stance": "has", "value": "", "quote": "a large gym with a personal trainer"},            # invented: not in the passage
    {"passage": "P2", "topic": "helipad", "stance": "has", "value": "", "quote": "It has a spa"},                              # not a topic
]
fake = Fake(claims)
got, _u = ai_facts.extract(fake, "m", snips, H, C)
check("a claim whose words are not in the answer is dropped, and so is an unknown topic", {c["topic"] for c in got} == {"pool", "parking", "spa", "stars", "status"}, got)
check("the model is told to describe the target hotel only", "THE TARGET HOTEL ONLY" in fake.prompt)

print("2. compared with the website")
pages = [{"url": "https://www.brooklands.example/", "text": "Brooklands Hotel, Weybridge. Free on-site parking for all guests. Our indoor swimming pool is open daily. Free parking with EV chargers. Parking is free.", "title": "Home"},
         {"url": "https://www.brooklands.example/leisure", "text": "Leisure: the swimming pool and gym. Swimming pool open 7am to 10pm. Book the swimming pool.", "title": "Leisure"},
         {"url": "https://www.brooklands.example/parking", "text": "Parking: free parking on site. Car parking for 120 cars.", "title": "Parking"}]
res = ai_facts.run({"items": items}, H, C, pages, "https://www.brooklands.example/", site_stars=4.0, client=fake, model="claude-haiku-5-5")
by = {r["topic"]: r for r in res["rows"]}
check("'no pool' when the website states a pool is called wrong", by.get("pool", {}).get("status") == "differs", res["rows"])
check("'no parking' when the website states parking is called wrong", by.get("parking", {}).get("status") == "differs")
check("'has a spa' that the website never mentions is a thing to check, not called wrong", by.get("spa", {}).get("status") == "check")
check("3-star against the website's 4-star is called wrong", by.get("stars", {}).get("status") == "differs")
check("'closed for refurbishment' is always flagged, first among the checks", by.get("status", {}).get("status") == "check" and [r["topic"] for r in res["rows"] if r["status"] == "check"][0] == "status")
check("wrong ones come before ones to check", [r["status"] for r in res["rows"]] == sorted([r["status"] for r in res["rows"]], key=lambda s: {"differs": 0, "check": 1}[s]))
check("the result keeps the assistant's own words and says how much was looked at", by["pool"]["says"] == "There is no swimming pool" and res["passages"] == 2 and res["status"] == "ok" and res["cost_usd"] > 0)
none = ai_facts.compare([{"topic": "pool", "stance": "has", "value": "", "quote": "x", "passage": "P1"}], {})
check("with no website pages read nothing is judged", none["rows"] == [] and none["unjudged"] == 1)

print("3. the actions")
recs = advice._from_facts_check(res)
ids = [r["id"] for r in recs]
check("one action per wrong or doubtful fact, each with its own lasting id", ids and len(ids) == len(set(ids)) and "AF-pool" in ids and "AF-status" in ids, ids)
check("they are data-accuracy actions, the wrong ones high priority", all(advice.track_of(r) == "accuracy" for r in recs) and next(r for r in recs if r["id"] == "AF-pool")["priority"] == "high")
check("the closed claim is high priority too", next(r for r in recs if r["id"] == "AF-status")["priority"] == "high")
check("an audit with nothing to report makes no action, and a failed check does not break the audit",
      advice._from_facts_check({"rows": []}) == [] and advice._from_facts_check(None) == [] and ai_facts.run({"items": items}, H, C, pages, "", client=object())["status"] == "unavailable")
check("an answer that says nothing about the hotel needs no model at all", ai_facts.run({"items": [items[1]]}, H, C, pages, "")["status"] == "none")

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
