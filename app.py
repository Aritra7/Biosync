"""
Bio-Sync Streamlit UI
Three screens:
  1. Input panel (sidebar)
  2. Real-time agent activity log (while generating)
  3. Meal plan output (after generation)
"""

import os
import queue
import threading
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("USE_MOCK_APIS", "true")

from src.schemas import UserConstraints, MacroTargets
from src.pipeline import run_pipeline

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Bio-Sync: Budget Meal Planner",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
for key, default in {
    "result": None,
    "running": False,
    "log_lines": [],
    "error": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Sidebar — Screen 1: Input Panel
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🥗 Bio-Sync")
    st.caption("Budget-Constrained AI Meal Planner")
    st.divider()

    st.subheader("Macro Targets (per day)")
    col1, col2 = st.columns(2)
    with col1:
        protein_g = st.number_input("Protein (g)", min_value=0, max_value=500, value=150, step=5)
        fat_g = st.number_input("Fat (g)", min_value=0, max_value=300, value=55, step=5)
    with col2:
        carbs_g = st.number_input("Carbs (g)", min_value=0, max_value=600, value=180, step=5)
        calories_kcal = st.number_input("Max Calories (kcal)", min_value=500, max_value=5000, value=1800, step=50)

    st.divider()
    st.subheader("Budget & Location")
    daily_budget = st.slider("Daily Budget ($)", min_value=5.0, max_value=50.0, value=15.0, step=0.5)
    zip_code = st.text_input("ZIP Code", value="15213", max_chars=10)

    st.divider()
    st.subheader("Plan Settings")
    plan_duration = st.selectbox("Plan Duration", options=[1, 3, 7], format_func=lambda x: f"{x} day{'s' if x > 1 else ''}")
    meals_options = st.multiselect(
        "Meals per Day",
        options=["breakfast", "lunch", "dinner", "snack"],
        default=["breakfast", "lunch", "dinner"],
    )

    st.divider()
    st.subheader("Dietary Preferences")
    dietary_prefs = st.text_area(
        "Free-text constraints",
        value="No shellfish. Prefer simple, easy-to-cook meals.",
        height=80,
        placeholder="e.g. No shellfish, prefer Mediterranean style, lactose intolerant",
    )

    st.divider()
    generate_btn = st.button(
        "Generate Plan",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.running or not meals_options,
    )

# ---------------------------------------------------------------------------
# Pipeline runner (background thread)
# ---------------------------------------------------------------------------
def _run_pipeline_thread(constraints: UserConstraints, log_q: queue.Queue):
    try:
        def log_cb(msg: str):
            log_q.put(("log", msg))

        result = run_pipeline(constraints, log_callback=log_cb)
        log_q.put(("done", result))
    except Exception as e:
        log_q.put(("error", str(e)))


# ---------------------------------------------------------------------------
# Trigger pipeline on button click
# ---------------------------------------------------------------------------
if generate_btn and not st.session_state.running:
    if not zip_code.strip():
        st.sidebar.error("Please enter a ZIP code.")
    elif not meals_options:
        st.sidebar.error("Select at least one meal type.")
    else:
        constraints = UserConstraints(
            macro_targets=MacroTargets(
                protein_g=float(protein_g),
                carbs_g=float(carbs_g),
                fat_g=float(fat_g),
                calories_kcal=float(calories_kcal),
            ),
            daily_budget_usd=daily_budget,
            zip_code=zip_code.strip(),
            plan_duration_days=plan_duration,
            dietary_preferences=dietary_prefs.strip(),
            meals_per_day=meals_options,
        )
        st.session_state.result = None
        st.session_state.error = None
        st.session_state.log_lines = []
        st.session_state.running = True
        st.session_state._constraints = constraints

        log_q: queue.Queue = queue.Queue()
        st.session_state._log_q = log_q

        t = threading.Thread(
            target=_run_pipeline_thread,
            args=(constraints, log_q),
            daemon=True,
        )
        t.start()
        st.session_state._thread = t
        st.rerun()

# ---------------------------------------------------------------------------
# Screen 2: Real-time agent activity log
# ---------------------------------------------------------------------------
if st.session_state.running:
    st.title("Generating your meal plan...")

    log_container = st.container()

    with log_container:
        log_placeholder = st.empty()

    # Drain the queue and update display
    log_q: queue.Queue = st.session_state._log_q
    done = False

    while not done:
        try:
            msg_type, payload = log_q.get(timeout=0.3)
        except queue.Empty:
            # Queue empty but thread still running — re-render and wait
            break

        if msg_type == "log":
            st.session_state.log_lines.append(payload)
        elif msg_type == "done":
            st.session_state.result = payload
            st.session_state.running = False
            done = True
        elif msg_type == "error":
            st.session_state.error = payload
            st.session_state.running = False
            done = True

    # Render accumulated log
    log_text = "\n".join(st.session_state.log_lines)
    log_placeholder.code(log_text, language=None)

    if st.session_state.running:
        st.rerun()
    else:
        st.rerun()  # flip to results screen

# ---------------------------------------------------------------------------
# Helper: color-coded pass/fail badge
# ---------------------------------------------------------------------------
def _badge(ok: bool) -> str:
    return "✅" if ok else "❌"


def _delta_color(value: float, target: float, tolerance: float = 0.10) -> str:
    lo, hi = target * (1 - tolerance), target * (1 + tolerance)
    if lo <= value <= hi:
        return "normal"
    return "inverse"


# ---------------------------------------------------------------------------
# Screen 3: Meal Plan Output
# ---------------------------------------------------------------------------
if st.session_state.error:
    st.error(f"Pipeline error: {st.session_state.error}")
    if st.button("Try Again"):
        st.session_state.error = None
        st.rerun()

elif st.session_state.result is not None:
    result = st.session_state.result
    vr = result.validation_report
    constraints: UserConstraints = st.session_state._constraints

    # Header
    st.title("Your Meal Plan")
    status_icon = "✅" if vr.passed else "⚠️"
    st.caption(
        f"{status_icon} {'All constraints satisfied' if vr.passed else 'Some constraints not fully met'} "
        f"· {result.iterations_taken} iteration(s) · "
        f"Est. total cost: **${result.estimated_total_cost_usd:.2f}**"
    )

    # Top-level reset button
    if st.button("🔄 Generate New Plan", type="secondary"):
        st.session_state.result = None
        st.session_state.log_lines = []
        st.rerun()

    st.divider()

    # -----------------------------------------------------------------------
    # Day tabs
    # -----------------------------------------------------------------------
    day_tabs = st.tabs([f"Day {d.day}" for d in result.days])

    for tab, day in zip(day_tabs, result.days):
        with tab:
            dv = vr.day_validations[day.day - 1]

            # Daily summary metrics row
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric(
                "Protein",
                f"{day.daily_protein_g:.0f}g",
                f"target {constraints.macro_targets.protein_g:.0f}g",
                delta_color=_delta_color(day.daily_protein_g, constraints.macro_targets.protein_g),
            )
            m2.metric(
                "Carbs",
                f"{day.daily_carbs_g:.0f}g",
                f"target {constraints.macro_targets.carbs_g:.0f}g",
                delta_color=_delta_color(day.daily_carbs_g, constraints.macro_targets.carbs_g),
            )
            m3.metric(
                "Fat",
                f"{day.daily_fat_g:.0f}g",
                f"target {constraints.macro_targets.fat_g:.0f}g",
                delta_color=_delta_color(day.daily_fat_g, constraints.macro_targets.fat_g),
            )
            m4.metric(
                "Calories",
                f"{day.daily_calories_kcal:.0f} kcal",
                f"max {constraints.macro_targets.calories_kcal:.0f}",
                delta_color="normal" if dv.calories_ok else "inverse",
            )
            m5.metric(
                "Daily Cost",
                f"${day.daily_cost_usd:.2f}",
                f"budget ${constraints.daily_budget_usd:.2f}",
                delta_color="normal" if dv.budget_ok else "inverse",
            )

            # Validation issues banner
            if dv.issues:
                with st.expander(f"⚠️ {len(dv.issues)} constraint issue(s)", expanded=False):
                    for issue in dv.issues:
                        st.warning(issue)

            st.divider()

            # Per-meal cards
            for enriched_meal in day.meals:
                meal = enriched_meal.meal
                with st.expander(
                    f"**{meal.meal_type.capitalize()}** — {meal.recipe_name}  "
                    f"| {enriched_meal.verified_protein_g:.0f}g P · "
                    f"{enriched_meal.verified_carbs_g:.0f}g C · "
                    f"{enriched_meal.verified_fat_g:.0f}g F · "
                    f"{enriched_meal.verified_calories_kcal:.0f} kcal · "
                    f"${enriched_meal.verified_cost_usd:.2f}",
                    expanded=True,
                ):
                    col_left, col_right = st.columns([1, 1])

                    with col_left:
                        st.markdown("**Ingredients**")
                        rows = []
                        for ing in meal.ingredients:
                            cost = enriched_meal.per_ingredient_cost.get(ing.name, None)
                            cost_str = f"${cost:.2f}" if cost is not None else "—"
                            rows.append({
                                "Ingredient": ing.name,
                                "Amount": ing.quantity_description,
                                "Est. Cost": cost_str,
                            })
                        st.table(rows)

                    with col_right:
                        st.markdown("**Nutrition (USDA verified)**")
                        st.progress(
                            min(enriched_meal.verified_protein_g / max(constraints.macro_targets.protein_g, 1), 1.0),
                            text=f"Protein: {enriched_meal.verified_protein_g:.1f}g",
                        )
                        st.progress(
                            min(enriched_meal.verified_carbs_g / max(constraints.macro_targets.carbs_g, 1), 1.0),
                            text=f"Carbs: {enriched_meal.verified_carbs_g:.1f}g",
                        )
                        st.progress(
                            min(enriched_meal.verified_fat_g / max(constraints.macro_targets.fat_g, 1), 1.0),
                            text=f"Fat: {enriched_meal.verified_fat_g:.1f}g",
                        )
                        st.progress(
                            min(enriched_meal.verified_calories_kcal / max(constraints.macro_targets.calories_kcal, 1), 1.0),
                            text=f"Calories: {enriched_meal.verified_calories_kcal:.0f} kcal",
                        )

                    st.markdown("**Cooking Instructions**")
                    for i, step in enumerate(meal.cooking_instructions, 1):
                        st.markdown(f"{i}. {step}")

    st.divider()

    # -----------------------------------------------------------------------
    # Grocery list
    # -----------------------------------------------------------------------
    st.subheader("Aggregate Grocery List")
    st.caption(f"All ingredients across {len(result.days)} day(s) · Est. total: **${result.estimated_total_cost_usd:.2f}**")

    grocery_rows = []
    for ingredient, total_g in sorted(result.grocery_list.items()):
        grocery_rows.append({
            "Ingredient": ingredient.title(),
            "Total (g)": f"{total_g:.0f}g",
        })

    col_g1, col_g2 = st.columns([1, 2])
    with col_g1:
        st.table(grocery_rows)

    st.divider()

    # -----------------------------------------------------------------------
    # Agent log (collapsible)
    # -----------------------------------------------------------------------
    with st.expander("Agent Activity Log", expanded=False):
        st.code("\n".join(st.session_state.log_lines), language=None)

# ---------------------------------------------------------------------------
# Default landing screen (no result, not running)
# ---------------------------------------------------------------------------
elif not st.session_state.running:
    st.title("Bio-Sync")
    st.subheader("Budget-Constrained AI Meal Planner")
    st.markdown("""
    Bio-Sync uses a **multi-agent pipeline** to generate meal plans that are:
    - Grounded in real nutrition data from the **USDA FoodData Central** database
    - Priced using real grocery data from the **Kroger Product API**
    - Verified against your macro and budget targets by a **Critic agent**

    **How it works:**
    1. **Planner Agent** — generates a creative meal plan based on your constraints
    2. **Researcher Agent** — looks up real grocery prices for each ingredient
    3. **Nutritionist Agent** — verifies nutrition data via the USDA API
    4. **Critic Agent** — checks all constraints and requests revisions if needed

    Set your targets in the sidebar and click **Generate Plan** to start.
    """)

    st.info("Currently running with **mock grocery/nutrition data**. Set `USE_MOCK_APIS=false` in `.env` once your API keys are ready.")
