"""
Stripe Checkout for the Presence Pro marketing site (presencepro.co.uk).

A Payment Link cannot be opened with a quantity already chosen, so a visitor who picked "5 hotels" on the pricing page had to pick again on
Stripe's page. This makes the session on the server instead: POST /api/checkout {plan, interval, quantity} -> {url}, and the site sends the
visitor to that address, where Stripe already shows the right number of hotels (they can still change it, within the plan's limits).

  - Prices are fixed on the server (the Stripe price ids in marketing/src/site.json), never taken from the browser, so a visitor cannot change what a hotel costs.
  - The quantity is checked against the plan (Portfolio has a minimum of five).
  - The secret key is the STRIPE_SECRET_KEY setting on the host. Use a Stripe *restricted* key that can only write Checkout Sessions.
  - If the key or a price id is missing, the route says so and the site falls back to the ordinary Payment Link, so nothing breaks.
  - Nothing about the visitor is stored here; Stripe holds the customer and the payment.
"""

import chat

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"
MAX_HOTELS = 99
SITE = "https://presencepro.co.uk"


class Unavailable(Exception):
    """Checkout cannot be made right now; the message is safe to show."""


class Invalid(Exception):
    """The request itself is wrong (unknown plan, too few hotels)."""


def plans():
    return {p["id"]: p for p in (chat.site().get("plans") or [])}


def price_id(plan_id, interval):
    prices = ((chat.site().get("stripe") or {}).get("prices") or {}).get(plan_id) or {}
    return prices.get(interval) or ""


def enabled():
    """True when at least one price id is set, so the site knows it can offer this checkout."""
    prices = (chat.site().get("stripe") or {}).get("prices") or {}
    return any(v for d in prices.values() for v in d.values())


def build_params(plan_id, interval, quantity):
    """The form fields for Stripe's Create Checkout Session call, or raises Invalid."""
    plan = plans().get(plan_id)
    if not plan:
        raise Invalid("Unknown plan.")
    interval = interval if interval in ("monthly", "annual") else "monthly"
    if interval == "annual" and not (plan.get("annual") and price_id(plan_id, "annual")):
        interval = "monthly"
    pid = price_id(plan_id, interval)
    if not pid:
        raise Unavailable("This plan cannot be bought online yet.")
    lo = int(plan.get("min_hotels") or 1)
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        raise Invalid("Please choose a number of hotels.")
    if qty < lo or qty > MAX_HOTELS:
        raise Invalid(f"Please choose between {lo} and {MAX_HOTELS} hotels.")
    each = plan["annual"] if interval == "annual" else plan["monthly"]
    period = "year" if interval == "annual" else "month"
    first = "your first hotel" if qty > 1 else "your hotel"
    params = {
        "mode": "subscription",
        "line_items[0][price]": pid,
        "line_items[0][quantity]": str(qty),
        "line_items[0][adjustable_quantity][enabled]": "true",
        "line_items[0][adjustable_quantity][minimum]": str(lo),
        "line_items[0][adjustable_quantity][maximum]": str(MAX_HOTELS),
        "success_url": f"{SITE}/welcome.html",
        "cancel_url": f"{SITE}/pricing.html",
        "billing_address_collection": "auto",
        "custom_text[submit][message]": f"{qty} {'hotel' if qty == 1 else 'hotels'} at £{each:g} each per {period}. You can change the number above. Prices exclude VAT.",
        "subscription_data[metadata][plan]": plan_id,
        "subscription_data[metadata][hotels]": str(qty),
        "metadata[plan]": plan_id,
        "metadata[hotels]": str(qty),
    }
    for i, (key, label) in enumerate((("hotel_name", f"Name of {first}"), ("hotel_city", f"Town or city of {first}"), ("hotel_website", f"Website of {first}"))):
        params[f"custom_fields[{i}][key]"] = key
        params[f"custom_fields[{i}][label][type]"] = "custom"
        params[f"custom_fields[{i}][label][custom]"] = label
        params[f"custom_fields[{i}][type]"] = "text"
    return params


def create(plan_id, interval, quantity, secret, post=None):
    """Make the Checkout Session and return its address. `post` is for tests."""
    if not secret:
        raise Unavailable("Online checkout is not switched on yet.")
    params = build_params(plan_id, interval, quantity)
    if post is None:
        import requests
        post = requests.post
    try:
        resp = post(STRIPE_URL, data=params, headers={"Authorization": f"Bearer {secret}"}, timeout=20)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - nothing from the error is shown to the visitor
        raise Unavailable("Checkout could not be opened just now.") from exc
    url = data.get("url") if isinstance(data, dict) else None
    if not getattr(resp, "ok", False) or not url:
        raise Unavailable("Checkout could not be opened just now.")
    return url
