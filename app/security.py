"""
security.py - login and server protections for web deployment.

init_security(app) is called from create_app(). In local mode (your PC and
the .exe) it does nothing. In server mode it:
  - requires a login for every page and /api call (password from settings)
  - locks an address out for a few minutes after repeated wrong passwords
  - uses secure session cookies and standard security headers
  - trusts GoDaddy's proxy headers (https, client address)
  - deletes uploaded files older than upload_max_age_hours
  - adds a "Log out" button to the app page
"""
from __future__ import annotations

import hmac
import secrets
import time
from datetime import timedelta
from html import escape
from pathlib import Path

from flask import Response, current_app, jsonify, redirect, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from .server_settings import ServerSettings, load_settings

OPEN_PATHS = {"/login", "/login/check", "/logout", "/healthz"}
FORM_MAX_AGE = 2 * 3600  # a sign-in form stays valid for 2 hours
_failures: dict[str, list[float]] = {}
_last_cleanup = [0.0]


def init_security(app):
    settings = load_settings()
    app.config["APP_MODE"] = settings.mode
    if not settings.is_server:
        return app
    settings.validate()

    app.secret_key = settings.secret_key
    app.config.update(
        SESSION_COOKIE_NAME="tal_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=settings.session_hours),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.extensions["tal_settings"] = settings

    app.add_url_rule("/login", "tal_login", _login_view, methods=["GET", "POST"])
    app.add_url_rule("/login/check", "tal_login_check", _login_check_view)
    app.add_url_rule("/logout", "tal_logout", _logout_view, methods=["GET", "POST"])
    app.add_url_rule("/healthz", "tal_health", lambda: ("ok", 200, {"Content-Type": "text/plain"}))
    app.before_request(_guard)
    app.after_request(_after)
    return app


# ------------------------------------------------------------------ guard
def _settings() -> ServerSettings:
    return current_app.extensions["tal_settings"]


def _form_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="tal-login-form")


def _guard():
    _cleanup_uploads()
    if request.path in OPEN_PATHS:
        return None
    if session.get("tal_auth"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Your session has ended. Please log in again."}), 401
    return redirect("/login?next=" + _safe_next(request.path))


def _safe_next(path: str) -> str:
    if not path or not path.startswith("/") or path.startswith("//") or path.startswith("/login"):
        return "/"
    return path


def _after(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if _settings().secure_cookies:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if (session.get("tal_auth") and response.mimetype == "text/html"
            and not response.direct_passthrough and request.path not in OPEN_PATHS):
        body = response.get_data()
        if b"</body>" in body and b"tal-logout" not in body:
            response.set_data(body.replace(b"</body>", _LOGOUT_SNIPPET + b"</body>", 1))
    return response


_LOGOUT_SNIPPET = (
    b'<form method="post" action="/logout" class="tal-logout" style="position:fixed;top:14px;right:16px;'
    b'z-index:60;margin:0"><button type="submit" style="height:32px;padding:0 14px;border-radius:6px;'
    b'border:1px solid rgba(255,255,255,.35);background:rgba(255,255,255,.08);color:#fff;font:600 13px '
    b'\'Segoe UI\',Arial,sans-serif;cursor:pointer">Log out</button></form>'
)


# ------------------------------------------------------------------ login
def _client() -> str:
    return request.remote_addr or "unknown"


def _locked_for() -> int:
    s = _settings()
    now = time.time()
    recent = [t for t in _failures.get(_client(), []) if now - t < s.lockout_minutes * 60]
    _failures[_client()] = recent
    if len(recent) >= s.max_login_attempts:
        return int(s.lockout_minutes * 60 - (now - recent[0])) + 1
    return 0


def _password_ok(given: str) -> bool:
    s = _settings()
    if s.password_hash:
        try:
            return check_password_hash(s.password_hash, given)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(given.encode("utf-8"), s.password.encode("utf-8"))


def _render_login(nxt: str, error: str = "", status: int = 200, detail: str = "") -> Response:
    # The form carries its own signed, time-limited token, so it does not
    # depend on a cookie surviving between showing and submitting the form.
    token = _form_signer().dumps(secrets.token_hex(8))
    extra = f'<p class="err" role="alert">{escape(error)}</p>' if error else ""
    if detail:
        extra += f'<p class="detail">{escape(detail)}</p>'
    html = _LOGIN_HTML.replace("{{csrf}}", token).replace("{{next}}", escape(nxt)).replace("{{error}}", extra)
    return Response(html, status=status, mimetype="text/html")


def _login_view():
    nxt = _safe_next(request.values.get("next", "/"))
    if session.get("tal_auth"):
        return redirect(nxt)
    if request.method != "POST":
        return _render_login(nxt)
    wait = _locked_for()
    if wait:
        return _render_login(nxt, f"Too many attempts. Try again in {max(1, round(wait / 60))} minute(s).", 401)
    try:
        _form_signer().loads(request.form.get("csrf", ""), max_age=FORM_MAX_AGE)
    except SignatureExpired:
        return _render_login(nxt, "The form expired. Please try again.", 401)
    except BadSignature:
        return _render_login(nxt, "The form was not valid. Please try again.", 401)
    if _password_ok(request.form.get("password", "")):
        session.clear()
        session.permanent = True
        session["tal_auth"] = True
        _failures.pop(_client(), None)
        # Confirm the browser really kept the sign-in before going on.
        return redirect("/login/check?next=" + nxt)
    _failures.setdefault(_client(), []).append(time.time())
    time.sleep(0.4)
    return _render_login(nxt, "That password is not correct.", 401)


def _login_check_view():
    nxt = _safe_next(request.args.get("next", "/"))
    if session.get("tal_auth"):
        return redirect(nxt)
    # Password was right, but the browser did not send the sign-in cookie back.
    s = _settings()
    detail = (f"Diagnostics: address={request.host_url} scheme={request.scheme} "
              f"secure_cookies={s.secure_cookies} forwarded_proto={request.headers.get('X-Forwarded-Proto', '-')} "
              f"cookie_received={'yes' if request.cookies else 'no'}")
    msg = ("Your password was accepted, but your browser did not keep the sign-in. "
           "Open the site at https://" + (s.domain or request.host) + " (with the padlock), "
           "allow cookies for it, and try again.")
    return _render_login(nxt, msg, 401, detail)


def _logout_view():
    session.clear()
    return redirect("/login")


# ------------------------------------------------------------------ uploads
def _cleanup_uploads():
    now = time.time()
    if now - _last_cleanup[0] < 600:
        return
    _last_cleanup[0] = now
    try:
        from .config import Config
        folder = Path(Config.UPLOAD_DIR)
    except Exception:
        return
    max_age = _settings().upload_max_age_hours * 3600
    if not folder.is_dir():
        return
    for f in folder.iterdir():
        try:
            if f.is_file() and now - f.stat().st_mtime > max_age:
                f.unlink()
        except OSError:
            pass


_LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Sign in - Extreme &amp; Change Analytics Lab</title>
<style>
  :root { --g:#1f2a33; --line:#d5dbe1; --signal:#2f6fed; --muted:#5d6975; }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:grid; grid-template-rows:auto 1fr; background:#edf0f3; color:var(--g);
         font-family:"Segoe UI Variable Text","Segoe UI",system-ui,Arial,sans-serif; }
  header { color:#eef2f5; border-bottom:3px solid var(--signal);
           background:repeating-linear-gradient(90deg,rgba(255,255,255,.035) 0 1px,transparent 1px 3px),
                      linear-gradient(180deg,#334350,var(--g)); }
  header > div { max-width:1100px; margin:0 auto; padding:20px 24px; display:flex; align-items:center; gap:16px; }
  .mark { width:44px; height:44px; border-radius:9px; display:grid; place-items:center;
          background:linear-gradient(145deg,#b9c3cc,#7e8a96 55%,#aab5bf); color:var(--g);
          font:700 19px Bahnschrift,"Segoe UI",Arial,sans-serif; box-shadow:inset 0 1px 0 rgba(255,255,255,.6); }
  header small { display:block; color:#a9b6c2; font:13px Bahnschrift,"Segoe UI",Arial,sans-serif; }
  header strong { font:600 20px Bahnschrift,"Segoe UI",Arial,sans-serif; }
  main { display:grid; place-items:start center; padding:56px 16px; }
  form { width:100%; max-width:380px; background:#fff; border:1px solid var(--line); border-radius:6px; padding:28px; }
  h1 { font:600 21px Bahnschrift,"Segoe UI",Arial,sans-serif; margin:0 0 4px; }
  p.sub { margin:0 0 20px; color:var(--muted); font-size:13.5px; }
  label { display:block; font-size:12.5px; font-weight:600; color:#3a4753; margin-bottom:6px; }
  input[type=password] { width:100%; height:40px; padding:0 12px; border:1px solid var(--line); border-radius:6px; font:inherit; font-size:15px; }
  input[type=password]:focus { outline:none; border-color:var(--signal); box-shadow:0 0 0 3px rgba(47,111,237,.18); }
  button { margin-top:16px; width:100%; height:42px; border:0; border-radius:6px; background:var(--signal); color:#fff;
           font:600 15px "Segoe UI",Arial,sans-serif; cursor:pointer; }
  button:hover { background:#2159c9; }
  .err { margin:0 0 14px; padding:9px 12px; border-radius:6px; background:#fde5e3; color:#a1261c; font-size:13.5px; }
  .detail { margin:-6px 0 14px; font:11.5px Consolas,monospace; color:#5d6975; word-break:break-all; }
</style></head>
<body>
<header><div><div class="mark" aria-hidden="true">Ti</div><div><small>Titanium Analytics</small><strong>Extreme &amp; Change Analytics Lab</strong></div></div></header>
<main>
<form method="post" action="/login">
  <h1>Sign in</h1>
  <p class="sub">Enter the access password to continue.</p>
  {{error}}
  <label for="password">Password</label>
  <input type="password" id="password" name="password" autocomplete="current-password" required autofocus>
  <input type="hidden" name="csrf" value="{{csrf}}">
  <input type="hidden" name="next" value="{{next}}">
  <button type="submit">Sign in</button>
</form>
</main>
</body></html>
"""
