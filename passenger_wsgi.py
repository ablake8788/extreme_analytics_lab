"""
passenger_wsgi.py - start file for GoDaddy (cPanel > Setup Python App).

  Application startup file:  passenger_wsgi.py
  Application entry point:   application

Runs in server mode (login required). The password and secret key come from
the environment variables set in cPanel, never from files in git.
Not used on your PC: there you keep using run.py, rebuild.ps1 or the .exe.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("APP_MODE", "server")

from app import create_app  # noqa: E402

application = create_app()
