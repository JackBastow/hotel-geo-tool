# Reviews and replies: how we get a proper analysis

## The problem

Reviews, and how a hotel replies to them, come up in every conversation about AI visibility: a review is third-party evidence in guest language, and a reply is the one place the hotel's own words sit inside that evidence. Our own samples agree that review sites are central: Tripadvisor, Booking.com and Hotels.com are among the most-cited sources behind the AI answers we collect. We do not know how any assistant *weights* reviews, and the report never claims to.

The difficulty is access. Booking.com, Expedia and Tripadvisor prohibit automated collection, Google's review data needs an official, billed or owner-authorised route, and this project has no paid APIs and no card. Whatever we build has to be free, compliant and honest about what it saw.

## What we can see today (shipped)

One AI model with web search reads the review pages that appear in public search results and reports, for the reviews it could see: whether the hotel replied, by whom, the tone, and now **how the reply was written** (specific to the guest, thanks or apologises, says what will be done, signed by a role) and **what each review was about** (breakfast, noise, parking...). Every item must cite a page that was in the search results or it is dropped.

Limits, stated in the report: a handful of reviews (the ones search surfaces), no reply *rate*, no response time, mostly Tripadvisor and Booking pages, little or no Google. It is a snapshot, never a score.

## The options

| Route | What it gives | Cost | Catch |
|---|---|---|---|
| **A. Search snapshot** (built) | A sample of reviews, reply behaviour, reply quality, topics | about 4-10 cents an audit | Small, unrepresentative sample |
| **A+. A deeper snapshot** | One search pass per platform (Tripadvisor, Booking, Google, Expedia, Trustpilot), more reviews, recency | about 15 cents | Still only what search shows |
| **B. The hotel uploads its own review export** | The full picture: every review and reply the hotel can export | Free | Needs the hotel to export a file |
| **C. Connect the hotel's Google Business Profile** | All Google reviews and replies, live | Free | OAuth plus Google approval for the API; the hotel must sign in |
| **D. Tripadvisor Content API** | Up to a few recent reviews per property | Free tier, terms apply | Tiny sample; needs an account; attribution rules |
| **E. Booking / Expedia partner APIs** | Everything | n/a | Only for connectivity partners, not for us |
| **F. Paid scrapers or review APIs** | Everything | Paid | Against the no-paid-APIs rule, and some breach platform terms |

## Recommendation

1. **Now: A, done.** Add **A+** when we want a bigger sample from search.
2. **Next: B, the review pack.** It is the only free, compliant way to analyse a hotel's *whole* review history, and every platform already lets the hotel export: Booking.com extranet, the Tripadvisor management centre, Google Business Profile, Expedia Partner Central. The hotel is the owner of that data and chooses to share it.
3. **Later, if hotels will connect accounts: C**, for live Google data.

## What the review pack (B) would do

Input: a CSV or Excel export, or pasted text, from any platform (we map common column names). Output, in the report and the monthly pack:

- **Reply rate**, overall, by platform, by star rating, and for the last 90 days; **critical reviews still unanswered**, listed.
- **Response time** where dates exist (median days, share replied within 3 days).
- **Reply quality**: specific to the guest, acknowledges, says what will be done, signed; how many replies are identical or near-identical templates; length; language matched to the guest.
- **What guests praise and what they complain about**, with counts and the months they spike, and whether the hotel's own site states those things in plain language (praised: breakfast; site says nothing on breakfast).
- **Rating and volume trend** by month, and recency (reviews in the last 90 days).
- **Draft replies** for the unanswered critical reviews, clearly labelled drafts for a person to edit, never posted.
- The scorecard's *Reviews & Reputation* category, "not assessed" today, becomes assessed with high-strength evidence.

Rules we keep:

- **Privacy.** Reviews contain personal data. The pack is analysed in memory; the saved run and the monthly pack keep **aggregates and short paraphrases only**, no reviewer names and no verbatim review text.
- **Honesty.** Reply rate is stated only for the file supplied ("of the 412 reviews in your export"), never as a market figure. Tone and themes are an AI's reading and are labelled so.
- **No incentives.** No advice to change, buy or reward reviews.
- **Cost.** Counting, dating and templating are plain arithmetic. Only themes and tone use the model, in batches, a few cents for a few hundred reviews.

## Other items from the IHG session

- **Content hub** (area pages, hotel pages): added as checks. Every audit now asks whether the site states *what the rate includes and what costs extra*, *which rooms sleep how many guests and the bed set-up*, and *where to eat, what to do and what is open late or when it rains*, each with the missing points and wording to fill in. Walking times to stations and venues were already checked.
- **"If it isn't on your site, AI cites elsewhere"**: the AI tab now says how often the hotel's own website was among the sources behind the answers, and which other sites were cited instead.
- **Content consistency across OTAs**: next. The plan is to take what each platform's listing states in public search results (check-in time, star rating, address, phone) from the passages the assistant cites, compare with the hotel's own pages, and list differences as "to check". After a rebrand, also flag listings whose title still carries a former name.
- **Descriptions and profile completeness** (Google Business Profile, OTA property descriptions): cannot be read directly. The review pack route can include a short "paste your current profile descriptions" box, checked for the facts AI looks for. Until then a checklist in the report is the honest option.
