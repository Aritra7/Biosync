"""
Kroger Product API wrapper.

Real API docs: https://developer.kroger.com/api-products/api/product-api
- OAuth2 client credentials flow (client_id + client_secret → access token)
- Product search by keyword + ZIP code (resolved to nearest store location)
- Returns per-item pricing, unit size, and availability
- Rate limit: varies by tier; cache aggressively

Set USE_MOCK_APIS=true in .env to use mock data instead.
"""

import os
import json
import time
import httpx
import diskcache
from tenacity import retry, stop_after_attempt, wait_exponential
from src.schemas import PriceRecord, PriceLookupResult

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache = diskcache.Cache(".cache/kroger")

KROGER_AUTH_URL = "https://api.kroger.com/v1/connect/oauth2/token"
KROGER_BASE_URL = "https://api.kroger.com/v1"

# Realistic mock price data (USD per package, with package sizes)
_MOCK_PRICES: dict[str, dict] = {
    "chicken breast": {
        "kroger_product_id": "0001111060903",
        "kroger_description": "Kroger Boneless Skinless Chicken Breasts",
        "price_usd": 7.99,
        "unit_size_g": 907.0,   # 2 lb package
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "brown rice": {
        "kroger_product_id": "0001111089291",
        "kroger_description": "Kroger Long Grain Brown Rice",
        "price_usd": 2.49,
        "unit_size_g": 907.0,   # 2 lb bag
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "broccoli": {
        "kroger_product_id": "0000000004060",
        "kroger_description": "Broccoli Crowns, Fresh",
        "price_usd": 1.99,
        "unit_size_g": 340.0,   # ~12 oz typical crown
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "eggs": {
        "kroger_product_id": "0001111060805",
        "kroger_description": "Kroger Grade A Large Eggs, 12 ct",
        "price_usd": 3.49,
        "unit_size_g": 600.0,   # 12 large eggs ~ 50g each
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "oats": {
        "kroger_product_id": "0001600027500",
        "kroger_description": "Quaker Old Fashioned Rolled Oats",
        "price_usd": 4.49,
        "unit_size_g": 1134.0,  # 40 oz canister
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "banana": {
        "kroger_product_id": "0000000004011",
        "kroger_description": "Bananas, Fresh",
        "price_usd": 0.29,
        "unit_size_g": 120.0,   # per banana
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "greek yogurt": {
        "kroger_product_id": "0001700077706",
        "kroger_description": "Chobani Non-Fat Plain Greek Yogurt, 32 oz",
        "price_usd": 6.99,
        "unit_size_g": 907.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "salmon": {
        "kroger_product_id": "0002114000102",
        "kroger_description": "Atlantic Salmon Fillet, Fresh",
        "price_usd": 9.99,
        "unit_size_g": 453.0,   # 1 lb
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "tilapia": {
        "kroger_product_id": "0002114000201",
        "kroger_description": "Tilapia Fillets, Frozen",
        "price_usd": 6.99,
        "unit_size_g": 680.0,   # 1.5 lb bag
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "olive oil": {
        "kroger_product_id": "0007203600022",
        "kroger_description": "Kroger Pure Olive Oil, 17 fl oz",
        "price_usd": 5.99,
        "unit_size_g": 473.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "spinach": {
        "kroger_product_id": "0000000094065",
        "kroger_description": "Baby Spinach, Fresh, 5 oz",
        "price_usd": 3.49,
        "unit_size_g": 142.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "sweet potato": {
        "kroger_product_id": "0000000084072",
        "kroger_description": "Sweet Potatoes, Fresh",
        "price_usd": 1.29,
        "unit_size_g": 300.0,   # per large sweet potato
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "black beans": {
        "kroger_product_id": "0001111001764",
        "kroger_description": "Kroger Black Beans, Canned 15 oz",
        "price_usd": 0.99,
        "unit_size_g": 425.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "almonds": {
        "kroger_product_id": "0001008800002",
        "kroger_description": "Blue Diamond Almonds, Whole Natural, 16 oz",
        "price_usd": 8.99,
        "unit_size_g": 453.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "whole wheat bread": {
        "kroger_product_id": "0008500001800",
        "kroger_description": "Nature's Own 100% Whole Wheat Bread, 20 oz",
        "price_usd": 3.99,
        "unit_size_g": 567.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "cottage cheese": {
        "kroger_product_id": "0007025800061",
        "kroger_description": "Daisy Low Fat Cottage Cheese, 16 oz",
        "price_usd": 3.79,
        "unit_size_g": 453.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "lentils": {
        "kroger_product_id": "0001111000821",
        "kroger_description": "Kroger Green Lentils, 1 lb",
        "price_usd": 1.79,
        "unit_size_g": 453.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "ground beef": {
        "kroger_product_id": "0002114000401",
        "kroger_description": "Lean Ground Beef 90/10, 1 lb",
        "price_usd": 6.99,
        "unit_size_g": 453.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "tuna": {
        "kroger_product_id": "0004800031122",
        "kroger_description": "Starkist Chunk Light Tuna in Water, 5 oz can",
        "price_usd": 1.29,
        "unit_size_g": 142.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
    },
    "quinoa": {
        "kroger_product_id": "0003903700260",
        "kroger_description": "Ancient Harvest Organic Quinoa, 12 oz",
        "price_usd": 5.49,
        "unit_size_g": 340.0,
        "store_location": "Kroger #531, Pittsburgh PA 15213",
        "data_source": "mock",
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
    d["store_location"] = f"Kroger #531, near {zip_code}"
    price_per_100g = round(d["price_usd"] / d["unit_size_g"] * 100, 4)
    return PriceRecord(
        ingredient_name=ingredient_name,
        price_per_100g=price_per_100g,
        **d,
    )


# ---------------------------------------------------------------------------
# Real Kroger API helpers
# ---------------------------------------------------------------------------

class _KrogerAuth:
    """Manages Kroger OAuth2 client credentials token, auto-refreshes on expiry."""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        resp = httpx.post(
            KROGER_AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "scope": "product.compact",
            },
            auth=(self._client_id, self._client_secret),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 1800)
        return self._token


_auth: _KrogerAuth | None = None


def _get_auth() -> _KrogerAuth:
    global _auth
    if _auth is None:
        _auth = _KrogerAuth(
            client_id=os.environ["KROGER_CLIENT_ID"],
            client_secret=os.environ["KROGER_CLIENT_SECRET"],
        )
    return _auth


def _resolve_location_id(zip_code: str, token: str) -> str | None:
    """Find the nearest Kroger store location ID for a given ZIP code."""
    cache_key = f"kroger_location:{zip_code}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    resp = httpx.get(
        f"{KROGER_BASE_URL}/locations",
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.zipCode.near": zip_code, "filter.limit": 1},
        timeout=10,
    )
    resp.raise_for_status()
    locations = resp.json().get("data", [])
    if not locations:
        return None
    location_id = locations[0]["locationId"]
    _cache.set(cache_key, location_id, expire=86400)  # cache 1 day
    return location_id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _real_lookup(ingredient_name: str, zip_code: str) -> PriceRecord | None:
    cache_key = f"kroger_product:{ingredient_name.lower()}:{zip_code}"
    cached = _cache.get(cache_key)
    if cached:
        return PriceRecord(**json.loads(cached))

    auth = _get_auth()
    token = auth.get_token()
    location_id = _resolve_location_id(zip_code, token)

    params = {
        "filter.term": ingredient_name,
        "filter.limit": 5,
    }
    if location_id:
        params["filter.locationId"] = location_id

    resp = httpx.get(
        f"{KROGER_BASE_URL}/products",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    products = resp.json().get("data", [])
    if not products:
        return None

    # Pick first product that has price data
    product = None
    for p in products:
        if p.get("items") and p["items"][0].get("price"):
            product = p
            break
    if product is None:
        product = products[0]

    item = product["items"][0] if product.get("items") else {}
    price_info = item.get("price", {})
    price_usd = price_info.get("regular", price_info.get("promo", 0.0))

    # Kroger API returns size as a string like "2 lb" — parse to grams
    size_str = item.get("size", "")
    unit_size_g = _parse_size_to_grams(size_str)

    price_per_100g = round(price_usd / unit_size_g * 100, 4) if unit_size_g > 0 else 0.0

    record = PriceRecord(
        ingredient_name=ingredient_name,
        kroger_product_id=product.get("productId", ""),
        kroger_description=product.get("description", ""),
        price_usd=price_usd,
        unit_size_g=unit_size_g,
        price_per_100g=price_per_100g,
        store_location=location_id or "",
        data_source="kroger",
    )
    _cache.set(cache_key, record.model_dump_json(), expire=3600 * 6)  # cache 6 hours
    return record


def _parse_size_to_grams(size_str: str) -> float:
    """
    Parse a Kroger size string like '2 lb', '16 oz', '500g' to grams.
    Returns 454.0 (1 lb) as a safe default if parsing fails.
    """
    if not size_str:
        return 454.0
    s = size_str.lower().strip()
    try:
        if "lb" in s:
            val = float(s.replace("lb", "").strip())
            return val * 453.592
        if "oz" in s:
            val = float(s.replace("oz", "").strip())
            return val * 28.3495
        if "kg" in s:
            val = float(s.replace("kg", "").strip())
            return val * 1000
        if "g" in s:
            val = float(s.replace("g", "").strip())
            return val
    except ValueError:
        pass
    return 454.0


def lookup_price(ingredient_name: str, zip_code: str) -> PriceRecord | None:
    """
    Main entry point. Routes to mock or real Kroger API based on USE_MOCK_APIS env var.
    Returns None if the ingredient cannot be priced.
    """
    use_mock = os.getenv("USE_MOCK_APIS", "true").lower() == "true"
    if use_mock:
        return _mock_lookup(ingredient_name, zip_code)
    return _real_lookup(ingredient_name, zip_code)


def batch_lookup_prices(ingredient_names: list[str], zip_code: str) -> PriceLookupResult:
    """
    Look up prices for a list of ingredients at the given ZIP code.
    Returns a PriceLookupResult with records dict and any failed lookups.
    """
    result = PriceLookupResult()
    for name in ingredient_names:
        record = lookup_price(name, zip_code)
        if record:
            result.records[name.lower()] = record
        else:
            result.failed_lookups.append(name)
    return result
