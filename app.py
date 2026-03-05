"""
app.py — Streamlit front-end for the Dinner Scheduler.

Run with:  streamlit run app.py

Tabs:
  📅  Plan            — editable calendar table + lock controls
  ⚙️  Rules/Settings  — edit config (restrictions, anchors, leftovers)
  🥘  Meals Database  — add / edit / delete meals and excluded list
  📤  Export          — download .ics for the selected month
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

import ics_export
import scheduler as sched_mod
import storage
from models import (
    AnchorRule, Config, LeftoverStrategy, Meal, Restrictions, ScheduleDay,
    FAST_FOOD_LABEL, LEFTOVERS_LABEL, WEEKDAY_NAMES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be the FIRST Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dinner Scheduler",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# Session-state initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _init() -> None:
    today = date.today()
    if "config" not in st.session_state:
        st.session_state.config = storage.load_config()
    if "meals" not in st.session_state:
        st.session_state.meals = storage.load_meals()
    if "schedule" not in st.session_state:
        st.session_state.schedule: Optional[List[ScheduleDay]] = None
    if "warnings" not in st.session_state:
        st.session_state.warnings: List[str] = []
    if "locked_days" not in st.session_state:
        st.session_state.locked_days: Dict[date, ScheduleDay] = {}
    if "sel_year" not in st.session_state:
        st.session_state.sel_year = today.year
    if "sel_month" not in st.session_state:
        st.session_state.sel_month = today.month


_init()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: schedule → DataFrame (for st.data_editor)
# ─────────────────────────────────────────────────────────────────────────────

def _type_label(day: ScheduleDay) -> str:
    if day.is_fast_food:  return "🍕 Fast Food"
    if day.is_anchor:     return "⚓ Anchor"
    if day.is_leftovers:  return "♻️ Leftovers"
    return "🥘 Regular"


def schedule_to_df(schedule: List[ScheduleDay]) -> pd.DataFrame:
    rows = []
    for day in schedule:
        rows.append({
            "date_iso":   day.date.isoformat(),          # hidden key
            "Date":       day.date.strftime("%a, %b %d"),
            "Meal":       day.meal_name,
            "Type":       _type_label(day),
            "Lock 🔒":    day.locked,
            "Notes":      day.notes,
            "⚠️":         day.warning,
        })
    return pd.DataFrame(rows)


def df_to_locked_days(
    df: pd.DataFrame,
    original_schedule: List[ScheduleDay],
) -> Dict[date, ScheduleDay]:
    """
    Read back edits from the data-editor DataFrame and return a dict of
    locked ScheduleDay objects to carry over into the next generation.
    """
    locked: Dict[date, ScheduleDay] = {}
    for i, row in df.iterrows():
        if row["Lock 🔒"]:
            orig = original_schedule[i]
            locked[orig.date] = ScheduleDay(
                date=orig.date,
                meal_name=row["Meal"],
                locked=True,
                is_anchor=orig.is_anchor,
                is_fast_food=orig.is_fast_food,
                is_leftovers=orig.is_leftovers,
                notes=row["Notes"],
            )
    return locked


def sync_df_to_schedule(
    df: pd.DataFrame,
    schedule: List[ScheduleDay],
) -> None:
    """Push data-editor edits (meal name, lock, notes) back into the schedule list."""
    for i, row in df.iterrows():
        if i < len(schedule):
            schedule[i].meal_name = row["Meal"]
            schedule[i].locked    = row["Lock 🔒"]
            schedule[i].notes     = row["Notes"]


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🍽️ Dinner Scheduler")
    st.caption("Family dinner planner + ICS export")
    st.divider()

    # Month / Year
    today = date.today()
    col_m, col_y = st.columns(2)
    with col_m:
        sel_month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            format_func=lambda m: calendar.month_abbr[m],
            index=st.session_state.sel_month - 1,
        )
    with col_y:
        year_options = list(range(today.year - 1, today.year + 4))
        sel_year = st.selectbox(
            "Year",
            options=year_options,
            index=year_options.index(st.session_state.sel_year)
            if st.session_state.sel_year in year_options else 1,
        )
    st.session_state.sel_month = sel_month
    st.session_state.sel_year  = sel_year

    st.divider()

    # Events are all-day — no dinner time or timezone needed
    cfg: Config = st.session_state.config
    seed = st.number_input(
        "Random Seed", value=int(cfg.random_seed), min_value=0, max_value=999999,
        help="Change the seed to get a different meal arrangement."
    )

    st.divider()

    # Generate button
    generate_clicked = st.button(
        "▶ Generate / Regenerate", type="primary", use_container_width=True
    )
    clear_clicked = st.button(
        "✖ Clear Schedule", use_container_width=True
    )

    if generate_clicked:
        # Persist sidebar settings to config
        cfg.random_seed = int(seed)
        storage.save_config(cfg)

        # Carry forward any locks from the current schedule display
        locked = st.session_state.locked_days.copy()
        # Also read the data-editor state if it has been rendered
        if st.session_state.schedule and "plan_editor" in st.session_state:
            editor_val = st.session_state.get("plan_editor")
            if editor_val is not None:
                try:
                    live_df = schedule_to_df(st.session_state.schedule)
                    # Apply edited rows
                    for idx, edits in editor_val.get("edited_rows", {}).items():
                        for col, val in edits.items():
                            live_df.at[int(idx), col] = val
                    locked = df_to_locked_days(live_df, st.session_state.schedule)
                except Exception:
                    pass  # fall back to existing locked_days

        # Run scheduler
        schedule, warnings = sched_mod.generate_schedule(
            year=st.session_state.sel_year,
            month=st.session_state.sel_month,
            meals=st.session_state.meals,
            config=cfg,
            locked_days=locked,
        )
        st.session_state.schedule     = schedule
        st.session_state.warnings     = warnings
        st.session_state.locked_days  = {
            d.date: d for d in schedule if d.locked
        }

    if clear_clicked:
        st.session_state.schedule    = None
        st.session_state.warnings    = []
        st.session_state.locked_days = {}

    # Status summary
    if st.session_state.schedule:
        total = len(st.session_state.schedule)
        locked_ct = sum(1 for d in st.session_state.schedule if d.locked)
        st.divider()
        st.caption(f"Plan: **{total}** days · **{locked_ct}** locked")
        if st.session_state.warnings:
            st.warning(f"{len(st.session_state.warnings)} warning(s) — see Plan tab")


# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_plan, tab_rules, tab_meals, tab_export = st.tabs([
    "📅 Plan",
    "⚙️ Rules / Settings",
    "🥘 Meals Database",
    "📤 Export",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Plan
# ══════════════════════════════════════════════════════════════════════════════

with tab_plan:
    month_label = f"{calendar.month_name[sel_month]} {sel_year}"
    st.header(f"📅 Dinner Plan — {month_label}")

    if st.session_state.schedule is None:
        st.info(
            "No plan generated yet. Select a month in the sidebar and click "
            "**▶ Generate / Regenerate**."
        )
    else:
        schedule = st.session_state.schedule

        # Warnings banner
        if st.session_state.warnings:
            with st.expander(
                f"⚠️ {len(st.session_state.warnings)} warning(s)", expanded=True
            ):
                for w in st.session_state.warnings:
                    st.warning(w)

        # Validation issues
        issues = sched_mod.validate_schedule(schedule)
        if issues:
            with st.expander(f"🔍 {len(issues)} validation issue(s)"):
                for issue in issues:
                    st.error(issue)

        # Legend
        st.markdown(
            "**Legend:** ⚓ Anchor · 🍕 Fast Food · ♻️ Leftovers · 🥘 Regular · "
            "🔒 Lock = keep this meal when regenerating"
        )

        # Build display DataFrame from current schedule
        display_df = schedule_to_df(schedule)

        # Editable table
        edited_df = st.data_editor(
            display_df,
            column_config={
                "date_iso":  st.column_config.TextColumn("_date_iso", disabled=True),
                "Date":      st.column_config.TextColumn("Date", disabled=True, width="medium"),
                "Meal":      st.column_config.TextColumn("Meal Name", width="large"),
                "Type":      st.column_config.TextColumn("Type", disabled=True, width="medium"),
                "Lock 🔒":   st.column_config.CheckboxColumn("Lock 🔒", width="small"),
                "Notes":     st.column_config.TextColumn("Notes", width="large"),
                "⚠️":        st.column_config.TextColumn("⚠️", disabled=True, width="small"),
            },
            column_order=["Date", "Meal", "Type", "Lock 🔒", "Notes", "⚠️"],
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="plan_editor",
        )

        # Sync edits back to the live schedule so ICS export reflects changes
        if edited_df is not None:
            sync_df_to_schedule(edited_df, schedule)
            # Update locked_days registry
            st.session_state.locked_days = df_to_locked_days(edited_df, schedule)

        # Week-summary view (collapsible)
        with st.expander("Week-by-week summary", expanded=False):
            current_week: List[str] = []
            week_rows = []
            week_header = []
            for day in schedule:
                wd = day.date.weekday()
                if wd == 0 and current_week:
                    week_rows.append(current_week)
                    current_week = []
                current_week.append(f"**{day.date.strftime('%a %d')}** — {day.meal_name}")
            if current_week:
                week_rows.append(current_week)

            for i, week in enumerate(week_rows, 1):
                st.markdown(f"#### Week {i}")
                for line in week:
                    st.markdown(f"- {line}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Rules / Settings
# ══════════════════════════════════════════════════════════════════════════════

with tab_rules:
    st.header("⚙️ Rules & Settings")
    cfg: Config = st.session_state.config

    with st.form("rules_form"):

        st.subheader("General")
        people_served = st.text_input("People served", value=cfg.people_served)

        st.subheader("Restrictions")
        st.caption("Toggle each restriction on or off.")
        col1, col2 = st.columns(2)
        with col1:
            no_pork      = st.checkbox("No pork",              value=cfg.restrictions.no_pork)
            no_dairy     = st.checkbox("No dairy",             value=cfg.restrictions.no_dairy)
            no_creamy    = st.checkbox("No creamy sauces",     value=cfg.restrictions.no_creamy)
        with col2:
            no_breakfast = st.checkbox("No breakfast-for-dinner", value=cfg.restrictions.no_breakfast)
            no_fried_rice = st.checkbox("No fried rice",       value=cfg.restrictions.no_fried_rice)
            oven_avoid   = st.checkbox(
                "Avoid full-size oven (use small appliances)",
                value=cfg.restrictions.oven_avoid,
            )

        st.subheader("Favorites")
        favorite_boost = st.number_input(
            "Favorite meal boost (×)",
            value=int(cfg.favorite_boost),
            min_value=1,
            max_value=10,
            help=(
                "Meals marked ⭐ Favorite appear this many times more often "
                "than regular meals when a day is being filled. "
                "E.g. 3× means a favorite is 3× as likely to be picked next. "
                "Favorites still only appear once per month before repeating."
            ),
        )

        st.subheader("Soup Cap")
        max_soups = st.number_input(
            "Max soups per week (0 = unlimited)",
            value=int(cfg.max_soups_per_week),
            min_value=0,
            max_value=7,
            help=(
                "Weeks with soup anchor days (Sunday, Wednesday) already fill this "
                "quota, so regular days won't be assigned additional soup meals. "
                "Set to 0 to disable the cap."
            ),
        )

        st.subheader("Leftover Night Strategy")
        ls_enabled = st.checkbox(
            "Enable 'Leftovers Night' (one day per week is auto-assigned leftovers)",
            value=cfg.leftover_strategy.enabled,
        )
        ls_weekday = st.selectbox(
            "Leftover night weekday",
            options=list(range(7)),
            format_func=lambda w: WEEKDAY_NAMES[w],
            index=cfg.leftover_strategy.weekday,
            disabled=not ls_enabled,
        )

        st.subheader("Anchor Rules")
        st.caption(
            "Anchor rules pin a weekday to a fixed meal or constrained pool. "
            "Disable an anchor to let the scheduler choose freely for that day."
        )
        anchor_data = []
        for ar in cfg.anchor_rules:
            anchor_data.append({
                "Weekday": WEEKDAY_NAMES[ar.weekday],
                "Label / Meal": ar.label,
                "Description": ar.description,
                "Enabled": ar.enabled,
                "Fixed Name": ar.fixed_name,
                "Require Make-Ahead": ar.require_make_ahead,
                "Require Tags": ", ".join(ar.require_tags),
                "_weekday_int": ar.weekday,
            })

        anchor_df = pd.DataFrame(anchor_data)
        edited_anchors = st.data_editor(
            anchor_df,
            column_config={
                "Weekday":            st.column_config.TextColumn(disabled=True),
                "Label / Meal":       st.column_config.TextColumn(width="large"),
                "Description":        st.column_config.TextColumn(width="large"),
                "Enabled":            st.column_config.CheckboxColumn(
                    help="Uncheck to disable this anchor (day becomes regular)."
                ),
                "Fixed Name":         st.column_config.CheckboxColumn(
                    help="Checked → label used as-is. "
                         "Unchecked → auto-select from pool."
                ),
                "Require Make-Ahead": st.column_config.CheckboxColumn(
                    help="Auto-select only from make_ahead_ok meals."
                ),
                "Require Tags":       st.column_config.TextColumn(
                    help="Comma-separated tags the auto-selected meal must have "
                         "(e.g. 'soup'). Leave blank for no tag filter.",
                    width="medium",
                ),
                "_weekday_int":       st.column_config.NumberColumn(disabled=True),
            },
            column_order=[
                "Weekday", "Label / Meal", "Description",
                "Enabled", "Fixed Name", "Require Make-Ahead", "Require Tags",
            ],
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="anchor_editor",
        )

        saved = st.form_submit_button("💾 Save Settings", type="primary")

    if saved:
        cfg.people_served = people_served
        cfg.restrictions = Restrictions(
            no_pork=no_pork,
            no_dairy=no_dairy,
            no_creamy=no_creamy,
            no_breakfast=no_breakfast,
            no_fried_rice=no_fried_rice,
            oven_avoid=oven_avoid,
        )
        cfg.leftover_strategy = LeftoverStrategy(
            enabled=ls_enabled,
            weekday=int(ls_weekday),
        )
        cfg.favorite_boost     = int(favorite_boost)
        cfg.max_soups_per_week = int(max_soups)

        # Rebuild anchor rules from the edited table
        new_anchors: List[AnchorRule] = []
        for _, row in edited_anchors.iterrows():
            wday = int(row["_weekday_int"]) if "_weekday_int" in row else 0
            raw_tags = str(row.get("Require Tags", ""))
            req_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            new_anchors.append(AnchorRule(
                weekday=wday,
                label=str(row["Label / Meal"]),
                description=str(row["Description"]) if row["Description"] else "",
                enabled=bool(row["Enabled"]),
                fixed_name=bool(row["Fixed Name"]),
                require_make_ahead=bool(row["Require Make-Ahead"]),
                require_tags=req_tags,
            ))
        cfg.anchor_rules = new_anchors

        storage.save_config(cfg)
        st.success("Settings saved to config.yaml ✓")
        st.rerun()

    # Show current seed
    st.info(
        f"**Random seed:** {cfg.random_seed}  "
        f"(change in the sidebar to get a different arrangement)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Meals Database
# ══════════════════════════════════════════════════════════════════════════════

with tab_meals:
    st.header("🥘 Meals Database")

    meals: List[Meal] = st.session_state.meals
    cfg: Config = st.session_state.config

    # ── Candidate meals ──────────────────────────────────────────────────────
    st.subheader("Candidate Meals")
    st.caption(
        "Add, edit, or delete meals. "
        "Changes are saved when you click **Save Meals**."
    )

    meal_rows = []
    for m in meals:
        meal_rows.append({
            "Name":             m.name,
            "Tags":             ", ".join(m.tags),
            "Equipment":        ", ".join(m.equipment),
            "Pork":             m.contains_pork,
            "Dairy":            m.contains_dairy,
            "Creamy":           m.creamy,
            "Breakfast":        m.breakfast,
            "Fried Rice":       m.fried_rice,
            "Favorite ⭐":      m.favorite,
            "Make-Ahead OK":    m.make_ahead_ok,
            "Leftover Friendly":m.leftover_friendly,
            "Notes":            m.notes,
        })
    meals_df = pd.DataFrame(meal_rows) if meal_rows else pd.DataFrame(
        columns=["Name", "Tags", "Equipment", "Pork", "Dairy", "Creamy",
                 "Breakfast", "Fried Rice", "Favorite ⭐", "Make-Ahead OK",
                 "Leftover Friendly", "Notes"]
    )

    edited_meals_df = st.data_editor(
        meals_df,
        column_config={
            "Name":              st.column_config.TextColumn(width="large"),
            "Tags":              st.column_config.TextColumn(
                help="Comma-separated tags, e.g. chicken, italian, quick",
                width="medium",
            ),
            "Equipment":         st.column_config.TextColumn(
                help="Comma-separated: air_fryer, instant_pot, slow_cooker, rice_cooker, toaster_oven",
                width="medium",
            ),
            "Pork":              st.column_config.CheckboxColumn("Pork?"),
            "Dairy":             st.column_config.CheckboxColumn("Dairy?"),
            "Creamy":            st.column_config.CheckboxColumn("Creamy?"),
            "Breakfast":         st.column_config.CheckboxColumn("Breakfast?"),
            "Fried Rice":        st.column_config.CheckboxColumn("Fried Rice?"),
            "Favorite ⭐":       st.column_config.CheckboxColumn(
                "Favorite ⭐",
                help="Checked meals appear more often in generation (see Favorite Boost in Settings).",
            ),
            "Make-Ahead OK":     st.column_config.CheckboxColumn("Make-Ahead"),
            "Leftover Friendly": st.column_config.CheckboxColumn("Leftovers"),
            "Notes":             st.column_config.TextColumn(width="large"),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="meals_editor",
    )

    col_save, col_reload = st.columns([1, 1])
    with col_save:
        if st.button("💾 Save Meals", type="primary"):
            new_meals: List[Meal] = []
            for _, row in edited_meals_df.iterrows():
                if not str(row["Name"]).strip():
                    continue  # skip blank rows
                new_meals.append(Meal(
                    name=str(row["Name"]).strip(),
                    tags=[t.strip() for t in str(row["Tags"]).split(",") if t.strip()],
                    equipment=[e.strip() for e in str(row["Equipment"]).split(",") if e.strip()],
                    contains_pork=bool(row["Pork"]),
                    contains_dairy=bool(row["Dairy"]),
                    creamy=bool(row["Creamy"]),
                    breakfast=bool(row["Breakfast"]),
                    fried_rice=bool(row["Fried Rice"]),
                    favorite=bool(row["Favorite ⭐"]),
                    make_ahead_ok=bool(row["Make-Ahead OK"]),
                    leftover_friendly=bool(row["Leftover Friendly"]),
                    notes=str(row["Notes"]) if row["Notes"] else "",
                ))
            storage.save_meals(new_meals)
            st.session_state.meals = new_meals
            st.success(f"Saved {len(new_meals)} meals to meals.yaml ✓")
            st.rerun()
    with col_reload:
        if st.button("🔄 Reload from File"):
            st.session_state.meals = storage.load_meals()
            st.success("Reloaded meals from meals.yaml ✓")
            st.rerun()

    # Stats
    st.divider()
    total_meals   = len(meals)
    ma_meals      = sum(1 for m in meals if m.make_ahead_ok)
    eligible      = sched_mod.filter_eligible_meals(meals, cfg.excluded_meals, cfg)
    eligible_ma   = sched_mod.filter_eligible_meals(meals, cfg.excluded_meals, cfg, require_make_ahead=True)
    st.markdown(
        f"**Library:** {total_meals} meals total · "
        f"{ma_meals} make-ahead-ok · "
        f"**Eligible** (current restrictions + excluded list): "
        f"{len(eligible)} general · {len(eligible_ma)} make-ahead"
    )

    # ── Excluded / Already-Used List ─────────────────────────────────────────
    st.subheader("Already-Used / Excluded Meals")
    st.caption(
        "Meals in this list are skipped during generation. "
        "Add a meal name here after you've served it."
    )

    excluded = cfg.excluded_meals
    excl_df = pd.DataFrame({"Meal Name": excluded})

    edited_excl_df = st.data_editor(
        excl_df,
        column_config={
            "Meal Name": st.column_config.TextColumn(width="large")
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="excluded_editor",
    )

    if st.button("💾 Save Excluded List"):
        new_excl = [
            str(row["Meal Name"]).strip()
            for _, row in edited_excl_df.iterrows()
            if str(row["Meal Name"]).strip()
        ]
        cfg.excluded_meals = new_excl
        storage.save_config(cfg)
        st.session_state.config = cfg
        st.success(f"Saved {len(new_excl)} excluded meals ✓")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Export
# ══════════════════════════════════════════════════════════════════════════════

with tab_export:
    st.header("📤 Export")
    cfg: Config = st.session_state.config

    month_label = f"{calendar.month_name[sel_month]} {sel_year}"

    if st.session_state.schedule is None:
        st.info(
            "Generate a plan first (sidebar → **▶ Generate / Regenerate**), "
            "then come back here to download the .ics file."
        )
    else:
        schedule = st.session_state.schedule

        st.markdown(
            "Events are exported as **all-day** entries. "
            "Import into Google Calendar, Apple Calendar, Outlook, or any app "
            "that supports the iCalendar format."
        )
        st.caption(f"{len(schedule)} events · Calendar: Family Dinners — {month_label}")

        # ── Full-month export ────────────────────────────────────────────────
        st.subheader(f"Full month — {month_label}")
        try:
            month_ics = ics_export.generate_ics(
                schedule=schedule,
                people_served=cfg.people_served,
                label=f"Family Dinners — {month_label}",
            )
            st.download_button(
                label=f"⬇️ Download {month_label} .ics",
                data=month_ics,
                file_name=f"dinner_plan_{sel_year}_{sel_month:02d}.ics",
                mime="text/calendar",
                type="primary",
                use_container_width=True,
                key="dl_full_month",
            )
            with st.expander("Preview ICS (first 40 lines)", expanded=False):
                st.code(
                    "\n".join(month_ics.decode("utf-8").splitlines()[:40]),
                    language="text",
                )
        except Exception as exc:
            st.error(f"Failed to generate ICS: {exc}")

        # ── Per-week exports ─────────────────────────────────────────────────
        st.divider()
        st.subheader("Individual weeks")
        st.caption("Download a separate .ics file for any single week.")

        try:
            weeks = ics_export.week_ranges(schedule)
            for wk_num, wk_days in weeks:
                wk_start = wk_days[0].date
                wk_end   = wk_days[-1].date
                wk_label = (
                    f"Week of {wk_start:%b %d} – {wk_end:%b %d, %Y}"
                    if wk_start.month != wk_end.month
                    else f"Week of {wk_start:%b %d} – {wk_end:%d, %Y}"
                )
                meal_preview = "  ·  ".join(
                    f"{d.date:%a}: {d.meal_name}" for d in wk_days
                )

                with st.expander(wk_label, expanded=False):
                    st.caption(meal_preview)
                    wk_ics = ics_export.generate_ics(
                        schedule=wk_days,
                        people_served=cfg.people_served,
                        label=f"Family Dinners — {wk_label}",
                    )
                    st.download_button(
                        label=f"⬇️ Download {wk_label} .ics",
                        data=wk_ics,
                        file_name=(
                            f"dinner_plan_{sel_year}_{sel_month:02d}"
                            f"_week{wk_num}.ics"
                        ),
                        mime="text/calendar",
                        key=f"dl_week_{wk_num}",
                    )
        except Exception as exc:
            st.error(f"Failed to generate weekly ICS: {exc}")

        # ── Plain-text export ────────────────────────────────────────────────
        st.divider()
        st.subheader("Plain-text Summary")
        lines = [f"Dinner Plan — {month_label}", "=" * 40]
        for day in schedule:
            lock_mark = " [LOCKED]" if day.locked else ""
            lines.append(f"{day.date:%a, %b %d}: {day.meal_name}{lock_mark}")
        plain_text = "\n".join(lines)

        st.download_button(
            label="⬇️ Download as .txt",
            data=plain_text,
            file_name=f"dinner_plan_{sel_year}_{sel_month:02d}.txt",
            mime="text/plain",
        )
        with st.expander("Preview text", expanded=False):
            st.text(plain_text)
