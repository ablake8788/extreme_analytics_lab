"""
apply_data_listing.py - turns on the Day/Night data listing.

Run once from the project root (the folder containing run.py):

    python apply_data_listing.py

Changes (each file backed up as <name>.bak first; safe to run again):
  app/routes/api.py          - adds category columns such as Day/Night to
                               every /api/analyze result row
  app/templates/index.html   - loads js/data_listing.js after app.js

Needs the updated app/services/data_loader.py (with last_extras) and
app/static/js/data_listing.js from extreme_all_updates.zip.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "app" / "routes" / "api.py"
INDEX = ROOT / "app" / "templates" / "index.html"
LOADER = ROOT / "app" / "services" / "data_loader.py"
JS_FILE = ROOT / "app" / "static" / "js" / "data_listing.js"
MARKER = "DATA LISTING EXTRAS"
APP_TAG = re.compile(r'<script[^>]*\bapp\.js[^>]*>\s*</script>', re.IGNORECASE)

API_HOOKS = '''

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
'''


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")


def main() -> int:
    for p in (API, INDEX, LOADER, JS_FILE):
        if not p.exists():
            print(f"ERROR: {p.relative_to(ROOT)} not found.")
            print("       Run this from the extreme_analytics_lab folder after extracting extreme_all_updates.zip.")
            return 1
    if "def last_extras(" not in LOADER.read_text(encoding="utf-8"):
        print("ERROR: app/services/data_loader.py is an older version (no last_extras).")
        print("       Extract the latest extreme_all_updates.zip first.")
        return 1

    ok = True
    api = API.read_text(encoding="utf-8")
    if MARKER in api:
        print("api.py: already patched, skipping.")
    elif "api_bp" not in api:
        print("ERROR: api.py has no api_bp blueprint - paste app/routes/api.py into the chat.")
        ok = False
    else:
        backup(API)
        API.write_text(api.rstrip() + "\n" + API_HOOKS, encoding="utf-8")
        print("api.py: rows now include category columns such as Day/Night.")

    html = INDEX.read_text(encoding="utf-8")
    if "data_listing.js" in html:
        print("index.html: data listing already enabled.")
    else:
        m = APP_TAG.search(html)
        if m:
            tag = m.group(0).replace("app.js", "data_listing.js")
            html = html[: m.end()] + "\n  " + tag + html[m.end():]
        elif "</body>" in html.lower():
            i = html.lower().rfind("</body>")
            html = html[:i] + "  <script src=\"{{ url_for('static', filename='js/data_listing.js') }}\"></script>\n" + html[i:]
        else:
            print("ERROR: could not find where to add the script in index.html.")
            ok = False
            html = None
        if html is not None:
            backup(INDEX)
            INDEX.write_text(html, encoding="utf-8")
            print("index.html: added data_listing.js.")

    if ok:
        print("\nDone. Run .\\rebuild.ps1 to test, then .\\build.ps1.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
