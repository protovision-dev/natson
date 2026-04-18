"""Resolve the --hotels CLI expression into a concrete list of subscription
hotel_ids, and expose admin verbs for editing hotels.json.

Only the IDs present in hotels.json can drive /rates/ and /liveshop —
those are the "portfolio" (subscriptions we own).  Any other ID is a
compset competitor that can only be observed inside a portfolio scrape.
"""
from __future__ import annotations

import json
from pathlib import Path

_HOTELS_FILE_DEFAULT = Path(__file__).resolve().parent.parent / "hotels.json"


def _load(path: Path | None = None) -> dict:
    p = path or _HOTELS_FILE_DEFAULT
    return json.loads(p.read_text())


def _portfolio_ids(config: dict) -> list[str]:
    return [h["hotel_id"] for h in config.get("hotels", [])]


def resolve_hotels(expr: str, hotels_file: Path | None = None) -> list[str]:
    """Expand --hotels into a list of subscription IDs.

    Accepted forms:
        345062,345069    comma-separated explicit IDs
        portfolio        all entries in hotels.json
        file:path.json   same shape as hotels.json
    Raises ValueError if any explicit ID is not in the portfolio (since
    Lighthouse won't accept /liveshop for non-subscription IDs).
    """
    expr = expr.strip()
    config = _load(hotels_file)
    portfolio = set(_portfolio_ids(config))

    if expr == "portfolio" or expr == "all":
        return sorted(portfolio)

    if expr.startswith("file:"):
        other = _load(Path(expr[len("file:"):]))
        ids = _portfolio_ids(other)
        missing = [i for i in ids if i not in portfolio]
        if missing:
            raise ValueError(
                f"hotels from {expr} not in portfolio (no subscription access): {missing}"
            )
        return ids

    ids = [p.strip() for p in expr.split(",") if p.strip()]
    missing = [i for i in ids if i not in portfolio]
    if missing:
        raise ValueError(
            f"hotel_id(s) not in portfolio (no subscription access): {missing}"
        )
    return ids


def get_hotel_metadata(hotel_id: str, hotels_file: Path | None = None) -> dict:
    """Return the hotels.json entry for a subscription, merged with defaults."""
    config = _load(hotels_file)
    defaults = config.get("defaults", {})
    for h in config.get("hotels", []):
        if h["hotel_id"] == hotel_id:
            return {**defaults, **h}
    raise KeyError(hotel_id)


# --- admin verbs (called from scraper/admin.py in Phase 4) ----------------

def add_subscription(hotel_id: str, name: str, hotels_file: Path | None = None) -> None:
    p = hotels_file or _HOTELS_FILE_DEFAULT
    config = _load(p)
    if any(h["hotel_id"] == hotel_id for h in config["hotels"]):
        return
    config["hotels"].append({"hotel_id": hotel_id, "name": name})
    p.write_text(json.dumps(config, indent=2) + "\n")


def remove_subscription(hotel_id: str, hotels_file: Path | None = None) -> bool:
    p = hotels_file or _HOTELS_FILE_DEFAULT
    config = _load(p)
    before = len(config["hotels"])
    config["hotels"] = [h for h in config["hotels"] if h["hotel_id"] != hotel_id]
    if len(config["hotels"]) == before:
        return False
    p.write_text(json.dumps(config, indent=2) + "\n")
    return True
