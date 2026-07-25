import json
from pathlib import Path
from typing import Dict

from .types import StoredBook


def load_state(path: Path) -> Dict[str, StoredBook]:
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding='utf-8'))
    return {
        book_id: StoredBook.from_dict(data)
        for book_id, data in raw.items()
    }


def save_state(path: Path, state: Dict[str, StoredBook]) -> None:
    payload = {book_id: book.to_dict() for book_id, book in state.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
