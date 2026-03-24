"""
Bio-Sync Human Evaluation Interface

Raters score generated meal plans on three dimensions (1–5 scale):
  - Culinary coherence: Do the meals make sense together?
  - Variety: Enough diversity across meals/days?
  - Practicality: Can a normal person actually make these?

Usage:
    # First generate plans to rate:
    python -m src.evaluation.generate_eval_plans

    # Then launch the rating interface:
    streamlit run human_eval.py

Ratings saved to eval_results/human_eval_ratings.json
"""

import os
import json
from datetime import datetime
import streamlit as st

PLANS_FILE = "eval_results/human_eval_plans.json"
RATINGS_FILE = "eval_results/human_eval_ratings.json"

st.set_page_config(page_title="Bio-Sync Human Eval", layout="wide")

# ---------------------------------------------------------------------------
# Load plans
# ---------------------------------------------------------------------------
if not os.path.exists(PLANS_FILE):
    st.error(
        f"No plans file found at `{PLANS_FILE}`. "
        "Run `python -m src.evaluation.generate_eval_plans` first to generate plans to rate."
    )
    st.stop()

with open(PLANS_FILE) as f:
    eval_plans = json.load(f)

# Load existing ratings
if os.path.exists(RATINGS_FILE):
    with open(RATINGS_FILE) as f:
        all_ratings: dict = json.load(f)
else:
    all_ratings = {}

# ---------------------------------------------------------------------------
# Sidebar — rater identity
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Human Evaluation")
    st.caption("Bio-Sync Plan Quality Rating")
    st.divider()
    rater_name = st.text_input("Your name / rater ID", placeholder="e.g. rater_1")
    st.divider()
    st.markdown("""
    **Rating scale:**
    - **1** — Very poor
    - **2** — Poor
    - **3** — Acceptable
    - **4** — Good
    - **5** — Excellent

    **Dimensions:**
    - **Coherence** — Do meals make culinary sense?
    - **Variety** — Enough diversity across days/meals?
    - **Practicality** — Can a normal person actually cook these?
    """)

    if rater_name:
        rated_count = sum(
            1 for plan_id in all_ratings
            if rater_name in all_ratings.get(plan_id, {})
        )
        st.info(f"You've rated {rated_count} / {len(eval_plans)} plans.")

if not rater_name:
    st.title("Bio-Sync Human Evaluation")
    st.info("Enter your rater ID in the sidebar to begin.")
    st.stop()

# ---------------------------------------------------------------------------
# Main — plan rating interface
# ---------------------------------------------------------------------------
st.title("Rate These Meal Plans")
st.caption(f"Rater: **{rater_name}** · {len(eval_plans)} plans to evaluate")

for plan_entry in eval_plans:
    plan_id = str(plan_entry["plan_id"])
    system = plan_entry["system"]
    plan_data = plan_entry["plan"]
    constraints = plan_entry["constraints"]

    already_rated = rater_name in all_ratings.get(plan_id, {})

    with st.expander(
        f"Plan #{plan_id} — {system.upper()} · "
        f"Profile: {constraints['macro_targets']['protein_g']}g protein, "
        f"${constraints['daily_budget_usd']}/day · "
        f"{'✅ Rated' if already_rated else '⬜ Not rated'}",
        expanded=not already_rated,
    ):
        # Show plan content
        for day in plan_data["days"]:
            st.markdown(f"**Day {day['day']}**")
            for meal in day["meals"]:
                st.markdown(f"- *{meal['meal_type'].capitalize()}*: {meal['recipe_name']}")
                ing_list = ", ".join(
                    f"{i['name']} ({i['quantity_description']})"
                    for i in meal["ingredients"]
                )
                st.caption(f"  Ingredients: {ing_list}")

        st.divider()

        # Rating widgets
        col1, col2, col3 = st.columns(3)
        existing = all_ratings.get(plan_id, {}).get(rater_name, {})

        with col1:
            coherence = st.select_slider(
                "Culinary Coherence",
                options=[1, 2, 3, 4, 5],
                value=existing.get("coherence", 3),
                key=f"coherence_{plan_id}_{rater_name}",
                help="Do the meals make culinary sense? Would this be a real meal someone would eat?",
            )
        with col2:
            variety = st.select_slider(
                "Variety",
                options=[1, 2, 3, 4, 5],
                value=existing.get("variety", 3),
                key=f"variety_{plan_id}_{rater_name}",
                help="Is there enough diversity across meals and days?",
            )
        with col3:
            practicality = st.select_slider(
                "Practicality",
                options=[1, 2, 3, 4, 5],
                value=existing.get("practicality", 3),
                key=f"practicality_{plan_id}_{rater_name}",
                help="Can a normal person with basic cooking skills actually make these?",
            )

        notes = st.text_area(
            "Notes (optional)",
            value=existing.get("notes", ""),
            key=f"notes_{plan_id}_{rater_name}",
            height=60,
        )

        if st.button(f"Save Rating for Plan #{plan_id}", key=f"save_{plan_id}_{rater_name}"):
            if plan_id not in all_ratings:
                all_ratings[plan_id] = {}
            all_ratings[plan_id][rater_name] = {
                "coherence": coherence,
                "variety": variety,
                "practicality": practicality,
                "notes": notes,
                "timestamp": datetime.now().isoformat(),
            }
            os.makedirs("eval_results", exist_ok=True)
            with open(RATINGS_FILE, "w") as f:
                json.dump(all_ratings, f, indent=2)
            st.success(f"Rating saved! (coherence={coherence}, variety={variety}, practicality={practicality})")
            st.rerun()

# ---------------------------------------------------------------------------
# Summary (if enough ratings collected)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Ratings Summary")

raters = set()
for plan_ratings in all_ratings.values():
    raters.update(plan_ratings.keys())

if not raters:
    st.info("No ratings collected yet.")
else:
    st.caption(f"{len(raters)} rater(s): {', '.join(sorted(raters))}")

    for system in ["biosync", "baseline"]:
        scores = {"coherence": [], "variety": [], "practicality": []}
        for plan_entry in eval_plans:
            if plan_entry["system"] != system:
                continue
            plan_id = str(plan_entry["plan_id"])
            for rater_ratings in all_ratings.get(plan_id, {}).values():
                for dim in scores:
                    scores[dim].append(rater_ratings[dim])

        if not scores["coherence"]:
            continue

        n = len(scores["coherence"])
        st.markdown(f"**{system.upper()}** ({n} ratings)")
        c1, c2, c3 = st.columns(3)
        c1.metric("Coherence", f"{sum(scores['coherence'])/n:.2f} / 5")
        c2.metric("Variety", f"{sum(scores['variety'])/n:.2f} / 5")
        c3.metric("Practicality", f"{sum(scores['practicality'])/n:.2f} / 5")
