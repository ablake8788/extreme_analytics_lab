/*
 * theme.js - Titanium Analytics layout for the Extreme & Change Analytics Lab.
 * Adds the header mark, numbers the workflow steps and builds the workflow
 * rail. Works with the existing page; nothing else has to change.
 */
(function () {
  'use strict';
  if (window.__tiThemeLoaded) return;
  window.__tiThemeLoaded = true;

  const STEP_HINTS = {
    upload: 'CSV or Excel file',
    columns: 'Time and value',
    parameters: 'Detection settings',
    results: 'Chart and listing',
  };

  function hintFor(title) {
    const t = title.toLowerCase();
    if (t.includes('upload')) return STEP_HINTS.upload;
    if (t.includes('column')) return STEP_HINTS.columns;
    if (t.includes('param') || t.includes('setting')) return STEP_HINTS.parameters;
    if (t.includes('result')) return STEP_HINTS.results;
    return '';
  }

  function brandHeader() {
    const inner = document.querySelector('body > header > div');
    if (!inner || inner.querySelector('.ti-mark')) return;
    const mark = document.createElement('div');
    mark.className = 'ti-mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = 'Ti';
    inner.insertBefore(mark, inner.firstChild);
    const eyebrow = inner.querySelector('.eyebrow');
    if (eyebrow) eyebrow.textContent = 'Titanium Analytics';
  }

  function isShown(el) {
    return el.style.display !== 'none' && getComputedStyle(el).display !== 'none';
  }

  function build() {
    brandHeader();
    const main = document.querySelector('main');
    if (!main || document.querySelector('.ti-shell')) return;

    const panels = Array.from(main.querySelectorAll(':scope > section.panel'));
    if (!panels.length) return;

    // Number the headings: "1. Upload data" -> [1] Upload data
    const steps = panels.map((panel, i) => {
      const h2 = panel.querySelector(':scope > h2');
      const raw = h2 ? h2.textContent.trim() : `Step ${i + 1}`;
      const m = raw.match(/^(\d+)[.)]\s*(.*)$/);
      const no = m ? m[1] : String(i + 1);
      const title = m ? m[2] : raw;
      if (h2 && !h2.querySelector('.ti-step-no')) {
        h2.textContent = '';
        const badge = document.createElement('span');
        badge.className = 'ti-step-no';
        badge.textContent = no;
        const text = document.createElement('span');
        text.textContent = title;
        h2.append(badge, text);
      }
      if (!panel.id) panel.id = `ti-step-${i + 1}`;
      return { panel, no, title };
    });

    // Shell: rail on the left, the existing <main> on the right
    const shell = document.createElement('div');
    shell.className = 'ti-shell';
    main.parentNode.insertBefore(shell, main);
    const rail = document.createElement('nav');
    rail.className = 'ti-rail';
    rail.setAttribute('aria-label', 'Workflow');
    rail.innerHTML = '<h2>Workflow</h2><ol></ol>';
    shell.append(rail, main);

    const ol = rail.querySelector('ol');
    const items = steps.map((s) => {
      const li = document.createElement('li');
      li.innerHTML = `<a href="#${s.panel.id}"><span class="ti-dot">${s.no}</span>` +
        `<span>${s.title}<span class="ti-sub">${hintFor(s.title)}</span></span></a>`;
      li.querySelector('a').addEventListener('click', (e) => {
        if (li.classList.contains('is-locked')) e.preventDefault();
      });
      ol.appendChild(li);
      return li;
    });

    let current = 0;
    function refresh() {
      let lastShown = -1;
      steps.forEach((s, i) => { if (isShown(s.panel)) lastShown = i; });
      steps.forEach((s, i) => {
        const li = items[i];
        const shown = isShown(s.panel);
        li.classList.toggle('is-locked', !shown);
        li.classList.toggle('is-done', shown && i < lastShown);
        li.classList.toggle('is-ready', shown && i >= lastShown);
        li.classList.toggle('is-current', shown && i === current);
        const a = li.querySelector('a');
        if (shown) a.removeAttribute('aria-disabled'); else a.setAttribute('aria-disabled', 'true');
        if (i === current && shown) a.setAttribute('aria-current', 'step'); else a.removeAttribute('aria-current');
      });
    }

    // Track which panels are visible (app.js shows them step by step)
    const mo = new MutationObserver(refresh);
    steps.forEach((s) => mo.observe(s.panel, { attributes: true, attributeFilter: ['style', 'class', 'hidden'] }));

    // Track which panel is in view
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            const idx = steps.findIndex((s) => s.panel === en.target);
            if (idx >= 0) { current = idx; refresh(); }
          }
        });
      }, { rootMargin: '-35% 0px -55% 0px' });
      steps.forEach((s) => io.observe(s.panel));
    }

    // Jump to results when they appear
    const results = steps[steps.length - 1];
    let resultsWasShown = isShown(results.panel);
    new MutationObserver(() => {
      const now = isShown(results.panel);
      if (now && !resultsWasShown) setTimeout(() => results.panel.scrollIntoView({ block: 'start' }), 150);
      resultsWasShown = now;
    }).observe(results.panel, { attributes: true, attributeFilter: ['style'] });

    refresh();
    watchSummary();
  }

  // Readout values: 42194 -> 42,194 and bollinger -> Bollinger
  const METHOD_NAMES = { bollinger: 'Bollinger', ewma: 'EWMA', mad: 'MAD', percentile: 'Percentile', iqr: 'IQR' };
  function formatSummary(grid) {
    grid.querySelectorAll('.summary-item .value').forEach((el) => {
      if (el.dataset.tiFormatted === el.textContent) return;
      const t = el.textContent.trim();
      let out = t;
      if (/^-?\d+(\.\d+)?$/.test(t)) {
        const n = Number(t);
        out = Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 3 });
      } else if (METHOD_NAMES[t.toLowerCase()]) {
        out = METHOD_NAMES[t.toLowerCase()];
      }
      el.textContent = out;
      el.dataset.tiFormatted = out;
    });
  }
  function watchSummary() {
    const grid = document.getElementById('summaryGrid') || document.querySelector('.summary-grid');
    if (!grid) return;
    formatSummary(grid);
    new MutationObserver(() => formatSummary(grid)).observe(grid, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
