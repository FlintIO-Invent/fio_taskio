document.addEventListener('DOMContentLoaded', () => {
  if (!document.body.classList.contains('logistics-workspace')) return;
  const narrow = window.matchMedia('(max-width: 991.98px)');
  // Move existing nodes, including their labels and form state, so keyboard and
  // screen-reader order matches the mobile hierarchy. Restore desktop positions.
  const arrange = (container, selectors) => {
    if (!container) return;
    const slots = selectors.map(selector => container.querySelector(selector)).filter(Boolean).map(node => {
      const anchor = document.createComment('desktop position');
      node.before(anchor);
      return {node, anchor};
    });
    const update = () => slots.forEach(({node, anchor}) => {
      if (narrow.matches) container.append(node);
      else anchor.after(node);
    });
    update();
    narrow.addEventListener('change', update);
  };
  arrange(document.querySelector('.logistics-dashboard'), [
    '.mobile-dashboard-kpis', '.mobile-dashboard-quick', '.mobile-dashboard-attention',
    '.mobile-dashboard-shipments', '.mobile-dashboard-activity', '.mobile-dashboard-status',
    '.mobile-dashboard-finance',
  ]);
  arrange(document.querySelector('.mobile-shipment-fields'), [
    '.mobile-shipment-transport', '.mobile-shipment-route', '.mobile-shipment-assignment',
    '.mobile-shipment-schedule', '.mobile-shipment-notes', '.mobile-form-actions',
  ]);
  if (narrow.matches) {
    document.querySelectorAll('[autofocus]').forEach(input => {
      input.removeAttribute('autofocus');
      if (document.activeElement === input) input.blur();
    });
  }
  // Keep the original rows so List.js filtering, sorting and pagination still work.
  document.querySelectorAll('.logistics-mobile-table').forEach(table => {
    table.setAttribute('role', 'table');
    const headings = [...table.querySelectorAll('thead th')].map(heading => {
      const copy = heading.cloneNode(true);
      copy.querySelectorAll('.dropdown-menu, button').forEach(item => item.remove());
      return copy.textContent.trim();
    });
    table.querySelectorAll('thead, tbody, tfoot').forEach(group => group.setAttribute('role', 'rowgroup'));
    table.querySelectorAll('tr').forEach(row => {
      row.setAttribute('role', 'row');
      [...row.children].forEach((cell, index) => {
        cell.setAttribute('role', cell.tagName === 'TH' ? 'columnheader' : 'cell');
        if (cell.tagName === 'TD' && cell.colSpan === 1 && row.parentElement.tagName === 'TBODY') {
          cell.dataset.label = headings[index] || '';
        }
      });
    });
  });
  const links = [...document.querySelectorAll('.navbar-vertical a.nav-link')]
    .filter(link => new URL(link.href).origin === location.origin && !link.hash);
  const exact = links.find(link => new URL(link.href).pathname === location.pathname);
  const parent = links.filter(link => {
    const path = new URL(link.href).pathname.replace(/(?:list|all)\/$/, '');
    return location.pathname.startsWith(path);
  })
    .sort((a, b) => b.pathname.length - a.pathname.length)[0];
  const active = exact || parent;
  if (active) {
    active.classList.add('active');
    if (exact) active.setAttribute('aria-current', 'page');
    else active.setAttribute('aria-current', 'location');
    let section = active.closest('.collapse');
    while (section) {
      section.classList.add('show');
      document.querySelector(`[aria-controls="${section.id}"]`)?.setAttribute('aria-expanded', 'true');
      section = section.parentElement.closest('.collapse:not(#navbarVerticalCollapse)');
    }
  }
  // Server errors are authoritative and stay reachable after a rejected write.
  const error = [...document.querySelectorAll('[data-logistics-form-errors]')].find(item => item.getClientRects().length);
  if (error) error.focus();
  document.querySelectorAll('input[name$="phone"], input[name$="phone_number"]').forEach(input => {
    input.type = 'tel';
    input.setAttribute('inputmode', 'tel');
  });
  document.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.cancelConfirmation) return;
    const status = event.submitter?.name === 'status' ? event.submitter.value : form.elements.namedItem('status')?.value;
    if (status === 'CANCELLED' && !window.confirm(form.dataset.cancelConfirmation)) {
      event.preventDefault();
    }
  });
});
