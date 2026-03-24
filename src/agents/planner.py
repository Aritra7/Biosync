"""
Planner Agent — main orchestrator / meal plan generator.

Responsibilities:
- Takes user constraints and generates a structured JSON meal plan
- Uses chain-of-thought to balance variety, cultural coherence, and macro targets
- Revises the plan when the Critic returns failing validation
"""

import json
import re
from src.agents.base import llm_call
from src.schemas import UserConstraints, MealPlan, DayPlan, Meal, Ingredient

SYSTEM_PROMPT = """You are the Planner agent in Bio-Sync, a multi-agent meal planning system.

Your job is to generate a realistic, diverse multi-day meal plan as valid JSON.

Rules you MUST follow:
1. Output ONLY valid JSON — no markdown fences, no explanation, no extra text.
2. The JSON must match this exact schema:
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
          "cooking_instructions": ["step 1", "step 2", ...],
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
3. Each ingredient name must be a simple, common grocery item (e.g. "chicken breast", "brown rice").
   Do NOT use compound names like "grilled chicken with herbs" — keep each ingredient atomic.
4. Use realistic gram quantities. A chicken breast is ~150-200g. A cup of rice is ~200g cooked.
5. Respect all dietary preferences strictly. If the user says no shellfish, use zero shellfish.
6. Aim for variety across days — don't repeat the same meal on consecutive days.
7. Use chain-of-thought reasoning INTERNALLY before writing the JSON, but output ONLY the JSON.

When revising a plan based on Critic feedback:
- Make targeted changes (e.g. swap one ingredient, adjust quantities)
- Do not rebuild the entire plan unless instructed
- Address each specific issue the Critic raised
"""

FEW_SHOT_EXAMPLE = """Example output for a 1-day plan (breakfast + lunch + dinner):
{
  "days": [
    {
      "day": 1,
      "meals": [
        {
          "meal_type": "breakfast",
          "recipe_name": "Greek Yogurt Parfait with Oats and Banana",
          "ingredients": [
            {"name": "greek yogurt", "quantity_g": 200, "quantity_description": "200g (about 3/4 cup)"},
            {"name": "oats", "quantity_g": 50, "quantity_description": "50g (1/2 cup dry)"},
            {"name": "banana", "quantity_g": 120, "quantity_description": "1 medium banana"}
          ],
          "cooking_instructions": [
            "Mix dry oats with 100ml water and microwave for 2 minutes.",
            "Layer greek yogurt, cooked oats, and sliced banana in a bowl.",
            "Serve immediately."
          ],
          "estimated_protein_g": 22,
          "estimated_carbs_g": 55,
          "estimated_fat_g": 4,
          "estimated_calories_kcal": 345
        },
        {
          "meal_type": "lunch",
          "recipe_name": "Grilled Chicken Rice Bowl",
          "ingredients": [
            {"name": "chicken breast", "quantity_g": 180, "quantity_description": "180g (1 medium breast)"},
            {"name": "brown rice", "quantity_g": 200, "quantity_description": "200g cooked (about 1 cup)"},
            {"name": "broccoli", "quantity_g": 150, "quantity_description": "150g (about 1 cup florets)"},
            {"name": "olive oil", "quantity_g": 10, "quantity_description": "10g (2 tsp)"}
          ],
          "cooking_instructions": [
            "Season chicken breast with salt and pepper.",
            "Heat olive oil in a pan over medium-high heat.",
            "Cook chicken 6-7 minutes per side until internal temp reaches 165F.",
            "Steam broccoli for 4-5 minutes.",
            "Serve chicken sliced over rice with broccoli on the side."
          ],
          "estimated_protein_g": 62,
          "estimated_carbs_g": 48,
          "estimated_fat_g": 9,
          "estimated_calories_kcal": 530
        },
        {
          "meal_type": "dinner",
          "recipe_name": "Baked Salmon with Sweet Potato and Spinach",
          "ingredients": [
            {"name": "salmon", "quantity_g": 200, "quantity_description": "200g fillet"},
            {"name": "sweet potato", "quantity_g": 250, "quantity_description": "1 large sweet potato"},
            {"name": "spinach", "quantity_g": 100, "quantity_description": "100g fresh spinach"},
            {"name": "olive oil", "quantity_g": 10, "quantity_description": "10g (2 tsp)"}
          ],
          "cooking_instructions": [
            "Preheat oven to 400F.",
            "Cube sweet potato, toss with half the olive oil, roast 25 minutes.",
            "Place salmon on a lined baking sheet, drizzle with remaining olive oil.",
            "Bake salmon for 15-18 minutes until it flakes easily.",
            "Wilt spinach in a pan with a splash of water for 2 minutes.",
            "Plate salmon with roasted sweet potato and wilted spinach."
          ],
          "estimated_protein_g": 48,
          "estimated_carbs_g": 47,
          "estimated_fat_g": 20,
          "estimated_calories_kcal": 560
        }
      ]
    }
  ],
  "planner_notes": "High-protein plan with Mediterranean-leaning ingredients. Day 1 totals ~132g protein, 150g carbs, 33g fat, 1435 kcal."
}"""


def _build_user_prompt(constraints: UserConstraints, revision_instructions: str = "") -> str:
    macros = constraints.macro_targets
    meals_str = ", ".join(constraints.meals_per_day)

    prompt = f"""Generate a {constraints.plan_duration_days}-day meal plan with the following constraints:

MACRO TARGETS (per day):
- Protein: {macros.protein_g}g
- Carbohydrates: {macros.carbs_g}g
- Fat: {macros.fat_g}g
- Calories: maximum {macros.calories_kcal} kcal

BUDGET: ${constraints.daily_budget_usd:.2f} per day

ZIP CODE: {constraints.zip_code} (use ingredients available at typical US grocery stores)

DIETARY PREFERENCES: {constraints.dietary_preferences or 'None specified'}

MEALS PER DAY: {meals_str}

{FEW_SHOT_EXAMPLE}

Now generate the full {constraints.plan_duration_days}-day plan. Output ONLY the JSON."""

    if revision_instructions:
        prompt += f"""

IMPORTANT — CRITIC FEEDBACK (apply these revisions):
{revision_instructions}

Revise the previous plan to fix these issues. Output the complete corrected JSON."""

    return prompt


def _extract_json(text: str) -> str:
    """Strip any accidental markdown fences or leading text before the JSON."""
    # Remove ```json ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in LLM response")
    return text[start:end]


def run_planner(
    constraints: UserConstraints,
    revision_instructions: str = "",
    log_callback=None,
) -> MealPlan:
    """
    Call the Planner LLM and parse the response into a MealPlan.

    Args:
        constraints: User input constraints.
        revision_instructions: Critic feedback from a previous iteration (empty on first run).
        log_callback: Optional callable(str) for streaming log messages to the UI.
    """
    if log_callback:
        if revision_instructions:
            log_callback("Planner Agent: Revising plan based on Critic feedback...")
        else:
            log_callback(f"Planner Agent: Generating {constraints.plan_duration_days}-day meal plan...")

    user_prompt = _build_user_prompt(constraints, revision_instructions)
    raw = llm_call(SYSTEM_PROMPT, user_prompt, max_tokens=8192)

    if log_callback:
        log_callback("Planner Agent: Plan generated, parsing JSON...")

    try:
        json_str = _extract_json(raw)
        data = json.loads(json_str)
        plan = MealPlan(**data)
    except (json.JSONDecodeError, ValueError, Exception) as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\n\nRaw response:\n{raw[:500]}")

    if log_callback:
        total_meals = sum(len(d.meals) for d in plan.days)
        log_callback(f"Planner Agent: Plan ready — {len(plan.days)} day(s), {total_meals} meals total.")

    return plan
