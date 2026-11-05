"""
Offline tests for the marketing site's chat assistant (chat.py and POST /api/chat). No network, no keys: the model is a stand-in.
Run: python test_chat.py
"""
import os
import tempfile
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")

import audit_service
import chat
import server
import store

tmp = tempfile.mkdtemp()
store.RUNS_DIR, store.QUOTA_FILE = tmp, os.path.join(tmp, "quota.json")      # counters go to a throwaway folder

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


class FakeClient:
    def __init__(self, text="Presence Pro is a monthly report for hotels."):
        self.text, self.calls = text, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(text=self.text)], usage=NS(input_tokens=900, output_tokens=60))


print("1. the conversation is made safe")
check("a plain question is kept", chat.clean_messages([{"role": "user", "content": "How much is it?"}]) == [{"role": "user", "content": "How much is it?"}])
check("not a list, wrong role, or non-text is refused", chat.clean_messages("hi") is None and chat.clean_messages([{"role": "system", "content": "x"}]) is None and chat.clean_messages([{"role": "user", "content": {"a": 1}}]) is None)
check("it must end on a user turn", chat.clean_messages([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]) is None)
check("an empty message is refused", chat.clean_messages([{"role": "user", "content": "   "}]) is None)
long = chat.clean_messages([{"role": "user", "content": "x" * 5000}])
check("a long message is cut", len(long[0]["content"]) == chat.MAX_USER_CHARS)
many = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(40)] + [{"role": "user", "content": "last"}]
cm = chat.clean_messages(many)
check("only the last few turns are kept, starting on a user turn, ending on the new question", len(cm) <= chat.MAX_TURNS * 2 and cm[0]["role"] == "user" and cm[-1]["content"] == "last")
check("two user turns in a row are merged (the API wants alternating turns)", [m["role"] for m in chat.clean_messages([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])] == ["user"])

print("2. the fact sheet and the rules")
f = chat.facts()
check("the fact sheet carries the honesty rules", "cannot guarantee" in f and "not assessed" in f and "Booking.com" in f)
sj = chat.site()
check("every plan on the website appears with its price", all(p["name"] in f and f"£{p['monthly']:g}" in f for p in sj.get("plans", [])) and bool(sj.get("plans")))
check("the per-hotel drop and the monthly-only plan are stated", "per hotel once there are 11 or more hotels" in f and "yearly billing on request" in f and "£39.99" in f)
check("the instructions treat the visitor's words as data and forbid invention", "data" in chat.SYSTEM and "Never invent" in chat.SYSTEM and "ONLY from the FACT SHEET" in chat.SYSTEM)

print("3. the reply")
fc = FakeClient()
out = chat.reply([{"role": "user", "content": "What do you do?"}], "key", client=fc)
call = fc.calls[0]
check("the model is given the fact sheet, the conversation and a short limit", "FACT SHEET" in call["system"] and call["messages"][-1]["content"] == "What do you do?" and call["max_tokens"] == chat.MAX_TOKENS and "tools" not in call)
check("the reply comes back", out == fc.text)
check("the call and an estimated spend are counted", store.read_quota("chat")["calls"] == 1 and store.read_quota("claude")["calls"] >= 1)
try:
    chat.reply([{"role": "user", "content": "hi"}], "", client=fc)
    check("without a key it says it is not switched on", False)
except chat.Unavailable as e:
    check("without a key it says it is not switched on", "not switched on" in str(e))


class Boom:
    messages = None

    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise RuntimeError("secret-key-sk-123 leaked in the error")


try:
    chat.reply([{"role": "user", "content": "hi"}], "key", client=Boom())
    check("a failing model gives the visitor a calm line", False)
except chat.Unavailable as e:
    check("a failing model gives the visitor a calm line, with nothing from the error in it", "sk-123" not in str(e) and "could not answer" in str(e))
store.SERVICE_CAPS["chat"] = 1
try:
    chat.reply([{"role": "user", "content": "hi"}], "key", client=fc)
    check("at the monthly cap it stops", False)
except chat.Unavailable as e:
    check("at the monthly cap it stops", "limit" in str(e))
store.SERVICE_CAPS["chat"] = 3000

print("4. the limiter")
lim = chat.Limiter(limit=3, window=60)
check("three allowed, the fourth refused, another visitor unaffected", [lim.allow("a", 0), lim.allow("a", 1), lim.allow("a", 2), lim.allow("a", 3), lim.allow("b", 3)] == [True, True, True, False, True])
check("it frees up after the window", lim.allow("a", 100))

print("5. the route")
chat_mod_reply = chat.reply
cfg = audit_service.Config({"ANTHROPIC_API_KEY": "k", "SITE_PASSWORD": "pw"})            # a site password is set: the chat must still answer
app = server.create_app(cfg, run_fn=lambda p, pr: {})
c = app.test_client()
site_origin = {"Origin": "https://presencepro.co.uk"}
chat.reply = lambda msgs, key, client=None: chat_mod_reply(msgs, key, client=FakeClient("Plans start at the price on the pricing page."))
ok = c.post("/api/chat", json={"messages": [{"role": "user", "content": "How much?"}]}, headers=site_origin)
check("from the marketing site it answers, even with a site password set", ok.status_code == 200 and ok.get_json()["reply"].startswith("Plans start"))
check("and allows that origin only", ok.headers.get("Access-Control-Allow-Origin") == "https://presencepro.co.uk")
pre = c.open("/api/chat", method="OPTIONS", headers={**site_origin, "Access-Control-Request-Method": "POST"})
check("the browser's pre-flight check is answered", pre.status_code == 204 and "POST" in pre.headers.get("Access-Control-Allow-Methods", ""))
check("from another website it is refused, with no allow header", c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}]}, headers={"Origin": "https://evil.example"}).status_code == 403
      and "Access-Control-Allow-Origin" not in c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}]}, headers={"Origin": "https://evil.example"}).headers)
check("with no origin at all (a script) it is refused", c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 403)
check("a bad body is a 400", c.post("/api/chat", json={"messages": "hi"}, headers=site_origin).status_code == 400 and c.post("/api/chat", data="nope", headers=site_origin).status_code == 400)
check("the rest of the site still needs the password", c.get("/").status_code == 302)
chat.reply = lambda msgs, key, client=None: (_ for _ in ()).throw(chat.Unavailable("The chat assistant is not switched on yet."))
r503 = c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=site_origin)
check("when it cannot answer the site gets a 503 and a sentence it can show", r503.status_code == 503 and "not switched on" in r503.get_json()["error"])
chat.reply = lambda msgs, key, client=None: chat_mod_reply(msgs, key, client=FakeClient())          # never the real model, whatever the key says
spam = server.create_app(audit_service.Config({"ANTHROPIC_API_KEY": "k"}), run_fn=lambda p, pr: {}).test_client()
codes = [spam.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=site_origin).status_code for _ in range(chat.PER_VISITOR + 2)]
check("one visitor cannot ask without limit", codes[-1] == 429 and 429 not in codes[:chat.PER_VISITOR])

print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails))
raise SystemExit(1 if fails else 0)
