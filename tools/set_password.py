import getpass, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.server_settings import load_settings, ini_paths

_, local = ini_paths()
local = local or __import__("pathlib").Path(ROOT, "config.local.ini")
if os.environ.get("APP_PASSWORD"):
    print("NOTE: environment variable APP_PASSWORD is set and overrides the file. Remove it: Remove-Item Env:APP_PASSWORD")

pw1 = getpass.getpass("New sign-in password: ")
pw2 = getpass.getpass("Type it again: ")
if pw1 != pw2:
    sys.exit("The two entries differ - nothing changed.")
if not pw1 or pw1 != pw1.strip() or any(c in pw1 for c in ";#%"):
    sys.exit("Use letters, numbers and - _ ! @ only (no ; # %, no spaces at the ends) - nothing changed.")

text = local.read_text(encoding="utf-8-sig") if local.exists() else ""
lines = [l for l in text.splitlines() if not re.match(r"\s*password\s*=", l, re.I)]
out, inserted = [], False
for l in lines:
    out.append(l)
    if not inserted and re.match(r"\s*\[server\]\s*$", l, re.I):
        out.append("password = " + pw1); inserted = True
if not inserted:
    out += ["", "[server]", "password = " + pw1]
local.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("Written to:", local)

s = load_settings()
print("app now reads length:", len(s.password), "| you typed length:", len(pw1))
print("MATCH - restart the app and sign in" if s.password == pw1 else "STILL NO MATCH - paste this output")
