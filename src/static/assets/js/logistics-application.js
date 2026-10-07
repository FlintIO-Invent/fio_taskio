(() => {
  const form = document.querySelector('[data-logistics-application-form]');
  if (!form) return;

  const tabs = Array.from(form.querySelectorAll('[data-logistics-tab]'));
  const panes = Array.from(form.querySelectorAll('[data-logistics-pane]'));
  const previous = form.querySelector('[data-logistics-prev]');
  const next = form.querySelector('[data-logistics-next]');
  const submit = form.querySelector('[data-logistics-submit]');
  const status = form.querySelector('[data-logistics-step-status]');
  let currentStep = 0;

  const existingAccount = form.querySelector('[name="use_existing_account"]');
  function syncPasswordFields() {
    if (!existingAccount) return;
    form.querySelectorAll('[data-logistics-new-password]').forEach((container) => {
      const field = container.querySelector('input');
      container.classList.toggle('d-none', existingAccount.checked);
      field.disabled = existingAccount.checked;
      field.required = !existingAccount.checked;
      if (existingAccount.checked) field.value = '';
    });
  }
  if (existingAccount) existingAccount.addEventListener('change', syncPasswordFields);
  syncPasswordFields();

  function activateStep(index, focusTab = false) {
    currentStep = Math.max(0, Math.min(index, panes.length - 1));
    tabs.forEach((tab, tabIndex) => {
      const active = tabIndex === currentStep;
      tab.classList.toggle('active', active);
      tab.classList.toggle('done', tabIndex < currentStep);
      tab.classList.toggle('complete', tabIndex < currentStep - 1);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panes.forEach((pane, paneIndex) => {
      const active = paneIndex === currentStep;
      pane.classList.toggle('active', active);
      pane.classList.toggle('show', active);
      pane.hidden = !active;
    });
    previous.disabled = currentStep === 0;
    next.classList.toggle('d-none', currentStep === panes.length - 1);
    submit.classList.toggle('d-none', currentStep !== panes.length - 1);
    status.textContent = `Step ${currentStep + 1} of ${panes.length}: ${tabs[currentStep].textContent.trim()}`;
    if (focusTab) tabs[currentStep].focus();
  }

  function validateStep(index) {
    const pane = panes[index];
    const error = pane.querySelector('[data-logistics-step-error]');
    let firstInvalid = null;
    pane.querySelectorAll('input, select, textarea').forEach((field) => {
      if (field.disabled || field.type === 'hidden') return;
      const invalid = !field.checkValidity();
      field.classList.toggle('is-invalid', invalid);
      field.setAttribute('aria-invalid', String(invalid));
      if (invalid && !firstInvalid) firstInvalid = field;
    });
    error.textContent = firstInvalid ? 'Complete the highlighted fields before continuing.' : '';
    error.classList.toggle('d-none', !firstInvalid);
    if (firstInvalid) {
      activateStep(index);
      firstInvalid.focus();
      firstInvalid.reportValidity();
      return false;
    }
    return true;
  }

  function goToStep(index) {
    // Validate every intervening step, including when a tab skips ahead.
    for (let step = currentStep; step < index; step += 1) {
      if (!validateStep(step)) return;
    }
    activateStep(index, true);
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', (event) => {
      event.preventDefault();
      goToStep(index);
    });
    tab.addEventListener('keydown', (event) => {
      let target;
      if (event.key === 'ArrowRight') target = Math.min(index + 1, tabs.length - 1);
      if (event.key === 'ArrowLeft') target = Math.max(index - 1, 0);
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = tabs.length - 1;
      if (target !== undefined) {
        event.preventDefault();
        goToStep(target);
      }
    });
  });
  previous.addEventListener('click', () => activateStep(currentStep - 1, true));
  next.addEventListener('click', () => goToStep(currentStep + 1));
  form.addEventListener('submit', (event) => {
    // Enter advances through the wizard; only the final step submits.
    if (currentStep < panes.length - 1) {
      event.preventDefault();
      goToStep(currentStep + 1);
      return;
    }
    for (let step = 0; step < panes.length; step += 1) {
      if (!validateStep(step)) {
        event.preventDefault();
        return;
      }
    }
  });
  form.querySelectorAll('[data-logistics-field]').forEach((container) => {
    const field = container.querySelector('input, select, textarea');
    const serverError = container.querySelector('[data-logistics-server-error]');
    if (serverError) {
      field.classList.add('is-invalid');
      field.setAttribute('aria-invalid', 'true');
      field.setAttribute('aria-describedby', `${field.getAttribute('aria-describedby') || ''} ${serverError.id}`.trim());
    }
    const clearInvalid = () => {
      field.classList.remove('is-invalid');
      field.removeAttribute('aria-invalid');
      const pane = container.closest('[data-logistics-pane]');
      pane.querySelector('[data-logistics-step-error]').classList.add('d-none');
    };
    field.addEventListener('input', clearInvalid);
    field.addEventListener('change', clearInvalid);
  });

  const firstErrorStep = panes.findIndex((pane) => pane.querySelector('[data-logistics-server-error]'));
  form.noValidate = true;
  form.querySelector('[data-logistics-wizard-navigation]').classList.remove('d-none');
  previous.classList.remove('d-none');
  status.classList.remove('d-none');
  activateStep(Math.max(firstErrorStep, 0));
})();
