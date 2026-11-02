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


def price_spans(p):
    m, a = money(p["monthly"]), money(p["annual"])
    return (f'<span class="amt" data-m="{m}" data-a="{a}">{m}</span><span class="per" data-m="/month" data-a="/year">/month</span>')


def plan_cards(site):
    out = []
    for p in site["plans"]:
        feat = " feat" if p.get("highlight") else ""
        badge = '<span class="badge">Most chosen</span>' if p.get("highlight") else ""
        btn = "gold" if p.get("highlight") else "dark"
        out.append(
            f'<div class="plan{feat} rv">{badge}<h3>{html.escape(p["name"])}</h3>'
            f'<p class="for">{html.escape(p["for"])}</p>'
            f'<p class="price">{price_spans(p)}</p>'
            f'<p class="save" data-m="Billed monthly. Cancel any time." data-a="Two months free. Billed once a year.">Billed monthly. Cancel any time.</p>'
            f'{feature_list(p)}<a class="btn {btn}" href="/contact.html?plan={p["id"]}" data-buy="{p["id"]}">Get started</a></div>'
        )
    return '<div class="plans3">' + "".join(out) + "</div>"


def plan_cards_home(site):
    out = []
    for p in site["plans"]:
        feat = " feat" if p.get("highlight") else ""
        out.append(
            f'<div class="plan mini{feat} rv"><h3>{html.escape(p["name"])}</h3><p class="for">{html.escape(p["for"])}</p>'
            f'<p class="price"><span class="amt">{money(p["monthly"])}</span><span class="per">/month</span></p></div>'
        )
    return '<div class="plans3">' + "".join(out) + "</div>"


COMPARE_ROWS = [
    ("Hotels covered", ["1", "1", "Up to 5"]),
    ("Monthly report (management PDF and evidence appendix)", [True, True, True]),
    ("Same questions re-tested, with change since last month", [True, True, True]),
    ("Website, listings and AI-answer findings, each with evidence", [True, True, True]),
    ("Your own questions tested each month", [False, "Up to 5", "Up to 5 per hotel"]),
    ("Your review export analysed each month", [False, True, True]),
    ("Open forum conversations worth joining", [False, True, True]),
    ("Summary across all your hotels", [False, False, True]),
    ("Set-up call", [False, False, True]),
    ("Support", ["Email", "Priority email", "Priority email"]),
]


def plan_compare(site):
    head = "<tr><th scope='col'>What you get</th>" + "".join(f"<th scope='col'>{html.escape(p['name'])}</th>" for p in site["plans"]) + "</tr>"
    rows = []
    for label, vals in COMPARE_ROWS:
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
    return json.dumps([{"@type": "Offer", "name": p["name"], "price": f"{p['monthly']}", "priceCurrency": "GBP",
                        "priceSpecification": {"@type": "UnitPriceSpecification", "price": f"{p['monthly']}", "priceCurrency": "GBP", "unitText": "MONTH"}} for p in site["plans"]])


def runtime_config(site):
    links = site["stripe"]["links"]
    return ("/* Generated by build.py from src/site.json. Edit site.json, not this file. */\n"
            "window.PP = " + json.dumps({
                "APP_URL": site["app_url"], "CHAT_URL": site["chat_url"], "EMAIL": site["contact"]["email"],
                "FORM_ENDPOINT": site["form_endpoint"], "PORTAL_URL": site["stripe"]["portal_url"], "LINKS": links,
                "PLANS": [{"id": p["id"], "name": p["name"], "monthly": p["monthly"], "annual": p["annual"]} for p in site["plans"]],
            }, indent=2) + ";\n")


def nav_marks(slug):
    return {f"cur_{k}": (' aria-current="page"' if k == slug else "") for k in ("what", "sample", "pricing", "about", "contact")}


def build(dev=False):
    site = load_site(dev)
    layout = open(os.path.join(SRC, "partials", "layout.html"), encoding="utf8").read()
    footer_biz = business_block(site)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(os.path.join(SRC, "assets"), OUT)
    has_og = os.path.exists(os.path.join(OUT, "og.png"))
    blocks = {"plans_cards": plan_cards(site), "plans_home": plan_cards_home(site), "plans_compare": plan_compare(site),
              "business": footer_biz, "year": str(dt.date.today().year), "offers_json": offers_json(site),
              "portal_link": (f'<a href="{html.escape(site["stripe"]["portal_url"])}" rel="noopener" target="_blank">Manage billing</a>' if site["stripe"]["portal_url"] else ""),
              "lowest_price": money(min(p["monthly"] for p in site["plans"])),
              "llms_plans": "\n".join(f"- {p['name']}, {p['for'].rstrip('.').lower()}: {money(p['monthly'])} a month or {money(p['annual'])} a year" for p in site["plans"])}
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
    if not site["stripe"]["portal_url"]:
        warnings.append("stripe.portal_url is empty: no 'Manage billing' link")
    empty = [f"{pid}/{iv}" for pid, d in site["stripe"]["links"].items() for iv, u in d.items() if not u]
    if empty:
        warnings.append("Stripe payment links not set for: " + ", ".join(empty) + " (those buttons fall back to the contact page)")
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
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), H) as srv:
        print(f"serving on http://localhost:{port}")
        srv.serve_forever()


if __name__ == "__main__":
    build(dev="--dev" in sys.argv)
    if "--serve" in sys.argv:
        serve(8767)
