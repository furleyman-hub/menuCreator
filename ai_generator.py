"""
ai_generator.py — AI-powered meal schedule generation using Claude.

Uses Claude claude-opus-4-6 to suggest creative, varied dinner ideas within the
family's dietary rules, rather than drawing only from the static meals.yaml catalog.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Tuple

import anthropic
from pydantic import BaseModel

from models import (
    Config, ScheduleDay, AnchorRule,
    FAST_FOOD_LABEL, WEEKDAY_NAMES,
)


# ---------------------------------------------------------------------------
# Pydantic schema for structured AI output
# ---------------------------------------------------------------------------

class _AIMealDay(BaseModel):
    date: str       # YYYY-MM-DD
    meal_name: str  # Specific, descriptive name e.g. "Instant Pot Korean Beef Bulgogi + Rice"
    notes: str      # One-sentence prep/serving tip


class _AIMealPlan(BaseModel):
    meals: List[_AIMealDay]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_ai_schedule(
    dates: List[date],
    config: Config,
    locked_days: Dict[date, ScheduleDay],
    api_key: str = "",
) -> Tuple[List[ScheduleDay], List[str]]:
    """
    Generate a creative dinner plan for *dates* using Claude.

    Fixed anchors (Sunday soup, Thursday fast food) are applied directly.
    All other days are handed to Claude to fill creatively within the
    family's dietary rules and equipment constraints.

    Returns (schedule, warnings) matching the same shape as
    scheduler.generate_schedule().
    """
    anchor_index: Dict[int, AnchorRule] = {
        ar.weekday: ar for ar in config.anchor_rules if ar.enabled
    }

    schedule: List[ScheduleDay] = []
    ai_dates: List[date] = []
    warnings: List[str] = []

    # ── Pass 1: handle locked + fixed-anchor days ────────────────────────────
    for d in dates:
        if d in locked_days:
            day = locked_days[d]
            day.locked = True
            schedule.append(day)
            continue

        anchor = anchor_index.get(d.weekday())
        if anchor and anchor.fixed_name:
            schedule.append(ScheduleDay(
                date=d,
                meal_name=anchor.label,
                is_anchor=True,
                is_fast_food=(anchor.label == FAST_FOOD_LABEL),
                notes=anchor.description,
            ))
            continue

        ai_dates.append(d)

    if not ai_dates:
        schedule.sort(key=lambda s: s.date)
        return schedule, warnings

    # ── Pass 2: ask Claude for the remaining days ────────────────────────────
    date_lines: List[str] = []
    for d in ai_dates:
        anchor = anchor_index.get(d.weekday())
        constraint = ""
        if anchor and not anchor.fixed_name:
            if "soup" in (anchor.require_tags or []):
                constraint = "  ← MUST BE A SOUP"
            elif anchor.require_make_ahead:
                constraint = "  ← MAKE-AHEAD: fully cooked the previous evening, served this day"
        date_lines.append(f"  {d.isoformat()} ({d.strftime('%A')}){constraint}")

    system_prompt = (
        "You are an enthusiastic family meal planner who loves suggesting creative, "
        "globally-inspired dinners that are easy to make with small kitchen appliances. "
        "You always respect the family's dietary rules strictly."
    )

    user_prompt = f"""Plan creative family dinners for these dates.

FAMILY: {config.people_served}

STRICT RULES — never violate:
• No pork or pork products
• No dairy (no cheese, milk, butter, cream, yogurt)
• No creamy sauces
• No breakfast-for-dinner dishes
• No fried rice
• Small appliances ONLY: air fryer, instant pot, slow cooker, rice cooker, toaster oven
  (no full-size oven baking)

CREATIVITY GUIDELINES:
• Vary cuisines broadly — Mexican, Korean, Thai, Mediterranean, Caribbean,
  Middle Eastern, Indian, Japanese, American, etc.
• Give each meal a specific, appetising name (e.g. "Instant Pot Chicken Tikka Masala"
  not just "chicken curry")
• Suggest dishes the family may not have tried before — be adventurous but
  kid-friendly (ages 10 and 13)
• Do NOT repeat the same protein or cuisine on back-to-back days
• For SOUP days, name the specific soup (e.g. "Slow Cooker Chicken Pozole Rojo")
• For MAKE-AHEAD days, choose something that reheats well the next day

DATES:
{chr(10).join(date_lines)}

Return exactly one entry per date in the meals array.
Each meal_name must include the cooking method and main protein/star ingredient.
Each notes field: one short sentence about prep or serving."""

    client = anthropic.Anthropic(api_key=api_key or None)

    response = client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_AIMealPlan,
    )

    ai_plan: _AIMealPlan = response.parsed_output
    ai_lookup: Dict[str, _AIMealDay] = {m.date: m for m in ai_plan.meals}

    # ── Pass 3: build ScheduleDay objects from AI results ────────────────────
    for d in ai_dates:
        ai_meal = ai_lookup.get(d.isoformat())
        if ai_meal:
            anchor = anchor_index.get(d.weekday())
            schedule.append(ScheduleDay(
                date=d,
                meal_name=ai_meal.meal_name,
                is_anchor=(anchor is not None),
                notes=ai_meal.notes,
            ))
        else:
            warnings.append(f"{d:%b %d}: AI did not return a meal for this date.")
            schedule.append(ScheduleDay(
                date=d,
                meal_name="[No meal suggested]",
                warning="AI did not return a meal for this date.",
            ))

    schedule.sort(key=lambda s: s.date)
    return schedule, warnings
