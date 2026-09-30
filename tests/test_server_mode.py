"""Tests for local vs server (web) mode, the login, and passenger_wsgi."""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import create_app
from app.server_settings import ServerConfigError, load_settings

KEYS = ["APP_MODE", "APP_PASSWORD", "APP_PASSWORD_HASH", "APP_SECRET_KEY", "APP_DOMAIN",
        "APP_SECURE_COOKIES", "APP_CONFIG_LOCAL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    # never read the private config.local.ini on this PC
    monkeypatch.setenv("APP_CONFIG_LOCAL", str(tmp_path / "none.ini"))
    import app.security as sec
    sec._failures.clear()
    yield


def server_client(monkeypatch, password="s3cret-pass"):
    monkeypatch.setenv("APP_MODE", "server")
    monkeypatch.setenv("APP_PASSWORD", password)
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 32)
    return create_app().test_client()


def login(client, password):
    client.get("/login")
    with client.session_transaction() as s:
        token = s["tal_csrf"]
    return client.post("/login", data={"password": password, "csrf": token, "next": "/"})


def test_local_mode_has_no_login():
    app = create_app()
    assert app.config["APP_MODE"] == "local"
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/login").status_code == 404


def test_server_mode_requires_login(monkeypatch):
    c = server_client(monkeypatch)
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = c.post("/api/analyze", json={})
    assert r.status_code == 401 and "log in" in r.get_json()["error"]
    assert c.get("/healthz").data == b"ok"


def test_wrong_then_right_password(monkeypatch):
    c = server_client(monkeypatch)
    r = login(c, "wrong")
    assert r.status_code == 401 and b"not correct" in r.data
    r = login(c, "s3cret-pass")
    assert r.status_code == 302
    page = c.get("/")
    assert page.status_code == 200 and b"tal-logout" in page.data
    assert c.post("/logout").status_code == 302
    assert c.get("/").status_code == 302


def test_lockout_after_repeated_failures(monkeypatch):
    c = server_client(monkeypatch)
    for _ in range(5):
        login(c, "nope")
    r = login(c, "s3cret-pass")
    assert b"Too many attempts" in r.data


def test_missing_password_refuses_to_start(monkeypatch):
    monkeypatch.setenv("APP_MODE", "server")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 32)
    with pytest.raises(ServerConfigError, match="password"):
        create_app()


def test_ini_settings_and_env_override(monkeypatch, tmp_path):
    ini = tmp_path / "local.ini"
    ini.write_text("[app]\nmode = server\n[server]\npassword = from-ini\nsecret_key = " + "y" * 20 + "\n")
    monkeypatch.setenv("APP_CONFIG_LOCAL", str(ini))
    s = load_settings()
    assert s.mode == "server" and s.password == "from-ini" and not s.secure_cookies
    monkeypatch.setenv("APP_PASSWORD", "from-env")
    monkeypatch.setenv("APP_DOMAIN", "analytics.example.com")
    s = load_settings()
    assert s.password == "from-env" and s.secure_cookies


def test_passenger_wsgi_starts_in_server_mode(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "p")
    monkeypatch.setenv("APP_SECRET_KEY", "z" * 32)
    sys.modules.pop("passenger_wsgi", None)
    mod = importlib.import_module("passenger_wsgi")
    assert mod.application.config["APP_MODE"] == "server"
    os.environ.pop("APP_MODE", None)
