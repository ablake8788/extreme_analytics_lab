"""
extreme_change_engine.py

Implements the Consolidated Standardized Time-Series Analytics Framework:
  - Channel 1 (Extreme):    is the value outside its normal range?
  - Channel 2 (Change):     is the series' rate of movement abnormal?
  - Persistence/Hysteresis: how long has a deviation sustained?
  - Materiality:            is the deviation significant enough to report?

Five interchangeable baseline methods are supported for the Extreme
channel (selectable per run): rolling Bollinger/Z-score, EWMA, percentile/
quantile, IQR fences, and MAD/robust Z-score. The Change channel always
uses its own standardized Rate-of-Change (Z_ROC) baseline, independent of
whichever Extreme method is selected, per the framework's requirement
that the two channels stay analytically separate.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import pandas as pd
import numpy as np


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

@dataclass
class ExtremeParams:
    baseline_method: str = "bollinger"   # bollinger | ewma | percentile | iqr | mad
    window: int = 20                     # W: rolling lookback for MA/sigma
    ewma_alpha: float = 0.3              # alpha for EWMA baseline
    k_e: float = 2.0                     # extreme entry threshold (std devs)
    k_p: float = 1.0                     # persistence continuation threshold (< k_e)
    n_p: int = 3                         # min consecutive periods for "Persistent"
    n_m: int = 7                         # min consecutive periods for "Confirmed/Materialized"
    k_m: float = 1.2                     # min mean |Z| over the event for confirmed shift
    n_exit: int = 1                      # consecutive sub-threshold periods to close an event
    percentile_p: float = 0.01           # p for percentile method (uses p and 1-p)
    k_iqr: float = 1.5                   # IQR fence multiplier


@dataclass
class ChangeParams:
    roc_window: int = 1                  # h: horizon for ROC(t,h)
    roc_baseline_window: int = 20        # rolling window for ROC's own mean/std
    roc_k: float = 2.0                   # |Z_ROC| threshold for abnormal change
    frequency_window: int = 10           # trailing periods to count recurrence
    frequency_min_count: int = 2         # min abnormal changes in window to be "material"


@dataclass
class MaterialityWeights:
    w_magnitude: float = 0.4
    w_duration: float = 0.4
    w_frequency: float = 0.2


# --------------------------------------------------------------------------
# Extreme channel
# --------------------------------------------------------------------------

def _rolling_mad(series: pd.Series, window: int) -> pd.Series:
    def mad(x):
        med = np.median(x)
        return np.median(np.abs(x - med))
    return series.rolling(window, min_periods=2).apply(mad, raw=True)


def compute_baseline(x: pd.Series, params: ExtremeParams):
    """Returns (ma, sigma, upper_limit, lower_limit, z) for the chosen method.
    For percentile/IQR methods, z is a magnitude-comparable pseudo-Z
    (computed from the overall mean/std) since those methods define limits
    directly rather than via a Z threshold; the extreme decision for those
    methods still uses the direct upper/lower limits, not z."""
    method = params.baseline_method

    if method == "bollinger":
        ma = x.rolling(params.window, min_periods=2).mean()
        sigma = x.rolling(params.window, min_periods=2).std(ddof=1)
        upper = ma + params.k_e * sigma
        lower = ma - params.k_e * sigma
        z = (x - ma) / sigma
        return ma, sigma, upper, lower, z

    if method == "ewma":
        ma = x.ewm(alpha=params.ewma_alpha, adjust=False).mean()
        sigma = x.rolling(params.window, min_periods=2).std(ddof=1)
        upper = ma + params.k_e * sigma
        lower = ma - params.k_e * sigma
        z = (x - ma) / sigma
        return ma, sigma, upper, lower, z

    if method == "mad":
        med = x.expanding(min_periods=2).median()
        mad = _rolling_mad(x, params.window)
        mad_safe = mad.replace(0, np.nan)
        robust_z = 0.6745 * (x - med) / mad_safe
        upper = med + (params.k_e / 0.6745) * mad_safe
        lower = med - (params.k_e / 0.6745) * mad_safe
        return med, mad, upper, lower, robust_z

    if method == "percentile":
        lower_q = x.quantile(params.percentile_p)
        upper_q = x.quantile(1 - params.percentile_p)
        overall_mean = x.mean()
        overall_std = x.std(ddof=1)
        z = (x - overall_mean) / overall_std if overall_std else x * 0
        upper = pd.Series(upper_q, index=x.index)
        lower = pd.Series(lower_q, index=x.index)
        ma = pd.Series(overall_mean, index=x.index)
        return ma, pd.Series(overall_std, index=x.index), upper, lower, z

    if method == "iqr":
        q1 = x.quantile(0.25)
        q3 = x.quantile(0.75)
        iqr = q3 - q1
        upper = pd.Series(q3 + params.k_iqr * iqr, index=x.index)
        lower = pd.Series(q1 - params.k_iqr * iqr, index=x.index)
        overall_mean = x.mean()
        overall_std = x.std(ddof=1)
        z = (x - overall_mean) / overall_std if overall_std else x * 0
        return pd.Series(overall_mean, index=x.index), pd.Series(overall_std, index=x.index), upper, lower, z

    raise ValueError(f"Unknown baseline_method: {method}")


def extreme_channel(x: pd.Series, params: ExtremeParams) -> pd.DataFrame:
    ma, sigma, upper, lower, z = compute_baseline(x, params)

    if params.baseline_method in ("percentile", "iqr"):
        extreme_flag = (x > upper) | (x < lower)
    else:
        extreme_flag = z.abs() >= params.k_e

    direction = np.where(x > upper, "upper", np.where(x < lower, "lower", "none"))
    delta_upper = x - upper
    delta_lower = lower - x
    delta_upper_pct = np.where(upper != 0, delta_upper / upper * 100, np.nan)
    delta_lower_pct = np.where(lower != 0, delta_lower / lower * 100, np.nan)

    return pd.DataFrame({
        "MovingAverage": ma,
        "RollingStdDev": sigma,
        "UpperLimit": upper,
        "LowerLimit": lower,
        "ZScore": z,
        "ExtremeFlag": extreme_flag,
        "ExtremeDirection": direction,
        "DeltaUpper": delta_upper,
        "DeltaLower": delta_lower,
        "DeltaUpper_pct": delta_upper_pct,
        "DeltaLower_pct": delta_lower_pct,
    }, index=x.index)


# --------------------------------------------------------------------------
# Persistence / hysteresis state machine
# --------------------------------------------------------------------------

def persistence_state_machine(z: pd.Series, extreme_flag: pd.Series, params: ExtremeParams) -> pd.DataFrame:
    """Implements hysteresis: a stronger threshold (k_e) starts an event, a
    weaker threshold (k_p) maintains it, and n_exit consecutive periods
    below k_p closes it. Promotes to 'Persistent' at n_p periods and to
    'Confirmed/Materialized Shift' at n_m periods with mean |Z| >= k_m."""
    n = len(z)
    states = [""] * n
    persistence_counts = [0] * n
    event_starts = [None] * n
    event_ends = [None] * n
    mean_z_event = [np.nan] * n

    in_event = False
    persistence = 0
    event_zs: list[float] = []
    exit_streak = 0
    event_start_idx = None

    z_vals = z.to_numpy()
    trigger = extreme_flag.to_numpy()
    idx = z.index

    for i in range(n):
        zi = z_vals[i]
        continuation = (not math.isnan(zi)) and abs(zi) >= params.k_p
        triggers_now = bool(trigger[i])

        if not in_event:
            if triggers_now:
                in_event = True
                persistence = 1
                event_zs = [zi]
                event_start_idx = i
                exit_streak = 0
                states[i] = "Extreme triggered"
            else:
                persistence = 0
                states[i] = "Normal"
        else:
            if continuation:
                exit_streak = 0
                persistence += 1
                event_zs.append(zi)
                mean_abs_z = float(np.nanmean(np.abs(event_zs)))
                if persistence >= params.n_m and mean_abs_z >= params.k_m:
                    states[i] = "Confirmed/Materialized Shift"
                elif persistence >= params.n_p:
                    states[i] = "Persistent"
                else:
                    states[i] = "Extreme/elevated"
            else:
                exit_streak += 1
                if exit_streak >= params.n_exit:
                    states[i] = "Persistence ends"
                    event_ends[event_start_idx] = idx[i]
                    in_event = False
                    persistence = 0
                    event_zs = []
                    event_start_idx = None
                else:
                    # still within tolerance, treat as still-persistent (noise tolerance)
                    persistence += 1
                    event_zs.append(zi)
                    states[i] = "Persistent" if persistence >= params.n_p else "Extreme/elevated"

        persistence_counts[i] = persistence
        if event_start_idx is not None:
            event_starts[i] = idx[event_start_idx]
            mean_z_event[i] = float(np.nanmean(np.abs(event_zs))) if event_zs else np.nan

    return pd.DataFrame({
        "State": states,
        "PersistenceCount": persistence_counts,
        "EventStartTime": event_starts,
        "EventEndTime": event_ends,
        "MeanZ_event": mean_z_event,
    }, index=idx)


# --------------------------------------------------------------------------
# Change / Rate-of-Change channel
# --------------------------------------------------------------------------

def change_channel(x: pd.Series, params: ChangeParams) -> pd.DataFrame:
    delta_x = x.diff(1)
    roc = (x - x.shift(params.roc_window)) / params.roc_window
    roc_mean = roc.rolling(params.roc_baseline_window, min_periods=2).mean()
    roc_sigma = roc.rolling(params.roc_baseline_window, min_periods=2).std(ddof=1)
    z_roc = (roc - roc_mean) / roc_sigma

    abnormal_change = z_roc.abs() >= params.roc_k
    frequency_count = abnormal_change.rolling(params.frequency_window, min_periods=1).sum()
    material_change = abnormal_change & (frequency_count >= params.frequency_min_count)

    return pd.DataFrame({
        "DeltaX": delta_x,
        "ROC": roc,
        "ROC_MeanBaseline": roc_mean,
        "ROC_StdDev": roc_sigma,
        "ROC_ZScore": z_roc,
        "AbnormalChangeFlag": abnormal_change.fillna(False),
        "FrequencyCount": frequency_count,
        "MaterialChangeFlag": material_change.fillna(False),
    }, index=x.index)


# --------------------------------------------------------------------------
# Materiality
# --------------------------------------------------------------------------

def materiality(extreme_df: pd.DataFrame, persistence_df: pd.DataFrame,
                 change_df: pd.DataFrame, ext_params: ExtremeParams,
                 weights: MaterialityWeights) -> pd.DataFrame:
    magnitude_criterion = extreme_df["ExtremeFlag"]
    duration_criterion = persistence_df["PersistenceCount"] >= ext_params.n_p
    material_extreme = magnitude_criterion & duration_criterion
    confirmed_shift = persistence_df["State"] == "Confirmed/Materialized Shift"

    z = extreme_df["ZScore"].abs()
    magnitude_score = (z / ext_params.k_e).clip(upper=3) / 3
    duration_score = (persistence_df["PersistenceCount"] / ext_params.n_m).clip(upper=1)
    frequency_score = (change_df["FrequencyCount"] / max(ext_params.n_m, 1)).clip(upper=1)

    materiality_score = (
        weights.w_magnitude * magnitude_score.fillna(0)
        + weights.w_duration * duration_score.fillna(0)
        + weights.w_frequency * frequency_score.fillna(0)
    )

    return pd.DataFrame({
        "MaterialExtremeFlag": material_extreme,
        "ConfirmedShiftFlag": confirmed_shift,
        "MaterialChangeFlag": change_df["MaterialChangeFlag"],
        "MaterialityScore": materiality_score.round(4),
    }, index=extreme_df.index)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    table: pd.DataFrame
    summary: dict = field(default_factory=dict)


def run_analysis(timestamps, values, ext_params: ExtremeParams,
                  chg_params: ChangeParams, weights: MaterialityWeights) -> AnalysisResult:
    x = pd.Series(values, index=pd.Index(timestamps, name="Timestamp"), dtype="float64")

    extreme_df = extreme_channel(x, ext_params)
    persistence_df = persistence_state_machine(extreme_df["ZScore"], extreme_df["ExtremeFlag"], ext_params)
    change_df = change_channel(x, chg_params)
    material_df = materiality(extreme_df, persistence_df, change_df, ext_params, weights)

    table = pd.concat(
        [x.rename("Value"), extreme_df, persistence_df, change_df, material_df], axis=1
    )
    table.reset_index(inplace=True)

    summary = {
        "row_count": int(len(table)),
        "baseline_method": ext_params.baseline_method,
        "extreme_periods": int(extreme_df["ExtremeFlag"].sum()),
        "persistent_periods": int((persistence_df["State"] == "Persistent").sum()),
        "confirmed_shift_periods": int((persistence_df["State"] == "Confirmed/Materialized Shift").sum()),
        "material_extreme_periods": int(material_df["MaterialExtremeFlag"].sum()),
        "abnormal_change_periods": int(change_df["AbnormalChangeFlag"].sum()),
        "material_change_periods": int(material_df["MaterialChangeFlag"].sum()),
        "max_abs_zscore": float(np.nanmax(np.abs(extreme_df["ZScore"]))) if len(extreme_df) else None,
    }
    return AnalysisResult(table=table, summary=summary)
