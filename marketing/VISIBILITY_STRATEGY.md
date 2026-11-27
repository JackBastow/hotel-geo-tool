# How Presence Pro gets found by AI and search (strategy, 2026-11-27)

## The honest starting point
- presencepro.co.uk is weeks old and, as far as a search on 27 Nov could show, not yet indexed by the engines we can see. That alone explains most of why it does not appear when someone asks an AI assistant about AI tracking for hotels.
- The head phrases ("AI visibility tracking for hotels", "GEO for hotels") are already covered by established hotel-technology companies (for example Lighthouse, Cloudbeds, SiteMinder, Mews, Smartness, Local Falcon, Operto's free checker) and by Hospitality Net explainers. A new domain will not out-rank them on those phrases in weeks, whatever we publish.
- So the plan is: get indexed fast, win the narrower questions where we can be the most useful and most specific answer, and earn mentions on other sites, because assistants lean on third-party pages as much as on a brand's own site (the same thing we tell hotels).
- Nobody can promise a timescale. Realistic: indexed in days to weeks; long-tail pages start appearing in weeks to months; head terms are a longer game.

## What AI assistants need from us (same as for a hotel)
1. **Be crawlable and indexed.** Bing and Google indexes feed most assistants' search. We were not telling either engine we exist.
2. **Be a clear entity.** One name, one description, the same facts everywhere ("Presence Pro, a UK-focused dashboard that tracks how AI describes a hotel"). The name is generic and another company, "PRESENCEPRO LIMITED", exists, so consistency and a description that repeats "hotel" and "AI visibility" matter.
3. **Answer the exact question, in extractable form.** Short definition at the top, a table, a short FAQ in plain words, with matching FAQ structured data.
4. **Be mentioned elsewhere.** Credible third-party pages that name us, honestly.
5. **Be checked.** We run our own prompts monthly (below), like a customer would.

## Workstream A: get indexed and be a clear entity
Done 27 Nov (in the site):
- Five new pages, each built for one question, with a definition up top, tables and a matching FAQ block (FAQPage and Article structured data): `/ai-visibility-for-hotels.html`, `/geo-for-hotels.html`, `/how-to-get-your-hotel-recommended-by-chatgpt.html`, `/hotel-ai-visibility-tools.html`, `/hotel-schema-markup-for-ai.html`.
- Linked from the Guides page, from each other and from the footer; added to `llms.txt` and the sitemap. The `llms.txt` description now says what Presence Pro is in one sentence.
- IndexNow: a key file on the site and a publish step that tells Bing (and other IndexNow engines) about every page on each deploy. No account needed. This does not reach Google.

Owner steps (needs your sign-in; about 15 minutes in total):
1. **Google Search Console** (search.google.com/search-console): Add property > Domain > `presencepro.co.uk`. It shows a TXT record; add it in GoDaddy (DNS > Add record > TXT, host `@`, paste the value). Verify, then Sitemaps > add `sitemap.xml`. Then URL Inspection > Request indexing for the home page and the five new pages.
2. **Bing Webmaster Tools** (bing.com/webmasters): sign in, choose "Import from Google Search Console" (easiest after step 1), then submit `sitemap.xml`.
3. **LinkedIn company page** "Presence Pro" (a company page, not your profile, so it stays the team): same one-line description as `llms.txt`, a link to the site. Tell me the page address and I will add it to the site's structured data as an official profile.

## Workstream B: content (the pages that can win)
Principle: one page per real question, written to be the most specific and most honest answer, with tables and FAQs. No invented statistics, no fake case studies, no promises of recommendations. Competitors are named only by what they publicly say they are, with a note that we have not tested them.

Queue after the first five (ordered by value; build when you say):
1. **"What AI said about [N] UK hotels"**: original data from real runs (below). The single most linkable thing we can publish.
2. **AI visibility for hotel groups**: how to track many properties in one place (matches the Portfolio plan).
3. **AI visibility for agencies**: a page for the agencies we are emailing, on offering it to hotel clients.
4. **A short monthly note** on what changed in AI hotel search, sourced, which gives people and assistants a reason to return.
5. **Case study**: only once a hotel agrees in writing, with their real numbers.

## Workstream C: original data (the link magnet)
Run the tool over a defined set of UK hotels (for example 50 independents from the outreach list), and publish only aggregates: how often hotels were named for their own area's questions, how often the cited pages were booking sites versus the hotel's own site, how often key facts were missing from hotel websites. Rules: fixed questions, repeats, stated method and date, a plain note on what it cannot show, no naming of hotels in a bad light, no claims about assistants we did not test. Dependency: the AI sampling needs to be reliable first (Gemini timed out last week, see the snapshot notes). Do not publish a number we cannot reproduce.

## Workstream D: be mentioned elsewhere (this matters most)
- **Partners and agencies** that say yes to a snapshot: ask for an honest mention or link on their site.
- **Hospitality Net** publishes expert articles from contributors: offer one based on the data in workstream C.
- **Hotel-technology directories** (for example HotelTechReport): see whether a vendor listing is possible once there is a customer to reference.
- **Communities where hotel owners ask about AI** (LinkedIn groups, Reddit, Facebook groups): answer real questions usefully, say who we are, never post links as spam.
- **Reviews on G2 or Capterra**: later, only genuine ones from customers.

## Workstream E: measure ourselves, monthly
Run these prompts in each assistant you use, in a new chat, and note whether Presence Pro is named, who is named instead, and which pages are cited. Then compare with last month. (This is the same method we sell, so it also tells us what our own product would say.)
1. AI visibility tracking for hotels
2. GEO for hotels
3. What is generative engine optimisation for hotels?
4. How do I check if ChatGPT recommends my hotel?
5. How to get my hotel recommended by ChatGPT
6. Best tools to track a hotel's AI visibility
7. Hotel AI visibility tool for a group of hotels
8. Schema markup for hotels: what to add
9. Does llms.txt help hotels?
10. What is Presence Pro?
Also watch in Search Console: indexed pages, impressions and queries, and in Cloudflare Web Analytics: visits to the five new pages.

## What we will not do
No fake reviews, no invented statistics, no hidden text, no buying links presented as editorial, no claiming results or customers we do not have, no claiming which assistants we cover. Same standards we ask of hotels.
