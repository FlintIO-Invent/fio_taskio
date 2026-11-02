document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('draftClientModal');
  if (!modal) return;
  const form = modal.querySelector('[data-draft-client-form]');
  const errorBox = modal.querySelector('[data-draft-client-errors]');
  const submit = form.querySelector('[type="submit"]');
  const status = document.querySelector('[data-draft-client-status]');
  const isLead = modal.dataset.clientDestination === 'lead';

  modal.addEventListener('show.bs.modal', () => {
    errorBox.classList.add('d-none');
    if (isLead) {
      for (const input of form.querySelectorAll('[name^="new_client-"]')) {
        const source = document.getElementById(`id_${input.name.replace('new_client-', '')}`);
        if (source) input.value = source.value;
      }
    }
  });
  modal.addEventListener('shown.bs.modal', () => {
    form.querySelector('[name="new_client-first_name"]').focus();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    errorBox.classList.add('d-none');
    errorBox.replaceChildren();
    submit.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      });
      const data = await response.json();
      if (!response.ok) {
        let hasErrors = false;
        for (const [field, errors] of Object.entries(data.errors || {})) {
          const input = form.elements.namedItem(`new_client-${field}`);
          const label = input?.labels?.[0]?.textContent.replace('*', '').trim();
          for (const error of errors) {
            const item = document.createElement('div');
            item.textContent = `${label ? `${label}: ` : ''}${error.message || error}`;
            errorBox.appendChild(item);
            hasErrors = true;
          }
        }
        if (!hasErrors) errorBox.textContent = 'Please check the client details and try again.';
        errorBox.classList.remove('d-none');
        errorBox.focus();
        return;
      }

      if (isLead) {
        for (const input of form.querySelectorAll('[name^="new_client-"]')) {
          const name = input.name.replace('new_client-', '');
          const target = document.getElementById(`id_${name}`);
          if (target) {
            target.value = data.client[name];
            target.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
        status.textContent = `${data.client.label} saved. Their details are ready for this service request.`;
      } else {
        const select = document.getElementById('id_client');
        select.add(new Option(data.client.label, String(data.client.id), true, true));
        select.dispatchEvent(new Event('change', { bubbles: true }));
        status.textContent = 'New client saved and selected. Continue creating your appointment.';
      }
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      form.reset();
    } catch (error) {
      errorBox.textContent = 'Unable to confirm that the client was saved. Check your connection and client list before trying again.';
      errorBox.classList.remove('d-none');
      errorBox.focus();
    } finally {
      submit.disabled = false;
    }
  });
});
