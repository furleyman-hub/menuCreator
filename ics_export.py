"""
ics_export.py — Generate a standards-compliant iCalendar (.ics) file
from a list of ScheduleDay objects.

The returned bytes can be offered as a download in the Streamlit UI.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import List

import pytz
from icalendar import Calendar, Event, vText

from models import Config, ScheduleDay


def generate_ics(
    schedule: List[ScheduleDay],
    config: Config,
    month: int,
    year: int,
) -> bytes:
    """
    Build a VCALENDAR with one VEVENT per schedule day.

    Each event:
      • DTSTART / DTEND in the user-selected timezone
      • SUMMARY  = "Dinner: <meal name>"
      • DESCRIPTION includes notes, tags, and any warnings
      • UID is deterministic (date-based) so repeated exports don't create duplicates
    """
    try:
        tz = pytz.timezone(config.timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        tz = pytz.timezone("America/New_York")

    # Parse HH:MM dinner time
    try:
        hour, minute = map(int, config.dinner_time.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 18, 0

    # --- Build calendar ---
    cal = Calendar()
    cal.add("prodid", "-//Dinner Scheduler//menuCreator 1.0//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"Family Dinners — {_month_label(month, year)}")
    cal.add("x-wr-timezone", config.timezone)

    for day in schedule:
        event = Event()

        # DTSTART / DTEND
        naive_start = datetime(
            day.date.year, day.date.month, day.date.day, hour, minute
        )
        local_start = tz.localize(naive_start)
        local_end   = local_start + timedelta(minutes=config.event_duration_minutes)

        event.add("dtstart", local_start)
        event.add("dtend",   local_end)

        # SUMMARY
        event.add("summary", f"Dinner: {day.meal_name}")

        # DESCRIPTION
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
        desc_lines.append(f"Servings: {config.people_served}")

        if desc_lines:
            event.add("description", "\n".join(desc_lines))

        # UID — deterministic so re-exporting the same month doesn't create duplicates
        uid_seed = f"{year}-{month:02d}-{day.date.day:02d}-dinner@menuCreator"
        uid_hash = hashlib.md5(uid_seed.encode()).hexdigest()[:8]
        event.add("uid", f"{day.date.isoformat()}-{uid_hash}@menuCreator")

        cal.add_component(event)

    return cal.to_ical()


def _month_label(month: int, year: int) -> str:
    import calendar as cal_mod
    return f"{cal_mod.month_name[month]} {year}"


# ---------------------------------------------------------------------------
# Self-test (run: python ics_export.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import storage
    import scheduler as sched_mod

    print("=== ics_export.py self-test ===")

    cfg   = storage.load_config()
    meals = storage.load_meals()

    schedule, warnings = sched_mod.generate_schedule(2025, 3, meals, cfg)
    ics_bytes = generate_ics(schedule, cfg, month=3, year=2025)

    # Basic checks
    assert b"BEGIN:VCALENDAR" in ics_bytes, "Missing VCALENDAR block"
    assert b"BEGIN:VEVENT"    in ics_bytes, "Missing VEVENT block"
    assert b"DTSTART"         in ics_bytes, "Missing DTSTART"
    assert b"SUMMARY:Dinner:" in ics_bytes, "Missing SUMMARY"

    event_count = ics_bytes.count(b"BEGIN:VEVENT")
    print(f"Events generated: {event_count}")

    if warnings:
        print(f"Scheduler warnings: {len(warnings)}")

    print("PASSED")
