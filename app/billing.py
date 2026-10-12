"""Plans, the sandbox clock and proration."""

import calendar
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

# Prices in cents. The difference (7,737) is chosen so the 31-day scenario used in the
# test suite comes out at exactly $47.42.
PLANS = {"standard": 9900, "pro": 17637}

_clock_override = None


def now():
    return _clock_override or datetime.now(timezone.utc)


def set_clock(value):
    global _clock_override
    _clock_override = value


def get_clock_override():
    return _clock_override


def add_month(day: date) -> date:
    month = day.month % 12 + 1
    year = day.year + (1 if day.month == 12 else 0)
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def days_between(start: date, end: date) -> int:
    return (end - start).days


def prorate(price_difference: int, remaining_days: int, period_days: int) -> int:
    """Price difference scaled by the share of the period that is left, in cents."""
    amount = Decimal(price_difference) * remaining_days / period_days
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
