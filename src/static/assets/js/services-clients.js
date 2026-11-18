/* Progressive Services presentation. Django remains authoritative for every write. */
document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('.mm-services-clients');
  if (!root) return;
  const openSection = element => {
    for (let node = element; node && node !== root; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
    }
  };
  const revealHash = (focus = false) => {
    if (!location.hash || location.hash === '#!') return;
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
    const target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    openSection(target);
    if (focus) {
      const control = target.matches('input,select,textarea,summary') ? target : target.querySelector('summary,input,select,textarea');
      control?.focus();
    }
  };
  root.addEventListener('click', event => {
    const anchor = event.target.closest('a[href^="#"]');
    if (!anchor || anchor.getAttribute('href') === '#!') return;
    const target = document.getElementById(anchor.getAttribute('href').slice(1));
    if (!target || !root.contains(target)) return;
    openSection(target);
    if (anchor.closest('[data-clients-error-summary]') || anchor.hasAttribute('data-clients-section')) {
      event.preventDefault();
      const control = target.matches('input,select,textarea') ? target : target.querySelector('summary,input,select,textarea');
      control?.focus();
      target.scrollIntoView({block: 'start'});
      history.replaceState(null, '', '#' + target.id);
    }
  });
  window.addEventListener('hashchange', () => revealHash(true));
  revealHash();

  const form = root.querySelector('[data-client-form]');
  const summary = root.querySelector('[data-clients-error-summary]');
  if (form && summary) {
    form.addEventListener('submit', event => {
      if (form.checkValidity()) return;
      event.preventDefault();
      const invalid = [...form.querySelectorAll(':invalid')];
      const heading = document.createElement('h2');
      heading.textContent = 'Client was not saved. Please complete the required fields:';
      const list = document.createElement('ul');
      invalid.forEach(input => {
        openSection(input);
        const item = document.createElement('li');
        const anchor = document.createElement('a');
        anchor.href = '#' + input.id;
        anchor.textContent = `${input.labels?.[0]?.textContent.trim() || input.name}: ${input.validationMessage}`;
        item.append(anchor); list.append(item);
      });
      summary.replaceChildren(heading, list);
      summary.classList.remove('d-none');
      summary.focus();
    });
    if (!summary.classList.contains('d-none')) {
      form.querySelectorAll('[aria-invalid="true"]').forEach(openSection);
      summary.focus();
    }
  }
  const address = root.querySelector('[data-client-create-address]');
  const addressData = document.getElementById('client-create-address-data');
  if (address && addressData && form) {
    const data = JSON.parse(addressData.textContent || '{}');
    const country = form.elements.namedItem('country');
    const normalize = value => String(value || '').trim().toLowerCase();
    const label = (name, text) => {
      const node = address.querySelector(`[data-address-label="${name}"]`);
      if (!node || !text) return;
      const first = [...node.childNodes].find(child => child.nodeType === Node.TEXT_NODE);
      if (first) first.nodeValue = text.replace(/\s*\(optional\)\s*$/i, '') + ' ';
    };
    const apply = () => {
      const selected = normalize(country?.value);
      const key = (data.netherlandsCountries || []).includes(selected) ? 'netherlands' : (data.sintMaartenCountries || []).includes(selected) ? 'sintMaarten' : 'caribbean';
      const style = (data.styles || {})[key] || {};
      label('street', style.streetLabel); label('district', style.districtLabel); label('postal', style.postalLabel);
      const street = form.elements.namedItem('street_address');
      const postal = form.elements.namedItem('postal_code');
      street?.setAttribute('placeholder', style.streetPlaceholder || '');
      postal?.setAttribute('placeholder', style.postalPlaceholder || '');
      const current = form.elements.namedItem('district');
      if (current) {
        const value = current.tagName === 'SELECT' ? (current.value ? current.selectedOptions[0]?.textContent.trim() || current.value : '') : current.value;
        const tag = style.districtType === 'select' ? 'SELECT' : 'INPUT';
        const next = current.tagName === tag ? current : document.createElement(tag);
        for (const attribute of ['name', 'id', 'aria-invalid', 'aria-describedby', 'required', 'disabled']) {
          if (current.hasAttribute(attribute)) next.setAttribute(attribute, current.getAttribute(attribute));
        }
        next.className = style.districtType === 'select' ? 'form-select' : 'form-control';
        if (next.tagName === 'SELECT') {
          next.replaceChildren();
          let found = false;
          for (const choice of data.districtChoices || []) {
            const option = new Option(choice.label, choice.value);
            if (value && (value === choice.value || value === choice.label)) { option.selected = true; found = true; }
            next.add(option);
          }
          if (value && !found) next.add(new Option(value, value, true, true));
        } else {
          next.type = 'text'; next.maxLength = 100; next.value = value;
          next.placeholder = style.districtPlaceholder || '';
        }
        if (next !== current) current.replaceWith(next);
      }
      const help = address.querySelector('[data-address-help="postal"]');
      if (help && postal) {
        help.textContent = style.postalHelp || '';
        help.classList.toggle('d-none', !style.postalHelp);
        const described = new Set((postal.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
        if (style.postalHelp) described.add(help.id); else described.delete(help.id);
        if (described.size) postal.setAttribute('aria-describedby', [...described].join(' ')); else postal.removeAttribute('aria-describedby');
      }
    };
    country?.addEventListener('change', apply);
    apply();
  }

  const table = root.querySelector('#clientsTable[data-list]');
  if (table) {
    const sort = table.querySelector('[data-client-sort]');
    const direction = table.querySelector('[data-client-sort-direction]');
    // Phoenix/List.js owns the single existing initialization. Its sort handler
    // reads data-sort/data-order from this same visible button at click time.
    sort?.addEventListener('change', () => {
      direction.dataset.sort = sort.value;
      direction.dataset.order = 'asc';
      direction.click();
    });
    direction?.addEventListener('click', () => {
      const order = direction.dataset.order;
      direction.textContent = order === 'asc' ? 'Ascending ↑' : 'Descending ↓';
      direction.dataset.order = order === 'asc' ? 'desc' : 'asc';
      direction.setAttribute('aria-label', order === 'asc' ? 'Sort descending' : 'Sort ascending');
      const feedback = root.querySelector('[data-clients-feedback]');
      if (feedback) feedback.textContent = `Clients sorted by ${sort.selectedOptions[0].textContent}, ${order === 'asc' ? 'ascending' : 'descending'}.`;
    });
    const bulk = table.querySelector('[data-bulk-select]');
    const count = table.querySelector('[data-client-selected-count]');
    const clear = table.querySelector('[data-client-clear-selection]');
    const updateCount = () => {
      const instance = window.phoenix?.BulkSelect?.getInstance(bulk);
      const total = instance?.getSelectedRows().length || 0;
      if (count) count.textContent = `${total} selected`;
      if (clear) clear.disabled = total === 0;
    };
    clear?.addEventListener('click', () => {
      window.phoenix?.BulkSelect?.getInstance(bulk)?.deselectAll();
      updateCount();
      bulk.focus();
    });
    table.addEventListener('change', updateCount);
    updateCount();
  }

  const invoiceTitle = root.querySelector('#client-invoices-title');
  if (invoiceTitle) { invoiceTitle.setAttribute('role', 'heading'); invoiceTitle.setAttribute('aria-level', '2'); }
  root.querySelectorAll('#client-invoices article h5').forEach(heading => { heading.setAttribute('role', 'heading'); heading.setAttribute('aria-level', '3'); });

  const archiveForm = root.querySelector('[data-client-archive]');
  const dialog = root.querySelector('#clientsArchiveModal');
  if (archiveForm && dialog && window.bootstrap?.Modal) {
    const modal = bootstrap.Modal.getOrCreateInstance(dialog);
    const confirm = dialog.querySelector('[data-client-archive-confirm]');
    const trigger = archiveForm.querySelector('[type="submit"]');
    let approved = false;
    archiveForm.addEventListener('submit', event => {
      if (approved) { approved = false; return; }
      event.preventDefault(); confirm.disabled = false; modal.show();
    });
    dialog.addEventListener('shown.bs.modal', () => dialog.querySelector('[data-bs-dismiss="modal"]:not(.btn-close)').focus());
    dialog.addEventListener('hidden.bs.modal', () => trigger.focus());
    confirm.addEventListener('click', () => {
      if (confirm.disabled) return;
      confirm.disabled = true; approved = true; archiveForm.requestSubmit(trigger);
    });
  }
});
