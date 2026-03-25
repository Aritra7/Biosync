"""
Run Bio-Sync vs Baseline comparison on first 3 profiles.
Usage: python -m src.evaluation.run_comparison
"""

import os, sys
os.environ.setdefault("USE_MOCK_APIS", "true")
from dotenv import load_dotenv
load_dotenv()

from src.evaluation.profiles import INITIAL_EVAL_PROFILES
from src.evaluation.runner import run_evaluation

if __name__ == "__main__":
    profiles = INITIAL_EVAL_PROFILES[:3]
    run_evaluation(
        profiles,
        systems=["biosync", "baseline"],
        output_path="eval_results/comparison_3profiles.json",
    )
