# Free GEO visibility snapshot: feasibility note (not built)

Written 2026-11-06 for the pricing brief. Nothing here is implemented beyond what already exists.

## What exists today
`/snapshot.html` is a form (name, email, hotel, town, website). It emails the owner, who prepares a one-page snapshot by hand with the private audit tool and sends it. The form promises one page, one assistant, one day, and one follow-up email.

## How an automated version could work
1. Visitor submits the form (already built).
2. A server job runs a cut-down audit: read the home page and a few key pages, put 5 or 6 traveller questions to one AI assistant with web search (each asked twice), find which hotels are named and whether this one is.
3. Render a one-page PDF or web page from the existing audit engine, and email it.
4. The owner can optionally review before it is sent (recommended at first, because a wrong or embarrassing snapshot is a worse advert than none).

## Cost
- The README's estimate for a **full** audit is about $0.55 to $0.60 of API spend, plus extras. A snapshot uses a fraction of the questions and none of the review or editorial work, so a reasonable **estimate** is $0.10 to $0.25 each. That is an estimate, not a measurement: measure ten real runs before committing.
- Other costs: email sending (negligible), and the Render host staying awake (already needed for chat and checkout).
- At $0.20 each, 500 snapshots a month is about $100. Not a worry against the $200 a month budget, but a flood of fake requests would be, hence the abuse controls below.

## Abuse prevention
- Require a real email address and send the snapshot only to it, with a confirmation link before anything is run (stops submitting other people's hotels and bots).
- One snapshot per hotel website domain per 90 days, and per email address.
- Limit per IP address and a global daily cap (for example 20 a day), after which the form says "we're at capacity, we'll reply within a week".
- Honeypot field (already in the form) and, if needed, a CAPTCHA.
- Only run for websites that resolve and look like a hotel; refuse obvious non-hotel domains.
- A hard monthly spend ceiling in code (the app already has a Claude spend guard).

## Reuse of the audit engine
Most of it already exists: the website reader, the question generator, the single-assistant sampling and the competitor naming. What would need building: a cut-down "snapshot" profile (fewer questions, no review pack, no competitor deep-dive), a one-page template, a queue so requests do not run in the web request, and the email step. Perhaps two to four days of work, mostly the template, the queue and the abuse controls.

## Simplest implementation, and a recommendation
Keep it manual for now. The form already works and costs nothing but the owner's time. Move to semi-automatic first: the form triggers the cut-down audit in the background and emails the owner the draft to approve and forward. Only go fully automatic once ten or so real snapshots show the output is reliably good, and once the abuse controls above are in place.

## Honesty points to keep
Label it as one assistant on one day. Never present it as a ranking or a prediction. If the website could not be read, say "not assessed", never a low score.
