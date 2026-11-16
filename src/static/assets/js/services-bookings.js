/* Progressive presentation only; existing Django forms own mutations. */
document.addEventListener('DOMContentLoaded', () => {
  if (!document.body.classList.contains('mm-services-bookings-page')) return;
  const root = document.querySelector('.mm-sb-content');
  if (!root) return;
  root.querySelectorAll('.mm-sb-related').forEach(details => {
    details.addEventListener('keydown', event => {
      if (event.key === 'Escape') { details.open = false; details.querySelector('summary').focus(); }
    });
  });
  const errorSummary = root.querySelector('[data-booking-error-summary]');
  if (errorSummary) errorSummary.focus();
  const dialog = root.querySelector('[data-booking-status-dialog]');
  if (!dialog || !window.bootstrap?.Modal) return;
  const modal = bootstrap.Modal.getOrCreateInstance(dialog);
  const confirm = dialog.querySelector('[data-booking-status-confirm]');
  let pending = null;
  let approved = null;
  root.querySelectorAll('[data-booking-status-form]').forEach(form => {
    form.addEventListener('submit', event => {
      if (approved === form) { approved = null; return; }
      event.preventDefault();
      pending = {form, submitter: event.submitter || form.querySelector('[type="submit"]')};
      dialog.querySelector('#bookingStatusTitle').textContent = pending.submitter.textContent.trim() + '?';
      confirm.textContent = pending.submitter.textContent.trim();
      confirm.disabled = false;
      modal.show();
    });
  });
  dialog.addEventListener('shown.bs.modal', () => dialog.querySelector('[data-bs-dismiss="modal"]:not(.btn-close)').focus());
  dialog.addEventListener('hidden.bs.modal', () => { pending?.submitter.focus(); pending = null; });
  confirm.addEventListener('click', () => {
    if (!pending || confirm.disabled) return;
    confirm.disabled = true;
    approved = pending.form;
    pending.form.requestSubmit(pending.submitter);
  });
});
