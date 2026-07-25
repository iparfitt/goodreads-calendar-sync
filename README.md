# Goodreads Book Release Sync

Synchronise Goodreads "Want to Read" future releases to an Apple Calendar called **Book Releases**.

## What it does

- Logs in to Goodreads with email/password.
- Reads the private `to-read` shelf.
- Detects future release dates.
- Creates or updates all-day events in an iCloud Calendar.
- Detects added, removed, title/author/release date changes.
- Stores sync state in `state.json`.
- Runs hourly via GitHub Actions.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set secrets and environment variables:

- `GOODREADS_EMAIL`
- `GOODREADS_PASSWORD`
- `GOODREADS_USER_ID` or `GOODREADS_SHELF_URL`
- `ICLOUD_EMAIL`
- `ICLOUD_APP_PASSWORD`
- Optional: `ICLOUD_CALDAV_URL` (default: `https://caldav.icloud.com/`)

You can set these in your shell or by creating a `.env` file in the repository root.

3. Run once manually:

```bash
python main.py
```

## GitHub Actions

The workflow in `.github/workflows/sync.yml` runs hourly and uses the same environment variables.

### GitHub-hosted runner note

Goodreads can challenge new login environments from GitHub-hosted runners. To make the hosted workflow more reliable, you can store a valid Goodreads session cookie in `GOODREADS_SESSION_COOKIES` instead of reusing email/password login every run.

How to use session cookies:

1. Open Goodreads in a browser where you are logged in.
2. Open developer tools and inspect cookies for `goodreads.com`.
3. Copy the relevant cookie names and values into valid JSON, for example:
   ```json
   {"session-id":"xxxx","session-token":"xxxx","s":"xxxx"}
   ```
4. Add that JSON string as a GitHub repository secret named `GOODREADS_SESSION_COOKIES`.

When the workflow runs, it will try the saved session cookie first. If the cookie is valid, it will skip the email/password login flow.

If the session expires or becomes invalid, you must refresh the cookie and update the secret.

## State

The sync stores information in `state.json` to track:

- Goodreads book ID
- title
- author
- release date
- calendar UID
- ISBN
- series
- last checked timestamp

## Notes

- The project prefers Goodreads RSS when available, but falls back to shelf HTML parsing.
- Book page scraping is limited to new entries, stale records, or missing metadata.
- Future releases are created as all-day calendar events with deterministic UID `goodreads-<bookid>`.
- If the calendar named `Book Releases` already exists, events are added to it. If it does not exist, it is created automatically.
