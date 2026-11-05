"""
Offline tests for the marketing site's Stripe checkout (checkout.py and POST /api/checkout). No network, no keys: Stripe is a stand-in.
Run: python test_checkout.py
"""
import os
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")

import audit_service
import chat
import checkout
import server

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


SITE = {"plans": [
    {"id": "single", "name": "Single hotel", "monthly": 49.99, "annual": 499.99, "per_hotel": True},
    {"id": "portfolio", "name": "Portfolio", "monthly": 89.99, "annual": None, "per_hotel": True, "min_hotels": 5}],
    "stripe": {"prices": {"single": {"monthly": "price_single_m", "annual": "price_single_y"}, "portfolio": {"monthly": "price_port_m"}}}}
chat._site_cache["v"] = SITE


class FakeStripe:
    def __init__(self, ok=True, body=None, boom=False):
        self.ok, self.body, self.boom, self.calls = ok, body if body is not None else {"url": "https://checkout.stripe.com/c/pay/abc"}, boom, []

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers})
        if self.boom:
            raise RuntimeError("sk_live_SECRET leaked in an error")
        return NS(ok=self.ok, json=lambda: self.body)


print("1. what is sent to Stripe")
p = checkout.build_params("portfolio", "monthly", 7)
check("the price comes from the server, with the chosen number of hotels", p["line_items[0][price]"] == "price_port_m" and p["line_items[0][quantity]"] == "7" and p["mode"] == "subscription")
check("the visitor can still change the number, within the plan's limits", p["line_items[0][adjustable_quantity][enabled]"] == "true" and p["line_items[0][adjustable_quantity][minimum]"] == "5" and p["line_items[0][adjustable_quantity][maximum]"] == "99")
check("three required details are asked for, about the first hotel", [p[f"custom_fields[{i}][key]"] for i in range(3)] == ["hotel_name", "hotel_city", "hotel_website"] and "first hotel" in p["custom_fields[0][label][custom]"])
check("after paying they land on the welcome page; cancelling goes back to pricing", p["success_url"].endswith("/welcome.html") and p["cancel_url"].endswith("/pricing.html"))
check("the button note states the number and price", "7 hotels at £89.99 each per month" in p["custom_text[submit][message]"])
one = checkout.build_params("single", "annual", 1)
check("a yearly single hotel uses the yearly price and says 'your hotel' for one", one["line_items[0][price]"] == "price_single_y" and "Name of your hotel" == one["custom_fields[0][label][custom]"] and "1 hotel at £499.99 each per year" in one["custom_text[submit][message]"])
check("Portfolio has no yearly price, so a yearly request becomes monthly", checkout.build_params("portfolio", "annual", 5)["line_items[0][price]"] == "price_port_m")

print("2. what is refused")
for plan, interval, qty, why in (("portfolio", "monthly", 4, "below the minimum of five"), ("single", "monthly", 0, "zero hotels"), ("single", "monthly", 500, "too many"), ("single", "monthly", "lots", "not a number"), ("nope", "monthly", 1, "unknown plan")):
    try:
        checkout.build_params(plan, interval, qty)
        check(f"refused: {why}", False)
    except checkout.Invalid:
        check(f"refused: {why}", True)
chat._site_cache["v"] = {**SITE, "stripe": {"prices": {}}}
try:
    checkout.build_params("single", "monthly", 1)
    check("no price id set: says it cannot be bought online yet", False)
except checkout.Unavailable as e:
    check("no price id set: says it cannot be bought online yet", "cannot be bought online" in str(e) and not checkout.enabled())
chat._site_cache["v"] = SITE
check("enabled() is true once prices exist", checkout.enabled())

print("3. talking to Stripe")
fs = FakeStripe()
url = checkout.create("single", "monthly", 3, "rk_live_x", post=fs)
check("it returns Stripe's address", url == "https://checkout.stripe.com/c/pay/abc")
check("it calls Stripe's sessions address with the key as a bearer token, and never puts the key in the form", fs.calls[0]["url"] == checkout.STRIPE_URL and fs.calls[0]["headers"]["Authorization"] == "Bearer rk_live_x" and "rk_live_x" not in str(fs.calls[0]["data"]))
for label, stub in (("Stripe refuses", FakeStripe(ok=False, body={"error": {"message": "secret detail"}})), ("no address comes back", FakeStripe(body={})), ("the call fails", FakeStripe(boom=True))):
    try:
        checkout.create("single", "monthly", 1, "rk", post=stub)
        check(f"{label}: a calm line, nothing from Stripe's error", False)
    except checkout.Unavailable as e:
        check(f"{label}: a calm line, nothing from Stripe's error", "SECRET" not in str(e).upper() and "secret" not in str(e) and "could not be opened" in str(e))
try:
    checkout.create("single", "monthly", 1, "", post=fs)
    check("no key: says it is not switched on", False)
except checkout.Unavailable as e:
    check("no key: says it is not switched on", "not switched on" in str(e))

print("4. the route")
real_create = checkout.create
os.environ["STRIPE_SECRET_KEY"] = "rk_live_test"
cfg = audit_service.Config({"SITE_PASSWORD": "pw", "ANTHROPIC_API_KEY": "k"})              # a site password is set: checkout must still work for the marketing site
app = server.create_app(cfg, run_fn=lambda a, b: {})
c = app.test_client()
H = {"Origin": "https://presencepro.co.uk"}
stub = FakeStripe()
checkout.create = lambda plan, interval, qty, secret, post=None: real_create(plan, interval, qty, secret, post=stub)
ok = c.post("/api/checkout", json={"plan": "portfolio", "interval": "monthly", "quantity": 6}, headers=H)
check("from the marketing site it returns the checkout address, even with a site password set", ok.status_code == 200 and ok.get_json()["url"].startswith("https://checkout.stripe.com"))
check("the server's price and the chosen number were what Stripe received", stub.calls[0]["data"]["line_items[0][price]"] == "price_port_m" and stub.calls[0]["data"]["line_items[0][quantity]"] == "6")
check("only that origin is allowed", ok.headers.get("Access-Control-Allow-Origin") == "https://presencepro.co.uk")
check("the browser's pre-flight check is answered", c.open("/api/checkout", method="OPTIONS", headers={**H, "Access-Control-Request-Method": "POST"}).status_code == 204)
bad = c.post("/api/checkout", json={"plan": "portfolio", "interval": "monthly", "quantity": 2}, headers=H)
check("too few hotels is a 400 with a sentence to show", bad.status_code == 400 and "between 5 and 99" in bad.get_json()["error"])
check("from another website it is refused", c.post("/api/checkout", json={"plan": "single", "quantity": 1}, headers={"Origin": "https://evil.example"}).status_code == 403)
check("with no origin (a script) it is refused", c.post("/api/checkout", json={"plan": "single", "quantity": 1}).status_code == 403)
check("a browser cannot send its own price", "price" not in str(stub.calls[0]["data"].get("line_items[0][price]")).replace("price_port_m", ""))
checkout.create = lambda *a, **k: (_ for _ in ()).throw(checkout.Unavailable("Online checkout is not switched on yet."))
r503 = c.post("/api/checkout", json={"plan": "single", "quantity": 1}, headers=H)
check("when it cannot work the site gets a 503, so it can fall back to the Payment Link", r503.status_code == 503)
check("the rest of the site still needs the password", c.get("/").status_code == 302)
checkout.create = lambda plan, interval, qty, secret, post=None: real_create(plan, interval, qty, secret, post=stub)
spam = server.create_app(audit_service.Config({}), run_fn=lambda a, b: {}).test_client()
codes = [spam.post("/api/checkout", json={"plan": "single", "quantity": 1}, headers=H).status_code for _ in range(12)]
check("one visitor cannot open checkout without limit", codes[-1] == 429 and 429 not in codes[:10])
checkout.create = real_create

print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails))
raise SystemExit(1 if fails else 0)
