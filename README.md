# Hotel AI Discoverability Audit

A free, public dashboard that measures how visible, and how correctly
described, a hotel is to AI answer engines and to the open data those systems
draw on. No account, no API key, nothing to install — type a website, press
one button, get a report.

Not an SEO audit. It's about whether a *machine* — an AI assistant, a map
app, a knowledge graph — can find the hotel, describe it correctly, and agree
with every other source about what it is.

---

## Using it

If this has been deployed (see **Deploying your own copy** below), just open
the link and use it. One form: a website, optionally a hotel name and city,
one button. Nothing else to configure.

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

Eight categories, weighted:

| # | Category | Weight | Measured in this build? |
|---|---|---|---|
| 1 | AI Visibility | 25% | ❌ never — needs a paid, billed API |
| 2 | OTAs & Travel Platforms | 15% | 🔑 if a free Tavily key is configured |
| 3 | Reviews & Reputation | 15% | ❌ not currently — needs Google Places (paid) or Amadeus (Enterprise sales, no longer free — see below) |
| 4 | Editorial & Blogs | 15% | 🔑 if a free Tavily key is configured |
| 5 | Website & Technical | 12.5% | ✅ always |
| 6 | Social & UGC | 7.5% | ⚠️ presence yes, activity no |
| 7 | Entity Consistency | 5% | ✅ always |
| 8 | Freshness | 5% | ✅ always |

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
module docstring for the full design and honest trade-offs (more searches
per audit, so fewer free audits per month - still comfortable for
occasional use, worth knowing for heavy use).

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
**Website & Technical**; the eight categories and their weights are
unchanged.

### The fact sheet

The facts the audit read from the site (name, address, phone, email,
check-in and check-out times, and each policy it found), each with a link to
the page it came from. If two pages give different check-in times, that is
flagged as a conflict. The same facts are used to cross-check OpenStreetMap
and Wikidata, so the consistency check now works on sites that publish no
structured data.

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
