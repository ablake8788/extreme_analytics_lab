import getpass, os, sys, configparser
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.server_settings import load_settings, ini_paths
shared, local = ini_paths()
print("shared ini :", shared, "| exists:", shared.exists())
print("local ini  :", local, "| exists:", bool(local and local.exists()))
print("env APP_PASSWORD set:", bool(os.environ.get("APP_PASSWORD")), "| env APP_CONFIG_LOCAL:", os.environ.get("APP_CONFIG_LOCAL"))
for path in [p for p in (shared, local) if p and p.exists()]:
    lines = [l for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip().lower().startswith("password")]
    print(f"  {path.name}: {len(lines)} password line(s), value lengths as written:",
          [len(l.split("=", 1)[1].strip()) for l in lines if "=" in l])
s = load_settings()
typed = getpass.getpass("Password you type in the browser: ")
print("app uses length:", len(s.password), "| typed length:", len(typed))
print("MATCH" if typed == s.password else "NO MATCH")
