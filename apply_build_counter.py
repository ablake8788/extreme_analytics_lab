"""
apply_build_counter.py - turns on the build number badge.

Run once from the project root (the folder containing run.py):

    python apply_build_counter.py

It adds a <script> line for js/build_badge.js to app/templates/index.html
(after the app.js script tag) and creates app/static/build_info.json with
build 0 if it does not exist yet. build.ps1 raises the number on every
successful build. index.html is backed up as index.html.bak first.
Safe to run more than once.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "app" / "templates" / "index.html"
BADGE = ROOT / "app" / "static" / "js" / "build_badge.js"
INFO = ROOT / "app" / "static" / "build_info.json"
APP_TAG = re.compile(r'<script[^>]*\bapp\.js[^>]*>\s*</script>', re.IGNORECASE)


def main() -> int:
    if not BADGE.exists():
        print("ERROR: app/static/js/build_badge.js not found. Extract extreme_build_counter_update.zip first.")
        return 1
    if not INDEX.exists():
        print("ERROR: app/templates/index.html not found. Run this from the extreme_analytics_lab folder.")
        return 1

    if not INFO.exists():
        INFO.write_text(json.dumps({"build": 0, "version": "1.0.0", "built_at": "", "branch": "", "commit": ""},
                                   indent=4), encoding="utf-8")
        print("build_info.json: created (build 0). The next .\\build.ps1 makes build 1.")
    else:
        print("build_info.json: already exists, keeping current build number.")

    html = INDEX.read_text(encoding="utf-8")
    if "build_badge.js" in html:
        print("index.html: build badge already enabled.")
        return 0

    match = APP_TAG.search(html)
    if match:
        tag = match.group(0).replace("app.js", "build_badge.js")
        html = html[: match.end()] + "\n  " + tag + html[match.end():]
    elif "</body>" in html.lower():
        idx = html.lower().rfind("</body>")
        tag = "<script src=\"{{ url_for('static', filename='js/build_badge.js') }}\"></script>"
        html = html[:idx] + "  " + tag + "\n" + html[idx:]
    else:
        print("ERROR: could not find where to add the script in index.html. Paste index.html into the chat.")
        return 1

    bak = INDEX.with_suffix(".html.bak")
    if not bak.exists():
        shutil.copy2(INDEX, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")
    INDEX.write_text(html, encoding="utf-8")
    print("index.html: added build_badge.js.")
    print("\nDone. Run .\\build.ps1 - it will be build 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
