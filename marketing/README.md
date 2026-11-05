# Presence Pro: marketing site (presencepro.co.uk)

A small static-site generator, no dependencies beyond Python 3. Pages live in `src/pages`, the shared frame (navigation, footer) in `src/partials/layout.html`, and **everything you will ever edit without touching HTML** in `src/site.json`: domain, contact email, business details, plans and prices, Stripe links.

```
python marketing/build.py                  # builds into marketing/public (what GitHub publishes)
python marketing/build.py --dev --serve    # local preview on http://localhost:8767 (the chat talks to the app on :8766)
```

The build prints notes for anything not yet filled in.

## What is here

| Page | Purpose |
|---|---|
| `/` | Home: what it is, how it works, sample taste, pricing summary, FAQ |
| `/what-we-do.html` | Everything a report covers, and what it doesn't |
| `/sample-report.html` | A full sample report for a fictional hotel (clearly labelled) |
| `/pricing.html` | Plans, monthly/yearly switch, comparison, billing FAQ, subscribe buttons |
| `/about.html`, `/contact.html` | Principles; contact form |
| `/terms.html`, `/privacy.html` | **Drafts.** Have them read before you take payment |
| `/welcome.html` | Where Stripe sends people after paying (not indexed) |
| chat widget (every page) | Common questions answered instantly; anything else goes to the assistant in `chat.py` |

## Go live, in order

### 1. Fill in `src/site.json`
- `operator`: your name (or company name), address and, if you have them, company and VAT numbers. UK online traders must show a business name, a geographic address and an email address on the site; a limited company must show its registered name, number and office. These appear in the footer, contact page and legal pages.
- `contact.email`: `hello@presencepro.co.uk` is assumed. **Make that mailbox exist** (your registrar or Cloudflare Email Routing can forward it to your own inbox).
- Prices: change `plans` freely. The pricing page, home page, chat answers and `llms.txt` all follow.

### 2. Stripe (taking payment, no code)
1. Create a Stripe account for the business at stripe.com and finish verification. Turn on **Stripe Tax** if you are VAT-registered.
2. Products: create one product per plan with a **monthly** and a **yearly** recurring price in GBP (the site shows 10 x monthly for yearly; change `annual` in `site.json` if you choose differently).
3. For each price create a **Payment Link** (Payment Links, New). In the options: collect the customer's **billing address**, add three **custom fields**, all text, all required: "Hotel name", "Town or city" and "Hotel website" (these are how you learn which hotel to report on; for Portfolio they cover the first hotel, and the welcome page form collects the rest), allow **promotion codes** if you like, and set **After payment: Don't show confirmation page, redirect customers to your website** to `https://presencepro.co.uk/welcome.html`.
4. Paste the six links into `stripe.links` in `site.json`. Until a link is pasted, that plan's button sends the visitor to the contact page instead, so nothing is broken in the meantime.
5. Customer billing portal: Settings, then Billing, then Customer portal. Allow cancelling and updating the card. Activate it and copy the **portal login link** into `stripe.portal_url`; a "Manage billing" link then appears in the footer. Customers can cancel themselves, which matches the terms.
6. Test with Stripe's test mode and card `4242 4242 4242 4242` first, using test-mode Payment Links, then swap in the live ones.

### 3. Domain and hosting
The site is on GitHub Pages at `presencepro.co.uk`; the audit tool stays on Render at `app.presencepro.co.uk`.

1. **GitHub**: Settings, Pages, Source: **GitHub Actions**. The workflow `.github/workflows/marketing-pages.yml` builds and publishes on every push to `main` that touches `marketing/`. (Pages on a free account needs a public repository. If this repository must stay private, put `marketing/` in its own public repository; nothing in it is secret. The chat route and prices are read from `src/site.json` by `chat.py`, so keep a copy of that file in this repo if you split them.)
2. In the same screen set the custom domain to `presencepro.co.uk` and tick **Enforce HTTPS** once offered.
3. **DNS** at your registrar for `presencepro.co.uk`:
   - Four `A` records on `@`: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
   - `CNAME` `www` pointing to `<your-github-username>.github.io`
   - `CNAME` `app` pointing to your Render address (for example `hotel-ai-audit.onrender.com`)
4. **Render**: service Settings, Custom Domains, add `app.presencepro.co.uk`.
5. In `site.json` set `app_url` to `https://app.presencepro.co.uk` and push.

### 4. The chat assistant
It runs inside the Flask app (`chat.py`, route `/api/chat`), so it needs nothing extra on Render beyond the `ANTHROPIC_API_KEY` already set. It answers only from a fact sheet built from `site.json`, never stores conversations, and is limited per visitor (12 messages in ten minutes), per month (3,000 replies, `CHAT_MONTHLY_CAP`) and by the shared Claude spend guard. Typical cost is a fraction of a penny a reply (`CHAT_MODEL`, default `claude-haiku-5-5`). Only `presencepro.co.uk`, `www.presencepro.co.uk` and localhost may call it; add others with `CHAT_ALLOWED_ORIGINS`. Without a key the chat still answers the quick-question buttons and points people to email for anything else. Note the Render free plan sleeps, so the first typed question after a quiet spell can take up to a minute (the widget says so).

### 5. After launch
- Submit `https://presencepro.co.uk/sitemap.xml` in Google Search Console and Bing Webmaster Tools.
- Read through the two legal pages with a solicitor.
- Look at the whole site on your phone.

## When someone subscribes
Stripe emails you (and them a receipt) and the custom fields give you the first hotel's name, town or city and website (find them on the payment in Stripe, under Payments; the welcome page form emails you the full list). Run their audit in the tool, send the PDFs, and repeat monthly. Nothing here is automated; automating delivery is a later build.

## Moving this to another GitHub account later
The site is published from this repository. To move it (for example to a personal account): Settings, Danger zone, Transfer ownership. The domain and DNS do not change. Afterwards re-check Settings, Pages (Source: GitHub Actions, custom domain) and re-link Render to the new owner.
