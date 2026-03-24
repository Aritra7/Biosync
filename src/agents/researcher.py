"""
Researcher Agent — Kroger API grounding for real-time pricing.

Responsibilities:
- Takes an ingredient list + ZIP code from the Planner
- Uses the LLM to map ingredient names to the best Kroger product search terms
  (e.g. "chicken breast" → "boneless skinless chicken breast" for better SKU match)
- Queries the Kroger Product API for current per-unit prices and availability
- Returns a PriceLookupResult for the Critic to use
"""

import json
import re
from src.agents.base import llm_call
from src.tools.kroger import lookup_price
from src.schemas import PriceLookupResult, PriceRecord

SYSTEM_PROMPT = """You are the Researcher agent in Bio-Sync, a multi-agent meal planning system.

Your job is to map ingredient names from a meal plan to the best Kroger product search terms.

Rules:
1. Output ONLY valid JSON — a flat object mapping each input ingredient name to its best Kroger search term.
2. Use terms that match real Kroger product names:
   - "chicken breast" → "boneless skinless chicken breast"
   - "greek yogurt" → "plain greek yogurt nonfat"
   - "brown rice" → "long grain brown rice"
   - "eggs" → "large eggs"
   - "olive oil" → "extra virgin olive oil"
3. Keep search terms concise (3-5 words). Avoid overly specific brand names unless it helps.
4. For produce, keep it simple: "broccoli crowns", "baby spinach", "sweet potato"
5. Output format: {"original_name": "kroger_search_term", ...}
"""


def _resolve_kroger_terms(ingredient_names: list[str]) -> dict[str, str]:
    """
    Use the LLM to map ingredient names to optimal Kroger product search terms.
    Returns a dict of {original_name: kroger_search_term}.
    """
    names_json = json.dumps(ingredient_names, indent=2)
    user_prompt = f"""Map these ingredient names to the best Kroger product search terms.

Ingredients:
{names_json}

Output ONLY a JSON object like:
{{"ingredient name": "kroger search term", ...}}"""

    raw = llm_call(SYSTEM_PROMPT, user_prompt, max_tokens=1024)

    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1:
        return {name: name for name in ingredient_names}

    try:
        mapping = json.loads(raw[start:end])
        return {name: mapping.get(name, name) for name in ingredient_names}
    except json.JSONDecodeError:
        return {name: name for name in ingredient_names}


def run_researcher(
    ingredient_names: list[str],
    zip_code: str,
    log_callback=None,
) -> PriceLookupResult:
    """
    Look up Kroger prices for a list of ingredient names at the given ZIP code.

    Args:
        ingredient_names: Unique ingredient names from the meal plan.
        zip_code: User's ZIP code for local store pricing.
        log_callback: Optional callable(str) for streaming log messages.
    """
    # Deduplicate
    seen = set()
    unique_names = []
    for n in ingredient_names:
        key = n.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_names.append(n)

    if log_callback:
        log_callback(
            f"Researcher Agent: Pricing {len(unique_names)} ingredients "
            f"near ZIP {zip_code} via Kroger API..."
        )

    # Step 1: LLM resolves ingredient names to Kroger-optimized search terms
    term_mapping = _resolve_kroger_terms(unique_names)

    if log_callback:
        for orig, term in term_mapping.items():
            if orig.lower() != term.lower():
                log_callback(f"Researcher Agent: Mapped '{orig}' → '{term}' for Kroger search")

    # Step 2: Query Kroger API (or mock) for each resolved term
    result = PriceLookupResult()
    for original_name, kroger_term in term_mapping.items():
        record = lookup_price(kroger_term, zip_code)
        if record:
            # Re-tag with the original ingredient name
            record = PriceRecord(
                ingredient_name=original_name,
                kroger_product_id=record.kroger_product_id,
                kroger_description=record.kroger_description,
                price_usd=record.price_usd,
                unit_size_g=record.unit_size_g,
                price_per_100g=record.price_per_100g,
                store_location=record.store_location,
                data_source=record.data_source,
            )
            result.records[original_name.lower()] = record
            if log_callback:
                log_callback(
                    f"Researcher Agent: '{original_name}' → "
                    f"${record.price_usd:.2f} / {record.unit_size_g:.0f}g "
                    f"(${record.price_per_100g:.3f}/100g) at {record.store_location} ✓"
                )
        else:
            result.failed_lookups.append(original_name)
            if log_callback:
                log_callback(f"Researcher Agent: Could not find Kroger price for '{original_name}'")

    if log_callback:
        log_callback(
            f"Researcher Agent: Done — {len(result.records)} priced, "
            f"{len(result.failed_lookups)} failed."
        )

    return result
