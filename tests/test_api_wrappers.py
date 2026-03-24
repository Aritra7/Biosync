"""
Smoke tests for USDA and Kroger API wrappers (mock mode).
Run with: python -m pytest tests/test_api_wrappers.py -v
"""

import os
os.environ["USE_MOCK_APIS"] = "true"

from src.tools.usda import lookup_nutrition, batch_lookup_nutrition
from src.tools.kroger import lookup_price, batch_lookup_prices


# ---------------------------------------------------------------------------
# USDA tests
# ---------------------------------------------------------------------------

def test_usda_exact_match():
    record = lookup_nutrition("chicken breast")
    assert record is not None
    assert record.protein_per_100g > 25
    assert record.calories_per_100g > 100


def test_usda_partial_match():
    record = lookup_nutrition("brown rice cooked")
    assert record is not None
    assert record.carbs_per_100g > 10


def test_usda_unknown_ingredient():
    record = lookup_nutrition("xyzzy_nonexistent_food_99")
    assert record is None


def test_usda_batch():
    result = batch_lookup_nutrition(["salmon", "eggs", "spinach", "unknown_food_xyz"])
    assert "salmon" in result.records
    assert "eggs" in result.records
    assert "spinach" in result.records
    assert "unknown_food_xyz" in result.failed_lookups


def test_usda_nutrition_math():
    """Verify that per-100g values are plausible (not zero everywhere)."""
    for name in ["oats", "greek yogurt", "almonds", "black beans"]:
        r = lookup_nutrition(name)
        assert r is not None, f"Missing mock for: {name}"
        total = r.protein_per_100g + r.carbs_per_100g + r.fat_per_100g
        assert total > 0, f"All macros zero for: {name}"


# ---------------------------------------------------------------------------
# Kroger tests
# ---------------------------------------------------------------------------

def test_kroger_exact_match():
    record = lookup_price("chicken breast", "15213")
    assert record is not None
    assert record.price_usd > 0
    assert record.unit_size_g > 0
    assert record.price_per_100g > 0


def test_kroger_partial_match():
    record = lookup_price("brown rice bag", "15213")
    assert record is not None


def test_kroger_unknown_ingredient():
    record = lookup_price("xyzzy_nonexistent_food_99", "15213")
    assert record is None


def test_kroger_batch():
    result = batch_lookup_prices(["salmon", "eggs", "oats", "unknown_xyz"], "15213")
    assert "salmon" in result.records
    assert "eggs" in result.records
    assert "unknown_xyz" in result.failed_lookups


def test_kroger_price_per_100g_computed():
    record = lookup_price("tilapia", "15213")
    assert record is not None
    expected = round(record.price_usd / record.unit_size_g * 100, 4)
    assert abs(record.price_per_100g - expected) < 0.001


def test_kroger_zip_reflected():
    record = lookup_price("tuna", "90210")
    assert record is not None
    assert "90210" in record.store_location
