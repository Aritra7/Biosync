"""
Single-agent baseline for Bio-Sync ablation study.

One LLM call with everything in the prompt — no multi-agent coordination,
no external API calls, no verification loop. Used as the comparison point
against the full 4-agent pipeline.
"""

import json
import re
from src.agents.base import llm_call
from src.schemas import (
    UserConstraints,
    MealPlan,
    NutritionLookupResult,
    PriceLookupResult,
    ValidationReport,
    DayValidation,
    EnrichedMealPlan,
    EnrichedDayPlan,
    EnrichedMeal,
    NutritionRecord,
    PriceRecord,
)

SYSTEM_PROMPT = """You are a meal planning assistant. Generate a complete multi-day meal plan
that meets the user's macro-nutrient targets, budget, and dietary preferences.

Output ONLY valid JSON matching this exact schema:
{
  "days": [
    {
      "day": 1,
      "meals": [
        {
          "meal_type": "breakfast|lunch|dinner|snack",
          "recipe_name": "string",
          "ingredients": [
            {"name": "string", "quantity_g": number, "quantity_description": "string"}
          ],
          "cooking_instructions": ["step 1", "step 2"],
          "estimated_protein_g": number,
          "estimated_carbs_g": number,
          "estimated_fat_g": number,
          "estimated_calories_kcal": number
        }
      ]
    }
  ],
  "planner_notes": "string"
}

Use your own knowledge of nutrition and food prices. Be as accurate as possible.
Output ONLY the JSON — no markdown, no explanation."""


def _extract_json(text: str) -> str:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON found in baseline response")
    return text[start:end]


def _build_prompt(constraints: UserConstraints) -> str:
    macros = constraints.macro_targets
    return f"""Generate a {constraints.plan_duration_days}-day meal plan:

DAILY TARGETS:
- Protein: {macros.protein_g}g
- Carbs: {macros.carbs_g}g
- Fat: {macros.fat_g}g
- Calories: max {macros.calories_kcal} kcal
- Budget: max ${constraints.daily_budget_usd:.2f}/day
- ZIP: {constraints.zip_code}
- Meals: {', '.join(constraints.meals_per_day)}
- Preferences: {constraints.dietary_preferences or 'None'}

Output ONLY the JSON meal plan."""


def _build_mock_enriched_plan(
    plan: MealPlan,
    constraints: UserConstraints,
) -> EnrichedMealPlan:
    """
    Build an EnrichedMealPlan from the baseline using the LLM's own
    estimated macro values (not USDA-verified). Costs are estimated
    from the LLM's knowledge (not Kroger-verified).
    """
    enriched_days = []
    grocery: dict[str, float] = {}
    total_cost = 0.0

    for day_plan in plan.days:
        enriched_meals = []
        day_protein = day_carbs = day_fat = day_cal = day_cost = 0.0

        for meal in day_plan.meals:
            # Use the LLM's own estimates as the "verified" values
            p = meal.estimated_protein_g
            c = meal.estimated_carbs_g
            f = meal.estimated_fat_g
            cal = meal.estimated_calories_kcal

            # Rough cost estimate: $0.015 per gram of protein, $0.002 per kcal
            est_cost = round(p * 0.015 + cal * 0.002, 2)

            enriched_meals.append(EnrichedMeal(
                meal=meal,
                verified_protein_g=p,
                verified_carbs_g=c,
                verified_fat_g=f,
                verified_calories_kcal=cal,
                verified_cost_usd=est_cost,
                per_ingredient_cost={},
            ))

            day_protein += p
            day_carbs += c
            day_fat += f
            day_cal += cal
            day_cost += est_cost

            for ing in meal.ingredients:
                key = ing.name.lower()
                grocery[key] = grocery.get(key, 0.0) + ing.quantity_g

        macros = constraints.macro_targets
        nutrition_ok = (
            abs(day_protein - macros.protein_g) / max(macros.protein_g, 1) <= 0.10
            and abs(day_carbs - macros.carbs_g) / max(macros.carbs_g, 1) <= 0.10
            and abs(day_fat - macros.fat_g) / max(macros.fat_g, 1) <= 0.10
            and day_cal <= macros.calories_kcal * 1.05
        )
        budget_ok = day_cost <= constraints.daily_budget_usd + 0.50

        enriched_days.append(EnrichedDayPlan(
            day=day_plan.day,
            meals=enriched_meals,
            daily_protein_g=round(day_protein, 1),
            daily_carbs_g=round(day_carbs, 1),
            daily_fat_g=round(day_fat, 1),
            daily_calories_kcal=round(day_cal, 1),
            daily_cost_usd=round(day_cost, 2),
            nutrition_ok=nutrition_ok,
            budget_ok=budget_ok,
        ))
        total_cost += day_cost

    all_ok = all(d.nutrition_ok and d.budget_ok for d in enriched_days)
    report = ValidationReport(
        passed=all_ok,
        day_validations=[
            DayValidation(
                day=d.day,
                total_protein_g=d.daily_protein_g,
                total_carbs_g=d.daily_carbs_g,
                total_fat_g=d.daily_fat_g,
                total_calories_kcal=d.daily_calories_kcal,
                total_cost_usd=d.daily_cost_usd,
                protein_ok=d.nutrition_ok,
                carbs_ok=d.nutrition_ok,
                fat_ok=d.nutrition_ok,
                calories_ok=d.nutrition_ok,
                budget_ok=d.budget_ok,
                issues=[] if (d.nutrition_ok and d.budget_ok) else ["LLM self-estimated — not externally verified"],
            )
            for d in enriched_days
        ],
        revision_instructions="",
        iteration=1,
    )

    return EnrichedMealPlan(
        days=enriched_days,
        grocery_list=grocery,
        estimated_total_cost_usd=round(total_cost, 2),
        validation_report=report,
        iterations_taken=1,
    )


def run_baseline(
    constraints: UserConstraints,
    log_callback=None,
) -> EnrichedMealPlan:
    """
    Run the single-agent baseline: one LLM call, no external APIs.

    The LLM relies entirely on its parametric knowledge for nutrition
    estimates and pricing — exactly what Bio-Sync's multi-agent design
    is meant to improve upon.
    """
    if log_callback:
        log_callback("Baseline: Single LLM call (no external APIs, no verification)...")

    raw = llm_call(SYSTEM_PROMPT, _build_prompt(constraints), max_tokens=8192)

    if log_callback:
        log_callback("Baseline: Parsing response...")

    try:
        json_str = _extract_json(raw)
        data = json.loads(json_str)
        plan = MealPlan(**data)
    except Exception as e:
        raise ValueError(f"Baseline returned invalid JSON: {e}")

    enriched = _build_mock_enriched_plan(plan, constraints)

    if log_callback:
        log_callback(
            f"Baseline: Done — {len(plan.days)} day(s), "
            f"validation {'PASSED' if enriched.validation_report.passed else 'FAILED'} "
            f"(self-estimated, not USDA-verified)"
        )

    return enriched
