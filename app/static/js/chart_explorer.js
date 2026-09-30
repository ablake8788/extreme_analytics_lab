/*
 * chart_explorer.js - scrollable, paginated, stretchable chart for the
 * Extreme & Change Analytics Lab.
 *
 * Loaded after app.js. It listens for /api/analyze responses, hides the
 * original chart and shows this explorer in its place. No other file needs
 * to call it. Draws on a plain <canvas>, so it works offline inside the .exe.
 */
(function () {
  'use strict';
  if (window.__chartExplorerLoaded) return;
  window.__chartExplorerLoaded = true;

  // ---------------------------------------------------------------- config
  const COLORS = {
    value: '#2f6fed',
    ma: '#16a34a',
    limit: '#94a3b8',
    band: 'rgba(47, 111, 237, 0.08)',
    grid: '#e8edf3',
    axis: '#5b6b7c',
    cross: 'rgba(22, 35, 46, 0.35)',
  };
  const STATE_COLORS = {
    'Extreme triggered': '#f59e0b',
    'Extreme/elevated': '#f97316',
    'Persistent': '#ef4444',
    'Confirmed/Materialized Shift': '#7c3aed',
    'Persistence ends': '#64748b',
  };
  const PAGE_SIZES = [500, 1000, 2000, 5000, 10000, 0]; // 0 = All
  const ZOOM_LEVELS = [0.1, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32];
  const HEIGHTS = { Small: 280, Medium: 380, Large: 520, 'Extra large': 700 };
  const MAX_CANVAS_PX = 30000;
  const AXIS_W = 64;
  const PAD_TOP = 12;
  const PAD_BOTTOM = 30;

  const S = {
    rows: [],
    page: 0,
    pageSize: 2000,
    px: 0, // 0 = fit to window
    height: 380,
    show: { value: true, ma: true, limits: true, extremes: true },
    layout: null, // last drawn geometry
  };

  let root, plot, axis, scroller, inner, tip, cross, pageInput, pageTotal, rangeLabel,
      zoomLabel, capNote, origWrap;

  // ---------------------------------------------------------------- helpers
  const num = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v));
  const isExtreme = (r) => r.ExtremeFlag === true || r.ExtremeFlag === 'True' || r.ExtremeFlag === 1 ||
    (r.State && r.State !== 'Normal' && STATE_COLORS[r.State] && r.State !== 'Persistence ends');
  const pageCount = () => (S.pageSize ? Math.max(1, Math.ceil(S.rows.length / S.pageSize)) : 1);
  const pageStart = () => (S.pageSize ? S.page * S.pageSize : 0);
  const pageRows = () => (S.pageSize ? S.rows.slice(pageStart(), pageStart() + S.pageSize) : S.rows);

  function fmtTime(t, long) {
    if (t === null || t === undefined) return '';
    const s = String(t).replace('T', ' ');
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return long ? s.slice(0, 19) : s.slice(5, 16);
    return s;
  }
  function fmtNum(v) {
    if (v === null) return '-';
    const a = Math.abs(v);
    return a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(2) : v.toFixed(3);
  }
  function niceTicks(min, max, count) {
    const span = max - min || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
    const ticks = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  // ---------------------------------------------------------------- UI
  function injectStyles() {
    const css = `
      .cx { margin: 8px 0 16px; }
      .cx-bar { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin-bottom: 10px; font-size: 13px; }
      .cx-group { display: flex; align-items: center; gap: 6px; }
      .cx-group > span.cx-lbl { color: #5b6b7c; }
      .cx button { border: 1px solid #d7e0ea; background: #fff; color: #16232e; border-radius: 7px; padding: 4px 10px; font-size: 13px; cursor: pointer; min-width: 0; width: auto; }
      .cx button:hover { background: #eef3fb; }
      .cx button:disabled { opacity: .4; cursor: default; }
      .cx button.cx-accent { background: #2f6fed; border-color: #2f6fed; color: #fff; }
      .cx select, .cx input[type=number] { border: 1px solid #d7e0ea; border-radius: 7px; padding: 3px 6px; font-size: 13px; width: auto; min-width: 0; }
      .cx input[type=number] { width: 64px; }
      .cx label.cx-chk { display: inline-flex; align-items: center; gap: 4px; margin: 0; font-size: 13px; color: #16232e; cursor: pointer; }
      .cx label.cx-chk input { width: auto; margin: 0; }
      .cx-sw { display: inline-block; width: 12px; height: 3px; border-radius: 2px; }
      .cx-frame { position: relative; display: flex; border: 1px solid #d7e0ea; border-radius: 10px; background: #fff; overflow: hidden; }
      .cx-axis { flex: 0 0 ${AXIS_W}px; width: ${AXIS_W}px; min-width: ${AXIS_W}px; border-right: 1px solid #eef1f4; }
      .cx-scroll { position: relative; flex: 1 1 auto; min-width: 0; overflow-x: auto; overflow-y: hidden; cursor: grab; }
      .cx-scroll.cx-drag { cursor: grabbing; }
      .cx-inner { position: relative; }
      .cx-cross { position: absolute; top: 0; width: 1px; background: ${COLORS.cross}; pointer-events: none; display: none; }
      .cx-tip { position: absolute; z-index: 5; pointer-events: none; display: none; background: #16232e; color: #fff; font-size: 12px; line-height: 1.45; border-radius: 8px; padding: 7px 10px; white-space: nowrap; box-shadow: 0 6px 18px rgba(0,0,0,.18); }
      .cx-tip b { font-weight: 600; }
      .cx-foot { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px; font-size: 12px; color: #5b6b7c; margin-top: 6px; }
      .cx-legend { display: flex; flex-wrap: wrap; gap: 12px; }
      .cx-legend span { display: inline-flex; align-items: center; gap: 5px; }
      .cx-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
      .cx-link { background: none !important; border: none !important; color: #2f6fed !important; padding: 0 !important; text-decoration: underline; }
    `;
    const st = document.createElement('style');
    st.textContent = css;
    document.head.appendChild(st);
  }

  function buildUI() {
    injectStyles();
    root = document.createElement('div');
    root.className = 'cx';
    const pageOpts = PAGE_SIZES.map((n) => `<option value="${n}"${n === S.pageSize ? ' selected' : ''}>${n ? n.toLocaleString() : 'All'}</option>`).join('');
    const hOpts = Object.entries(HEIGHTS).map(([k, v]) => `<option value="${v}"${v === S.height ? ' selected' : ''}>${k}</option>`).join('');
    root.innerHTML = `
      <div class="cx-bar">
        <div class="cx-group"><span class="cx-lbl">Points per page</span><select data-cx="size">${pageOpts}</select></div>
        <div class="cx-group">
          <button data-cx="first" title="First page">&#x23EE;</button>
          <button data-cx="prev" title="Previous page">&#x25C0;</button>
          <span class="cx-lbl">Page</span><input type="number" min="1" value="1" data-cx="page"><span class="cx-lbl" data-cx="total">of 1</span>
          <button data-cx="next" title="Next page">&#x25B6;</button>
          <button data-cx="last" title="Last page">&#x23ED;</button>
        </div>
        <div class="cx-group">
          <span class="cx-lbl">Stretch</span>
          <button data-cx="zout" title="Squeeze">&minus;</button>
          <button data-cx="fit" title="Fit the page to the window">Fit</button>
          <button data-cx="zin" title="Stretch">+</button>
          <span class="cx-lbl" data-cx="zoom">Fit</span>
        </div>
        <div class="cx-group"><span class="cx-lbl">Height</span><select data-cx="height">${hOpts}</select></div>
        <div class="cx-group">
          <label class="cx-chk"><input type="checkbox" data-show="value" checked><span class="cx-sw" style="background:${COLORS.value}"></span>Value</label>
          <label class="cx-chk"><input type="checkbox" data-show="ma" checked><span class="cx-sw" style="background:${COLORS.ma}"></span>Moving avg</label>
          <label class="cx-chk"><input type="checkbox" data-show="limits" checked><span class="cx-sw" style="background:${COLORS.limit}"></span>Limits</label>
          <label class="cx-chk"><input type="checkbox" data-show="extremes" checked><span class="cx-dot" style="background:#ef4444"></span>Extremes</label>
        </div>
        <div class="cx-group">
          <button data-cx="prevx" title="Previous extreme reading">&#x25C0; Extreme</button>
          <button data-cx="nextx" class="cx-accent" title="Next extreme reading">Extreme &#x25B6;</button>
        </div>
        <div class="cx-group">
          <span class="cx-lbl">Save</span>
          <button data-cx="saveview" title="Save what is on screen now as a PNG image">View (PNG)</button>
          <button data-cx="savepage" title="Save the whole current page, including the part scrolled off screen, as a PNG image">Full page (PNG)</button>
          <button data-cx="savecsv" title="Save the readings on the current page as a CSV file">Data (CSV)</button>
        </div>
      </div>
      <div class="cx-frame">
        <canvas class="cx-axis"></canvas>
        <div class="cx-scroll"><div class="cx-inner"><canvas></canvas><div class="cx-cross"></div></div></div>
        <div class="cx-tip"></div>
      </div>
      <div class="cx-foot">
        <span data-cx="range"></span>
        <span class="cx-legend">
          ${Object.entries(STATE_COLORS).filter(([k]) => k !== 'Persistence ends')
            .map(([k, c]) => `<span><i class="cx-dot" style="background:${c}"></i>${k}</span>`).join('')}
        </span>
        <span><span data-cx="cap"></span> <button class="cx-link" data-cx="orig">Show original chart</button></span>
      </div>`;

    const q = (sel) => root.querySelector(sel);
    axis = q('.cx-axis');
    scroller = q('.cx-scroll');
    inner = q('.cx-inner');
    plot = inner.querySelector('canvas');
    cross = q('.cx-cross');
    tip = q('.cx-tip');
    pageInput = q('[data-cx=page]');
    pageTotal = q('[data-cx=total]');
    rangeLabel = q('[data-cx=range]');
    zoomLabel = q('[data-cx=zoom]');
    capNote = q('[data-cx=cap]');

    q('[data-cx=size]').onchange = (e) => {
      const first = pageStart();
      S.pageSize = Number(e.target.value);
      S.page = S.pageSize ? Math.floor(first / S.pageSize) : 0;
      render(true);
    };
    q('[data-cx=first]').onclick = () => goPage(0);
    q('[data-cx=prev]').onclick = () => goPage(S.page - 1);
    q('[data-cx=next]').onclick = () => goPage(S.page + 1);
    q('[data-cx=last]').onclick = () => goPage(pageCount() - 1);
    pageInput.onchange = () => goPage(Number(pageInput.value) - 1);
    q('[data-cx=zin]').onclick = () => zoomStep(+1);
    q('[data-cx=zout]').onclick = () => zoomStep(-1);
    q('[data-cx=fit]').onclick = () => setZoom(0);
    q('[data-cx=height]').onchange = (e) => { S.height = Number(e.target.value); render(false); };
    root.querySelectorAll('[data-show]').forEach((cb) => {
      cb.onchange = () => { S.show[cb.dataset.show] = cb.checked; render(false); };
    });
    q('[data-cx=saveview]').onclick = () => saveImage(false);
    q('[data-cx=savepage]').onclick = () => saveImage(true);
    q('[data-cx=savecsv]').onclick = saveCsv;
    q('[data-cx=nextx]').onclick = () => jumpExtreme(+1);
    q('[data-cx=prevx]').onclick = () => jumpExtreme(-1);
    q('[data-cx=orig]').onclick = (e) => {
      if (!origWrap) return;
      const hidden = origWrap.style.display === 'none';
      origWrap.style.display = hidden ? '' : 'none';
      e.target.textContent = hidden ? 'Hide original chart' : 'Show original chart';
    };

    wireInteractions();
    window.addEventListener('resize', () => { if (S.rows.length) render(false); });
  }

  function placeUI() {
    if (root.isConnected) return;
    // Put the explorer where the original chart is, and hide the original.
    const canvases = Array.from(document.querySelectorAll('canvas')).filter((c) => !root.contains(c));
    const orig = canvases.find((c) => c.offsetParent !== null) || canvases[0];
    if (orig) {
      // Hide only the old chart: its wrapper if the wrapper holds nothing else,
      // otherwise the canvas itself (e.g. canvas placed directly in the panel).
      const parent = orig.parentElement;
      origWrap = parent && parent.children.length === 1 && parent.id !== 'resultsPanel' &&
        parent.tagName !== 'SECTION' && parent.tagName !== 'MAIN' && parent !== document.body ? parent : orig;
      origWrap.parentElement.insertBefore(root, origWrap);
      origWrap.style.display = 'none';
    } else {
      const host = document.getElementById('resultsPanel') || document.querySelector('main') || document.body;
      host.appendChild(root);
      root.querySelector('[data-cx=orig]').style.display = 'none';
    }
  }

  // ---------------------------------------------------------------- navigation
  function goPage(p) {
    const n = pageCount();
    S.page = Math.min(Math.max(0, p || 0), n - 1);
    render(true);
  }
  function currentFitPx() {
    const n = Math.max(pageRows().length, 1);
    return Math.max(scroller.clientWidth, 200) / n;
  }
  function setZoom(px, anchorX) {
    const oldW = inner.offsetWidth || 1;
    const ax = anchorX === undefined ? scroller.clientWidth / 2 : anchorX;
    const ratio = (scroller.scrollLeft + ax) / oldW;
    S.px = px;
    render(false);
    scroller.scrollLeft = ratio * inner.offsetWidth - ax;
  }
  function zoomStep(dir, anchorX) {
    const cur = S.px || currentFitPx();
    let next;
    if (dir > 0) next = ZOOM_LEVELS.find((z) => z > cur * 1.01);
    else next = [...ZOOM_LEVELS].reverse().find((z) => z < cur * 0.99);
    if (next === undefined) return;
    if (dir < 0 && next <= currentFitPx()) next = 0; // back to fit
    setZoom(next, anchorX);
  }
  function jumpExtreme(dir) {
    if (!S.rows.length) return;
    const L = S.layout;
    const centerLocal = L ? Math.floor((scroller.scrollLeft + scroller.clientWidth / 2) / L.px) : 0;
    const from = pageStart() + centerLocal;
    let i = from + dir;
    while (i >= 0 && i < S.rows.length && !isExtreme(S.rows[i])) i += dir;
    if (i < 0 || i >= S.rows.length) {
      flash(dir > 0 ? 'No more extreme readings after this point.' : 'No extreme readings before this point.');
      return;
    }
    // skip to the start of the next separate event, not the next row of the same event
    if (dir > 0 && i === from + 1) {
      while (i < S.rows.length && isExtreme(S.rows[i])) i++;
      while (i < S.rows.length && !isExtreme(S.rows[i])) i++;
      if (i >= S.rows.length) { flash('No more extreme readings after this point.'); return; }
    }
    goToIndex(i);
  }
  function goToIndex(i) {
    if (!S.rows.length || i < 0 || i >= S.rows.length) return;
    if (S.pageSize) S.page = Math.floor(i / S.pageSize);
    if (!S.px) S.px = 4;
    render(true);
    const local = i - pageStart();
    scroller.scrollLeft = local * S.layout.px - scroller.clientWidth / 2;
    showTipAt(local);
  }
  function flash(msg) {
    const prev = rangeLabel.textContent;
    rangeLabel.textContent = msg;
    rangeLabel.style.color = '#b45309';
    setTimeout(() => { rangeLabel.style.color = ''; updateRangeLabel(); }, 2200);
    return prev;
  }

  // ---------------------------------------------------------------- mouse
  function wireInteractions() {
    let drag = null;
    scroller.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, left: scroller.scrollLeft, moved: false };
      scroller.classList.add('cx-drag');
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      if (Math.abs(dx) > 3) drag.moved = true;
      scroller.scrollLeft = drag.left - dx;
    });
    window.addEventListener('mouseup', () => { drag = null; scroller.classList.remove('cx-drag'); });

    scroller.addEventListener('wheel', (e) => {
      if (!e.ctrlKey) return; // plain wheel / shift+wheel scroll as normal
      e.preventDefault();
      const rect = scroller.getBoundingClientRect();
      zoomStep(e.deltaY < 0 ? +1 : -1, e.clientX - rect.left);
    }, { passive: false });

    plot.addEventListener('mousemove', (e) => {
      if (!S.layout) return;
      const i = Math.floor(e.offsetX / S.layout.px);
      showTipAt(i);
    });
    plot.addEventListener('mouseleave', hideTip);
    scroller.addEventListener('scroll', hideTip);
  }

  function showTipAt(i) {
    const L = S.layout;
    if (!L || i < 0 || i >= L.data.length) { hideTip(); return; }
    const r = L.data[i];
    const x = L.x(i);
    cross.style.display = 'block';
    cross.style.left = `${x}px`;
    cross.style.height = `${L.h}px`;
    const rows = [
      `<b>${fmtTime(r.Timestamp, true)}</b>`,
      `Value: <b>${fmtNum(num(r.Value))}</b>`,
    ];
    if (num(r.MovingAverage) !== null) rows.push(`Moving avg: ${fmtNum(num(r.MovingAverage))}`);
    if (num(r.UpperLimit) !== null) rows.push(`Limits: ${fmtNum(num(r.LowerLimit))} to ${fmtNum(num(r.UpperLimit))}`);
    if (num(r.ZScore) !== null) rows.push(`Z-score: ${fmtNum(num(r.ZScore))}`);
    if (r.State) rows.push(`State: <b style="color:${STATE_COLORS[r.State] || '#9fd0ff'}">${r.State}</b>`);
    rows.push(`<span style="opacity:.7">Row ${(pageStart() + i + 1).toLocaleString()} of ${S.rows.length.toLocaleString()}</span>`);
    tip.innerHTML = rows.join('<br>');
    tip.style.display = 'block';
    const frame = root.querySelector('.cx-frame');
    const screenX = AXIS_W + x - scroller.scrollLeft;
    const tw = tip.offsetWidth;
    let left = screenX + 14;
    if (left + tw > frame.clientWidth - 6) left = screenX - tw - 14;
    tip.style.left = `${Math.max(4, left)}px`;
    tip.style.top = `${PAD_TOP + 4}px`;
  }
  function hideTip() {
    tip.style.display = 'none';
    cross.style.display = 'none';
  }

  // ---------------------------------------------------------------- drawing
  function updateRangeLabel() {
    const data = pageRows();
    if (!data.length) { rangeLabel.textContent = ''; return; }
    const a = pageStart() + 1;
    const b = pageStart() + data.length;
    rangeLabel.textContent = `Rows ${a.toLocaleString()}-${b.toLocaleString()} of ${S.rows.length.toLocaleString()}  |  ` +
      `${fmtTime(data[0].Timestamp, true)} to ${fmtTime(data[data.length - 1].Timestamp, true)}`;
  }

  function render(resetScroll) {
    if (!root) return;
    hideTip();
    const n = pageCount();
    pageInput.max = n;
    pageInput.value = S.page + 1;
    pageTotal.textContent = `of ${n.toLocaleString()}`;
    root.querySelector('[data-cx=first]').disabled = root.querySelector('[data-cx=prev]').disabled = S.page <= 0;
    root.querySelector('[data-cx=next]').disabled = root.querySelector('[data-cx=last]').disabled = S.page >= n - 1;
    updateRangeLabel();
    draw();
    if (resetScroll) scroller.scrollLeft = 0;
  }

  function draw() {
    const data = pageRows();
    const count = Math.max(data.length, 1);
    const H = S.height;
    inner.style.width = '1px'; // let the scroller take its natural width before measuring
    const viewW = Math.max(scroller.clientWidth, 200);

    let px = S.px || viewW / count;
    let width = Math.max(viewW, Math.ceil(count * px));
    capNote.textContent = '';
    if (width > MAX_CANVAS_PX) {
      width = MAX_CANVAS_PX;
      px = width / count;
      capNote.textContent = 'Stretch limited by browser - use fewer points per page to stretch more.';
    }
    zoomLabel.textContent = S.px ? `${+px.toFixed(2)} px per point` : `Fit (${+px.toFixed(2)} px per point)`;

    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 32000 / width));
    for (const [c, w] of [[plot, width], [axis, AXIS_W]]) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(H * dpr);
      c.style.width = `${w}px`;
      c.style.height = `${H}px`;
    }
    inner.style.width = `${width}px`;
    inner.style.height = `${H}px`;

    // y range from what is shown
    let lo = Infinity, hi = -Infinity;
    const take = (v) => { if (v !== null) { if (v < lo) lo = v; if (v > hi) hi = v; } };
    for (const r of data) {
      if (S.show.value || S.show.extremes) take(num(r.Value));
      if (S.show.ma) take(num(r.MovingAverage));
      if (S.show.limits) { take(num(r.UpperLimit)); take(num(r.LowerLimit)); }
    }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= 1; hi += 1; }
    const padY = (hi - lo) * 0.06;
    lo -= padY; hi += padY;

    const plotH = H - PAD_TOP - PAD_BOTTOM;
    const y = (v) => PAD_TOP + (1 - (v - lo) / (hi - lo)) * plotH;
    const x = (i) => i * px + px / 2;
    S.layout = { data, px, x, y, h: H };

    const g = plot.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, H);
    const a = axis.getContext('2d');
    a.setTransform(dpr, 0, 0, dpr, 0, 0);
    a.clearRect(0, 0, AXIS_W, H);

    // grid + y labels
    const ticks = niceTicks(lo, hi, Math.max(3, Math.round(plotH / 55)));
    g.strokeStyle = COLORS.grid; g.lineWidth = 1;
    a.fillStyle = COLORS.axis; a.font = '11px "Segoe UI", Arial, sans-serif';
    a.textAlign = 'right'; a.textBaseline = 'middle';
    for (const t of ticks) {
      const yy = Math.round(y(t)) + 0.5;
      g.beginPath(); g.moveTo(0, yy); g.lineTo(width, yy); g.stroke();
      a.fillText(fmtNum(t), AXIS_W - 8, yy);
    }

    // x labels
    const stepIdx = Math.max(1, Math.ceil(120 / px));
    g.fillStyle = COLORS.axis; g.font = '11px "Segoe UI", Arial, sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'top';
    for (let i = 0; i < data.length; i += stepIdx) {
      const xx = Math.round(x(i)) + 0.5;
      g.strokeStyle = COLORS.grid;
      g.beginPath(); g.moveTo(xx, PAD_TOP); g.lineTo(xx, PAD_TOP + plotH); g.stroke();
      const label = fmtTime(data[i].Timestamp, false) || String(pageStart() + i + 1);
      const tx = Math.min(Math.max(xx, 34), width - 34);
      g.fillText(label, tx, PAD_TOP + plotH + 8);
    }

    // band between limits
    if (S.show.limits) {
      g.fillStyle = COLORS.band;
      let seg = [];
      const flush = () => {
        if (seg.length > 1) {
          g.beginPath();
          seg.forEach(([i, up], k) => (k ? g.lineTo(x(i), y(up)) : g.moveTo(x(i), y(up))));
          for (let k = seg.length - 1; k >= 0; k--) g.lineTo(x(seg[k][0]), y(seg[k][2]));
          g.closePath(); g.fill();
        }
        seg = [];
      };
      data.forEach((r, i) => {
        const up = num(r.UpperLimit), dn = num(r.LowerLimit);
        if (up === null || dn === null) flush(); else seg.push([i, up, dn]);
      });
      flush();
      line(g, data, 'UpperLimit', COLORS.limit, 1, [4, 3], x, y);
      line(g, data, 'LowerLimit', COLORS.limit, 1, [4, 3], x, y);
    }
    if (S.show.ma) line(g, data, 'MovingAverage', COLORS.ma, 1.4, [], x, y);
    if (S.show.value) line(g, data, 'Value', COLORS.value, px < 1 ? 1 : 1.6, [], x, y);

    // extreme markers
    if (S.show.extremes) {
      const r0 = px >= 6 ? 4 : px >= 2 ? 3 : 2.2;
      data.forEach((r, i) => {
        if (!isExtreme(r)) return;
        const v = num(r.Value);
        if (v === null) return;
        g.fillStyle = STATE_COLORS[r.State] || '#ef4444';
        g.beginPath(); g.arc(x(i), y(v), r0, 0, Math.PI * 2); g.fill();
      });
    }
  }

  function line(g, data, key, color, w, dash, x, y) {
    g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash); g.lineJoin = 'round';
    g.beginPath();
    let pen = false;
    data.forEach((r, i) => {
      const v = num(r[key]);
      if (v === null) { pen = false; return; }
      if (pen) g.lineTo(x(i), y(v)); else { g.moveTo(x(i), y(v)); pen = true; }
    });
    g.stroke(); g.setLineDash([]);
  }

  // ---------------------------------------------------------------- save
  function seriesName() {
    const sel = document.getElementById('valueColumn');
    const txt = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : '';
    return txt || 'Value';
  }
  function safe(s) {
    return String(s).replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60);
  }
  function stamp(t) {
    return String(t || '').replace('T', ' ').slice(0, 16).replace(/[-: ]/g, '').replace(/^(\d{8})(\d{4})$/, '$1-$2');
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function visibleIndexRange(full) {
    const L = S.layout;
    if (full) return [0, L.data.length - 1];
    const a = Math.max(0, Math.floor(scroller.scrollLeft / L.px));
    const b = Math.min(L.data.length - 1, Math.ceil((scroller.scrollLeft + scroller.clientWidth) / L.px) - 1);
    return [a, Math.max(a, b)];
  }

  function saveImage(full) {
    if (!S.layout || !S.layout.data.length) { flash('Run an analysis first.'); return; }
    hideTip();
    const L = S.layout;
    const dpr = plot.width / parseFloat(plot.style.width); // scale the chart was drawn at
    const srcX = full ? 0 : Math.round(scroller.scrollLeft * dpr);
    const srcW = full ? plot.width : Math.min(plot.width - srcX, Math.round(scroller.clientWidth * dpr));
    const axisW = axis.width;
    const H = plot.height;
    const headH = Math.round(58 * dpr);
    const footH = Math.round(34 * dpr);
    const margin = Math.round(16 * dpr);

    let outW = margin + axisW + srcW + margin;
    let outH = headH + H + footH;
    // Browsers cap canvas size; shrink very wide pages to fit.
    const scale = Math.min(1, 32000 / outW, 16000 / outH);
    const out = document.createElement('canvas');
    out.width = Math.floor(outW * scale);
    out.height = Math.floor(outH * scale);
    const g = out.getContext('2d');
    g.scale(scale, scale);

    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, outW, outH);

    // header
    const [i0, i1] = visibleIndexRange(full);
    const first = L.data[i0], last = L.data[i1];
    g.fillStyle = '#16232e';
    g.font = `600 ${16 * dpr}px "Segoe UI", Arial, sans-serif`;
    g.textBaseline = 'top';
    g.fillText(`${seriesName()} - Extreme & Change Analysis`, margin, 12 * dpr);
    g.fillStyle = '#5b6b7c';
    g.font = `${12 * dpr}px "Segoe UI", Arial, sans-serif`;
    const rowsTxt = `rows ${(pageStart() + i0 + 1).toLocaleString()}-${(pageStart() + i1 + 1).toLocaleString()} of ${S.rows.length.toLocaleString()}`;
    g.fillText(`${fmtTime(first.Timestamp, true)} to ${fmtTime(last.Timestamp, true)}   |   page ${S.page + 1} of ${pageCount()}   |   ${rowsTxt}`,
      margin, 34 * dpr);

    // chart
    g.drawImage(axis, 0, 0, axisW, H, margin, headH, axisW, H);
    g.drawImage(plot, srcX, 0, srcW, H, margin + axisW, headH, srcW, H);
    g.strokeStyle = '#d7e0ea'; g.lineWidth = dpr;
    g.strokeRect(margin + 0.5, headH + 0.5, axisW + srcW - 1, H - 1);

    // legend
    const items = [];
    if (S.show.value) items.push(['line', COLORS.value, 'Value']);
    if (S.show.ma) items.push(['line', COLORS.ma, 'Moving avg']);
    if (S.show.limits) items.push(['dash', COLORS.limit, 'Limits']);
    if (S.show.extremes) Object.entries(STATE_COLORS).filter(([k]) => k !== 'Persistence ends')
      .forEach(([k, c]) => items.push(['dot', c, k]));
    let lx = margin;
    const ly = headH + H + 12 * dpr;
    g.font = `${11 * dpr}px "Segoe UI", Arial, sans-serif`;
    g.textBaseline = 'middle';
    for (const [kind, color, label] of items) {
      g.strokeStyle = color; g.fillStyle = color; g.lineWidth = 2 * dpr;
      if (kind === 'dot') { g.beginPath(); g.arc(lx + 5 * dpr, ly + 5 * dpr, 4 * dpr, 0, Math.PI * 2); g.fill(); }
      else {
        g.setLineDash(kind === 'dash' ? [4 * dpr, 3 * dpr] : []);
        g.beginPath(); g.moveTo(lx, ly + 5 * dpr); g.lineTo(lx + 14 * dpr, ly + 5 * dpr); g.stroke();
        g.setLineDash([]);
      }
      g.fillStyle = '#5b6b7c';
      g.fillText(label, lx + 18 * dpr, ly + 5 * dpr);
      lx += 18 * dpr + g.measureText(label).width + 16 * dpr;
    }
    const badge = document.title.match(/\(Build \d+\)/);
    g.textAlign = 'right';
    g.fillText(`Saved ${new Date().toLocaleString()}${badge ? '  ' + badge[0] : ''}`, outW - margin, ly + 5 * dpr);

    const name = `extreme_chart_${safe(seriesName())}_${stamp(first.Timestamp)}_to_${stamp(last.Timestamp)}` +
      `_p${S.page + 1}${full ? '_full' : '_view'}.png`;
    out.toBlob((blob) => {
      if (!blob) { flash('Could not create the image - try fewer points per page.'); return; }
      download(blob, name);
      flash(`Saved ${name}` + (scale < 1 ? ' (scaled down to fit)' : ''));
    }, 'image/png');
  }

  function saveCsv() {
    if (!S.layout || !S.layout.data.length) { flash('Run an analysis first.'); return; }
    const data = pageRows();
    const preferred = ['Timestamp', 'Value', 'MovingAverage', 'RollingStdDev', 'UpperLimit', 'LowerLimit', 'ZScore',
      'ExtremeFlag', 'ExtremeDirection', 'State', 'PersistenceCount', 'ROC', 'ROC_ZScore', 'AbnormalChangeFlag',
      'MaterialChangeFlag', 'MaterialityScore'];
    const cols = preferred.filter((c) => c in data[0]).concat(Object.keys(data[0]).filter((c) => !preferred.includes(c)));
    const esc = (v) => {
      if (v === null || v === undefined) return '';
      const t = String(v);
      return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    const lines = [cols.join(',')].concat(data.map((r) => cols.map((c) => esc(r[c])).join(',')));
    const first = data[0], last = data[data.length - 1];
    const name = `extreme_data_${safe(seriesName())}_${stamp(first.Timestamp)}_to_${stamp(last.Timestamp)}_p${S.page + 1}.csv`;
    download(new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), name);
    flash(`Saved ${name}`);
  }

  // ---------------------------------------------------------------- data in
  function extractRows(d) {
    if (!d || typeof d !== 'object') return null;
    for (const key of ['rows', 'table', 'data', 'results', 'records']) {
      if (Array.isArray(d[key]) && d[key].length && typeof d[key][0] === 'object') return d[key];
    }
    for (const v of Object.values(d)) {
      if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object' && 'Value' in v[0]) return v;
    }
    return null;
  }

  function normalize(rows) {
    return rows.map((r) => {
      if ('Timestamp' in r) return r;
      const ts = r.timestamp ?? r.DateTime ?? r.Date ?? r.index;
      return Object.assign({ Timestamp: ts }, r);
    });
  }

  function load(rows) {
    if (!root) buildUI();
    placeUI();
    S.rows = normalize(rows);
    S.page = 0;
    render(true);
  }

  // Public hook, in case app.js wants to call it directly
  window.ChartExplorer = {
    load,
    goTo(i) {
      goToIndex(i);
      if (root) root.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    const p = originalFetch(url, opts);
    const u = typeof url === 'string' ? url : (url && url.url) || '';
    if (u.indexOf('/api/analyze') !== -1) {
      p.then((res) => {
        if (!res.ok) return;
        res.clone().json().then((d) => {
          const rows = extractRows(d);
          if (rows) setTimeout(() => load(rows), 60); // after app.js has drawn its results
        }).catch(() => {});
      }).catch(() => {});
    }
    return p;
  };
})();
