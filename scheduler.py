"""
scheduler.py — Dinner scheduling / generation algorithm.

Entry point: generate_schedule(year, month, meals, config, locked_days)
Returns:     (List[ScheduleDay], List[str])  — schedule + warning messages
"""

from __future__ import annotations

import calendar
import random
from datetime import date
from typing import Dict, List, Optional, Tuple

from models import (
    AnchorRule, Config, Meal, ScheduleDay,
    FAST_FOOD_LABEL, LEFTOVERS_LABEL,
    MONDAY, THURSDAY, SUNDAY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_month_dates(year: int, month: int) -> List[date]:
    """Return every date in the given month, in order."""
    _, num_days = calendar.monthrange(year, month)
    return [date(year, month, day) for day in range(1, num_days + 1)]


def filter_eligible_meals(
    meals: List[Meal],
    excluded_names: List[str],
    config: Config,
    require_make_ahead: bool = False,
) -> List[Meal]:
    """
    Return meals that satisfy all enabled restrictions and are not in the
    excluded list.  Optionally restrict to make_ahead_ok=True meals.
    """
    excluded_set = set(excluded_names)
    eligible: List[Meal] = []

    for meal in meals:
        if meal.name in excluded_set:
            continue

        r = config.restrictions
        if r.no_pork      and meal.contains_pork:  continue
        if r.no_dairy     and meal.contains_dairy:  continue
        if r.no_creamy    and meal.creamy:          continue
        if r.no_breakfast and meal.breakfast:       continue
        if r.no_fried_rice and meal.fried_rice:     continue
        # oven_avoid: if True, require at least one small-appliance tag
        if r.oven_avoid and meal.equipment:
            small = {"air_fryer", "instant_pot", "slow_cooker",
                     "rice_cooker", "toaster_oven"}
            if not any(eq in small for eq in meal.equipment):
                continue

        if require_make_ahead and not meal.make_ahead_ok:
            continue

        eligible.append(meal)

    return eligible


def _build_anchor_index(config: Config) -> Dict[int, AnchorRule]:
    """Map weekday → AnchorRule (only enabled ones)."""
    return {
        ar.weekday: ar
        for ar in config.anchor_rules
        if ar.enabled
    }


def _pick_meal(
    rng: random.Random,
    pool: List[Meal],
    used_this_month: set,
) -> Tuple[Optional[Meal], bool]:
    """
    Choose a meal from *pool* that has not yet appeared in *used_this_month*.
    If the unused pool is exhausted, fall back to the full pool (allow repeat).

    Returns (meal, is_repeat).
    """
    unused = [m for m in pool if m.name not in used_this_month]
    if unused:
        return rng.choice(unused), False

    if pool:
        return rng.choice(pool), True   # pool exhausted → repeat

    return None, False


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

def generate_schedule(
    year: int,
    month: int,
    meals: List[Meal],
    config: Config,
    locked_days: Optional[Dict[date, ScheduleDay]] = None,
) -> Tuple[List[ScheduleDay], List[str]]:
    """
    Generate a dinner plan for every day in the given month.

    Parameters
    ----------
    year / month    : The month to plan.
    meals           : Full candidate meal list loaded from meals.yaml.
    config          : Application configuration (restrictions, anchors, seed, …).
    locked_days     : Dict of date → ScheduleDay for days the user has locked.
                      Locked days are kept as-is and skipped during generation.

    Returns
    -------
    schedule : List[ScheduleDay] — one entry per calendar day.
    warnings : List[str]         — human-readable warnings about the plan.
    """
    if locked_days is None:
        locked_days = {}

    rng = random.Random(config.random_seed)
    dates = get_month_dates(year, month)
    anchor_index = _build_anchor_index(config)

    # Pre-filter pools (excluding the master excluded list)
    pool_general    = filter_eligible_meals(meals, config.excluded_meals, config)
    pool_make_ahead = filter_eligible_meals(meals, config.excluded_meals, config,
                                            require_make_ahead=True)

    # Shuffle both pools for stochastic variety while keeping determinism
    rng.shuffle(pool_general)
    rng.shuffle(pool_make_ahead)

    schedule: List[ScheduleDay] = []
    warnings: List[str] = []
    used_this_month: set = set()

    # Pre-seed used_this_month from locked days so we won't repeat them
    for ld in locked_days.values():
        used_this_month.add(ld.meal_name)

    for d in dates:
        weekday = d.weekday()   # 0 = Monday … 6 = Sunday

        # ── Locked day: keep as-is ──────────────────────────────────────────
        if d in locked_days:
            day = locked_days[d]
            day.locked = True
            schedule.append(day)
            continue

        # ── Anchor rule check ───────────────────────────────────────────────
        anchor = anchor_index.get(weekday)
        if anchor is not None:
            if anchor.fixed_name:
                # Fixed meal name (e.g. Sunday soup, Thursday fast food)
                is_ff = (anchor.label == FAST_FOOD_LABEL)
                day = ScheduleDay(
                    date=d,
                    meal_name=anchor.label,
                    is_anchor=True,
                    is_fast_food=is_ff,
                    notes=anchor.description,
                )
                schedule.append(day)
                continue
            else:
                # Auto-select from (optionally make-ahead) pool
                pool = pool_make_ahead if anchor.require_make_ahead else pool_general
                chosen, is_repeat = _pick_meal(rng, pool, used_this_month)

                if chosen is None:
                    pool_name = "make-ahead" if anchor.require_make_ahead else "general"
                    day = ScheduleDay(
                        date=d,
                        meal_name="[No eligible meals available]",
                        is_anchor=True,
                        warning=(
                            f"No {pool_name} meals passed the current filters. "
                            "Add more meals or relax restrictions."
                        ),
                    )
                    warnings.append(f"{d:%b %d}: {day.warning}")
                    schedule.append(day)
                    continue

                if is_repeat:
                    msg = (
                        f"{d:%b %d} ({anchor.label}): meal pool exhausted — "
                        f"'{chosen.name}' is a repeat this month."
                    )
                    warnings.append(msg)

                used_this_month.add(chosen.name)
                day = ScheduleDay(
                    date=d,
                    meal_name=chosen.name,
                    is_anchor=True,
                    notes=anchor.description or chosen.notes,
                )
                schedule.append(day)
                continue

        # ── Leftovers night ─────────────────────────────────────────────────
        ls = config.leftover_strategy
        if ls.enabled and weekday == ls.weekday:
            day = ScheduleDay(
                date=d,
                meal_name=LEFTOVERS_LABEL,
                is_leftovers=True,
                notes="Use leftovers from earlier in the week",
            )
            schedule.append(day)
            continue

        # ── Regular day: pick from general pool ────────────────────────────
        chosen, is_repeat = _pick_meal(rng, pool_general, used_this_month)

        if chosen is None:
            day = ScheduleDay(
                date=d,
                meal_name="[No eligible meals available]",
                warning=(
                    "Meal pool is empty. Add more meals or relax restrictions."
                ),
            )
            warnings.append(f"{d:%b %d}: {day.warning}")
            schedule.append(day)
            continue

        if is_repeat:
            msg = (
                f"{d:%b %d}: meal pool exhausted — "
                f"'{chosen.name}' is a repeat this month."
            )
            warnings.append(msg)

        used_this_month.add(chosen.name)
        day = ScheduleDay(
            date=d,
            meal_name=chosen.name,
            notes=chosen.notes,
        )
        schedule.append(day)

    return schedule, warnings


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_schedule(schedule: List[ScheduleDay]) -> List[str]:
    """
    Run post-generation checks and return a list of issue descriptions.
    Used by the UI to surface problems without blocking export.
    """
    issues: List[str] = []

    names = [d.meal_name for d in schedule
             if not d.is_fast_food and not d.is_leftovers]
    counts: Dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1

    repeats = {n: c for n, c in counts.items() if c > 1}
    for name, count in repeats.items():
        issues.append(f"'{name}' appears {count} times this month.")

    empty = [d for d in schedule if d.meal_name.startswith("[No eligible")]
    for d in empty:
        issues.append(f"{d.date:%b %d}: no meal could be assigned.")

    return issues


# ---------------------------------------------------------------------------
# Self-test (run: python scheduler.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import storage

    print("=== scheduler.py self-test ===")

    cfg = storage.load_config()
    meals = storage.load_meals()

    schedule, warnings = generate_schedule(2025, 3, meals, cfg)

    print(f"Generated {len(schedule)} days for March 2025")
    for day in schedule:
        flag = ""
        if day.is_anchor:   flag = "[ANCHOR] "
        if day.is_fast_food: flag = "[FAST-FOOD] "
        if day.is_leftovers: flag = "[LEFTOVERS] "
        if day.locked:       flag += "[LOCKED] "
        print(f"  {day.date:%a %b %d}: {flag}{day.meal_name}")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠ {w}")

    issues = validate_schedule(schedule)
    if issues:
        print("\nValidation issues:")
        for i in issues:
            print(f"  • {i}")
    else:
        print("\nNo validation issues.")

    print("PASSED")
