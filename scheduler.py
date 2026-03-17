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
    MONDAY, TUESDAY, THURSDAY, SUNDAY,
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
    require_tags: Optional[List[str]] = None,
) -> List[Meal]:
    """
    Return meals that satisfy all enabled restrictions and are not in the
    excluded list.

    Optional filters:
      require_make_ahead – only meals with make_ahead_ok=True
      require_tags       – only meals whose tags contain ALL listed tags
                           (e.g. ["soup"] for the Wednesday soup anchor)
    """
    excluded_set = set(excluded_names)
    eligible: List[Meal] = []

    for meal in meals:
        if meal.name in excluded_set:
            continue

        # Restrictions are always enforced (no toggles)
        if meal.contains_pork:   continue
        if meal.contains_dairy:  continue
        if meal.creamy:          continue
        if meal.breakfast:       continue
        if meal.fried_rice:      continue
        # oven_avoid: require at least one small-appliance tag
        if meal.equipment:
            small = {"air_fryer", "instant_pot", "slow_cooker",
                     "rice_cooker", "toaster_oven"}
            if not any(eq in small for eq in meal.equipment):
                continue

        if require_make_ahead and not meal.make_ahead_ok:
            continue

        if require_tags:
            if not all(tag in meal.tags for tag in require_tags):
                continue

        eligible.append(meal)

    return eligible


def _apply_boost(pool: List[Meal], boost: int) -> List[Meal]:
    """
    Return a new list where every favorite meal appears *boost* times and
    every non-favorite appears once.  This makes favorites proportionally
    more likely when rng.choice() samples the pool.

    The boost only affects *which* meal gets chosen on each pick; the
    deduplication in _pick_meal (via used_this_month) still prevents a
    favorite from dominating the whole month — it just raises the chance
    it gets the next available slot.
    """
    result: List[Meal] = []
    for meal in pool:
        result.extend([meal] * (boost if meal.favorite else 1))
    return result


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
    included_dates: Optional[set] = None,
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

    # ── Pre-filter base pools ────────────────────────────────────────────────
    pool_general    = filter_eligible_meals(meals, config.excluded_meals, config)
    pool_make_ahead = filter_eligible_meals(meals, config.excluded_meals, config,
                                            require_make_ahead=True)

    # Build per-anchor pools for auto-select anchors with require_tags.
    # Keyed by weekday integer so we can look them up cheaply inside the loop.
    anchor_pools: Dict[int, List[Meal]] = {}
    for ar in config.anchor_rules:
        if ar.enabled and not ar.fixed_name:
            ap = filter_eligible_meals(
                meals, config.excluded_meals, config,
                require_make_ahead=ar.require_make_ahead,
                require_tags=ar.require_tags if ar.require_tags else None,
            )
            anchor_pools[ar.weekday] = ap

    # Apply favorite boost: insert extra copies of favorite meals so they are
    # proportionally more likely to be chosen by rng.choice().
    # boost=3 means a favorite appears 3× as often as a non-favorite.
    boost = max(1, config.favorite_boost)
    pool_general    = _apply_boost(pool_general,    boost)
    pool_make_ahead = _apply_boost(pool_make_ahead, boost)
    anchor_pools    = {wd: _apply_boost(ap, boost) for wd, ap in anchor_pools.items()}

    # Shuffle pools for stochastic variety (deterministic via seed)
    rng.shuffle(pool_general)
    rng.shuffle(pool_make_ahead)
    for ap in anchor_pools.values():
        rng.shuffle(ap)

    # ── Pre-compute soup-anchor count per ISO week ───────────────────────────
    # An anchor "counts as soup" when its require_tags includes "soup" (applies
    # to both fixed and auto-select anchors, e.g. Sunday chicken soup and
    # Wednesday soup night).  This lets us cap soup meals on regular days.
    soup_anchors_per_week: Dict[int, int] = {}
    for d in dates:
        wk = d.isocalendar()[1]
        anchor = anchor_index.get(d.weekday())
        if anchor and _anchor_is_soup(anchor):
            soup_anchors_per_week[wk] = soup_anchors_per_week.get(wk, 0) + 1

    # Pool of non-soup meals for regular days in weeks that are at the soup cap
    pool_no_soup = [m for m in pool_general if "soup" not in m.tags]

    schedule: List[ScheduleDay] = []
    warnings: List[str] = []
    used_this_month: set = set()
    # Maps ISO week number → meal name cooked on Monday (for Tuesday reheat)
    monday_meal_by_week: Dict[int, str] = {}

    # Pre-seed used_this_month from locked days so we won't repeat them
    for ld in locked_days.values():
        used_this_month.add(ld.meal_name)

    for d in dates:
        if included_dates is not None and d not in included_dates:
            continue

        weekday = d.weekday()   # 0 = Monday … 6 = Sunday
        wk      = d.isocalendar()[1]

        # ── Locked day: keep as-is ──────────────────────────────────────────
        if d in locked_days:
            day = locked_days[d]
            day.locked = True
            schedule.append(day)
            continue

        # ── Tuesday: pick a different make-ahead meal (prepared Monday) ────────
        if weekday == TUESDAY and wk in monday_meal_by_week:
            chosen, is_repeat = _pick_meal(rng, pool_make_ahead, used_this_month)
            if chosen is None:
                chosen, is_repeat = _pick_meal(rng, pool_general, used_this_month)
            if chosen is not None:
                if is_repeat:
                    warnings.append(
                        f"{d:%b %d} (Tuesday): meal pool exhausted — "
                        f"'{chosen.name}' is a repeat this month."
                    )
                used_this_month.add(chosen.name)
                day = ScheduleDay(
                    date=d,
                    meal_name=chosen.name,
                    notes="Prepared on Monday",
                )
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
                # Auto-select from the anchor's tagged pool (or general pool).
                # If this anchor doesn't specifically require soups and the week
                # is already at the soup cap, strip soup-tagged meals from pool.
                pool = anchor_pools.get(weekday, pool_general)
                soups_this_week = soup_anchors_per_week.get(wk, 0)
                if (
                    "soup" not in anchor.require_tags
                    and soups_this_week >= config.max_soups_per_week
                    and config.max_soups_per_week > 0
                ):
                    pool = [m for m in pool if "soup" not in m.tags]
                chosen, is_repeat = _pick_meal(rng, pool, used_this_month)

                if chosen is None:
                    tag_desc = (
                        f"tagged [{', '.join(anchor.require_tags)}] "
                        if anchor.require_tags else ""
                    )
                    pool_desc = (
                        f"make-ahead {tag_desc}" if anchor.require_make_ahead
                        else tag_desc or "general"
                    )
                    day = ScheduleDay(
                        date=d,
                        meal_name="[No eligible meals available]",
                        is_anchor=True,
                        warning=(
                            f"No {pool_desc}meals passed the current filters. "
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
                # Record Monday anchor so Tuesday knows to pick a make-ahead meal
                if weekday == MONDAY:
                    monday_meal_by_week[wk] = chosen.name
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

        # ── Regular day: pick from general pool (with soup cap) ─────────────
        # If this week already has max_soups_per_week soup-anchor days,
        # exclude soup-tagged meals from the regular pool.
        soups_this_week = soup_anchors_per_week.get(wk, 0)
        if soups_this_week >= config.max_soups_per_week:
            regular_pool = pool_no_soup
        else:
            regular_pool = pool_general

        chosen, is_repeat = _pick_meal(rng, regular_pool, used_this_month)

        if chosen is None:
            day = ScheduleDay(
                date=d,
                meal_name="[No eligible meals available]",
                warning="Meal pool is empty. Add more meals or relax restrictions.",
            )
            warnings.append(f"{d:%b %d}: {day.warning}")
            schedule.append(day)
            continue

        if is_repeat:
            warnings.append(
                f"{d:%b %d}: meal pool exhausted — "
                f"'{chosen.name}' is a repeat this month."
            )

        used_this_month.add(chosen.name)
        day = ScheduleDay(
            date=d,
            meal_name=chosen.name,
            notes=chosen.notes,
        )
        schedule.append(day)

    return schedule, warnings


def _anchor_is_soup(anchor: AnchorRule) -> bool:
    """
    Return True if this anchor contributes a soup to its week's soup count.
    Matches anchors whose require_tags include 'soup', OR fixed anchors whose
    label contains 'soup' (case-insensitive) — covers the Sunday chicken soup.
    """
    if "soup" in anchor.require_tags:
        return True
    if anchor.fixed_name and "soup" in anchor.label.lower():
        return True
    return False


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
             if not d.is_fast_food and not d.is_leftovers and not d.is_reheat]
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
