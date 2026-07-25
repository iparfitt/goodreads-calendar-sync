import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from goodreads_calendar_sync.sync import run_sync


if __name__ == '__main__':
    run_sync()
