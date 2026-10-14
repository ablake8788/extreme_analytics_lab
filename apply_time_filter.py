"""
apply_time_filter.py - adds a From / To time period filter to the
Extreme & Change Analytics Lab.

Run once from the project root (the folder containing run.py):

    python apply_time_filter.py

What it changes (each file is backed up as <name>.bak first):
  app/routes/api.py      - passes date_from / date_to to extract_series()
                           and adds GET /api/time_range
  app/static/js/app.js   - adds From / To inputs to the "Select columns"
                           panel and sends them with every analysis/report

Safe to run more than once: it skips anything already applied.
Requires the updated app/services/data_loader.py (with time_range()).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "app" / "routes" / "api.py"
JS = ROOT / "app" / "static" / "js" / "app.js"
LOADER = ROOT / "app" / "services" / "data_loader.py"

MARKER = "TIME PERIOD FILTER"

# --------------------------------------------------------------------------
# api.py
# --------------------------------------------------------------------------

CALL_PATTERN = re.compile(
    r'extract_series\(\s*df\s*,\s*data\.get\(\s*"timestamp_column"\s*\)\s*or\s*None\s*,'
    r'\s*data\[\s*"value_column"\s*\]\s*,?\s*\)'
)
CALL_REPLACEMENT = (
    'extract_series(\n'
    '            df, data.get("timestamp_column") or None, data["value_column"],\n'
    '            start=data.get("date_from") or None, end=data.get("date_to") or None,\n'
    '        )'
)

API_ROUTE = '''

# === TIME PERIOD FILTER (added by apply_time_filter.py) =====================
from flask import request as _tp_request, jsonify as _tp_jsonify
from app.services.data_loader import (
    read_sheet as _tp_read_sheet, read_table as _tp_read_table,
    time_range as _tp_time_range, DataLoadError as _TpDataLoadError,
)


@api_bp.get("/time_range")
def time_range_route():
    """First/last timestamp of the chosen timestamp column, used to pre-fill
    the From / To inputs."""
    token = _tp_request.args.get("token", "")
    sheet = _tp_request.args.get("sheet", "")
    ts_col = _tp_request.args.get("timestamp_column", "") or None
    path = _resolve_path(token)
    if not path:
        return _tp_jsonify({"error": "Unknown or expired upload. Please upload the file again."}), 400
    try:
        df = _tp_read_sheet(str(path), sheet) if sheet else _tp_read_table(str(path))
        first, last, count = _tp_time_range(df, ts_col)
    except _TpDataLoadError as exc:
        return _tp_jsonify({"error": str(exc)}), 400
    fmt = "%Y-%m-%dT%H:%M:%S"
    return _tp_jsonify({
        "is_datetime": first is not None,
        "start": first.strftime(fmt) if first is not None else None,
        "end": last.strftime(fmt) if last is not None else None,
        "count": count,
    })
'''

# --------------------------------------------------------------------------
# app.js
# --------------------------------------------------------------------------

JS_BLOCK = r'''

// === TIME PERIOD FILTER (added by apply_time_filter.py) =====================
(function () {
  const panel = document.getElementById('columnsPanel');
  if (!panel || document.getElementById('dateFrom')) return;

  const box = document.createElement('div');
  box.innerHTML = `
    <div class="group-title" style="margin-top:6px">Time period (optional)</div>
    <div class="controls">
      <div><label for="dateFrom">From</label><input type="datetime-local" id="dateFrom" step="1"></div>
      <div><label for="dateTo">To</label><input type="datetime-local" id="dateTo" step="1"></div>
      <div style="flex:0 0 auto;min-width:0;align-self:flex-end">
        <button type="button" id="dateFullRange" style="background:#eef2f8;color:#2f6fed">Full range</button>
      </div>
    </div>
    <p id="dateRangeInfo" class="muted" style="margin-top:-8px"></p>`;
  panel.appendChild(box);

  const fromEl = document.getElementById('dateFrom');
  const toEl = document.getElementById('dateTo');
  const info = document.getElementById('dateRangeInfo');
  let full = { start: '', end: '' };
  let lastKey = '';

  function tokenNow() {
    try { return currentToken; } catch (e) { return null; }
  }

  async function loadRange(force) {
    const token = tokenNow();
    if (!token) return;
    const sheet = document.getElementById('sheetSelect')?.value || '';
    const tsCol = document.getElementById('timestampColumn')?.value || '';
    const key = [token, sheet, tsCol].join('|');
    if (!force && key === lastKey) return;
    lastKey = key;
    info.textContent = 'Reading time range...';
    try {
      const q = new URLSearchParams({ token, sheet, timestamp_column: tsCol });
      const res = await fetch('/api/time_range?' + q.toString());
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      if (!data.is_datetime) {
        full = { start: '', end: '' };
        fromEl.value = ''; toEl.value = '';
        fromEl.disabled = toEl.disabled = true;
        info.textContent = 'Time filter is available when the timestamp column contains dates/times.';
        return;
      }
      fromEl.disabled = toEl.disabled = false;
      full = { start: data.start, end: data.end };
      fromEl.min = toEl.min = data.start;
      fromEl.max = toEl.max = data.end;
      fromEl.value = data.start;
      toEl.value = data.end;
      info.textContent = `Data covers ${data.start.replace('T', ' ')} to ${data.end.replace('T', ' ')} (${data.count.toLocaleString()} readings).`;
    } catch (e) {
      info.textContent = e.message;
    }
  }

  document.getElementById('dateFullRange').onclick = () => {
    fromEl.value = full.start;
    toEl.value = full.end;
  };

  // Reload the range after an upload (columns get repopulated) or a change
  // of sheet / timestamp column.
  const tsSel = document.getElementById('timestampColumn');
  if (tsSel) {
    new MutationObserver(() => loadRange(true)).observe(tsSel, { childList: true });
    tsSel.addEventListener('change', () => loadRange(false));
  }
  document.getElementById('sheetSelect')?.addEventListener('change', () => setTimeout(() => loadRange(true), 300));

  // Send date_from / date_to with every analysis or report request.
  const originalFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    try {
      const u = typeof url === 'string' ? url : (url && url.url) || '';
      if (opts && String(opts.method || '').toUpperCase() === 'POST' &&
          u.indexOf('/api/') !== -1 && typeof opts.body === 'string') {
        const body = JSON.parse(opts.body);
        if (body && typeof body === 'object' && 'value_column' in body) {
          const isFull = fromEl.value === full.start && toEl.value === full.end;
          body.date_from = (!fromEl.disabled && !isFull) ? fromEl.value : '';
          body.date_to = (!toEl.disabled && !isFull) ? toEl.value : '';
          opts = Object.assign({}, opts, { body: JSON.stringify(body) });
        }
      }
    } catch (e) { /* not JSON - leave the request unchanged */ }
    return originalFetch(url, opts);
  };
})();
'''


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup: {bak.relative_to(ROOT)}")


def main() -> int:
    for p in (API, JS, LOADER):
        if not p.exists():
            print(f"ERROR: {p.relative_to(ROOT)} not found. Run this from the extreme_analytics_lab folder.")
            return 1

    if "def time_range(" not in LOADER.read_text(encoding="utf-8"):
        print("ERROR: app/services/data_loader.py is the old version (no time_range).")
        print("       Extract extreme_time_filter_update.zip first, then run this again.")
        return 1

    ok = True

    # ---- api.py
    api = API.read_text(encoding="utf-8")
    if MARKER in api:
        print("api.py: already patched, skipping.")
    else:
        new_api, n = CALL_PATTERN.subn(CALL_REPLACEMENT, api)
        if n == 0:
            print("ERROR: api.py - could not find the extract_series(...) call to update.")
            print("       Paste app/routes/api.py into the chat and I will patch it by hand.")
            ok = False
        elif "_resolve_path" not in new_api or "api_bp" not in new_api:
            print("ERROR: api.py - expected api_bp and _resolve_path, not found.")
            ok = False
        else:
            backup(API)
            API.write_text(new_api.rstrip() + "\n" + API_ROUTE, encoding="utf-8")
            print(f"api.py: updated {n} extract_series call(s) and added /api/time_range.")

    # ---- app.js
    js = JS.read_text(encoding="utf-8")
    if MARKER in js:
        print("app.js: already patched, skipping.")
    elif "columnsPanel" not in js and "currentToken" not in js:
        print("ERROR: app.js does not look like the Extreme Analytics Lab script.")
        ok = False
    else:
        backup(JS)
        JS.write_text(js.rstrip() + "\n" + JS_BLOCK, encoding="utf-8")
        print("app.js: added From / To time period controls.")

    if ok:
        print("\nDone. Run .\\rebuild.ps1 (or .\\build.ps1) to test.")
        return 0
    print("\nNothing was broken: files with errors were left unchanged.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
