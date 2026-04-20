"""
Nutritionist Agent — USDA API grounding for nutrition data.

Responsibilities:
- Takes an ingredient list from the Planner
- Uses the LLM to resolve ambiguous ingredient names to the best USDA query term
  (e.g. decides "brown rice" should map to the cooked, not raw, USDA entry)
- Queries the USDA FoodData Central API for verified per-100g macros
- Returns a NutritionLookupResult for the Critic to use
"""

import json
import re
from src.agents.base import llm_call
from src.tools.usda import lookup_nutrition
from src.schemas import NutritionLookupResult, NutritionRecord

# ---------------------------------------------------------------------------
# Static lookup table for common ingredients.
# These are resolved without an LLM call — faster and cheaper.
# Add entries here whenever a new common ingredient causes repeated LLM calls.
# ---------------------------------------------------------------------------
_COMMON_TERM_MAPPING: dict[str, str] = {
    "chicken breast": "chicken breast raw",
    "ground beef": "ground beef raw",
    "ground turkey": "ground turkey raw",
    "salmon": "salmon raw",
    "tuna": "tuna canned",
    "canned tuna": "tuna canned",
    "cod": "cod raw",
    "tilapia": "tilapia raw",
    "shrimp": "shrimp raw",
    "eggs": "whole egg",
    "egg": "whole egg",
    "whole egg": "whole egg",
    "greek yogurt": "greek yogurt",
    "cottage cheese": "cottage cheese",
    "milk": "milk",
    "butter": "butter",
    "brown rice": "brown rice cooked",
    "white rice": "white rice cooked",
    "rice": "white rice cooked",
    "oats": "rolled oats dry",
    "oatmeal": "rolled oats dry",
    "rolled oats": "rolled oats dry",
    "pasta": "pasta cooked",
    "whole wheat bread": "whole wheat bread",
    "bread": "whole wheat bread",
    "sweet potato": "sweet potato cooked",
    "broccoli": "broccoli raw",
    "spinach": "spinach raw",
    "onion": "onion",
    "garlic": "garlic",
    "tomato": "tomato",
    "bell pepper": "bell pepper",
    "cucumber": "cucumber",
    "avocado": "avocado",
    "banana": "banana",
    "apple": "apple",
    "black beans": "black beans cooked",
    "canned black beans": "black beans cooked",
    "chickpeas": "chickpeas cooked",
    "canned chickpeas": "chickpeas cooked",
    "lentils": "lentils cooked",
    "tofu": "tofu",
    "olive oil": "olive oil",
    "peanut butter": "peanut butter",
    "almonds": "almonds",
    "mushroom": "mushroom",
    "mushrooms": "mushroom",
    "cauliflower": "cauliflower",
    "green beans": "green beans",
    "canned tomatoes": "canned tomatoes",
    "salsa": "salsa",
    "soy sauce": "soy sauce",
    "honey": "honey",
}

SYSTEM_PROMPT = """You are the Nutritionist agent in Bio-Sync, a multi-agent meal planning system.

Your job is to map ingredient names from a meal plan to the best USDA FoodData Central search terms.

Rules:
1. Output ONLY valid JSON — a flat object mapping each input ingredient name to its best USDA search term.
2. Resolve ambiguities:
   - "brown rice" → use "brown rice cooked" (quantities in the plan are cooked weights)
   - "oats" → use "rolled oats dry" (quantities are dry weights)
   - "chicken breast" → use "chicken breast raw" (raw weight is what you buy/measure)
   - For canned items like "black beans", use "black beans cooked" since canned = cooked
3. Keep search terms short and specific (2-4 words). Avoid brand names.
4. If an ingredient is a condiment or spice used in tiny amounts (<5g), map it to its standard name.
5. Output format: {"original_name": "usda_search_term", ...}
"""


def _resolve_usda_terms(ingredient_names: list[str]) -> dict[str, str]:
    """
    Map ingredient names to optimal USDA search terms.

    First checks the static _COMMON_TERM_MAPPING lookup table (fast, no LLM call).
    Only sends unknown ingredients to the LLM for resolution.
    Returns a dict of {original_name: usda_search_term}.
    """
    resolved: dict[str, str] = {}
    unknown: list[str] = []

    for name in ingredient_names:
        key = name.lower().strip()
        if key in _COMMON_TERM_MAPPING:
            resolved[name] = _COMMON_TERM_MAPPING[key]
        else:
            unknown.append(name)

    if not unknown:
        return resolved

    # LLM resolves only the ingredients not in the static table
    names_json = json.dumps(unknown, indent=2)
    user_prompt = f"""Map these ingredient names to the best USDA FoodData Central search terms.

Ingredients:
{names_json}

Output ONLY a JSON object like:
{{"ingredient name": "usda search term", ...}}"""

    raw = llm_call(SYSTEM_PROMPT, user_prompt, max_tokens=1024)

    # Strip any markdown fences
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1:
        # Fallback: identity mapping for unknown ingredients
        for name in unknown:
            resolved[name] = name
        return resolved

    try:
        mapping = json.loads(raw[start:end])
        for name in unknown:
            resolved[name] = mapping.get(name, name)
    except json.JSONDecodeError:
        for name in unknown:
            resolved[name] = name

    return resolved


def run_nutritionist(
    ingredient_names: list[str],
    log_callback=None,
) -> NutritionLookupResult:
    """
    Look up USDA nutrition data for a list of ingredient names.

    Args:
        ingredient_names: Unique ingredient names from the meal plan.
        log_callback: Optional callable(str) for streaming log messages.
    """
    # Deduplicate while preserving order
    seen = set()
    unique_names = []
    for n in ingredient_names:
        key = n.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_names.append(n)

    # Count how many will be resolved from the static table vs. the LLM
    static_count = sum(1 for n in unique_names if n.lower().strip() in _COMMON_TERM_MAPPING)
    llm_count = len(unique_names) - static_count

    if log_callback:
        log_callback(
            f"Nutritionist Agent: Resolving {len(unique_names)} ingredients "
            f"({static_count} from lookup table, {llm_count} via LLM)..."
        )

    # Step 1: Resolve names to optimal USDA search terms (static table + LLM fallback)
    term_mapping = _resolve_usda_terms(unique_names)

    if log_callback:
        for orig, term in term_mapping.items():
            if orig.lower() != term.lower():
                log_callback(f"Nutritionist Agent: Mapped '{orig}' → '{term}' for USDA lookup")

    # Step 2: Query USDA API (or mock) for each resolved term
    result = NutritionLookupResult()
    for original_name, usda_term in term_mapping.items():
        record = lookup_nutrition(usda_term)
        if record:
            # Store under the original ingredient name so other agents can look it up
            record = NutritionRecord(
                ingredient_name=original_name,
                usda_food_id=record.usda_food_id,
                usda_description=record.usda_description,
                protein_per_100g=record.protein_per_100g,
                carbs_per_100g=record.carbs_per_100g,
                fat_per_100g=record.fat_per_100g,
                calories_per_100g=record.calories_per_100g,
                data_source=record.data_source,
            )
            result.records[original_name.lower()] = record
            if log_callback:
                log_callback(
                    f"Nutritionist Agent: '{original_name}' → "
                    f"{record.protein_per_100g}g protein, "
                    f"{record.carbs_per_100g}g carbs, "
                    f"{record.fat_per_100g}g fat per 100g ✓"
                )
        else:
            result.failed_lookups.append(original_name)
            if log_callback:
                log_callback(f"Nutritionist Agent: Could not find USDA data for '{original_name}'")

    if log_callback:
        log_callback(
            f"Nutritionist Agent: Done — {len(result.records)} resolved, "
            f"{len(result.failed_lookups)} failed."
        )

    return result
