import html
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import caldav
from caldav.lib.error import AuthorizationError

from .types import BookInfo


logger = logging.getLogger(__name__)


def _escape_ics_text(value: str) -> str:
    value = html.unescape(value)
    escaped = value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '')
    escaped = escaped.replace(',', '\\,').replace(';', '\\;')
    return escaped


def _build_event_data(book: BookInfo) -> str:
    summary = f"{book.title} — {book.author}"
    lines = [book.author, book.goodreads_url]
    if book.isbn:
        lines.append(f'ISBN: {book.isbn}')
    if book.series:
        lines.append(f'Series: {book.series}')
    description = '\\n'.join(_escape_ics_text(line) for line in lines)
    dtstamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    dtstart = book.release_date.strftime('%Y%m%d')
    dtend = (book.release_date + timedelta(days=1)).strftime('%Y%m%d')

    return '\n'.join(
        [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//goodreads-book-release-sync//EN',
            'BEGIN:VEVENT',
            f'UID:goodreads-{book.goodreads_id}',
            f'DTSTAMP:{dtstamp}',
            f'DTSTART;VALUE=DATE:{dtstart}',
            f'DTEND;VALUE=DATE:{dtend}',
            f'SUMMARY:{_escape_ics_text(summary)}',
            f'DESCRIPTION:{description}',
            'END:VEVENT',
            'END:VCALENDAR',
        ]
    )


class AppleCalendarClient:
    def __init__(self, username: str, password: str, url: str = 'https://caldav.icloud.com/'):
        self.username = username
        self.password = password
        self.url = url
        self.client = caldav.DAVClient(url=self.url, username=self.username, password=self.password)
        try:
            self.principal = self.client.principal()
        except AuthorizationError as exc:
            raise RuntimeError(
                f'iCloud CalDAV authorization failed for {self.username} at {self.url}. '
                'Check that ICLOUD_APP_PASSWORD is a valid Apple app-specific password and that ICLOUD_EMAIL matches your Apple ID.'
            ) from exc

    def _get_calendar(self, name: str):
        for calendar in self.principal.calendars():
            try:
                display_name = calendar.get_display_name()
                if display_name and display_name.strip() == name:
                    return calendar
            except Exception:
                continue
        return None

    def ensure_calendar(self, name: str):
        calendar = self._get_calendar(name)
        if calendar is not None:
            return calendar

        try:
            return self.principal.make_calendar(name=name)
        except Exception as exc:
            logger.error('Failed to create calendar %s: %s', name, exc)
            raise

    def _event_uid(self, event) -> Optional[str]:
        try:
            data = getattr(event, 'data', None)
            if data:
                match = re.search(r'UID:(.+)', data)
                if match:
                    return match.group(1).strip()
        except Exception:
            pass
        return None

    def find_event_by_uid(self, calendar, uid: str):
        for event in calendar.events():
            if self._event_uid(event) == uid:
                return event
        return None

    def create_event(self, calendar, book: BookInfo):
        ics = _build_event_data(book)
        return calendar.add_event(ics)

    def delete_event(self, calendar, uid: str) -> bool:
        event = self.find_event_by_uid(calendar, uid)
        if event is None:
            return False

        try:
            event.delete()
            return True
        except Exception as exc:
            logger.error('Failed to delete event %s: %s', uid, exc)
            return False

    def ensure_event(self, calendar, book: BookInfo, force_update: bool = False):
        uid = f'goodreads-{book.goodreads_id}'
        existing = self.find_event_by_uid(calendar, uid)
        if existing is not None and not force_update:
            return existing

        if existing is not None:
            existing.delete()

        return self.create_event(calendar, book)
