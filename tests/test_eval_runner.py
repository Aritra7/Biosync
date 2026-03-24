"""
Smoke test for evaluation runner — 2 profiles only to verify the pipeline works.
Full 10-profile eval: python -m src.evaluation.runner --mode initial
"""

import os
os.environ["USE_MOCK_APIS"] = "true"

from dotenv import load_dotenv
load_dotenv()

from src.evaluation.profiles import INITIAL_EVAL_PROFILES
from src.evaluation.runner import run_evaluation
from src.evaluation.metrics import aggregate_metrics


def test_eval_runner_smoke():
    """Run evaluation on 2 profiles (biosync only) to verify infrastructure."""
    profiles = INITIAL_EVAL_PROFILES[:2]
    output_path = "eval_results/test_smoke.json"

    output = run_evaluation(profiles, systems=["biosync"], output_path=output_path)

    assert "aggregates" in output
    assert "biosync" in output["aggregates"]
    assert output["aggregates"]["biosync"]["n_plans"] == 2

    agg = output["aggregates"]["biosync"]
    assert 0 <= agg["mean_macro_pct_error"] <= 200
    assert 0 <= agg["budget_compliance_rate"] <= 100
    assert agg["mean_iterations"] >= 1

    print(f"\nSmoke test passed.")
    print(f"Mean macro error: {agg['mean_macro_pct_error']:.1f}%")
    print(f"Budget compliance: {agg['budget_compliance_rate']:.1f}%")
    print(f"Validation pass rate: {agg['validation_pass_rate']:.1f}%")
    print(f"Mean latency: {agg['mean_latency_s']:.1f}s")

    import os
    assert os.path.exists(output_path)
