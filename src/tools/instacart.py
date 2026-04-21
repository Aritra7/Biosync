"""
Instacart Connect API wrapper.

Real API docs: https://docs.instacart.com/connect/
- REST API with Bearer token authentication (requires retailer partnership)
- Product search across multiple retailer chains per ZIP code
  (Whole Foods, Safeway, Costco, Target, Aldi, etc.)
- Broader geographic coverage than Kroger (available in 50+ metro areas)
- Prices include any retailer-set service adjustments

Set USE_MOCK_APIS=true in .env to use mock data instead.
Set PRICING_SOURCE=instacart (or kroger) to choose the active pricing source.
"""

import os
import json
import httpx
import diskcache
from tenacity import retry, stop_after_attempt, wait_exponential
from src.schemas import PriceRecord, PriceLookupResult

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache = diskcache.Cache(".cache/instacart")

INSTACART_BASE_URL = "https://connect.instacart.com"

# ---------------------------------------------------------------------------
# Mock price data sourced from Instacart retailers
# Prices reflect a weighted average across Whole Foods, Safeway, and Target
# — typically 5–15% above Kroger for premium/organic variants.
# ---------------------------------------------------------------------------
_MOCK_PRICES: dict[str, dict] = {
    "chicken breast": {
        "instacart_item_id": "ic_2801001",
        "instacart_description": "Organic Boneless Skinless Chicken Breasts",
        "retailer": "Whole Foods Market",
        "price_usd": 9.99,
        "unit_size_g": 907.0,   # 2 lb package
        "data_source": "mock/instacart",
    },
    "brown rice": {
        "instacart_item_id": "ic_2802001",
        "instacart_description": "Lundberg Organic Long Grain Brown Rice",
        "retailer": "Whole Foods Market",
        "price_usd": 4.49,
        "unit_size_g": 907.0,   # 2 lb bag
        "data_source": "mock/instacart",
    },
    "broccoli": {
        "instacart_item_id": "ic_2803001",
        "instacart_description": "Broccoli Crowns, Organic",
        "retailer": "Safeway",
        "price_usd": 2.49,
        "unit_size_g": 340.0,
        "data_source": "mock/instacart",
    },
    "eggs": {
        "instacart_item_id": "ic_2804001",
        "instacart_description": "Vital Farms Pasture-Raised Eggs, 12 ct",
        "retailer": "Whole Foods Market",
        "price_usd": 7.99,
        "unit_size_g": 600.0,   # 12 large eggs
        "data_source": "mock/instacart",
    },
    "oats": {
        "instacart_item_id": "ic_2805001",
        "instacart_description": "Bob's Red Mill Organic Rolled Oats",
        "retailer": "Target",
        "price_usd": 5.49,
        "unit_size_g": 907.0,   # 32 oz bag
        "data_source": "mock/instacart",
    },
    "banana": {
        "instacart_item_id": "ic_2806001",
        "instacart_description": "Organic Bananas",
        "retailer": "Safeway",
        "price_usd": 0.35,
        "unit_size_g": 120.0,
        "data_source": "mock/instacart",
    },
    "greek yogurt": {
        "instacart_item_id": "ic_2807001",
        "instacart_description": "Fage Total 0% Greek Yogurt, 32 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 8.49,
        "unit_size_g": 907.0,
        "data_source": "mock/instacart",
    },
    "salmon": {
        "instacart_item_id": "ic_2808001",
        "instacart_description": "Wild-Caught Alaskan Salmon Fillet",
        "retailer": "Whole Foods Market",
        "price_usd": 13.99,
        "unit_size_g": 453.0,   # 1 lb
        "data_source": "mock/instacart",
    },
    "tilapia": {
        "instacart_item_id": "ic_2808002",
        "instacart_description": "Fresh Tilapia Fillets",
        "retailer": "Safeway",
        "price_usd": 7.49,
        "unit_size_g": 680.0,
        "data_source": "mock/instacart",
    },
    "olive oil": {
        "instacart_item_id": "ic_2809001",
        "instacart_description": "California Olive Ranch Extra Virgin Olive Oil, 16.9 fl oz",
        "retailer": "Target",
        "price_usd": 8.99,
        "unit_size_g": 500.0,
        "data_source": "mock/instacart",
    },
    "spinach": {
        "instacart_item_id": "ic_2810001",
        "instacart_description": "Organic Baby Spinach, 5 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 4.49,
        "unit_size_g": 142.0,
        "data_source": "mock/instacart",
    },
    "sweet potato": {
        "instacart_item_id": "ic_2811001",
        "instacart_description": "Organic Sweet Potatoes, Fresh",
        "retailer": "Safeway",
        "price_usd": 1.79,
        "unit_size_g": 300.0,
        "data_source": "mock/instacart",
    },
    "black beans": {
        "instacart_item_id": "ic_2812001",
        "instacart_description": "Eden Organic Black Beans, 15 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 2.29,
        "unit_size_g": 425.0,
        "data_source": "mock/instacart",
    },
    "almonds": {
        "instacart_item_id": "ic_2813001",
        "instacart_description": "Blue Diamond Almonds Whole Natural, 16 oz",
        "retailer": "Target",
        "price_usd": 9.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "whole wheat bread": {
        "instacart_item_id": "ic_2814001",
        "instacart_description": "Dave's Killer Bread 100% Whole Wheat, 20.5 oz",
        "retailer": "Safeway",
        "price_usd": 5.99,
        "unit_size_g": 581.0,
        "data_source": "mock/instacart",
    },
    "cottage cheese": {
        "instacart_item_id": "ic_2815001",
        "instacart_description": "Good Culture Low-Fat Cottage Cheese, 16 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 5.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "lentils": {
        "instacart_item_id": "ic_2816001",
        "instacart_description": "Bob's Red Mill Green Lentils, 1 lb",
        "retailer": "Whole Foods Market",
        "price_usd": 3.29,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "ground beef": {
        "instacart_item_id": "ic_2817001",
        "instacart_description": "Organic 85/15 Ground Beef, 1 lb",
        "retailer": "Whole Foods Market",
        "price_usd": 8.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "tuna": {
        "instacart_item_id": "ic_2818001",
        "instacart_description": "Wild Planet Wild Albacore Tuna, 5 oz",
        "retailer": "Target",
        "price_usd": 3.49,
        "unit_size_g": 142.0,
        "data_source": "mock/instacart",
    },
    "quinoa": {
        "instacart_item_id": "ic_2819001",
        "instacart_description": "Ancient Harvest Organic Quinoa, 12 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 6.49,
        "unit_size_g": 340.0,
        "data_source": "mock/instacart",
    },
    "cod": {
        "instacart_item_id": "ic_2820001",
        "instacart_description": "Wild Pacific Cod Fillets, 1 lb",
        "retailer": "Safeway",
        "price_usd": 10.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "lemon juice": {
        "instacart_item_id": "ic_2821001",
        "instacart_description": "Santa Cruz Organic Lemon Juice, 16 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 4.29,
        "unit_size_g": 473.0,
        "data_source": "mock/instacart",
    },
    "garlic powder": {
        "instacart_item_id": "ic_2822001",
        "instacart_description": "Frontier Co-op Garlic Powder, 2.33 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 4.49,
        "unit_size_g": 66.0,
        "data_source": "mock/instacart",
    },
    "paprika": {
        "instacart_item_id": "ic_2823001",
        "instacart_description": "Simply Organic Paprika, 2.96 oz",
        "retailer": "Target",
        "price_usd": 4.19,
        "unit_size_g": 84.0,
        "data_source": "mock/instacart",
    },
    "cumin": {
        "instacart_item_id": "ic_2824001",
        "instacart_description": "Simply Organic Ground Cumin, 2.31 oz",
        "retailer": "Target",
        "price_usd": 4.29,
        "unit_size_g": 65.5,
        "data_source": "mock/instacart",
    },
    "milk": {
        "instacart_item_id": "ic_2825001",
        "instacart_description": "Organic Valley Whole Milk, 1/2 gallon",
        "retailer": "Whole Foods Market",
        "price_usd": 5.99,
        "unit_size_g": 1893.0,
        "data_source": "mock/instacart",
    },
    "butter": {
        "instacart_item_id": "ic_2826001",
        "instacart_description": "Kerrygold Pure Irish Butter Unsalted, 8 oz",
        "retailer": "Target",
        "price_usd": 5.99,
        "unit_size_g": 227.0,
        "data_source": "mock/instacart",
    },
    "onion": {
        "instacart_item_id": "ic_2827001",
        "instacart_description": "Organic Yellow Onions",
        "retailer": "Safeway",
        "price_usd": 1.29,
        "unit_size_g": 200.0,
        "data_source": "mock/instacart",
    },
    "garlic": {
        "instacart_item_id": "ic_2828001",
        "instacart_description": "Organic Garlic Bulb",
        "retailer": "Whole Foods Market",
        "price_usd": 0.99,
        "unit_size_g": 50.0,
        "data_source": "mock/instacart",
    },
    "tomato": {
        "instacart_item_id": "ic_2829001",
        "instacart_description": "Organic Roma Tomatoes",
        "retailer": "Safeway",
        "price_usd": 1.49,
        "unit_size_g": 150.0,
        "data_source": "mock/instacart",
    },
    "apple": {
        "instacart_item_id": "ic_2830001",
        "instacart_description": "Organic Fuji Apples",
        "retailer": "Whole Foods Market",
        "price_usd": 1.49,
        "unit_size_g": 200.0,
        "data_source": "mock/instacart",
    },
    "peanut butter": {
        "instacart_item_id": "ic_2831001",
        "instacart_description": "Justin's Classic Peanut Butter, 16 oz",
        "retailer": "Target",
        "price_usd": 7.49,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "protein powder": {
        "instacart_item_id": "ic_2832001",
        "instacart_description": "Vega Sport Premium Protein Powder, 1.8 lb",
        "retailer": "Whole Foods Market",
        "price_usd": 44.99,
        "unit_size_g": 816.0,
        "data_source": "mock/instacart",
    },
    "ground turkey": {
        "instacart_item_id": "ic_2833001",
        "instacart_description": "Organic 93/7 Ground Turkey, 1 lb",
        "retailer": "Whole Foods Market",
        "price_usd": 7.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "canned tomatoes": {
        "instacart_item_id": "ic_2834001",
        "instacart_description": "Muir Glen Organic Diced Tomatoes, 14.5 oz",
        "retailer": "Target",
        "price_usd": 2.49,
        "unit_size_g": 411.0,
        "data_source": "mock/instacart",
    },
    "pasta": {
        "instacart_item_id": "ic_2835001",
        "instacart_description": "Jovial Organic Brown Rice Pasta Penne, 12 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 3.99,
        "unit_size_g": 340.0,
        "data_source": "mock/instacart",
    },
    "bell pepper": {
        "instacart_item_id": "ic_2836001",
        "instacart_description": "Organic Bell Peppers Tri-Color 3-pack",
        "retailer": "Safeway",
        "price_usd": 3.99,
        "unit_size_g": 450.0,
        "data_source": "mock/instacart",
    },
    "cucumber": {
        "instacart_item_id": "ic_2837001",
        "instacart_description": "Organic English Cucumber",
        "retailer": "Whole Foods Market",
        "price_usd": 1.99,
        "unit_size_g": 300.0,
        "data_source": "mock/instacart",
    },
    "avocado": {
        "instacart_item_id": "ic_2838001",
        "instacart_description": "Organic Hass Avocados, each",
        "retailer": "Safeway",
        "price_usd": 1.99,
        "unit_size_g": 200.0,
        "data_source": "mock/instacart",
    },
    "chickpeas": {
        "instacart_item_id": "ic_2839001",
        "instacart_description": "Eden Organic Garbanzo Beans, 15 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 2.29,
        "unit_size_g": 425.0,
        "data_source": "mock/instacart",
    },
    "tofu": {
        "instacart_item_id": "ic_2840001",
        "instacart_description": "House Foods Organic Extra Firm Tofu, 14 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 3.29,
        "unit_size_g": 396.0,
        "data_source": "mock/instacart",
    },
    "whole egg": {
        "instacart_item_id": "ic_2841001",
        "instacart_description": "Vital Farms Pasture-Raised Eggs, 12 ct",
        "retailer": "Whole Foods Market",
        "price_usd": 7.99,
        "unit_size_g": 600.0,
        "data_source": "mock/instacart",
    },
    "salsa": {
        "instacart_item_id": "ic_2842001",
        "instacart_description": "Desert Pepper Trading Salsa Medium, 16 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 5.99,
        "unit_size_g": 453.0,
        "data_source": "mock/instacart",
    },
    "russet potato": {
        "instacart_item_id": "ic_2843001",
        "instacart_description": "Organic Russet Potatoes",
        "retailer": "Safeway",
        "price_usd": 1.19,
        "unit_size_g": 250.0,
        "data_source": "mock/instacart",
    },
    "green beans": {
        "instacart_item_id": "ic_2844001",
        "instacart_description": "Fresh Organic Green Beans",
        "retailer": "Whole Foods Market",
        "price_usd": 2.99,
        "unit_size_g": 340.0,
        "data_source": "mock/instacart",
    },
    "cauliflower": {
        "instacart_item_id": "ic_2845001",
        "instacart_description": "Organic Cauliflower Head",
        "retailer": "Safeway",
        "price_usd": 3.99,
        "unit_size_g": 600.0,
        "data_source": "mock/instacart",
    },
    "mushroom": {
        "instacart_item_id": "ic_2846001",
        "instacart_description": "Organic White Button Mushrooms, 8 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 3.49,
        "unit_size_g": 227.0,
        "data_source": "mock/instacart",
    },
    "soy sauce": {
        "instacart_item_id": "ic_2847001",
        "instacart_description": "San-J Organic Tamari Soy Sauce, 10 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 5.49,
        "unit_size_g": 284.0,
        "data_source": "mock/instacart",
    },
    "honey": {
        "instacart_item_id": "ic_2848001",
        "instacart_description": "Manuka Health MGO 100+ Raw Honey, 8.8 oz",
        "retailer": "Whole Foods Market",
        "price_usd": 12.99,
        "unit_size_g": 250.0,
        "data_source": "mock/instacart",
    },
}


def _fuzzy_match_mock(ingredient: str) -> str | None:
    query = ingredient.lower().strip()
    if query in _MOCK_PRICES:
        return query
    for key in _MOCK_PRICES:
        if key in query or query in key:
            return key
    query_words = set(query.split())
    for key in _MOCK_PRICES:
        key_words = set(key.split())
        if query_words & key_words:
            return key
    return None


def _mock_lookup(ingredient_name: str, zip_code: str) -> PriceRecord | None:
    key = _fuzzy_match_mock(ingredient_name)
    if key is None:
        return None
    d = _MOCK_PRICES[key].copy()
    retailer = d.pop("instacart_description", "")
    item_id = d.pop("instacart_item_id", "")
    store = f"{d.pop('retailer', 'Instacart retailer')} via Instacart (near {zip_code})"
    price_per_100g = round(d["price_usd"] / d["unit_size_g"] * 100, 4)
    return PriceRecord(
        ingredient_name=ingredient_name,
        kroger_product_id=item_id,           # reuse field; represents Instacart item ID
        kroger_description=retailer,          # reuse field; represents Instacart description
        price_usd=d["price_usd"],
        unit_size_g=d["unit_size_g"],
        price_per_100g=price_per_100g,
        store_location=store,
        data_source=d["data_source"],
    )


# ---------------------------------------------------------------------------
# Real Instacart Connect API
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _real_lookup(ingredient_name: str, zip_code: str) -> PriceRecord | None:
    """
    Query the real Instacart Connect API.
    Requires INSTACART_API_KEY set in the environment.

    Instacart Connect API v2022-02-01:
      POST /v2/products/search
      Headers: Authorization: Bearer <key>
      Body: {"query": "<term>", "postal_code": "<zip>", "limit": 5}
    """
    cache_key = f"instacart_product:{ingredient_name.lower()}:{zip_code}"
    cached = _cache.get(cache_key)
    if cached:
        return PriceRecord(**json.loads(cached))

    api_key = os.environ.get("INSTACART_API_KEY", "")
    if not api_key:
        raise EnvironmentError("INSTACART_API_KEY not set; cannot use real Instacart API")

    resp = httpx.post(
        f"{INSTACART_BASE_URL}/v2/products/search",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"query": ingredient_name, "postal_code": zip_code, "limit": 5},
        timeout=10,
    )
    resp.raise_for_status()
    products = resp.json().get("products", [])
    if not products:
        return None

    # Use the first result that has pricing
    product = next((p for p in products if p.get("price")), products[0])
    price_usd = float(product.get("price", 0.0))
    if not price_usd:
        return None

    size_str = product.get("size", "")
    unit_size_g = _parse_size_to_grams(size_str)
    price_per_100g = round(price_usd / unit_size_g * 100, 4) if unit_size_g > 0 else 0.0

    record = PriceRecord(
        ingredient_name=ingredient_name,
        kroger_product_id=product.get("id", ""),
        kroger_description=product.get("name", ""),
        price_usd=price_usd,
        unit_size_g=unit_size_g,
        price_per_100g=price_per_100g,
        store_location=product.get("retailer_name", "Instacart retailer"),
        data_source="instacart",
    )
    _cache.set(cache_key, record.model_dump_json(), expire=3600 * 6)
    return record


def _parse_size_to_grams(size_str: str) -> float:
    if not size_str:
        return 454.0
    s = size_str.lower().strip()
    try:
        if "lb" in s:
            return float(s.replace("lb", "").strip()) * 453.592
        if "oz" in s:
            return float(s.replace("oz", "").strip()) * 28.3495
        if "kg" in s:
            return float(s.replace("kg", "").strip()) * 1000
        if "g" in s:
            return float(s.replace("g", "").strip())
    except ValueError:
        pass
    return 454.0


def lookup_price(ingredient_name: str, zip_code: str) -> PriceRecord | None:
    """
    Main entry point. Routes to mock or real Instacart API based on USE_MOCK_APIS.
    """
    use_mock = os.getenv("USE_MOCK_APIS", "true").lower() == "true"
    if use_mock:
        return _mock_lookup(ingredient_name, zip_code)
    return _real_lookup(ingredient_name, zip_code)


def batch_lookup_prices(ingredient_names: list[str], zip_code: str) -> PriceLookupResult:
    result = PriceLookupResult()
    for name in ingredient_names:
        record = lookup_price(name, zip_code)
        if record:
            result.records[name.lower()] = record
        else:
            result.failed_lookups.append(name)
    return result
