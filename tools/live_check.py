"""
live_check.py - starts the real app and tests it over HTTP, in local mode and
in server (login) mode, plus GoDaddy's passenger_wsgi start file.

Used by test_all.ps1. Can also be run on its own from the project folder:
    python tools/live_check.py [path\\to\\data.xlsx]

It never reads or changes your config.local.ini: each run uses a temporary
ini file of its own.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    return ok


# --------------------------------------------------------------------- http
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def request(self, method, path, data=None, headers=None, timeout=120):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(self, path):
        return self.request("GET", path)

    def post_form(self, path, fields):
        body = urllib.parse.urlencode(fields).encode()
        return self.request("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"})

    def post_json(self, path, obj):
        return self.request("POST", path, json.dumps(obj).encode(), {"Content-Type": "application/json"})

    def upload(self, path, file_path: Path):
        boundary = uuid.uuid4().hex
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file_path.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        body = head + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


# --------------------------------------------------------------------- server
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(ini_text: str, extra_env=None):
    ini = Path(tempfile.mkstemp(suffix=".ini")[1])
    ini.write_text(ini_text, encoding="utf-8")
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_")}
    env["APP_CONFIG_LOCAL"] = str(ini)
    env.update(extra_env or {})
    code = f"from app import create_app; create_app().run(host='127.0.0.1', port={port}, debug=False, use_reloader=False)"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc, base, ini
        except OSError:
            time.sleep(0.25)
    return proc, None, ini


def stop_server(proc, ini: Path):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    try:
        ini.unlink()
    except OSError:
        pass


def analyze_flow(c: Client, data_file: Path | None, label: str):
    if not data_file:
        print(f"  [SKIP] {label}: upload + analysis (no data file given)")
        return
    st, _, body = c.upload("/api/upload", data_file)
    if not check(f"{label}: upload {data_file.name}", st == 200, f"HTTP {st}: {body[:200]!r}"):
        return
    up = json.loads(body)
    cols = up.get("columns", [])
    value_col = cols[1] if len(cols) > 1 else cols[0]
    sheet = (up.get("sheets") or [""])[0]
    payload = {"token": up["token"], "sheet": sheet, "timestamp_column": "", "value_column": value_col, "window": 96}
    t0 = time.time()
    st, _, body = c.post_json("/api/analyze", payload)
    ok = st == 200
    rows = json.loads(body).get("rows", []) if ok else []
    check(f"{label}: analysis runs", ok and len(rows) > 0,
          f"HTTP {st}: {body[:200]!r}" if not ok else "no rows")
    try:  # remove the test upload again
        (ROOT / "uploads" / Path(up["token"]).name).unlink()
    except (OSError, KeyError):
        pass
    if ok and rows:
        print(f"         {len(rows):,} rows analyzed in {time.time() - t0:.1f}s; columns include "
              f"{', '.join(k for k in ('Day/Night', 'State', 'ZScore') if k in rows[0])}")


# --------------------------------------------------------------------- checks
def local_mode(data_file):
    print("\n== Local mode (no login) ==")
    proc, base, ini = start_server("[app]\nmode = local\n")
    try:
        if not check("app starts", base is not None, proc.stdout.read() if proc.poll() is not None else ""):
            return
        c = Client(base)
        st, _, body = c.get("/")
        check("home page opens without login", st == 200 and b"Sign in" not in body, f"HTTP {st}")
        st, _, _ = c.get("/login")
        check("no login page in local mode", st == 404, f"HTTP {st}")
        analyze_flow(c, data_file, "local")
    finally:
        stop_server(proc, ini)


def server_mode(data_file):
    print("\n== Server mode (login), settings from an ini file ==")
    password = "test-" + secrets.token_hex(4)
    ini = f"[app]\nmode = server\n[server]\npassword = {password}\nsecret_key = {secrets.token_hex(24)}\n"
    proc, base, ini_path = start_server(ini)
    try:
        if not check("app starts in server mode", base is not None,
                     proc.stdout.read() if proc.poll() is not None else ""):
            return
        c = Client(base)
        st, h, _ = c.get("/")
        check("home page redirects to sign-in", st == 302 and "/login" in h.get("Location", ""), f"HTTP {st}")
        st, _, body = c.post_json("/api/analyze", {})
        check("API blocked before login (401)", st == 401, f"HTTP {st}")
        st, _, body = c.get("/login")
        m = re.search(rb'name="csrf" value="([^"]+)"', body)
        check("sign-in page shows", st == 200 and m is not None, f"HTTP {st}")
        csrf = m.group(1).decode() if m else ""
        st, _, body = c.post_form("/login", {"password": "wrong", "csrf": csrf, "next": "/"})
        check("wrong password rejected", st == 401 and b"not correct" in body, f"HTTP {st}")
        m = re.search(rb'name="csrf" value="([^"]+)"', body)
        csrf = m.group(1).decode() if m else csrf
        st, h, _ = c.post_form("/login", {"password": password, "csrf": csrf, "next": "/"})
        ok = st == 302
        if ok and "/login/check" in h.get("Location", ""):
            loc = h.get("Location"); loc = loc[loc.index("/login/check"):]
            st, h, _ = c.get(loc)
            ok = st == 302
        check("right password signs in", ok, f"HTTP {st}")
        st, _, body = c.get("/")
        check("app page opens with Log out button", st == 200 and b"tal-logout" in body, f"HTTP {st}")
        analyze_flow(c, data_file, "server")
        st, _, _ = c.post_form("/logout", {})
        check("log out", st == 302, f"HTTP {st}")
        st, _, _ = c.post_json("/api/analyze", {})
        check("API blocked after logout (401)", st == 401, f"HTTP {st}")
    finally:
        stop_server(proc, ini_path)


def refuses_without_password():
    print("\n== Safety: server mode without a password ==")
    proc, base, ini = start_server("[app]\nmode = server\n")
    try:
        out = ""
        if proc.poll() is None:
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        else:
            out = proc.stdout.read()
        check("refuses to start without a password", base is None and "password" in (out or "").lower(),
              "it started - it must not" if base else (out or "")[-200:])
    finally:
        stop_server(proc, ini)


def passenger():
    print("\n== GoDaddy start file (passenger_wsgi.py) ==")
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_")}
    env.update({"APP_PASSWORD": "p", "APP_SECRET_KEY": secrets.token_hex(24),
                "APP_CONFIG_LOCAL": str(ROOT / "__no_such_file__.ini")})
    code = "import passenger_wsgi as p; print(p.application.config['APP_MODE'])"
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True)
    check("passenger_wsgi loads in server mode", r.returncode == 0 and r.stdout.strip().endswith("server"),
          (r.stderr or r.stdout)[-300:])


def main() -> int:
    data_file = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    if data_file and not data_file.exists():
        print(f"Data file not found: {data_file} - upload tests will be skipped.")
        data_file = None
    local_mode(data_file)
    server_mode(data_file)
    refuses_without_password()
    passenger()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\nLive checks: {len(RESULTS) - len(failed)} passed, {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
