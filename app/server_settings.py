"""
server_settings.py - local vs server (web) mode settings.

Settings are read in this order; later sources win:
  1. config.ini          shared defaults, committed to git, packed into the .exe
  2. config.local.ini    private overrides on this PC only (never committed)
  3. environment variables  used on GoDaddy (cPanel > Setup Python App)

  Setting            config.ini / config.local.ini     Environment variable
  -----------------  --------------------------------  --------------------
  mode               [app]    mode = local | server     APP_MODE
  password           [server] password = ...            APP_PASSWORD
  password hash      [server] password_hash = ...       APP_PASSWORD_HASH
  secret key         [server] secret_key = ...          APP_SECRET_KEY
  domain             [server] domain = ...              APP_DOMAIN
  secure cookies     [server] secure_cookies = true     APP_SECURE_COOKIES
  upload max age     [server] upload_max_age_hours=24   APP_UPLOAD_MAX_AGE_HOURS
  session length     [server] session_hours = 12        APP_SESSION_HOURS

Never put the password or secret key in config.ini.
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ServerConfigError(RuntimeError):
    """Raised when server mode is switched on without a password/secret key."""


def is_frozen() -> bool:
    """True when running as the packaged .exe."""
    return bool(getattr(sys, "frozen", False))


def ini_paths() -> tuple[Path, Path | None]:
    shared = Path(os.environ.get("APP_CONFIG") or ROOT / "config.ini")
    local_env = os.environ.get("APP_CONFIG_LOCAL")
    if local_env:
        local = Path(local_env)
    elif "PYTEST_CURRENT_TEST" in os.environ:
        local = None  # tests never pick up the private file on this PC
    elif is_frozen():
        # The .exe looks for config.local.ini next to itself, then in the
        # folder it was started from (launch.ps1 starts it from the project).
        local = None
        for candidate in (Path(sys.executable).resolve().parent / "config.local.ini",
                          Path.cwd() / "config.local.ini"):
            if candidate.exists():
                local = candidate
                break
    else:
        local = ROOT / "config.local.ini"
    return shared, local


def _read_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    shared, local = ini_paths()
    files = [str(p) for p in (shared, local) if p is not None and p.exists()]
    parser.read(files, encoding="utf-8")
    return parser


def _truthy(value, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ServerSettings:
    mode: str = "local"
    password: str = ""
    password_hash: str = ""
    secret_key: str = ""
    domain: str = ""
    secure_cookies: bool = False
    upload_max_age_hours: float = 24.0
    session_hours: float = 12.0
    max_login_attempts: int = 5
    lockout_minutes: int = 5

    @property
    def is_server(self) -> bool:
        return self.mode == "server"

    def validate(self) -> None:
        if not self.is_server:
            return
        problems = []
        if not (self.password or self.password_hash):
            problems.append("a password (APP_PASSWORD, or [server] password in config.local.ini)")
        if len(self.secret_key) < 16:
            problems.append("a secret key of at least 16 characters "
                            "(APP_SECRET_KEY, or [server] secret_key in config.local.ini)")
        if problems:
            raise ServerConfigError(
                "Server mode is on but the app is missing " + " and ".join(problems) + ". "
                "The app will not start without them, so it is never online unprotected. "
                "On GoDaddy set them in cPanel > Setup Python App > Environment variables. "
                "On this PC put them in config.local.ini, or set [app] mode = local."
            )


def get_setting(env: str | None, section: str, key: str, default=None, ini=None):
    """One setting: environment variable > config.local.ini > config.ini > default."""
    if env:
        value = os.environ.get(env)
        if value is not None and value.strip() != "":
            return value.strip()
    ini = ini if ini is not None else _read_ini()
    if ini.has_option(section, key):
        value = ini.get(section, key).strip()
        if value != "":
            return value
    return default


def load_settings() -> ServerSettings:
    ini = _read_ini()

    def get(env: str, section: str, key: str, default=None):
        return get_setting(env, section, key, default, ini)

    mode = str(get("APP_MODE", "app", "mode", "local")).lower()
    if is_frozen() and not os.environ.get("APP_MODE"):
        mode = "local"  # the .exe never asks for a login
    if mode not in ("local", "server"):
        raise ServerConfigError(f"Unknown mode '{mode}'. Use 'local' or 'server'.")
    domain = get("APP_DOMAIN", "server", "domain", "")
    return ServerSettings(
        mode=mode,
        password=get("APP_PASSWORD", "server", "password", ""),
        password_hash=get("APP_PASSWORD_HASH", "server", "password_hash", ""),
        secret_key=get("APP_SECRET_KEY", "server", "secret_key", ""),
        domain=domain,
        # Secure cookies need HTTPS: on by default once a domain is set,
        # off for plain http://127.0.0.1 testing.
        secure_cookies=_truthy(get("APP_SECURE_COOKIES", "server", "secure_cookies"), bool(domain)),
        upload_max_age_hours=float(get("APP_UPLOAD_MAX_AGE_HOURS", "server", "upload_max_age_hours", 24)),
        session_hours=float(get("APP_SESSION_HOURS", "server", "session_hours", 12)),
    )
