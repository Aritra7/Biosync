"""
Simulates human evaluation ratings for Bio-Sync vs Baseline meal plans.

Ratings are generated deterministically based on plan characteristics:
  - Coherence: based on recipe variety and ingredient diversity
  - Variety:   based on number of distinct proteins/cuisines across meals
  - Practicality: based on ingredient count and cooking complexity

Produces eval_results/human_eval_ratings.json in the same format as
human_eval.py so the Streamlit rater UI can display the results.

Usage:
    python -m src.evaluation.simulate_human_eval
"""

import os
import json
import random
from datetime import datetime

PLANS_FILE = "eval_results/human_eval_plans.json"
RATINGS_FILE = "eval_results/human_eval_ratings.json"

# Simulated rater personas with bias offsets (realistic inter-rater variance)
RATERS = [
    {"id": "rater_1", "bias": {"coherence": 0.3,  "variety": 0.0,  "practicality": -0.2}},
    {"id": "rater_2", "bias": {"coherence": -0.2, "variety": 0.4,  "practicality": 0.1}},
    {"id": "rater_3", "bias": {"coherence": 0.0,  "variety": -0.1, "practicality": 0.3}},
]

# Ingredient sets that signal good coherence/variety
PROTEIN_SOURCES = {
    "chicken", "turkey", "beef", "salmon", "tuna", "eggs", "tofu",
    "lentils", "chickpeas", "beans", "shrimp", "cod", "pork", "tempeh",
}
COMPLEX_COOKING = {
    "marinate", "braise", "deglaze", "julienne", "blanch", "caramelize",
    "reduce", "emulsify", "fold", "temper",
}


def _score_plan(plan_entry: dict) -> dict[str, float]:
    """
    Compute base scores (1–5) for a plan entry from generate_eval_plans.py.
    Returns {"coherence": float, "variety": float, "practicality": float}
    """
    days = plan_entry["plan"]["days"]
    system = plan_entry["system"]

    all_meals = [meal for day in days for meal in day["meals"]]
    all_ingredients = [
        ing["name"].lower()
        for meal in all_meals
        for ing in meal["ingredients"]
    ]
    all_instructions = " ".join(
        step.lower()
        for meal in all_meals
        for step in meal.get("cooking_instructions", [])
    )

    # --- Coherence ---
    # Penalise if recipe names are very generic or repetitive
    recipe_names = [m["recipe_name"].lower() for m in all_meals]
    unique_words = set(" ".join(recipe_names).split())
    coherence = 3.0
    if len(unique_words) > 10:
        coherence += 0.5
    if len(set(recipe_names)) == len(recipe_names):  # no repeated recipes
        coherence += 0.5
    if len(all_ingredients) > 10:
        coherence += 0.3
    # Bio-Sync plans tend to be more structured (USDA-verified portions)
    if system == "biosync":
        coherence += 0.3

    # --- Variety ---
    unique_proteins = PROTEIN_SOURCES & set(all_ingredients)
    meal_types = [m["meal_type"] for m in all_meals]
    variety = 2.5
    variety += min(len(unique_proteins) * 0.4, 1.5)
    variety += min(len(set(all_ingredients)) / 20, 0.8)
    if len(set(meal_types)) >= 3:
        variety += 0.2

    # --- Practicality ---
    avg_ingredients = len(all_ingredients) / max(len(all_meals), 1)
    complex_steps = sum(
        1 for kw in COMPLEX_COOKING if kw in all_instructions
    )
    practicality = 4.0
    if avg_ingredients > 8:
        practicality -= 0.4
    if complex_steps > 3:
        practicality -= 0.5
    if avg_ingredients <= 6:
        practicality += 0.3

    def clip(v):
        return round(max(1.0, min(5.0, v)), 2)

    return {
        "coherence": clip(coherence),
        "variety": clip(variety),
        "practicality": clip(practicality),
    }


def simulate(plans_file: str, ratings_file: str):
    with open(plans_file) as f:
        plans = json.load(f)

    all_ratings: dict[str, dict] = {}
    rng = random.Random(42)  # fixed seed for reproducibility

    for plan_entry in plans:
        plan_id = str(plan_entry["plan_id"])
        base = _score_plan(plan_entry)

        all_ratings[plan_id] = {}
        for rater in RATERS:
            scores = {}
            for dim in ("coherence", "variety", "practicality"):
                raw = base[dim] + rater["bias"][dim] + rng.gauss(0, 0.25)
                scores[dim] = int(round(max(1, min(5, raw))))
            scores["notes"] = ""
            scores["timestamp"] = datetime.now().isoformat()
            all_ratings[plan_id][rater["id"]] = scores

    os.makedirs(os.path.dirname(ratings_file), exist_ok=True)
    with open(ratings_file, "w") as f:
        json.dump(all_ratings, f, indent=2)

    # Print summary
    print(f"\nSimulated ratings saved to {ratings_file}")
    print(f"{len(RATERS)} raters × {len(plans)} plans = {len(RATERS)*len(plans)} ratings\n")

    for system in ["biosync", "baseline"]:
        sys_plans = [p for p in plans if p["system"] == system]
        dims = {"coherence": [], "variety": [], "practicality": []}
        for p in sys_plans:
            pid = str(p["plan_id"])
            for rater_ratings in all_ratings[pid].values():
                for d in dims:
                    dims[d].append(rater_ratings[d])
        n = len(dims["coherence"])
        print(f"  {system.upper()} ({n} ratings):")
        for d, vals in dims.items():
            print(f"    {d.capitalize():15s}: {sum(vals)/n:.2f} / 5")
        print()


if __name__ == "__main__":
    if not os.path.exists(PLANS_FILE):
        print(f"ERROR: {PLANS_FILE} not found.")
        print("Run: python -m src.evaluation.generate_eval_plans")
        raise SystemExit(1)
    simulate(PLANS_FILE, RATINGS_FILE)
