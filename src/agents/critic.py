"""
Critic Agent — validation and constraint checking.

Responsibilities:
- Receives the full plan with USDA-verified nutrition + Kroger-verified prices
- Does deterministic arithmetic in Python (NOT by the LLM) to compute daily totals
- Compares against user targets and flags violations
- If validation fails, calls the LLM to write targeted, actionable revision instructions
  for the Planner (e.g. "Day 2 is $2.30 over budget; replace salmon with tilapia")
- Returns a ValidationReport
"""

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
)

# Tolerance bands — plan passes if within these margins of the targets
MACRO_TOLERANCE_PCT = 0.10   # ±10% for protein, carbs, fat
CALORIE_TOLERANCE_PCT = 0.05  # ±5% for calories (stricter — calories_kcal is a hard cap)
BUDGET_TOLERANCE_USD = 0.50   # $0.50 leeway on daily budget

CRITIC_SYSTEM_PROMPT = """You are the Critic agent in Bio-Sync, a multi-agent meal planning system.

You have already performed the arithmetic validation (that was done in code, not by you).
Your job is to write clear, specific, actionable revision instructions for the Planner agent
so it can fix the constraint violations.

Rules for your revision instructions:
1. Be specific: name the exact day and meal to change.
2. Suggest concrete swaps: "replace salmon (200g) with tilapia (200g) to save ~$3.00/day".
3. Suggest quantity adjustments when a macro is off: "increase chicken breast to 200g on Day 2 to add ~10g protein".
4. Address budget issues first, then macro issues.
5. Keep instructions concise and numbered.
6. Do NOT rewrite the meal plan yourself — only give instructions to the Planner.
"""


def _compute_meal_nutrition(
    meal,
    nutrition: NutritionLookupResult,
) -> tuple[float, float, float, float]:
    """Returns (protein_g, carbs_g, fat_g, calories_kcal) for a single meal."""
    total_p = total_c = total_f = total_cal = 0.0
    for ing in meal.ingredients:
        key = ing.name.lower()
        record = nutrition.records.get(key)
        if record is None:
            continue
        factor = ing.quantity_g / 100.0
        total_p += record.protein_per_100g * factor
        total_c += record.carbs_per_100g * factor
        total_f += record.fat_per_100g * factor
        total_cal += record.calories_per_100g * factor
    return round(total_p, 1), round(total_c, 1), round(total_f, 1), round(total_cal, 1)


def _compute_meal_cost(
    meal,
    prices: PriceLookupResult,
) -> tuple[float, dict[str, float]]:
    """Returns (total_cost_usd, {ingredient_name: cost_usd}) for a single meal."""
    total = 0.0
    breakdown: dict[str, float] = {}
    for ing in meal.ingredients:
        key = ing.name.lower()
        record = prices.records.get(key)
        if record is None:
            continue
        cost = record.price_per_100g * ing.quantity_g / 100.0
        breakdown[ing.name] = round(cost, 3)
        total += cost
    return round(total, 2), breakdown


def _build_day_validation(
    day_plan,
    constraints: UserConstraints,
    nutrition: NutritionLookupResult,
    prices: PriceLookupResult,
    iteration: int,
) -> tuple[DayValidation, list[EnrichedMeal]]:
    """Compute and validate a single day's totals."""
    total_p = total_c = total_f = total_cal = total_cost = 0.0
    enriched_meals = []

    for meal in day_plan.meals:
        p, c, f, cal = _compute_meal_nutrition(meal, nutrition)
        cost, cost_breakdown = _compute_meal_cost(meal, prices)

        total_p += p
        total_c += c
        total_f += f
        total_cal += cal
        total_cost += cost

        enriched_meals.append(EnrichedMeal(
            meal=meal,
            verified_protein_g=p,
            verified_carbs_g=c,
            verified_fat_g=f,
            verified_calories_kcal=cal,
            verified_cost_usd=cost,
            per_ingredient_cost=cost_breakdown,
        ))

    macros = constraints.macro_targets
    issues = []

    # Protein check (target ± tolerance)
    p_lo = macros.protein_g * (1 - MACRO_TOLERANCE_PCT)
    p_hi = macros.protein_g * (1 + MACRO_TOLERANCE_PCT)
    protein_ok = p_lo <= total_p <= p_hi
    if not protein_ok:
        issues.append(
            f"Day {day_plan.day} protein: {total_p:.1f}g "
            f"(target {macros.protein_g}g ± {MACRO_TOLERANCE_PCT*100:.0f}%)"
        )

    # Carbs check
    c_lo = macros.carbs_g * (1 - MACRO_TOLERANCE_PCT)
    c_hi = macros.carbs_g * (1 + MACRO_TOLERANCE_PCT)
    carbs_ok = c_lo <= total_c <= c_hi
    if not carbs_ok:
        issues.append(
            f"Day {day_plan.day} carbs: {total_c:.1f}g "
            f"(target {macros.carbs_g}g ± {MACRO_TOLERANCE_PCT*100:.0f}%)"
        )

    # Fat check
    f_lo = macros.fat_g * (1 - MACRO_TOLERANCE_PCT)
    f_hi = macros.fat_g * (1 + MACRO_TOLERANCE_PCT)
    fat_ok = f_lo <= total_f <= f_hi
    if not fat_ok:
        issues.append(
            f"Day {day_plan.day} fat: {total_f:.1f}g "
            f"(target {macros.fat_g}g ± {MACRO_TOLERANCE_PCT*100:.0f}%)"
        )

    # Calories check (hard upper cap + tolerance)
    cal_hi = macros.calories_kcal * (1 + CALORIE_TOLERANCE_PCT)
    calories_ok = total_cal <= cal_hi
    if not calories_ok:
        issues.append(
            f"Day {day_plan.day} calories: {total_cal:.0f} kcal "
            f"(max {macros.calories_kcal:.0f} kcal)"
        )

    # Budget check
    budget_ok = total_cost <= constraints.daily_budget_usd + BUDGET_TOLERANCE_USD
    if not budget_ok:
        issues.append(
            f"Day {day_plan.day} cost: ${total_cost:.2f} "
            f"(budget ${constraints.daily_budget_usd:.2f})"
        )

    dv = DayValidation(
        day=day_plan.day,
        total_protein_g=round(total_p, 1),
        total_carbs_g=round(total_c, 1),
        total_fat_g=round(total_f, 1),
        total_calories_kcal=round(total_cal, 1),
        total_cost_usd=round(total_cost, 2),
        protein_ok=protein_ok,
        carbs_ok=carbs_ok,
        fat_ok=fat_ok,
        calories_ok=calories_ok,
        budget_ok=budget_ok,
        issues=issues,
    )
    return dv, enriched_meals


def _generate_revision_instructions(
    day_validations: list[DayValidation],
    constraints: UserConstraints,
    plan: MealPlan,
    nutrition: NutritionLookupResult,
    prices: PriceLookupResult,
) -> str:
    """Call the LLM to write actionable revision instructions based on the violations."""
    all_issues = []
    for dv in day_validations:
        all_issues.extend(dv.issues)

    # Build a compact summary of the plan for the LLM
    plan_summary_lines = []
    for day in plan.days:
        for meal in day.meals:
            ings = ", ".join(
                f"{i.name} {i.quantity_g:.0f}g" for i in meal.ingredients
            )
            plan_summary_lines.append(
                f"Day {day.day} {meal.meal_type}: {meal.recipe_name} [{ings}]"
            )
    plan_summary = "\n".join(plan_summary_lines)

    user_prompt = f"""The following constraints were violated:
{chr(10).join(f"- {issue}" for issue in all_issues)}

Current meal plan summary:
{plan_summary}

User targets:
- Protein: {constraints.macro_targets.protein_g}g/day
- Carbs: {constraints.macro_targets.carbs_g}g/day
- Fat: {constraints.macro_targets.fat_g}g/day
- Calories: max {constraints.macro_targets.calories_kcal} kcal/day
- Budget: max ${constraints.daily_budget_usd:.2f}/day

Write numbered revision instructions for the Planner to fix these issues."""

    return llm_call(CRITIC_SYSTEM_PROMPT, user_prompt, max_tokens=1024)


def run_critic(
    plan: MealPlan,
    constraints: UserConstraints,
    nutrition: NutritionLookupResult,
    prices: PriceLookupResult,
    iteration: int = 1,
    log_callback=None,
) -> tuple[ValidationReport, EnrichedMealPlan]:
    """
    Validate the meal plan against all constraints using deterministic arithmetic.
    If validation fails, generate LLM revision instructions for the Planner.

    Returns:
        (ValidationReport, EnrichedMealPlan) — the report and the enriched plan data.
    """
    if log_callback:
        log_callback(f"Critic Agent: Validating plan (iteration {iteration})...")

    day_validations = []
    all_enriched_days = []

    for day_plan in plan.days:
        dv, enriched_meals = _build_day_validation(
            day_plan, constraints, nutrition, prices, iteration
        )
        day_validations.append(dv)

        nutrition_ok = dv.protein_ok and dv.carbs_ok and dv.fat_ok and dv.calories_ok
        all_enriched_days.append(EnrichedDayPlan(
            day=day_plan.day,
            meals=enriched_meals,
            daily_protein_g=dv.total_protein_g,
            daily_carbs_g=dv.total_carbs_g,
            daily_fat_g=dv.total_fat_g,
            daily_calories_kcal=dv.total_calories_kcal,
            daily_cost_usd=dv.total_cost_usd,
            nutrition_ok=nutrition_ok,
            budget_ok=dv.budget_ok,
        ))

        status = "PASS" if not dv.issues else "FAIL"
        if log_callback:
            log_callback(
                f"Critic Agent: Day {day_plan.day} — "
                f"Protein {dv.total_protein_g:.1f}g | "
                f"Carbs {dv.total_carbs_g:.1f}g | "
                f"Fat {dv.total_fat_g:.1f}g | "
                f"{dv.total_calories_kcal:.0f} kcal | "
                f"${dv.total_cost_usd:.2f} → {status}"
            )
            for issue in dv.issues:
                log_callback(f"Critic Agent:   ✗ {issue}")

    all_passed = all(not dv.issues for dv in day_validations)

    revision_instructions = ""
    if not all_passed:
        if log_callback:
            log_callback("Critic Agent: Validation FAILED — generating revision instructions...")
        revision_instructions = _generate_revision_instructions(
            day_validations, constraints, plan, nutrition, prices
        )
        if log_callback:
            log_callback("Critic Agent: Revision instructions ready.")
    else:
        if log_callback:
            log_callback("Critic Agent: Validation PASSED — all constraints satisfied.")

    # Build aggregate grocery list
    grocery_list: dict[str, float] = {}
    for day in plan.days:
        for meal in day.meals:
            for ing in meal.ingredients:
                key = ing.name.lower()
                grocery_list[key] = grocery_list.get(key, 0.0) + ing.quantity_g

    total_cost = sum(d.daily_cost_usd for d in all_enriched_days)

    enriched_plan = EnrichedMealPlan(
        days=all_enriched_days,
        grocery_list=grocery_list,
        estimated_total_cost_usd=round(total_cost, 2),
        validation_report=ValidationReport(
            passed=all_passed,
            day_validations=day_validations,
            revision_instructions=revision_instructions,
            iteration=iteration,
        ),
        iterations_taken=iteration,
    )

    report = ValidationReport(
        passed=all_passed,
        day_validations=day_validations,
        revision_instructions=revision_instructions,
        iteration=iteration,
    )

    return report, enriched_plan
