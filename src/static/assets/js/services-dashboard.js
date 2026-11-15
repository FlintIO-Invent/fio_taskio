/* Presentation only. Bootstrap and Phoenix retain all navigation/theme/forms. */
(function () {
  'use strict';
  const root = document.querySelector('.mm-services-dashboard');
  if (!root || root.dataset.mmSdReady) return;
  document.querySelectorAll('.onboarding-welcome-modal [role="progressbar"], .onboarding-guide-panel [role="progressbar"]').forEach(progress => {
    const section = progress.closest('.onboarding-journey-card, .list-group-item, .onboarding-panel-section');
    const title = section && section.querySelector('h5, .fw-semibold');
    if (title && !progress.hasAttribute('aria-label')) progress.setAttribute('aria-label', title.textContent.trim() + ' progress');
  });
  const wide = window.matchMedia('(min-width: 768px)');
  const choices = new WeakMap();
  const disclosures = [...root.querySelectorAll('[data-mm-sd-more]')];
  function label(detail) {
    const text = detail.querySelector('[data-mm-sd-more-label]');
    if (text) text.textContent = detail.open ? text.dataset.expandedLabel : text.dataset.collapsedLabel;
  }
  function layout() {
    disclosures.forEach(detail => {
      const open = wide.matches || choices.get(detail) === true;
      if (open || !detail.contains(document.activeElement)) detail.open = open;
      label(detail);
    });
  }
  disclosures.forEach(detail => {
    detail.addEventListener('toggle', () => label(detail));
    detail.querySelector('summary').addEventListener('click', () => {
      requestAnimationFrame(() => { choices.set(detail, detail.open); });
    });
  });
  layout();
  wide.addEventListener('change', layout);
  const button = root.querySelector('[data-mm-sd-copy]');
  const input = root.querySelector('#mm-sd-booking-url');
  const status = root.querySelector('#mm-sd-copy-status');
  if (button && input && status) {
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      status.textContent = 'Copying link…';
      status.removeAttribute('data-failed');
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(input.value);
        status.textContent = 'Link copied';
      } catch (_) {
        status.textContent = 'Copy unavailable — the link is selected. Copy it manually.';
        status.setAttribute('data-failed', 'true');
        input.focus({preventScroll: true});
        input.select();
      } finally {
        button.disabled = false;
        button.removeAttribute('aria-busy');
      }
    });
  }
  root.dataset.mmSdReady = 'true';
})();
