(() => {
  'use strict';
  const root = document.querySelector('[data-scan-workflow]');
  if (!root) return;
  const lookup = root.querySelector('[data-scan-lookup]');
  const input = lookup.querySelector('[data-scan-input]');
  const result = root.querySelector('[data-scan-result]');
  let busy = false;
  const normalizeCode = value => typeof value === 'string' && value.length <= 256 ? value.trim().toUpperCase() : '';
  const validCode = code => /^[A-F0-9]{48}$/.test(code);
  const clearParcel = () => result.querySelector('[data-scan-parcel]')?.remove();
  const focusInput = () => { input.focus(); input.select(); };
  const feedback = (message, isError = true) => {
    const target = root.querySelector('#scan-feedback');
    const alert = document.createElement('div');
    alert.className = `alert ${isError ? 'alert-danger' : 'alert-subtle-info'}`;
    alert.setAttribute('role', isError ? 'alert' : 'status');
    alert.textContent = message;
    target.replaceChildren(alert);
  };
  const setBusy = value => {
    busy = value;
    root.setAttribute('aria-busy', String(value));
    input.readOnly = value;
    root.querySelectorAll('button').forEach(button => { button.disabled = value; });
  };
  const reset = () => {
    if (busy) return;
    input.value = '';
    input.setCustomValidity('');
    input.removeAttribute('aria-invalid');
    result.replaceChildren();
    const panel = document.createElement('div');
    panel.dataset.scanPanel = '';
    const status = document.createElement('div');
    status.id = 'scan-feedback';
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    panel.append(status);
    result.append(panel);
    focusInput();
  };

  // Camera or another future source can submit a decoded string here. Resolution
  // belongs to the authenticated endpoint, not to a keyboard event or this API.
  const submitCode = value => {
    if (busy) return false;
    if (!navigator.onLine) {
      feedback('A connection is required to look up parcels.');
      focusInput();
      return false;
    }
    const code = normalizeCode(value);
    if (!validCode(code)) {
      clearParcel();
      feedback('Enter a complete 48-character tracking code.');
      input.setAttribute('aria-invalid', 'true');
      focusInput();
      return false;
    }
    input.value = code;
    input.setCustomValidity('');
    lookup.requestSubmit();
    return true;
  };
  window.MotionmateParcelScan = Object.freeze({normalizeCode, submitCode});
  input.addEventListener('input', () => {
    clearParcel();
    input.setCustomValidity('');
    input.removeAttribute('aria-invalid');
  });
  input.addEventListener('paste', event => {
    if (!event.clipboardData || busy) return;
    event.preventDefault();
    const code = normalizeCode(event.clipboardData.getData('text'));
    clearParcel();
    input.value = code;
    input.setCustomValidity(validCode(code) ? '' : 'Enter a complete 48-character tracking code.');
    if (!validCode(code)) {
      input.setAttribute('aria-invalid', 'true');
      feedback('Enter a complete 48-character tracking code.');
    } else input.removeAttribute('aria-invalid');
  });
  root.querySelector('[data-next-scan]').addEventListener('click', reset);
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!root.contains(form) || !form.matches('[data-scan-lookup], [data-scan-action]') || event.defaultPrevented) return;
    event.preventDefault();
    if (busy) return;
    const action = form.matches('[data-scan-action]');
    if (!action) {
      clearParcel();
      const code = normalizeCode(input.value);
      if (!validCode(code)) {
        feedback('Enter a complete 48-character tracking code.');
        input.setAttribute('aria-invalid', 'true');
        focusInput();
        return;
      }
      input.value = code;
    }
    const body = new FormData(form);
    if (event.submitter?.name) body.set(event.submitter.name, event.submitter.value);
    setBusy(true);
    feedback(action ? 'Recording update…' : 'Finding parcel…', false);
    try {
      const response = await fetch(form.action, {
        method: 'POST', body, credentials: 'same-origin', cache: 'no-store',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const documentResult = new DOMParser().parseFromString(await response.text(), 'text/html');
      const panel = documentResult.querySelector('[data-scan-panel]');
      if (!panel || response.redirected) {
        result.querySelector('[data-scan-parcel]')?.remove();
        throw new Error('access');
      }
      // An action is confirmed only after the service returned success.
      if (action && response.ok && !panel.hasAttribute('data-scan-action-success')) throw new Error('unconfirmed');
      result.replaceChildren(document.importNode(panel, true));
      if (action && response.ok) input.value = '';
      if (!action && !response.ok) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    } catch (error) {
      feedback(error.message === 'access'
        ? 'Your session or access changed. Reload this page before continuing.'
        : action
          ? 'The update could not be confirmed. Check your connection and retry the same action.'
          : 'Lookup unavailable. Check your connection and try again.');
      // Preserve the original action form and its retry key on an uncertain write.
    } finally {
      setBusy(false);
      focusInput();
    }
  });
  focusInput();
})();
