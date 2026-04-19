"""Make `scraper/` importable from tests without an installed package."""

import sys
from pathlib import Path

_SCRAPER = Path(__file__).resolve().parent.parent
if str(_SCRAPER) not in sys.path:
    sys.path.insert(0, str(_SCRAPER))
