import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from app.services.extreme_change_engine import (
    ExtremeParams, ChangeParams, MaterialityWeights,
    persistence_state_machine, run_analysis,
)


def test_persistence_matches_framework_worked_example():
    """Reproduces section 9 of the Consolidated Standardized Time-Series
    Analytics Framework document, row for row."""
    values = [103, 135, 128, 120, 119, 117, 121, 118, 108]
    x = pd.Series(values, dtype="float64")
    ma = pd.Series([100.0] * len(values))
    sigma = pd.Series([10.0] * len(values))
    z = (x - ma) / sigma
    extreme_flag = z.abs() >= 2.0

    params = ExtremeParams(k_e=2.0, k_p=1.0, n_p=3, n_m=7, k_m=1.2, n_exit=1)
    result = persistence_state_machine(z, extreme_flag, params)

    expected_states = [
        "Normal", "Extreme triggered", "Extreme/elevated", "Persistent",
        "Persistent", "Persistent", "Persistent",
        "Confirmed/Materialized Shift", "Persistence ends",
    ]
    expected_persistence = [0, 1, 2, 3, 4, 5, 6, 7, 0]

    assert list(result["State"]) == expected_states
    assert list(result["PersistenceCount"]) == expected_persistence


def test_run_analysis_end_to_end_smoke():
    timestamps = pd.date_range("2026-01-01", periods=30, freq="D")
    values = [100 + (i % 5) for i in range(30)]
    result = run_analysis(timestamps, values, ExtremeParams(window=5),
                           ChangeParams(roc_baseline_window=5), MaterialityWeights())
    assert result.summary["row_count"] == 30
    assert "MaterialityScore" in result.table.columns
    assert "State" in result.table.columns


def test_extreme_flag_triggers_on_clear_spike():
    timestamps = pd.date_range("2026-01-01", periods=20, freq="D")
    values = [100.0] * 19 + [200.0]
    result = run_analysis(timestamps, values, ExtremeParams(window=10),
                           ChangeParams(roc_baseline_window=10), MaterialityWeights())
    assert bool(result.table.iloc[-1]["ExtremeFlag"]) is True
