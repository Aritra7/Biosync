"""
Bio-Sync orchestration pipeline.

Flow per iteration:
  Step 1 — Planner generates candidate meal plan (JSON)
  Step 2 — Researcher prices all ingredients via Kroger API
  Step 3 — Nutritionist verifies all ingredients via USDA API
  Step 4 — Critic validates macros + budget (deterministic arithmetic)
  Step 5 — If failed and iterations remain, Planner revises; go to Step 2
"""

from src.schemas import UserConstraints, EnrichedMealPlan
from src.agents.planner import run_planner
from src.agents.researcher import run_researcher
from src.agents.nutritionist import run_nutritionist
from src.agents.critic import run_critic

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
) -> EnrichedMealPlan:
    """
    Run the full Bio-Sync multi-agent pipeline.

    Args:
        constraints: User input constraints.
        log_callback: Optional callable(str) called with status messages in real time.
                      The UI uses this to populate the agent activity log.

    Returns:
        EnrichedMealPlan with verified nutrition, prices, and validation report.
    """
    revision_instructions = ""
    enriched_plan = None

    for iteration in range(1, MAX_ITERATIONS + 1):
        if log_callback:
            log_callback(f"\n--- Iteration {iteration} / {MAX_ITERATIONS} ---")

        # Step 1: Plan generation (or revision)
        plan = run_planner(constraints, revision_instructions, log_callback)

        # Step 2 & 3: Price and nutrition grounding (can conceptually run in parallel;
        # kept sequential here to avoid hammering APIs — swap to asyncio if needed)
        ingredient_names = _collect_ingredient_names(plan)

        prices = run_researcher(ingredient_names, constraints.zip_code, log_callback)
        nutrition = run_nutritionist(ingredient_names, log_callback)

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

    # Exhausted iterations — return best plan so far with failed validation
    if log_callback:
        log_callback(
            f"\nPipeline: Reached max iterations ({MAX_ITERATIONS}). "
            "Returning best plan — some constraints may not be fully satisfied."
        )
    enriched_plan.iterations_taken = MAX_ITERATIONS
    return enriched_plan
