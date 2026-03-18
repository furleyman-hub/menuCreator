"""
ai_generator.py — AI-powered meal schedule generation using OpenAI.

Uses GPT-4o to suggest creative, varied dinner ideas within the family's
dietary rules, rather than drawing only from the static meals.yaml catalog.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Dict, List, Tuple

from openai import OpenAI

from models import (
    Config, ScheduleDay, AnchorRule,
    FAST_FOOD_LABEL, WEEKDAY_NAMES,
)


def generate_ai_schedule(
    dates: List[date],
    config: Config,
    locked_days: Dict[date, ScheduleDay],
    api_key: str = "",
) -> Tuple[List[ScheduleDay], List[str]]:
    """
    Generate a creative dinner plan for *dates* using OpenAI.

    Fixed anchors (Sunday soup, Thursday fast food) are applied directly.
    All other days are handed to GPT-4o to fill creatively within the
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

    # ── Pass 2: ask GPT-4o for the remaining days ────────────────────────────
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
        "You always respect the family's dietary rules strictly. "
        "You respond only with valid JSON."
    )

    user_prompt = f"""Plan creative family dinners for these dates.

FAMILY: {config.people_served}

STRICT RULES — never violate:
• No pork or pork products
• No dairy (no cheese, milk, butter, cream, yogurt)
• No creamy sauces
• No breakfast-for-dinner dishes
• No fried rice
• No seafood except salmon (no shrimp, fish other than salmon, crab, lobster, clams, etc.)
• Salmon is a rare treat — use it AT MOST ONCE across the entire set of dates provided,
  and only if no salmon appeared in the previous week. Default to NOT using salmon.
• No spicy food — mild and family-friendly only
• Small appliances ONLY: air fryer, instant pot, slow cooker, rice cooker, toaster oven
  (no full-size oven baking)

CREATIVITY GUIDELINES:
• Vary cuisines BROADLY across the full week — spread across different regions so no
  single cuisine dominates. Aim for a balanced mix such as:
  Classic American, Italian, Mexican, Greek/Mediterranean, French, Japanese,
  Indian, Caribbean, Middle Eastern, Chinese, Thai, Moroccan, Korean, etc.
• Do NOT default to Asian or North African cuisines more than 1-2 times per week —
  include plenty of European and classic American dishes
• Give each meal a specific, appetising name (e.g. "Instant Pot Chicken Tikka Masala"
  not just "chicken curry")
• Suggest dishes the family may not have tried before — be adventurous but
  kid-friendly (ages 10 and 13)
• Do NOT repeat the same protein or cuisine on back-to-back days
• For SOUP days, name the specific soup (e.g. "Slow Cooker Chicken Pozole Rojo")
• For MAKE-AHEAD days, choose something that reheats well the next day

DATES:
{chr(10).join(date_lines)}

Respond with a JSON object in exactly this format:
{{
  "meals": [
    {{"date": "YYYY-MM-DD", "meal_name": "...", "notes": "one sentence prep/serving tip"}},
    ...
  ]
}}

Return exactly one entry per date. Each meal_name must include the cooking method
and main protein/star ingredient."""

    client = OpenAI(api_key=api_key or None)

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    ai_lookup: Dict[str, dict] = {m["date"]: m for m in data.get("meals", [])}

    # ── Pass 3: build ScheduleDay objects from AI results ────────────────────
    for d in ai_dates:
        ai_meal = ai_lookup.get(d.isoformat())
        if ai_meal:
            anchor = anchor_index.get(d.weekday())
            schedule.append(ScheduleDay(
                date=d,
                meal_name=ai_meal["meal_name"],
                is_anchor=(anchor is not None),
                notes=ai_meal.get("notes", ""),
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
