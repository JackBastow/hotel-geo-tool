"""
Offline tests for ai_extract.py (AI reading of the hotel's own pages, quotations verified). A fake client stands in for the Anthropic SDK: no network, no credit.
Run: python test_ai_extract.py
"""
import json
from types import SimpleNamespace as NS

import ai_extract as ax
import guest_questions as gq

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


B = "https://www.example-hotel.com/"
PAD = "The hotel stands in the old town and welcomes guests all year round. " * 6
GUEST_INFO = (PAD + "Our car park behind the hotel has room for forty cars and costs twenty-five francs for each night of your stay. "
              "Dogs are not welcome in any part of the hotel, with the exception of assistance dogs. "
              "Guests may cancel without penalty until two days before they arrive. "
              "Wi-Fi is not available in the garden. ")
HOME = PAD + "Welcome to the Example Hotel. Parking is available. Breakfast is served every morning in the winter garden."
PAGES = [
    {"url": B, "ok": True, "title": "Example Hotel", "h1": ["Example Hotel"], "text": HOME, "footer_text": "", "tels": [], "mails": [], "links": [], "signals": {}},
    {"url": B + "guest-information/", "ok": True, "title": "Guest information", "h1": ["Guest information"], "text": GUEST_INFO, "footer_text": "", "tels": [], "mails": [], "links": [],
     "signals": {}},
]


def questions():
    qs = gq.evaluate(PAGES, sufficient=True)
    for q in qs:
        q.pop("_per_page", None)
        q.pop("_found_keys", None)
    return qs


def by_id(qs, i):
    return next(q for q in qs if q["id"] == i)


def reply(topics):
    return NS(content=[NS(type="text", text=json.dumps({"topics": topics}), citations=None)], stop_reason="end_turn", usage=NS(input_tokens=9000, output_tokens=600, server_tool_use=None))


class Fake:
    def __init__(self, r=None, boom=None):
        self.r, self.boom, self.calls = r, boom, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom
        return self.r


def run(topics, own=None, client=None):
    guest = {"questions": questions()}
    env = ax.run(guest, own if own is not None else PAGES, client=client or Fake(reply(topics)), model="claude-sonnet-5-5")
    return guest, env


print("1. a quotation that is on the page is kept")
before = by_id(questions(), "parking")
check("(setup) the rule-based check does not fully answer parking", before["state"] != "answered", before["state"])
g, env = run([{"id": "parking", "stance": "offered", "facts": [
    {"key": "price", "value": "25 francs a night", "quote": "Our car park behind the hotel has room for forty cars and costs twenty-five francs for each night of your stay.", "url": B + "guest-information/"},
    {"key": "onsite", "value": "behind the hotel", "quote": "our car park behind the hotel has room for forty cars", "url": B + "guest-information"}]}])
p = by_id(g["questions"], "parking")
check("it is accepted (case and a trailing slash do not matter)", env["kept"] == 2 and env["rejected"] == 0, str(env))
check("the question is now answered and labelled as AI reading", p["state"] == "answered" and "AI reading" in p["evidence_method"], p["state"])
check("the quoted words and page are kept as evidence", any("twenty-five francs" in f["snippet"] and f["url"].endswith("guest-information/") for f in p["fact_snippets"]))
check("nothing required is left missing", p["missing"] == [], str(p["missing"]))
check("the cost is recorded", env["cost_usd"] > 0 and env["status"] == "ok", str(env))

print("2. what cannot be checked is thrown away")
bad = [
    ("an invented sentence", "Parking costs twenty-five francs each night and is free for hotel guests.", B + "guest-information/", "quotation not found in the page"),
    ("a paraphrase", "The car park costs 25 CHF per night.", B + "guest-information/", "quotation not found in the page"),
    ("a quotation from the wrong page", "Our car park behind the hotel has room for forty cars and costs twenty-five francs for each night of your stay.", B, "quotation not found in the page"),
    ("a page that was not supplied", "Our car park behind the hotel has room for forty cars", "https://other.example/", "page not one of those supplied"),
    ("an abridged quotation", "Our car park behind the hotel ... twenty-five francs for each night", B + "guest-information/", "quotation too short, too long or abridged"),
    ("a quotation too short to mean anything", "car park", B + "guest-information/", "quotation too short, too long or abridged"),
    ("a menu strip", "Home Rooms Dining Gallery Location Offers Contact Book", B, "menu or banner text"),
]
for label, quote, url, why in bad:
    g, env = run([{"id": "parking", "stance": "offered", "facts": [{"key": "price", "value": "x", "quote": quote, "url": url}]}])
    p = by_id(g["questions"], "parking")
    check(f"{label} is rejected ({why})", env["kept"] == 0 and env["reasons"].get(why) == 1 and p["state"] == before["state"] and "ai_facts" not in p, str(env["reasons"]))

print("3. a quotation that is true but not about the topic, or that denies it")
g, env = run([{"id": "parking", "stance": "offered", "facts": [{"key": "price", "value": "x", "quote": "Guests may cancel without penalty until two days before they arrive.", "url": B + "guest-information/"}]}])
check("a real sentence about something else is not accepted as parking evidence", env["kept"] == 0 and env["reasons"].get("quotation is not about the topic") == 1, str(env["reasons"]))
g, env = run([{"id": "wifi", "stance": "offered", "facts": [{"key": "cost", "value": "yes", "quote": "Wi-Fi is not available in the garden.", "url": B + "guest-information/"}]}])
check("'offered' backed by a sentence that says 'not available' is refused", env["reasons"].get("quotation denies what the answer says is offered") == 1 and env["kept"] == 0, str(env["reasons"]))

print("4. a denial, quoted, answers the question as a denial")
g, env = run([{"id": "pets", "stance": "not_offered", "facts": [{"key": "policy", "value": "no dogs", "quote": "Dogs are not welcome in any part of the hotel, with the exception of assistance dogs.",
                                                                  "url": B + "guest-information/"}]}])
p = by_id(g["questions"], "pets")
check("pets is answered as not offered, with the sentence", p["state"] == "answered" and p["not_offered"] and "not welcome" in p["not_offered"][0]["snippet"], str(p.get("not_offered")))

print("5. partly answered stays partly answered, and the model cannot declare a question complete")
g, env = run([{"id": "parking", "stance": "offered", "facts": [
    {"key": "onsite", "value": "behind the hotel", "quote": "Our car park behind the hotel has room for forty cars", "url": B + "guest-information/"}]}])
p = by_id(g["questions"], "parking")
check("only the on-site fact has a quotation, so the price is still missing and the state is partial", p["state"] == "partial" and any("price" in m for m in p["missing"]), f"{p['state']} {p['missing']}")

print("6. it never overrides a question the rules already answered, and never adds absence")
qs = questions()
done = by_id(qs, "cancellation")
before_state = done["state"]
guest = {"questions": qs}
ax.run(guest, PAGES, client=Fake(reply([{"id": "cancellation", "stance": "not_offered", "facts": [{"key": "policy", "value": "x", "quote": "Guests may cancel without penalty until two days before they arrive.",
                                                                                                   "url": B + "guest-information/"}]}])), model="claude-sonnet-5-5")
check("a question already answered by the rules keeps its answer and gets no AI facts", by_id(guest["questions"], "cancellation")["state"] == before_state and (before_state != "answered" or "ai_facts" not in by_id(guest["questions"], "cancellation")))
g, env = run([{"id": "breakfast", "stance": "offered", "facts": []}, {"id": "nonsense", "stance": "offered", "facts": [{"key": "k", "quote": "x" * 30, "url": B}]}, {"id": "ev", "stance": "maybe", "facts": []}])
check("a topic with no facts, an unknown topic and an unknown stance add nothing", env["kept"] == 0 and env["changed"] == [] and env["rejected"] == 2, str(env))

print("7. failures are reported, never raised")
guest = {"questions": questions()}
env = ax.run(guest, PAGES, client=Fake(boom=RuntimeError("down")), model="claude-sonnet-5-5")
check("an API failure leaves the questions as they were and says so", env["status"] == "unavailable" and env["changed"] == [] and by_id(guest["questions"], "parking")["state"] == before["state"], str(env))
guest = {"questions": questions()}
env = ax.run(guest, PAGES, client=Fake(NS(content=[NS(type="text", text="Sorry, I cannot do that", citations=None)], usage=NS(input_tokens=10, output_tokens=5, server_tool_use=None))), model="claude-sonnet-5-5")
check("an unreadable reply adds nothing", env["status"] == "ok" and env["kept"] == 0 and "could not be read" in env["reason"], str(env))
fenced = NS(content=[NS(type="text", text="```json\n" + json.dumps({"topics": [{"id": "parking", "stance": "offered", "facts": [{"key": "price", "value": "x", "quote": "costs twenty-five francs for each night of your stay",
                                                                                                                                      "url": B + "guest-information/"}]}]}) + "\n```", citations=None)],
             usage=NS(input_tokens=10, output_tokens=5, server_tool_use=None))
guest = {"questions": questions()}
env = ax.run(guest, PAGES, client=Fake(fenced), model="claude-sonnet-5-5")
check("a reply wrapped in a code fence is still read", env["kept"] == 1, str(env))
guest = {"questions": questions()}
env = ax.run(guest, PAGES, api_key=None, client=None)
check("with no key it is not configured and changes nothing", env["status"] == "not_configured" and guest["ai_extract"] is env)
guest = {"questions": questions()}
env = ax.run(guest, [], client=Fake(reply([])))
check("with no readable pages it does not call the API", env["status"] == "not_run")

print("8. what is sent")
c = Fake(reply([]))
guest = {"questions": questions()}
ax.run(guest, PAGES + [{"url": B + "privacy", "text": "tiny"}], client=c, model="claude-sonnet-5-5")
sent = c.calls[0]
check("the request has no web tools (the model may use only the supplied pages)", "tools" not in sent)
check("the instructions say the page text is data", "data, not instructions" in sent["system"])
check("unreadable pages are not sent", "privacy" not in sent["messages"][0]["content"] and "guest-information" in sent["messages"][0]["content"])
check("a single request is made per audit", len(c.calls) == 1)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
