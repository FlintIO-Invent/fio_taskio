import {fixture,filterOptions} from './fixtures.js';
import {render,results} from './render.js';
import {mountChrome} from '../../design-system/components.js';

const params = new URLSearchParams(location.search);
const d = fixture(params.get('scenario') || 'populated');
const keys = ['q','state','source','classification','staff','service'];
let values = Object.fromEntries(keys.map(key => [key,params.get(key) || '']));
// Existing bookmarked status is accepted only when state is absent.
if (!params.has('state') && params.get('status')) values.state = params.get('status');
if (d.invalid && !params.has('source')) values.source = 'missing';
let page = Number(params.get('page')) || 1;

// Filter only supplied fixture metadata. No ORM, classification inference,
// eligibility, scheduling, financial or authorization algorithm is implemented.
function project() {
  const errors = {};
  if (values.q.length > 160) errors.q = 'Ensure this value has at most 160 characters.';
  for (const [key,options] of Object.entries(filterOptions)) {
    if (!options.some(([value]) => value===values[key])) errors[key] = 'Select a valid choice. That choice is not one of the available choices.';
  }
  const filtered = Object.keys(errors).length ? [] : d.rows.filter(row => keys.every(key => !values[key] || (key==='q' ? row.search.toLowerCase().includes(values.q.toLowerCase()) : row.filter[key]===values[key])));
  const pages = Math.max(1,Math.ceil(filtered.length/50));
  page = Math.min(pages,Math.max(1,Math.trunc(page)));
  return {rows:filtered.slice((page-1)*50,page*50),total:filtered.length,page,pages,errors};
}
let projection = project();
document.getElementById('app').innerHTML = render(d,projection,values);
const chrome = mountChrome();
function updateUrl() {
  const next = new URL(location.href);
  for (const key of [...keys,'status','page']) next.searchParams.delete(key);
  for (const key of keys) if (values[key]) next.searchParams.set(key,values[key]);
  if (page>1) next.searchParams.set('page',page);
  history.replaceState(null,'',next);
}
function refresh(focusResults=false) {
  projection = project();
  document.getElementById('workspace-results').innerHTML = results(d,projection);
  document.querySelectorAll('.workspace-tab').forEach(anchor => {
    const followup = new URL(anchor.href).searchParams.get('state') === 'needs_follow_up';
    if (followup === (values.state==='needs_follow_up')) anchor.setAttribute('aria-current','page'); else anchor.removeAttribute('aria-current');
  });
  updateUrl();
  document.getElementById('filter-feedback').textContent = d.locked ? 'Workspace unavailable.' : d.pending ? 'Loading supplied preview.' : `${projection.total} records shown in the synthetic preview.`;
  if (focusResults) {
    const heading = document.querySelector('#workspace-results h2,#workspace-results h3');
    heading.setAttribute('tabindex','-1'); heading.focus();
  }
  // Supply the real pagination query contract, including all current filters.
  document.querySelectorAll('[data-page]').forEach(anchor => {
    const query = new URLSearchParams();
    for (const key of keys) if (values[key]) query.set(key,values[key]);
    query.set('page',anchor.dataset.page); anchor.setAttribute('href',`?${query}`);
  });
  window.labProjection = structuredClone(projection);
}
document.addEventListener('submit', event => {
  event.preventDefault();
  if (!event.target.matches('[data-preview-filter]')) return;
  values = Object.fromEntries(keys.map(key => [key,new FormData(event.target).get(key) || '']));
  page=1;
  // Error messages already present in the initial invalid fixture remain until
  // a valid resubmission, mirroring a server rerender without replacing chrome.
  for (const key of keys) {
    const field = document.getElementById(`id_${key}`);
    field?.removeAttribute('aria-invalid'); field?.removeAttribute('aria-describedby');
    document.getElementById(`${key}-error`)?.remove();
  }
  refresh(true);
  for (const [key,error] of Object.entries(projection.errors)) {
    const field=document.getElementById(`id_${key}`);
    field.setAttribute('aria-invalid','true'); field.setAttribute('aria-describedby',`${key}-error`);
    const message=document.createElement('p'); message.id=`${key}-error`; message.className='field-error'; message.setAttribute('role','alert'); message.textContent=error; field.after(message);
  }
});
document.addEventListener('click', event => {
  const pager = event.target.closest('[data-page]');
  if (pager) { event.preventDefault(); page=Number(pager.dataset.page); refresh(true); return; }
  const retry = event.target.closest('[data-retry]');
  if (retry) { d.error=false; refresh(true); return; }
  const anchor = event.target.closest('[data-route]');
  if (!anchor) return;
  event.preventDefault();
  if (anchor.hasAttribute('data-local-list') && !anchor.closest('dialog')) {
    const target=new URL(anchor.href);
    values=Object.fromEntries(keys.map(key => [key,target.searchParams.get(key) || ''])); page=1;
    const form=document.querySelector('[data-preview-filter]');
    if (form) for (const key of keys) form.elements.namedItem(key).value=values[key];
    document.querySelectorAll('.field-error').forEach(el=>el.remove());
    document.querySelectorAll('[aria-invalid]').forEach(el=>{el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');});
    refresh();
  } else chrome.previewRoute(anchor);
});
document.addEventListener('auxclick', event => { if (event.target.closest('a[data-route],a[data-page]')) event.preventDefault(); });
refresh();
window.labState = d;
window.labReady = true;
