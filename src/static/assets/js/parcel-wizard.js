(() => {
  document.querySelectorAll('[data-parcel-wizard]').forEach(wizard => {
    const entry = wizard.dataset.parcelWizard === 'entry';
    const form = entry ? wizard.closest('form') : null;
    const panels = Array.from(wizard.querySelectorAll('[data-parcel-wizard-panel]'));
    const steps = Array.from(wizard.querySelectorAll('[data-parcel-wizard-step]'));
    const back = wizard.querySelector('[data-parcel-wizard-back]');
    const next = wizard.querySelector('[data-parcel-wizard-next]');
    const saveButtons = form ? Array.from(form.querySelectorAll('[type="submit"]')) : [];
    let current = 0;
    const decisionForm = wizard.querySelector('[data-payment-decision-form]');
    const paymentIndex = panels.findIndex(panel => panel.id === 'registration-payment');
    const paymentComplete = () => decisionForm?.dataset.paymentComplete === 'true';
    if (decisionForm) {
      const refreshPayment = () => {
        const paid = decisionForm.querySelector('[name="decision"]:checked')?.value === 'paid';
        const receipt = decisionForm.querySelector('[data-payment-receipt-fields]');
        if (receipt) {
          receipt.hidden = !paid;
          receipt.querySelectorAll('input, select, textarea').forEach(field => {
            if (field.name !== 'currency') field.disabled = !paid;
          });
        }
      };
      decisionForm.querySelectorAll('[name="decision"]').forEach(field => {
        field.addEventListener('change', () => {
          decisionForm.dataset.paymentComplete = 'false';
          refreshPayment();
        });
      });
      refreshPayment();
    }

    const fieldLabel = field => field.labels?.[0]?.textContent.trim().replace(/\s*\*$/, '') || field.name;
    const fieldsIn = panel => Array.from(panel.querySelectorAll('input, select, textarea'))
      .filter(field => field.name && field.type !== 'hidden' && !field.disabled);

    const review = () => {
      const summary = wizard.querySelector('[data-parcel-wizard-review]');
      if (!summary) return;
      summary.replaceChildren();
      panels.slice(0, -1).forEach(panel => {
        const group = document.createElement('div');
        group.className = 'border rounded p-3 mb-3';
        const heading = document.createElement('h4');
        heading.className = 'fs-8 mb-3';
        heading.textContent = panel.querySelector('h3').textContent;
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'btn btn-link btn-sm px-0 mb-2';
        edit.textContent = `Edit ${heading.textContent.toLowerCase()}`;
        edit.addEventListener('click', () => show(panels.indexOf(panel)));
        const list = document.createElement('dl');
        list.className = 'row mb-0';
        fieldsIn(panel).forEach(field => {
          if (field.type === 'checkbox' && !field.checked) return;
          if (!field.value) return;
          const label = document.createElement('dt');
          label.className = 'col-sm-5 text-body-secondary fw-normal';
          label.textContent = fieldLabel(field);
          const value = document.createElement('dd');
          value.className = 'col-sm-7';
          value.textContent = field.type === 'checkbox' ? 'Yes' :
            field.tagName === 'SELECT' ? field.selectedOptions[0]?.textContent : field.value;
          list.append(label, value);
        });
        if (!list.children.length) {
          const empty = document.createElement('p');
          empty.className = 'text-body-secondary mb-0';
          empty.textContent = 'No optional details supplied.';
          list.append(empty);
        }
        group.append(heading, edit, list);
        summary.append(group);
      });
    };

    // Navigation changes visibility only. All fields stay in the original POST.
    const show = (index, focus = true) => {
      current = index;
      panels.forEach((panel, i) => { panel.hidden = i !== index; });
      steps.forEach((step, i) => {
        step.classList.toggle('active', i === index);
        if (i === index) step.setAttribute('aria-current', 'step');
        else step.removeAttribute('aria-current');
      });
      back.disabled = index === 0;
      next.hidden = index === panels.length - 1;
      if (entry) {
        saveButtons.forEach(button => { button.hidden = index !== panels.length - 1; });
        form.querySelector('[data-parcel-wizard-actions]').classList.toggle(
          'mobile-form-actions', index === panels.length - 1
        );
        wizard.querySelector('[data-parcel-wizard-save-note]').hidden = index === panels.length - 1;
        if (index === panels.length - 1) review();
        next.textContent = index === panels.length - 2 ? 'Review parcel' : 'Continue';
      }
      wizard.querySelector('[data-parcel-wizard-status]').textContent =
        `Step ${index + 1} of ${panels.length} · ${steps[index].textContent.trim().replace(/^\d+\s*/, '')}`;
      if (focus) panels[index].querySelector('h3').focus();
    };

    const revealField = field => {
      const index = panels.findIndex(panel => panel.contains(field));
      if (index < 0) return;
      show(index, false);
      let details = field.closest('details');
      while (details) {
        details.open = true;
        details = details.parentElement.closest('details');
      }
      const pane = field.closest('.tab-pane');
      if (pane) {
        // Works before Bootstrap has loaded, too.
        pane.parentElement.querySelectorAll('.tab-pane').forEach(tab => {
          tab.classList.toggle('active', tab === pane);
          tab.classList.toggle('show', tab === pane);
        });
        wizard.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
          const active = tab.getAttribute('aria-controls') === pane.id;
          tab.classList.toggle('active', active);
          tab.setAttribute('aria-selected', String(active));
        });
      }
    };

    const focusField = field => {
      revealField(field);
      (field.closest('.choices') || field).focus();
    };

    const validateThrough = index => {
      if (!entry) return true;
      const invalid = panels.slice(0, index + 1).flatMap(fieldsIn)
        .filter(field => field.willValidate && !field.validity.valid);
      const summary = form.querySelector('[data-parcel-browser-errors]');
      if (!invalid.length) {
        summary.classList.add('d-none');
        return true;
      }
      const heading = document.createElement('p');
      heading.className = 'fw-semibold mb-1';
      heading.textContent = 'Check these fields before continuing:';
      const list = document.createElement('ul');
      list.className = 'mb-0';
      invalid.forEach(field => {
        const item = document.createElement('li');
        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'btn btn-link p-0 text-start';
        link.textContent = `${fieldLabel(field)}: ${field.validationMessage}`;
        link.addEventListener('click', () => focusField(field));
        item.append(link);
        list.append(item);
      });
      summary.replaceChildren(heading, list);
      summary.classList.remove('d-none');
      revealField(invalid[0]);
      summary.focus();
      return false;
    };

    const navigate = index => {
      if (index < 0 || index >= panels.length) return;
      if (decisionForm && index > paymentIndex && !paymentComplete()) {
        if (current === paymentIndex) decisionForm.requestSubmit();
        else show(paymentIndex);
        return;
      }
      if (index > current && !validateThrough(index - 1)) return;
      show(index);
      if (!entry) history.pushState(null, '', `#${panels[index].id}`);
    };

    back.addEventListener('click', () => navigate(current - 1));
    next.addEventListener('click', () => navigate(current + 1));
    steps.forEach((step, index) => step.addEventListener('click', event => {
      event.preventDefault();
      navigate(index);
    }));

    if (entry) {
      form.addEventListener('parcel-wizard-reveal', event => revealField(event.detail));
      form.addEventListener('submit', event => {
        // Enter advances the current step; saving requires the review screen.
        if (current < panels.length - 1) {
          event.preventDefault();
          event.stopImmediatePropagation();
          navigate(current + 1);
        } else if (!validateThrough(panels.length - 2)) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      }, true);
    } else {
      // Preserve existing resume, payment and summary deep links.
      const followHash = (focus = true) => {
        const index = panels.findIndex(panel => `#${panel.id}` === window.location.hash);
        if (index >= 0) show(decisionForm && index > paymentIndex && !paymentComplete() ? paymentIndex : index, focus);
      };
      document.addEventListener('click', event => {
        const link = event.target.closest('a[href^="#registration-"]');
        if (!link || link.hasAttribute('data-parcel-wizard-step')) return;
        const index = panels.findIndex(panel => `#${panel.id}` === link.getAttribute('href'));
        if (index >= 0) {
          event.preventDefault();
          navigate(index);
        }
      });
      window.addEventListener('popstate', () => {
        if (window.location.hash) followHash();
        else show(initial);
      });
      window.addEventListener('hashchange', () => followHash());
    }

    const errorField = wizard.querySelector('.invalid-feedback.d-block')?.parentElement
      .querySelector('input, select, textarea');
    const hash = panels.findIndex(panel => `#${panel.id}` === window.location.hash);
    const requested = panels.findIndex(panel => panel.id === wizard.dataset.initialStep);
    let initial = !entry && hash >= 0 && !errorField ? hash : Math.max(0, requested);
    if (decisionForm && initial > paymentIndex && !paymentComplete()) initial = paymentIndex;
    wizard.querySelector('[data-parcel-wizard-nav]').hidden = false;
    wizard.querySelector('[data-parcel-wizard-controls]').hidden = false;
    show(initial, false);
    if (errorField) revealField(errorField);
    const errors = form?.querySelector('[data-logistics-form-errors]');
    if (errors) errors.focus();
  });
})();
