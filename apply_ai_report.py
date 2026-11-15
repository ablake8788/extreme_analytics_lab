"""
apply_ai_report.py - adds the AI report feature (OpenAI + Word report).

Run once from the project root (the folder containing run.py):

    python apply_ai_report.py

What it does (files backed up as <name>.bak first; safe to run again):
  app/__init__.py          registers the /api/ai-report endpoints
  app/templates/index.html loads js/ai_report.js
  config.ini               adds [openai] model/timeout and [reports] defaults
                           (NO API key - that belongs in config.local.ini)
  config.local.ini         adds commented [openai] api_key and [reports]
                           path lines for you to fill in (never committed)
  config.local.ini.example same, for reference
  requirements.txt         adds python-docx, requests, matplotlib if missing
  .gitignore               ignores the results/ folder (reports hold data)
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INIT = ROOT / "app" / "__init__.py"
INDEX = ROOT / "app" / "templates" / "index.html"
CONFIG = ROOT / "config.ini"
LOCAL = ROOT / "config.local.ini"
EXAMPLE = ROOT / "config.local.ini.example"
REQ = ROOT / "requirements.txt"
GITIGNORE = ROOT / ".gitignore"
NEEDED = ["app/ai_settings.py", "app/routes/ai_report.py", "app/services/results_facts.py",
          "app/services/report_ai.py", "app/services/report_docx.py", "app/static/js/ai_report.js",
          "app/server_settings.py"]
APP_TAG = re.compile(r'<script[^>]*\bapp\.js[^>]*>\s*</script>', re.IGNORECASE)

SHARED_SECTIONS = """
[openai]
; model used for AI report wording. The API key is NOT set here - put it in
; config.local.ini ([openai] api_key) or the OPENAI_API_KEY environment variable.
model = gpt-4o-mini
timeout_seconds = 90

[reports]
; reference document the AI follows (Titanium method and report format)
reference_document = info_main/reference/Titanium_analytics.docx
; folder where a copy of each Word report is saved (local mode only)
output_folder = results
"""

LOCAL_SECTIONS = """
[openai]
; your OpenAI API key - private, never committed
; api_key = sk-...

[reports]
; optional: your own locations (override config.ini), for example
; reference_document = C:\\path\\to\\Titanium_analytics.docx
; output_folder = C:\\path\\to\\results
"""


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")


def has_section(text: str, name: str) -> bool:
    return re.search(rf"^\[{re.escape(name)}\]\s*$", text, re.M) is not None


def patch_init() -> bool:
    text = INIT.read_text(encoding="utf-8")
    if "ai_report_bp" in text:
        print("app/__init__.py: AI report already registered.")
        return True
    m = re.search(r"def create_app\([^)]*\)[^:]*:.*?\n([ \t]+)(?:from \.security import init_security.*?\n[ \t]+)?return app\b", text, re.S)
    if not m:
        print("ERROR: could not find 'return app' in create_app() - paste app/__init__.py into the chat.")
        return False
    indent = m.group(1)
    # insert right before the security lines (or before return app)
    sec = text.find("from .security import init_security", m.start(), m.end())
    insert_at = sec if sec != -1 else m.end() - len("return app")
    lines = (f"from .routes.ai_report import ai_report_bp  # AI results reports\n"
             f"{indent}app.register_blueprint(ai_report_bp)\n{indent}")
    backup(INIT)
    INIT.write_text(text[:insert_at] + lines + text[insert_at:], encoding="utf-8")
    print("app/__init__.py: registered /api/ai-report.")
    return True


def patch_index() -> bool:
    html = INDEX.read_text(encoding="utf-8")
    if "ai_report.js" in html:
        print("index.html: ai_report.js already loaded.")
        return True
    m = APP_TAG.search(html)
    if m:
        html = html[: m.end()] + "\n  " + m.group(0).replace("app.js", "ai_report.js") + html[m.end():]
    elif "</body>" in html.lower():
        i = html.lower().rfind("</body>")
        html = html[:i] + "  <script src=\"{{ url_for('static', filename='js/ai_report.js') }}\"></script>\n" + html[i:]
    else:
        print("ERROR: could not find where to add ai_report.js in index.html.")
        return False
    backup(INDEX)
    INDEX.write_text(html, encoding="utf-8")
    print("index.html: added js/ai_report.js.")
    return True


def patch_config() -> None:
    text = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    if re.search(r"^\s*api_key\s*=", text, re.M):
        print("WARNING: config.ini contains an api_key line - move it to config.local.ini!")
    add = ""
    if not has_section(text, "openai"):
        add += SHARED_SECTIONS.split("[reports]")[0]
    if not has_section(text, "reports"):
        add += "[reports]" + SHARED_SECTIONS.split("[reports]")[1]
    if not add:
        print("config.ini: [openai] and [reports] already present.")
        return
    backup(CONFIG)
    CONFIG.write_text(text.rstrip() + "\n" + add, encoding="utf-8")
    print("config.ini: added [openai] model/timeout and [reports] defaults (no key).")


def patch_local(path: Path, label: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    add = ""
    if not has_section(text, "openai"):
        add += LOCAL_SECTIONS.split("[reports]")[0]
    if not has_section(text, "reports"):
        add += "[reports]" + LOCAL_SECTIONS.split("[reports]")[1]
    if not add:
        print(f"{label}: [openai] and [reports] already present, leaving your values.")
        return
    path.write_text(text.rstrip() + "\n" + add, encoding="utf-8")
    print(f"{label}: added [openai] api_key and [reports] lines (commented - fill them in).")


def patch_requirements() -> None:
    text = REQ.read_text(encoding="utf-8") if REQ.exists() else ""
    names = {re.split(r"[<>=!~\[; ]", line.strip(), 1)[0].lower()
             for line in text.splitlines() if line.strip() and not line.strip().startswith("#")}
    want = [("python-docx", "python-docx>=1.1"), ("requests", "requests>=2.31,<3.0"), ("matplotlib", "matplotlib>=3.7")]
    missing = [spec for name, spec in want if name not in names]
    if not missing:
        print("requirements.txt: python-docx, requests, matplotlib already listed.")
        return
    backup(REQ)
    REQ.write_text(text.rstrip() + "\n" + "\n".join(missing) + "\n", encoding="utf-8")
    print("requirements.txt: added " + ", ".join(missing) + ".")


def patch_gitignore() -> None:
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if re.search(r"^/?results/?\s*$", text, re.M):
        print(".gitignore: results/ already ignored.")
        return
    GITIGNORE.write_text(text.rstrip() + "\n\n# AI reports contain sensor data\nresults/\n", encoding="utf-8")
    print(".gitignore: added results/.")


def main() -> int:
    missing = [n for n in NEEDED if not (ROOT / n).exists()]
    if missing or not INIT.exists() or not INDEX.exists():
        print("ERROR: missing " + ", ".join(missing or ["app/__init__.py or index.html"]))
        print("       Extract the latest extreme_all_updates.zip into this folder first.")
        return 1
    if not (patch_init() and patch_index()):
        return 1
    patch_config()
    patch_local(LOCAL, "config.local.ini")
    patch_local(EXAMPLE, "config.local.ini.example")
    patch_requirements()
    patch_gitignore()
    print("\nDone. Next:")
    print("  1. notepad config.local.ini  -> under [openai] set  api_key = sk-...  (remove the ;)")
    print("  2. optional: set your reference_document and output_folder paths under [reports]")
    print("  3. .\\rebuild.ps1  (installs python-docx) then run an analysis and use the AI report panel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
