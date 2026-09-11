"""
Phase 8: Validation & Benchmarking Package.

Implements hydrodynamic performance metrics and historical validation benchmarks.

Modules:
  - metrics: CSI (Critical Success Index), F1-score, RMSE, NSE (Nash-Sutcliffe Efficiency)
  - benchmarks: Malpasset (1959) & Chamoli (2021) validation datasets
"""

from jalraksha.validation.metrics import compute_csi, compute_f1_score, compute_rmse, compute_nse
from jalraksha.validation.benchmarks import get_malpasset_benchmark, get_chamoli_benchmark, evaluate_benchmark

__all__ = [
    "compute_csi",
    "compute_f1_score",
    "compute_rmse",
    "compute_nse",
    "get_malpasset_benchmark",
    "get_chamoli_benchmark",
    "evaluate_benchmark",
]
