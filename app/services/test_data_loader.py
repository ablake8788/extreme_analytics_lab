"""Tests for both input layouts handled by data_loader."""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest

from app.services.data_loader import (
    DATETIME_COL, read_table, read_sheet, list_sheets, column_names, extract_series,
)

VALUE_COL = "AHU 1 (channel 0) [Fahrenheit]"


def _sensor_rows():
    """Sensor-export layout, including the DST fall-back hour (local time
    repeats 01:00-01:59 on 2025-11-02) and rows written out of order."""
    header = ["Date", "Time", "Timezone", "Timestamp (UTC)", "Day/Night", "AHU 1 (channel 0)"]
    units = ["MM/DD/YYYY", "hh:mm:ss", None, "seconds", None, "Fahrenheit"]
    data = [
        (dt.datetime(2025, 11, 2), dt.time(0, 47, 19), 1762058839, "Night", 72.1),
        (dt.datetime(2025, 11, 2), dt.time(1, 47, 0), 1762062420, "Night", 72.4),
        (dt.datetime(2025, 11, 2), dt.time(1, 2, 3), 1762063323, "Night", 72.6),   # second 01:xx
        (dt.datetime(2025, 11, 2), dt.time(1, 17, 25), 1762060645, "Night", 72.3), # out of order
        (dt.datetime(2025, 11, 2), dt.time(2, 1, 45), 1762066905, "Night", 72.9),
    ]
    rows = [units] + [[d, t, "America/New_York", e, dn, v] for d, t, e, dn, v in data]
    return header, rows


@pytest.fixture
def sensor_xlsx(tmp_path):
    header, rows = _sensor_rows()
    path = tmp_path / "sensor.xlsx"
    pd.DataFrame(rows, columns=header).to_excel(path, index=False, sheet_name="Sheet1")
    return str(path)


@pytest.fixture
def sensor_csv(tmp_path):
    header, rows = _sensor_rows()
    text_rows = [rows[0]] + [
        [r[0].strftime("%m/%d/%Y"), r[1].strftime("%H:%M:%S"), r[2], r[3], r[4], r[5]] for r in rows[1:]
    ]
    path = tmp_path / "sensor.csv"
    pd.DataFrame(text_rows, columns=header).to_csv(path, index=False)
    return str(path)


@pytest.fixture
def simple_xlsx(tmp_path):
    path = tmp_path / "simple.xlsx"
    pd.DataFrame({
        "Date": pd.date_range("2026-06-01", periods=10, freq="D"),
        "SensorValue": [float(100 + i) for i in range(10)],
    }).to_excel(path, index=False, sheet_name="Sensor Readings")
    return str(path)


def _check_sensor(df):
    cols = column_names(df)
    assert cols[0] == DATETIME_COL
    assert cols[1] == VALUE_COL                      # UI pre-selects index 1 as value
    assert len(df) == 5                              # units row removed
    assert pd.api.types.is_float_dtype(df[VALUE_COL])
    assert list(df["Timestamp (UTC)"]) == sorted(df["Timestamp (UTC)"])  # UTC order

    ts, vals = extract_series(df, None, VALUE_COL)   # DateTime used automatically
    assert vals == [72.1, 72.3, 72.4, 72.6, 72.9]
    assert ts[0] == pd.Timestamp("2025-11-02 00:47:19")
    assert ts[2] == pd.Timestamp("2025-11-02 01:47:00")
    assert ts[3] == pd.Timestamp("2025-11-02 01:02:03")  # repeated hour kept in true order


def test_sensor_layout_xlsx(sensor_xlsx):
    assert list_sheets(sensor_xlsx) == ["Sheet1"]
    _check_sensor(read_sheet(sensor_xlsx, "Sheet1"))


def test_sensor_layout_csv(sensor_csv):
    _check_sensor(read_table(sensor_csv))


def test_epoch_column_as_timestamp(sensor_xlsx):
    df = read_sheet(sensor_xlsx, "Sheet1")
    ts, _ = extract_series(df, "Timestamp (UTC)", VALUE_COL)
    assert ts[0] == pd.Timestamp("2025-11-02 00:47:19")  # converted to New York local time


def test_simple_layout_unchanged(simple_xlsx):
    df = read_sheet(simple_xlsx, "Sensor Readings")
    assert column_names(df) == ["Date", "SensorValue"]
    ts, vals = extract_series(df, "Date", "SensorValue")
    assert len(vals) == 10 and vals[0] == 100.0
    assert ts[0] == pd.Timestamp("2026-06-01")


def test_simple_layout_row_index_when_no_timestamp(simple_xlsx):
    df = read_sheet(simple_xlsx, "Sensor Readings")
    ts, _ = extract_series(df, None, "SensorValue")
    assert ts[:3] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Time period filter
# ---------------------------------------------------------------------------
from app.services.data_loader import DataLoadError, time_range  # noqa: E402


def test_time_filter_from_to(sensor_xlsx):
    df = read_sheet(sensor_xlsx, "Sheet1")
    ts, vals = extract_series(df, None, VALUE_COL,
                              start="2025-11-02T01:00", end="2025-11-02T01:50")
    # 01:17:25 and 01:47:00 (first 01:xx pass) plus 01:02:03 (repeated hour)
    assert vals == [72.3, 72.4, 72.6]
    assert all(pd.Timestamp("2025-11-02 01:00") <= t <= pd.Timestamp("2025-11-02 01:50") for t in ts)


def test_time_filter_open_ended(sensor_xlsx):
    df = read_sheet(sensor_xlsx, "Sheet1")
    _, vals = extract_series(df, None, VALUE_COL, start="2025-11-02T01:30", end="")
    assert vals == [72.4, 72.9]
    _, vals = extract_series(df, None, VALUE_COL, start=None, end="2025-11-02 01:00:00")
    assert vals == [72.1]


def test_time_filter_errors(sensor_xlsx, simple_xlsx):
    df = read_sheet(sensor_xlsx, "Sheet1")
    with pytest.raises(DataLoadError, match="No readings"):
        extract_series(df, None, VALUE_COL, start="2030-01-01", end="2030-02-01")
    with pytest.raises(DataLoadError, match="after"):
        extract_series(df, None, VALUE_COL, start="2025-11-03", end="2025-11-01")
    simple = read_sheet(simple_xlsx, "Sensor Readings")
    with pytest.raises(DataLoadError, match="date/time column"):
        extract_series(simple, None, "SensorValue", start="2026-06-02")


def test_time_range(sensor_xlsx):
    df = read_sheet(sensor_xlsx, "Sheet1")
    first, last, n = time_range(df, None)
    assert first == pd.Timestamp("2025-11-02 00:47:19")
    assert last == pd.Timestamp("2025-11-02 02:01:45")
    assert n == 5
