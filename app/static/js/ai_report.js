/*
 * ai_report.js - "AI report" panel for the Extreme & Change Analytics Lab.
 *
 *   Save results CSV...            Save As dialog, you choose folder and name
 *   Generate AI report (Word)      the app computes the facts, reads the reference
 *   Generate AI report (Excel)     document and asks OpenAI for the wording, then
 *   Generate both                  builds the .docx and/or the .xlsx workbook
 *
 *   For each report:  Open (Word / Excel, PC version) - Save as... - Download -
 *                     Save copy to reports folder (PC version)
 *   Open reports folder (PC version)
 *
 * Save As dialogs use the browser's File System Access API (Edge / Chrome).
 * Other browsers fall back to a normal download.
 */
(function () {
  'use strict';
  if (window.__aiReportLoaded) return;
  window.__aiReportLoaded = true;

  let rows = null;          // rows of the last analysis
  let root = null;
  let savedCsvFile = null;  // a results CSV chosen from disk
  const LS_KEY = 'tal_ai_report_location';

  const $ = (sel) => root.querySelector(sel);
  const canPick = typeof window.showSaveFilePicker === 'function';

  // ------------------------------------------------------------ helpers
  function unitsFromColumn() {
    const sel = document.getElementById('valueColumn');
    const txt = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : '';
    const m = txt.match(/\[([^\]]+)\]/);
    const u = m ? m[1].trim().toLowerCase() : '';
    return { fahrenheit: '°F', celsius: '°C' }[u] || (m ? m[1] : '');
  }
  function defaultLocation() {
    const remembered = (() => { try { return localStorage.getItem(LS_KEY) || ''; } catch (e) { return ''; } })();
    if (remembered) return remembered;
    const fi = document.getElementById('fileInput');
    const file = fi && fi.files && fi.files[0] ? fi.files[0].name.replace(/\.[^.]+$/, '').replace(/_/g, ' ') : '';
    const sel = document.getElementById('valueColumn');
    const col = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text.replace(/\s*\[[^\]]*\]\s*/, '') : '';
    return [file, col].filter(Boolean).join(', ') || 'Sensor';
  }
  const safe = (s) => String(s || 'Sensor').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 24).replace(/_+$/, '') || 'Sensor';   // short names: Windows paths max 260 characters
  const ymd = (t) => String(t || '').slice(0, 10).replace(/-/g, '');

  function rowsToCsv(list) {
    if (!list || !list.length) return '';
    const keys = Object.keys(list[0]);
    const lead = ['Timestamp', 'Value'];
    const cols = lead.filter((k) => keys.includes(k)).concat(keys.filter((k) => !lead.includes(k)));
    const cell = (v) => {
      if (v === null || v === undefined) return '';
      const t = String(v);
      return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    return '\ufeff' + [cols.join(',')].concat(list.map((r) => cols.map((k) => cell(r[k])).join(','))).join('\r\n');
  }

  function chosenRows() {
    const which = $('[data-ar=source]').value;
    if (which === 'page' && window.ChartExplorer && window.ChartExplorer.pageRows) {
      const pr = window.ChartExplorer.pageRows();
      if (pr && pr.length) return pr;
    }
    return rows;
  }

  // Opens the Save As dialog straight away (must happen right after the click),
  // then writes whatever makeBlob() produces. If anything fails after the
  // dialog created the (empty) file, that file is removed again and the
  // content is offered as a normal download instead - never a 0-byte file.
  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
  async function discard(handle) {
    try { if (handle && handle.remove) await handle.remove(); } catch (e) { /* older browsers: leave it */ }
  }

  async function saveAs(suggestedName, kind, makeBlob) {
    const types = kind === 'docx'
      ? [{ description: 'Word document', accept: { 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] } }]
      : kind === 'xlsx'
        ? [{ description: 'Excel workbook', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }]
        : [{ description: 'CSV file', accept: { 'text/csv': ['.csv'] } }];
    let handle = null;
    if (canPick) {
      try {
        handle = await window.showSaveFilePicker({ suggestedName, id: `extreme-${kind}`, startIn: 'documents', types });
      } catch (e) {
        if (e && e.name === 'AbortError') return null; // user cancelled
        console.warn('Save As dialog not available, using download:', e);
        handle = null;
      }
    }

    let result;
    try {
      result = await makeBlob();
    } catch (e) {
      await discard(handle);                             // do not leave an empty file behind
      throw e;
    }
    if (!result) { await discard(handle); return null; }
    const blob = result.blob || result;
    if (!blob || !blob.size) {
      await discard(handle);
      throw new Error('Nothing to save - the content came back empty.');
    }

    if (handle) {
      try {
        const w = await handle.createWritable();
        await w.write(blob);
        await w.close();
        const written = await handle.getFile();
        if (written.size === blob.size) return { name: handle.name, extra: result, dialog: true, size: blob.size };
        throw new Error(`only ${written.size} of ${blob.size} bytes were written`);
      } catch (e) {
        console.warn('Writing to the chosen file failed, using download instead:', e);
        await discard(handle);
        download(blob, handle.name || result.name || suggestedName);
        return { name: handle.name || suggestedName, extra: result, dialog: false, size: blob.size,
                 warning: `Could not write to the folder you chose (${e.message || e.name}). ` +
                          'This often happens in Dropbox/OneDrive folders while they sync. ' +
                          'The file was downloaded to your Downloads folder instead.' };
      }
    }
    download(blob, result.name || suggestedName);
    return { name: result.name || suggestedName, extra: result, dialog: false, size: blob.size };
  }

  function status(msg, kind) {
    const el = $('[data-ar=msg]');
    el.innerHTML = msg;
    el.style.color = kind === 'error' ? '#a1261c' : kind === 'ok' ? '#1e6b3e' : '#5d6975';
  }
  function busy(on) {
    root.querySelectorAll('button, select, input').forEach((b) => { b.disabled = on; });
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ------------------------------------------------------------ actions
  async function saveCsv() {
    const list = chosenRows();
    if (!list || !list.length) { status('Run an analysis first.', 'error'); return; }
    const loc = $('[data-ar=location]').value.trim();
    const name = `results_${safe(loc)}_${ymd(list[0].Timestamp)}-${ymd(list[list.length - 1].Timestamp)}.csv`;
    try {
      const r = await saveAs(name, 'csv', async () => new Blob([rowsToCsv(list)], { type: 'text/csv;charset=utf-8' }));
      if (r) {
        const kb = Math.max(1, Math.round(r.size / 1024)).toLocaleString();
        status(`Saved <b>${esc(r.name)}</b> (${list.length.toLocaleString()} rows, ${kb} KB)` +
               `${r.dialog ? '' : ' to your Downloads folder'}.` + (r.warning ? `<br>${esc(r.warning)}` : ''), r.warning ? undefined : 'ok');
      }
    } catch (e) {
      status(`Could not save the CSV: ${esc(e.message || e)}`, 'error');
    }
  }

  let lastBatch = null;  // {reports:[{token, filename, size, saved_to, kind}], source, note, can_open, folder}
  const APP = { docx: 'Word', xlsx: 'Excel' };

  async function generate(format) {
    const source = $('[data-ar=source]').value;
    const loc = $('[data-ar=location]').value.trim() || 'Sensor';
    const units = $('[data-ar=units]').value.trim();
    try { localStorage.setItem(LS_KEY, loc); } catch (e) { /* ignore */ }

    let csvBlob, csvName;
    if (source === 'file') {
      if (!savedCsvFile) { status('Choose a results CSV file first.', 'error'); return; }
      csvBlob = savedCsvFile; csvName = savedCsvFile.name;
    } else {
      const list = chosenRows();
      if (!list || !list.length) { status('Run an analysis first.', 'error'); return; }
      csvBlob = new Blob([rowsToCsv(list)], { type: 'text/csv' });
      csvName = `results_${safe(loc)}.csv`;
    }

    busy(true);
    lastBatch = null;
    $('[data-ar=ready]').innerHTML = '';
    $('[data-ar=ready]').style.display = 'none';
    const what = format === 'both' ? 'Word and Excel reports' : `${APP[format]} report`;
    status(`Generating the ${what}: computing facts, reading the reference document, asking OpenAI` +
           (format !== 'docx' ? ', drawing the charts' : '') + '. This can take up to a minute...');
    try {
      const fd = new FormData();
      fd.append('file', csvBlob, csvName);
      fd.append('location', loc);
      fd.append('units', units);
      fd.append('format', format);
      fd.append('include_data', $('[data-ar=incdata]').checked ? '1' : '0');
      const res = await fetch('/api/ai-report', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      if (!data.reports) data.reports = [{ token: data.token, filename: data.filename, size: data.size, saved_to: data.saved_to, kind: 'docx' }];
      lastBatch = data;
      showReady();
      if (data.can_open && $('[data-ar=autoopen]').checked) {
        for (const r of data.reports) await openReport(r, true);   // PC / .exe: open in Word / Excel right away
      }
    } catch (e) {
      console.error('AI report failed:', e);
      status(`Report not created: ${esc(e.message || e)}`, 'error');
    } finally {
      busy(false);
      updateSource();
    }
  }

  function showReady() {
    const b = lastBatch;
    const box = $('[data-ar=ready]');
    box.innerHTML = '';
    b.reports.forEach((r) => {
      const kb = Math.max(1, Math.round(r.size / 1024)).toLocaleString();
      const row = document.createElement('div');
      row.className = 'ar-ready-row';
      row.innerHTML = `
        <span class="ar-kind ar-kind-${r.kind}">${r.kind === 'xlsx' ? 'XLSX' : 'DOCX'}</span>
        <span class="ar-ready-name">${esc(r.filename)} <span class="muted">(${kb} KB)</span></span>
        <button type="button" class="ar-secondary" data-act="open">${b.can_open ? `Open in ${APP[r.kind]}` : 'Open (download)'}</button>
        <button type="button" data-act="saveas">Save as...</button>
        <button type="button" class="ar-secondary" data-act="download">Download</button>
        ${b.can_open && b.folder ? '<button type="button" class="ar-secondary" data-act="copy">Save copy to reports folder</button>' : ''}`;
      row.querySelector('[data-act=open]').onclick = () => openReport(r, false);
      row.querySelector('[data-act=saveas]').onclick = () => saveReportAs(r);
      row.querySelector('[data-act=download]').onclick = () => downloadReport(r);
      const cp = row.querySelector('[data-act=copy]');
      if (cp) cp.onclick = () => copyToFolder(r);
      box.appendChild(row);
    });
    if (b.can_open && b.folder) {
      const foot = document.createElement('div');
      foot.className = 'ar-ready-foot';
      foot.innerHTML = `<span class="muted">Reports folder: <code>${esc(b.folder)}</code></span>
        <button type="button" class="ar-secondary" data-act="folder">Open reports folder</button>`;
      foot.querySelector('[data-act=folder]').onclick = openFolder;
      box.appendChild(foot);
    }
    box.style.display = 'block';
    const n = b.reports.length;
    const parts = [`${n === 1 ? 'Report' : 'Reports'} ready. ` +
                   (b.can_open && $('[data-ar=autoopen]').checked ? `Opening ${n === 1 ? 'it' : 'them'}...` : 'Click Open to view.') +
                   ' Use <b>Save as...</b> to choose the folder and name, or <b>Download</b> to save to your Downloads.'];
    const saved = b.reports.filter((r) => r.saved_to).map((r) => `<code>${esc(r.saved_to)}</code>`);
    if (saved.length) parts.push(`Copy in the reports folder: ${saved.join(', ')}`);
    parts.push(b.source === 'openai' ? 'Wording by OpenAI, numbers computed by the app.' : 'Plain wording (AI not used).');
    if (b.note) parts.push(esc(b.note));
    status(parts.join('<br>'), b.source === 'openai' ? 'ok' : undefined);
  }

  async function fetchReportBlob(r) {
    const res = await fetch(`/api/ai-report/file/${r.token}`);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
      throw new Error(msg);
    }
    return res.blob();
  }

  async function openReport(r, auto) {
    try {
      if (lastBatch && lastBatch.can_open) {
        const res = await fetch(`/api/ai-report/open/${r.token}`, { method: 'POST' });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
        if (!auto) status(`Opened <b>${esc(r.filename)}</b> in ${APP[r.kind]}. Click <b>Save as...</b> to choose where to save it.`, 'ok');
      } else {
        download(await fetchReportBlob(r), r.filename);
        status(`Downloaded <b>${esc(r.filename)}</b> - open it from your Downloads. Click <b>Save as...</b> to save it somewhere else.`, 'ok');
      }
    } catch (e) {
      status(`Could not open the report: ${esc(e.message || e)}`, 'error');
    }
  }

  async function saveReportAs(r) {
    try {
      const res = await saveAs(r.filename, r.kind, async () => ({ blob: await fetchReportBlob(r), name: r.filename }));
      if (!res) { status('Save cancelled. The report is still ready - click Save as... again any time.'); return; }
      const kb = Math.max(1, Math.round(res.size / 1024)).toLocaleString();
      status(`Saved <b>${esc(res.name)}</b> (${kb} KB)${res.dialog ? '' : ' in your Downloads folder'}.` +
             (res.warning ? `<br>${esc(res.warning)}` : ''), res.warning ? undefined : 'ok');
    } catch (e) {
      status(`Report not saved: ${esc(e.message || e)}`, 'error');
    }
  }

  async function downloadReport(r) {
    try {
      download(await fetchReportBlob(r), r.filename);
      status(`Downloaded <b>${esc(r.filename)}</b> to your Downloads folder.`, 'ok');
    } catch (e) {
      status(`Download failed: ${esc(e.message || e)}`, 'error');
    }
  }

  async function copyToFolder(r) {
    try {
      const res = await fetch(`/api/ai-report/copy/${r.token}`, { method: 'POST' });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
      status(`Saved a copy: <code>${esc(d.saved_to)}</code>`, 'ok');
    } catch (e) {
      status(`Copy not saved: ${esc(e.message || e)}`, 'error');
    }
  }

  async function openFolder() {
    try {
      const res = await fetch('/api/ai-report/open-folder', { method: 'POST' });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    } catch (e) {
      status(`Could not open the folder: ${esc(e.message || e)}`, 'error');
    }
  }

  // ------------------------------------------------------------ UI
  function build() {
    root = document.createElement('div');
    root.className = 'ar-panel';
    root.id = 'aiReportPanel';
    root.innerHTML = `
      <h3 class="ar-title">AI report</h3>
      <p class="muted" style="margin-top:-6px">Save the results, or turn them into a Word report and/or an Excel workbook with findings, recommendations, charts and benchmarks.</p>
      <div class="controls ar-controls">
        <div><label for="arLocation">Location / sensor name</label><input type="text" id="arLocation" data-ar="location"></div>
        <div><label for="arUnits">Units</label><input type="text" id="arUnits" data-ar="units" placeholder="°F"></div>
        <div><label for="arSource">Results to use</label>
          <select id="arSource" data-ar="source">
            <option value="all">All results of this analysis</option>
            <option value="page">Current chart page only</option>
            <option value="file">A saved results CSV file...</option>
          </select></div>
      </div>
      <div class="ar-file" data-ar="filebox" style="display:none;margin:10px 0 0">
        <input type="file" accept=".csv" data-ar="file"> <span class="muted" data-ar="filename"></span>
      </div>
      <div class="row ar-buttons" style="margin-top:14px;gap:10px">
        <button type="button" data-ar="savecsv" class="ar-secondary">Save results CSV...</button>
        <button type="button" data-ar="generate">Generate AI report (Word)</button>
        <button type="button" data-ar="generatex">Generate AI report (Excel)</button>
        <button type="button" data-ar="generateb" class="ar-secondary">Generate both</button>
      </div>
      <div class="ar-options">
        <label><input type="checkbox" data-ar="incdata" checked> Excel: include all readings (Data tab)</label>
        <label data-ar="autoopenbox"><input type="checkbox" data-ar="autoopen" checked> Open the report when it is ready</label>
      </div>
      <div class="ar-ready" data-ar="ready" style="display:none"></div>
      <p class="muted" data-ar="cfg" style="margin:12px 0 0"></p>
      <p data-ar="msg" role="status" style="margin:8px 0 0;font-size:13.5px;line-height:1.5"></p>`;
    const st = document.createElement('style');
    st.textContent = `
      .ar-panel { margin: 22px 0 6px; padding: 16px 18px 14px; background: #fff; border: 1px solid #d5dbe1;
                  border-left: 4px solid #2f6fed; border-radius: 8px; }
      .ar-panel .ar-title { font-size: 17px; font-weight: 600; margin: 0 0 4px; }
      .ar-panel > p.muted { margin: 0 0 12px !important; }
      .ar-panel .ar-controls { display:grid; grid-template-columns: minmax(0,2fr) minmax(0,.6fr) minmax(0,1.4fr); gap:14px 18px; }
      .ar-panel .ar-controls input, .ar-panel .ar-controls select { width:100%; }
      .ar-panel button.ar-secondary { background:#fff; color:#1f2a33; border:1px solid #d5dbe1; }
      .ar-panel button.ar-secondary:hover { background:#e8f0fe; }
      .ar-panel .ar-options { display:flex; flex-wrap:wrap; gap:6px 22px; margin-top:10px; font-size:13px; color:#3a4753; }
      .ar-panel .ar-options label { display:inline-flex !important; align-items:center; gap:7px; font-weight:400; margin:0 !important; width:auto !important; white-space:nowrap; }
      .ar-panel .ar-options label[hidden] { display:none !important; }
      .ar-panel .ar-options input[type=checkbox] { width:auto !important; margin:0 !important; height:auto; }
      .ar-panel .ar-ready { margin-top:12px; padding:6px 12px; background:#f3f7ff; border:1px solid #c9d8f6; border-radius:6px; }
      .ar-panel .ar-ready-row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:6px 0; }
      .ar-panel .ar-ready-row + .ar-ready-row { border-top:1px solid #dbe5f7; }
      .ar-panel .ar-ready-name { font-weight:600; margin-right:auto; }
      .ar-panel .ar-ready-foot { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:8px 0 4px; border-top:1px solid #dbe5f7; }
      .ar-panel .ar-ready-foot .muted { margin-right:auto; }
      .ar-panel .ar-kind { font:600 10.5px/1 Arial; letter-spacing:.04em; color:#fff; padding:4px 6px; border-radius:4px; }
      .ar-panel .ar-kind-docx { background:#2a78d6; } .ar-panel .ar-kind-xlsx { background:#1d7a46; }
      .ar-panel code { font-size:12px; background:#f3f5f7; padding:1px 5px; border-radius:4px; }
      @media (max-width: 760px) { .ar-panel .ar-controls { grid-template-columns: 1fr; } }`;
    document.head.appendChild(st);

    placePanel();

    $('[data-ar=location]').value = defaultLocation();
    $('[data-ar=units]').value = unitsFromColumn();
    $('[data-ar=source]').onchange = updateSource;
    $('[data-ar=file]').onchange = (e) => {
      savedCsvFile = e.target.files && e.target.files[0] ? e.target.files[0] : null;
      $('[data-ar=filename]').textContent = savedCsvFile ? `${(savedCsvFile.size / 1024).toFixed(0)} KB` : '';
      updateSource();
    };
    $('[data-ar=savecsv]').onclick = saveCsv;
    $('[data-ar=generate]').onclick = () => generate('docx');
    $('[data-ar=generatex]').onclick = () => generate('xlsx');
    $('[data-ar=generateb]').onclick = () => generate('both');
    updateSource();
    loadStatus();
  }

  // Put the panel inside Results, just before the Data listing. The listing is
  // created by data_listing.js, possibly after this panel, so watch for it.
  function placePanel() {
    const listing = document.querySelector('.dl');
    if (listing && listing.parentNode) {
      if (root.nextElementSibling !== listing) listing.parentNode.insertBefore(root, listing);
      return true;
    }
    if (!root.isConnected) {
      const results = document.getElementById('resultsPanel');
      if (results) results.appendChild(root);
      else (document.querySelector('main') || document.body).appendChild(root);
    }
    if (!placePanel._watching) {
      placePanel._watching = true;
      const mo = new MutationObserver(() => {
        const l = document.querySelector('.dl');
        if (l && l.parentNode && root.nextElementSibling !== l) l.parentNode.insertBefore(root, l);
      });
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => mo.disconnect(), 15000);
    }
    return false;
  }

  function updateSource() {
    if (!root) return;
    const src = $('[data-ar=source]').value;
    $('[data-ar=filebox]').style.display = src === 'file' ? 'block' : 'none';
    $('[data-ar=savecsv]').style.display = src === 'file' ? 'none' : '';
    const pageOpt = $('[data-ar=source]').querySelector('option[value=page]');
    if (window.ChartExplorer && window.ChartExplorer.pageInfo) {
      const pi = window.ChartExplorer.pageInfo();
      pageOpt.textContent = `Current chart page only (page ${pi.page} of ${pi.pages})`;
    }
  }

  async function loadStatus() {
    try {
      const res = await fetch('/api/ai-report/status');
      if (!res.ok) return;
      const s = await res.json();
      $('[data-ar=autoopenbox]').hidden = !s.can_open;   // only the PC version can open Word / Excel
      const bits = [];
      bits.push(s.ai_configured ? `OpenAI: on (${esc(s.model)})` : 'OpenAI: off - add [openai] api_key to config.local.ini (plain wording is used meanwhile)');
      bits.push(s.reference_found ? `Reference: ${esc(s.reference_document)}` : 'Reference document: not found - set [reports] reference_document');
      if (s.saves_copy) bits.push(`Reports folder: <code>${esc(s.output_folder)}</code>`);
      if (!canPick) bits.push('Tip: use Edge or Chrome to get a Save As dialog');
      $('[data-ar=cfg]').innerHTML = bits.join(' &nbsp;|&nbsp; ');
    } catch (e) { /* status is optional */ }
  }

  // ------------------------------------------------------------ data in
  const originalFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    const p = originalFetch(url, opts);
    const u = typeof url === 'string' ? url : (url && url.url) || '';
    if (u.indexOf('/api/analyze') !== -1) {
      p.then((res) => {
        if (!res.ok) return;
        res.clone().json().then((d) => {
          if (!Array.isArray(d.rows) || !d.rows.length) return;
          rows = d.rows;
          setTimeout(() => {
            if (!root) build(); else placePanel();
            const unitsEl = $('[data-ar=units]');
            if (!unitsEl.value) unitsEl.value = unitsFromColumn();
            updateSource();
          }, 120);
        }).catch(() => {});
      }).catch(() => {});
    }
    return p;
  };
  // keep the "page N of M" label current when the chart page changes
  document.addEventListener('click', (e) => {
    if (root && e.target.closest && e.target.closest('.cx')) setTimeout(updateSource, 50);
  });
})();
