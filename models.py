"""
models.py — Data models for the Dinner Scheduler app.

All models use Python dataclasses for simplicity and JSON/YAML friendliness.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import date


@dataclass
class Meal:
    """A single meal in the candidate database."""

    name: str
    tags: List[str] = field(default_factory=list)        # e.g. ['chicken', 'italian', 'quick']
    equipment: List[str] = field(default_factory=list)   # e.g. ['air_fryer', 'instant_pot']

    # Dietary / restriction flags
    contains_pork: bool = False
    contains_dairy: bool = False
    creamy: bool = False        # creamy sauces; treated like dairy
    breakfast: bool = False     # breakfast-for-dinner items
    fried_rice: bool = False

    # Scheduling flags
    make_ahead_ok: bool = False      # can be cooked ahead, reheated Monday
    leftover_friendly: bool = False  # works well as next-day leftovers

    notes: str = ""  # free-form recipe / prep notes


@dataclass
class Restrictions:
    """
    Dietary and appliance restrictions.  Every flag is independently toggleable.
    """
    no_pork: bool = True
    no_dairy: bool = True
    no_creamy: bool = True         # no creamy sauces
    no_breakfast: bool = True      # no breakfast-for-dinner
    no_fried_rice: bool = True
    oven_avoid: bool = True        # avoid full-size oven; use small appliances only


@dataclass
class LeftoverStrategy:
    """Configuration for the optional 'leftovers night' weekly slot."""
    enabled: bool = False
    weekday: int = 2   # 0 = Monday … 6 = Sunday; default Wednesday


@dataclass
class AnchorRule:
    """
    Pins a weekday to either a fixed meal name *or* an auto-selected pool.

    Fields:
        weekday            – 0 = Monday … 6 = Sunday
        label              – Meal name (if fixed_name=True) or a display description
        description        – Extra human-readable note shown in the plan
        enabled            – If False the anchor is skipped; normal scheduling applies
        fixed_name         – True  → use `label` verbatim as the meal name
                             False → auto-select from eligible pool
        require_make_ahead – Restrict auto-select pool to make_ahead_ok meals
        require_tags       – Restrict auto-select pool to meals carrying ALL of
                             these tags (e.g. ["soup"] for Wednesday soup night).
                             Also used by the soup-cap logic to identify soup anchors.
    """
    weekday: int
    label: str
    description: str = ""
    enabled: bool = True
    fixed_name: bool = True
    require_make_ahead: bool = False
    require_tags: List[str] = field(default_factory=list)


@dataclass
class Config:
    """Top-level application configuration (persisted to config.yaml)."""
    dinner_time: str = "18:00"                 # HH:MM, 24-hour
    timezone: str = "America/New_York"
    event_duration_minutes: int = 60
    random_seed: int = 42                       # deterministic generation
    people_served: str = "1 adult + 2 boys (ages 10 and 13) — plan as 3 adults"
    max_soups_per_week: int = 2                 # cap on soup meals per calendar week

    restrictions: Restrictions = field(default_factory=Restrictions)
    leftover_strategy: LeftoverStrategy = field(default_factory=LeftoverStrategy)
    anchor_rules: List[AnchorRule] = field(default_factory=list)

    # Master "already used / excluded" list – stored here for single-file simplicity
    excluded_meals: List[str] = field(default_factory=list)


@dataclass
class ScheduleDay:
    """One day's entry in the generated dinner plan."""
    date: date
    meal_name: str

    # State flags
    locked: bool = False        # user-locked; survives "Regenerate"
    is_anchor: bool = False     # assigned by an AnchorRule
    is_fast_food: bool = False  # Thursday no-cook placeholder
    is_leftovers: bool = False  # leftovers-night placeholder

    warning: str = ""   # surfaced in the UI if something is wrong
    notes: str = ""     # meal notes or anchor description


# ---------------------------------------------------------------------------
# Weekday helpers
# ---------------------------------------------------------------------------

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Python weekday integers for anchor defaults
MONDAY    = 0
THURSDAY  = 3
SUNDAY    = 6

# Labels used for placeholder events (fast-food / leftovers)
FAST_FOOD_LABEL  = "Fast Food / Pizza Night"
LEFTOVERS_LABEL  = "Leftovers Night"
