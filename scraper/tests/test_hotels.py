"""Coverage for the --hotels resolver."""

import json
from pathlib import Path

import pytest

from jobs.hotels import resolve_hotels


@pytest.fixture
def hotels_file(tmp_path: Path) -> Path:
    p = tmp_path / "hotels.json"
    p.write_text(
        json.dumps(
            {
                "defaults": {"compset_id": 1, "los": 7, "persons": 2},
                "hotels": [
                    {"hotel_id": "100", "name": "Alpha"},
                    {"hotel_id": "200", "name": "Bravo"},
                    {"hotel_id": "300", "name": "Charlie"},
                ],
            }
        )
    )
    return p


class TestResolveHotels:
    def test_portfolio_returns_all_sorted(self, hotels_file):
        assert resolve_hotels("portfolio", hotels_file=hotels_file) == ["100", "200", "300"]

    def test_all_alias_returns_all_sorted(self, hotels_file):
        assert resolve_hotels("all", hotels_file=hotels_file) == ["100", "200", "300"]

    def test_explicit_csv_returns_in_input_order(self, hotels_file):
        assert resolve_hotels("200,100", hotels_file=hotels_file) == ["200", "100"]

    def test_explicit_id_not_in_portfolio_raises(self, hotels_file):
        with pytest.raises(ValueError, match="not in portfolio"):
            resolve_hotels("999", hotels_file=hotels_file)

    def test_file_form(self, hotels_file, tmp_path):
        other = tmp_path / "other.json"
        other.write_text(json.dumps({"hotels": [{"hotel_id": "200", "name": "Bravo"}]}))
        assert resolve_hotels(f"file:{other}", hotels_file=hotels_file) == ["200"]

    def test_file_with_unknown_id_raises(self, hotels_file, tmp_path):
        other = tmp_path / "other.json"
        other.write_text(json.dumps({"hotels": [{"hotel_id": "999", "name": "Unknown"}]}))
        with pytest.raises(ValueError, match="not in portfolio"):
            resolve_hotels(f"file:{other}", hotels_file=hotels_file)
