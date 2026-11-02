"""
ai_settings.py - settings for AI reports, read with the same order as the
rest of the app (later wins):

  config.ini  ->  config.local.ini  ->  environment variables

  Setting              ini section/key                 Environment variable
  -------------------  ------------------------------  ----------------------
  OpenAI API key       [openai] api_key  (LOCAL ONLY)   OPENAI_API_KEY
  OpenAI model         [openai] model                   OPENAI_MODEL
  Request timeout (s)  [openai] timeout_seconds         OPENAI_TIMEOUT
  Reference document   [reports] reference_document     APP_REFERENCE_DOCUMENT
  Reports folder       [reports] output_folder          APP_REPORTS_FOLDER

Relative paths are taken from the project folder (or, for the .exe, the
folder it was started from). The API key is never returned to the browser.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .server_settings import ROOT, _read_ini, get_setting, is_frozen

DEFAULT_MODEL = "gpt-4o-mini"


def _base_dir() -> Path:
    return Path.cwd() if is_frozen() else ROOT


def _resolve(path_text: str | None) -> Path | None:
    if not path_text:
        return None
    p = Path(path_text).expanduser()
    if p.is_absolute():
        return p
    found = _base_dir() / p
    if is_frozen() and not found.exists() and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / p          # e.g. the reference document packed into the .exe
        if bundled.exists():
            return bundled
    return found


@dataclass
class AISettings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 90.0
    reference_document: Path | None = None
    output_folder: Path | None = None

    @property
    def ai_configured(self) -> bool:
        return bool(self.api_key)

    def public_status(self, mode: str) -> dict:
        ref = self.reference_document
        out = self.output_folder
        return {
            "ai_configured": self.ai_configured,
            "model": self.model,
            "reference_document": ref.name if ref else None,
            "reference_found": bool(ref and ref.exists()),
            "output_folder": str(out) if (out and mode == "local") else None,
            "saves_copy": bool(out and mode == "local"),
        }


def load_ai_settings() -> AISettings:
    ini = _read_ini()

    def get(env, section, key, default=None):
        return get_setting(env, section, key, default, ini)

    try:
        timeout = float(get("OPENAI_TIMEOUT", "openai", "timeout_seconds", 90))
    except ValueError:
        timeout = 90.0
    return AISettings(
        api_key=get("OPENAI_API_KEY", "openai", "api_key", "") or "",
        model=get("OPENAI_MODEL", "openai", "model", DEFAULT_MODEL) or DEFAULT_MODEL,
        timeout_seconds=timeout,
        reference_document=_resolve(get("APP_REFERENCE_DOCUMENT", "reports", "reference_document")),
        output_folder=_resolve(get("APP_REPORTS_FOLDER", "reports", "output_folder")),
    )
