"""
Ingredient Substitution Agent (5th agent — reach goal).

When the Critic flags a plan as over-budget or nutritionally off,
this agent suggests concrete ingredient swaps that are:
- Budget-friendly (cheaper alternatives)
- Allergy/preference safe (respects dietary restrictions)
- Nutritionally close (maintains macro balance)

Returns a list of substitution suggestions the Planner can apply.
"""

import json
import re
from src.agents.base import llm_call
from src.schemas import UserConstraints, EnrichedMealPlan, ValidationReport

SYSTEM_PROMPT = """You are a culinary nutrition expert specializing in ingredient substitutions.

Given a meal plan that has failed validation (over-budget, wrong macros, or dietary violations),
suggest specific ingredient swaps to fix the issues.

Output ONLY valid JSON:
{
  "substitutions": [
    {
      "day": 1,
      "meal_type": "dinner",
      "original_ingredient": "salmon fillet",
      "substitute_ingredient": "tilapia fillet",
      "reason": "Tilapia is ~40% cheaper with similar protein content (~26g/100g vs 25g/100g)",
      "estimated_cost_saving_usd": 2.50,
      "macro_impact": "Protein unchanged, fat slightly lower (-2g), calories slightly lower (-15 kcal)"
    }
  ],
  "summary": "One sentence describing the overall substitution strategy."
}

Rules:
- Only suggest substitutions that actually fix the reported issue
- Respect all dietary restrictions strictly
- Prefer substitutions that reuse ingredients already in the plan (saves cost)
- Keep substitutions culturally coherent with the original recipe
- Output ONLY the JSON — no markdown, no explanation."""


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    start = text.find("{")
    end = text.rfind("}") + 1
    return json.loads(text[start:end])


def run_substitutor(
    enriched_plan: EnrichedMealPlan,
    constraints: UserConstraints,
    validation: ValidationReport,
    log_callback=None,
) -> dict:
    """
    Suggest ingredient substitutions to fix constraint violations.

    Returns a dict with 'substitutions' list and 'summary' string.
    Returns empty substitutions if the plan already passes.
    """
    if validation.passed:
        if log_callback:
            log_callback("Substitutor Agent: Plan already passes — no substitutions needed.")
        return {"substitutions": [], "summary": "Plan satisfies all constraints."}

    if log_callback:
        log_callback("Substitutor Agent: Analyzing constraint violations and generating swaps...")

    # Build context for the LLM
    issues = []
    for dv in validation.day_validations:
        issues.extend([f"Day {dv.day}: {issue}" for issue in dv.issues])

    # Summarize current plan ingredients and costs
    ingredient_summary = []
    for day in enriched_plan.days:
        for em in day.meals:
            meal = em.meal
            for ing in meal.ingredients:
                cost = em.per_ingredient_cost.get(ing.name, None)
                ingredient_summary.append(
                    f"Day {day.day} {meal.meal_type} — {ing.name}: "
                    f"{ing.quantity_description}"
                    + (f" (~${cost:.2f})" if cost else "")
                )

    macros = constraints.macro_targets
    prompt = f"""CONSTRAINT VIOLATIONS:
{chr(10).join(issues) if issues else validation.revision_instructions}

DAILY TARGETS:
- Protein: {macros.protein_g}g | Carbs: {macros.carbs_g}g | Fat: {macros.fat_g}g
- Max calories: {macros.calories_kcal} kcal | Budget: ${constraints.daily_budget_usd:.2f}/day

DIETARY RESTRICTIONS: {constraints.dietary_preferences or "None"}

CURRENT INGREDIENTS:
{chr(10).join(ingredient_summary[:30])}

Suggest specific ingredient swaps to fix the violations above.
Output ONLY the JSON."""

    raw = llm_call(SYSTEM_PROMPT, prompt, max_tokens=2048)

    try:
        result = _extract_json(raw)
    except Exception as e:
        if log_callback:
            log_callback(f"Substitutor Agent: Failed to parse response — {e}")
        return {"substitutions": [], "summary": f"Parse error: {e}"}

    n = len(result.get("substitutions", []))
    if log_callback:
        log_callback(
            f"Substitutor Agent: {n} substitution(s) suggested. "
            f"{result.get('summary', '')}"
        )

    return result
