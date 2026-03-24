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
from src.tools.usda import lookup_nutrition, batch_lookup_nutrition
from src.schemas import NutritionLookupResult, NutritionRecord

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
    Use the LLM to map ingredient names to optimal USDA search terms.
    Returns a dict of {original_name: usda_search_term}.
    """
    names_json = json.dumps(ingredient_names, indent=2)
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
        # Fallback: identity mapping
        return {name: name for name in ingredient_names}

    try:
        mapping = json.loads(raw[start:end])
        # Ensure every original name has a mapping (use original as fallback)
        return {name: mapping.get(name, name) for name in ingredient_names}
    except json.JSONDecodeError:
        return {name: name for name in ingredient_names}


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

    if log_callback:
        log_callback(f"Nutritionist Agent: Resolving {len(unique_names)} ingredients via USDA API...")

    # Step 1: LLM resolves ambiguous names to optimal USDA search terms
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
