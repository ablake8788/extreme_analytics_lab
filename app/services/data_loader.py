"""Reads an uploaded CSV/XLSX file into columns the engine can consume.

Supports two layouts:

1. Simple layout (original): one header row, then data.
       Date | SensorValue

2. Sensor-export layout (e.g. Jensen_Beach_AHU1_temperature.xlsx):
       Date       | Time     | Timezone         | Timestamp (UTC) | Day/Night | AHU 1 (channel 0)
       MM/DD/YYYY | hh:mm:ss |                  | seconds         |           | Fahrenheit      <- units row
       08/01/2025 | 11:29:27 | America/New_York | 1754062167      | Day       | 73.2236

   For this layout the loader:
     - detects and removes the units row, and appends the unit to measurement
       column names, e.g. "AHU 1 (channel 0) [Fahrenheit]"
     - combines Date + Time into a single "DateTime" column (local time)
     - orders rows by the UTC epoch column, so the repeated hour at the
       daylight-saving fall-back does not scramble the series
     - converts text numbers to real numbers
     - puts DateTime first and the measurement column second, so the UI
       pre-selects sensible defaults

Every function keeps the same name and signature as before, so the routes
(api.py) and the frontend need no changes.
"""
from __future__ import annotations

import datetime as _dt
import math

import pandas as pd


DATETIME_COL = "DateTime"

_DATE_NAMES = {"date", "day", "reading date"}
_TIME_NAMES = {"time", "time of day", "reading time"}
_EPOCH_HINTS = ("utc", "epoch", "unix")
_EPOCH_UNITS = {"seconds", "second", "s", "sec", "ms", "milliseconds"}


class DataLoadError(Exception):
    pass


# --------------------------------------------------------------------------
# Public API (unchanged signatures)
# --------------------------------------------------------------------------

def read_table(path: str) -> pd.DataFrame:
    lower = path.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm")):
            raw = pd.read_excel(path, engine="openpyxl")
        elif lower.endswith(".csv"):
            raw = pd.read_csv(path)
        else:
            raise DataLoadError("Unsupported file type. Use .csv, .xlsx, or .xlsm.")
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(f"Could not read file: {exc}")
    return normalize_layout(raw)


def read_sheet(path: str, sheet_name: str) -> pd.DataFrame:
    try:
        raw = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    except Exception as exc:
        raise DataLoadError(f"Could not read sheet '{sheet_name}': {exc}")
    return normalize_layout(raw)


def list_sheets(path: str) -> list:
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return []
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        return xl.sheet_names
    except Exception as exc:
        raise DataLoadError(f"Could not open workbook: {exc}")


def column_names(df: pd.DataFrame) -> list:
    return [str(c) for c in df.columns]


def extract_series(df: pd.DataFrame, timestamp_col: str | None, value_col: str):
    """Returns (timestamps, values) as lists, in the file's time order.

    If no timestamp column is chosen but the loader built a DateTime column,
    DateTime is used automatically. A numeric epoch column (e.g.
    "Timestamp (UTC)") is converted to local date-times.
    """
    if value_col not in df.columns:
        raise DataLoadError(f"Value column '{value_col}' not found.")
    values = pd.to_numeric(df[value_col], errors="coerce")
    if values.isna().all():
        raise DataLoadError(f"Column '{value_col}' has no numeric data.")

    if not timestamp_col and DATETIME_COL in df.columns:
        timestamp_col = DATETIME_COL

    if timestamp_col and timestamp_col in df.columns:
        timestamps = _to_timestamps(df, timestamp_col)
    else:
        timestamps = pd.Series(range(1, len(df) + 1), index=df.index)

    combined = pd.DataFrame({"ts": timestamps, "val": values}).dropna(subset=["val"])
    return list(combined["ts"]), list(combined["val"])


# --------------------------------------------------------------------------
# Layout normalization
# --------------------------------------------------------------------------

def normalize_layout(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = df.loc[:, [not c.lower().startswith("unnamed:") or df[c].notna().any() for c in df.columns]]
    if df.empty:
        raise DataLoadError("The sheet has no data rows.")

    # 1. Units row directly under the header
    units: dict[str, str] = {}
    if _is_units_row(df):
        first = df.iloc[0]
        units = {c: str(first[c]).strip() for c in df.columns if isinstance(first[c], str)}
        df = df.iloc[1:].reset_index(drop=True)

    # 2. Text that is really numbers -> numbers
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            converted = pd.to_numeric(df[col], errors="coerce")
            non_null = df[col].notna().sum()
            if non_null and converted.notna().sum() / non_null >= 0.95:
                df[col] = converted

    # 3. Epoch (UTC seconds) column, if any
    epoch_col = _find_epoch_col(df, units)

    # 4. Build DateTime from separate Date + Time columns
    date_col = _find_named(df, _DATE_NAMES)
    time_col = _find_named(df, _TIME_NAMES)
    built_datetime = False
    if date_col and time_col and DATETIME_COL not in df.columns:
        combined = _combine_date_time(df[date_col], df[time_col])
        if combined.notna().mean() >= 0.9:
            df.insert(0, DATETIME_COL, combined)
            built_datetime = True
    if not built_datetime and epoch_col and DATETIME_COL not in df.columns:
        df.insert(0, DATETIME_COL, _epoch_to_local(df[epoch_col], _single_timezone(df)))
        built_datetime = True

    # 5. Chronological order (UTC epoch is DST-safe; local time is not)
    if epoch_col:
        df = df.sort_values(epoch_col, kind="stable")
    elif built_datetime:
        df = df.sort_values(DATETIME_COL, kind="stable")
    df = df.reset_index(drop=True)

    # 6. Append units to measurement column names
    skip = {DATETIME_COL, date_col, time_col, epoch_col}
    measurement_cols = [
        c for c in df.columns
        if c not in skip and pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
    ]
    renames = {c: f"{c} [{units[c]}]" for c in measurement_cols if units.get(c)}
    df = df.rename(columns=renames)
    measurement_cols = [renames.get(c, c) for c in measurement_cols]

    # 7. Column order: DateTime, measurements, everything else
    if built_datetime:
        rest = [c for c in df.columns if c != DATETIME_COL and c not in measurement_cols]
        df = df[[DATETIME_COL] + measurement_cols + rest]

    df.attrs["units"] = units
    df.attrs["epoch_column"] = epoch_col
    return df


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_blank(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _looks_like_value(v) -> bool:
    """True for anything that is data rather than a unit label."""
    if _is_blank(v):
        return False
    if not isinstance(v, str):
        return True
    s = v.strip()
    try:
        float(s)
        return True
    except ValueError:
        pass
    try:
        pd.to_datetime(s)
        return True
    except (ValueError, TypeError, OverflowError):
        return False


def _is_units_row(df: pd.DataFrame) -> bool:
    """Row 0 is a units row when every filled cell is a text label (not a
    number or date) sitting above a column of real data."""
    if len(df) < 3:
        return False
    first = df.iloc[0]
    below = df.iloc[1:51]
    checked = 0
    for col in df.columns:
        v = first[col]
        if _is_blank(v):
            continue
        checked += 1
        if not isinstance(v, str) or _looks_like_value(v):
            return False
        col_below = below[col].dropna()
        if col_below.empty:
            return False
        if col_below.map(_looks_like_value).mean() < 0.9:
            return False
    return checked > 0


def _find_named(df: pd.DataFrame, names: set) -> str | None:
    for c in df.columns:
        if c.strip().lower() in names:
            return c
    return None


def _find_epoch_col(df: pd.DataFrame, units: dict) -> str | None:
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        named = any(h in c.lower() for h in _EPOCH_HINTS)
        unit_ok = units.get(c, "").strip().lower() in _EPOCH_UNITS
        if not (named or unit_ok):
            continue
        s = df[c].dropna()
        if s.empty:
            continue
        if s.between(1e9, 1e10).mean() > 0.95 or s.between(1e12, 1e13).mean() > 0.95:
            return c
    return None


def _single_timezone(df: pd.DataFrame) -> str | None:
    tz_col = _find_named(df, {"timezone", "time zone", "tz"})
    if not tz_col:
        return None
    zones = df[tz_col].dropna().astype(str).str.strip().unique()
    return zones[0] if len(zones) == 1 else None


def _epoch_to_local(series: pd.Series, tz: str | None) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    unit = "ms" if s.dropna().gt(1e11).mean() > 0.5 else "s"
    ts = pd.to_datetime(s, unit=unit, utc=True)
    if tz:
        try:
            ts = ts.dt.tz_convert(tz)
        except Exception:
            pass
    return ts.dt.tz_localize(None)


def _time_to_timedelta(v):
    if _is_blank(v):
        return pd.NaT
    if isinstance(v, _dt.datetime):
        v = v.time()
    if isinstance(v, _dt.time):
        return pd.Timedelta(hours=v.hour, minutes=v.minute, seconds=v.second, microseconds=v.microsecond)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 0 <= v < 1:  # Excel fraction of a day
            return pd.Timedelta(days=float(v))
        return pd.NaT
    try:
        return pd.to_timedelta(str(v).strip())
    except (ValueError, TypeError):
        try:
            t = pd.to_datetime(str(v).strip())
            return pd.Timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        except (ValueError, TypeError):
            return pd.NaT


def _combine_date_time(dates: pd.Series, times: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates, errors="coerce")
    if d.isna().mean() > 0.5:  # text dates like 08/01/2025
        d = pd.to_datetime(dates.astype(str), format="%m/%d/%Y", errors="coerce")
    t = times.map(_time_to_timedelta)
    return d.dt.normalize() + pd.to_timedelta(t)


def _to_timestamps(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if col == df.attrs.get("epoch_column") or (
        pd.api.types.is_numeric_dtype(s) and s.dropna().between(1e9, 1e13).mean() > 0.95
    ):
        return _epoch_to_local(s, _single_timezone(df))
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    try:
        return pd.to_datetime(s)
    except Exception:
        return s  # fall back to raw values as labels
