#!/usr/bin/env python3
"""
Builds the Presence Pro marketing site. No dependencies beyond Python 3.

    python marketing/build.py                 build into marketing/public
    python marketing/build.py --dev --serve   build for local use (the chat talks to localhost:8766) and serve it on :8767

Inputs (marketing/src):
    site.json            the one place for the domain, contact address, business details, plans, prices and Stripe links
    partials/layout.html the page frame (head, navigation, footer, scripts)
    pages/*.html         one file per page: a few "key: value" lines between --- marks, then the body
    assets/*             copied as they are (stylesheet, scripts, icon, images)

In a page body, {{ some.key }} is replaced from site.json, plus a few built-in blocks (plan cards and so on).
"""

import datetime as dt
import html
import http.server
import json
import os
import re
import shutil
import socketserver
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "public")


def money(n):
    return f"£{n:,.0f}" if float(n).is_integer() else f"£{n:,.2f}"


def load_site(dev):
    with open(os.path.join(SRC, "site.json"), encoding="utf8") as f:
        site = json.load(f)
    if dev:
        site["app_url"] = "http://localhost:8766"
    site["app_url"] = site["app_url"].rstrip("/")
    if site.get("form_key") and not site.get("form_endpoint"):
        site["form_endpoint"] = "https://api.web3forms.com/submit"        # the access key in site.json is Web3Forms'; Formspree users set form_endpoint instead
    site["chat_url"] = site["app_url"] + "/api/chat"
    return site


def parse_page(path):
    raw = open(path, encoding="utf8").read()
    meta, body = {}, raw
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = raw[m.end():]
    return meta, body


def get(site, dotted):
    cur = site
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def fill(text, site, extra):
    def sub(m):
        key = m.group(1).strip()
        if key in extra:
            return extra[key]
        try:
            return html.escape(str(get(site, key)), quote=True)
        except KeyError:
            raise SystemExit(f"build: unknown {{{{ {key} }}}}")
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub, text)


# ---------------------------------------------------------------- built-in blocks

def feature_list(p):
    return "<ul>" + "".join(f"<li>{html.escape(f)}</li>" for f in p["features"]) + "</ul>"


def save_text(p):
    """What yearly billing saves, worked out from the prices (empty when a plan has no yearly price)."""
    if not p.get("annual"):
        return ""
    saved = p["monthly"] * 12 - p["annual"]
    return f"Save {money(round(saved, 2))} a year (about {round(saved / p['monthly']):g} months free)"


def by_id(site, pid):
    return next(p for p in site["plans"] if p["id"] == pid)


def tier_label(t):
    return f"{t['from']} to {t['to']} hotels"


def tier_rows(p):
    """The portfolio tiers as plain lines."""
    rows = [f'<li><b>{tier_label(t)}</b><span>{money(t["price"])} per hotel a month</span></li>' for t in p["tiers"]]
    rows.append(f'<li><b>{p["tiers"][-1]["to"] + 1} or more hotels</b><span>Custom quotation</span></li>')
    return '<ul class="tiers">' + "".join(rows) + "</ul>"


def calc_box(p, buy_label):
    """The 'how many hotels?' control above a Subscribe button. Portfolio uses its volume tiers, Single Hotel a flat price."""
    lo = p.get("min_hotels", 1)
    hi = p.get("max_hotels", 99)
    tiers = html.escape(json.dumps(p["tiers"])) if p.get("tiers") else ""
    cross = ""
    if p["id"] == "single":
        cross = '<p class="cross" data-from="5" hidden>With 5 or more hotels, <a href="#portfolio">Portfolio</a> costs less per hotel.</p>'
    if p["id"] == "portfolio":
        cross = '<p class="cross">Need 50 or more hotels? <a href="/contact.html?plan=enterprise">Contact us for a quotation</a>.</p>'
    return (f'<div class="calc" data-calc data-min="{lo}" data-max="{hi}" data-pm="{p["monthly"]}" data-pa="{p.get("annual") or ""}" data-tiers="{tiers}">'
            f'<p class="calc-title">How many hotels do you need?</p>'
            f'<div class="stepper"><button type="button" class="step-btn" data-dir="-1" aria-label="Fewer hotels">&minus;</button>'
            f'<input type="number" min="{lo}" max="{hi}" value="{lo}" inputmode="numeric" aria-label="Number of hotels">'
            f'<button type="button" class="step-btn" data-dir="1" aria-label="More hotels">+</button></div>'
            f'<p class="total" aria-live="polite"></p>{cross}</div>')


def plan_cards(site):
    single, port, ent = by_id(site, "single"), by_id(site, "portfolio"), by_id(site, "enterprise")
    sm, sa = money(single["monthly"]), money(single["annual"])
    yearly_note = save_text(single) + ". Billed once a year, paid upfront."
    c1 = (f'<div class="plan rv"><h3>{html.escape(single["name"])}</h3><p class="for">{html.escape(single["for"])}</p>'
          f'<p class="price"><span class="amt" data-m="{sm}" data-a="{sa}">{sm}</span><span class="per" data-m="/month" data-a="/year">/month</span></p>'
          f'<p class="save" data-m="Per hotel. Billed monthly. Cancel any time." data-a="{html.escape(yearly_note)}">Per hotel. Billed monthly. Cancel any time.</p>'
          f'{feature_list(single)}{calc_box(single, "Get Started")}<a class="btn dark" href="/contact.html?plan=single" data-buy="single">Get Started</a></div>')
    low = min(t["price"] for t in port["tiers"])
    c2 = (f'<div class="plan feat rv"><span class="badge">For groups</span><h3>{html.escape(port["name"])}</h3><p class="for">{html.escape(port["for"])}</p>'
          f'<p class="price"><span class="amt">From {money(low)}</span><span class="per">/hotel/month</span></p>'
          f'<p class="save">Monthly billing. Cancel any time.</p>{tier_rows(port)}{feature_list(port)}'
          f'<a class="btn gold" href="#portfolio">Explore Portfolio Pricing</a></div>')
    c3 = (f'<div class="plan rv"><h3>{html.escape(ent["name"])}</h3><p class="for">{html.escape(ent["for"])}</p>'
          f'<p class="price"><span class="amt">Custom</span></p><p class="save">Tailored quotation. Annual contracts available on request.</p>'
          f'{feature_list(ent)}<a class="btn dark" href="/contact.html?plan=enterprise">Contact Us</a></div>')
    return '<div class="plans3">' + c1 + c2 + c3 + "</div>"


def portfolio_section(site):
    """The Portfolio pricing detail: the two tiers, the hotel count, and the Subscribe button."""
    port = by_id(site, "portfolio")
    t1, t2 = port["tiers"]
    return (f'<div class="plan feat wide rv" id="portfolio-buy"><div class="wide-grid"><div>'
            f'<h3>Portfolio pricing</h3><p class="for">One price per hotel, and it falls as your portfolio grows. The tier price applies to every hotel on your account.</p>'
            f'{tier_rows(port)}'
            f'<ul class="rules"><li>Monthly billing only. For an annual portfolio contract, <a href="/contact.html?plan=enterprise">ask for a quotation</a>.</li>'
            f'<li>Portfolio pricing covers the hotels you own or manage. We may ask you to confirm the list, and adjust the plan if it does not match.</li></ul></div>'
            f'<div>{calc_box(port, "Subscribe")}<a class="btn gold" href="/contact.html?plan=portfolio" data-buy="portfolio">Subscribe</a></div></div></div>')


def plan_cards_home(site):
    single, port, ent = by_id(site, "single"), by_id(site, "portfolio"), by_id(site, "enterprise")
    low = min(t["price"] for t in port["tiers"])
    return ('<div class="plans3">'
            f'<div class="plan mini rv"><h3>{html.escape(single["name"])}</h3><p class="for">{html.escape(single["for"])}</p><p class="price"><span class="amt">{money(single["monthly"])}</span><span class="per">/month</span></p></div>'
            f'<div class="plan mini feat rv"><h3>{html.escape(port["name"])}</h3><p class="for">{html.escape(port["for"])}</p><p class="price"><span class="amt">From {money(low)}</span><span class="per">/hotel/month</span></p></div>'
            f'<div class="plan mini rv"><h3>{html.escape(ent["name"])}</h3><p class="for">{html.escape(ent["for"])}</p><p class="price"><span class="amt">Custom</span></p></div></div>')


COMPARE_ROWS = [
    ("Hotels covered", ["One or more", "5 to 49", "50 or more"]),
    ("Monthly report with PDF and the evidence behind every finding", [True, True, True]),
    ("Competitor intelligence and the pages the assistant cited", [True, True, True]),
    ("Change since last month", [True, True, True]),
    ("Your own questions tested, and your review export analysed", [True, True, True]),
    ("Portfolio dashboard: every hotel's score, trends and AI visibility side by side", [False, True, True]),
    ("Ongoing analysis: which hotels need attention, and which are improving", [False, True, True]),
    ("Actions tracked hotel by hotel", [False, True, True]),
    ("A dashboard for each hotel, showing only that hotel", [False, True, True]),
    ("Yearly billing", ["Yes, paid upfront", "Monthly only", "By quotation"]),
    ("Consolidated billing, custom reporting, cross-property benchmarking", [False, False, "Available to discuss"]),
    ("Support", ["Email", "Priority email", "To discuss"]),
]


def plan_compare(site):
    single, port = by_id(site, "single"), by_id(site, "portfolio")
    head = "<tr><th scope='col'>What you get</th>" + "".join(f"<th scope='col'>{html.escape(p['name'])}</th>" for p in site["plans"]) + "</tr>"
    t1, t2 = port["tiers"]
    price_cells = [f"{money(single['monthly'])} a month, or {money(single['annual'])} a year, per hotel",
                   f"{money(t1['price'])} per hotel a month for {tier_label(t1)}; {money(t2['price'])} for {tier_label(t2)}",
                   "Custom quotation"]
    rows_data = [("Price (plus VAT)", price_cells)] + COMPARE_ROWS
    rows = []
    for label, vals in rows_data:
        cells = []
        for v in vals:
            if v is True:
                cells.append("<td><span class='yes' aria-label='Included'>&#10003;</span></td>")
            elif v is False:
                cells.append("<td><span class='no' aria-label='Not included'>&ndash;</span></td>")
            else:
                cells.append(f"<td>{html.escape(v)}</td>")
        rows.append(f"<tr><th scope='row'>{html.escape(label)}</th>{''.join(cells)}</tr>")
    return f"<div class='table-wrap'><table class='compare'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def business_block(site):
    op = site["operator"]
    bits = []
    if op["name"]:
        bits.append(f"Presence Pro is a trading name of {html.escape(op['name'])}.")
    if op["company_number"]:
        bits.append(f"Company number {html.escape(op['company_number'])}.")
    if op["vat_number"]:
        bits.append(f"VAT number {html.escape(op['vat_number'])}.")
    if op["address"]:
        bits.append(f"Address: {html.escape(op['address'])}.")
    return " ".join(bits)


def offers_json(site):
    single, port = by_id(site, "single"), by_id(site, "portfolio")

    def offer(name, price, unit):
        return {"@type": "Offer", "name": name, "price": f"{price:g}", "priceCurrency": "GBP",
                "priceSpecification": {"@type": "UnitPriceSpecification", "price": f"{price:g}", "priceCurrency": "GBP", "unitText": unit}}
    out = [offer("Single Hotel, per hotel per month", single["monthly"], "MONTH"), offer("Single Hotel, per hotel per year", single["annual"], "YEAR")]
    out += [offer(f"Portfolio, {tier_label(t)}, per hotel per month", t["price"], "MONTH") for t in port["tiers"]]
    return json.dumps(out)


def llms_plan_lines(site):
    single, port, ent = by_id(site, "single"), by_id(site, "portfolio"), by_id(site, "enterprise")
    lines = [f"- Single Hotel: {money(single['monthly'])} per hotel a month, or {money(single['annual'])} a year. {single['for']}"]
    lines += [f"- Portfolio, {tier_label(t)}: {money(t['price'])} per hotel a month (the tier price applies to every hotel on the account; monthly billing only)" for t in port["tiers"]]
    lines.append(f"- Enterprise, {ent['min_hotels']} or more hotels: custom quotation")
    f = site["founding"]
    lines.append(f"- Founding Hotel programme: {money(f['price'])} a month for the first {f['months']} months, limited to {f['places']} selected hotels, by application")
    return "\n".join(lines)


def runtime_config(site):
    links = site["stripe"]["links"]
    keep = ("id", "name", "monthly", "annual", "per_hotel", "min_hotels", "max_hotels", "tiers", "custom")
    return ("/* Generated by build.py from src/site.json. Edit site.json, not this file. */\n"
            "window.PP = " + json.dumps({
                "APP_URL": site["app_url"], "CHAT_URL": site["chat_url"], "EMAIL": site["contact"]["email"],
                "CHECKOUT_URL": site["app_url"] + "/api/checkout",
                "CHECKOUT_ON": bool(site["stripe"].get("checkout")) and any(v for dd in site["stripe"].get("prices", {}).values() for v in dd.values()),
                "FORM_ENDPOINT": site["form_endpoint"], "FORM_KEY": site.get("form_key", ""), "PORTAL_URL": site["stripe"]["portal_url"], "LINKS": links,
                "PLANS": [{k: pl.get(k) for k in keep} for pl in site["plans"]],
                "FOUNDING": site["founding"],
            }, indent=2) + ";\n")


def nav_marks(slug):
    return {f"cur_{k}": (' aria-current="page"' if k == slug else "") for k in ("what", "sample", "guides", "pricing", "about", "contact")}


def build(dev=False):
    site = load_site(dev)
    layout = open(os.path.join(SRC, "partials", "layout.html"), encoding="utf8").read()
    footer_biz = business_block(site)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(os.path.join(SRC, "assets"), OUT)
    has_og = os.path.exists(os.path.join(OUT, "og.png"))
    sg, pf = by_id(site, "single"), by_id(site, "portfolio")
    fd = site["founding"]
    blocks = {"plans_cards": plan_cards(site), "plans_home": plan_cards_home(site), "plans_compare": plan_compare(site), "portfolio_buy": portfolio_section(site),
              "business": footer_biz, "year": str(dt.date.today().year), "updated": f"{dt.date.today().day} {dt.date.today():%B %Y}", "offers_json": offers_json(site),
              "portal_link": (f'<a href="{html.escape(site["stripe"]["portal_url"])}" rel="noopener" target="_blank">Manage billing</a>' if site["stripe"]["portal_url"] else ""),
              "lowest_price": money(sg["monthly"]), "price_single": money(sg["monthly"]), "price_single_annual": money(sg["annual"]),
              "price_single_saving": money(sg["monthly"] * 12 - sg["annual"]),
              "price_portfolio": money(pf["tiers"][0]["price"]), "price_portfolio_large": money(pf["tiers"][1]["price"]),
              "price_founding": money(fd["price"]), "founding_headline": fd["headline"], "founding_message": fd["message"], "founding_benefits": "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in fd["benefits"]) + "</ul>", "founding_asks": "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in fd["asks"]) + "</ul>", "founding_months": str(fd["months"]), "founding_places": str(fd["places"]),
              "llms_plans": llms_plan_lines(site)}
    pages, sitemap = [], []
    pdir = os.path.join(SRC, "pages")
    for name in sorted(os.listdir(pdir)):
        if not name.endswith(".html"):
            continue
        meta, body = parse_page(os.path.join(pdir, name))
        out_name = meta.get("path", name)
        slug = meta.get("nav", "")
        noindex = meta.get("noindex") == "true"
        canonical = site["url"] + ("/" if out_name == "index.html" else "/" + out_name)
        extra = {**blocks, **nav_marks(slug)}
        content = fill(body, site, extra)
        page = fill(layout, site, {**extra, "content": content, "title": html.escape(meta.get("title", site["name"])), "description": html.escape(fill(meta.get("description", ""), site, extra), quote=True),
                                   "canonical": canonical, "robots_meta": '<meta name="robots" content="noindex, nofollow">' if noindex else "",
                                   "og_image": (f'<meta property="og:image" content="{site["url"]}/og.png"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{site["url"]}/og.png">' if has_og else '<meta name="twitter:card" content="summary">'),
                                   "body_class": meta.get("body", "")})
        with open(os.path.join(OUT, out_name), "w", encoding="utf8", newline="\n") as f:
            f.write(page)
        pages.append(out_name)
        if not noindex and out_name != "404.html":
            sitemap.append(canonical)
    today = dt.date.today().isoformat()
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in sitemap) + "</urlset>\n")
    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf8") as f:
        f.write("# Presence Pro helps hotels be readable to AI search, so its own site welcomes AI crawlers.\nUser-agent: *\nAllow: /\n\nSitemap: " + site["url"] + "/sitemap.xml\n")
    with open(os.path.join(OUT, "CNAME"), "w", encoding="utf8") as f:
        f.write(site["domain"] + "\n")
    with open(os.path.join(OUT, "config.js"), "w", encoding="utf8") as f:
        f.write(runtime_config(site))
    with open(os.path.join(OUT, "llms.txt"), "w", encoding="utf8") as f:
        f.write(fill(open(os.path.join(SRC, "partials", "llms.txt"), encoding="utf8").read(), site, blocks))
    warnings = []
    op = site["operator"]
    for k in ("name", "address"):
        if not op[k]:
            warnings.append(f"operator.{k} is empty: UK online traders must show a name and address on the site")
    if not site.get("form_key") and not site.get("form_endpoint"):
        warnings.append("form_key is empty: the contact and hotel-details forms open the visitor's email app instead of sending (see README)")
    if not site["stripe"].get("checkout"):
        warnings.append("stripe.checkout is false: the Subscribe buttons use the Payment Links, so the visitor chooses the number of hotels again on Stripe's page. Set it to true once STRIPE_SECRET_KEY is in Render (see README)")
    elif not any(v for d in site["stripe"].get("prices", {}).values() for v in d.values()):
        warnings.append("stripe.prices are empty: the Subscribe buttons use the Payment Links, so the visitor must choose the number of hotels again on Stripe's page (see README)")
    if not site["stripe"]["portal_url"]:
        warnings.append("stripe.portal_url is empty: no 'Manage billing' link")
    empty = [f"{pid}/{iv}" for pid, dd in site["stripe"]["links"].items() for iv, u in dd.items() if not u]
    if empty:
        warnings.append("Stripe payment links not set for: " + ", ".join(empty) + " (if the new checkout is unavailable, those buttons fall back to the contact page)")
    print(f"built {len(pages)} pages into {os.path.relpath(OUT)}")
    for w in warnings:
        print("  note:", w)
    return OUT


def serve(port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=OUT, **k)

        def log_message(self, *a):
            pass

        def send_error(self, code, message=None, explain=None):
            if code == 404 and os.path.exists(os.path.join(OUT, "404.html")):
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(open(os.path.join(OUT, "404.html"), "rb").read())
            else:
                super().send_error(code, message, explain)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    with socketserver.ThreadingTCPServer(("", port), H) as srv:
        print(f"serving on http://localhost:{port}")
        srv.serve_forever()


if __name__ == "__main__":
    build(dev="--dev" in sys.argv)
    if "--serve" in sys.argv:
        serve(8767)
