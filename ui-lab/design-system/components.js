import {icons} from '../services-dashboard/shared/icons.js';

export const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const icon = name => `<span class="mm-icon">${icons[name] || icons.circle}</span>`;
export const badge = (text, tone = '') => `<span class="badge mm-badge ${escape(tone)}">${escape(text)}</span>`;
export function link(route, path, text, cls = '', attrs = '') {
  return `<a href="${escape(path)}" data-route="${escape(route)}" class="${escape(cls)}" ${attrs}>${text}</a>`;
}

// Callers supply already-authorized navigation and actions. No role policy here.
export function shell({title, subtitle, role, navigation, actions, content}) {
  return `<a class="skip-link" href="#main-content">Skip to content</a>
    <header class="navbar topbar"><div class="brand-zone">
      <button class="btn mm-icon-button menu-trigger" type="button" data-open="navigationDrawer" aria-controls="navigationDrawer" aria-expanded="false" aria-label="Open navigation">${icon('menu')}<span>Menu</span></button>
      ${link('agent_dashboard','/crm/agent/dashboard/',`<span class="brand-mark"><img src="./assets/motionmate-logo.svg" width="36" height="36" alt=""></span><span class="brand-word">Motionmate</span><span class="vertical-label">Services</span>`,'brand','aria-label="Motionmate Services home"')}
    </div><div class="topbar-actions">
      <button class="btn mm-icon-button" type="button" data-theme-toggle aria-label="Switch to dark theme">${icon('moon')}</button>
      <div class="account-container"><button class="btn account-button" type="button" data-account-toggle aria-label="Account menu" aria-expanded="false" aria-controls="account-menu">AM</button>
      <div id="account-menu" class="account-popover" hidden><p>Alex Morgan<br><span class="supporting">${escape(role)}</span></p>${link('logout','/accounts/logout/','Log out')}</div></div>
    </div></header>
    <aside class="sidebar"><div class="workspace-identity"><span class="workspace-monogram">H</span><div><strong>Harbour Services</strong><small>Services workspace</small></div></div>${navigation}</aside>
    <main class="mm-page" id="main-content" tabindex="-1"><div class="page-content">
      <header class="page-header"><div><p class="eyebrow">Motionmate Services</p><h1>${escape(title)}</h1><p class="supporting">${escape(subtitle)}</p></div><div class="action-group">${actions}</div></header>${content}
    </div></main>
    <footer class="lab-note">UI preview · Synthetic records · No changes are saved</footer>
    <dialog id="navigationDrawer" class="mm-dialog drawer-dialog" aria-labelledby="navigation-title"><header class="dialog-header"><h2 id="navigation-title">Services workspace</h2><button class="btn mm-icon-button" type="button" data-close aria-label="Close navigation">${icon('x')}</button></header><div class="dialog-body">${navigation}</div></dialog>
    <dialog id="routePreview" class="mm-dialog" aria-labelledby="route-title"><header class="dialog-header"><h2 id="route-title">Navigation preview</h2><button class="btn mm-icon-button" type="button" data-close aria-label="Close preview">${icon('x')}</button></header><div class="dialog-body"><p>This opens the existing workflow after a separately authorized implementation.</p><dl><dt>Named route</dt><dd id="route-name"></dd><dt>Destination</dt><dd id="route-path"></dd></dl><p>No application request was sent. Close to return to your current filters.</p></div></dialog>`;
}

export function mountChrome() {
  const triggers = new Map();
  const accountButton = document.querySelector('[data-account-toggle]');
  const account = document.getElementById('account-menu');
  const closeAccount = (returnFocus = false) => {
    if (account.hidden) return;
    account.hidden = true;
    accountButton.setAttribute('aria-expanded', 'false');
    if (returnFocus) accountButton.focus();
  };
  const open = (id, trigger) => {
    closeAccount();
    triggers.set(id, trigger);
    document.getElementById(id).showModal();
    document.documentElement.style.overflow = 'hidden';
    if (id === 'navigationDrawer') document.querySelector('[data-open]').setAttribute('aria-expanded','true');
  };
  const close = dialog => dialog.close();
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('close', () => {
      document.documentElement.style.overflow = '';
      document.querySelector('[data-open]').setAttribute('aria-expanded','false');
      const trigger = triggers.get(dialog.id);
      if (trigger?.isConnected && trigger.checkVisibility()) trigger.focus();
    });
    dialog.addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const controls = [...dialog.querySelectorAll('button,a[href],input,select,[tabindex="0"]')].filter(el => !el.disabled && el.checkVisibility());
      if (!controls.length) return;
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1).focus(); }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0].focus(); }
    });
  });
  const themeButton = document.querySelector('[data-theme-toggle]');
  const updateThemeLabel = () => {
    const dark = document.documentElement.dataset.bsTheme === 'dark';
    themeButton.setAttribute('aria-label',`Switch to ${dark ? 'light' : 'dark'} theme`);
    themeButton.innerHTML = icon(dark ? 'sun' : 'moon');
  };
  updateThemeLabel();
  themeButton.addEventListener('click', () => {
    const next = document.documentElement.dataset.bsTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.bsTheme = next;
    document.documentElement.dataset.theme = `motionmate-${next}`;
    try { localStorage.setItem('mm-services-lab-theme', next); } catch { /* OS/URL preference still works. */ }
    updateThemeLabel();
  });
  accountButton.addEventListener('click', () => {
    account.hidden = !account.hidden;
    accountButton.setAttribute('aria-expanded',String(!account.hidden));
    if (!account.hidden) account.querySelector('a').focus();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeAccount(true); });
  document.addEventListener('click', event => {
    if (!event.target.closest('.account-container')) closeAccount();
    const opener = event.target.closest('[data-open]');
    if (opener) open(opener.dataset.open, opener);
    const closer = event.target.closest('[data-close]');
    if (closer) close(closer.closest('dialog'));
  });
  document.addEventListener('focusin', event => { if (!event.target.closest('.account-container')) closeAccount(); });
  function previewRoute(anchor) {
    document.getElementById('route-name').textContent = anchor.dataset.route;
    document.getElementById('route-path').textContent = anchor.getAttribute('href');
    const drawer = document.getElementById('navigationDrawer');
    if (drawer.open) {
      const trigger = document.querySelector('[data-open]');
      drawer.addEventListener('close', () => open('routePreview',trigger), {once:true});
      close(drawer);
    } else open('routePreview', anchor);
  }
  return {previewRoute};
}
