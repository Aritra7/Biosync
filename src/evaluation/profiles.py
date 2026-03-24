"""
50 diverse test user profiles for Bio-Sync evaluation.

Covers a range of:
- Macro targets (bulking, cutting, maintenance, endurance)
- Budgets ($8–$30/day)
- Dietary restrictions (vegetarian, vegan, gluten-free, lactose intolerant, etc.)
- ZIP codes (across major US regions)
- Plan durations (1 day for initial eval, 3/7 for full eval)
- Meals per day (2–4)
"""

from src.schemas import UserConstraints, MacroTargets

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _p(protein, carbs, fat, calories, budget, zip_code, prefs, meals=None, days=1):
    return UserConstraints(
        macro_targets=MacroTargets(
            protein_g=protein,
            carbs_g=carbs,
            fat_g=fat,
            calories_kcal=calories,
        ),
        daily_budget_usd=budget,
        zip_code=zip_code,
        plan_duration_days=days,
        dietary_preferences=prefs,
        meals_per_day=meals or ["breakfast", "lunch", "dinner"],
    )


# ---------------------------------------------------------------------------
# 50 test profiles
# ---------------------------------------------------------------------------

TEST_PROFILES: list[UserConstraints] = [
    # --- High-protein bulking (muscle gain) ---
    _p(180, 250, 70, 2400, 20.0, "15213", "No shellfish. Prefer simple meals."),
    _p(200, 300, 80, 2800, 25.0, "10001", "No pork. High protein focus."),
    _p(160, 200, 65, 2200, 18.0, "90210", "Prefer Mediterranean style."),
    _p(190, 280, 75, 2700, 22.0, "77001", "No dairy. High protein."),
    _p(175, 220, 60, 2300, 15.0, "60601", "Budget-friendly, easy to cook."),

    # --- Cutting (calorie deficit) ---
    _p(150, 120, 45, 1500, 12.0, "30301", "No shellfish. Low carb preferred."),
    _p(140, 100, 40, 1400, 10.0, "98101", "Gluten-free. Low calorie."),
    _p(130, 130, 40, 1600, 14.0, "85001", "No pork. Simple meals."),
    _p(160, 110, 50, 1550, 13.0, "19101", "Dairy-free. Lean protein focus."),
    _p(145, 140, 45, 1650, 11.0, "33101", "Low carb, Mediterranean style."),

    # --- Maintenance ---
    _p(120, 180, 60, 1800, 15.0, "15213", "No shellfish. Prefer Mediterranean."),
    _p(110, 200, 65, 2000, 16.0, "10001", "Vegetarian. No meat."),
    _p(130, 170, 55, 1900, 14.0, "94101", "Gluten-free. Easy weekday meals."),
    _p(125, 190, 60, 1950, 15.0, "60601", "No dairy. Simple and quick."),
    _p(115, 185, 58, 1850, 13.0, "77001", "Budget meals. Any diet."),

    # --- Vegetarian ---
    _p(80,  220, 60, 1800, 12.0, "10001", "Vegetarian. No meat or fish."),
    _p(90,  200, 65, 1900, 14.0, "94101", "Vegetarian. Prefer Mediterranean."),
    _p(100, 210, 55, 1850, 13.0, "98101", "Vegetarian. No shellfish."),
    _p(85,  230, 70, 2000, 15.0, "15213", "Vegetarian. High carb for endurance."),
    _p(95,  195, 60, 1800, 12.0, "30301", "Vegetarian. Budget-friendly."),

    # --- Vegan ---
    _p(70,  230, 55, 1800, 13.0, "10001", "Vegan. No animal products."),
    _p(80,  250, 60, 1900, 15.0, "94101", "Vegan. Prefer whole foods."),
    _p(75,  220, 50, 1700, 12.0, "60601", "Vegan. Budget-friendly."),
    _p(85,  240, 65, 2000, 16.0, "98101", "Vegan. High protein focus."),
    _p(90,  200, 55, 1800, 14.0, "15213", "Vegan. Simple quick meals."),

    # --- Gluten-free ---
    _p(120, 150, 55, 1750, 15.0, "85001", "Gluten-free. No wheat, barley, rye."),
    _p(130, 160, 60, 1850, 16.0, "33101", "Gluten-free. Prefer rice-based meals."),
    _p(140, 140, 50, 1700, 14.0, "19101", "Gluten-free. Low carb."),
    _p(110, 170, 58, 1800, 13.0, "77001", "Gluten-free. Mediterranean style."),
    _p(125, 145, 52, 1720, 15.0, "15213", "Gluten-free. Simple meals."),

    # --- Lactose intolerant ---
    _p(150, 180, 55, 1850, 14.0, "10001", "Lactose intolerant. No dairy."),
    _p(140, 200, 60, 1950, 15.0, "94101", "No dairy. Mediterranean style."),
    _p(160, 170, 58, 1900, 16.0, "60601", "Dairy-free. High protein."),
    _p(130, 190, 62, 1950, 14.0, "98101", "No dairy. Budget meals."),
    _p(145, 175, 55, 1830, 13.0, "15213", "Lactose intolerant. Simple."),

    # --- Budget-constrained (<$12/day) ---
    _p(100, 180, 50, 1700, 8.0,  "15213", "Very budget-friendly. Use cheap proteins."),
    _p(110, 190, 55, 1750, 9.0,  "77001", "Budget meals. Eggs, beans, rice."),
    _p(120, 170, 52, 1720, 10.0, "60601", "Low budget. Simple ingredients."),
    _p(90,  200, 58, 1800, 9.0,  "30301", "Budget-friendly. Vegetarian preferred."),
    _p(115, 185, 55, 1780, 10.0, "10001", "Cheap and healthy meals."),

    # --- Endurance athlete (high carb) ---
    _p(120, 350, 70, 2600, 20.0, "94101", "High carb for endurance training."),
    _p(110, 380, 65, 2700, 22.0, "98101", "Marathon training. High carb."),
    _p(130, 320, 75, 2500, 18.0, "10001", "Cyclist diet. High carb, moderate protein."),
    _p(115, 360, 68, 2600, 20.0, "15213", "Endurance athlete. Complex carbs preferred."),
    _p(125, 340, 72, 2550, 19.0, "60601", "Triathlete. High carb, moderate fat."),

    # --- Mixed / edge cases ---
    _p(200, 150, 80, 2200, 30.0, "10001", "Keto-leaning. High fat, low carb.",
       meals=["breakfast", "lunch", "dinner", "snack"]),
    _p(120, 200, 55, 1800, 15.0, "15213", "No shellfish, no pork. Mediterranean.",
       days=3),
    _p(150, 180, 60, 1900, 18.0, "94101", "Gluten-free and dairy-free.",
       meals=["breakfast", "lunch", "dinner", "snack"]),
    _p(80,  180, 50, 1600, 12.0, "30301", "Vegan and gluten-free."),
    _p(160, 200, 65, 2000, 20.0, "98101", "No preferences. Maximize variety.",
       days=3),
]

# First 10 profiles used for initial/midpoint evaluation
INITIAL_EVAL_PROFILES = TEST_PROFILES[:10]
