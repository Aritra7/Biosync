"""
Generates 20 meal plans (10 Bio-Sync + 10 Baseline) for human evaluation.
Saves to eval_results/human_eval_plans.json.

Usage:
    python -m src.evaluation.generate_eval_plans
"""

import os
import json
from datetime import datetime

os.environ.setdefault("USE_MOCK_APIS", "true")

from dotenv import load_dotenv
load_dotenv()

from src.evaluation.profiles import INITIAL_EVAL_PROFILES
from src.pipeline import run_pipeline
from src.baseline import run_baseline

OUTPUT_FILE = "eval_results/human_eval_plans.json"


def _plan_to_dict(enriched_plan) -> dict:
    """Serialize EnrichedMealPlan to a JSON-serializable dict for raters."""
    days = []
    for day in enriched_plan.days:
        meals = []
        for em in day.meals:
            meals.append({
                "meal_type": em.meal.meal_type,
                "recipe_name": em.meal.recipe_name,
                "ingredients": [
                    {"name": i.name, "quantity_description": i.quantity_description}
                    for i in em.meal.ingredients
                ],
                "cooking_instructions": em.meal.cooking_instructions,
                "protein_g": em.verified_protein_g,
                "carbs_g": em.verified_carbs_g,
                "fat_g": em.verified_fat_g,
                "calories_kcal": em.verified_calories_kcal,
                "cost_usd": em.verified_cost_usd,
            })
        days.append({"day": day.day, "meals": meals})
    return {"days": days}


def main():
    os.makedirs("eval_results", exist_ok=True)
    plans = []
    plan_id = 1

    print("Generating 20 meal plans for human evaluation (10 Bio-Sync + 10 Baseline)...")

    for i, constraints in enumerate(INITIAL_EVAL_PROFILES):
        constraints_dict = {
            "macro_targets": {
                "protein_g": constraints.macro_targets.protein_g,
                "carbs_g": constraints.macro_targets.carbs_g,
                "fat_g": constraints.macro_targets.fat_g,
                "calories_kcal": constraints.macro_targets.calories_kcal,
            },
            "daily_budget_usd": constraints.daily_budget_usd,
            "zip_code": constraints.zip_code,
            "dietary_preferences": constraints.dietary_preferences,
            "meals_per_day": constraints.meals_per_day,
        }

        # Bio-Sync plan
        print(f"\n[{i+1}/10] Bio-Sync — profile {i+1}...")
        try:
            result = run_pipeline(constraints)
            plans.append({
                "plan_id": plan_id,
                "system": "biosync",
                "profile_id": i + 1,
                "constraints": constraints_dict,
                "plan": _plan_to_dict(result),
                "passed_validation": result.validation_report.passed,
            })
        except Exception as e:
            print(f"  Error: {e}")
        plan_id += 1

        # Baseline plan
        print(f"[{i+1}/10] Baseline — profile {i+1}...")
        try:
            result = run_baseline(constraints)
            plans.append({
                "plan_id": plan_id,
                "system": "baseline",
                "profile_id": i + 1,
                "constraints": constraints_dict,
                "plan": _plan_to_dict(result),
                "passed_validation": result.validation_report.passed,
            })
        except Exception as e:
            print(f"  Error: {e}")
        plan_id += 1

    with open(OUTPUT_FILE, "w") as f:
        json.dump(plans, f, indent=2)

    print(f"\nDone. {len(plans)} plans saved to {OUTPUT_FILE}")
    print(f"Launch rater interface with: streamlit run human_eval.py")


if __name__ == "__main__":
    main()
