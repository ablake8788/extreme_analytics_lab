import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from app.services.extreme_change_engine import ExtremeParams, ChangeParams, MaterialityWeights, run_analysis
from app.services.report_generator import (
    render_chart_png, chart_png_base64, generate_findings,
    generate_recommendations, generate_markdown_report,
)


def _sample_result():
    timestamps = pd.date_range("2026-01-01", periods=60, freq="D")
    values = [100.0] * 30 + [140.0] * 20 + [100.0] * 10  # sustained step shift
    return run_analysis(timestamps, values, ExtremeParams(window=15), ChangeParams(roc_baseline_window=15), MaterialityWeights())


def test_chart_renders_valid_png_bytes():
    result = _sample_result()
    png_bytes = render_chart_png(result.table, "Value", ExtremeParams(window=15))
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG file signature
    assert len(png_bytes) > 1000


def test_chart_base64_is_decodable():
    result = _sample_result()
    b64 = chart_png_base64(result.table, "Value", ExtremeParams(window=15))
    import base64
    decoded = base64.b64decode(b64)
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


def test_findings_are_generated_and_nonempty():
    result = _sample_result()
    ext_params = ExtremeParams(window=15)
    chg_params = ChangeParams(roc_baseline_window=15)
    findings = generate_findings(result.table, result.summary, ext_params, chg_params)
    assert len(findings) >= 3
    assert all(isinstance(f, str) and len(f) > 0 for f in findings)


def test_recommendations_are_generated():
    result = _sample_result()
    ext_params = ExtremeParams(window=15)
    chg_params = ChangeParams(roc_baseline_window=15)
    recs = generate_recommendations(result.summary, ext_params, chg_params)
    assert len(recs) >= 2


def test_no_extreme_periods_produces_relevant_recommendation():
    """Flat data with no deviation should trigger the 'no extremes' guidance."""
    timestamps = pd.date_range("2026-01-01", periods=30, freq="D")
    values = [100.0] * 30
    ext_params = ExtremeParams(window=10)
    chg_params = ChangeParams(roc_baseline_window=10)
    result = run_analysis(timestamps, values, ext_params, chg_params, MaterialityWeights())
    recs = generate_recommendations(result.summary, ext_params, chg_params)
    assert any("no periods were flagged extreme" in r.lower() for r in recs)


def test_markdown_report_contains_all_sections():
    result = _sample_result()
    ext_params = ExtremeParams(window=15)
    chg_params = ChangeParams(roc_baseline_window=15)
    md = generate_markdown_report(
        result.table, result.summary, ext_params, chg_params,
        value_column="TestValue", source_filename="test.xlsx",
    )
    for heading in ("## 1. Configuration", "## 2. Summary Statistics", "## 3. Findings", "## 4. Recommendations"):
        assert heading in md
    assert "test.xlsx" in md
    assert "TestValue" in md


def test_flat_data_does_not_produce_nan_in_findings():
    """Regression test: constant data yields NaN max_abs_zscore (sigma=0),
    which previously leaked into the finding text as literal 'nan'."""
    timestamps = pd.date_range("2026-01-01", periods=30, freq="D")
    values = [100.0] * 30
    ext_params = ExtremeParams(window=10)
    chg_params = ChangeParams(roc_baseline_window=10)
    result = run_analysis(timestamps, values, ext_params, chg_params, MaterialityWeights())
    findings = generate_findings(result.table, result.summary, ext_params, chg_params)
    assert not any("nan" in f.lower() for f in findings)


def test_findings_never_crash_on_zero_confirmed_shifts():
    """Guards the branch where confirmed_shift_periods == 0 but persistent > 0."""
    timestamps = pd.date_range("2026-01-01", periods=40, freq="D")
    values = [100.0] * 20 + [115.0] * 5 + [100.0] * 15  # short-lived deviation
    ext_params = ExtremeParams(window=10, n_m=20)  # n_m unreachable by design
    chg_params = ChangeParams(roc_baseline_window=10)
    result = run_analysis(timestamps, values, ext_params, chg_params, MaterialityWeights())
    findings = generate_findings(result.table, result.summary, ext_params, chg_params)
    assert any("confirmed" in f.lower() or "persistent" in f.lower() or "isolated" in f.lower() for f in findings)
