# PolicyCrush Automation Dashboard

Active repository for the PolicyCrush Automation Dashboard.

## Deployment notes

This app now expects server-side sessions. Local development uses `Flask-Session` with filesystem storage by default, which is more durable than the previous in-memory caches and avoids losing state between requests in a hosted backend.

Recommended hosted shape:

- `Vercel` can run the Flask app directly from `app.py`.
- The production workflow still needs durable server-side session storage, so a Vercel deployment should include a Blob store token.
- Manual fallback in the Production News step remains the fallback for blocked sources like HHS.

### Vercel setup

Official references:

- Flask on Vercel: https://vercel.com/docs/frameworks/backend/flask/
- Python runtime on Vercel: https://vercel.com/docs/functions/runtimes/python
- Vercel Blob SDK: https://vercel.com/docs/vercel-blob/using-blob-sdk

This repo now includes:

- `.python-version` pinned to `3.12`
- `vercel.json` with the Flask function duration set to `60` seconds
- a Blob-backed session backend that activates automatically when `BLOB_READ_WRITE_TOKEN` is set
- `public/assets/*` copies for Vercel-served static assets

Before deploying to Vercel:

1. Create a Blob store in the Vercel dashboard and attach its read-write token to the project as `BLOB_READ_WRITE_TOKEN`.
2. Set `FLASK_SECRET_KEY` in the Vercel project environment variables.
3. Set any app secrets you already use locally, including `OPENAI_API_KEY` when suggestions are enabled.
4. Do not rely on local-only files like `credentials.json` and `token.pickle` unless you replace those flows with a hosted-safe auth path.

## Environment variables

- `FLASK_SECRET_KEY`: required outside local development.
- `BLOB_READ_WRITE_TOKEN`: required on Vercel for durable production workflow sessions.
- `OPENAI_API_KEY`: enables article suggestion classification, categorization, and headline generation.
- `OPENAI_MODEL`: optional override for the classifier model. Default is `gpt-3.5-turbo` to preserve current behavior.
- `HEADLINE_OPENAI_MODEL`: optional model used for structured headline generation. Defaults to `gpt-4o-mini`.
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

If a hosted environment still blocks one of those sources, the `/production/news` screen now surfaces a manual fallback path instead of silently dropping the source.
