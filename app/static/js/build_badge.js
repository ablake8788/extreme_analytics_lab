/*
 * build_badge.js - shows the build number in the bottom-right corner.
 * Reads static/build_info.json, which build.ps1 writes on every build.
 * Click the badge to see the build date, branch and commit.
 */
(function () {
  'use strict';
  if (window.__buildBadgeLoaded) return;
  window.__buildBadgeLoaded = true;

  const me = document.currentScript && document.currentScript.src;
  const infoUrl = me ? me.replace(/js\/build_badge\.js.*$/, 'build_info.json') : '/static/build_info.json';

  function show(info) {
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.setAttribute('aria-label', 'Build information');
    badge.style.cssText = [
      'position:fixed', 'right:14px', 'bottom:12px', 'z-index:50',
      'font:600 12px "Segoe UI",Arial,sans-serif', 'color:#2f6fed', 'background:#fff',
      'border:1px solid #d7e0ea', 'border-radius:999px', 'padding:5px 12px',
      'box-shadow:0 4px 14px rgba(20,40,70,.10)', 'cursor:pointer', 'width:auto', 'min-width:0',
    ].join(';');

    const short = info ? `Build ${info.build}` : 'Dev build';
    const details = info
      ? `Build ${info.build}  |  version ${info.version}  |  built ${info.built_at}` +
        (info.branch ? `  |  ${info.branch}` : '') + (info.commit ? ` @ ${info.commit}` : '')
      : 'Running from source - no build number yet (run build.ps1)';

    let open = false;
    badge.textContent = short;
    badge.title = details;
    badge.onclick = () => {
      open = !open;
      badge.textContent = open ? details : short;
      badge.style.color = open ? '#16232e' : '#2f6fed';
    };
    document.body.appendChild(badge);
    if (info && !/\(Build \d+\)$/.test(document.title)) document.title += ` (Build ${info.build})`;
  }

  function start() {
    fetch(infoUrl + '?t=' + Date.now(), { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then(show)
      .catch(() => show(null));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
