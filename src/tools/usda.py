"""
USDA FoodData Central API wrapper.

Real API docs: https://fdc.nal.usda.gov/api-guide.html
- Uses "Foundation" and "SR Legacy" datasets (raw/cooked ingredient data)
- Rate limit: 1000 req/hr with DEMO_KEY, 3600/hr with a registered key
- No auth needed for DEMO_KEY (just pass as query param)

Set USE_MOCK_APIS=true in .env to use mock data instead.
"""

import os
import json
import httpx
import diskcache
from tenacity import retry, stop_after_attempt, wait_exponential
from src.schemas import NutritionRecord, NutritionLookupResult

# ---------------------------------------------------------------------------
# Cache — persists across runs to avoid redundant API calls
# ---------------------------------------------------------------------------
_cache = diskcache.Cache(".cache/usda")

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# Realistic mock data covering common meal-plan ingredients
_MOCK_NUTRITION: dict[str, dict] = {
    "chicken breast": {
        "usda_food_id": "171077",
        "usda_description": "Chicken, broilers or fryers, breast, meat only, raw",
        "protein_per_100g": 31.0,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 3.6,
        "calories_per_100g": 165.0,
        "data_source": "mock/SR Legacy",
    },
    "brown rice": {
        "usda_food_id": "169704",
        "usda_description": "Rice, brown, long-grain, cooked",
        "protein_per_100g": 2.6,
        "carbs_per_100g": 23.0,
        "fat_per_100g": 0.9,
        "calories_per_100g": 112.0,
        "data_source": "mock/SR Legacy",
    },
    "broccoli": {
        "usda_food_id": "170379",
        "usda_description": "Broccoli, raw",
        "protein_per_100g": 2.8,
        "carbs_per_100g": 7.0,
        "fat_per_100g": 0.4,
        "calories_per_100g": 34.0,
        "data_source": "mock/Foundation",
    },
    "eggs": {
        "usda_food_id": "748967",
        "usda_description": "Eggs, Grade A, Large, egg whole",
        "protein_per_100g": 12.6,
        "carbs_per_100g": 0.7,
        "fat_per_100g": 9.5,
        "calories_per_100g": 143.0,
        "data_source": "mock/Foundation",
    },
    "oats": {
        "usda_food_id": "173904",
        "usda_description": "Oats, rolled, dry",
        "protein_per_100g": 13.2,
        "carbs_per_100g": 67.0,
        "fat_per_100g": 6.9,
        "calories_per_100g": 379.0,
        "data_source": "mock/SR Legacy",
    },
    "banana": {
        "usda_food_id": "173944",
        "usda_description": "Bananas, raw",
        "protein_per_100g": 1.1,
        "carbs_per_100g": 23.0,
        "fat_per_100g": 0.3,
        "calories_per_100g": 89.0,
        "data_source": "mock/Foundation",
    },
    "greek yogurt": {
        "usda_food_id": "170903",
        "usda_description": "Yogurt, Greek, plain, nonfat",
        "protein_per_100g": 10.2,
        "carbs_per_100g": 3.6,
        "fat_per_100g": 0.4,
        "calories_per_100g": 59.0,
        "data_source": "mock/SR Legacy",
    },
    "salmon": {
        "usda_food_id": "175168",
        "usda_description": "Fish, salmon, Atlantic, farmed, raw",
        "protein_per_100g": 20.4,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 13.4,
        "calories_per_100g": 208.0,
        "data_source": "mock/SR Legacy",
    },
    "tilapia": {
        "usda_food_id": "175177",
        "usda_description": "Fish, tilapia, raw",
        "protein_per_100g": 20.1,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 1.7,
        "calories_per_100g": 96.0,
        "data_source": "mock/SR Legacy",
    },
    "olive oil": {
        "usda_food_id": "171413",
        "usda_description": "Oil, olive, salad or cooking",
        "protein_per_100g": 0.0,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 100.0,
        "calories_per_100g": 884.0,
        "data_source": "mock/SR Legacy",
    },
    "spinach": {
        "usda_food_id": "168462",
        "usda_description": "Spinach, raw",
        "protein_per_100g": 2.9,
        "carbs_per_100g": 3.6,
        "fat_per_100g": 0.4,
        "calories_per_100g": 23.0,
        "data_source": "mock/Foundation",
    },
    "sweet potato": {
        "usda_food_id": "168483",
        "usda_description": "Sweet potato, raw, unprepared",
        "protein_per_100g": 1.6,
        "carbs_per_100g": 20.1,
        "fat_per_100g": 0.1,
        "calories_per_100g": 86.0,
        "data_source": "mock/Foundation",
    },
    "black beans": {
        "usda_food_id": "173735",
        "usda_description": "Beans, black, mature seeds, cooked, boiled",
        "protein_per_100g": 8.9,
        "carbs_per_100g": 23.7,
        "fat_per_100g": 0.5,
        "calories_per_100g": 132.0,
        "data_source": "mock/SR Legacy",
    },
    "almonds": {
        "usda_food_id": "170567",
        "usda_description": "Nuts, almonds",
        "protein_per_100g": 21.2,
        "carbs_per_100g": 21.7,
        "fat_per_100g": 49.4,
        "calories_per_100g": 579.0,
        "data_source": "mock/Foundation",
    },
    "whole wheat bread": {
        "usda_food_id": "172687",
        "usda_description": "Bread, whole-wheat, commercially prepared",
        "protein_per_100g": 13.4,
        "carbs_per_100g": 43.1,
        "fat_per_100g": 4.2,
        "calories_per_100g": 247.0,
        "data_source": "mock/SR Legacy",
    },
    "cottage cheese": {
        "usda_food_id": "173417",
        "usda_description": "Cheese, cottage, lowfat, 2% milkfat",
        "protein_per_100g": 11.1,
        "carbs_per_100g": 3.7,
        "fat_per_100g": 2.3,
        "calories_per_100g": 81.0,
        "data_source": "mock/SR Legacy",
    },
    "lentils": {
        "usda_food_id": "172420",
        "usda_description": "Lentils, mature seeds, cooked, boiled",
        "protein_per_100g": 9.0,
        "carbs_per_100g": 20.1,
        "fat_per_100g": 0.4,
        "calories_per_100g": 116.0,
        "data_source": "mock/SR Legacy",
    },
    "ground beef": {
        "usda_food_id": "174032",
        "usda_description": "Beef, ground, 90% lean meat / 10% fat, raw",
        "protein_per_100g": 20.0,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 10.0,
        "calories_per_100g": 176.0,
        "data_source": "mock/Foundation",
    },
    "tuna": {
        "usda_food_id": "175159",
        "usda_description": "Fish, tuna, light, canned in water, drained",
        "protein_per_100g": 25.5,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 0.8,
        "calories_per_100g": 109.0,
        "data_source": "mock/SR Legacy",
    },
    "quinoa": {
        "usda_food_id": "168917",
        "usda_description": "Quinoa, cooked",
        "protein_per_100g": 4.4,
        "carbs_per_100g": 21.3,
        "fat_per_100g": 1.9,
        "calories_per_100g": 120.0,
        "data_source": "mock/Foundation",
    },
}


def _fuzzy_match_mock(ingredient: str) -> str | None:
    """Return the best matching mock key for a given ingredient name."""
    query = ingredient.lower().strip()
    if query in _MOCK_NUTRITION:
        return query
    for key in _MOCK_NUTRITION:
        if key in query or query in key:
            return key
    # partial word match
    query_words = set(query.split())
    for key in _MOCK_NUTRITION:
        key_words = set(key.split())
        if query_words & key_words:
            return key
    return None


def _mock_lookup(ingredient_name: str) -> NutritionRecord | None:
    key = _fuzzy_match_mock(ingredient_name)
    if key is None:
        return None
    d = _MOCK_NUTRITION[key]
    return NutritionRecord(
        ingredient_name=ingredient_name,
        **d,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _real_search(ingredient_name: str, api_key: str) -> NutritionRecord | None:
    """Query USDA FoodData Central for an ingredient and return a NutritionRecord."""
    cache_key = f"usda_search:{ingredient_name.lower()}"
    cached = _cache.get(cache_key)
    if cached:
        return NutritionRecord(**json.loads(cached))

    params = {
        "query": ingredient_name,
        "dataType": ["Foundation", "SR Legacy"],
        "pageSize": 5,
        "api_key": api_key,
    }
    resp = httpx.get(f"{USDA_BASE_URL}/foods/search", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    foods = data.get("foods", [])
    if not foods:
        return None

    # Pick the first result — the Nutritionist agent LLM will have already
    # chosen the best USDA query term before calling this function
    food = foods[0]
    nutrients = {n["nutrientName"]: n["value"] for n in food.get("foodNutrients", [])}

    record = NutritionRecord(
        ingredient_name=ingredient_name,
        usda_food_id=str(food.get("fdcId", "")),
        usda_description=food.get("description", ""),
        protein_per_100g=nutrients.get("Protein", 0.0),
        carbs_per_100g=nutrients.get("Carbohydrate, by difference", 0.0),
        fat_per_100g=nutrients.get("Total lipid (fat)", 0.0),
        calories_per_100g=nutrients.get("Energy", 0.0),
        data_source=food.get("dataType", ""),
    )
    _cache.set(cache_key, record.model_dump_json(), expire=86400 * 7)  # cache 7 days
    return record


def lookup_nutrition(ingredient_name: str) -> NutritionRecord | None:
    """
    Main entry point. Routes to mock or real USDA API based on USE_MOCK_APIS env var.
    Returns None if the ingredient cannot be found.
    """
    use_mock = os.getenv("USE_MOCK_APIS", "true").lower() == "true"
    if use_mock:
        return _mock_lookup(ingredient_name)

    api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
    return _real_search(ingredient_name, api_key)


def batch_lookup_nutrition(ingredient_names: list[str]) -> NutritionLookupResult:
    """
    Look up nutrition for a list of ingredients.
    Returns a NutritionLookupResult with records dict and any failed lookups.
    """
    result = NutritionLookupResult()
    for name in ingredient_names:
        record = lookup_nutrition(name)
        if record:
            result.records[name.lower()] = record
        else:
            result.failed_lookups.append(name)
    return result
