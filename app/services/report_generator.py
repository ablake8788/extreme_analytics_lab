"""
report_generator.py

Turns a run_analysis() result into a downloadable chart (PNG) and a
written Markdown report (summary, findings, conclusions, recommendations).

Everything here is derived generically from the result table and summary
dict — nothing is hardcoded to any particular dataset. The same functions
work on any uploaded time series.
"""
from __future__ import annotations
import base64
import io
import math
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

STATE_COLORS = {
    "Extreme triggered": "#b5316b",
    "Extreme/elevated": "#b5316b",
    "Persistent": "#c9860a",
    "Confirmed/Materialized Shift": "#c0392b",
    "Persistence ends": "#7b8794",
}


# --------------------------------------------------------------------------
# Chart
# --------------------------------------------------------------------------

def render_chart_png(table: pd.DataFrame, value_label: str, ext_params) -> bytes:
    """Renders the value series with upper/lower bands and state-colored
    points, matching the style used in the manual analysis report. Returns
    raw PNG bytes."""
    t = table.copy()
    t["Timestamp"] = pd.to_datetime(t["Timestamp"], errors="coerce")
    is_datetime = t["Timestamp"].notna().any()
    x = t["Timestamp"] if is_datetime else range(len(t))

    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=150)
    fig.patch.set_facecolor("#FCFCFA")
    ax.set_facecolor("#FCFCFA")

    ax.plot(x, t["Value"], color="#2f6fed", linewidth=1.5, label=value_label, zorder=3)

    if "UpperLimit" in t.columns and t["UpperLimit"].notna().any():
        ax.plot(x, t["UpperLimit"], color="#c0392b", linewidth=1, linestyle="--", alpha=0.5, label="Upper/Lower limit")
        ax.plot(x, t["LowerLimit"], color="#c0392b", linewidth=1, linestyle="--", alpha=0.5)
        ax.fill_between(x, t["LowerLimit"], t["UpperLimit"], color="#c0392b", alpha=0.04)

    plotted = set()
    for state, color in STATE_COLORS.items():
        sub = t[t["State"] == state]
        if sub.empty:
            continue
        label = state if state not in plotted else None
        sx = sub["Timestamp"] if is_datetime else sub.index
        ax.scatter(sx, sub["Value"], color=color, s=28, zorder=4, label=label,
                   edgecolor="white", linewidth=0.5)
        plotted.add(state)

    if is_datetime:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        fig.autofmt_xdate(rotation=40)

    ax.set_ylabel(value_label, fontsize=11)
    ax.set_title(
        f"Extreme / Persistence Detection ({ext_params.baseline_method}, "
        f"W={ext_params.window}, K\u2091={ext_params.k_e}, K\u209a={ext_params.k_p}, N\u2098={ext_params.n_m})",
        fontsize=12, fontweight="bold", color="#16232e", pad=12,
    )
    ax.grid(True, color="#e5eaf0", linewidth=0.7)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    if plotted or "UpperLimit" in t.columns:
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.9, ncol=2)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def chart_png_base64(table: pd.DataFrame, value_label: str, ext_params) -> str:
    png_bytes = render_chart_png(table, value_label, ext_params)
    return base64.b64encode(png_bytes).decode("ascii")


# --------------------------------------------------------------------------
# Findings (generic, rule-based — derived from whatever the result contains)
# --------------------------------------------------------------------------

def _fmt_ts(ts) -> str:
    """Formats a timestamp for display, dropping the time component when
    it's midnight (i.e. the data is date-only granularity) so findings
    don't read '2026-07-13 00:00:00' for daily data."""
    if ts is None:
        return "?"
    s = str(ts)
    if s.endswith(" 00:00:00"):
        return s[: -len(" 00:00:00")]
    return s


def _longest_run(table: pd.DataFrame, state_set: set) -> tuple:
    """Returns (max_length, start_ts, end_ts) of the longest consecutive
    run where State is in state_set."""
    best_len, best_start, best_end = 0, None, None
    cur_len, cur_start = 0, None
    for _, row in table.iterrows():
        if row["State"] in state_set:
            if cur_len == 0:
                cur_start = row["Timestamp"]
            cur_len += 1
            cur_end = row["Timestamp"]
            if cur_len > best_len:
                best_len, best_start, best_end = cur_len, cur_start, cur_end
        else:
            cur_len = 0
    return best_len, best_start, best_end


def generate_findings(table: pd.DataFrame, summary: dict, ext_params, chg_params) -> list:
    findings = []
    n = summary["row_count"]

    # Extreme channel
    ext_pct = (summary["extreme_periods"] / n * 100) if n else 0
    max_z = summary.get("max_abs_zscore")
    if max_z is not None and not math.isnan(max_z):
        findings.append(
            f"{summary['extreme_periods']} of {n} periods ({ext_pct:.1f}%) were flagged Extreme "
            f"under the {summary['baseline_method']} method; peak |Z| observed was {max_z:.2f}."
        )
    else:
        findings.append(
            f"{summary['extreme_periods']} of {n} periods ({ext_pct:.1f}%) were flagged Extreme. "
            f"A peak Z-score could not be computed — the data may be constant or too short for "
            f"the chosen window (no variability within the baseline)."
        )

    # Persistence channel
    persistent_len, p_start, p_end = _longest_run(table, {"Persistent", "Confirmed/Materialized Shift"})
    if persistent_len > 0:
        findings.append(
            f"The longest sustained deviation lasted {persistent_len} consecutive periods "
            f"({_fmt_ts(p_start)} to {_fmt_ts(p_end)})."
        )

    if summary["confirmed_shift_periods"] > 0:
        findings.append(
            f"{summary['confirmed_shift_periods']} period(s) reached Confirmed/Materialized Shift "
            f"status — a sustained deviation of at least N_M={ext_params.n_m} periods with mean "
            f"|Z| \u2265 K_M={ext_params.k_m}."
        )
    elif summary["persistent_periods"] > 0:
        findings.append(
            f"No period reached Confirmed/Materialized Shift status, though "
            f"{summary['persistent_periods']} period(s) reached Persistent "
            f"(\u2265 N_P={ext_params.n_p} periods). The longest run "
            f"({persistent_len} periods) fell short of N_M={ext_params.n_m}."
        )
    else:
        findings.append(
            "No sustained deviations were detected — any Extreme periods present were isolated, "
            "single-period events."
        )

    # Change / ROC channel
    if summary["abnormal_change_periods"] > 0:
        findings.append(
            f"{summary['abnormal_change_periods']} abnormal rate-of-change period(s) detected; "
            f"{summary['material_change_periods']} of those recurred often enough within the "
            f"trailing {chg_params.frequency_window}-period window to be classified Material Change."
        )
    else:
        findings.append("No abnormal rate-of-change periods were detected.")

    # Materiality
    if summary["material_extreme_periods"] > 0:
        top_row = table.loc[table["MaterialityScore"].idxmax()] if "MaterialityScore" in table.columns and table["MaterialityScore"].notna().any() else None
        if top_row is not None:
            findings.append(
                f"{summary['material_extreme_periods']} period(s) were flagged Material Extreme "
                f"(magnitude and duration criteria both met); the highest MaterialityScore was "
                f"{top_row['MaterialityScore']:.2f} at {_fmt_ts(top_row['Timestamp'])}."
            )
    else:
        findings.append("No periods met both the magnitude and duration criteria for Material Extreme status.")

    return findings


# --------------------------------------------------------------------------
# Recommendations (generic, rule-based)
# --------------------------------------------------------------------------

def generate_recommendations(summary: dict, ext_params, chg_params) -> list:
    recs = []
    n = max(summary["row_count"], 1)
    ext_pct = summary["extreme_periods"] / n * 100

    if summary["confirmed_shift_periods"] == 0 and summary["persistent_periods"] > 0:
        recs.append(
            "No period reached Confirmed/Materialized Shift under the current settings, but "
            "sustained deviations were present. Consider widening `Window` and/or lowering `N_M` "
            "or `K_M`, then re-run to see whether the persistence resolves before or after "
            "confirmation — a wider window will make the baseline lag longer, keeping Z elevated "
            "further into any sustained event."
        )

    if ext_pct > 15:
        recs.append(
            f"{ext_pct:.1f}% of periods were flagged Extreme, which is a high proportion. "
            f"Consider raising `K_E` or widening `Window` — the current thresholds may be "
            f"flagging normal variability rather than genuine anomalies."
        )
    elif ext_pct == 0:
        recs.append(
            "No periods were flagged Extreme at all. If deviations were expected in this data, "
            "consider lowering `K_E` or narrowing `Window` so the baseline responds faster to "
            "local changes."
        )

    if summary["abnormal_change_periods"] > 0 and summary["material_change_periods"] == 0:
        recs.append(
            "Abnormal rate-of-change periods were detected but none recurred often enough to be "
            "classified Material Change. If isolated large jumps should still be actionable, "
            "consider lowering `frequency_min_count`."
        )

    recs.append(
        "Run this same dataset at two or more `Window` settings before trusting a single "
        "configuration's Confirmed/Materialized Shift count — this framework is sensitive to "
        "window width by design, and a single run can under- or over-report materiality."
    )
    recs.append(
        "Treat an unexpected Confirmed/Materialized Shift as a prompt to inspect the underlying "
        "data rather than assuming the flag is a false positive — a wider window can surface real, "
        "if unplanned, sustained structure in the data."
    )

    return recs


# --------------------------------------------------------------------------
# Full report assembly
# --------------------------------------------------------------------------

def generate_markdown_report(table: pd.DataFrame, summary: dict, ext_params, chg_params,
                              value_column: str, source_filename: str = "") -> str:
    findings = generate_findings(table, summary, ext_params, chg_params)
    recommendations = generate_recommendations(summary, ext_params, chg_params)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# Results Analysis: {value_column}")
    if source_filename:
        lines.append(f"### Source: `{source_filename}`")
    lines.append(f"*Generated {generated_at} by Extreme & Change Analytics Lab*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. Configuration")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|---|---|")
    lines.append(f"| Baseline method | {ext_params.baseline_method} |")
    lines.append(f"| Window (W) | {ext_params.window} |")
    lines.append(f"| K_E / K_P | {ext_params.k_e} / {ext_params.k_p} |")
    lines.append(f"| N_P / N_M | {ext_params.n_p} / {ext_params.n_m} |")
    lines.append(f"| K_M | {ext_params.k_m} |")
    lines.append(f"| ROC window / baseline window | {chg_params.roc_window} / {chg_params.roc_baseline_window} |")
    lines.append(f"| ROC_K | {chg_params.roc_k} |")
    lines.append("")
    lines.append("![Time series with detection overlay](chart.png)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. Summary Statistics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    for k, v in summary.items():
        label = k.replace("_", " ").title()
        lines.append(f"| {label} | {v} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. Findings")
    lines.append("")
    for f in findings:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. Recommendations")
    lines.append("")
    for r in recommendations:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*This report was generated automatically from the same analysis engine "
        "(`app/services/extreme_change_engine.py`) used elsewhere in this application.*"
    )

    return "\n".join(lines)
