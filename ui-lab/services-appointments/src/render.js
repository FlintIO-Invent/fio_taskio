import {escape as e, icon, badge, link, shell} from '../../design-system/components.js';
import {filterOptions} from './fixtures.js';

const listLink = (text,query='',cls='') => link('appointment_list',`/appointments/${query}`,text,cls,'data-local-list');
function navigation(d) {
  const items = [link('agent_dashboard','/crm/agent/dashboard/',`${icon('grid')}<span>Overview</span>`),
    listLink(`${icon('calendar')}<span>Appointments</span>`,'','is-current'),
    ...(d.requestRead ? [listLink(`${icon('clock')}<span>Needs follow-up</span>`,'?state=needs_follow_up')] : []),
    link('staff_client_list','/crm/staff/clients/',`${icon('users')}<span>Clients</span>`)];
  return `<nav aria-label="Services workspace"><p class="nav-label">Workspace</p><ul class="menu mm-menu">${items.map((item,i) => `<li>${i===1 ? item.replace('data-local-list','aria-current="page" data-local-list') : item}</li>`).join('')}</ul></nav>`;
}
function field(key,label,values,errors) {
  const value = values[key] || '';
  const error = errors[key];
  return `<div class="filter-field"><label class="field-label" for="id_${key}">${label}</label><select class="select" id="id_${key}" name="${key}" ${error ? `aria-invalid="true" aria-describedby="${key}-error"` : ''}>${!filterOptions[key].some(([v]) => v===value) ? `<option value="${e(value)}" selected>Unavailable selection</option>` : ''}${filterOptions[key].map(([v,text]) => `<option value="${e(v)}" ${v===value ? 'selected' : ''}>${e(text)}</option>`).join('')}</select>${error ? `<p class="field-error" id="${key}-error" role="alert">${e(error)}</p>` : ''}</div>`;
}
function filters(values,errors) {
  const advanced = ['source','classification','staff','service'].some(key => values[key] || errors[key]);
  return `<section class="card mm-panel filter-panel" aria-label="Workspace filters"><form method="get" action="/appointments/" data-preview-filter novalidate>
    <div class="quick-filters"><div class="filter-field search-field"><label class="field-label" for="id_q">Search</label><input class="input" id="id_q" name="q" type="search" maxlength="160" value="${e(values.q)}" placeholder="Client, service or booking" ${errors.q ? 'aria-invalid="true" aria-describedby="q-error"' : ''}>${errors.q ? `<p class="field-error" id="q-error" role="alert">${e(errors.q)}</p>` : ''}</div>
    ${field('state','State',values,errors)}<div class="action-group filter-actions"><button class="btn mm-primary" type="submit">Filter</button>${listLink('Reset','','btn mm-secondary')}</div></div>
    <details class="advanced-filters" ${advanced ? 'open' : ''}><summary>More filters ${icon('chevron-down')}</summary><div class="advanced-grid">${field('source','Source',values,errors)}${field('classification','Client classification',values,errors)}${field('staff','Staff',values,errors)}${field('service','Service',values,errors)}</div></details>
  </form></section>`;
}
const tone = state => ({Scheduled:'info',Completed:'success',Cancelled:'error','No Show':'attention','Needs follow-up':'attention'}[state] || '');
function row(r,d) {
  const route = r.kind==='request' ? 'staff_lead_detail' : 'appointment_detail';
  const url = r.kind==='request' ? `/crm/staff/leads/${r.id}/` : `/appointments/${r.id}/`;
  const edit = r.kind==='request' ? d.canCreateRequest : d.canCreateAppointment;
  return `<tr data-entry-kind="${r.kind}" data-entry-id="${r.id}">
    <td data-label="Booking / request" class="entry-title">${link(route,url,e(r.title),'record-link')}<span class="record-meta">${r.kind==='request' ? 'Request' : 'Appointment'} · ${e(r.source)}</span></td>
    <td data-label="Client">${r.clientId ? link('staff_client_detail',`/crm/staff/clients/${r.clientId}/`,e(r.client),'client-link') : `<span class="client-name">${e(r.client)}</span>`}<span class="record-meta">${e(r.classification)}</span></td>
    <td data-label="Service / staff"><span>${e(r.service)}</span><span class="record-meta">${r.kind==='appointment' ? `Staff: ${e(r.staff)}` : 'Unassigned'}</span></td>
    <td data-label="Time" class="entry-time">${r.instant ? `<time datetime="${r.instant}">${e(r.time)}</time><span class="record-meta">to <time datetime="${r.endInstant}">${e(r.end)}</time></span>` : `<span>Not scheduled</span>${r.preferred ? `<span class="record-meta">Preferred: ${e(r.preferred)}</span>` : ''}`}</td>
    <td data-label="State" class="entry-state">${badge(r.state,tone(r.state))}${r.requestStatus ? `<span class="record-meta">${e(r.requestStatus)}</span>` : ''}</td>
    <td data-label="Actions" class="entry-actions"><div class="action-group">${link(route,url,'View','btn mm-quiet',`aria-label="View ${e(r.title)}"`)}${edit ? link(r.kind==='request' ? 'staff_lead_update' : 'appointment_update',`${url}edit/`,'Edit','btn mm-secondary',`aria-label="Edit ${e(r.title)}"`) : ''}</div></td>
  </tr>`;
}
export function results(d,projection) {
  const {rows:visible,total,page,pages,errors} = projection;
  if (d.locked) return `<div class="mm-empty">${icon('lock')}<h2>Appointments workspace unavailable</h2><p>Appointment or service-request read access is required.</p></div>`;
  if (d.pending) return `<div class="mm-empty" aria-busy="true">${icon('clock')}<h2>Loading preview</h2><p>Waiting for the supplied presentation state.</p></div>`;
  return `<header class="mm-panel-header"><div><h2>Bookings & requests</h2><p class="supporting">${total} ${total===1 ? 'record' : 'records'}${pages>1 ? ` · Page ${page} of ${pages}` : ''}</p></div><p class="supporting time-zone">${icon('clock')} ${e(d.timezone)}</p></header>
    ${d.error ? `<div class="mm-notice error" role="alert">${icon('alert-circle')}<div><p>Could not refresh the preview. Previously supplied records remain visible.</p><button type="button" class="btn mm-secondary" data-retry>Retry preview</button></div></div>` : ''}
    ${visible.length ? `<div class="records-container"><table class="table records" data-unified-workspace><caption class="sr-only">Bookings and requests · ${e(d.timezone)}</caption><thead><tr><th scope="col">Booking / request</th><th scope="col">Client</th><th scope="col">Service / staff</th><th scope="col">Time</th><th scope="col">State</th><th scope="col">Actions</th></tr></thead><tbody>${visible.map(r=>row(r,d)).join('')}</tbody></table></div>` : `<div class="mm-empty">${icon(Object.keys(errors).length ? 'alert-circle' : 'calendar')}<h3>${Object.keys(errors).length ? 'Check the highlighted filters' : 'No bookings or requests match these filters.'}</h3><p>${Object.keys(errors).length ? 'Correct the selection, then filter again.' : 'Try another search or reset your filters.'}</p>${listLink('Reset filters','','btn mm-secondary')}</div>`}
    ${pages>1 ? `<nav class="pagination-bar" aria-label="Workspace pages"><span>Page ${page} of ${pages} · 50 per page</span><div class="action-group">${page>1 ? `<a href="?page=${page-1}" data-page="${page-1}" class="btn mm-secondary">Previous</a>` : ''}${page<pages ? `<a href="?page=${page+1}" data-page="${page+1}" class="btn mm-secondary">Next</a>` : ''}</div></nav>` : ''}`;
}
export function render(d,projection,values) {
  const actions = `${d.canCreateAppointment ? link('appointment_create','/appointments/create/',`${icon('calendar')}New Appointment`,'btn mm-primary') : ''}${d.canCreateRequest ? link('staff_lead_create','/crm/staff/leads/create/','Create Request','btn mm-secondary') : ''}`;
  return shell({title:'Appointments',subtitle:'Bookings and requests for your workspace.',role:d.role,navigation:navigation(d),actions,
    content:`${d.notice ? `<div class="mm-notice" role="status">${icon('lock')}<span>${e(d.notice)}</span></div>` : ''}
    ${!d.locked ? `<nav class="workspace-tabs" aria-label="Appointments views">${listLink('All bookings & requests','','workspace-tab')}${d.requestRead ? listLink('Needs follow-up','?state=needs_follow_up','workspace-tab') : ''}</nav>${filters(values,projection.errors)}` : ''}
    <section class="card mm-panel results-panel" id="workspace-results" aria-label="Workspace records">${results(d,projection)}</section>
    ${d.requestRead ? link('staff_lead_list','/crm/staff/leads/?status_group=all','Request history','btn mm-quiet history-link') : ''}
    <p id="filter-feedback" class="sr-only" role="status" aria-live="polite"></p>`});
}
