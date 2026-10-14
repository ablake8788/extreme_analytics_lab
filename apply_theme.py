"""
apply_theme.py - turns on the Titanium Analytics design.

Run once from the project root (the folder containing run.py):

    python apply_theme.py

Adds to app/templates/index.html (backed up as index.html.bak first):
  - css/theme.css right after the app.css stylesheet link
  - js/theme.js right after the app.js script tag
Safe to run more than once. To switch the design off, delete those two lines.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "app" / "templates" / "index.html"
CSS = ROOT / "app" / "static" / "css" / "theme.css"
JS = ROOT / "app" / "static" / "js" / "theme.js"
CSS_TAG = re.compile(r'<link[^>]*\bapp\.css[^>]*>', re.IGNORECASE)
APP_TAG = re.compile(r'<script[^>]*\bapp\.js[^>]*>\s*</script>', re.IGNORECASE)


def main() -> int:
    for p in (INDEX, CSS, JS):
        if not p.exists():
            print(f"ERROR: {p.relative_to(ROOT)} not found. Extract extreme_all_updates.zip into this folder first.")
            return 1
    html = INDEX.read_text(encoding="utf-8")
    changed = False

    if "theme.css" in html:
        print("index.html: theme.css already linked.")
    else:
        m = CSS_TAG.search(html)
        if m:
            tag = m.group(0).replace("app.css", "theme.css")
            html = html[: m.end()] + "\n" + tag + html[m.end():]
        elif "</head>" in html.lower():
            i = html.lower().find("</head>")
            html = html[:i] + "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='css/theme.css') }}\">\n" + html[i:]
        else:
            print("ERROR: could not find where to add theme.css in index.html.")
            return 1
        changed = True
        print("index.html: linked css/theme.css.")

    if "theme.js" in html:
        print("index.html: theme.js already loaded.")
    else:
        m = APP_TAG.search(html)
        if m:
            tag = m.group(0).replace("app.js", "theme.js")
            html = html[: m.end()] + "\n  " + tag + html[m.end():]
        elif "</body>" in html.lower():
            i = html.lower().rfind("</body>")
            html = html[:i] + "  <script src=\"{{ url_for('static', filename='js/theme.js') }}\"></script>\n" + html[i:]
        else:
            print("ERROR: could not find where to add theme.js in index.html.")
            return 1
        changed = True
        print("index.html: added js/theme.js.")

    if changed:
        bak = INDEX.with_suffix(".html.bak")
        if not bak.exists():
            shutil.copy2(INDEX, bak)
            print(f"  backup: {bak.relative_to(ROOT)}")
        INDEX.write_text(html, encoding="utf-8")
    print("\nDone. Run .\\rebuild.ps1 or .\\build.ps1, then press Ctrl+F5 in the browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
