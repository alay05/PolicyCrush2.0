# PolicyCrush Automation Dashboard

Active repository for the PolicyCrush Automation Dashboard.

The home page links to Main Newsletter, W2W4, Daily, Senate, House, and AddEvent (Manual). Main Newsletter uses saved articles, headline generation/review, and Mailchimp draft creation; W2W4 uses calendar pulls and event headline generation/review.

## Deployment notes

This app now expects server-side sessions. Local development uses `Flask-Session` with filesystem storage by default, which is more durable than the previous in-memory caches and avoids losing state between requests in a hosted backend.

Recommended hosted shape:

- `Vercel` can run the Flask app directly from `app.py`.
- The newsletter workflows need durable server-side session storage, so a Vercel deployment should include a Blob store token.
- Articles from unavailable sources can be added through Main Newsletter's manual article form.

### Vercel setup

Official references:

- Flask on Vercel: https://vercel.com/docs/frameworks/backend/flask/
- Python runtime on Vercel: https://vercel.com/docs/functions/runtimes/python
- Vercel Blob SDK: https://vercel.com/docs/vercel-blob/using-blob-sdk

This repo now includes:

- `.python-version` pinned to `3.12`
- `vercel.json` with the Flask function duration set to `300` seconds for the initial hearing-cache build
- a Blob-backed session backend that activates automatically when `BLOB_READ_WRITE_TOKEN` is set
- `public/assets/*` copies for Vercel-served static assets

Before deploying to Vercel:

1. Create a Blob store in the Vercel dashboard and attach its read-write token to the project as `BLOB_READ_WRITE_TOKEN`.
2. Set `FLASK_SECRET_KEY` in the Vercel project environment variables.
3. Set any app secrets you already use locally, including `OPENAI_API_KEY` when suggestions are enabled.
4. Set `CONGRESS_API_KEY` for Senate and Joint Economic hearings.
5. Optionally set `SCRAPINGBEE_API_KEY` to try a paid transport when committee sites reject normal requests. Akamai may still reject the proxied request.

## Environment variables

- `FLASK_SECRET_KEY`: required outside local development.
- `BLOB_READ_WRITE_TOKEN`: required on Vercel for durable newsletter workflow sessions.
- `OPENAI_API_KEY`: enables article suggestion classification, categorization, and headline generation.
- `OPENAI_MODEL`: optional override for the classifier model. Default is `gpt-3.5-turbo` to preserve current behavior.
- `HEADLINE_OPENAI_MODEL`: optional model used for structured headline generation. Defaults to `gpt-4o-mini`.
- `MAILCHIMP_API_KEY`: enables Main Newsletter draft creation in Mailchimp. Keep this server-side; the data center is read from the key suffix.
- `CONGRESS_API_KEY`: required for Senate and Joint Economic hearing calendars. Get a free key from https://api.congress.gov/sign-up/.
- `SCRAPINGBEE_API_KEY`: optional transport fallback for official committee pages that return 401, 403, or 429 to normal server requests. Get it from https://www.scrapingbee.com/.
- `SCRAPINGBEE_PREMIUM_PROXY`: defaults to `true`. Set to `false` only if the standard proxy pool works for the Senate sites.
- `SCRAPINGBEE_CIRCUIT_BREAKER_SECONDS`: defaults to 15 minutes and prevents repeated paid transport requests after Senate Akamai rejects the transport.
- `CONGRESS_CACHE_TTL_SECONDS`: optional Congress.gov meeting-cache refresh interval. Defaults to one hour.
- `CONGRESS_INITIAL_LOOKBACK_DAYS`: update-date lookback used to seed a hearing cache around the requested date. Defaults to `120`; requesting an older date expands the cache backward.
- `CONGRESS_API_MAX_WORKERS`: optional bounded concurrency for the initial Congress.gov meeting index. Defaults to `8`.
- `CONGRESS_CACHE_DIR`: optional local meeting-cache directory. Defaults to the operating system temporary directory.
- `SESSION_TYPE`: defaults to `filesystem`.
- `SESSION_FILE_DIR`: optional filesystem session directory override.
- `SCRAPER_BROWSER_PROVIDER`: `auto`, `requests`, `playwright`, or `selenium`.
- `ENABLE_SELENIUM_FALLBACK`: set to `true` only if you intentionally want Selenium as a fallback.
- `HTTP_TIMEOUT_SECONDS`: optional scraper timeout override.

## Browser-backed sources

News sources that previously hard-required `ChromeDriver` now use a shared loader:

1. Try a normal HTTP fetch first.
2. Fall back to `Playwright` when the expected page markup is missing.
3. Optionally fall back to `Selenium` only when explicitly enabled.

If a hosted environment still blocks one of those sources, articles can be entered manually on Main Newsletter (`/saved-articles`).

## Committee sources

- House hearings use the official House Committee Repository calendar. Senate and Joint Economic hearings use the official Congress.gov API; later pulls reuse cached meeting details.
- Local meeting details are cached under the system temporary directory. When `BLOB_READ_WRITE_TOKEN` is configured, Vercel Blob also stores the cache so cold function instances do not repeatedly consume the Congress.gov API quota.
- House majority/minority listings and Senate majority/minority listings paginate through the requested start date.
- Committee press pages always try the official committee URL directly first. If that request is blocked and `SCRAPINGBEE_API_KEY` is configured, the app attempts the same government URL through ScrapingBee with JavaScript rendering disabled. A circuit breaker prevents repeated paid requests when Akamai also rejects that transport.
- Committee scraping does not require Selenium, Playwright, Chrome, or a bundled browser.
