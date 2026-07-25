from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from goodreads_calendar_sync.state import load_state, save_state
from goodreads_calendar_sync.types import StoredBook


def test_state_roundtrip():
    with TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / 'state.json'
        record = StoredBook(
            goodreads_id='12345',
            title='Example Book',
            author='Jane Doe',
            release_date=None,
            isbn='9781234567890',
            series='Example Series',
            calendar_uid='goodreads-12345',
            last_checked=datetime.utcnow(),
        )
        save_state(state_path, {'12345': record})
        loaded = load_state(state_path)
        assert '12345' in loaded
        assert loaded['12345'].title == 'Example Book'
        assert loaded['12345'].isbn == '9781234567890'
