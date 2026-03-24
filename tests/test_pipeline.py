"""
End-to-end pipeline smoke test (uses real Anthropic API, mock external APIs).
Run with: python -m pytest tests/test_pipeline.py -v -s

NOTE: Each run makes multiple LLM calls. On a free/low-tier Anthropic key
(5 req/min), run tests individually to avoid rate limits. The base llm_call
retries automatically with backoff, but tests will take longer.
"""

import os
os.environ["USE_MOCK_APIS"] = "true"

from dotenv import load_dotenv
load_dotenv()

from src.schemas import UserConstraints, MacroTargets
from src.pipeline import run_pipeline


def _make_constraints(**overrides) -> UserConstraints:
    defaults = dict(
        macro_targets=MacroTargets(
            protein_g=150,
            carbs_g=180,
            fat_g=55,
            calories_kcal=1800,
        ),
        daily_budget_usd=15.0,
        zip_code="15213",
        plan_duration_days=1,
        dietary_preferences="No shellfish. Prefer simple, easy-to-cook meals.",
        meals_per_day=["breakfast", "lunch", "dinner"],
    )
    defaults.update(overrides)
    return UserConstraints(**defaults)


def test_pipeline_full():
    """
    Single comprehensive test covering: plan structure, nutrition values,
    costs, grocery list, meal names, and cooking instructions.
    Runs one full pipeline to stay within rate limits.
    """
    logs = []
    constraints = _make_constraints()
    result = run_pipeline(constraints, log_callback=logs.append)

    # Structure
    assert result is not None
    assert len(result.days) == 1
    assert result.iterations_taken >= 1

    day = result.days[0]
    assert len(day.meals) == 3  # breakfast, lunch, dinner

    # Nutrition values computed
    assert day.daily_protein_g > 0
    assert day.daily_calories_kcal > 0

    # Cost computed
    assert day.daily_cost_usd > 0

    # Grocery list
    assert len(result.grocery_list) > 0
    for ingredient, grams in result.grocery_list.items():
        assert grams > 0

    # Meal content
    for enriched_meal in day.meals:
        assert enriched_meal.meal.recipe_name.strip() != ""
        assert len(enriched_meal.meal.cooking_instructions) > 0

    print(f"\nProtein:    {day.daily_protein_g:.1f}g")
    print(f"Carbs:      {day.daily_carbs_g:.1f}g")
    print(f"Fat:        {day.daily_fat_g:.1f}g")
    print(f"Calories:   {day.daily_calories_kcal:.0f} kcal")
    print(f"Cost:       ${day.daily_cost_usd:.2f}")
    print(f"Passed:     {result.validation_report.passed}")
    print(f"Iterations: {result.iterations_taken}")
    print(f"\nMeals:")
    for em in day.meals:
        print(f"  [{em.meal.meal_type}] {em.meal.recipe_name}")
    print(f"\nLog ({len(logs)} lines):")
    for line in logs:
        print(f"  {line}")
