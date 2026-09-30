/*
 * data_listing.js - paginated, filterable data listing for the
 * Extreme & Change Analytics Lab.
 *
 * Loaded after app.js. Replaces the original results table after each
 * analysis with a listing that:
 *   - shows category columns from the file, such as Day/Night
 *   - filters by Day/Night (and any other category column) and by State
 *   - pages through the rows (fast even with 40,000+ readings)
 *   - summarises readings and extremes per Day/Night value
 *   - exports the filtered rows to CSV
 *   - jumps the chart to a reading when you click its row
 */
(function () {
  'use strict';
  if (window.__dataListingLoaded) return;
  window.__dataListingLoaded = true;

  const PAGE_SIZES = [50, 100, 250, 500];
  const EXTREME_STATES = new Set(['Extreme triggered', 'Extreme/elevated', 'Persistent', 'Confirmed/Materialized Shift']);
  const CAT_ICONS = { day: '\u2600', night: '\u263E' };

  const S = { rows: [], cats: [], filtered: [], page: 0, pageSize: 100, catFilter: {}, stateFilter: 'all' };
  let root, origWrap;

  const $q = (sel) => root.querySelector(sel);
  const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (v, d = 3) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? '' : Number(v).toFixed(d));
  const truthy = (v) => v === true || v === 'True' || v === 'true' || v === 1;
  const isExtreme = (r) => truthy(r.ExtremeFlag) || EXTREME_STATES.has(r.State);

  function badge(state) {
    if (!state) return '';
    const cls = state === 'Confirmed/Materialized Shift' ? 'badge-confirmed'
      : state === 'Persistent' ? 'badge-persistent'
      : (state === 'Extreme triggered' || state === 'Extreme/elevated') ? 'badge-extreme' : 'badge-normal';
    return `<span class="badge ${cls}">${esc(state)}</span>`;
  }
  function catPill(v) {
    if (!v) return '';
    const key = String(v).trim().toLowerCase();
    const icon = CAT_ICONS[key] || '';
    const cls = key === 'day' ? 'dl-day' : key === 'night' ? 'dl-night' : 'dl-cat';
    return `<span class="dl-pill ${cls}">${icon ? icon + ' ' : ''}${esc(v)}</span>`;
  }

  function injectStyles() {
    const st = document.createElement('style');
    st.textContent = `
      .dl { margin-top: 18px; }
      .dl h3 { font-size: 15px; margin: 0 0 10px; }
      .dl-bar { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin-bottom: 10px; font-size: 13px; }
      .dl-group { display: flex; align-items: center; gap: 6px; }
      .dl-lbl { color: #5b6b7c; }
      .dl select, .dl input { border: 1px solid #d7e0ea; border-radius: 7px; padding: 3px 6px; font-size: 13px; width: auto; min-width: 0; }
      .dl input[type=number] { width: 64px; }
      .dl input[type=text] { width: 150px; }
      .dl button { border: 1px solid #d7e0ea; background: #fff; color: #16232e; border-radius: 7px; padding: 4px 10px; font-size: 13px; cursor: pointer; width: auto; min-width: 0; margin: 0; }
      .dl button:hover { background: #eef3fb; }
      .dl button:disabled { opacity: .4; cursor: default; }
      .dl-seg { display: inline-flex; border: 1px solid #d7e0ea; border-radius: 8px; overflow: hidden; }
      .dl-seg button { border: none; border-radius: 0; border-right: 1px solid #d7e0ea; }
      .dl-seg button:last-child { border-right: none; }
      .dl-seg button.on { background: #2f6fed; color: #fff; }
      .dl-sum { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 10px; }
      .dl-card { border: 1px solid #d7e0ea; border-radius: 10px; padding: 8px 12px; font-size: 12px; color: #5b6b7c; background: #fff; min-width: 180px; }
      .dl-card b { color: #16232e; font-size: 13px; }
      .dl-wrap { overflow-x: auto; border: 1px solid #d7e0ea; border-radius: 10px; }
      .dl table { width: 100%; border-collapse: collapse; font-size: 13px; }
      .dl th { position: sticky; top: 0; background: #f4f7fb; text-align: left; font-weight: 600; color: #3b4a59; padding: 7px 10px; border-bottom: 1px solid #d7e0ea; white-space: nowrap; }
      .dl td { padding: 6px 10px; border-bottom: 1px solid #eef1f4; white-space: nowrap; }
      .dl tbody tr { cursor: pointer; }
      .dl tbody tr:hover { background: #f5f8fc; }
      .dl tbody tr.dl-x { background: #fff8ec; }
      .dl tbody tr.dl-x:hover { background: #fff1d9; }
      .dl td.num { text-align: right; font-variant-numeric: tabular-nums; }
      .dl-pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
      .dl-day { background: #fff4d6; color: #8a5a00; }
      .dl-night { background: #e4e8f7; color: #2c3a7a; }
      .dl-cat { background: #eef1f4; color: #4a5561; }
      .dl-foot { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px; font-size: 12px; color: #5b6b7c; margin-top: 8px; }
      .dl-empty { padding: 18px; text-align: center; color: #5b6b7c; }
      .dl-link { background: none !important; border: none !important; color: #2f6fed !important; padding: 0 !important; text-decoration: underline; }
    `;
    document.head.appendChild(st);
  }

  function buildUI() {
    injectStyles();
    root = document.createElement('div');
    root.className = 'dl';
    root.innerHTML = `
      <h3>Data listing</h3>
      <div class="dl-sum" data-dl="sum"></div>
      <div class="dl-bar">
        <span data-dl="catfilters" style="display:contents"></span>
        <div class="dl-group"><span class="dl-lbl">State</span><select data-dl="state"></select></div>
        <div class="dl-group"><span class="dl-lbl">Rows per page</span>
          <select data-dl="size">${PAGE_SIZES.map((n) => `<option value="${n}"${n === S.pageSize ? ' selected' : ''}>${n}</option>`).join('')}</select></div>
        <div class="dl-group">
          <button data-dl="first" title="First page">&#x23EE;</button>
          <button data-dl="prev" title="Previous page">&#x25C0;</button>
          <span class="dl-lbl">Page</span><input type="number" min="1" value="1" data-dl="page"><span class="dl-lbl" data-dl="total">of 1</span>
          <button data-dl="next" title="Next page">&#x25B6;</button>
          <button data-dl="last" title="Last page">&#x23ED;</button>
        </div>
        <div class="dl-group"><span class="dl-lbl">Go to date</span><input type="text" data-dl="find" placeholder="2026-01-15 08:00"><button data-dl="go">Go</button></div>
        <div class="dl-group"><button data-dl="csv" title="Save the filtered rows as CSV">Export filtered (CSV)</button></div>
      </div>
      <div class="dl-wrap"><table><thead data-dl="head"></thead><tbody data-dl="body"></tbody></table></div>
      <div class="dl-foot"><span data-dl="count"></span>
        <span>Click a row to show it on the chart. <button class="dl-link" data-dl="orig">Show original table</button></span></div>`;

    $q('[data-dl=size]').onchange = (e) => { S.pageSize = Number(e.target.value); S.page = 0; renderPage(); };
    $q('[data-dl=first]').onclick = () => goPage(0);
    $q('[data-dl=prev]').onclick = () => goPage(S.page - 1);
    $q('[data-dl=next]').onclick = () => goPage(S.page + 1);
    $q('[data-dl=last]').onclick = () => goPage(pageCount() - 1);
    $q('[data-dl=page]').onchange = (e) => goPage(Number(e.target.value) - 1);
    $q('[data-dl=state]').onchange = (e) => { S.stateFilter = e.target.value; applyFilters(); };
    $q('[data-dl=go]').onclick = findDate;
    $q('[data-dl=find]').onkeydown = (e) => { if (e.key === 'Enter') findDate(); };
    $q('[data-dl=csv]').onclick = exportCsv;
    $q('[data-dl=orig]').onclick = (e) => {
      if (!origWrap) return;
      const hidden = origWrap.style.display === 'none';
      origWrap.style.display = hidden ? '' : 'none';
      e.target.textContent = hidden ? 'Hide original table' : 'Show original table';
    };
    $q('[data-dl=body]').onclick = (e) => {
      const tr = e.target.closest('tr[data-i]');
      if (tr && window.ChartExplorer && window.ChartExplorer.goTo) window.ChartExplorer.goTo(Number(tr.dataset.i));
    };
  }

  function placeUI() {
    if (root.isConnected) return;
    const table = document.getElementById('resultsTable');
    if (table) {
      const wrap = table.closest('.table-wrap');
      origWrap = wrap || (table.parentElement && table.parentElement.children.length === 1 &&
        table.parentElement.id !== 'resultsPanel' ? table.parentElement : table);
      origWrap.parentElement.insertBefore(root, origWrap);
      origWrap.style.display = 'none';
    } else {
      (document.getElementById('resultsPanel') || document.querySelector('main') || document.body).appendChild(root);
      $q('[data-dl=orig]').style.display = 'none';
    }
  }

  // ------------------------------------------------------------ filters
  function buildFilters() {
    const host = $q('[data-dl=catfilters]');
    host.innerHTML = S.cats.map((c) => {
      const values = [...new Set(S.rows.map((r) => r[c]).filter((v) => v !== null && v !== undefined && v !== ''))].sort();
      const btns = ['All', ...values].map((v) =>
        `<button data-cat="${esc(c)}" data-val="${esc(v)}" class="${(S.catFilter[c] || 'All') === v ? 'on' : ''}">` +
        `${v === 'All' ? 'All' : (CAT_ICONS[String(v).toLowerCase()] ? CAT_ICONS[String(v).toLowerCase()] + ' ' : '') + esc(v)}</button>`).join('');
      return `<div class="dl-group"><span class="dl-lbl">${esc(c)}</span><span class="dl-seg">${btns}</span></div>`;
    }).join('');
    host.querySelectorAll('button[data-cat]').forEach((b) => {
      b.onclick = () => {
        S.catFilter[b.dataset.cat] = b.dataset.val;
        host.querySelectorAll(`button[data-cat="${CSS.escape(b.dataset.cat)}"]`).forEach((x) => x.classList.toggle('on', x === b));
        applyFilters();
      };
    });

    const states = [...new Set(S.rows.map((r) => r.State).filter(Boolean))];
    const order = ['Normal', 'Extreme triggered', 'Extreme/elevated', 'Persistent', 'Confirmed/Materialized Shift', 'Persistence ends'];
    states.sort((a, b) => (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99);
    const sel = $q('[data-dl=state]');
    sel.innerHTML = `<option value="all">All states</option><option value="extremes">Extremes only</option>` +
      states.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    sel.value = S.stateFilter;
    if (sel.value !== S.stateFilter) { S.stateFilter = 'all'; sel.value = 'all'; }
  }

  function applyFilters() {
    S.filtered = [];
    for (let i = 0; i < S.rows.length; i++) {
      const r = S.rows[i];
      let ok = true;
      for (const c of S.cats) {
        const f = S.catFilter[c];
        if (f && f !== 'All' && r[c] !== f) { ok = false; break; }
      }
      if (ok && S.stateFilter === 'extremes') ok = isExtreme(r);
      else if (ok && S.stateFilter !== 'all') ok = r.State === S.stateFilter;
      if (ok) S.filtered.push(i);
    }
    S.page = 0;
    renderSummary();
    renderPage();
  }

  // ------------------------------------------------------------ render
  function columns() {
    const have = (k) => S.rows.length && k in S.rows[0];
    const cols = [['Timestamp', 'Timestamp', (r) => esc(String(r.Timestamp ?? '').replace('T', ' ')), '']];
    S.cats.forEach((c) => cols.push([c, c, (r) => catPill(r[c]), '']));
    cols.push(['Value', 'Value', (r) => fmt(r.Value), 'num']);
    if (have('ZScore')) cols.push(['ZScore', 'Z', (r) => fmt(r.ZScore), 'num']);
    if (have('State')) cols.push(['State', 'State', (r) => badge(r.State), '']);
    if (have('PersistenceCount')) cols.push(['PersistenceCount', 'Persistence', (r) => esc(r.PersistenceCount ?? ''), 'num']);
    if (have('ExtremeFlag')) cols.push(['ExtremeFlag', 'Extreme', (r) => (truthy(r.ExtremeFlag) ? 'Yes' : ''), '']);
    if (have('AbnormalChangeFlag')) cols.push(['AbnormalChangeFlag', 'Abnormal change', (r) => (truthy(r.AbnormalChangeFlag) ? 'Yes' : ''), '']);
    if (have('MaterialityScore')) cols.push(['MaterialityScore', 'Materiality', (r) => fmt(r.MaterialityScore), 'num']);
    return cols;
  }

  const pageCount = () => Math.max(1, Math.ceil(S.filtered.length / S.pageSize));
  function goPage(p) { S.page = Math.min(Math.max(0, p || 0), pageCount() - 1); renderPage(); }

  function renderPage() {
    const cols = columns();
    $q('[data-dl=head]').innerHTML = `<tr>${cols.map(([, label, , cls]) => `<th class="${cls}">${esc(label)}</th>`).join('')}</tr>`;
    const start = S.page * S.pageSize;
    const idx = S.filtered.slice(start, start + S.pageSize);
    $q('[data-dl=body]').innerHTML = idx.length
      ? idx.map((i) => {
          const r = S.rows[i];
          return `<tr data-i="${i}" class="${isExtreme(r) ? 'dl-x' : ''}">` +
            cols.map(([, , cell, cls]) => `<td class="${cls}">${cell(r)}</td>`).join('') + '</tr>';
        }).join('')
      : `<tr><td class="dl-empty" colspan="${cols.length}">No rows match these filters.</td></tr>`;

    const n = pageCount();
    $q('[data-dl=page]').value = S.page + 1;
    $q('[data-dl=page]').max = n;
    $q('[data-dl=total]').textContent = `of ${n.toLocaleString()}`;
    $q('[data-dl=first]').disabled = $q('[data-dl=prev]').disabled = S.page <= 0;
    $q('[data-dl=next]').disabled = $q('[data-dl=last]').disabled = S.page >= n - 1;
    const a = idx.length ? start + 1 : 0;
    const b = start + idx.length;
    const filteredNote = S.filtered.length === S.rows.length ? '' : ` (filtered from ${S.rows.length.toLocaleString()})`;
    $q('[data-dl=count]').textContent = `Showing ${a.toLocaleString()}-${b.toLocaleString()} of ${S.filtered.length.toLocaleString()} rows${filteredNote}`;
  }

  function renderSummary() {
    const host = $q('[data-dl=sum]');
    if (!S.cats.length) { host.innerHTML = ''; return; }
    const c = S.cats[0];
    const groups = {};
    for (const r of S.rows) {
      const k = r[c] || '(blank)';
      const g = groups[k] || (groups[k] = { n: 0, x: 0, sum: 0, cnt: 0, min: Infinity, max: -Infinity });
      g.n++;
      if (isExtreme(r)) g.x++;
      const v = Number(r.Value);
      if (r.Value !== null && !Number.isNaN(v)) { g.sum += v; g.cnt++; if (v < g.min) g.min = v; if (v > g.max) g.max = v; }
    }
    host.innerHTML = Object.entries(groups).sort().map(([k, g]) =>
      `<div class="dl-card">${catPill(k)}<br><b>${g.n.toLocaleString()}</b> readings, <b>${g.x.toLocaleString()}</b> extreme ` +
      `(${g.n ? ((g.x / g.n) * 100).toFixed(1) : '0.0'}%)<br>avg ${g.cnt ? (g.sum / g.cnt).toFixed(2) : '-'}, ` +
      `range ${g.cnt ? g.min.toFixed(2) : '-'} to ${g.cnt ? g.max.toFixed(2) : '-'}</div>`).join('');
  }

  function findDate() {
    const q = $q('[data-dl=find]').value.trim().replace('T', ' ');
    if (!q) return;
    const pos = S.filtered.findIndex((i) => String(S.rows[i].Timestamp ?? '').replace('T', ' ') >= q);
    if (pos < 0) { $q('[data-dl=count]').textContent = `No filtered rows at or after ${q}.`; return; }
    S.page = Math.floor(pos / S.pageSize);
    renderPage();
    const tr = $q(`tr[data-i="${S.filtered[pos]}"]`);
    if (tr) { tr.style.outline = '2px solid #2f6fed'; tr.scrollIntoView({ block: 'center' }); }
  }

  function exportCsv() {
    if (!S.filtered.length) return;
    const first = S.rows[0];
    const keys = Object.keys(first);
    const lead = ['Timestamp', ...S.cats, 'Value'];
    const cols = lead.filter((k) => keys.includes(k)).concat(keys.filter((k) => !lead.includes(k)));
    const cell = (v) => {
      if (v === null || v === undefined) return '';
      const t = String(v);
      return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    const lines = [cols.join(',')].concat(S.filtered.map((i) => cols.map((k) => cell(S.rows[i][k])).join(',')));
    const tag = S.cats.map((c) => S.catFilter[c] && S.catFilter[c] !== 'All' ? S.catFilter[c] : '').filter(Boolean).join('_');
    const stateTag = S.stateFilter === 'all' ? '' : S.stateFilter === 'extremes' ? 'extremes' : S.stateFilter;
    const name = ['extreme_listing', tag, stateTag].filter(Boolean).join('_').replace(/[^A-Za-z0-9._-]+/g, '_') + '.csv';
    const url = URL.createObjectURL(new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  // ------------------------------------------------------------ data in
  function detectCats(rows, declared) {
    if (Array.isArray(declared) && declared.length) return declared.filter((c) => c in rows[0]);
    const known = new Set(['Timestamp', 'State', 'ExtremeDirection', 'EventStartTime', 'EventEndTime']);
    return Object.keys(rows[0]).filter((k) => {
      if (known.has(k) || typeof rows[0][k] !== 'string') return false;
      const vals = new Set();
      for (let i = 0; i < rows.length && vals.size <= 12; i += Math.max(1, Math.floor(rows.length / 2000))) vals.add(rows[i][k]);
      return vals.size >= 2 && vals.size <= 12;
    });
  }

  function load(data) {
    const rows = Array.isArray(data.rows) ? data.rows : null;
    if (!rows || !rows.length || typeof rows[0] !== 'object') return;
    if (!root) buildUI();
    placeUI();
    S.rows = rows;
    S.cats = detectCats(rows, data.category_columns);
    S.cats.forEach((c) => { if (!(c in S.catFilter)) S.catFilter[c] = 'All'; });
    buildFilters();
    applyFilters();
  }

  window.DataListing = { load };

  const originalFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    const p = originalFetch(url, opts);
    const u = typeof url === 'string' ? url : (url && url.url) || '';
    if (u.indexOf('/api/analyze') !== -1) {
      p.then((res) => {
        if (!res.ok) return;
        res.clone().json().then((d) => setTimeout(() => load(d), 80)).catch(() => {});
      }).catch(() => {});
    }
    return p;
  };
})();
