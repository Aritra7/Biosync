"""
Evaluation runner for Bio-Sync.

Usage:
    # Initial eval (10 profiles, biosync only)
    python -m src.evaluation.runner --mode initial

    # Full eval (50 profiles, biosync + baseline)
    python -m src.evaluation.runner --mode full

    # Ablation (50 profiles, biosync + baseline + no-critic)
    python -m src.evaluation.runner --mode ablation

Results saved to eval_results/<mode>_<timestamp>.json
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from dataclasses import asdict

os.environ.setdefault("USE_MOCK_APIS", "true")

from dotenv import load_dotenv
load_dotenv()

from src.schemas import UserConstraints
from src.pipeline import run_pipeline
from src.baseline import run_baseline
from src.evaluation.profiles import TEST_PROFILES, INITIAL_EVAL_PROFILES
from src.evaluation.metrics import compute_plan_metrics, aggregate_metrics, print_report, PlanMetrics


# ---------------------------------------------------------------------------
# No-critic variant (for ablation) — pipeline without the Critic agent
# ---------------------------------------------------------------------------

def _run_no_critic(constraints: UserConstraints, log_callback=None):
    """Run the pipeline with only Planner + Researcher + Nutritionist (no Critic/revision)."""
    from src.agents.planner import run_planner
    from src.agents.researcher import run_researcher
    from src.agents.nutritionist import run_nutritionist
    from src.agents.critic import run_critic

    if log_callback:
        log_callback("No-Critic variant: Single iteration (no revision loop)...")

    plan = run_planner(constraints, log_callback=log_callback)

    ingredient_names = list({
        ing.name.lower()
        for day in plan.days
        for meal in day.meals
        for ing in meal.ingredients
    })

    prices = run_researcher(ingredient_names, constraints.zip_code, log_callback)
    nutrition = run_nutritionist(ingredient_names, log_callback)

    # Run critic for metrics only — don't loop even if it fails
    _, enriched = run_critic(plan, constraints, nutrition, prices, iteration=1, log_callback=log_callback)
    enriched.iterations_taken = 1
    return enriched


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_evaluation(
    profiles: list[UserConstraints],
    systems: list[str],
    output_path: str,
):
    all_metrics: dict[str, list[PlanMetrics]] = {s: [] for s in systems}
    results_log = []

    total = len(profiles) * len(systems)
    done = 0

    for i, constraints in enumerate(profiles):
        for system in systems:
            done += 1
            print(f"\n[{done}/{total}] Profile {i+1} | system={system} | "
                  f"protein={constraints.macro_targets.protein_g}g | "
                  f"budget=${constraints.daily_budget_usd} | "
                  f"zip={constraints.zip_code}")

            logs = []
            t0 = time.time()
            error = None

            try:
                if system == "biosync":
                    result = run_pipeline(constraints, log_callback=logs.append)
                elif system == "baseline":
                    result = run_baseline(constraints, log_callback=logs.append)
                elif system == "no_critic":
                    result = _run_no_critic(constraints, log_callback=logs.append)
                else:
                    raise ValueError(f"Unknown system: {system}")
            except Exception as e:
                error = str(e)
                print(f"  ERROR: {error}")
                # Create a dummy failed result so we still record the attempt
                from src.schemas import (
                    EnrichedMealPlan, EnrichedDayPlan, EnrichedMeal,
                    ValidationReport, DayValidation, Meal, Ingredient
                )
                dummy_meal = Meal(
                    meal_type="lunch",
                    recipe_name="ERROR",
                    ingredients=[],
                    cooking_instructions=[],
                )
                dummy_enriched = EnrichedMeal(
                    meal=dummy_meal,
                    verified_protein_g=0, verified_carbs_g=0,
                    verified_fat_g=0, verified_calories_kcal=0,
                    verified_cost_usd=0,
                )
                result = EnrichedMealPlan(
                    days=[EnrichedDayPlan(
                        day=1, meals=[dummy_enriched],
                        daily_protein_g=0, daily_carbs_g=0,
                        daily_fat_g=0, daily_calories_kcal=0,
                        daily_cost_usd=0,
                        nutrition_ok=False, budget_ok=False,
                    )],
                    grocery_list={},
                    estimated_total_cost_usd=0,
                    validation_report=ValidationReport(
                        passed=False,
                        day_validations=[DayValidation(
                            day=1, total_protein_g=0, total_carbs_g=0,
                            total_fat_g=0, total_calories_kcal=0, total_cost_usd=0,
                            protein_ok=False, carbs_ok=False, fat_ok=False,
                            calories_ok=False, budget_ok=False,
                            issues=[f"Error: {error}"],
                        )],
                        revision_instructions="",
                    ),
                    iterations_taken=0,
                )

            latency = time.time() - t0
            m = compute_plan_metrics(i + 1, system, result, constraints, latency)
            all_metrics[system].append(m)

            print(f"  Macro error: {m.mean_macro_pct_error:.1f}% | "
                  f"Budget: {'✓' if m.within_budget else '✗'} | "
                  f"Passed: {'✓' if m.passed_validation else '✗'} | "
                  f"Latency: {latency:.1f}s")

            results_log.append({
                "profile_id": i + 1,
                "system": system,
                "metrics": asdict(m),
                "error": error,
                "logs": logs,
            })

    # Aggregate and print
    print("\n" + "="*55)
    print("EVALUATION SUMMARY")
    print("="*55)
    aggregates = {}
    for system in systems:
        if all_metrics[system]:
            agg = aggregate_metrics(all_metrics[system], system)
            aggregates[system] = asdict(agg)
            print_report(agg)

    # Save results
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(),
        "systems": systems,
        "n_profiles": len(profiles),
        "aggregates": aggregates,
        "per_plan": results_log,
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: {output_path}")
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Bio-Sync evaluation")
    parser.add_argument(
        "--mode",
        choices=["initial", "full", "ablation"],
        default="initial",
        help="initial=10 profiles/biosync only, full=50 profiles/both, ablation=50/all three",
    )
    parser.add_argument("--mock", action="store_true", default=True,
                        help="Use mock APIs (default True)")
    args = parser.parse_args()

    if args.mock:
        os.environ["USE_MOCK_APIS"] = "true"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.mode == "initial":
        profiles = INITIAL_EVAL_PROFILES
        systems = ["biosync"]
    elif args.mode == "full":
        profiles = TEST_PROFILES
        systems = ["biosync", "baseline"]
    else:  # ablation
        profiles = TEST_PROFILES
        systems = ["biosync", "baseline", "no_critic"]

    output_path = f"eval_results/{args.mode}_{ts}.json"
    run_evaluation(profiles, systems, output_path)
