const $ = id => document.getElementById(id);
let currentToken = null;
let chartInstance = null;
let lastAnalyzePayload = null;
let lastReport = null;

$('uploadBtn').onclick = async () => {
  const file = $('fileInput').files[0];
  if (!file) { $('uploadStatus').textContent = 'Choose a file first.'; return; }
  const fd = new FormData();
  fd.append('file', file);
  $('uploadStatus').textContent = 'Uploading...';
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    currentToken = data.token;
    $('uploadStatus').textContent = `Loaded "${data.filename}" — ${data.row_count} row(s).`;

    const sheetRow = $('sheetRow');
    if (data.sheets && data.sheets.length) {
      sheetRow.style.display = 'flex';
      const sel = $('sheetSelect');
      sel.innerHTML = '';
      data.sheets.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s; opt.textContent = s;
        sel.appendChild(opt);
      });
    } else {
      sheetRow.style.display = 'none';
    }

    populateColumns(data.columns);
    $('columnsPanel').style.display = 'block';
    $('paramsPanel').style.display = 'block';
    $('resultsPanel').style.display = 'none';
  } catch (e) {
    $('uploadStatus').textContent = e.message;
  }
};

$('sheetSelect')?.addEventListener('change', async () => {
  const sheet = $('sheetSelect').value;
  const res = await fetch(`/api/columns?token=${encodeURIComponent(currentToken)}&sheet=${encodeURIComponent(sheet)}`);
  const data = await res.json();
  if (!res.ok) { $('uploadStatus').textContent = data.error; return; }
  populateColumns(data.columns);
});

function populateColumns(columns) {
  const tsSel = $('timestampColumn');
  const valSel = $('valueColumn');
  tsSel.innerHTML = '<option value="">— row index —</option>';
  valSel.innerHTML = '';
  columns.forEach((c, i) => {
    const o1 = document.createElement('option'); o1.value = c; o1.textContent = c;
    tsSel.appendChild(o1);
    const o2 = document.createElement('option'); o2.value = c; o2.textContent = c;
    if (i === Math.min(1, columns.length - 1)) o2.selected = true;
    valSel.appendChild(o2);
  });
}

$('analyzeBtn').onclick = async () => {
  if (!currentToken) { $('analyzeStatus').textContent = 'Upload a file first.'; return; }
  const payload = {
    token: currentToken,
    sheet: $('sheetSelect')?.value || '',
    timestamp_column: $('timestampColumn').value,
    value_column: $('valueColumn').value,
    baseline_method: $('baselineMethod').value,
    window: $('window').value,
    ewma_alpha: $('ewmaAlpha').value,
    k_e: $('kE').value,
    k_p: $('kP').value,
    percentile_p: $('percentileP').value,
    k_iqr: $('kIqr').value,
    n_p: $('nP').value,
    n_m: $('nM').value,
    k_m: $('kM').value,
    n_exit: $('nExit').value,
    roc_window: $('rocWindow').value,
    roc_baseline_window: $('rocBaselineWindow').value,
    roc_k: $('rocK').value,
    frequency_window: $('frequencyWindow').value,
    frequency_min_count: $('frequencyMinCount').value,
    w_magnitude: $('wMagnitude').value,
    w_duration: $('wDuration').value,
    w_frequency: $('wFrequency').value,
  };
  $('analyzeStatus').textContent = 'Running analysis...';
  lastAnalyzePayload = payload;
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    $('analyzeStatus').textContent = '';
    renderResults(data);
  } catch (e) {
    $('analyzeStatus').textContent = e.message;
  }
};

function badgeFor(state) {
  if (state === 'Confirmed/Materialized Shift') return `<span class="badge badge-confirmed">${state}</span>`;
  if (state === 'Persistent') return `<span class="badge badge-persistent">${state}</span>`;
  if (state === 'Extreme triggered' || state === 'Extreme/elevated') return `<span class="badge badge-extreme">${state}</span>`;
  return `<span class="badge badge-normal">${state}</span>`;
}

function renderResults(data) {
  $('resultsPanel').style.display = 'block';
  const s = data.summary;
  const items = [
    ['Rows analyzed', s.row_count],
    ['Baseline method', s.baseline_method],
    ['Extreme periods', s.extreme_periods],
    ['Persistent periods', s.persistent_periods],
    ['Confirmed shifts', s.confirmed_shift_periods],
    ['Material extremes', s.material_extreme_periods],
    ['Abnormal changes', s.abnormal_change_periods],
    ['Material changes', s.material_change_periods],
  ];
  $('summaryGrid').innerHTML = items.map(([label, value]) =>
    `<div class="summary-item"><div class="label">${label}</div><div class="value">${value}</div></div>`
  ).join('');

  const rows = data.rows;
  const tbody = document.querySelector('#resultsTable tbody');
  tbody.innerHTML = rows.map(r => `<tr>
    <td>${r.Timestamp}</td>
    <td>${fmt(r.Value)}</td>
    <td>${fmt(r.ZScore)}</td>
    <td>${badgeFor(r.State)}</td>
    <td>${r.PersistenceCount ?? ''}</td>
    <td>${r.ExtremeFlag ? 'Yes' : ''}</td>
    <td>${r.AbnormalChangeFlag ? 'Yes' : ''}</td>
    <td>${fmt(r.MaterialityScore)}</td>
  </tr>`).join('');

  drawChart(rows);
}

function fmt(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return Math.round(v * 1000) / 1000;
  return v;
}

function drawChart(rows) {
  const ctx = $('chart').getContext('2d');
  if (chartInstance) chartInstance.destroy();
  const labels = rows.map(r => r.Timestamp);
  const values = rows.map(r => r.Value);
  const upper = rows.map(r => r.UpperLimit);
  const lower = rows.map(r => r.LowerLimit);
  const pointColors = rows.map(r => {
    if (r.State === 'Confirmed/Materialized Shift') return '#c0392b';
    if (r.State === 'Persistent') return '#c9860a';
    if (r.State === 'Extreme triggered' || r.State === 'Extreme/elevated') return '#b5316b';
    return '#2f6fed';
  });

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Value', data: values, borderColor: '#2f6fed', backgroundColor: 'transparent', pointBackgroundColor: pointColors, pointRadius: 2.5, borderWidth: 2, tension: 0.15 },
        { label: 'Upper limit', data: upper, borderColor: '#c0392b55', borderDash: [5, 4], pointRadius: 0, borderWidth: 1.3 },
        { label: 'Lower limit', data: lower, borderColor: '#c0392b55', borderDash: [5, 4], pointRadius: 0, borderWidth: 1.3 },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { ticks: { maxTicksLimit: 12, font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { font: { size: 11 } }, grid: { color: '#eef2f8' } },
      },
    },
  });
}

$('reportBtn').onclick = async () => {
  if (!lastAnalyzePayload) { $('reportStatus').textContent = 'Run an analysis first.'; return; }
  $('reportStatus').textContent = 'Generating report...';
  $('reportBtn').disabled = true;
  try {
    const res = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastAnalyzePayload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    lastReport = data;
    $('reportChartImg').src = `data:image/png;base64,${data.chart_png_base64}`;
    $('reportFindings').innerHTML = markdownToHtml(data.markdown);
    $('reportPanel').style.display = 'block';
    $('reportStatus').textContent = '';
    $('reportPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    $('reportStatus').textContent = e.message;
  } finally {
    $('reportBtn').disabled = false;
  }
};

$('downloadChartBtn').onclick = () => {
  if (!lastReport) return;
  downloadBlob(base64ToBlob(lastReport.chart_png_base64, 'image/png'), 'analysis_chart.png');
};

$('downloadReportBtn').onclick = () => {
  if (!lastReport) return;
  downloadBlob(new Blob([lastReport.markdown], { type: 'text/markdown' }), 'analysis_report.md');
};

function base64ToBlob(b64, mime) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Minimal Markdown -> HTML for report preview (headings, bold, bullets, hr, image, table)
function markdownToHtml(md) {
  const esc = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
  const lines = md.split('\n');
  let html = '';
  let inList = false;
  let inTable = false;
  for (let raw of lines) {
    const line = raw;
    if (/^!\[.*\]\(chart\.png\)$/.test(line)) { continue; } // chart already shown above
    if (/^---+$/.test(line)) { if (inList) { html += '</ul>'; inList = false; } html += '<hr>'; continue; }
    if (/^\|/.test(line)) {
      if (!inTable) { html += '<table class="report-table">'; inTable = true; }
      const isSep = /^\|[\s:-]+\|$/.test(line.replace(/-{2,}/g, '-'));
      if (isSep) continue;
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      html += '<tr>' + cells.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>';
      continue;
    } else if (inTable) { html += '</table>'; inTable = false; }
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) {
      if (inList) { html += '</ul>'; inList = false; }
      const level = h[1].length + 2;
      html += `<h${level}>${esc(h[2])}</h${level}>`;
      continue;
    }
    if (/^-\s+/.test(line)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${esc(line.replace(/^-\s+/, ''))}</li>`;
      continue;
    } else if (inList) { html += '</ul>'; inList = false; }
    if (line.trim() === '') continue;
    html += `<p>${esc(line)}</p>`;
  }
  if (inList) html += '</ul>';
  if (inTable) html += '</table>';
  return html;
}


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
