"""
Evaluation metrics for Bio-Sync.

Computes the four evaluation dimensions from the proposal:
1. Nutritional Accuracy  — % deviation from USDA-verified macro targets
2. Budget Compliance     — % of plans within budget, mean deviation
3. System Efficiency     — iterations, LLM calls (tracked externally), latency
4. Plan Quality          — human eval scores (loaded from eval_results/human_eval.json)
"""

import json
import math
from dataclasses import dataclass, field, asdict
from src.schemas import EnrichedMealPlan, UserConstraints


# ---------------------------------------------------------------------------
# Per-plan result record
# ---------------------------------------------------------------------------

@dataclass
class PlanMetrics:
    profile_id: int
    system: str                     # "biosync" | "baseline"

    # Nutritional accuracy (vs user targets, using USDA-verified values)
    protein_pct_error: float        # abs((actual - target) / target) * 100
    carbs_pct_error: float
    fat_pct_error: float
    calories_pct_error: float
    mean_macro_pct_error: float     # mean of above 4

    # Budget compliance
    within_budget: bool
    budget_deviation_usd: float     # actual - budget (negative = under budget)

    # Validation
    passed_validation: bool
    iterations_taken: int

    # Latency (seconds) — filled in by the runner
    latency_s: float = 0.0

    # Day-level detail (for multi-day plans, averaged)
    per_day_protein_g: list[float] = field(default_factory=list)
    per_day_cost_usd: list[float] = field(default_factory=list)


@dataclass
class AggregateMetrics:
    system: str
    n_plans: int

    # Nutritional accuracy
    mean_protein_pct_error: float
    mean_carbs_pct_error: float
    mean_fat_pct_error: float
    mean_calories_pct_error: float
    mean_macro_pct_error: float     # average across all macros and all plans

    # Budget compliance
    budget_compliance_rate: float   # % of plans within budget
    mean_budget_deviation_usd: float  # among non-compliant plans

    # Validation
    validation_pass_rate: float
    mean_iterations: float

    # Latency
    mean_latency_s: float


def compute_plan_metrics(
    profile_id: int,
    system: str,
    result: EnrichedMealPlan,
    constraints: UserConstraints,
    latency_s: float = 0.0,
) -> PlanMetrics:
    """Compute per-plan metrics from an EnrichedMealPlan."""
    macros = constraints.macro_targets

    # Average across days for multi-day plans
    days = result.days
    n = len(days)

    avg_protein = sum(d.daily_protein_g for d in days) / n
    avg_carbs   = sum(d.daily_carbs_g   for d in days) / n
    avg_fat     = sum(d.daily_fat_g     for d in days) / n
    avg_cal     = sum(d.daily_calories_kcal for d in days) / n
    avg_cost    = sum(d.daily_cost_usd  for d in days) / n

    def pct_err(actual, target):
        if target == 0:
            return 0.0
        return abs((actual - target) / target) * 100

    p_err  = pct_err(avg_protein, macros.protein_g)
    c_err  = pct_err(avg_carbs,   macros.carbs_g)
    f_err  = pct_err(avg_fat,     macros.fat_g)
    cal_err = pct_err(avg_cal,    macros.calories_kcal)
    mean_err = (p_err + c_err + f_err + cal_err) / 4

    budget_dev = avg_cost - constraints.daily_budget_usd
    within_budget = budget_dev <= 0.50  # $0.50 tolerance

    return PlanMetrics(
        profile_id=profile_id,
        system=system,
        protein_pct_error=round(p_err, 2),
        carbs_pct_error=round(c_err, 2),
        fat_pct_error=round(f_err, 2),
        calories_pct_error=round(cal_err, 2),
        mean_macro_pct_error=round(mean_err, 2),
        within_budget=within_budget,
        budget_deviation_usd=round(budget_dev, 2),
        passed_validation=result.validation_report.passed,
        iterations_taken=result.iterations_taken,
        latency_s=round(latency_s, 2),
        per_day_protein_g=[d.daily_protein_g for d in days],
        per_day_cost_usd=[d.daily_cost_usd for d in days],
    )


def aggregate_metrics(plan_metrics: list[PlanMetrics], system: str) -> AggregateMetrics:
    """Aggregate per-plan metrics into summary statistics."""
    n = len(plan_metrics)
    if n == 0:
        raise ValueError("No plan metrics to aggregate")

    non_compliant = [m for m in plan_metrics if not m.within_budget]

    return AggregateMetrics(
        system=system,
        n_plans=n,
        mean_protein_pct_error=round(sum(m.protein_pct_error for m in plan_metrics) / n, 2),
        mean_carbs_pct_error=round(sum(m.carbs_pct_error     for m in plan_metrics) / n, 2),
        mean_fat_pct_error=round(sum(m.fat_pct_error         for m in plan_metrics) / n, 2),
        mean_calories_pct_error=round(sum(m.calories_pct_error for m in plan_metrics) / n, 2),
        mean_macro_pct_error=round(sum(m.mean_macro_pct_error for m in plan_metrics) / n, 2),
        budget_compliance_rate=round(sum(1 for m in plan_metrics if m.within_budget) / n * 100, 1),
        mean_budget_deviation_usd=round(
            sum(m.budget_deviation_usd for m in non_compliant) / len(non_compliant), 2
        ) if non_compliant else 0.0,
        validation_pass_rate=round(sum(1 for m in plan_metrics if m.passed_validation) / n * 100, 1),
        mean_iterations=round(sum(m.iterations_taken for m in plan_metrics) / n, 2),
        mean_latency_s=round(sum(m.latency_s for m in plan_metrics) / n, 2),
    )


def print_report(agg: AggregateMetrics):
    print(f"\n{'='*55}")
    print(f"  {agg.system.upper()} — {agg.n_plans} plans")
    print(f"{'='*55}")
    print(f"  Nutritional Accuracy (lower = better):")
    print(f"    Protein error:   {agg.mean_protein_pct_error:.1f}%")
    print(f"    Carbs error:     {agg.mean_carbs_pct_error:.1f}%")
    print(f"    Fat error:       {agg.mean_fat_pct_error:.1f}%")
    print(f"    Calories error:  {agg.mean_calories_pct_error:.1f}%")
    print(f"    Mean macro error:{agg.mean_macro_pct_error:.1f}%")
    print(f"  Budget Compliance: {agg.budget_compliance_rate:.1f}% within budget")
    if agg.mean_budget_deviation_usd > 0:
        print(f"    Mean overage:  ${agg.mean_budget_deviation_usd:.2f}/day")
    print(f"  Validation pass rate: {agg.validation_pass_rate:.1f}%")
    print(f"  Mean iterations: {agg.mean_iterations:.1f}")
    print(f"  Mean latency:    {agg.mean_latency_s:.1f}s")
    print(f"{'='*55}\n")
