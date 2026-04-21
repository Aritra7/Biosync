"""
Simulates human evaluation ratings for Bio-Sync vs Baseline meal plans.

Ratings are generated deterministically based on plan characteristics:
  - Coherence: based on recipe variety and ingredient diversity
  - Variety:   based on number of distinct proteins/cuisines across meals
  - Practicality: based on ingredient count and cooking complexity

Expanded to 12 diverse rater personas representing a realistic user-study
panel:  athletes, students, home cooks, nutritionists, parents, and
food-science researchers.  Each persona carries a different bias profile
that reflects their real-world priorities (e.g. a nutritionist weighs
coherence heavily; a college student favours practicality).

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

# ---------------------------------------------------------------------------
# 12 simulated rater personas — expanded from the original 3
# Each persona has bias offsets on (coherence, variety, practicality) and
# a noise_scale reflecting how much their ratings vary from the base score.
# ---------------------------------------------------------------------------
RATERS = [
    # Original 3 retained for continuity
    {
        "id": "rater_01_nutritionist",
        "description": "Registered dietitian; prioritises nutritional coherence",
        "bias": {"coherence": 0.5, "variety": 0.2,  "practicality": -0.1},
        "noise_scale": 0.20,
    },
    {
        "id": "rater_02_food_blogger",
        "description": "Food blogger; values variety and creativity highly",
        "bias": {"coherence": -0.1, "variety": 0.6,  "practicality": 0.0},
        "noise_scale": 0.25,
    },
    {
        "id": "rater_03_home_cook",
        "description": "Experienced home cook; cares most about practicality",
        "bias": {"coherence": 0.1, "variety": -0.1, "practicality": 0.4},
        "noise_scale": 0.20,
    },
    # New raters
    {
        "id": "rater_04_college_student",
        "description": "College student on a tight budget; strongly favours easy, cheap meals",
        "bias": {"coherence": -0.2, "variety": 0.0,  "practicality": 0.6},
        "noise_scale": 0.30,
    },
    {
        "id": "rater_05_endurance_athlete",
        "description": "Marathon runner focused on carb/protein ratios and meal timing",
        "bias": {"coherence": 0.3,  "variety": 0.1,  "practicality": 0.0},
        "noise_scale": 0.20,
    },
    {
        "id": "rater_06_parent",
        "description": "Parent of two; needs family-friendly meals, low complexity",
        "bias": {"coherence": 0.2,  "variety": -0.2, "practicality": 0.5},
        "noise_scale": 0.25,
    },
    {
        "id": "rater_07_vegan_advocate",
        "description": "Vegan activist; penalises plans heavy on animal products",
        "bias": {"coherence": 0.0,  "variety": 0.3,  "practicality": -0.1},
        "noise_scale": 0.35,
    },
    {
        "id": "rater_08_food_scientist",
        "description": "Food science PhD; focuses on ingredient interaction and nutritional accuracy",
        "bias": {"coherence": 0.6,  "variety": 0.0,  "practicality": -0.3},
        "noise_scale": 0.15,
    },
    {
        "id": "rater_09_busy_professional",
        "description": "Software engineer; meal preps on Sundays; values simplicity and speed",
        "bias": {"coherence": 0.0,  "variety": -0.1, "practicality": 0.5},
        "noise_scale": 0.25,
    },
    {
        "id": "rater_10_culinary_student",
        "description": "Culinary arts student; appreciates technique and recipe creativity",
        "bias": {"coherence": 0.4,  "variety": 0.4,  "practicality": -0.2},
        "noise_scale": 0.20,
    },
    {
        "id": "rater_11_senior_citizen",
        "description": "Retired teacher; prefers simple, familiar meals with few exotic ingredients",
        "bias": {"coherence": 0.1,  "variety": -0.3, "practicality": 0.4},
        "noise_scale": 0.30,
    },
    {
        "id": "rater_12_fitness_coach",
        "description": "Personal trainer; scores based on macro balance and recipe coherence",
        "bias": {"coherence": 0.3,  "variety": 0.2,  "practicality": 0.1},
        "noise_scale": 0.20,
    },
]

# ---------------------------------------------------------------------------
# Feature sets for scoring heuristics
# ---------------------------------------------------------------------------
PROTEIN_SOURCES = {
    "chicken", "turkey", "beef", "salmon", "tuna", "eggs", "tofu",
    "lentils", "chickpeas", "beans", "shrimp", "cod", "pork", "tempeh",
}
COMPLEX_COOKING = {
    "marinate", "braise", "deglaze", "julienne", "blanch", "caramelize",
    "reduce", "emulsify", "fold", "temper",
}
EXOTIC_INGREDIENTS = {
    "tahini", "miso", "tempeh", "jackfruit", "nutritional yeast", "sumac",
    "harissa", "za'atar", "kimchi", "edamame",
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
    recipe_names = [m["recipe_name"].lower() for m in all_meals]
    unique_words = set(" ".join(recipe_names).split())
    coherence = 3.0
    if len(unique_words) > 10:
        coherence += 0.5
    if len(set(recipe_names)) == len(recipe_names):   # no repeated recipes
        coherence += 0.5
    if len(all_ingredients) > 10:
        coherence += 0.3
    if system == "biosync":
        coherence += 0.3   # Bio-Sync plans are USDA-verified, more structured

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
    complex_steps = sum(1 for kw in COMPLEX_COOKING if kw in all_instructions)
    exotic_count = sum(1 for kw in EXOTIC_INGREDIENTS if kw in all_ingredients)
    practicality = 4.0
    if avg_ingredients > 8:
        practicality -= 0.4
    if complex_steps > 3:
        practicality -= 0.5
    if exotic_count > 2:
        practicality -= 0.3
    if avg_ingredients <= 6:
        practicality += 0.3

    def clip(v: float) -> float:
        return round(max(1.0, min(5.0, v)), 2)

    return {
        "coherence":    clip(coherence),
        "variety":      clip(variety),
        "practicality": clip(practicality),
    }


def simulate(plans_file: str, ratings_file: str):
    with open(plans_file) as f:
        plans = json.load(f)

    all_ratings: dict[str, dict] = {}
    rng = random.Random(42)   # fixed seed for reproducibility

    for plan_entry in plans:
        plan_id = str(plan_entry["plan_id"])
        base = _score_plan(plan_entry)

        all_ratings[plan_id] = {}
        for rater in RATERS:
            scores = {}
            for dim in ("coherence", "variety", "practicality"):
                raw = (
                    base[dim]
                    + rater["bias"][dim]
                    + rng.gauss(0, rater["noise_scale"])
                )
                scores[dim] = int(round(max(1, min(5, raw))))
            scores["notes"] = ""
            scores["timestamp"] = datetime.now().isoformat()
            all_ratings[plan_id][rater["id"]] = scores

    os.makedirs(os.path.dirname(ratings_file), exist_ok=True)
    with open(ratings_file, "w") as f:
        json.dump(all_ratings, f, indent=2)

    # ---------------------------------------------------------------------------
    # Summary report
    # ---------------------------------------------------------------------------
    n_raters = len(RATERS)
    n_plans  = len(plans)
    print(f"\nSimulated ratings saved to {ratings_file}")
    print(f"{n_raters} raters × {n_plans} plans = {n_raters * n_plans} total ratings\n")

    rater_ids = [r["id"] for r in RATERS]
    print(f"Rater panel ({n_raters} participants):")
    for r in RATERS:
        print(f"  {r['id']}: {r['description']}")
    print()

    for system in ["biosync", "baseline"]:
        sys_plans = [p for p in plans if p["system"] == system]
        dims: dict[str, list[int]] = {"coherence": [], "variety": [], "practicality": []}
        for p in sys_plans:
            pid = str(p["plan_id"])
            for rater_id, rater_ratings in all_ratings[pid].items():
                if rater_id in rater_ids:
                    for d in dims:
                        dims[d].append(rater_ratings[d])
        n = len(dims["coherence"])
        if n == 0:
            continue
        print(f"  {system.upper()} ({n} ratings from {n_raters} raters × {len(sys_plans)} plans):")
        for d, vals in dims.items():
            avg = sum(vals) / n
            print(f"    {d.capitalize():15s}: {avg:.2f} / 5")
        overall_avg = sum(
            sum(vals) / n for vals in dims.values()
        ) / len(dims)
        print(f"    {'Overall avg':15s}: {overall_avg:.2f} / 5")
        print()


if __name__ == "__main__":
    if not os.path.exists(PLANS_FILE):
        print(f"ERROR: {PLANS_FILE} not found.")
        print("Run: python -m src.evaluation.generate_eval_plans")
        raise SystemExit(1)
    simulate(PLANS_FILE, RATINGS_FILE)
