# Hotel AI Discoverability Audit

A free, public dashboard that measures how visible, and how correctly
described, a hotel is to AI answer engines and to the open data those systems
draw on. No account, no API key, nothing to install — type a website, press
one button, get a report.

Not an SEO audit. It's about whether a *machine* — an AI assistant, a map
app, a knowledge graph — can find the hotel, describe it correctly, and agree
with every other source about what it is.

Since the discovery & reputation layer was added it is also a **hotel
discovery and reputation report**: the website is one evidence source, not the
centre of the product. It looks at where the hotel appears across public
sources, how those sources describe it, which traveller needs it has evidence
for, what could weaken its appeal, and which real publications and
organisations are worth approaching — with a **full PDF report** to download.

---

## Using it

If this has been deployed (see **Deploying your own copy** below), just open
the link and use it. One form: a website, optionally a hotel name and city,
one button. Nothing else to configure. When it finishes you get the report as
tabs, plus two PDFs - a short **management report** (about 5-10 pages: the
score and its coverage, the top actions, gaps, risks and a 30/60/90-day plan)
and a **technical & evidence appendix** (everything behind it) - and a `.json`
you can keep and upload next time to compare. A full run takes roughly 4–5 minutes
(mostly waiting on other people's servers); untick *Include the wider
discovery* for the faster, website-only audit.

## How the headline and the ranking work

**The headline is a readiness score, shown with its coverage.** The number is
the average of the categories that could be assessed, so it is labelled *AI
discoverability readiness (assessed factors)* and always appears with how
much of the full model it rests on (e.g. "83/100, provisional, 60% measured")
and what was *not* measured - chiefly what AI assistants actually say about
the hotel, and guest reviews. Below 70% coverage it is marked **provisional**;
below 30% no single number is given at all. It is never presented as a measure
of how visible the hotel is to AI.

**A score and the evidence behind it are separate.** Every readiness component
and scorecard category also carries an evidence strength (high / medium / low),
so "100/100 from one place checked, with the map data down" reads as thin, not
perfect. A thin score is marked provisional rather than "strong".

**One global ranking decides what is most worth doing.** Every finding in the
audit - website, entity, crawl, reputation, distribution - is scored on
*business/reputation risk*, *how much travellers care*, *effect on
discoverability* and *how sure we are*, then moderated by effort. Risk is
weighted highest on purpose: a 2/5 food-hygiene rating, a wrong phone number or
a site that blocks crawlers outranks cheap technical tidying such as markup.
The numbers are written down in `ranking.py` so they can be argued with. The
top list is built from the whole audit, after every module has finished.

**Required fixes are separate from commercial opportunities.** Wrong or
conflicting information, missing guest information, crawl problems, reputation
risks and broken entity information are *required fixes*. A weak signal for a
segment (couples, families, meetings, city breaks...) is a *commercial
opportunity*, phrased conditionally - "If couples are a target segment, the
hotel has a spa and restaurant but doesn't connect them into a clear
romantic-stay proposition" - and never presented as a defect or placed in the
top actions.

**Wording is kept to what can be shown.** The report does not claim that AI
"skips the hotel or guesses" or that "machines can't see images". Sources other
than the hotel's own pages (OTAs, maps, publishers) also feed AI answers, so it
says systems "may be less able to answer accurately or confidently", and that
information only in images is "less reliably discoverable, indexable and
accessible" than text with alt text.

## The consultant view: what AI can understand, and what to fix first

The headline of the report is not a list of checks. It answers: *what can AI
and search systems understand about this hotel, what do they struggle with,
and what are the few things most worth doing?* Everything here is computed
from pages the audit already fetched (no extra requests) and quotes the page
text it rests on.

| Part | What it does |
|---|---|
| **How AI currently understands this hotel** | One cautious sentence built only from wording found on the pages, plus strong and weak signals. Nothing is invented; absence means "not stated", not "not true" |
| **Traveller searches the content supports** | 17 traveller intents (business, family, couples, weddings, spa, pets, sustainability, accessibility...) classed strong / some / weak / none, each with the reason and a quote. Legal pages (terms, privacy) are not counted as evidence of what the hotel offers |
| **Questions AI may struggle to answer** | Only questions that apply to *this* hotel (it says it has a pool, meeting rooms, a spa...) and that the pages leave open, each with the page where the answer belongs and example wording |
| **Location** | Whether the site ties the hotel to the stations, airports and landmarks that matter, with a distance. Open map data is used only as a labelled straight-line *hint*; travel times are never calculated or invented |
| **Consistency inside the site** | Different check-in times, phone numbers, postcodes, hotel names, opening hours, room counts, expired offers, opposite amenity statements - each with every page involved |
| **Strengths that are easy to miss** | Features mentioned once, buried deep, only in PDFs (menus grouped as one finding), only in images, or not linked internally |
| **Machine readiness** | Four separate groups - machine access, machine understanding, content gaps, outside evidence - never blended into one "GEO score" |
| **Structured data** | What the markup *says* (wrong phone, bad coordinates, missing address parts), not whether it exists. Always carries the caution that markup is not a ranking lever; self-published ratings are never recommended |
| **AI visibility readiness** | Eight separate component scores, each showing what drove it |
| **Top actions and quick wins** | At most seven, ranked by impact against effort and spread across the four kinds of problem, plus a separate low-effort list |

Every recommendation has the same shape: **what we found, why it matters, the
evidence, what to do, where, what to add, an example, priority, effort and a
confidence label** (*established good practice*, *reasonable inference* or
*experimental*), with the SEO/GEO detail collapsed underneath. A recommendation
is only generated from an actual finding, and a well-built site gets little or
no advice. The crawl reads raw HTML and does not run JavaScript; where that
matters the report says so.

**Crawler access and speed (added later, all free).** `web_signals.py` adds four bounded checks that run
in the background while the site is read: what robots.txt asks of AI crawlers (training, AI search, live
look-up, in plain English); whether the site publishes an `llms.txt` (an informal proposal, so its absence
is never a defect); whether the **Common Crawl** public web archive could read the site, and whether the
site *refused* its crawler; and **Google PageSpeed Insights** mobile speed/accessibility scores. PageSpeed
needs a free key from a Google Cloud project with no billing account, set as the `PAGESPEED_API_KEY`
secret; without one it says it wasn't measured. None of this shows what any AI assistant says about a
hotel, and presence in Common Crawl is not evidence that any model knows or recommends it.

**Sampled AI answers (optional, uses the operator's free Anthropic credit).** `ai_sample.py` asks one Claude
model (default `claude-haiku-5-5`, overridable with an `ANTHROPIC_MODEL` secret) about eight ordinary
traveller questions (where to stay, value, getting around, plus what it is, its facilities, what guests say and
which hotels are similar) with web search switched on (up to three searches each), then records whether the hotel is named, what the model says
when asked about the hotel directly, and which sites it relied on. It is shown as a labelled **sample**: one
model on one day, never a score or a ranking, and it adds at most one low-priority opportunity to the plan.
Cost is estimated from the usage the API reports (a few tens of cents an audit); a monthly estimate guard
(`store.SERVICE_CAPS["claude"]`) stops calls when it is reached, and the workspace spend limit in the Anthropic
Console is the hard stop. Without an `ANTHROPIC_API_KEY` secret the section says it was not run.

**Questions for the markets the hotel actually competes in (`ai_niche.py`).** "Best hotels in Rome" cannot surface a
mid-range hotel among hundreds, so a second round of up to three questions is written from facts the audit holds: an
airport the hotel's own pages (or the map) put within 25 km, the neighbourhood the map puts it in, its star rating, and what
its pages signal strongly (spa, pool, meetings, pets, EV charging, dining...). Each question is ordinary traveller wording,
never contains the hotel's name, is not so exact that only this hotel fits, and carries *why it was asked*. They are reported
separately ("named in x of y town-wide questions; a of b in the markets it competes in"), have their own competitor table,
count equally with the town-wide question in the AI Visibility card, and can raise a recommendation (AI4) when the hotel is
not named where it is positioned to compete. On a hotel the assistant never named town-wide it was named in 3 of 3 niche markets.

**Reading the hotel's market first (`ai_niche.py`).** Asking only "best hotels in Zurich" shows that the big luxury names crowd out everyone else, so the standard set is now just two
town-wide questions plus four about the hotel itself, and the weight is on up to six questions written for the hotel's own market. The audit first works out *what kind of hotel
it is*: its **price level** (the star rating on its own pages; failing that the brand's usual level, a stated inference, e.g. Hilton is upscale; failing that its own wording),
whether it is an **airport hotel**, its neighbourhood, and the **audiences** its pages give evidence for (airport and transit, business, meetings, spa, families, couples,
weddings, pets, long stays and more), each with the evidence. Questions are then worded as a traveller with that need would write them ("I'm flying out of Zurich Airport early tomorrow. Which
upscale hotels nearby have a shuttle and an early breakfast?"), include the price level, never name the hotel, and carry why they were asked. The reading is shown at the top of the AI tab
and in the appendix. Whoever runs the audit can override it in the form ("Who is the hotel for?": a price level and audiences). A hotel name typed as one run-together word
("hiltonzurichairport") is replaced by the site's own spelling when it is the same name. On a Zurich airport Hilton this moved the hotel from named in 0 of 14 answers to 5 of 12 niche answers.

**What the sampled answers mean (`ai_insights.py`, same Anthropic credit, about 2-3 cents an audit).** Modelled on
what AI-visibility tools (Otterly, Peec, Profound, Ahrefs Brand Radar) report, but built to be honest about one
engine and one sample: *who the assistant recommends instead* (a leaderboard with each hotel's share of the names
given, average position and the reason the assistant gave, plus its view of the competitive set), *question by
question*, *where it got its information* (sources typed as booking sites, review sites, tourism boards and so on, with
whether this audit found the hotel there), *what it says about the hotel* against what the site emphasises, *is it
right* (phone, check-in/out, address and parking checked against facts we hold; anything uncheckable is "could not
check", never "wrong"), a *head-to-head* with the top competitor, and **hypotheses for why the hotel may not be named**.
The hypotheses are the careful part: the model is shown a numbered evidence ledger built from this audit and may cite
only those ids, any hypothesis without a valid id is dropped, it is told it cannot see the assistant's reasoning, and
the report says they are things to check, not causes. Hotel names are kept only if they appear in the answer text. Two
low-priority recommendations can follow (a statement that differs from the hotel's own record; sources used without the
hotel). The Tools-tab comparison also shows this month's sample against last month's. Only Claude is asked; other
assistants (ChatGPT, Gemini, Perplexity, Google AI Overviews) are not.

**Brand ranking, sentiment, repeated questions and cited pages (the Otterly-style view).** Each town-wide and niche question is
asked **twice** by default (`ANTHROPIC_REPEATS` secret, 1-3), so one odd answer does not decide the result; questions about the
hotel itself are asked once. **Coverage %** is the share of all answers that named the hotel; the **brand ranking** shows the
hotel and the five hotels named most, each with coverage %, average position and **net sentiment** (% positive minus % negative
across the answers that named it, -100 to +100, an AI's reading of how each answer spoke of that hotel, "not judged" when the
hotel was never named). The "question by question" table shows "named in 1 of 2 answers". **Cited pages**: every answer keeps the exact
pages the search returned and the ones the answer cited (with the short passage it used); the "exact pages" table lists them most
cited first, with whether the page title or the quoted passage names the hotel or a competitor. We do not read those pages, so
"not seen" means not visible in what we hold, and the report says so. Every figure is a count over this one sample, not a market ranking.
Extraction now runs in batches of eight answers. Cost is about $0.55-0.60 an audit with two repeats.

**Finding the hotel's listings (`listing_lookup.py`, same Anthropic credit, about 10 cents an audit).** The wider discovery only keeps
what a few general searches happened to return, so it could report "not found by our searches" for a hotel that is plainly on
Expedia. One Claude call with web search now looks for the hotel on Booking.com, Expedia, Hotels.com, TripAdvisor, Trivago, Agoda and
Trip.com in turn; its words are discarded and a listing is accepted only if a page in the search results (or in the sampled answers
and review pages already collected) is on that platform's domain and its address or title carries the hotel's name (the full name,
the name without "hotel"/"spa", or for names of three or more distinctive words all of them in any order; one word alone never
counts). Found listings join the footprint and the OTA score, marked "found in public search results; page not opened", because the
platforms prohibit automated reading. A platform still not found says "not found by our searches", never "not listed".

**The hotel's own review export (`review_pack.py`, free, no AI).** Platforms prohibit automated collection, but every one lets the hotel export its own reviews. Upload that file
(on the audit form before it runs, or afterwards under Reputation & listings, Reviews & reputation; a CSV or Excel file from Booking.com, Tripadvisor, Google or Expedia, or any sheet with a rating or review and, where there is one, a reply and
dates) and the whole file is analysed: reply rate overall, by platform and by rating, critical reviews still unanswered (listed newest first with a skeleton draft reply to finish, never
offering anything in return), response time, how the replies were written (specific, thanks or apologises, says what will be done, signed; a rule-based reading), how many replies are
identical templates, what guests praise and criticise by topic and whether the hotel's own site states it, and the rating by month. It makes the Reviews & Reputation category assessed
(evidence strength from the number of reviews), adds findings to the plan and updates the saved run. Uploaded with the audit form, the file is held in memory for that run only; the unanswered-review list and drafts stay available on the report for an hour and are never saved. Every figure is for the file supplied. **Privacy:** reviewer names are never read;
the review text is analysed in the session and never saved; the report, the PDF, the saved run and the monthly pack keep counts and rates only.

**What the travel sites show (`listing_facts.py`).** The listing lookup keeps the passages the search service quoted from each platform's page for the hotel; check-in and check-out time,
star rating and telephone number are read from those passages by rules (never from the model's words) and compared with the hotel's own pages. A difference is "worth checking" (the
listing may be right). A listing whose title or quoted passage carries a former name taken from the hotel's own pages, an article or Wikidata, and not the current name, is flagged.

**Reviews and replies snapshot (optional, same Anthropic credit).** `review_replies.py` asks the model to look at
the review pages that appear in public search results and report ratings, review counts and, above all, whether
the hotel replied to each review it could see, by which role, in what tone, with a paraphrase. A model can invent,
so every item must cite a page and **any item whose page was not among the pages the search actually returned is
dropped and counted**. It is shown as *replies seen on reviews examined*, never as a reply rate, is paraphrased
(no reviewer or staff names), is never scored, and can add two low-confidence recommendations (critical reviews
with no reply; a defensive tone). The platforms prohibit automated collection by this tool; the searching is done
by Anthropic's search service, and the report says so. About $0.04 an audit.

**Fallback page reader for sites that refuse this tool (optional, same Anthropic credit).** Chain hotels' pages
(hilton.com and the like) answer this tool's own reader with HTTP 403. `claude_reader.py` then asks Anthropic's
openly identified web-fetch tool (it respects robots.txt and is not disguised as a browser) to fetch the hotel's
own page and up to five sub-pages inside the hotel's own folder, keeps the RAW fetched text, and runs the same
guest-question, fact, location and consistency analysis on it. Because plain text carries no HTML, markup, titles,
headings, image text and the site's linked profiles are **not assessed** (the scorecard and the analysis say so)
and the report states that the pages were read this way. It is used only when our own reader got fewer than
three pages, and about half a cent an audit.

**Not implemented, deliberately:** any competitor entry (nothing in the main audit needs a competitor)
and anything that needs a billing account or breaks a platform's terms.

## Report quality: how findings are checked before the hotel sees them

Every recommendation has an issue, evidence (a page, a source or a quoted passage), why it matters, a specific action, priority, effort, a confidence label (**Verified finding** or **Reasonable inference**) and an owner. `advice.validate` is the last gate: a candidate with no evidence, no specific action, generic wording ('improve your online visibility') or that repeats an earlier one is withheld, and the withheld list is kept in the report (`dropped_recommendations`) so nothing disappears silently.

- **The score** (`scoring.totals`): overall = sum(score x weight) / sum(weights) over the *assessed* categories. A category that was not measured is left out of both sums and never counted as zero. The report shows each category's score, weight, share and points, the plain average (only to explain why it differs), and why each category has its weight. Readiness (how well the hotel is set up) is kept apart from observed AI visibility.
- **False positives removed**: award wording only counts when it describes the hotel (`media.award_subject`: a supplier's 'award winning tea brand' does not); a second phone number labelled as a department's line, or found only on that department's page, is not an inconsistency; 'Brooklands Hotel' and 'Brooklands Hotel & Spa' are one name written more fully; image alt text counts content images only (tracking pixels, base64 placeholders, icons, logos and decorative images are excluded, lazy-loaded images use their real file) and puts room, restaurant, spa and facility pictures first; a fact 'not found' on a page whose tabs or accordions had no text in the page as read is *Unknown*, not Missing; 'no Hotel markup' is stated as not found on the N pages inspected (a tag manager's markup would not show).
- **Traveller recommendation readiness** (`traveller_ready.py`): for each kind of traveller the hotel serves (assessed only when the site shows the hotel offers what they come for), a list of requirements classed Confirmed, Partially confirmed, Missing or Unknown, each with the quoted words and page, or the exact information to add and the existing page to add it to. Optional offers (couples' packages, connecting rooms) are never Missing.
- **External presence** (`external_presence.py`): Booking.com, Expedia, Tripadvisor, OpenStreetMap, Wikidata, Google Maps and independent publications, each Verified, Identified (found in search results, platform not read), Contradicts the website, Unclear, or **Not verified** (never 'missing' or 'wrong'). Publications are weighed by quality, not counted, and sponsored pieces count for nothing.
- **Booking readiness** (`booking_check.py`): a booking link or engine on the homepage, whether its destination answers (a refusal is Not verified, only a 404 or server error is broken), and whether the site's own links work. At most ten polite requests. Rooms, prices and availability are not touched.
- **Comparable hotels** (`competitors.py`): up to three, found from OpenStreetMap hotels with a website, kept only if comparable by rating or size and by facilities (not just nearest), their homepage and up to two facility pages read politely. A comparison is made only when both hotels were read. If map data or their sites are unavailable the section says so and makes no claim.
- **AI recommendation tests** (`ai_sample.test_log`): about ten prompts that do not name the hotel, dynamically written from its location, landmark, region, facilities and positioning, asked of **Claude with web search only**. The log records platform, whether the hotel appeared, whether it was recommended, its place in the list, whether its own site was cited and the date. ChatGPT, Gemini and Copilot are listed as not tested, with a checklist for testing them by hand. None of this enters the readiness score.
- **Structured data** (`insight_tech.structured_audit`): Hotel, LodgingBusiness and LocalBusiness are checked on the pages inspected; a generic LocalBusiness block is flagged; the developer recommendation lists the properties, gives an example filled only from facts read on the site (unknowns stay in [brackets]), and says that structured data supports accuracy and is not shown to make an assistant recommend a hotel.

### Accuracy rules added after the Hilton Zurich Airport review

- **Information on the page is found, in any currency** (`textutil.py`): prices in CHF, dollars, codes after the figure; 'not available', 'cannot be guaranteed', 'not needed' are **negative evidence** (stated as not available), never a confirmation; site-wide menus, brand banners and footers are removed before facts are matched.
- **Named places only** (`places.py`): a railway station, airport or attraction needs a proper name; 'Charging station', 'Airports', a menu strip and the hotel's own name are never places; a distance counts only if it is in the same sentence as the place and tied to it; places are matched to open map data where it lists them.
- **The right page** (`pagetarget.py`): each page gets a type (rooms, dining, location, accessibility, hotel information, FAQ, policies, events...) from the path *inside the hotel's own folder*, and each kind of information has the types it belongs on. A page is never chosen because it merely contains the word; with no suitable page the general hotel-information page is named, and no address is invented.
- **What kind of hotel it is** (`hotel_class.py`): airport, business, conference, city-centre, resort, spa, luxury, boutique, family-focused, each with its reasons. It decides which traveller segments are core, secondary (optional) or not assessed, and an airport hotel gets its own requirements (airport distance, shuttle, early departure and late arrival, parking, public transport, stopover). A gym is not a spa, a restaurant is not a wedding venue, a family room is not a family hotel.
- **Honest coverage** (`assessment.py`): one place decides what was Assessed, Partly assessed and Not assessed from the evidence held. A site read as plain text has no structured-data, title, heading or image check, and an unreadable robots.txt or sitemap is not claimed as checked.
- **Several identifiers for outside sources** (`external_presence.identifiers`): an OpenStreetMap or Wikidata entry is Verified only on the name plus at least one more of coordinates (0.5 km), postcode, official website or telephone. The same town alone is an uncertain match.
- **A stricter gate** (`advice.validate`): menu strips and telephone banners are never evidence; a 'not stated' finding must list the pages inspected, what was found and what is still unstated; it is labelled Verified only when the audit read a page it belongs on, fully, with coverage not limited (otherwise an inference, or suppressed when no page it belongs on was read); one underlying issue is one recommendation; confirmed problems and optional opportunities are listed apart.

### AI reading of the hotel's own pages (`ai_extract.py`)

After the rule-based guest-question check, one Claude request (default `claude-sonnet-5-5`, override with the `ANTHROPIC_EXTRACT_MODEL` environment variable; about 2-7 US cents per audit, added to the month's Claude spend) is given the text of up to 14 of the hotel's own pages and asked what they say about parking, breakfast, check-in and out, pets, accessibility, family rooms, getting there, Wi-Fi, EV charging and cancellation.

- **No outside knowledge:** there are no web tools in the request; the model may use only the supplied pages, and is told the page text is data, not instructions.
- **Every fact needs a quotation, and the code checks it:** the quoted words must appear word for word in the page named (ignoring case, spacing and quote marks) and sit in a sentence about the topic. Paraphrases, invented sentences, quotations from another page, abridged quotations, menu strips, and 'offered' backed by a sentence that denies it are thrown away and counted in the methodology.
- **Absence is never taken from the model:** it can only add evidence to a question the rules did not already answer. A question becomes 'answered' only when every required fact has a verified quotation; the model cannot declare it complete.
- **Labelled:** an AI-found fact is marked 'found by AI reading; the quoted words were checked against the page', and the methodology lists how many quotations were verified and how many were rejected.
- Needs `ANTHROPIC_API_KEY` (already used for the sampled AI answers). Without it the rule-based check stands alone. Tests: `test_ai_extract.py`.

## Back end: saved audits, the admin page and the monthly pack

Set a `DATABASE_URL` secret (a Postgres connection string; Neon's free plan needs no card) and **every** finished audit is
saved: there is no visitor opt-out, and the page tells visitors plainly that runs are saved by the operator and not shown to
other visitors. `backend.py` keeps one row per run (the headline, every category score, the AI-visibility, niche-market,
review-reply and speed numbers, coverage % and net sentiment, cost, and the full report as JSON) plus market tables (which hotels the assistant named, with
coverage and sentiment, run by run; which sites and which exact pages it relied on). An older database is upgraded in place when the app first opens it. Open the app with `?admin=1` and the `ADMIN_PASSWORD` secret to get `ui_admin.py`: Overview, Runs
(filter, reopen, rebuild PDFs, delete), Hotels (one row per hotel with the change since its last run, history charts), Markets
(who the assistant names most, the exact pages and sites it relies on, across every hotel or one city), Usage, and Export. A hotel's history also charts the
coverage of the hotel and its top five rivals over time.

**The monthly pack (`monthly_pack.py`).** Export > Monthly pack builds one Excel workbook for a month (or a range of months):
*Hotels* (one row per audit: readiness, all eight category scores, AI visibility town-wide and in niche markets, share of
hotel names, place in the competitor table, reviews replied, speed, the top 3 actions, and the change since the hotel's latest
run in an earlier month), *Metrics* (the same numbers in tidy form, one row per hotel/run/metric, for dashboards and pivots),
*Scores and why* (every score with its status, evidence strength and a brief reason), *AI rankings* (question by question: named in how many answers? where in the list? who was named instead), *AI brand ranking* (every hotel named in
each run with coverage %, position and net sentiment; pivot it by month for competitors over time), *AI competitors*, *AI citations* (the exact pages), *AI why* (hypotheses), *Top 3 actions* and *Sources*, plus a *Read me*
with the caveats (a sample of one model, readiness is an indicator, blank means not assessed). With no `DATABASE_URL` nothing is
saved and the admin page says so. SQLite (`sqlite:///file.db`) works for development and tests but is not durable on Streamlit
Community Cloud, whose disk is wiped.

## The Flask site (Render) and the Streamlit app

There are now two front ends over the same Python. **Streamlit** (`app.py`, deployed on Streamlit Community Cloud) is unchanged. The **Flask site** is `server.py`, served by Waitress
(`python wsgi.py`), with its own HTML, CSS and JavaScript under `web/`: a form that starts a background audit and shows its progress, a private report link for each visitor
(`/r/<token>`, kept in the database so it survives a restart), PDF and data downloads, the review-export upload, the comparison with an earlier report, and the operator's `/admin` pages
(password, signed cookie, CSRF on the one destructive action). The report screens are the same code as in Streamlit: `htmlst.py` stands in for the parts of Streamlit's API they use and writes HTML,
so every sentence and honesty rule is unchanged (`report_view.py`). `netguard.py` stops the audit's fetches reaching private addresses (localhost, cloud metadata, internal ranges), checked on
every redirect. The monthly free-tier counters now live in the database, so they survive a host that wipes its disk. `DEPLOY.md` has the Render steps and what was checked about free hosting;
`render.yaml` is the blueprint; `requirements-web.txt` is what the site installs (no Streamlit). Tests: `test_web.py`.

## The discovery & reputation report

Built around 30 checks. Each is reported as **assessed**, **partial** or **not
assessed** — with the specific reason when it isn't fully assessed — rather
than dressed up from thin data. Every finding points at an *evidence record*
(source, URL, date collected, publication date where stated, an extract,
hotel-match confidence, and whether it is observed, inferred or unassessed).

| Section | Checks | What it gives you |
|---|---|---|
| Identity & distribution | 1–5 | Cross-source identity, namesakes and former names; listing footprint ("discovered" kept apart from "content assessed"); listing consistency; destination-body presence and the route to enquire; booking links and named partners |
| Reviews & reputation | 6–14 | The review sample stated honestly (usually *0 guest reviews accessible*); aggregate ratings third parties display; editorial review articles; the official FSA food-hygiene record; claims vs. independent evidence |
| Media & validation | 15–23 | Named coverage with links, dates, languages and inferred type; duplicates and syndication collapsed; independent-publisher count; awards (claimed vs. issuer-confirmed); narrative themes with extracts and disagreements; comparison hotels; evidenced media/organisation targets; pitch angles with the evidence still missing |
| Traveller fit | 24–27 | Evidence per traveller type; realistic traveller questions the hotel could fit (opportunities, **not** measured rankings); distinctive vs. generic positioning; terminology |
| Social, video & local | 28–29 | Official profiles; optional YouTube; mapped stations/attractions/venues with *straight-line* distances; stated partnerships |
| Website support | 30 | What others say that the site doesn't; crawler access; the existing guest-question analysis |

### What is deliberately NOT done, and why

- **Guest review text (checks 7–13) is not assessed.** TripAdvisor, Booking.com, Expedia, Agoda, Trip.com and
  Trustpilot prohibit automated collection; Google reviews need a
  billing-enabled account; the hotel's own testimonials are marketing, not
  independent evidence and are never used as a stand-in. That removes review
  freshness, praise/complaint themes, reply coverage, reply speed, reply
  language and review languages. Aggregate ratings that third parties
  *display* are captured separately and labelled as such.
- **Nothing here measures what an AI assistant recommends.** No assistant is asked.
  "Opportunities" are traveller questions the hotel has evidence to fit.
- **A media outlet is named only when a real page supports it.** If discovery
  was insufficient the report gives *research directions*, labelled as such.
  No journalist names or contact details are produced.
- **Search results vary between runs.** The search index returns a different
  slice of pages each time, so absence of a piece is never proof it doesn't exist.
- **robots.txt is respected** for every third-party page read, and platforms
  whose terms prohibit automated reading are never fetched (a link on the
  hotel's own site is not permission to read the other site).

### Sources used (all free, no billing account)

| Source | Needs | Returns | Limits |
|---|---|---|---|
| Tavily | operator key (free plan, 1,000 credits/month) | search results; news mode adds dates | a full audit uses ~12 credits |
| GDELT DOC 2.0 | nothing | monitored-news links, publishers, dates | ~3-month window; 1 request/5 s; **often refuses shared server IPs** (reported as *unavailable*) |
| Wikipedia / Wikidata | nothing | articles naming the hotel; names, aliases, owner, website | only notable places |
| OpenStreetMap (Overpass, Nominatim) | nothing | hotel record; nearby hotels, stations, attractions, venues | public servers are slow and may time out (reported as *partial*) |
| Internet Archive | nothing | archived homepage titles (rebrand signal) | patchy |
| UK FSA hygiene ratings | nothing | official inspection result | UK only; food hygiene only |
| YouTube Data API | optional operator key (`YOUTUBE_API_KEY`, free quota, no billing) | public video titles, channels, dates | skipped without a key |

Not used: TripAdvisor/Booking/Expedia pages (terms), Google Places and Gemini
grounding (billing), Amadeus self-service (decommissioned 2026-07-17), Common
Crawl (presence in a crawl is not evidence that any AI knows the hotel), and
consumer search-result pages (terms). The report's methodology section lists
each source's status for that run.

### Recommendations

Every recommendation states the problem, its evidence, why it matters, the
exact action, the responsible team (operations, reputation management, PR,
distribution, marketing, web), a priority *with its rationale*, and how to
check success. Each is labelled **documented guidance**, **hypothesis** or
**observation**. None promises an AI recommendation, and none advises fake or
incentivised reviews, keyword-stuffed guest reviews or indiscriminate outreach.

## Running it yourself, locally

```powershell
git clone <this repo>
cd hotel-geo-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Or on Windows, double-click `run.bat` — it builds the environment and starts
the app for you. Either way it opens in your browser in a few seconds, no
key, no cost.

---

## The scoring model

Six categories make up the **readiness** score, weighted to 100. **Observed AI visibility** (what assistants actually recommend, from the tests that were run) is a different measurement: it is reported beside the readiness score and has no weight in it.

| # | Category | Weight | Measured in this build? |
|---|---|---|---|
| 1 | OTAs & Travel Platforms | 20% | 🔑 if a free Tavily key is configured; identified in search results, never read, so capped |
| 2 | Reviews & Reputation | 20% | ❌ unless the hotel uploads its own review export |
| 3 | Editorial & Blogs | 20% | 🔑 if a free Tavily key is configured; weighed by publisher quality, not counted |
| 4 | Website & Technical (includes freshness and Google's PageSpeed test) | 24% | ✅ always; partial from outside signals when the site refuses this tool's reader |
| 5 | Social & UGC | 10% | ⚠️ presence yes (from the site's links, or from search when the pages can't be read), activity no |
| 6 | Entity Consistency | 6% | ✅ always; facts with nothing to compare are left out, not scored zero |
| - | Observed AI visibility | none (separate) | ⚠️ one assistant sampled when an Anthropic key is configured; never part of readiness |

**Without any keys configured, this covers about 30% of the model.** That
30% is never gated behind anything — no account, no key, free for every
visitor, forever. The two 🔑 rows are genuinely free too (no card, ever) but
need the *operator* to add a key once; see **Raising coverage on the public
dashboard** below. AI Visibility and (currently) Reviews & Reputation are
permanently out of reach without a paid/Enterprise decision — see **Why some
categories aren't here**.

### Why the score is not out of 100

A single number covering 30% of a model, presented as "59/100", reads as
reassurance and would be worse than no number. So:

- The score is a **weighted average over assessed categories only**.
- **Coverage is shown next to it, always** — "59, across 30% of the model".
- **Unassessed categories score nothing and cost nothing.** A hotel is never
  marked down because a category wasn't measured.
- Each unassessed category states what it would take to measure it.

`Social & UGC` is capped at 60 and marked *partial*: this build can tell
whether the hotel links to its own Instagram/Facebook/TikTok, but not whether
anyone's actually talking about it there — that needs each platform's own
API. It can never score full marks on half the evidence.

### Why some categories aren't here

- **AI Visibility** needs Gemini with Google Search grounding, which is not
  on any free tier at all — verified live: ordinary calls succeed, every
  grounded call returns HTTP 429 without a billing-enabled Google Cloud
  project. Test this one yourself instead: ask any AI assistant "best hotels
  in [city]" and see if the hotel comes up.
- **OTAs & Travel Platforms** and **Reviews & Reputation** live on sites
  whose own Terms of Use explicitly prohibit automated collection —
  TripAdvisor's says "use... any robot, spider, artificial intelligence (AI)
  system... to access, retrieve, copy, scrape, aggregate, collect... except
  as expressly permitted by Tripadvisor in writing" (verified against their
  live terms, 2026-09). This tool does not try to get around that, on any
  hosting, with any client. The honest way to see this data is through a
  source that's licensed it for reuse — a search index (Tavily), or an
  official API (Google Places, Amadeus) — not by reading those sites
  directly.
- **Editorial & Blogs** needs a web search index to find press/tourism-board
  mentions, which needs a key too.

### Raising coverage on the public dashboard — free sources only

The dashboard (`app.py`) reads **free, no-card** keys from Streamlit's
secrets store, if configured — never from the visitor. Add them and the
matching categories get assessed for everyone, automatically:

| Source | Unlocks | Cost |
|---|---|---|
| [Tavily](https://tavily.com) | Editorial (15%), OTA presence (15%), a Social & UGC boost | Free, 1,000 searches/month, no card |
| Gemini, ungrounded only (`GEMINI_READER_API_KEY`) | Makes Tavily's Editorial coverage read and judged, not just counted | Free - genuinely different cost profile from AI Visibility, see below |

Tavily alone takes coverage from ~30% to ~60% at zero ongoing cost. Shared
monthly counters (`store.py`) stop the app calling either once that month's
free allowance is used up, so public traffic can't exhaust them unnoticed —
see `app.py`'s module docstring for exactly how.

**Tavily is no longer one shallow search.** It now runs a multi-angle,
segment-aware set of queries per audit - detecting from the hotel's own
topic pages whether it reads as a wedding venue, business hotel, family
hotel, pet-friendly or spa/wellness destination (free, reusing signals
`site_check.py` already extracts), and searching accordingly rather than
running one generic query regardless of hotel type. See `tavily_check.py`'s
module docstring for the full design and honest trade-offs. With the wider
discovery a full audit uses about **12 Tavily credits** (the older editorial
scan reuses those results rather than searching again), so the free
1,000-credit plan covers roughly **80 full audits a month**. `app.py` checks
the shared counter against that before every run.

**`GEMINI_READER_API_KEY` is a genuinely different thing from AI Visibility,
not a relaxed version of it.** AI Visibility needs Gemini's paid, grounded
Google Search - that's excluded here entirely. This key is used only to
*read text Tavily has already fetched* and judge it (is this genuinely about
the hotel, how substantial, what sentiment) via an ungrounded call, which
works fine on the free tier - verified live. `gemini_reader.py`'s module
docstring explains why these two are kept strictly separate in code, not
just in naming. Without this key, the same reading happens via cruder
keyword rules instead - the feature works either way, just less precisely.

**To add these, on Streamlit Community Cloud:** open the app → **Settings** →
**Secrets**, and paste:

```toml
TAVILY_API_KEY = "tvly-..."
GEMINI_READER_API_KEY = "..."
```

Save, and the app restarts with them picked up — no code change, no redeploy
needed. **Running locally:** create `.streamlit/secrets.toml` in the project
folder with the same contents (that path is already in `.gitignore`, so it's
never committed).

**Amadeus Hotel Ratings is no longer a free option.** It used to offer a
self-service test tier covering part of Reviews & Reputation, but Amadeus
decommissioned that portal on 2026-07-17 — `developers.amadeus.com` now
serves only an Enterprise sales process. `amadeus_check.py` and the
`AMADEUS_API_KEY`/`AMADEUS_API_SECRET` secrets are still supported for
anyone who already holds (or later gets, via that sales process) valid
credentials, but this is no longer something to point a new user at.

Google Places and Gemini AI visibility are **not** wired into the public
dashboard at all, deliberately — both can incur real, uncapped cost per
request, which isn't something to expose on a page any stranger can click
without that being its own explicit decision.

### Self-hosting with full coverage (including the paid categories)

The pipeline underneath this dashboard (`full_audit.py`) already supports
every category, including the two left out of the public build above. If
you're running your own private copy — not the shared public one — you can
bring in Google Places and Gemini AI visibility too via CLI flags or
environment variables; see `full_audit.py`'s `main()` for the exact flags:

| Source | Unlocks | Cost |
|---|---|---|
| [Google Places API](https://developers.google.com/maps/documentation/places) | Reviews properly (rating, count, snippets) | Free monthly allowance, but needs a Google Cloud billing account on file |
| Gemini (billing enabled) | AI Visibility (25%) | 5,000 searches/month included, then $14/1,000 |

```powershell
$env:TAVILY_API_KEY = "..."
$env:GOOGLE_PLACES_API_KEY = "..."
$env:AMADEUS_API_KEY = "..."
$env:AMADEUS_API_SECRET = "..."
$env:GEMINI_API_KEY = "..."
python full_audit.py --website brooklandshotelsurrey.com --include-ai-visibility
```

This CLI path is entirely separate from the public `app.py` and its
Streamlit secrets — running it never affects, and is never affected by, the
hosted dashboard's configuration.

---

## What the audit actually does

One pipeline (`full_audit.run_full_audit`), everything free:

1. **Checks the site** — robots.txt and AI crawlers, sitemap (including
   `lastmod` dates for freshness), JSON-LD, Hotel schema completeness.
2. **Reads the hotel's name** from its own markup, so you don't have to type
   it.
2b. **Reads up to 25 of the hotel's own pages and asks the questions guests
   ask** — see *Guest-question coverage* below. This is the hotel-specific
   part, and it shows the exact text it relied on.
3. **Works out where the hotel is** — from its published address, any
   `PostalAddress` in its JSON-LD, a Google Maps link on the page (these
   carry latitude/longitude, the most precise signal available), or a
   postcode in the text. This runs *before* any lookup, because hotel names
   repeat: searching "Brooklands Hotel" with no location returns a hotel in
   Blackpool from OpenStreetMap and one in Dawlish from Wikidata — neither is
   the Weybridge one. A match that can't be verified against a known location
   is reported as unverified, never as found.
4. **Finds its linked profiles** — `sameAs` declarations plus outbound links
   to Facebook, Instagram, TikTok, Google Maps, OpenTable and similar.
5. **Checks OpenStreetMap and Wikidata**, verifying each match against the
   location from step 3.
6. **Cross-checks facts** — the hotel's own site vs. every other readable
   source — and flags discrepancies as significant / minor / unable to
   verify, never guessed.
7. **Scores it** across the model above, and produces one prioritised list of
   what to fix.

**No audit result is stored or shared between visitors.** Each run lives only
in that visitor's own browser session (gone on refresh) and in the JSON they
can download — never written to a shared file other visitors could read. That
matters because a public multi-tenant deployment has no safe place to keep a
cross-visitor history: one visitor typing in another hotel's name must never
surface a stranger's report. The one thing kept in memory is the *public text
of pages already published on the open web*, for up to 6 hours, so
re-checking a site doesn't refetch it. That cache holds page content, never a
report, and it is lost whenever the app restarts.

### Guest-question coverage

Rather than guessing from URLs whether a "parking page" exists, the audit
reads the pages and checks whether they actually answer ten questions guests
ask: parking, breakfast, check-in/out, pets, accessibility, family rooms,
getting there, Wi-Fi, EV charging and cancellation. Each question has named
sub-facts (parking needs the price, whether it is on-site, and whether you
can reserve), so the report can say *"your parking page gives the price but
not whether you can reserve a space"* instead of *"parking keyword found"*.

Every result is in one of five states, and they mean different things:

| State | Meaning |
|---|---|
| **Answered** | Every required detail found, on a page about the topic |
| **Partly answered** | The topic is covered but named details are missing |
| **Needs checking** | Only passing mentions - a human should look |
| **Not found on pages checked** | We read N pages and found nothing. *Not* "missing" - it may be on a page we didn't reach |
| **Couldn't check** | Pages were blocked, timed out, or had no readable text (often JavaScript-built sites). Never counted against the hotel |

Everything shows the quoted text and a link to the page it came from.
Matching is **rule-based and says so** - it finds evidence, it does not
understand meaning - which is why uncertain results are labelled rather than
guessed at. It looks sentence by sentence (so a "booking" in a neighbouring
FAQ answer can't count as evidence about parking), and treats "we can't
accommodate dogs" as a complete answer to the pets question.

It is **bounded**: at most 25 pages, per-page timeouts, a 60-second total
budget, parallel fetching. It only follows addresses the site itself lists in
its sitemap or links to; it never guesses URLs. Because it can't read every
page, "not found" is always worded as *not found on the pages checked*.

This replaces the old "topics with a matching page address" component inside
**Website & Technical**.

### The fact sheet

The facts the audit read from the site (name, address, phone, email,
check-in and check-out times, and each policy it found), each with a link to
the page it came from. If two pages give different check-in times, that is
flagged as a conflict. The same facts are used to cross-check OpenStreetMap
and Wikidata, so the consistency check now works on sites that publish no
structured data.

### The action plan

Every recommendation carries a stable code, an owner (web developer,
reception, marketing…), the page it applies to, and a worked example. The
dashboard leads with the **top three fixes**, ordered by priority and then by
the weight of the category they sit in, preferring to spread across
categories. Where the audit could only say "check this", it never outranks
something actionable. The JSON-LD example is pre-filled with the name, URL,
phone, address and profile links the audit actually read; anything it did not
find stays as a `[bracketed]` placeholder rather than a guess.

### Checking what AI assistants say (manual, and not scored)

The audit doesn't ask any AI assistant about the hotel. Instead it gives you
a prompt pack: **accuracy** prompts (which name the hotel) and **discovery**
prompts (which never do — that is the test). You paste them into the
assistants yourself, record each answer in a short form, and the page
summarises them. Each answer is one sample from a non-deterministic system,
so the summary says plainly when you have too few (fewer than five) or have
mixed web-search settings. These records are saved in the report you
download but **never enter the score**. Bing Webmaster Tools' AI Performance
report is worth checking too, but it covers Microsoft's AI only.

### Save and compare

Nothing is stored on the server. Download the dated `.json` report, and next
time upload it to see what moved: score, each category, each guest question,
which recommendations were resolved, and which facts changed. If the two runs
had different coverage, the overall delta is flagged as not like-for-like.
Reports from earlier versions still compare (matched by wording, not code).

---

## What this does not tell you

**It is not a measure of what AI assistants currently say about this hotel.**
That's the AI Visibility category, and it isn't included — see above.

**A page existing is not a page answering the question.** Topic coverage is
a candidate list for a human to read, not a verdict. Detection is by URL
pattern, so an unusual slug causes a false negative.

**"Unable to verify" is not "consistent."** Where a fact can't be read from
a source at all, it's reported as unknown, never silently treated as
agreeing with the hotel's own site.

---

## Design decisions worth knowing

**Nothing is read from a site that has told automated tools not to.**
TripAdvisor, Booking.com and similar explicitly prohibit automated
collection in their Terms of Use. This holds regardless of hosting, client,
or how technically easy it would be to work around — see **Why some
categories aren't here**.

**A confidently wrong match is worse than no match.** Every entity lookup
(OpenStreetMap, Wikidata) is checked against a known location before being
reported as found. Hotel names repeat across the country; a same-named hotel
in the wrong town is reported as "not found," not as a false positive.

**Failed checks are recorded as failures**, never as "the hotel has no
presence here." A network error or a blocked request is a gap in what this
tool could check, not evidence about the hotel.

---

## Deploying your own copy

This is an ordinary [Streamlit](https://streamlit.io) app, so it deploys to
[Streamlit Community Cloud](https://streamlit.io/cloud) for free, straight
from a GitHub repo:

1. Push this repository to GitHub (it needs to be visible to Streamlit Cloud
   — a public repo is simplest).
2. Sign in to [share.streamlit.io](https://share.streamlit.io) with that
   GitHub account.
3. "New app" → pick the repo, branch `main`, main file `app.py` → Deploy.

No secrets to configure — the public build never reads an API key. The app
sleeps when nobody's visited for a while and wakes on the next visit, which
is normal for the free tier and fine for this kind of occasional-use tool.

**Why this didn't need to be "local only."** An earlier version of this
project treated the whole app as something that could only run on one
person's machine, because of a real constraint in Google's Grounding with
Google Search terms: grounded results may only be shown "to the end user who
submitted the prompt." That rules out *pre-running* searches and publishing
them for others to browse — it does not rule out an ordinary hosted app
where each visitor's own click is itself the prompt submission and only
they see their own result. The public build here never calls Gemini at all,
so the question doesn't even arise for it — but it's worth knowing the
distinction if AI Visibility is ever added back to a hosted deployment:
live, per-visitor grounding is fine; caching and redistributing one person's
grounded result to others is not.

---

## Files

| File | Purpose |
|---|---|
| `app.py` | The public Streamlit dashboard — one form, one button, no keys |
| `full_audit.py` | The audit pipeline — every category, optional integrations included |
| `scoring.py` | The eight-category weighted model, coverage and recommendations |
| `site_check.py` | Website technical checks (robots.txt, sitemap, JSON-LD, schema) |
| `external_check.py` | Entity presence (OpenStreetMap, Wikidata) and fact consistency |
| `guest_questions.py` | Bounded crawl of the hotel's own pages; answers the guest questions with quoted evidence; builds the fact sheet |
| `test_guest_questions.py` | Offline tests for the above. Run `python test_guest_questions.py` |
| `evidence.py` | The evidence ledger and hotel-name matching (full name + location signal; look-alikes are rejected) |
| `polite.py`, `langid.py` | robots.txt-respecting page reader (dates, publisher, language, sponsored cues); dependency-free language detection |
| `sources.py` | Free-source adapters (GDELT, Wikipedia/Wikidata, Overpass, Wayback, FSA, YouTube) returning one envelope: ok / no_results / unavailable / not_configured |
| `sourcetypes.py` | Domain and page-type classification, publisher groups, award issuers, theme lexicon |
| `collect.py` | Runs the adapters and the search plan, reads the pages worth reading, decides which are about *this* hotel |
| `media.py`, `targets.py`, `identity.py`, `reviews.py`, `travellers.py`, `localctx.py` | The analysis for the 30 checks |
| `recommend.py`, `intel.py` | Evidence-backed recommendations; assembles the report and the 30-check status table |
| `report_pdf.py` | The full PDF (reportlab): selectable text, links, page numbers, repeating table headers |
| `ui_intel.py` | Streamlit rendering of the report sections |
| `test_intel.py` | Offline tests: matching, source failures, duplicates, sample-size honesty, unsupported claims |
| `pagesignals.py` | Machine-readability signals taken from pages the crawl already fetched (meta, canonical, JSON-LD contents, images, PDFs, JavaScript shell) |
| `lexicon.py` | Feature, traveller-intent and distance vocabulary for the consultant layer |
| `insight_content.py` | AI understanding, intents, unanswered questions, location, consistency, hidden strengths |
| `insight_tech.py` | Structured-data audit, machine readiness (four buckets), readiness profile |
| `advice.py`, `consultant.py` | Recommendation engine (finding → why → evidence → action → example) and the orchestrator |
| `ranking.py` | The one global ranking model (risk x traveller x visibility x confidence, moderated by effort), fix-vs-opportunity classification, top actions, quick wins, 30/60/90 plan |
| `headline.py` | The readiness headline: score + coverage + what was not measured; provisional/withheld thresholds; per-category evidence strength |
| `ui_consult.py`, `report_pdf_consult.py` | Streamlit and PDF rendering of the consultant report |
| `report_pdf_mgmt.py` | The short management report PDF (the full PDF in `report_pdf.py` is the technical & evidence appendix) |
| `test_insight.py`, `test_pdf.py`, `test_ui.py` | Offline tests for the analysis, the PDF layout and the whole results page |
| `fixes.py` | Turns recommendations into an action plan: owner, page, worked example, top three. Builds the pre-filled JSON-LD |
| `dashboard.py` | Builds the report as fully-escaped HTML, shown with `st.iframe` (needs `streamlit>=1.50`). No Streamlit import, so it is testable |
| `ai_check.py` | Prompt pack and summary for the manual AI answer check. Never scored |
| `compare.py` | Compares two downloaded reports. Reports are held by the user, not stored |
| `test_fixes.py`, `test_dashboard.py`, `test_phase3.py`, `test_discovery.py` | Offline tests, run each with `python <file>` |
| `tavily_check.py` | Optional — multi-angle, segment-aware search: OTA presence, editorial mentions, social mentions |
| `gemini_reader.py` | Optional — free, ungrounded Gemini call that reads and judges text `tavily_check.py` fetches. Not AI Visibility - see its module docstring |
| `places_check.py` | Optional — Google Places rating/reviews |
| `amadeus_check.py` | Optional — Amadeus Hotel Ratings sentiment |
| `gemini_client.py` | Optional — Gemini grounded-search transport (AI visibility) |
| `audit.py` | The AI-visibility query runner, used only when a Gemini key is supplied |
| `queryset.py` | AI-visibility query templates — only relevant if that's enabled |
| `store.py` | Local run history/caching, used by the CLI and local runs, not the public app |
| `smoke_test.py` | Live Gemini API check — only relevant if self-hosting with AI visibility |
| `run.bat` | Windows launcher for running it locally |

### Changing the query set

`queryset.py` holds the AI-visibility query templates, relevant only if
you're self-hosting with a Gemini key. Add or edit them freely — but
changing the **core** set makes past runs incomparable to new ones.

## Command line

```powershell
python full_audit.py --website brooklandshotelsurrey.com --out audit.json
```

Add `--hotel`, `--city`, and any of the optional API key environment
variables from **Self-hosting with full coverage** above to broaden what it
covers. `--include-ai-visibility` additionally runs a small live Gemini
sample (12 calls) if `GEMINI_API_KEY` is set with billing enabled.
