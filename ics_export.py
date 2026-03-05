"""
ics_export.py — Generate a standards-compliant iCalendar (.ics) file
from a list of ScheduleDay objects.

Events are all-day (DATE value, no time component).
"""

from __future__ import annotations

import calendar as cal_mod
import hashlib
from datetime import date, timedelta
from typing import List

from icalendar import Calendar, Event

from models import ScheduleDay


def _build_calendar(label: str) -> Calendar:
    """Create a bare VCALENDAR with standard properties."""
    cal = Calendar()
    cal.add("prodid", "-//Dinner Scheduler//menuCreator 1.0//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", label)
    return cal


def _make_event(day: ScheduleDay, people_served: str) -> Event:
    """Build a single all-day VEVENT for *day*."""
    event = Event()

    # All-day: pass date objects → icalendar emits DTSTART;VALUE=DATE:YYYYMMDD
    event.add("dtstart", day.date)
    event.add("dtend",   day.date + timedelta(days=1))  # exclusive end

    event.add("summary", f"Dinner: {day.meal_name}")

    # Description
    desc_lines: List[str] = []
    if day.notes:
        desc_lines.append(f"Notes: {day.notes}")
    if day.is_anchor and not day.is_fast_food:
        desc_lines.append("Type: Weekly anchor meal")
    if day.is_fast_food:
        desc_lines.append("Type: Fast food / pizza night (no cooking)")
    if day.is_leftovers:
        desc_lines.append("Type: Leftovers night")
    if day.locked:
        desc_lines.append("(User-locked meal)")
    if day.warning:
        desc_lines.append(f"WARNING: {day.warning}")
    desc_lines.append(f"Servings: {people_served}")
    event.add("description", "\n".join(desc_lines))

    # Deterministic UID — re-exporting won't create duplicates in Google Calendar
    uid_hash = hashlib.md5(
        f"{day.date.isoformat()}-dinner@menuCreator".encode()
    ).hexdigest()[:8]
    event.add("uid", f"{day.date.isoformat()}-{uid_hash}@menuCreator")

    return event


def generate_ics(
    schedule: List[ScheduleDay],
    people_served: str,
    label: str,
) -> bytes:
    """
    Build a VCALENDAR with one all-day VEVENT per schedule day.

    Parameters
    ----------
    schedule      : days to include (can be the full month or a single week).
    people_served : stored in each event's description.
    label         : calendar display name, e.g. "Family Dinners — March 2025".
    """
    cal = _build_calendar(label)
    for day in schedule:
        cal.add_component(_make_event(day, people_served))
    return cal.to_ical()


def week_ranges(schedule: List[ScheduleDay]) -> List[tuple[int, List[ScheduleDay]]]:
    """
    Return [(iso_week_number, [ScheduleDay, ...]), ...] sorted by week.
    Used by the UI to offer per-week download buttons.
    """
    from collections import defaultdict
    buckets: dict[int, List[ScheduleDay]] = defaultdict(list)
    for day in schedule:
        buckets[day.date.isocalendar()[1]].append(day)
    return sorted(buckets.items())


# ---------------------------------------------------------------------------
# Self-test (run: python ics_export.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import storage
    import scheduler as sched_mod

    print("=== ics_export.py self-test ===")

    cfg   = storage.load_config()
    meals = storage.load_meals()

    schedule, _ = sched_mod.generate_schedule(2025, 3, meals, cfg)
    label = "Family Dinners — March 2025"
    ics_bytes = generate_ics(schedule, cfg.people_served, label)

    assert b"BEGIN:VCALENDAR" in ics_bytes, "Missing VCALENDAR"
    assert b"BEGIN:VEVENT"    in ics_bytes, "Missing VEVENT"
    assert b"DTSTART;VALUE=DATE" in ics_bytes, "Events must be all-day (VALUE=DATE)"
    assert b"DTEND;VALUE=DATE"   in ics_bytes, "Missing DTEND"
    assert b"SUMMARY:Dinner:"    in ics_bytes, "Missing SUMMARY"

    print(f"Events: {ics_bytes.count(b'BEGIN:VEVENT')}")
    print(f"All-day format confirmed (VALUE=DATE present)")

    # Weekly split test
    weeks = week_ranges(schedule)
    print(f"Weeks: {len(weeks)}")
    for wk, days in weeks:
        print(f"  Week {wk}: {days[0].date:%b %d} – {days[-1].date:%b %d} ({len(days)} days)")

    print("PASSED")
