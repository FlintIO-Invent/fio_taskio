/* Services invoice presentation; existing Django workflows remain authoritative. */
(() => { 'use strict';
function initialize() {
 const root = document.querySelector('.mm-services-invoices[data-invoice-workspace]');
 if (!root) return;

// Confirmation only submits the original Django form, retaining CSRF and hidden fields.
let pendingForm = null, trigger = null;
const modal = document.createElement('div');
modal.className = 'modal fade mm-services-invoices';
modal.id = 'invoiceConfirmation'; modal.tabIndex = -1;
modal.setAttribute('aria-labelledby','invoiceConfirmationTitle'); modal.setAttribute('aria-hidden','true');
modal.innerHTML = '<div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header"><h2 class="modal-title" id="invoiceConfirmationTitle">Confirm invoice action</h2><button class="btn-close" type="button" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><p id="invoiceConfirmationText"></p></div><div class="modal-footer"><button type="button" class="btn btn-phoenix-secondary" data-bs-dismiss="modal">Keep invoice</button><button type="button" class="btn btn-primary" data-confirm-submit>Continue</button></div></div></div>';
root.appendChild(modal);
root.addEventListener('submit', event => {
  const form = event.target.closest('[data-invoice-confirm]');
  if (!form || form.dataset.confirmed === 'true') return;
  if (!window.bootstrap?.Modal) { if (!window.confirm(form.dataset.invoiceConfirm)) event.preventDefault(); return; }
  event.preventDefault(); pendingForm = form; trigger = event.submitter || document.activeElement;
  modal.querySelector('#invoiceConfirmationText').textContent = form.dataset.invoiceConfirm;
  bootstrap.Modal.getOrCreateInstance(modal).show();
});
modal.querySelector('[data-confirm-submit]').addEventListener('click', () => {
  const form = pendingForm; if (!form) return;
  form.dataset.confirmed = 'true'; bootstrap.Modal.getOrCreateInstance(modal).hide();
  form.requestSubmit(); delete form.dataset.confirmed;
});
modal.addEventListener('hidden.bs.modal', () => { pendingForm = null; trigger?.focus(); });

 if (root.dataset.invoiceWorkspace !== 'editor') return;
 const currencyCode = root.dataset.currency;
 const taxRate = parseFloat(root.dataset.taxRate) || 0;
let clientChoices = null;

(() => {
  const clientSelect = document.getElementById('id_client_id');
  if (clientSelect && !clientSelect.disabled && window.Choices) {
    clientChoices = new window.Choices(clientSelect, {
      itemSelectText: '',
      addItems: true,
      allowHTML: false,
      searchEnabled: true,
      shouldSort: false,
      searchResultLimit: 8
    });
  }
})();

const quickClientForm = document.getElementById('quick-client-form');
if (quickClientForm) {
  quickClientForm.addEventListener('submit', async function(event) {
    event.preventDefault();

    const errorBox = document.getElementById('quick-client-errors');
    const submitButton = quickClientForm.querySelector('button[type="submit"]');
    errorBox.classList.add('d-none');
    errorBox.replaceChildren();
    quickClientForm.querySelectorAll('[aria-invalid=true]').forEach(field => { field.removeAttribute('aria-invalid'); field.removeAttribute('aria-describedby'); });
    submitButton.disabled = true;

    try {
      const response = await fetch(quickClientForm.action, {
        method: 'POST',
        body: new FormData(quickClientForm),
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      const data = await response.json();

      if (!response.ok) {
        const errorList = document.createElement('ul');
        errorList.className = 'mb-0';
        Object.entries(data.errors || {}).forEach(([name, messages]) => {
          const field = quickClientForm.elements.namedItem(name);
          const label = field?.id ? quickClientForm.querySelector(`label[for="${field.id}"]`) : null;
          if (field) { field.setAttribute('aria-invalid', 'true'); field.setAttribute('aria-describedby', 'quick-client-errors'); }
          messages.forEach(message => {
            const item = document.createElement('li');
            item.textContent = (label ? label.textContent.replace('*', '').trim() + ': ' : '') + message;
            errorList.appendChild(item);
          });
        });
        if (!errorList.children.length) {
          const item = document.createElement('li');
          item.textContent = 'Please check the client details and try again.';
          errorList.appendChild(item);
        }
        errorBox.appendChild(errorList);
        errorBox.classList.remove('d-none');
        quickClientForm.querySelector('[aria-invalid=true]')?.focus();
        return;
      }

      const clientValue = String(data.client.id);
      if (clientChoices) {
        clientChoices.setChoices(
          [{ value: clientValue, label: data.client.label, selected: true }],
          'value',
          'label',
          false
        );
      } else {
        const clientSelect = document.getElementById('id_client_id');
        clientSelect.add(new Option(data.client.label, clientValue, true, true));
      }

      document.getElementById('invoice-summary-client').textContent = data.client.label;
      const selectionHelp = document.getElementById('client-selection-help');
      if (selectionHelp) {
        selectionHelp.className = 'alert alert-subtle-success border mb-0';
        selectionHelp.textContent = 'Client added and selected. Continue editing your invoice.';
      }

      bootstrap.Modal.getOrCreateInstance(document.getElementById('quickClientModal')).hide();
      quickClientForm.reset();
    } catch (error) {
      errorBox.textContent = 'The client could not be added. Please try again.';
      errorBox.classList.remove('d-none');
    } finally {
      submitButton.disabled = false;
    }
  });
}

function getInputValue(lineItem, existingName, newName) {
  const field = lineItem.querySelector(`input[name="${existingName}"], input[name="${newName}"]`);
  return field ? field.value : '';
}

function setInputValue(lineItem, existingName, newName, value) {
  const field = lineItem.querySelector(`input[name="${existingName}"], input[name="${newName}"]`);
  if (field) {
    field.value = value;
  }
}

function isWholeUnitQuantity(value) {
  const quantity = parseFloat(value);
  return value && Number.isFinite(quantity) && quantity >= 1 && Number.isInteger(quantity);
}

function setManualServiceSave(lineItem, shouldSave) {
  const actionInput = lineItem.querySelector('.manual-service-action');
  const actionToggle = lineItem.querySelector('.manual-service-action-toggle');

  if (actionInput) {
    actionInput.value = shouldSave ? '1' : '';
  }
  if (actionToggle) {
    actionToggle.checked = shouldSave;
  }
}

function setServiceSource(lineItem, source, { clearService = false } = {}) {
  const serviceSelect = lineItem.querySelector('.service-select');
  lineItem.dataset.serviceSource = source;

  if (clearService && source === 'custom' && serviceSelect) {
    serviceSelect.value = '';
  }
  if (source === 'saved') {
    setManualServiceSave(lineItem, false);
  }

  updateServiceSource(lineItem);
  updateManualServiceOptions(lineItem);
}

function updateServiceSource(lineItem) {
  if (!lineItem) {
    return;
  }

  const serviceSelect = lineItem.querySelector('.service-select');
  const sourceSelect = lineItem.querySelector('.service-source-select');
  const savedFields = lineItem.querySelector('.saved-service-fields');
  const descriptionLabel = lineItem.querySelector('.service-description-label');
  const source = lineItem.dataset.serviceSource || (sourceSelect && sourceSelect.value) || (serviceSelect && serviceSelect.value ? 'saved' : 'custom');

  lineItem.dataset.serviceSource = source;
  if (sourceSelect) {
    sourceSelect.value = source;
  }
  if (savedFields) {
    savedFields.classList.toggle('d-none', source !== 'saved');
  }
  if (descriptionLabel) {
    descriptionLabel.textContent = root.dataset.services === 'true' ? (source === 'saved' ? 'Description' : 'Service name') : 'Description';
  }
}

function applySelectedService(selectElement) {
  const selectedOption = selectElement.options[selectElement.selectedIndex];
  const lineItem = selectElement.closest('.line-item');
  lineItem.dataset.serviceSource = 'saved';
  if (!selectedOption || !selectedOption.value) {
    updateServiceSource(lineItem);
    updateManualServiceOptions(lineItem);
    return;
  }

  setInputValue(lineItem, 'description', 'new_description', selectedOption.dataset.description || selectedOption.dataset.name || '');
  setInputValue(lineItem, 'unit_price', 'new_unit_price', selectedOption.dataset.unitPrice || '');

  const quantityValue = getInputValue(lineItem, 'quantity', 'new_quantity');
  if (!isWholeUnitQuantity(quantityValue)) {
    setInputValue(lineItem, 'quantity', 'new_quantity', '1.00');
  }
  setManualServiceSave(lineItem, false);

  updateServiceSource(lineItem);
  updateManualServiceOptions(lineItem);
  updateTotals();
}

function updateManualServiceOptions(lineItem) {
  if (!lineItem) {
    return;
  }

  const serviceSelect = lineItem.querySelector('.service-select');
  const actionInput = lineItem.querySelector('.manual-service-action');
  const actionToggle = lineItem.querySelector('.manual-service-action-toggle');
  const manualOptions = lineItem.querySelector('.manual-service-options');
  const categoryFields = lineItem.querySelectorAll('.manual-service-category-fields');
  const categorySelect = lineItem.querySelector('select[name$="service_category_id"]');
  const newCategoryInput = lineItem.querySelector('input[name$="new_service_category_name"]');
  const serviceSource = lineItem.dataset.serviceSource || (serviceSelect && serviceSelect.value ? 'saved' : 'custom');
  const hasSavedService = Boolean(serviceSelect && serviceSelect.value);
  const canSaveManualService = serviceSource === 'custom' && !hasSavedService;
  const shouldShow = Boolean(actionInput && actionInput.value === '1' && canSaveManualService);

  if (!canSaveManualService) {
    setManualServiceSave(lineItem, false);
  }
  if (manualOptions) {
    manualOptions.classList.toggle('d-none', !canSaveManualService);
  }
  if (actionToggle && actionInput) {
    actionToggle.checked = actionInput.value === '1';
  }

  categoryFields.forEach(field => {
    field.classList.toggle('d-none', !shouldShow);
  });

  if (!shouldShow) {
    if (categorySelect) {
      categorySelect.value = '';
    }
    if (newCategoryInput) {
      newCategoryInput.value = '';
    }
  }
}

function addLineItem() {
  const template = document.getElementById('line-item-template');
  const container = document.getElementById('line-items');
  const newItem = template.cloneNode(true);
  newItem.id = '';
  newItem.hidden = false;
  newItem.querySelectorAll('input, select').forEach(field => {
    field.disabled = false;
    if (field.name === 'new_quantity' || field.name === 'new_unit_price') {
      field.required = true;
    }
  });
  container.appendChild(newItem);
  newItem.querySelector('input:not([type=hidden]), select')?.focus();
  setServiceSource(newItem, 'custom');
  updateTotals();
}

function removeLineItem(button) {
  const lineItem = button.closest('.line-item');
  const nextFocus = lineItem.nextElementSibling || lineItem.previousElementSibling;
  lineItem.remove();
  (nextFocus?.querySelector('[data-remove-line]') || root.querySelector('[data-add-line]'))?.focus();
  updateTotals();
}

function updateTotals() {
  let subtotal = 0;
  const lineItems = document.querySelectorAll('.line-item:not(#line-item-template)');

  lineItems.forEach(item => {
    const quantity = parseFloat(getInputValue(item, 'quantity', 'new_quantity')) || 0;
    const unitPrice = parseFloat(getInputValue(item, 'unit_price', 'new_unit_price')) || 0;
    const lineTotal = quantity * unitPrice;
    const totalInput = item.querySelector('.line-total-display');

    if (totalInput) {
      totalInput.value = currencyCode + ' ' + lineTotal.toFixed(2);
    }

    subtotal += lineTotal;
  });

  const taxAmount = subtotal * (taxRate / 100);
  document.getElementById('subtotal-display').textContent = currencyCode + ' ' + subtotal.toFixed(2);
  document.getElementById('tax-display').textContent = currencyCode + ' ' + taxAmount.toFixed(2);
  document.getElementById('total-display').textContent = currencyCode + ' ' + (subtotal + taxAmount).toFixed(2);
}

document.addEventListener('input', function(e) {
  if (e.target.matches('input[name="quantity"], input[name="unit_price"], input[name="new_quantity"], input[name="new_unit_price"]')) {
    updateTotals();
  }
});

document.addEventListener('change', function(e) {
  if (e.target.matches('.service-select')) {
    applySelectedService(e.target);
  } else if (e.target.matches('.service-source-select')) {
    setServiceSource(
      e.target.closest('.line-item'),
      e.target.value,
      { clearService: e.target.value === 'custom' }
    );
    updateTotals();
  } else if (e.target.matches('.manual-service-action-toggle')) {
    setManualServiceSave(e.target.closest('.line-item'), e.target.checked);
    updateManualServiceOptions(e.target.closest('.line-item'));
  }
});

document.querySelectorAll('.line-item:not(#line-item-template)').forEach(lineItem => {
  const initialServiceSelect = lineItem.querySelector('.service-select');
  setServiceSource(
    lineItem,
    initialServiceSelect && initialServiceSelect.value ? 'saved' : 'custom'
  );
});
updateTotals();

root.addEventListener('click', event => {
  if (event.target.closest('[data-add-line]')) addLineItem();
  const button = event.target.closest('[data-remove-line]');
  if (button) removeLineItem(button);
});
root.querySelector('#id_client_id')?.addEventListener('change', event => {
  root.querySelector('#invoice-summary-client').textContent = event.target.selectedOptions[0]?.textContent.trim() || 'Select a client';
});
const quickModal = document.getElementById('quickClientModal');
quickModal?.addEventListener('shown.bs.modal', () => quickModal.querySelector('input:not([type=hidden])')?.focus());

}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize); else initialize();
})();
