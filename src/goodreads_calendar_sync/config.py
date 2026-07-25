import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / '.env'
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

STATE_FILE = ROOT.parent / 'state.json'
GOODREADS_EMAIL = os.environ.get('GOODREADS_EMAIL', '').strip()
GOODREADS_PASSWORD = os.environ.get('GOODREADS_PASSWORD', '').strip()
GOODREADS_USER_ID = os.environ.get('GOODREADS_USER_ID', '').strip()
GOODREADS_SHELF_URL = os.environ.get('GOODREADS_SHELF_URL', '').strip()
GOODREADS_SHELF_NAME = os.environ.get('GOODREADS_SHELF_NAME', 'to-read').strip()
ICLOUD_EMAIL = os.environ.get('ICLOUD_EMAIL', '').strip()
ICLOUD_APP_PASSWORD = os.environ.get('ICLOUD_APP_PASSWORD', '').strip()
ICLOUD_CALDAV_URL = os.environ.get('ICLOUD_CALDAV_URL', 'https://caldav.icloud.com/').strip()
CALENDAR_NAME = 'Book Releases'
SHELF_PAGE_SIZE = 200
REFRESH_DAYS = 7
BOOK_URL_PREFIX = 'https://www.goodreads.com/book/show/'
SHELF_BASE_URL = 'https://www.goodreads.com/review/list'
