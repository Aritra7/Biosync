"""
Shared Pydantic schemas for inter-agent communication in Bio-Sync.
All agents exchange these structured types.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# User input
# ---------------------------------------------------------------------------

class MacroTargets(BaseModel):
    protein_g: float = Field(..., description="Target protein in grams per day")
    carbs_g: float = Field(..., description="Target carbohydrates in grams per day")
    fat_g: float = Field(..., description="Target fat in grams per day")
    calories_kcal: float = Field(..., description="Maximum calories per day")


class UserConstraints(BaseModel):
    macro_targets: MacroTargets
    daily_budget_usd: float = Field(..., description="Maximum daily food spend in USD")
    zip_code: str = Field(..., description="User ZIP code for local pricing")
    plan_duration_days: int = Field(..., ge=1, le=7, description="Number of days to plan (1, 3, or 7)")
    dietary_preferences: str = Field(default="", description="Free-text dietary constraints and preferences")
    meals_per_day: list[str] = Field(
        default=["breakfast", "lunch", "dinner"],
        description="Which meals to include each day"
    )


# ---------------------------------------------------------------------------
# Planner output — candidate meal plan
# ---------------------------------------------------------------------------

class Ingredient(BaseModel):
    name: str
    quantity_g: float = Field(..., description="Amount in grams")
    quantity_description: str = Field(..., description="Human-readable quantity, e.g. '200g' or '1 cup'")


class Meal(BaseModel):
    meal_type: str = Field(..., description="breakfast | lunch | dinner | snack")
    recipe_name: str
    ingredients: list[Ingredient]
    cooking_instructions: list[str] = Field(..., description="Step-by-step cooking steps")
    estimated_protein_g: float = Field(default=0.0)
    estimated_carbs_g: float = Field(default=0.0)
    estimated_fat_g: float = Field(default=0.0)
    estimated_calories_kcal: float = Field(default=0.0)


class DayPlan(BaseModel):
    day: int = Field(..., description="Day number, starting at 1")
    meals: list[Meal]


class MealPlan(BaseModel):
    days: list[DayPlan]
    planner_notes: str = Field(default="", description="Any notes from the Planner agent")


# ---------------------------------------------------------------------------
# Nutritionist output — USDA-verified nutrition per ingredient
# ---------------------------------------------------------------------------

class NutritionRecord(BaseModel):
    ingredient_name: str
    usda_food_id: str
    usda_description: str
    protein_per_100g: float
    carbs_per_100g: float
    fat_per_100g: float
    calories_per_100g: float
    data_source: str = Field(default="", description="Foundation | SR Legacy | mock")


class NutritionLookupResult(BaseModel):
    records: dict[str, NutritionRecord] = Field(
        default_factory=dict,
        description="Maps ingredient name (lowercased) to its NutritionRecord"
    )
    failed_lookups: list[str] = Field(
        default_factory=list,
        description="Ingredient names that could not be resolved"
    )


# ---------------------------------------------------------------------------
# Researcher output — Kroger-verified prices per ingredient
# ---------------------------------------------------------------------------

class PriceRecord(BaseModel):
    ingredient_name: str
    kroger_product_id: str
    kroger_description: str
    price_usd: float = Field(..., description="Price in USD")
    unit_size_g: float = Field(..., description="Package size in grams")
    price_per_100g: float = Field(..., description="Computed: price_usd / unit_size_g * 100")
    store_location: str = Field(default="")
    data_source: str = Field(default="", description="kroger | mock")


class PriceLookupResult(BaseModel):
    records: dict[str, PriceRecord] = Field(
        default_factory=dict,
        description="Maps ingredient name (lowercased) to its PriceRecord"
    )
    failed_lookups: list[str] = Field(
        default_factory=list,
        description="Ingredient names that could not be priced"
    )


# ---------------------------------------------------------------------------
# Critic output — validation report
# ---------------------------------------------------------------------------

class DayValidation(BaseModel):
    day: int
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float
    total_calories_kcal: float
    total_cost_usd: float
    protein_ok: bool
    carbs_ok: bool
    fat_ok: bool
    calories_ok: bool
    budget_ok: bool
    issues: list[str] = Field(default_factory=list, description="Human-readable constraint violations")


class ValidationReport(BaseModel):
    passed: bool = Field(..., description="True if all days pass all constraints")
    day_validations: list[DayValidation]
    revision_instructions: str = Field(
        default="",
        description="Targeted instructions for the Planner if validation failed"
    )
    iteration: int = Field(default=1)


# ---------------------------------------------------------------------------
# Final enriched plan (what the UI renders)
# ---------------------------------------------------------------------------

class EnrichedMeal(BaseModel):
    meal: Meal
    verified_protein_g: float
    verified_carbs_g: float
    verified_fat_g: float
    verified_calories_kcal: float
    verified_cost_usd: float
    per_ingredient_cost: dict[str, float] = Field(default_factory=dict)


class EnrichedDayPlan(BaseModel):
    day: int
    meals: list[EnrichedMeal]
    daily_protein_g: float
    daily_carbs_g: float
    daily_fat_g: float
    daily_calories_kcal: float
    daily_cost_usd: float
    nutrition_ok: bool
    budget_ok: bool


class EnrichedMealPlan(BaseModel):
    days: list[EnrichedDayPlan]
    grocery_list: dict[str, float] = Field(
        default_factory=dict,
        description="Aggregate ingredient totals in grams"
    )
    estimated_total_cost_usd: float
    validation_report: ValidationReport
    iterations_taken: int
