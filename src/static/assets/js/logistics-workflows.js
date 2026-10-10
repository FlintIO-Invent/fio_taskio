document.addEventListener('DOMContentLoaded', () => {
  const shipmentForm = document.querySelector('[data-logistics-shipment-form]');
  if (shipmentForm) {
    const mode = shipmentForm.querySelector('[name="transport_mode"]');
    const updateReferences = () => {
      shipmentForm.querySelectorAll('[data-shipment-reference-mode]').forEach(group => {
        // Keep error fields reachable and retain entered values when switching modes.
        group.hidden = group.dataset.shipmentReferenceMode !== mode.value &&
          !group.querySelector('.invalid-feedback.d-block');
      });
    };
    updateReferences();
    mode.addEventListener('change', updateReferences);
  }
  const parcelForm = document.querySelector('[data-logistics-parcel-form]');
  if (parcelForm) {
    const showFieldTab = field => {
      const pane = field?.closest('.tab-pane');
      if (!pane || pane.classList.contains('active')) return;
      const trigger = parcelForm.querySelector(`[data-bs-target="#${pane.id}"]`);
      if (trigger && window.bootstrap) window.bootstrap.Tab.getOrCreateInstance(trigger).show();
    };
    const serverError = parcelForm.querySelector('.invalid-feedback.d-block');
    const serverSummary = parcelForm.querySelector('[data-logistics-form-errors]');
    if (serverSummary) {
      showFieldTab(serverError);
      serverSummary.focus();
    }
    parcelForm.addEventListener('submit', event => {
      if (parcelForm.checkValidity()) return;
      event.preventDefault();
      const invalidFields = Array.from(parcelForm.querySelectorAll(':invalid'));
      const summary = parcelForm.querySelector('[data-parcel-browser-errors]');
      const heading = document.createElement('div');
      heading.className = 'fw-semibold mb-1';
      heading.textContent = 'Parcel was not saved. Please correct the following fields:';
      const list = document.createElement('ul');
      list.className = 'mb-0';
      invalidFields.forEach(field => {
        const item = document.createElement('li');
        item.textContent = field.labels?.[0]?.textContent.trim() || field.name;
        list.appendChild(item);
      });
      summary.replaceChildren(heading, list);
      summary.classList.remove('d-none');
      showFieldTab(invalidFields[0]);
      summary.focus();
      summary.scrollIntoView({behavior: 'smooth', block: 'center'});
    });
  }
  const selections = new Map();
  document.querySelectorAll('[data-logistics-search-select]').forEach(select => {
    if (window.Choices && !select.disabled) {
      selections.set(select, new window.Choices(select, {
        itemSelectText: '', allowHTML: false, shouldSort: false, searchEnabled: true,
        searchResultLimit: 8,
        searchPlaceholderValue: select.dataset.searchPlaceholder || 'Search',
      }));
      const search = select.closest('.choices')?.querySelector('input');
      if (search) {
        search.setAttribute('aria-label', `Search ${select.labels?.[0]?.textContent.trim() || 'options'}`);
        search.setAttribute('autocapitalize', 'none');
        search.setAttribute('spellcheck', 'false');
        search.setAttribute('enterkeyhint', 'search');
      }
    }
  });

  document.querySelectorAll('[data-copy-tracking]').forEach(button => {
    button.addEventListener('click', async () => {
      const status = button.nextElementSibling;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(button.dataset.copyTracking);
        } else {
          const text = document.createElement('textarea');
          text.value = button.dataset.copyTracking;
          text.className = 'visually-hidden';
          document.body.appendChild(text);
          text.select();
          const copied = document.execCommand('copy');
          text.remove();
          if (!copied) throw new Error('Copy unavailable');
        }
        status.textContent = 'Tracking code copied.';
        button.textContent = 'Copied';
      } catch {
        status.textContent = 'Copy unavailable. Select the tracking code to copy it.';
      }
    });
  });

  document.querySelectorAll('[data-shipping-prefill]').forEach(button => {
    button.addEventListener('click', async () => {
      const form = button.closest('form');
      const side = button.dataset.shippingPrefill;
      const status = form.querySelector(`[data-shipping-prefill-status="${side}"]`);
      const client = form.querySelector('[name="client"]')?.value || form.dataset.shippingClientId;
      if (!client) {
        status.textContent = 'Select a Client first.';
        return;
      }
      button.disabled = true;
      try {
        const url = new URL(form.dataset.shippingPrefillUrl, window.location.origin);
        url.searchParams.set('client', client);
        const response = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) {
          throw new Error('Prefill unavailable');
        }
        const values = await response.json();
        Object.entries(values).forEach(([suffix, value]) => {
          const field = form.elements.namedItem(`${side}_${suffix}`);
          if (field && !field.value && value) {
            const choices = selections.get(field);
            if (choices) choices.setChoiceByValue(value);
            else field.value = value;
            field.dispatchEvent(new Event('change', {bubbles: true}));
          }
        });
        status.textContent = 'Empty fields copied. Review the shipping details before saving.';
      } catch {
        status.textContent = 'Client details are unavailable. Enter shipping details directly.';
      } finally {
        button.disabled = false;
      }
    });
  });

  const clientForm = document.querySelector('[data-parcel-client-form]');
  if (!clientForm) return;
  const modal = document.getElementById('parcelClientModal');
  modal.addEventListener('shown.bs.modal', () => {
    clientForm.querySelector('input[name="new_client-first_name"]').focus();
  });
  clientForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = clientForm.querySelector('[type="submit"]');
    const error = clientForm.querySelector('[data-client-request-error]');
    button.disabled = true;
    error.classList.add('d-none');
    try {
      const response = await fetch(clientForm.action, {
        method: 'POST', body: new FormData(clientForm),
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const result = new DOMParser().parseFromString(await response.text(), 'text/html');
      const created = result.querySelector('[data-created-client]');
      if (response.ok && created) {
        const select = document.getElementById('id_client');
        const choices = selections.get(select);
        if (choices) {
          choices.setChoices([{value: created.value, label: created.textContent, selected: true}], 'value', 'label', false);
        } else {
          select.add(new Option(created.textContent, created.value, true, true));
        }
        select.dispatchEvent(new Event('change', {bubbles: true}));
        document.querySelector('[data-client-selection-status]').textContent = 'Client added and selected. Continue registering your parcel.';
        document.querySelector('[data-no-clients]')?.remove();
        window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        clientForm.reset();
        clientForm.querySelectorAll('.invalid-feedback, .alert-danger').forEach(element => element.classList.add('d-none'));
        clientForm.querySelectorAll('[aria-invalid]').forEach(element => element.removeAttribute('aria-invalid'));
      } else {
        const fields = result.querySelector('[data-client-fields]');
        if (fields) {
          clientForm.querySelector('[data-client-fields]').replaceWith(fields);
          clientForm.querySelector('[aria-invalid="true"]')?.focus();
        } else {
          throw new Error('Client creation unavailable');
        }
      }
    } catch {
      error.textContent = 'The client could not be added. Check your access and try again.';
      error.classList.remove('d-none');
    } finally {
      button.disabled = false;
    }
  });
});
