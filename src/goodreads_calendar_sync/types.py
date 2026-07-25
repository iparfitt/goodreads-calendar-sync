from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional


@dataclass
class BookInfo:
    goodreads_id: str
    title: str
    author: str
    detail_url: str
    goodreads_url: str
    release_date: Optional[date] = None
    isbn: Optional[str] = None
    series: Optional[str] = None
    last_checked: Optional[datetime] = None


@dataclass
class StoredBook:
    goodreads_id: str
    title: str
    author: str
    release_date: Optional[date]
    isbn: Optional[str]
    series: Optional[str]
    calendar_uid: str
    last_checked: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            'goodreads_id': self.goodreads_id,
            'title': self.title,
            'author': self.author,
            'release_date': self.release_date.isoformat() if self.release_date else None,
            'isbn': self.isbn,
            'series': self.series,
            'calendar_uid': self.calendar_uid,
            'last_checked': self.last_checked.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoredBook':
        release_date = None
        if data.get('release_date'):
            release_date = date.fromisoformat(data['release_date'])

        return cls(
            goodreads_id=str(data['goodreads_id']),
            title=str(data['title']),
            author=str(data['author']),
            release_date=release_date,
            isbn=data.get('isbn'),
            series=data.get('series'),
            calendar_uid=str(data['calendar_uid']),
            last_checked=datetime.fromisoformat(data['last_checked']),
        )
