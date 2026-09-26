import os
import uuid
import math
import pandas as pd
from flask import Blueprint, request, jsonify
from app.config import Config
from app.services.data_loader import read_table, read_sheet, list_sheets, column_names, extract_series, DataLoadError
from app.services.extreme_change_engine import (
    ExtremeParams, ChangeParams, MaterialityWeights, run_analysis,
)
from app.services.report_generator import (
    chart_png_base64, generate_markdown_report,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xlsm")


@api_bp.post("/upload")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file selected."}), 400
    if not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        return jsonify({"error": "Only .csv, .xlsx, or .xlsm files are supported."}), 400

    token = uuid.uuid4().hex
    ext = ".xlsx" if file.filename.lower().endswith((".xlsx", ".xlsm")) else ".csv"
    path = Config.UPLOAD_DIR / f"{token}{ext}"
    file.save(str(path))

    try:
        sheets = list_sheets(str(path))
        if sheets:
            df = read_sheet(str(path), sheets[0])
        else:
            df = read_table(str(path))
        columns = column_names(df)
    except DataLoadError as exc:
        os.remove(path)
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "token": token + ext,
        "filename": file.filename,
        "sheets": sheets,
        "columns": columns,
        "row_count": len(df),
    })


@api_bp.get("/columns")
def columns():
    token = request.args.get("token", "")
    sheet = request.args.get("sheet", "")
    path = _resolve_path(token)
    if not path:
        return jsonify({"error": "Unknown or expired upload. Please upload the file again."}), 400
    try:
        df = read_sheet(str(path), sheet) if sheet else read_table(str(path))
    except DataLoadError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"columns": column_names(df)})


def _load_series_and_params(data: dict):
    """Shared by /analyze and /report: resolves the upload, reads the
    chosen column as a series, and builds the three parameter objects from
    the request, falling back to Config defaults. Returns
    (timestamps, values, ext_params, chg_params, weights, filename)."""
    token = data.get("token", "")
    path = _resolve_path(token)
    if not path:
        raise DataLoadError("Unknown or expired upload. Please upload the file again.")

    sheet = data.get("sheet") or ""
    df = read_sheet(str(path), sheet) if sheet else read_table(str(path))
    timestamps, values = extract_series(
            df, data.get("timestamp_column") or None, data["value_column"],
            start=data.get("date_from") or None, end=data.get("date_to") or None,
        )
    if len(values) < 5:
        raise DataLoadError("Need at least 5 numeric rows to run this analysis.")

    ext_params = ExtremeParams(
        baseline_method=data.get("baseline_method", "bollinger"),
        window=int(data.get("window", Config.WINDOW)),
        ewma_alpha=float(data.get("ewma_alpha", Config.EWMA_ALPHA)),
        k_e=float(data.get("k_e", Config.K_E)),
        k_p=float(data.get("k_p", Config.K_P)),
        n_p=int(data.get("n_p", Config.N_P)),
        n_m=int(data.get("n_m", Config.N_M)),
        k_m=float(data.get("k_m", Config.K_M)),
        n_exit=int(data.get("n_exit", Config.N_EXIT)),
        percentile_p=float(data.get("percentile_p", Config.PERCENTILE_P)),
        k_iqr=float(data.get("k_iqr", Config.K_IQR)),
    )
    chg_params = ChangeParams(
        roc_window=int(data.get("roc_window", Config.ROC_WINDOW)),
        roc_baseline_window=int(data.get("roc_baseline_window", Config.ROC_BASELINE_WINDOW)),
        roc_k=float(data.get("roc_k", Config.ROC_K)),
        frequency_window=int(data.get("frequency_window", Config.FREQUENCY_WINDOW)),
        frequency_min_count=int(data.get("frequency_min_count", Config.FREQUENCY_MIN_COUNT)),
    )
    weights = MaterialityWeights(
        w_magnitude=float(data.get("w_magnitude", Config.W_MAGNITUDE)),
        w_duration=float(data.get("w_duration", Config.W_DURATION)),
        w_frequency=float(data.get("w_frequency", Config.W_FREQUENCY)),
    )

    return timestamps, values, ext_params, chg_params, weights, os.path.basename(str(path))


@api_bp.post("/analyze")
def analyze():
    data = request.get_json(force=True)
    try:
        timestamps, values, ext_params, chg_params, weights, _ = _load_series_and_params(data)
        result = run_analysis(timestamps, values, ext_params, chg_params, weights)
    except DataLoadError as exc:
        return jsonify({"error": str(exc)}), 400
    except (KeyError, ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid parameters: {exc}"}), 400

    table = result.table.copy()
    for col in ("Timestamp", "EventStartTime", "EventEndTime"):
        if col in table.columns:
            table[col] = table[col].apply(
                lambda v: None if v is None or (hasattr(v, "__class__") and str(v) in ("NaT", "None")) or pd.isna(v) else str(v)
            )
    records = table.to_dict(orient="records")
    records = [_clean_record(r) for r in records]

    return jsonify({"summary": result.summary, "rows": records})


@api_bp.post("/report")
def report():
    """Regenerates the analysis for the given parameters and returns a
    rendered chart (base64 PNG) plus a full Markdown findings/recommendations
    report — both derived generically from whatever data/params are given."""
    data = request.get_json(force=True)
    try:
        timestamps, values, ext_params, chg_params, weights, filename = _load_series_and_params(data)
        result = run_analysis(timestamps, values, ext_params, chg_params, weights)
    except DataLoadError as exc:
        return jsonify({"error": str(exc)}), 400
    except (KeyError, ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid parameters: {exc}"}), 400

    value_column = data.get("value_column", "Value")

    try:
        chart_b64 = chart_png_base64(result.table, value_column, ext_params)
        markdown = generate_markdown_report(
            result.table, result.summary, ext_params, chg_params,
            value_column=value_column, source_filename=filename,
        )
    except Exception as exc:
        return jsonify({"error": f"Could not generate report: {exc}"}), 500

    return jsonify({
        "chart_png_base64": chart_b64,
        "markdown": markdown,
        "summary": result.summary,
    })


def _clean_record(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            fv = float(v)
            out[k] = None if (math.isnan(fv) or math.isinf(fv)) else v
        elif hasattr(v, "item"):  # numpy scalar
            item = v.item()
            if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
                out[k] = None
            else:
                out[k] = item
        else:
            out[k] = v
    return out


def _resolve_path(token: str):
    if not token:
        return None
    safe = "".join(c for c in token if c.isalnum() or c == ".")
    if safe != token:
        return None
    path = Config.UPLOAD_DIR / token
    return path if path.exists() else None


# === TIME PERIOD FILTER (added by apply_time_filter.py) =====================
from flask import request as _tp_request, jsonify as _tp_jsonify
from app.services.data_loader import (
    read_sheet as _tp_read_sheet, read_table as _tp_read_table,
    time_range as _tp_time_range, DataLoadError as _TpDataLoadError,
)


@api_bp.get("/time_range")
def time_range_route():
    """First/last timestamp of the chosen timestamp column, used to pre-fill
    the From / To inputs."""
    token = _tp_request.args.get("token", "")
    sheet = _tp_request.args.get("sheet", "")
    ts_col = _tp_request.args.get("timestamp_column", "") or None
    path = _resolve_path(token)
    if not path:
        return _tp_jsonify({"error": "Unknown or expired upload. Please upload the file again."}), 400
    try:
        df = _tp_read_sheet(str(path), sheet) if sheet else _tp_read_table(str(path))
        first, last, count = _tp_time_range(df, ts_col)
    except _TpDataLoadError as exc:
        return _tp_jsonify({"error": str(exc)}), 400
    fmt = "%Y-%m-%dT%H:%M:%S"
    return _tp_jsonify({
        "is_datetime": first is not None,
        "start": first.strftime(fmt) if first is not None else None,
        "end": last.strftime(fmt) if last is not None else None,
        "count": count,
    })
