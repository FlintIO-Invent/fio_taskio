(() => {
  'use strict';
  const script = document.querySelector('script[data-worker]');
  if (!script) return;
  const privatePage = script.dataset.private === 'true';
  const indicator = document.createElement('div');
  indicator.className = 'pwa-connectivity';
  indicator.setAttribute('role', 'status');
  indicator.setAttribute('aria-live', 'polite');
  indicator.textContent = 'Offline — live data may be out of date. Changes require a connection.';
  document.body.append(indicator);
  const connectivity = () => { indicator.hidden = navigator.onLine; };
  connectivity();
  window.addEventListener('online', connectivity);
  window.addEventListener('offline', connectivity);

  // Capture before existing AJAX/native form handlers. No write is queued.
  document.addEventListener('submit', event => {
    if (!navigator.onLine && event.target.method.toLowerCase() !== 'get') {
      event.preventDefault();
      event.stopImmediatePropagation();
      connectivity();
    }
  }, true);

  const hidePrivate = () => document.documentElement.classList.add('pwa-private-hidden');
  const refreshPrivate = () => { hidePrivate(); window.location.reload(); };
  if (privatePage) {
    // No-store alone does not guarantee all browsers exclude BFCache snapshots.
    window.addEventListener('pagehide', hidePrivate);
    window.addEventListener('pageshow', event => {
      if (event.persisted) refreshPrivate();
    });
  }

  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register(script.dataset.worker, {
      scope: script.dataset.scope,
      updateViaCache: 'none'
    }).catch(() => {
      // Online Django navigation remains usable if installation/storage fails.
    });
  }
})();
