"""Compute an all-in stay price from a Lighthouse rate cell.

Lighthouse returns `shop_value` (total for the stay) + three tax
components (`city_tax`, `vat`, `other_taxes`) each paired with a
`*_incl` flag that says whether the tax is already baked into
`shop_value`. We compute:

    all_in_price = shop_value
                 + (city_tax    if city_tax    and not city_tax_incl    else 0)
                 + (vat         if vat         and not vat_incl         else 0)
                 + (other_taxes if other_taxes and not other_taxes_incl else 0)

Guards (schema v3 §6 + client doc cross-source goal):
  - Null or zero shop_value → return None (don't fabricate; sold-out
    / missing cells carry message='general.missing' and deserve to
    stay NULL in the fact tables).
  - Non-USD currency → return None + log once; schema assumes USD.
  - `*_incl` is None (not explicitly True/False) → treat as excluded
    and ADD (safer for cross-source comparability; undercount is
    worse than overcount when comparing OTAs side-by-side).
  - String-form values like "0.00" → coerce via Decimal.
  - Negative tax → log, clamp to 0.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

_log = logging.getLogger(__name__)


def _as_decimal(v: Any) -> Decimal | None:
    """Coerce any numeric-ish input to Decimal; return None on failure/empty."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _clamp_nonneg(v: Decimal, label: str) -> Decimal:
    if v < 0:
        _log.warning("negative %s (%s) — clamping to 0", label, v)
        return Decimal(0)
    return v


def compute_all_in_price(cell: dict) -> Decimal | None:
    """Return all-in total for the cell, or None if it can't be computed."""
    shop = _as_decimal(cell.get("shop_value"))
    if shop is None or shop <= 0:
        return None

    currency = (cell.get("shop_currency") or cell.get("currency") or "").upper()
    if currency and currency != "USD":
        _log.warning("non-USD currency %r — skipping all_in_price", currency)
        return None

    total = _clamp_nonneg(shop, "shop_value")

    for tax_key, flag_key in (
        ("city_tax", "city_tax_incl"),
        ("vat", "vat_incl"),
        ("other_taxes", "other_taxes_incl"),
    ):
        tax = _as_decimal(cell.get(tax_key))
        if tax is None or tax == 0:
            continue
        tax = _clamp_nonneg(tax, tax_key)
        incl = cell.get(flag_key)
        # incl=None (unknown) is treated as excluded — conservative default.
        if incl is True:
            continue
        total += tax

    # Round to 2dp; the column is NUMERIC(10,2).
    return total.quantize(Decimal("0.01"))
