from datetime import date

from app.models import HolidayDocument
from app.services.working_days import working_days_between


def _holiday(**overrides) -> HolidayDocument:
    defaults = {"id": "h1", "name": "Test", "is_recurring": True, "month": 1, "day": 1, "year": None}
    defaults.update(overrides)
    return HolidayDocument(**defaults)


def test_recurring_holiday_excluded_every_year():
    recurring = _holiday(name="Fête du Travail", month=5, day=1, is_recurring=True)

    days_2026 = working_days_between(date(2026, 4, 29), date(2026, 5, 2), [recurring])
    days_2027 = working_days_between(date(2027, 4, 29), date(2027, 5, 2), [recurring])

    # 2026-04-29 Wed, 04-30 Thu, 05-01 Fri (holiday), 05-02 Sat (weekend)
    assert days_2026 == 2
    # 2027-04-29 Thu, 04-30 Fri, 05-01 Sat (weekend AND holiday), 05-02 Sun (weekend)
    assert days_2027 == 2


def test_non_recurring_holiday_excluded_only_in_its_own_year():
    eid = _holiday(name="Aïd al-Fitr", month=4, day=20, year=2026, is_recurring=False)

    days_2026 = working_days_between(date(2026, 4, 20), date(2026, 4, 20), [eid])
    days_2027 = working_days_between(date(2027, 4, 20), date(2027, 4, 20), [eid])

    assert days_2026 == 0  # excluded — Monday, matches the specific date
    assert days_2027 == 1  # not excluded — same (month, day), different year
