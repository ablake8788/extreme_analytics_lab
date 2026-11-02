"""
apply_web_deployment.py - prepares the project for web deployment (GoDaddy)
while keeping local use unchanged.

Run once from the project root (the folder containing run.py):

    python apply_web_deployment.py

What it does (files are backed up as <name>.bak first; safe to run again):
  app/__init__.py   adds 2 lines to create_app(): init_security(app)
  config.ini        adds  mode = local  to [app] (no secrets)
  .gitignore        ignores config.local.ini and extreme_server.zip
  config.local.ini  created from config.local.ini.example if missing,
                    with a random secret key (private, never committed)

Needs app/security.py, app/server_settings.py, passenger_wsgi.py and
config.local.ini.example from extreme_all_updates.zip.
"""
from __future__ import annotations

import re
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INIT = ROOT / "app" / "__init__.py"
CONFIG = ROOT / "config.ini"
LOCAL = ROOT / "config.local.ini"
EXAMPLE = ROOT / "config.local.ini.example"
GITIGNORE = ROOT / ".gitignore"
NEEDED = [ROOT / "app" / "security.py", ROOT / "app" / "server_settings.py", ROOT / "passenger_wsgi.py", EXAMPLE]


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")


def patch_init() -> bool:
    text = INIT.read_text(encoding="utf-8")
    if "init_security(" in text:
        print("app/__init__.py: already patched, skipping.")
        return True
    m = re.search(r"def create_app\([^)]*\)[^:]*:.*?\n([ \t]+)return app\b", text, re.S)
    if not m:
        print("ERROR: app/__init__.py - could not find 'return app' inside create_app().")
        print("       Paste app/__init__.py into the chat and I will patch it by hand.")
        return False
    indent = m.group(1)
    insert_at = m.end() - len("return app")
    lines = (f"from .security import init_security  # web login (server mode only)\n"
             f"{indent}init_security(app)\n{indent}")
    backup(INIT)
    INIT.write_text(text[:insert_at] + lines + text[insert_at:], encoding="utf-8")
    print("app/__init__.py: create_app() now calls init_security(app).")
    return True


def patch_config() -> None:
    comment = "; mode: local = no login (this PC and the .exe), server = login required (web)\n"
    if not CONFIG.exists():
        CONFIG.write_text("[app]\n" + comment + "mode = local\n", encoding="utf-8")
        print("config.ini: created with [app] mode = local.")
        return
    text = CONFIG.read_text(encoding="utf-8")
    sec = re.search(r"^\[app\][ \t]*\r?\n", text, re.M)
    if sec:
        nxt = re.search(r"^\[", text[sec.end():], re.M)
        body = text[sec.end(): sec.end() + (nxt.start() if nxt else len(text))]
        if re.search(r"^\s*mode\s*=", body, re.M):
            print("config.ini: [app] mode already set, leaving it.")
            return
        backup(CONFIG)
        text = text[: sec.end()] + comment + "mode = local\n" + text[sec.end():]
    else:
        backup(CONFIG)
        text = text.rstrip() + "\n\n[app]\n" + comment + "mode = local\n"
    CONFIG.write_text(text, encoding="utf-8")
    print("config.ini: added [app] mode = local.")


def patch_gitignore() -> None:
    wanted = ["config.local.ini", "extreme_server.zip"]
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    missing = [w for w in wanted if not re.search(rf"^{re.escape(w)}\s*$", text, re.M)]
    if not missing:
        print(".gitignore: already ignores config.local.ini and extreme_server.zip.")
        return
    text = text.rstrip() + "\n\n# Web deployment - private settings and upload zip\n" + "\n".join(missing) + "\n"
    GITIGNORE.write_text(text, encoding="utf-8")
    print(".gitignore: added " + ", ".join(missing) + ".")


def make_local_ini() -> None:
    if LOCAL.exists():
        print("config.local.ini: already exists, keeping your settings.")
        return
    text = EXAMPLE.read_text(encoding="utf-8").replace(
        "replace-with-a-long-random-string-at-least-16-characters", secrets.token_hex(32))
    LOCAL.write_text(text, encoding="utf-8")
    print("config.local.ini: created (mode = local, password = change-me). Private - not committed.")


def main() -> int:
    for p in NEEDED + [INIT]:
        if not p.exists():
            print(f"ERROR: {p.relative_to(ROOT)} not found.")
            print("       Run this from the extreme_analytics_lab folder after extracting extreme_all_updates.zip.")
            return 1
    if not patch_init():
        return 1
    patch_config()
    patch_gitignore()
    make_local_ini()
    print("\nDone. Local use is unchanged (mode = local).")
    print("To test the login locally: set mode = server in config.local.ini, then python run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
