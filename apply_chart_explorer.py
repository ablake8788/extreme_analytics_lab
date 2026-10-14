"""
apply_chart_explorer.py - turns on the scrollable / paginated / stretchable
chart in the Extreme & Change Analytics Lab.

Run once from the project root (the folder containing run.py):

    python apply_chart_explorer.py

It adds one <script> line for js/chart_explorer.js to
app/templates/index.html, right after the app.js script tag.
index.html is backed up as index.html.bak first. Safe to run more than once.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "app" / "templates" / "index.html"
JS_FILE = ROOT / "app" / "static" / "js" / "chart_explorer.js"

APP_TAG = re.compile(r'<script[^>]*\bapp\.js[^>]*>\s*</script>', re.IGNORECASE)


def main() -> int:
    if not JS_FILE.exists():
        print("ERROR: app/static/js/chart_explorer.js not found.")
        print("       Extract extreme_chart_explorer_update.zip into this folder first.")
        return 1
    if not INDEX.exists():
        print("ERROR: app/templates/index.html not found. Run this from the extreme_analytics_lab folder.")
        return 1

    html = INDEX.read_text(encoding="utf-8")
    if "chart_explorer.js" in html:
        print("index.html: chart explorer already enabled, nothing to do.")
        return 0

    match = APP_TAG.search(html)
    if match:
        app_tag = match.group(0)
        new_tag = app_tag.replace("app.js", "chart_explorer.js")
        html = html[: match.end()] + "\n  " + new_tag + html[match.end():]
        where = "after the app.js script tag"
    elif "</body>" in html.lower():
        idx = html.lower().rfind("</body>")
        tag = "<script src=\"{{ url_for('static', filename='js/chart_explorer.js') }}\"></script>"
        html = html[:idx] + "  " + tag + "\n" + html[idx:]
        where = "before </body>"
    else:
        print("ERROR: could not find where to add the script in index.html.")
        print("       Paste app/templates/index.html into the chat and I will add it by hand.")
        return 1

    bak = INDEX.with_suffix(".html.bak")
    if not bak.exists():
        shutil.copy2(INDEX, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")
    INDEX.write_text(html, encoding="utf-8")
    print(f"index.html: added chart_explorer.js {where}.")
    print("\nDone. Run .\\rebuild.ps1 to test, then .\\build.ps1 for a new .exe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
