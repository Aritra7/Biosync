"""
Bio-Sync orchestration pipeline.

Flow per iteration:
  Step 1 — Planner generates candidate meal plan (JSON)
  Step 2 — Researcher prices all ingredients via Kroger API   } run concurrently
  Step 3 — Nutritionist verifies all ingredients via USDA API }
  Step 4 — Critic validates macros + budget (deterministic arithmetic)
  Step 5 — If failed and iterations remain, Planner revises; go to Step 2
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.schemas import UserConstraints, EnrichedMealPlan
from src.agents.planner import run_planner
from src.agents.researcher import run_researcher
from src.agents.nutritionist import run_nutritionist
from src.agents.critic import run_critic
from src.agents.substitutor import run_substitutor

MAX_ITERATIONS = 3


def _collect_ingredient_names(plan) -> list[str]:
    """Extract all unique ingredient names from a MealPlan."""
    seen = set()
    names = []
    for day in plan.days:
        for meal in day.meals:
            for ing in meal.ingredients:
                key = ing.name.lower().strip()
                if key not in seen:
                    seen.add(key)
                    names.append(ing.name)
    return names


def run_pipeline(
    constraints: UserConstraints,
    log_callback=None,
    user_feedback: str = "",
) -> EnrichedMealPlan:
    """
    Run the full Bio-Sync multi-agent pipeline.

    Args:
        constraints: User input constraints.
        log_callback: Optional callable(str) called with status messages in real time.
                      The UI uses this to populate the agent activity log.
        user_feedback: Optional free-text feedback from the user requesting a revision
                       of a previously shown plan (e.g. "I hate olives, remove them").
                       When provided, the pipeline treats the first iteration as a
                       user-driven revision rather than a fresh generation.

    Returns:
        EnrichedMealPlan with verified nutrition, prices, and validation report.
    """
    # If the user provided feedback, prime the first revision with it
    revision_instructions = ""
    if user_feedback.strip():
        revision_instructions = (
            f"USER REVISION REQUEST: {user_feedback.strip()}\n"
            "Incorporate this feedback into the new plan while still satisfying all "
            "macro, calorie, and budget constraints."
        )

    enriched_plan = None
    previous_plan_json = ""

    for iteration in range(1, MAX_ITERATIONS + 1):
        if log_callback:
            log_callback(f"\n--- Iteration {iteration} / {MAX_ITERATIONS} ---")

        # Step 1: Plan generation (or revision)
        plan = run_planner(
            constraints,
            revision_instructions,
            log_callback,
            previous_plan_json=previous_plan_json,
        )

        # Serialize this plan as a potential anti-example for the next iteration
        try:
            previous_plan_json = plan.model_dump_json(indent=2)
        except Exception:
            previous_plan_json = ""

        # Steps 2 & 3: Price and nutrition grounding — run concurrently
        ingredient_names = _collect_ingredient_names(plan)

        if log_callback:
            log_callback("Pipeline: Running Researcher and Nutritionist concurrently...")

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_prices = executor.submit(
                run_researcher, ingredient_names, constraints.zip_code, log_callback
            )
            fut_nutrition = executor.submit(
                run_nutritionist, ingredient_names, log_callback
            )
            prices = fut_prices.result()
            nutrition = fut_nutrition.result()

        # Step 4: Validation
        report, enriched_plan = run_critic(
            plan, constraints, nutrition, prices, iteration, log_callback
        )

        if report.passed:
            if log_callback:
                log_callback(
                    f"\nPipeline: Plan validated successfully in {iteration} iteration(s)."
                )
            enriched_plan.iterations_taken = iteration
            return enriched_plan

        # Step 5: Prepare revision instructions for next iteration
        revision_instructions = report.revision_instructions
        if log_callback:
            log_callback(
                f"\nPipeline: Iteration {iteration} failed — "
                f"{'1 more attempt' if iteration == MAX_ITERATIONS - 1 else f'{MAX_ITERATIONS - iteration} attempts'} remaining."
            )

    # Exhausted iterations — run substitutor for targeted swap suggestions
    if log_callback:
        log_callback(
            f"\nPipeline: Reached max iterations ({MAX_ITERATIONS}). "
            "Running Substitutor Agent for ingredient swap suggestions..."
        )
    substitutions = run_substitutor(
        enriched_plan, constraints, enriched_plan.validation_report, log_callback
    )
    enriched_plan.substitution_suggestions = substitutions
    enriched_plan.iterations_taken = MAX_ITERATIONS
    return enriched_plan
