"""Jours-ouvrés calculation — a pure function, no Firestore access, so it's
trivial to unit test directly. Cahier des charges Module 6: "Week-ends et
jours fériés exclus automatiquement du décompte."
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models import HolidayDocument

_SATURDAY = 5
_SUNDAY = 6


def working_days_between(start: date, end: date, holidays: list[HolidayDocument]) -> int:
    """Count days in [start, end] (inclusive) that are neither a weekend
    nor a holiday. A recurring holiday matches every year by (month, day);
    a non-recurring (religious) holiday matches only its own
    (year, month, day) — see HolidayDocument's docstring.
    """
    recurring_month_days = {(h.month, h.day) for h in holidays if h.is_recurring}
    specific_dates = {
        (h.year, h.month, h.day) for h in holidays if not h.is_recurring and h.year
    }

    count = 0
    current = start
    while current <= end:
        is_weekend = current.weekday() in (_SATURDAY, _SUNDAY)
        is_holiday = (current.month, current.day) in recurring_month_days or (
            current.year,
            current.month,
            current.day,
        ) in specific_dates
        if not is_weekend and not is_holiday:
            count += 1
        current += timedelta(days=1)
    return count
