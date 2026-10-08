"""
ai_report.py - API for AI results reports.

  GET  /api/ai-report/status   what is configured (never returns the API key)
  POST /api/ai-report          multipart: file=<results CSV>, location, units
                               -> the Word report (.docx)

In local mode a copy is also saved to [reports] output_folder (if set).
Response headers tell the page what happened:
  X-Report-Filename, X-Report-Saved-To, X-AI-Source, X-AI-Note
"""
from __future__ import annotations

import io
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from flask import Blueprint, current_app, jsonify, request, send_file

from app.ai_settings import load_ai_settings
from app.services.report_ai import write_report_text
from app.services.report_docx import build_report
from app.services.results_facts import FactsError, compute_facts, prepare

ai_report_bp = Blueprint("ai_report", __name__, url_prefix="/api/ai-report")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
KEEP_HOURS = 24  # generated reports are kept this long for Open / Save as
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _report_dir() -> Path:
    from app.config import Config
    d = Path(Config.UPLOAD_DIR) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for f in d.glob("*.docx"):  # tidy up old ones
        try:
            if now - f.stat().st_mtime > KEEP_HOURS * 3600:
                f.unlink()
        except OSError:
            pass
    return d


def _report_path(token: str):
    if not _TOKEN.match(token or ""):
        return None
    hits = list(_report_dir().glob(token + "__*.docx"))
    return hits[0] if hits else None


def _mode() -> str:
    return current_app.config.get("APP_MODE", "local")


def read_reference_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    try:
        if path.suffix.lower() == ".docx":
            from docx import Document
            doc = Document(str(path))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for t in doc.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts)
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def report_filename(location: str, facts: dict) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", location or "Sensor").strip("_")[:60] or "Sensor"
    a = facts["period_start"][:10].replace("-", "")
    b = facts["period_end"][:10].replace("-", "")
    return f"{base}_Results_Analysis_{a}-{b}.docx"


@ai_report_bp.get("/status")
def status():
    s = load_ai_settings()
    st = s.public_status(_mode())
    st["mode"] = _mode()
    st["can_open"] = _mode() == "local" and hasattr(os, "startfile")
    return jsonify(st)


@ai_report_bp.post("")
def make_report():
    up = request.files.get("file")
    if not up or not up.filename:
        return jsonify({"error": "No results CSV was sent."}), 400
    location = (request.form.get("location") or "").strip()[:120] or "Sensor"
    units = (request.form.get("units") or "").strip()[:12]
    try:
        raw = pd.read_csv(io.BytesIO(up.read()), encoding="utf-8-sig", low_memory=False)
        facts = compute_facts(raw, location=location, units=units, source_name=Path(up.filename).name)
        prepared = prepare(raw)
    except FactsError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Could not read the results CSV: {exc.__class__.__name__}"}), 400

    s = load_ai_settings()
    ref_text = read_reference_text(s.reference_document)
    ref_name = s.reference_document.name if (s.reference_document and s.reference_document.exists()) else None
    text = write_report_text(facts, ref_text, s.api_key, s.model, s.timeout_seconds)
    data = build_report(prepared, facts, text, ref_name)
    name = report_filename(location, facts)

    saved = ""
    if _mode() == "local" and s.output_folder:
        try:
            s.output_folder.mkdir(parents=True, exist_ok=True)
            target = s.output_folder / name
            target.write_bytes(data)
            saved = str(target)
        except OSError as exc:
            saved = f"(not saved: {exc.strerror or exc})"

    token = secrets.token_hex(16)
    (_report_dir() / f"{token}__{name}").write_bytes(data)
    note = text.note or (f"{len(text.removed_sentences)} unverified sentence(s) removed" if text.removed_sentences else "")
    return jsonify({"token": token, "filename": name, "size": len(data), "saved_to": saved,
                    "source": text.source, "note": note,
                    "can_open": _mode() == "local" and hasattr(os, "startfile")})


@ai_report_bp.get("/file/<token>")
def report_file(token):
    path = _report_path(token)
    if not path:
        return jsonify({"error": "This report is no longer available. Generate it again."}), 404
    name = path.name.split("__", 1)[1]
    return send_file(str(path), mimetype=DOCX_MIME, as_attachment=True, download_name=name)


@ai_report_bp.post("/open/<token>")
def report_open(token):
    """Open the report in Word on this computer (PC / .exe only)."""
    if _mode() != "local" or not hasattr(os, "startfile"):
        return jsonify({"error": "Open in Word works in the PC version. Use Save as... here."}), 400
    path = _report_path(token)
    if not path:
        return jsonify({"error": "This report is no longer available. Generate it again."}), 404
    try:
        os.startfile(str(path))  # noqa: S606 - opens the default app (Word)
    except OSError as exc:
        return jsonify({"error": f"Could not open Word: {exc.strerror or exc}"}), 500
    return jsonify({"opened": True})
