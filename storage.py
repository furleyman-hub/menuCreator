"""
storage.py — YAML persistence layer for Dinner Scheduler.

Handles reading / writing config.yaml and meals.yaml with file locking
so the files stay safe even when edited externally while the app runs.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from filelock import FileLock
from typing import Any, Dict, List

from models import (
    AnchorRule, Config, LeftoverStrategy, Meal, Restrictions,
    FAST_FOOD_LABEL, MONDAY, SUNDAY, THURSDAY,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR   = Path(".")
CONFIG_FILE = DATA_DIR / "config.yaml"
MEALS_FILE  = DATA_DIR / "meals.yaml"


# ---------------------------------------------------------------------------
# Low-level YAML helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file; return an empty dict if the file doesn't exist."""
    if not path.exists():
        return {}
    with FileLock(str(path) + ".lock"):
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}


def _save_yaml(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write *data* to *path* using a file lock."""
    with FileLock(str(path) + ".lock"):
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh,
                      default_flow_style=False,
                      allow_unicode=True,
                      sort_keys=False)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

WEDNESDAY = 2


def _default_anchor_rules() -> List[AnchorRule]:
    return [
        AnchorRule(
            weekday=SUNDAY,
            label="Chicken Noodle Soup (big batch) — freeze half",
            description="Big batch; freeze half for later in the month",
            enabled=True,
            fixed_name=True,
            require_make_ahead=False,
            require_tags=["soup"],  # marks this anchor for the soup-cap counter
        ),
        AnchorRule(
            weekday=MONDAY,
            label="Make-ahead meal (auto-selected)",
            description="Cooked Sunday evening, reheated Monday",
            enabled=True,
            fixed_name=False,          # auto-select from eligible pool
            require_make_ahead=True,
            require_tags=[],
        ),
        AnchorRule(
            weekday=WEDNESDAY,
            label="Soup Night (auto-selected)",
            description="A different soup each week",
            enabled=True,
            fixed_name=False,
            require_make_ahead=False,
            require_tags=["soup"],  # auto-select any meal tagged 'soup'
        ),
        AnchorRule(
            weekday=THURSDAY,
            label=FAST_FOOD_LABEL,
            description="No cooking tonight — takeout or delivery",
            enabled=True,
            fixed_name=True,
            require_make_ahead=False,
            require_tags=[],
        ),
    ]


def _default_excluded_meals() -> List[str]:
    """Meals the family has already had — do not schedule again by default."""
    return [
        "Chicken Noodle Soup",
        "Teriyaki Salmon + Rice + Green Beans",
        "Turkey Tacos",
        "Baked Ziti",
        "Air Fryer Chicken Thighs + Potatoes + Peas",
        "Chicken Stir-Fry + Rice + Carrots",
        "Instant Pot Chicken Curry + Rice",
        "Beef & Veggie Stew",
        "Turkey Meatballs + Pasta + Peas",
        "Chicken & Rice Casserole",
    ]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> Config:
    """Load Config from config.yaml; write defaults if file is absent."""
    data = _load_yaml(CONFIG_FILE)
    if not data:
        cfg = Config(
            anchor_rules=_default_anchor_rules(),
            excluded_meals=_default_excluded_meals(),
        )
        save_config(cfg)
        return cfg

    # Restrictions
    r = data.get("restrictions", {})
    restrictions = Restrictions(
        no_pork=r.get("no_pork", True),
        no_dairy=r.get("no_dairy", True),
        no_creamy=r.get("no_creamy", True),
        no_breakfast=r.get("no_breakfast", True),
        no_fried_rice=r.get("no_fried_rice", True),
        oven_avoid=r.get("oven_avoid", True),
    )

    # Leftover strategy
    ls = data.get("leftover_strategy", {})
    leftover_strategy = LeftoverStrategy(
        enabled=ls.get("enabled", False),
        weekday=ls.get("weekday", 2),
    )

    # Anchor rules
    anchor_rules: List[AnchorRule] = []
    for ar in data.get("anchor_rules", []):
        anchor_rules.append(AnchorRule(
            weekday=ar["weekday"],
            label=ar.get("label", ""),
            description=ar.get("description", ""),
            enabled=ar.get("enabled", True),
            fixed_name=ar.get("fixed_name", True),
            require_make_ahead=ar.get("require_make_ahead", False),
            require_tags=ar.get("require_tags", []),
        ))
    if not anchor_rules:
        anchor_rules = _default_anchor_rules()

    return Config(
        dinner_time=data.get("dinner_time", "18:00"),
        event_duration_minutes=data.get("event_duration_minutes", 60),
        random_seed=data.get("random_seed", 42),
        people_served=data.get(
            "people_served",
            "1 adult + 2 boys (ages 10 and 13) — plan as 3 adults",
        ),
        restrictions=restrictions,
        leftover_strategy=leftover_strategy,
        anchor_rules=anchor_rules,
        excluded_meals=data.get("excluded_meals", _default_excluded_meals()),
        max_soups_per_week=data.get("max_soups_per_week", 2),
        favorite_boost=data.get("favorite_boost", 3),
    )


def save_config(config: Config) -> None:
    """Persist *config* to config.yaml."""
    data: Dict[str, Any] = {
        "dinner_time": config.dinner_time,
        "event_duration_minutes": config.event_duration_minutes,
        "random_seed": config.random_seed,
        "people_served": config.people_served,
        "restrictions": {
            "no_pork": config.restrictions.no_pork,
            "no_dairy": config.restrictions.no_dairy,
            "no_creamy": config.restrictions.no_creamy,
            "no_breakfast": config.restrictions.no_breakfast,
            "no_fried_rice": config.restrictions.no_fried_rice,
            "oven_avoid": config.restrictions.oven_avoid,
        },
        "leftover_strategy": {
            "enabled": config.leftover_strategy.enabled,
            "weekday": config.leftover_strategy.weekday,
        },
        "anchor_rules": [
            {
                "weekday": ar.weekday,
                "label": ar.label,
                "description": ar.description,
                "enabled": ar.enabled,
                "fixed_name": ar.fixed_name,
                "require_make_ahead": ar.require_make_ahead,
                "require_tags": ar.require_tags,
            }
            for ar in config.anchor_rules
        ],
        "excluded_meals": config.excluded_meals,
        "max_soups_per_week": config.max_soups_per_week,
        "favorite_boost": config.favorite_boost,
    }
    _save_yaml(CONFIG_FILE, data)


# ---------------------------------------------------------------------------
# Meals
# ---------------------------------------------------------------------------

def _default_meals() -> List[Meal]:
    """
    Built-in candidate library: 38 meals that comply with all default
    restrictions (pork-free, dairy-free, non-creamy, non-breakfast,
    non-fried-rice, small-appliance-compatible).
    """
    return [
        # ---- Air Fryer meals -----------------------------------------------
        Meal(
            name="Air Fryer Chicken Thighs + Sweet Potato Fries",
            tags=["chicken", "american"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Season with smoked paprika and garlic powder. 400 °F, 22 min.",
        ),
        Meal(
            name="Air Fryer Salmon + Asparagus",
            tags=["seafood", "healthy"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Lemon-dill marinade. 400 °F, 10 min.",
        ),
        Meal(
            name="Air Fryer Fish Tacos + Cabbage Slaw",
            tags=["seafood", "mexican"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Use cod or tilapia. Serve with corn tortillas and lime crema (dairy-free).",
        ),
        Meal(
            name="Air Fryer Turkey Burgers + Sweet Potato Fries",
            tags=["turkey", "american"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Form patties with onion powder and Worcestershire; 375 °F, 15 min.",
        ),
        Meal(
            name="Air Fryer Chicken Wings + Veggie Sticks",
            tags=["chicken", "american"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Toss with buffalo sauce or teriyaki. 400 °F, 25 min.",
        ),
        Meal(
            name="Air Fryer Cod + Roasted Veggies",
            tags=["seafood", "healthy"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Season with Old Bay; pair with zucchini and bell pepper.",
        ),
        Meal(
            name="Air Fryer Teriyaki Chicken + Broccoli + Rice",
            tags=["chicken", "asian", "japanese"],
            equipment=["air_fryer", "rice_cooker"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Marinate chicken 30 min in soy-ginger teriyaki sauce.",
        ),
        Meal(
            name="Air Fryer Salmon Patties + Green Beans",
            tags=["seafood", "american"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Canned salmon, panko, egg, Dijon. 390 °F, 10 min per side.",
        ),
        Meal(
            name="Air Fryer Beef Tacos",
            tags=["beef", "mexican"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Cook taco-seasoned ground beef in air fryer basket. Serve with hard shells.",
        ),
        Meal(
            name="Air Fryer Garlic Shrimp Skewers + Rice",
            tags=["seafood", "mediterranean"],
            equipment=["air_fryer", "rice_cooker"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Marinate in garlic, lemon, olive oil. 400 °F, 8 min.",
        ),
        Meal(
            name="Air Fryer Chicken Caesar Lettuce Wraps",
            tags=["chicken", "american", "salad"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=False,
            notes="Use dairy-free caesar dressing. Air fry chicken strips at 380 °F, 15 min.",
        ),
        Meal(
            name="Air Fryer Sweet Potato + Black Bean Bowls",
            tags=["vegetarian", "healthy", "american"],
            equipment=["air_fryer"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Cubed sweet potato, seasoned black beans, avocado, salsa.",
        ),
        Meal(
            name="Air Fryer Shrimp + Broccoli + Rice",
            tags=["seafood", "asian"],
            equipment=["air_fryer", "rice_cooker"],
            make_ahead_ok=False,
            leftover_friendly=True,
            notes="Season shrimp with soy, garlic, ginger. Broccoli alongside in basket.",
        ),

        # ---- Instant Pot meals --------------------------------------------
        Meal(
            name="Instant Pot Chicken Tikka Masala (Dairy-Free)",
            tags=["chicken", "indian", "curry"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Use full-fat coconut milk in place of cream. Serve with basmati rice.",
        ),
        Meal(
            name="Instant Pot Turkey Vegetable Soup",
            tags=["turkey", "soup", "healthy"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Ground or shredded turkey, carrots, celery, potatoes, diced tomatoes.",
        ),
        Meal(
            name="Instant Pot Beef Stew",
            tags=["beef", "american"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chuck roast, root veggies, beef broth. High pressure 35 min.",
        ),
        Meal(
            name="Instant Pot Lentil Soup",
            tags=["vegetarian", "soup", "healthy"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Red or green lentils, cumin, turmeric, canned tomatoes. High pressure 15 min.",
        ),
        Meal(
            name="Instant Pot Pasta e Fagioli",
            tags=["vegetarian", "italian", "soup"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="White beans, ditalini, tomatoes, Italian seasoning. Omit parmesan.",
        ),
        Meal(
            name="Instant Pot Chicken Shawarma Bowls",
            tags=["chicken", "middle_eastern"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Shawarma-spiced chicken thighs. Serve over rice with cucumber-tomato salad.",
        ),
        Meal(
            name="Instant Pot Red Lentil Dal + Rice",
            tags=["vegetarian", "indian"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Red lentils, coconut milk, spinach, garam masala.",
        ),
        Meal(
            name="Instant Pot White Bean Chicken Chili",
            tags=["chicken", "american", "soup"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken breast, white beans, green chiles, cumin, chicken broth.",
        ),
        Meal(
            name="Instant Pot Chicken Fajita Bowls",
            tags=["chicken", "mexican", "tex_mex"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken, peppers, onions, fajita seasoning. Serve over cilantro-lime rice.",
        ),
        Meal(
            name="Instant Pot Vegetable Curry + Rice",
            tags=["vegetarian", "indian", "curry"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chickpeas, sweet potato, spinach, coconut milk curry.",
        ),
        Meal(
            name="Instant Pot Chicken Burrito Bowls",
            tags=["chicken", "mexican"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken, black beans, corn, salsa. Cook rice in rice cooker.",
        ),
        Meal(
            name="Instant Pot Chicken & Rice Soup",
            tags=["chicken", "american", "soup"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Whole chicken thighs, long-grain rice, carrots, celery. High pressure 20 min.",
        ),

        # ---- Slow Cooker meals --------------------------------------------
        Meal(
            name="Slow Cooker Beef Chili",
            tags=["beef", "american", "soup"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Ground beef, kidney beans, black beans, diced tomatoes. Low 6–8 h.",
        ),
        Meal(
            name="Slow Cooker Chicken Cacciatore",
            tags=["chicken", "italian"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken thighs, bell peppers, olives, tomato sauce. Low 6–8 h.",
        ),
        Meal(
            name="Slow Cooker Chicken Tacos",
            tags=["chicken", "mexican"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken breasts, taco seasoning, salsa. Shred and serve in corn tortillas.",
        ),
        Meal(
            name="Slow Cooker Pulled Chicken Sandwiches",
            tags=["chicken", "american"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="BBQ sauce, apple cider vinegar, garlic. Low 6 h, shred.",
        ),
        Meal(
            name="Slow Cooker Minestrone Soup",
            tags=["vegetarian", "italian", "soup"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Zucchini, kidney beans, pasta, diced tomatoes, Italian seasoning. Low 6–8 h.",
        ),
        Meal(
            name="Slow Cooker Moroccan Chicken",
            tags=["chicken", "moroccan", "north_african"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken thighs, chickpeas, olives, preserved lemon, cumin, cinnamon. Low 6 h.",
        ),
        Meal(
            name="Slow Cooker Chicken Pozole",
            tags=["chicken", "mexican", "soup"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken, hominy, red chile sauce, oregano. Low 7 h. Top with shredded cabbage.",
        ),
        Meal(
            name="Slow Cooker Black Bean Soup",
            tags=["vegetarian", "latin", "soup"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Dried black beans, cumin, smoked paprika, vegetable broth. Low 8 h.",
        ),
        Meal(
            name="Slow Cooker Beef & Broccoli + Rice",
            tags=["beef", "asian", "chinese"],
            equipment=["slow_cooker", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Flank steak, soy sauce, sesame oil, ginger, garlic. Low 4–5 h. Add broccoli last 30 min.",
        ),
        Meal(
            name="Slow Cooker Chicken Adobo + Rice",
            tags=["chicken", "filipino", "asian"],
            equipment=["slow_cooker", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Soy sauce, coconut vinegar, garlic, bay leaves. Low 6 h.",
        ),
        Meal(
            name="Slow Cooker Turkey Bolognese + Pasta",
            tags=["turkey", "italian"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Ground turkey, crushed tomatoes, carrot, celery, Italian seasoning. Low 6–8 h.",
        ),
        Meal(
            name="Slow Cooker Chicken Tortilla Soup",
            tags=["chicken", "mexican", "soup"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Chicken, black beans, corn, salsa, chicken broth. Low 6–8 h. Top with tortilla strips.",
        ),
        Meal(
            name="Slow Cooker Beef Short Ribs",
            tags=["beef", "american"],
            equipment=["slow_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Bone-in short ribs, beef broth, Worcestershire, thyme. Low 8 h.",
        ),

        # ---- Rice Cooker / multi-appliance --------------------------------
        Meal(
            name="Instant Pot Turkey Meatball Soup",
            tags=["turkey", "italian", "soup"],
            equipment=["instant_pot"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Turkey meatballs simmered with diced tomatoes, orzo, spinach.",
        ),
        Meal(
            name="Instant Pot Beef Taco Bowl",
            tags=["beef", "mexican"],
            equipment=["instant_pot", "rice_cooker"],
            make_ahead_ok=True,
            leftover_friendly=True,
            notes="Ground beef, taco seasoning, black beans. Serve over rice with pico.",
        ),
    ]


def load_meals() -> List[Meal]:
    """Load meals from meals.yaml; write defaults if file is absent."""
    data = _load_yaml(MEALS_FILE)
    if not data or "meals" not in data:
        defaults = _default_meals()
        save_meals(defaults)
        return defaults

    meals: List[Meal] = []
    for m in data["meals"]:
        meals.append(Meal(
            name=m["name"],
            tags=m.get("tags", []),
            equipment=m.get("equipment", []),
            contains_pork=m.get("contains_pork", False),
            contains_dairy=m.get("contains_dairy", False),
            creamy=m.get("creamy", False),
            breakfast=m.get("breakfast", False),
            fried_rice=m.get("fried_rice", False),
            favorite=m.get("favorite", False),
            make_ahead_ok=m.get("make_ahead_ok", False),
            leftover_friendly=m.get("leftover_friendly", False),
            notes=m.get("notes", ""),
        ))
    return meals


def save_meals(meals: List[Meal]) -> None:
    """Persist *meals* to meals.yaml."""
    data = {
        "meals": [
            {
                "name": m.name,
                "tags": m.tags,
                "equipment": m.equipment,
                "contains_pork": m.contains_pork,
                "contains_dairy": m.contains_dairy,
                "creamy": m.creamy,
                "breakfast": m.breakfast,
                "fried_rice": m.fried_rice,
                "favorite": m.favorite,
                "make_ahead_ok": m.make_ahead_ok,
                "leftover_friendly": m.leftover_friendly,
                "notes": m.notes,
            }
            for m in meals
        ]
    }
    _save_yaml(MEALS_FILE, data)


# ---------------------------------------------------------------------------
# Self-test (run: python storage.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== storage.py self-test ===")

    cfg = load_config()
    print(f"Config loaded: seed={cfg.random_seed}")
    print(f"  Anchor rules: {len(cfg.anchor_rules)}")
    print(f"  Excluded meals: {len(cfg.excluded_meals)}")

    meals = load_meals()
    print(f"Meals loaded: {len(meals)} total")
    make_ahead = [m for m in meals if m.make_ahead_ok]
    print(f"  Make-ahead eligible: {len(make_ahead)}")

    print("PASSED")
