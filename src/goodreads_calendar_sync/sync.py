import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from .apple_calendar import AppleCalendarClient
from .config import (
    CALENDAR_NAME,
    GOODREADS_EMAIL,
    GOODREADS_PASSWORD,
    ICLOUD_APP_PASSWORD,
    ICLOUD_CALDAV_URL,
    ICLOUD_EMAIL,
    STATE_FILE,
)
from .goodreads import GoodreadsClient, _is_placeholder_text
from .state import load_state, save_state
from .types import BookInfo, StoredBook


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def _is_future_release(release_date: Optional[date]) -> bool:
    return release_date is not None and release_date > date.today()


def _is_past_release(release_date: Optional[date]) -> bool:
    return release_date is not None and release_date <= date.today()


def _has_valid_release_date(release_date: Optional[date]) -> bool:
    return release_date is not None


def _needs_detail_refresh(book: BookInfo, record: Optional[StoredBook]) -> bool:
    if record is None:
        return True
    if not book.title:
        return True
    if _is_placeholder_text(book.title) or _is_placeholder_text(record.title):
        return True
    if record.release_date is None:
        return True
    if not record.isbn or not record.series:
        return True
    if record.last_checked + timedelta(days=7) < datetime.utcnow():
        return True
    return False


def _effective_book(book: BookInfo, record: Optional[StoredBook]) -> BookInfo:
    if record is None:
        return book

    if not book.title:
        book.title = record.title
    if not book.author:
        book.author = record.author
    if book.release_date is None:
        book.release_date = record.release_date
    if not book.isbn:
        book.isbn = record.isbn
    if not book.series:
        book.series = record.series
    return book


def _make_stored_book(book: BookInfo) -> StoredBook:
    return StoredBook(
        goodreads_id=book.goodreads_id,
        title=book.title,
        author=book.author,
        release_date=book.release_date,
        isbn=book.isbn,
        series=book.series,
        calendar_uid=f'goodreads-{book.goodreads_id}',
        last_checked=book.last_checked or datetime.utcnow(),
    )


def run_sync() -> None:
    if not GOODREADS_EMAIL or not GOODREADS_PASSWORD:
        raise RuntimeError('GOODREADS_EMAIL and GOODREADS_PASSWORD are required')
    if not ICLOUD_EMAIL or not ICLOUD_APP_PASSWORD:
        raise RuntimeError('ICLOUD_EMAIL and ICLOUD_APP_PASSWORD are required')

    goodreads = GoodreadsClient()
    goodreads.login()
    logger.info('Logged in to Goodreads')

    books = goodreads.get_to_read_books()
    logger.info('Books loaded: %d', len(books))

    state_path = Path(STATE_FILE)
    existing_state = load_state(state_path)

    if not books and existing_state:
        logger.warning(
            'Goodreads returned no books while state contains entries. Preserving existing calendar events to protect against Goodreads outages.'
        )
        return

    calendar_client = AppleCalendarClient(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD, ICLOUD_CALDAV_URL)
    calendar = calendar_client.ensure_calendar(CALENDAR_NAME)
    logger.info('Using calendar: %s', CALENDAR_NAME)

    results = {'added': [], 'updated': [], 'deleted': [], 'errors': []}
    current_ids = {book.goodreads_id for book in books}
    stale_ids = set(existing_state) - current_ids

    for removed_id in stale_ids:
        record = existing_state.get(removed_id)
        if record:
            uid = record.calendar_uid
            deleted = calendar_client.delete_event(calendar, uid)
            if deleted:
                results['deleted'].append(removed_id)
                logger.info('Deleted removed book event %s', removed_id)
        existing_state.pop(removed_id, None)

    updated_state: Dict[str, StoredBook] = {}
    for book in books:
        record = existing_state.get(book.goodreads_id)
        if record is not None and _is_past_release(record.release_date):
            updated_state[book.goodreads_id] = record
            logger.info('Preserving past release %s without refreshing or changing its event', book.goodreads_id)
            continue

        book = _effective_book(book, record)
        if _needs_detail_refresh(book, record):
            try:
                goodreads.refresh_book_details(book)
            except Exception as exc:
                logger.error('Failed to refresh details for %s: %s', book.goodreads_id, exc)
                results['errors'].append(book.goodreads_id)
                if record is not None:
                    book = _effective_book(book, record)

        if book.release_date is None and record is not None and record.release_date is not None:
            book.release_date = record.release_date

        book.last_checked = datetime.utcnow()
        stored_book = _make_stored_book(book)
        updated_state[book.goodreads_id] = stored_book

        current_event_exists = calendar_client.find_event_by_uid(calendar, stored_book.calendar_uid) is not None
        should_be_present = _has_valid_release_date(book.release_date)
        changed = record is None or (
            record.title != book.title or
            record.author != book.author or
            record.release_date != book.release_date or
            record.isbn != book.isbn or
            record.series != book.series
        )

        if should_be_present:
            if not current_event_exists or changed:
                try:
                    calendar_client.ensure_event(calendar, book, force_update=changed)
                    if current_event_exists:
                        results['updated'].append(book.goodreads_id)
                        logger.info('Updated event for %s', book.goodreads_id)
                    else:
                        results['added'].append(book.goodreads_id)
                        logger.info('Created event for %s', book.goodreads_id)
                except Exception as exc:
                    logger.error('Failed to sync event for %s: %s', book.goodreads_id, exc)
                    results['errors'].append(book.goodreads_id)

    save_state(state_path, updated_state)
    logger.info('Future releases: %d', len([book for book in updated_state.values() if _is_future_release(book.release_date)]))
    logger.info('Added: %d', len(results['added']))
    logger.info('Updated: %d', len(results['updated']))
    logger.info('Deleted: %d', len(results['deleted']))
    if results['errors']:
        logger.warning('Errors: %d', len(results['errors']))
        raise RuntimeError(f'Sync completed with {len(results["errors"])} errors')
