"""Shared pay plausibility rules (the single Python definition; mirrored in frontend/src/utils/compensation.ts and the
`roleradar_pay_ranges` SQL function, with parity enforced by tests/fixtures/pay_rules.json).

A published figure is never edited. A range that cannot be real pay is *marked*, not corrected, so the original numbers
stay in the record and no display or filter treats them as pay:

* ``placeholder``      every amount is a token value ($1 - $2), the shape employers use to satisfy a pay-transparency form
* ``below_floor``      the posting states a period (e.g. annual) but the amounts are far too small for it ($38 - $58 "annual").
                       Which period was meant is NOT guessed.
* ``above_ceiling``    an amount no cash pay period can reach ($179,300,152 a year): a typo in the employer's data
* ``extreme_spread``   the top of the range is more than 10x the bottom: one end is a typo and we cannot tell which

Only currencies with a known magnitude (USD, CAD, AUD, GBP, EUR) are judged; other currencies are left as published.
"""
from __future__ import annotations

from typing import Optional

JUDGED_CURRENCIES = {"USD", "CAD", "AUD", "GBP", "EUR"}

# Lowest believable amount per stated period. With no stated period the smallest unit (hourly) applies.
FLOOR = {"year": 1000, "month": 100, "week": 25, "day": 5, "hour": 5, None: 5}
# Highest believable amount per period: about 3,000,000 a year, expressed in each period.
CEILING = {"year": 3_000_000, "month": 250_000, "week": 60_000, "day": 12_000, "hour": 1_500, None: 3_000_000}
MAX_SPREAD = 10
PLACEHOLDER_AT_MOST = 10

HOURS_PER_YEAR = 2080
_ANNUALIZE = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": HOURS_PER_YEAR}


def annualize(amount: float, interval: Optional[str]) -> Optional[float]:
    factor = _ANNUALIZE.get(interval or "")
    return amount * factor if factor else None


def pay_range_problem(minimum: Optional[float], maximum: Optional[float], currency: Optional[str], interval: Optional[str]) -> Optional[str]:
    """None when the range is believable pay; otherwise the reason it must not be shown or filtered on."""
    values = [v for v in (minimum, maximum) if isinstance(v, (int, float)) and v > 0]
    if not values:
        return "no_amount"
    low, high = min(values), max(values)
    if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > 0 and maximum > 0 and minimum > maximum:
        return "inverted"
    if currency and str(currency).upper() not in JUDGED_CURRENCIES:
        return None
    key = interval if interval in FLOOR else None
    if low < FLOOR[key]:
        return "placeholder" if high <= PLACEHOLDER_AT_MOST else "below_floor"
    if high > CEILING[key]:
        return "above_ceiling"
    if len(values) == 2 and high / low > MAX_SPREAD:
        return "extreme_spread"
    return None
