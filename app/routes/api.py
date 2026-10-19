import os
import uuid
import math
import pandas as pd
from flask import Blueprint, request, jsonify
from app.config import Config
from app.services.data_loader import read_table, read_sheet, list_sheets, column_names, extract_series, DataLoadError
from app.services.data_loader import last_meta, last_extras, set_extras
import numpy as np
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


def _max_gap(value) -> float:
    """Max time gap in minutes; blank or negative means off (0)."""
    if value is None or str(value).strip() == "":
        return 0.0
    v = float(value)
    return v if v > 0 else 0.0


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
        max_gap_minutes=_max_gap(data.get("max_gap_minutes", Config.MAX_GAP_MINUTES)),
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


def _gap_times():
    """True UTC time of each reading (from an epoch column such as Timestamp (UTC)), or None."""
    meta = last_meta() or {}
    secs = meta.get("utc_seconds")
    return pd.to_datetime(secs, unit="s", utc=True) if secs else None


def _gaps_payload(timestamps, values, result, ext_params) -> tuple[dict | None, list]:
    """One item per reading removed by Max time gap (the reading before and the
    removed reading after the gap, side by side), and the removed readings as
    listing rows. Also keeps the Day/Night columns aligned with the kept rows."""
    keep = result.keep
    if keep is None or keep.all():
        return None, []
    meta = last_meta() or {}
    src = meta.get("source_rows") or [None] * len(values)
    ctx = meta.get("context") or {}
    gm = result.gap_minutes
    steps = gm[np.isfinite(gm)]
    interval = max(1, int(round(float(np.median(steps))))) if len(steps) else 15
    extras = last_extras() or {}
    removed_pos = np.flatnonzero(~keep)
    items, removed = [], []
    for n, i in enumerate(removed_pos, start=1):
        b = i - 1
        g = float(gm[i])
        item = {"Gap #": n,
                "Before timestamp": str(timestamps[b]), "Before value": float(values[b]), "Before source row": src[b],
                "After timestamp": str(timestamps[i]), "After value": float(values[i]), "After source row": src[i],
                "Gap minutes": round(g, 2), "Gap hours": round(round(g, 2) / 60, 4),
                f"Est. missing {interval}-min readings": int(g // interval)}
        for c, vals in ctx.items():
            item[f"Before: {c}"] = vals[b]
        for c, vals in ctx.items():
            item[f"After: {c}"] = vals[i]
        items.append(item)
        row = {"Timestamp": str(timestamps[i]), "Value": float(values[i]), "State": "Removed (time gap)",
               "TimeGap_min": round(g, 2)}
        row.update({c: v[i] for c, v in extras.items() if len(v) == len(values)})
        removed.append(row)
    if extras:   # the listing's Day/Night columns must match the kept rows only
        set_extras({c: [x for x, k in zip(v, keep) if k] for c, v in extras.items() if len(v) == len(values)})
    gaps = {"min_gap_minutes": float(ext_params.max_gap_minutes), "interval_minutes": interval,
            "measured_on": "UTC" if meta.get("utc_seconds") else "local time",
            "columns": list(items[0].keys()) if items else [], "items": items}
    return gaps, removed


@api_bp.post("/analyze")
def analyze():
    data = request.get_json(force=True)
    try:
        timestamps, values, ext_params, chg_params, weights, _ = _load_series_and_params(data)
        result = run_analysis(timestamps, values, ext_params, chg_params, weights, gap_times=_gap_times())
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
    gaps, removed = _gaps_payload(timestamps, values, result, ext_params)

    return jsonify({"summary": result.summary, "rows": records, "gaps": gaps,
                    "removed_rows": [_clean_record(r) for r in removed]})


@api_bp.post("/report")
def report():
    """Regenerates the analysis for the given parameters and returns a
    rendered chart (base64 PNG) plus a full Markdown findings/recommendations
    report — both derived generically from whatever data/params are given."""
    data = request.get_json(force=True)
    try:
        timestamps, values, ext_params, chg_params, weights, filename = _load_series_and_params(data)
        result = run_analysis(timestamps, values, ext_params, chg_params, weights, gap_times=_gap_times())
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


# === DATA LISTING EXTRAS (added by apply_data_listing.py) ===================
# Adds category columns from the file (e.g. Day/Night) to each analysis row.
import json as _dl_json
from flask import request as _dl_request
from app.services.data_loader import last_extras as _dl_last_extras, reset_extras as _dl_reset_extras


@api_bp.before_request
def _dl_reset_before_request():
    _dl_reset_extras()


@api_bp.after_request
def _dl_add_category_columns(response):
    try:
        if _dl_request.method != "POST" or not response.is_json:
            return response
        extras = _dl_last_extras()
        if not extras:
            return response
        data = response.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list) or not data["rows"]:
            return response
        rows = data["rows"]
        cols = {name: values for name, values in extras.items() if len(values) == len(rows)}
        if not cols:
            return response
        for i, row in enumerate(rows):
            if isinstance(row, dict):
                for name, values in cols.items():
                    row[name] = values[i]
        data["category_columns"] = list(cols)
        response.set_data(_dl_json.dumps(data))
    except Exception:
        pass  # never break the analysis because of the listing extras
    finally:
        _dl_reset_extras()
    return response


# === FULL RESET (Reset button) ===============================================
@api_bp.post("/reset")
def reset_session():
    """Forget this browser's work: delete its uploaded file (and nothing else).
    The page then reloads with every field back to its default."""
    data = request.get_json(silent=True) or {}
    removed = []
    path = _resolve_path(str(data.get("token") or ""))
    if path and path.is_file():
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return jsonify({"reset": True, "removed": removed})
