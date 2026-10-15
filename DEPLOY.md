# Putting the Flask site online (Render, free)

The site is `server.py` (Flask) served by Waitress (`python wsgi.py`). The audit, the AI steps, the database and the PDFs are the same Python as the Streamlit app; the two apps can run side by side and share the same Neon database.

## What Render's free web service gives you (checked against Render's own docs, October 2026)

- No credit card needed to start. Free services are suspended if they pass the bandwidth or build limits and no payment method is on file.
- **It sleeps after 15 minutes with no visitors, and takes about a minute to wake.** Streamlit Community Cloud sleeps after 12 hours instead, so this is the real cost of the move. The fix below (a free pinger) keeps it awake.
- 750 free instance hours a month per workspace: enough for one service running all month (a 31-day month is 744 hours).
- The disk is wiped on every restart, deploy or sleep. Nothing here depends on it: reports and the free-tier counters live in your Neon database.
- Outbound calls to the APIs we use (Anthropic, Tavily, Google, OpenStreetMap, Wikidata) are allowed. Only the mail ports are blocked.
- Hugging Face Spaces, Koyeb, Railway and Fly.io were looked at and ruled out: free Docker Spaces appear to have been withdrawn for new accounts, Koyeb's free plan could not be confirmed, and Railway and Fly.io no longer have a real free tier.

## Steps (about 15 minutes)

1. **Render account.** Sign up at render.com with your GitHub login.
2. **Blueprint.** New, then Blueprint, pick the `hotel-geo-tool` repository. Render reads `render.yaml` and asks for the secret values.
3. **Paste the secrets** (the same names and values as in Streamlit's Secrets box):
   `DATABASE_URL`, `ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `GEMINI_READER_API_KEY`, `PAGESPEED_API_KEY`, `YOUTUBE_API_KEY` (leave blank any you do not use). `SECRET_KEY` is generated for you. Optional: `ANTHROPIC_MODEL`, `ANTHROPIC_REPEATS` (1 to 3), `AUDITS_PER_HOUR_PER_VISITOR` (default 4), `MAX_QUEUED_AUDITS` (default 6).
4. **Deploy.** The first build takes a few minutes. The site is at `https://hotel-ai-audit.onrender.com` (or the name Render gives it). `/healthz` should say `ok`. Every later push to `main` redeploys on its own.
5. **Keep it awake.** Create a free account at uptimerobot.com and add an HTTP(s) monitor for `https://<your-site>/healthz` every 5 minutes. That counts as traffic, so the service never sleeps, and it stays inside the 750 hours.
6. **Check it.** Run an audit from the form; open `/admin` with your `ADMIN_PASSWORD`; confirm the run appears.
7. **Switch over** when you are happy: share the new address, and stop the Streamlit app in Streamlit Cloud when you no longer want it (it can stay up meanwhile).

## Things to know

- A visitor's report link (`/r/<long random text>`) is private to them and is kept in the database, so it still works after a restart. It is never listed anywhere.
- Review-export text is analysed in the request and never stored; only counts and rates are saved with the report.
- The service limits each visitor to a few audits an hour and queues the rest, so a busy afternoon cannot use up the month's free allowances.
- Free-tier counters (Tavily searches, estimated Anthropic spend) are now kept in Neon, so they survive restarts. The Anthropic workspace spend limit is still the hard stop.
- If the free instance runs out of memory on a very large site, Render restarts it; the visitor sees the audit fail and can run it again. A paid instance fixes that.
- Run it on your own machine with `python wsgi.py` (port 8000) after `pip install -r requirements-web.txt` and setting the same environment variables.
