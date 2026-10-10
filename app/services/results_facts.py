"""
results_facts.py - computes the facts for an AI results report from a
results table (an exported results CSV or the rows of an analysis).

Everything here is deterministic Python. The AI only writes wording around
these facts; every number in the report tables comes from here.

Methods follow the Titanium Analytics approach:
  Extremes   - readings far from what is typical for that hour of the day
  Changes    - unusual speed/size of changes between readings
  Volatility - unusual instability (variability, direction reversals)
plus data gaps, and a check of how the engine's own flags were produced.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

TRANSITION_SHARE = 0.10   # hour counts as a schedule transition if its typical value moves >10% of the daily range
MIN_RUN_MINUTES = 60      # an abnormality must last at least this long
MAX_ABNORMALITIES = 5


class FactsError(ValueError):
    pass


# ---------------------------------------------------------------- helpers
def _r(x, n=2):
    if x is None:
        return None
    try:
        if isinstance(x, (np.floating, float)) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return round(float(x), n)
    return x


def _ts(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")


def _dur(minutes: float) -> str:
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def units_from_text(text: str) -> str:
    m = re.search(r"\[([^\]]+)\]", text or "")
    unit = (m.group(1) if m else "").strip().lower()
    return {"fahrenheit": "°F", "celsius": "°C", "f": "°F", "c": "°C"}.get(unit, m.group(1) if m else "")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.strip(): c for c in df.columns}
    if "Timestamp" not in cols or "Value" not in cols:
        raise FactsError("The results file needs 'Timestamp' and 'Value' columns (export it from the app).")
    d = df.rename(columns={v: k for k, v in cols.items()}).copy()
    d["Timestamp"] = pd.to_datetime(d["Timestamp"], errors="coerce")
    d["Value"] = pd.to_numeric(d["Value"], errors="coerce")
    d = d.dropna(subset=["Timestamp", "Value"]).sort_values("Timestamp", kind="stable").reset_index(drop=True)
    if len(d) < 24:
        raise FactsError("Need at least 24 readings with a time and a value to write a report.")
    for c in ("ExtremeFlag", "AbnormalChangeFlag", "MaterialChangeFlag", "ConfirmedShiftFlag"):
        d[c] = _bool(d[c]) if c in d else False
    for c in ("MovingAverage", "RollingStdDev", "UpperLimit", "LowerLimit", "ZScore", "ROC_ZScore"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    if "State" not in d:
        d["State"] = "Normal"
    d["State"] = d["State"].fillna("Normal").astype(str)
    return d


# ---------------------------------------------------------------- main
def compute_facts(df: pd.DataFrame, location: str = "", units: str = "", source_name: str = "") -> dict:
    d = prepare(df)
    u = units or ""
    t, v = d["Timestamp"], d["Value"]
    step_min = t.diff().dt.total_seconds() / 60
    interval = float(step_min.median())
    per_day = max(1, int(round(24 * 60 / interval))) if interval > 0 else 96

    # ---- data gaps
    gap_limit = max(60.0, 4 * interval)
    gaps = []
    for i in np.where(step_min > gap_limit)[0]:
        gaps.append({"start": _ts(t[i - 1]), "end": _ts(t[i]), "minutes": _r(step_min[i], 0),
                     "duration": _dur(step_min[i]), "missing_readings": int(round(step_min[i] / interval)) - 1})
    after_gap = set(int(i) for i in np.where(step_min > gap_limit)[0])

    # ---- settings detected from the file
    window = None
    if "MovingAverage" in d:
        for w in (5, 10, 12, 20, 24, 30, 48, 60, 96, 144, 192, 288):
            ma = v.rolling(w, min_periods=2).mean()
            diff = (ma - d["MovingAverage"]).abs().max()
            if pd.notna(diff) and diff < 1e-6:
                window = w
                break
    k_e = None
    if {"UpperLimit", "MovingAverage", "RollingStdDev"} <= set(d.columns):
        k = ((d["UpperLimit"] - d["MovingAverage"]) / d["RollingStdDev"]).replace([np.inf, -np.inf], np.nan).median()
        k_e = _r(k, 2)

    uniq = np.sort(v.round(4).unique())
    steps = np.diff(uniq)
    sensor_step = _r(float(np.median(steps[steps > 1e-6])) if (steps > 1e-6).any() else 0.0, 2)

    # ---- typical daily cycle (hour of day)
    d["hour"] = t.dt.hour
    prof = d.groupby("hour")["Value"].median()
    daily_range = float(prof.max() - prof.min()) if len(prof) else 0.0
    hourly = [{"hour": int(h), "typical": _r(val)} for h, val in prof.items()]
    blocks = []
    for a in range(0, 24, 4):
        hrs = [h for h in range(a, a + 4) if h in prof.index]
        if hrs:
            blocks.append({"hours": f"{a:02d}:00-{a + 3:02d}:59",
                           "typical_min": _r(prof[hrs].min()), "typical_max": _r(prof[hrs].max())})
    moves = prof.diff().abs().fillna(0)
    transition_hours = sorted(int(h) for h in prof.index
                              if moves.get(h, 0) > TRANSITION_SHARE * daily_range
                              or moves.get((h + 1) % 24, 0) > TRANSITION_SHARE * daily_range)
    d["date"] = t.dt.date
    days = d.groupby("date")["Value"].agg(["min", "max"])
    amp = (days["max"] - days["min"])
    full_days = d.groupby("date").size() >= 0.8 * per_day
    amp_full = amp[full_days] if full_days.any() else amp

    # ---- extremes: deviation from typical-for-hour
    d["typical"] = d["hour"].map(prof)
    d["dev"] = d["Value"] - d["typical"]
    mad = float((d["dev"] - d["dev"].median()).abs().median()) * 1.4826
    threshold = max(3 * mad, 4 * (sensor_step or 0), 0.05 * daily_range, 1e-9)
    flag = d["dev"].abs() > threshold
    runs = []
    sign = np.sign(d["dev"])
    run_id = ((flag != flag.shift()) | (sign != sign.shift())).cumsum()  # split when direction flips
    for _, sub in d[flag].groupby(run_id[flag]):
        runs.append([sub.index[0], sub.index[-1]])
    # merge runs that are only separated by a data gap or a single normal reading
    merged = []
    for a, b in runs:
        if merged and (a in after_gap or a - merged[-1][1] <= 2) and \
                np.sign(d["dev"][a]) == np.sign(d["dev"][merged[-1][1]]):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    abn = []
    for a, b in merged:
        sub = d.loc[a:b]
        minutes = (sub["Timestamp"].iloc[-1] - sub["Timestamp"].iloc[0]).total_seconds() / 60 + interval
        if minutes < MIN_RUN_MINUTES:
            continue
        pk = sub["dev"].abs().idxmax()
        spans_gap = any(a < g <= b for g in after_gap)
        abn.append({
            "start": _ts(sub["Timestamp"].iloc[0]), "end": _ts(sub["Timestamp"].iloc[-1]),
            "minutes": _r(minutes, 0), "duration": _dur(minutes),
            "direction": "below" if d["dev"][pk] < 0 else "above",
            "peak_time": _ts(d["Timestamp"][pk]), "observed": _r(d["Value"][pk]),
            "typical_at_peak": _r(d["typical"][pk]), "peak_deviation": _r(d["dev"][pk]),
            "typical_range": f"{_r(sub['typical'].min())}-{_r(sub['typical'].max())}",
            "observed_range": f"{_r(sub['Value'].min())}-{_r(sub['Value'].max())}",
            "readings": int(len(sub)), "spans_data_gap": spans_gap,
            "weekday": pd.Timestamp(sub["Timestamp"].iloc[0]).day_name(),
            "day_night": (sub["Day/Night"].mode().iloc[0] if "Day/Night" in sub and sub["Day/Night"].notna().any() else None),
            "status": "Continuing" if b == d.index[-1] else "Resolved",
            "score": _r(abs(d["dev"][pk]) * max(minutes, 1) / 60, 2),
        })
    abn.sort(key=lambda x: x["score"], reverse=True)
    abnormalities, minor = abn[:MAX_ABNORMALITIES], abn[MAX_ABNORMALITIES:]
    # keep only substantial ones as "abnormalities": at least 25% of the top score
    if abnormalities:
        top = abnormalities[0]["score"]
        minor = [x for x in abnormalities if x["score"] < 0.25 * top] + minor
        abnormalities = [x for x in abnormalities if x["score"] >= 0.25 * top]
    minor.sort(key=lambda x: x["start"])

    # ---- the engine's own flags
    nonnormal = d["State"] != "Normal"
    events = int((nonnormal & ~nonnormal.shift(fill_value=False)).sum())
    ext = d[d["ExtremeFlag"]]
    low_var = 0
    if "RollingStdDev" in d and sensor_step:
        low_var = int((d["ExtremeFlag"] & (d["RollingStdDev"] < sensor_step)).sum())
    states = {k: int(n) for k, n in d["State"].value_counts().items()}
    flags = {
        "states": states, "extreme_readings": int(len(ext)),
        "non_normal_readings": int(nonnormal.sum()),
        "non_normal_share_pct": _r(100 * nonnormal.mean(), 1),
        "events": events,
        "extreme_in_transition_hours": int(ext["hour"].isin(transition_hours).sum()),
        "extreme_in_transition_pct": _r(100 * ext["hour"].isin(transition_hours).mean(), 0) if len(ext) else 0,
        "extreme_with_tiny_variability": low_var,
        "abnormal_change_readings": int(d["AbnormalChangeFlag"].sum()),
        "material_change_readings": int(d["MaterialChangeFlag"].sum()),
    }

    # ---- re-run the engine with a daily window for comparison
    comparison = None
    try:
        from app.services.extreme_change_engine import ExtremeParams, ChangeParams, MaterialityWeights, run_analysis
        rows = []
        for w in sorted({w for w in (window or 20, per_day) if w}):
            r = run_analysis(list(t), list(v), ExtremeParams(window=w), ChangeParams(roc_baseline_window=w),
                             MaterialityWeights())
            tb = r.table
            nn = tb["State"].astype(str) != "Normal"
            rows.append({"window": w, "hours": _r(w * interval / 60, 1),
                         "extreme_readings": int(_bool(tb["ExtremeFlag"]).sum()),
                         "non_normal_readings": int(nn.sum()),
                         "events": int((nn & ~nn.shift(fill_value=False)).sum())})
        comparison = rows
    except Exception:  # engine unavailable or failed - report without the comparison
        comparison = None

    # ---- changes
    d["step"] = d["Value"].diff()
    real = d.loc[~d.index.isin(after_gap), "step"].dropna()
    big = d.loc[real.abs().sort_values(ascending=False).index[:3]]
    ac = d[d["AbnormalChangeFlag"]]
    changes = {
        "typical_fastest_drop": _r(real.quantile(0.01)), "typical_fastest_rise": _r(real.quantile(0.99)),
        "largest_steps": [{"time": _ts(r.Timestamp), "change": _r(r.step), "hour": int(r.hour)} for r in big.itertuples()],
        "gap_spanning_steps": [{"time": _ts(d["Timestamp"][i]), "change": _r(d["step"][i])} for i in sorted(after_gap)],
        "abnormal_change_top_hours": [int(h) for h in ac["hour"].value_counts().head(3).index] if len(ac) else [],
        "abnormal_change_in_transition_pct": _r(100 * ac["hour"].isin(transition_hours).mean(), 0) if len(ac) else 0,
        "abnormal_change_day": int((ac.get("Day/Night") == "Day").sum()) if "Day/Night" in ac else None,
        "abnormal_change_night": int((ac.get("Day/Night") == "Night").sum()) if "Day/Night" in ac else None,
    }

    # ---- volatility
    def reversals(s):
        x = np.sign(s.diff().dropna())
        x = x[x != 0]
        return int((x != x.shift()).sum() - 1) if len(x) > 1 else 0
    vol = d.groupby("date").agg(step_std=("step", "std"), rev=("Value", reversals), n=("Value", "size"))
    vol["rev_per_100"] = 100 * vol["rev"] / vol["n"]
    vfull = vol[vol["n"] >= 0.8 * per_day] if (vol["n"] >= 0.8 * per_day).any() else vol
    med_rev = float(vfull["rev_per_100"].median())
    half = len(vfull) // 2
    volatility = {
        "daily_step_std_min": _r(vfull["step_std"].min()), "daily_step_std_max": _r(vfull["step_std"].max()),
        "first_half_step_std": _r(vfull["step_std"].iloc[:half].mean()) if half else None,
        "second_half_step_std": _r(vfull["step_std"].iloc[half:].mean()) if half else None,
        "typical_reversals_per_100": _r(med_rev, 1),
        "unstable_days": [{"date": str(i), "reversals_per_100": _r(r.rev_per_100, 1)}
                          for i, r in vfull.iterrows() if r.rev_per_100 > 1.5 * med_rev],
    }
    if "Day/Night" in d:
        dn = d.groupby("Day/Night")["step"].std()
        volatility["day_step_std"] = _r(dn.get("Day"))
        volatility["night_step_std"] = _r(dn.get("Night"))

    dn_counts = {k: int(n) for k, n in d["Day/Night"].value_counts().items()} if "Day/Night" in d else {}
    return {
        "location": location or "Sensor", "units": u, "source_name": source_name,
        "period_start": _ts(t.iloc[0]), "period_end": _ts(t.iloc[-1]),
        "readings": int(len(d)), "interval_minutes": _r(interval, 1), "readings_per_day": per_day,
        "day_night_counts": dn_counts,
        "value_min": _r(v.min()), "value_max": _r(v.max()), "value_mean": _r(v.mean()),
        "settings_in_file": {"window": window, "window_hours": _r(window * interval / 60, 1) if window else None, "k_e": k_e},
        "sensor_step": sensor_step,
        "daily_cycle": {"hourly": hourly, "blocks": blocks, "daily_range_typical": _r(daily_range),
                        "daily_swing_min": _r(amp_full.min()), "daily_swing_max": _r(amp_full.max()),
                        "transition_hours": transition_hours},
        "deviation_threshold": _r(threshold),
        "data_gaps": gaps, "abnormalities": abnormalities, "minor_observations": minor[:8],
        "engine_flags": flags, "window_comparison": comparison,
        "changes": changes, "volatility": volatility,
    }
