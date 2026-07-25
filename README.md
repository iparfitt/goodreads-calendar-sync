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
