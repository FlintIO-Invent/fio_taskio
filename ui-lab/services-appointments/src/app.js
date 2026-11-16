import {fixture,filterOptions} from './fixtures.js';
import {render,results} from './render.js';
import {mountChrome,escape as e} from '../../design-system/components.js';
import * as ui from './journey.js';

const params=new URLSearchParams(location.search);
const aliases={'no-slots':'populated','conflict':'populated','uncertain':'populated'};
const scenario=params.get('scenario')||'populated';
const d=ui.enrich(fixture(aliases[scenario]||scenario));
d.noSlots=scenario==='no-slots';
const keys=['q','state','source','classification','staff','service'];
let values=Object.fromEntries(keys.map(k=>[k,params.get(k)||'']));
if(!params.has('state')&&params.has('status')) values.state=params.get('status');
if(d.invalid&&!params.has('source')) values.source='missing';
let page=Number(params.get('page'))||1;
let view=params.get('view')||(['no-slots','conflict','uncertain'].includes(scenario)?'public':'workspace');
let id=Number(params.get('id'))||(view==='request'||view==='completion'?701:801);
let mode=params.get('mode')||'create';
let step=0,flash='',errors={},outcomeKind='scheduled',pendingStatus='',proposal='',newId=2000;
const drafts=new Map();
const p=ui.emptyPublic();
if(!d.publicAppointments) p.booking_intent='book_later';
let snapshot=null;
const archivedRequests=new Map([[710,d.linkedRequest]]);
const publicPreviews=new Map();
const publicClients=new Map([['jamie@example.test',{id:501,classification:'Active Client',filter:'ACTIVE'}],['taylor@example.test',{id:502,classification:'Prospect',filter:'PROSPECT'}]]);
if(view==='outcome'){Object.assign(p,{date:'2026-11-16',time:'09:00',staff_member:'91',first_name:'Jamie',last_name:'Rivera',email:'jamie@example.test',street_address:'12 Harbour View Road'});outcomeKind=params.get('result')==='request'?'request':'scheduled';p.booking_intent=outcomeKind==='scheduled'?'book_now':'book_later';}
const firstAppointment=()=>d.rows.find(r=>r.kind==='appointment');
const record=()=>d.rows.find(r=>r.id===id&&r.kind===(view==='request'||view==='completion'||(view==='form'&&mode==='from-request')?'request':'appointment'));
const requestRecord=()=>d.rows.find(r=>r.id===id&&r.kind==='request')||archivedRequests.get(id)||null;
function project(){
  const err={};
  if(values.q.length>160)err.q='Use no more than 160 characters.';
  for(const [k,opts]of Object.entries(filterOptions))if(!opts.some(([v])=>v===values[k]))err[k]='Select a valid choice.';
  const filtered=Object.keys(err).length?[]:d.rows.filter(r=>keys.every(k=>!values[k]||(k==='q'?r.search.toLowerCase().includes(values.q.toLowerCase()):r.filter[k]===values[k])));
  const pages=Math.max(1,Math.ceil(filtered.length/50)); page=Math.min(pages,Math.max(1,page));
  return {rows:filtered.slice((page-1)*50,page*50),total:filtered.length,page,pages,errors:err};
}
function appointmentDraft(){
 const key=`${mode}:${mode==='create'?'new':id}`;
 if(!drafts.has(key)){
  const r=mode==='edit'?d.rows.find(r=>r.kind==='appointment'&&r.id===id):null;
  const req=mode==='from-request'?requestRecord():null;
  const local=t=>t?new Date(new Date(t).getTime()-4*3600000).toISOString().slice(0,16):'';
  drafts.set(key,{key,client:String(r?.clientId||req?.clientId||''),title:r?.title||(req?`${req.service} - ${req.title}`:''),service:r?.filter.service||req?.filter?.service||'',staff_member:r?.filter.staff||'',start_time:local(r?.instant),end_time:local(r?.endInstant),location:r?.location||req?.location||'',notes:r?.notes||req?.notes||''});
 }
 return drafts.get(key);
}
function requestDraft(completion=false){
 const key=`${completion?'completion':'request'}:${mode==='edit'||completion?id:'new'}`;
 if(!drafts.has(key)){
  const r=requestRecord();
  drafts.set(key,{requestId:r?.id,first_name:(completion||mode==='edit')?(r?.title?.split(' ')[0]||'Casey'):'',last_name:(completion||mode==='edit')?(r?.title?.split(' ').slice(1).join(' ')||'Laurent'):'',email:(completion||mode==='edit')?r?.email||'':'',phone:(completion||mode==='edit')?r?.phone||'':'',company_name:mode==='edit'?r?.client||'':'',street_address:mode==='edit'?r?.location||'':'',category:'',notes:mode==='edit'?r?.notes||'':'',lead_type:'REQUEST',status:'NEW'});
 }
 return drafts.get(key);
}
function updateUrl(push=false){
 const u=new URL(location.href);
 for(const key of [...keys,'status','page','view','id','mode','result'])u.searchParams.delete(key);
 for(const key of keys)if(values[key])u.searchParams.set(key,values[key]);
 if(page>1)u.searchParams.set('page',page);
 if(view!=='workspace')u.searchParams.set('view',view);
 if(view==='outcome')u.searchParams.set('result',outcomeKind);
 if(view!=='workspace'&&view!=='public'&&view!=='outcome')u.searchParams.set('id',id);
 if(view==='form'||view==='request-form')u.searchParams.set('mode',mode);
 u.searchParams.set('theme',document.documentElement.dataset.bsTheme);
 history[push?'pushState':'replaceState'](null,'',u);
}
const projection=project();
document.getElementById('app').innerHTML=render(d,projection,values)+ui.dialogs();
const main=document.querySelector('main .page-content');
const chrome=mountChrome();
const bar=document.createElement('aside');bar.className='review-bar';bar.setAttribute('aria-label','Prototype review controls');
document.querySelector('main').before(bar);
function reviewControls(){
 const names=[['workspace','Workspace'],['detail','Appointment details'],['form','Create / edit'],['public','Public booking'],['request','Request follow-up']];
 bar.innerHTML=`<details><summary>Interactive prototype <span class="review-pill">Synthetic records only</span></summary><div class="review-controls"><label for="review-screen">Screen</label><select class="select" id="review-screen">${names.map(([v,n])=>`<option value="${v}" ${v===view?'selected':''}>${n}</option>`).join('')}</select><label for="review-scenario">Scenario</label><select class="select" id="review-scenario">${['populated','long','empty','pagination','staff','accountant','viewer','request-only','appointments-only','read-only','locked','invalid','loading','error','no-slots','conflict','uncertain'].map(n=>`<option ${n===scenario?'selected':''}>${n}</option>`).join('')}</select><a class="btn mm-quiet" href="?view=public" data-view="public">Public booking preview</a></div><p>Local simulation only. No real records, database, email, invoices or provider calls. Reload resets all demo changes. ${e(proposal||'D2 status confirmations, D4 handoff, D5 wizard behavior and D6 outcome rendering remain proposals.')}</p>${snapshot?'<button type="button" class="btn mm-secondary" data-proposal-resume>Try proposed scheduling resume (D4)</button>':''}</details>`;
}
function workspace(){const template=document.createElement('template');template.innerHTML=render(d,project(),values);return template.content.querySelector('.page-content').innerHTML;}
function restricted(text){return ui.header('Access restricted','Harbour Services')+ui.notice(text)+ui.go('Back to Appointments','workspace');}
function draw(focus=false){
 document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
 document.body.classList.toggle('public-preview',view==='public'||view==='outcome');
 reviewControls();
 let content='';
 if(d.locked&&view!=='workspace')content=restricted('This workspace is unavailable in the supplied access scenario.');
 else if(view==='workspace')content=workspace();
 else if(view==='detail'){
  const r=d.rows.find(r=>r.kind==='appointment'&&r.id===id)||(!params.has('id')?firstAppointment():null);
  if(r)id=r.id;
  content=d.appointmentRead&&r?ui.appointmentDetail(r,d):restricted('Appointment read access is required.');
 }else if(view==='form'){
  const r=d.rows.find(r=>r.kind==='appointment'&&r.id===id);
  content=d.canCreateAppointment&&(mode!=='from-request'||(d.requestRead&&requestRecord()))?ui.appointmentForm(appointmentDraft(),d,mode,r,mode==='from-request'?requestRecord():null):restricted('Appointment write access is required.');
 }else if(view==='request'){
  const r=requestRecord();content=d.requestRead&&r?ui.requestDetail(r,d):restricted('Request read access is required.');
 }else if(view==='completion')content=d.access.clientWrite&&d.requestRead?ui.requestForm(requestDraft(true),true):restricted('Client completion access is required.');
 else if(view==='request-form')content=d.canCreateRequest?ui.requestForm(requestDraft()):restricted('Request write access is required.');
 else if(view==='public')content=d.publicAvailable?ui.publicBooking(p,step,d):ui.header('Online booking unavailable','Harbour Services')+ui.notice('This workspace is currently read-only. Online booking is temporarily unavailable.');
 else if(view==='outcome')content=ui.outcome(p,outcomeKind);
 else if(view==='client-saved')content=ui.header('Client details saved','No appointment is scheduled yet.')+ui.panel('Client record',`<p>Client information is saved in the synthetic preview. The current application continues to Client Details.</p><div class="action-group">${ui.go('Back to request','request',id)}<a class="btn mm-secondary" href="/crm/staff/clients/${snapshot?.clientId||501}/" data-route="staff_client_detail">View Client</a></div>`);
 else content=workspace();
 main.innerHTML=(flash?ui.notice(flash,'','role="status"'):'')+content;
 if(view==='workspace'){
  document.querySelectorAll('.workspace-tab').forEach(anchor=>{
   const follow=new URL(anchor.href).searchParams.get('state')==='needs_follow_up';
   if(follow===(values.state==='needs_follow_up'))anchor.setAttribute('aria-current','page');else anchor.removeAttribute('aria-current');
  });
  document.querySelectorAll('[data-page]').forEach(anchor=>{
   const query=new URLSearchParams();
   for(const key of keys)if(values[key])query.set(key,values[key]);
   query.set('page',anchor.dataset.page);query.set('scenario',scenario);query.set('theme',document.documentElement.dataset.bsTheme);
   anchor.setAttribute('href',`?${query}`);
  });
  const feedback=document.getElementById('filter-feedback');if(feedback)feedback.textContent=d.locked?'Workspace unavailable.':d.pending?'Loading supplied preview.':`${project().total} records in this synthetic preview.`;
 }

 const root=main.querySelector('form'); if(root&&Object.keys(errors).length)showErrors(root,errors,false);
 const loading=main.querySelector('[aria-busy=true]');if(loading&&d.pending)loading.insertAdjacentHTML('beforeend','<button type="button" class="btn mm-secondary" data-finish-loading>Show supplied records</button>');
 updateUrl();
 window.labProjection=structuredClone(project());window.labState=d;window.labView=view;window.labReady=true;
 document.title=`${main.querySelector('h1')?.textContent||'Appointments'} · Motionmate prototype`;
 if(focus){const heading=main.querySelector(view==='public'?'#step-title':'h1');heading?.setAttribute('tabindex','-1');heading?.focus();}
}
function navigate(next,nextId='',nextMode='',push=true){
 flash='';errors={};view=next;id=Number(nextId)||(next==='request'?701:next==='detail'?firstAppointment()?.id||801:id);mode=nextMode||'create';
 const drawer=document.getElementById('navigationDrawer');if(drawer.open)drawer.close();
 if(push)updateUrl(true);draw(true);
}
function showErrors(form,map,focus=true){
 form.querySelectorAll('[aria-invalid]').forEach(x=>{x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});
 form.querySelectorAll('.field-error').forEach(x=>x.remove());
 const target=form.querySelector('[data-form-errors]');
 target.innerHTML=`<div class="error-summary" role="alert" tabindex="-1"><h3>Check these details</h3><ul>${Object.entries(map).map(([name,msg])=>`<li><a class="error-link" href="#id_${e(name)}">${e(msg)}</a></li>`).join('')}</ul></div>`;
 for(const[name,msg]of Object.entries(map)){
  const input=form.elements.namedItem(name);if(!input||!input.setAttribute)continue;
  input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',`${name}-error`);
  input.insertAdjacentHTML('afterend',`<p class="field-error" id="${name}-error">${e(msg)}</p>`);
 }
 if(focus)target.querySelector('.error-summary').focus();
}
function formErrors(form){const map={};for(const field of form.elements){if(!field.name||field.disabled||field.type==='hidden')continue;if(!field.checkValidity())map[field.name]=`${field.labels?.[0]?.textContent.replace(/\((required|optional)\)/g,'').trim()||field.name}: ${field.validity.valueMissing?'Complete this field.':'Enter a valid value.'}`;}return map;}
function syncForm(form,target){for(const field of form.elements)if(field.name&&field.type!=='submit'&&field.type!=='button'&&field.type!=='radio')target[field.name]=field.type==='checkbox'?field.checked:field.value;}
function busy(form,callback){const b=form.querySelector('[type=submit]');if(b.disabled)return;b.disabled=true;b.setAttribute('aria-busy','true');const label=b.textContent;b.textContent='Saving preview…';setTimeout(()=>{b.disabled=false;b.removeAttribute('aria-busy');b.textContent=label;callback();},450);}
function saveAppointment(form){
 const draft=appointmentDraft();syncForm(form,draft);const err=formErrors(form);
 if(draft.start_time&&draft.end_time&&draft.end_time<=draft.start_time)err.end_time='End must be after Start.';
 if(Object.keys(err).length){showErrors(form,err);return;}
 busy(form,()=>{
  const old=mode==='edit'?d.rows.find(r=>r.id===id&&r.kind==='appointment'):null;
  const req=mode==='from-request'?requestRecord():null;
  const instant=x=>new Date(x+'-04:00').toISOString();
  const r={...(old||{}),id:old?.id||newId++,kind:'appointment',title:draft.title,client:d.clients.find(x=>x[0]===draft.client)?.[1]||'Synthetic Client',clientId:Number(draft.client),classification:old?.classification||req?.classification||'Lead',source:old?.source||req?.source||'Unspecified',staff:ui.staff.find(x=>x[0]===draft.staff_member)?.[1]||'Unassigned',service:ui.services.find(x=>x[0]===draft.service)?.[1]||'Not set',state:old?.state||'Scheduled',time:draft.start_time.replace('T',' · '),end:draft.end_time.replace('T',' · '),instant:instant(draft.start_time),endInstant:instant(draft.end_time),notes:draft.notes,location:draft.location,sourceLeadId:req?.id||old?.sourceLeadId,filter:{state:old?.filter.state||'scheduled',source:old?.filter.source||req?.filter.source||'unknown',classification:old?.filter.classification||req?.filter.classification||'LEAD',staff:draft.staff_member,service:draft.service},search:[draft.title,draft.notes].join(' ')};
  if(old)Object.assign(old,r);else d.rows.push(r);
  if(req){req.linkedId=r.id;archivedRequests.set(req.id,{...req});d.rows=d.rows.filter(x=>x!==req);proposal='D4: request linkage is simulated locally; authoritative application linkage remains unchanged.';}
  view='detail';id=r.id;errors={};flash=old?'Appointment changes saved in this preview.':'Appointment created in this preview.';draw(true);
 });
}
function saveRequest(form,completion=false){
 const draft=requestDraft(completion);syncForm(form,draft);const err=formErrors(form);if(Object.keys(err).length){showErrors(form,err);return;}
 busy(form,()=>{
  if(completion){const req=requestRecord();const clientId=String(newId++);d.clients.push([clientId,`${draft.first_name} ${draft.last_name} · ${draft.company_name}`]);req.ready=true;req.clientId=Number(clientId);req.location=draft.street_address;snapshot={id:req.id,clientId};view='client-saved';proposal='D4: current flow continues to Client Details; the proposed direct scheduling resume is available in review controls.';}
  else{const existing=mode==='edit'?requestRecord():null;const r={kind:'request',id:existing?.id||newId++,title:`${draft.first_name} ${draft.last_name}`,client:draft.company_name,clientId:null,classification:'Unknown',service:ui.services.find(x=>x[0]===draft.category)?.[1]||'Not set',staff:'Unassigned',state:'Needs follow-up',requestStatus:({NEW:'New',CONTACTED:'Contacted',INVOICED:'Invoiced',CLOSED:'Closed'}[draft.status]),source:'Internal',ready:!!draft.street_address,email:draft.email,phone:draft.phone,location:draft.street_address,notes:draft.notes,filter:{state:'needs_follow_up',source:'internal',classification:'unknown',staff:'',service:''},search:`${draft.first_name} ${draft.last_name} ${draft.company_name} ${draft.email} ${draft.phone}`};
   if(existing){r.source=existing.source;r.filter.source=existing.filter.source;Object.assign(existing,r);if(draft.is_active===false||!['NEW','CONTACTED'].includes(draft.status)||draft.lead_type!=='REQUEST'){archivedRequests.set(r.id,{...r,state:'Historical request'});d.rows=d.rows.filter(x=>x!==existing);}}else if(draft.is_active!==false&&draft.lead_type==='REQUEST'&&['NEW','CONTACTED'].includes(draft.status))d.rows.unshift(r);
   view='workspace';flash='Request saved in this preview. No appointment was scheduled.';
  }draw(true);
 });
}
function projectPublicPreview() {
 // Supplied local outcome projection, never an authoritative booking operation.
 const key=JSON.stringify(p);if(publicPreviews.has(key))return;
 const known=publicClients.get(p.email.toLowerCase());
 const clientId=known?known.id:newId++;
 const name=`${p.first_name} ${p.last_name}`.trim();
 if(!known){d.clients.push([String(clientId),p.company_name?`${name} · ${p.company_name}`:name]);publicClients.set(p.email.toLowerCase(),{id:clientId,classification:'Lead',filter:'LEAD'});}
 const req={kind:'request',id:newId++,title:name,client:p.company_name||name,clientId,classification:known?.classification||'Lead',source:'Online',service:ui.services.find(x=>x[0]===p.service)?.[1]||'Not set',state:'Needs follow-up',requestStatus:'New',staff:'Unassigned',ready:true,email:p.email,phone:p.phone,location:p.street_address,notes:p.message,filter:{state:'needs_follow_up',source:'online',classification:known?.filter||'LEAD',staff:'',service:p.service},search:`${name} ${p.company_name} ${p.email} ${p.phone}`};
 if(p.booking_intent==='book_now'){
  const start=new Date(`${p.date}T${p.time}:00-04:00`);
  const end=new Date(start.getTime()+(p.service==='42'?45:60)*60000);
  const localEnd=new Date(end.getTime()-4*3600000).toISOString().slice(0,16).replace('T',' · ');
  const appt={...req,kind:'appointment',id:newId++,title:`${req.service} - ${name}`,sourceLeadId:req.id,state:'Scheduled',requestStatus:null,staff:ui.staff.find(x=>x[0]===p.staff_member)?.[1],instant:start.toISOString(),endInstant:end.toISOString(),time:`${p.date} · ${p.time}`,end:localEnd,filter:{...req.filter,state:'scheduled',staff:p.staff_member}};
  req.linkedId=appt.id;archivedRequests.set(req.id,req);d.rows.push(appt);
 }else d.rows.unshift(req);
 publicPreviews.set(key,true);
}
function validatePublic(form){
 syncForm(form,p);const err=formErrors(form);
 if(step===1&&p.booking_intent==='book_now'&&(!p.date||!p.time))err.staff_member='Choose an available day and time before continuing.';
 return err;
}
document.addEventListener('input',event=>{
 const form=event.target.closest('form');if(!form)return;
 if(form.matches('[data-appointment-form]'))syncForm(form,appointmentDraft());
 if(form.matches('[data-public-form]'))syncForm(form,p);
 if(form.matches('[data-completion-form]'))syncForm(form,requestDraft(true));
 if(form.matches('[data-request-form]'))syncForm(form,requestDraft());
});
document.addEventListener('change',event=>{
 const t=event.target;
 if(t.id==='review-screen'){navigate(t.value);return;}
 if(t.id==='review-scenario'){const u=new URL(location.href);u.searchParams.set('scenario',t.value);location.assign(u);return;}
 if(t.closest('[data-public-form]')){
  syncForm(t.form,p);
  if(t.name==='booking_intent'){p.booking_intent=t.value;if(t.value==='book_later'){p.staff_member='';p.date='';p.time='';}proposal='D5: hidden-value clearing is an interaction concept, not a server validation change.';draw();document.querySelector(`[name=booking_intent][value=${p.booking_intent}]`)?.focus();}
  else if(t.name==='client_type'){if(p.client_type==='INDIVIDUAL')p.company_name='';draw();document.getElementById('id_client_type').focus();}
  else if(t.name==='staff_member'){p.date='';p.time='';draw();document.getElementById('id_staff_member').focus();}
  else if(t.name==='country'){draw();document.getElementById('id_country').focus();}
 }
});
document.addEventListener('submit',event=>{
 event.preventDefault();const form=event.target;
 if(form.matches('[data-preview-filter]')){values=Object.fromEntries(keys.map(k=>[k,new FormData(form).get(k)||'']));page=1;draw();const err=project().errors;if(Object.keys(err).length){main.querySelector('details').open=true;showErrors(main.querySelector('form'),err);}else{const h=main.querySelector('#workspace-results h2');h.tabIndex=-1;h.focus();}return;}
 if(form.matches('[data-appointment-form]')){saveAppointment(form);return;}
 if(form.matches('[data-request-form],[data-completion-form]')){saveRequest(form,form.matches('[data-completion-form]'));return;}
 if(form.matches('[data-client-form]')){
  const err=formErrors(form);if(Object.keys(err).length){showErrors(form,err);return;}
  const v=new FormData(form),clientId=String(newId++),label=`${v.get('new_client-first_name')} ${v.get('new_client-last_name')} · ${v.get('new_client-company_name')}`;
  d.clients.push([clientId,label]);const draft=appointmentDraft();draft.client=clientId;draft.clientMessage='Client saved and selected in this preview. Your appointment draft is retained.';
  document.getElementById('draftClientModal').close();draw();document.getElementById('id_client').focus();form.reset();return;
 }
 if(form.matches('[data-public-form]')){
  const err=validatePublic(form);if(Object.keys(err).length){showErrors(form,err);return;}
  if(step<3){errors={};step++;draw(true);return;}
  if(scenario==='conflict'&&p.booking_intent==='book_now'){step=1;errors={staff_member:'That staff member is already booked at the selected time. Choose another supplied slot.'};draw(true);return;}
  if(scenario==='uncertain'){showErrors(form,{consent:'Unable to confirm the result. Your details are retained; this preview made no application request.'});return;}
  busy(form,()=>{projectPublicPreview();outcomeKind=p.booking_intent==='book_now'?'scheduled':'request';view='outcome';proposal='D6: outcome-specific rendering is a synthetic concept; trusted server context is not implemented.';draw(true);});
 }
});
document.addEventListener('click',event=>{
 const t=event.target;
 const el=t.closest('[data-view]');if(el){event.preventDefault();navigate(el.dataset.view,el.dataset.id,el.dataset.mode);return;}
 const pager=t.closest('[data-page]');if(pager){event.preventDefault();page=Number(pager.dataset.page);draw(true);return;}
 if(t.closest('[data-retry],[data-finish-loading]')){d.error=false;d.pending=false;draw(true);return;}
 const stat=t.closest('[data-status]');if(stat){pendingStatus=stat.dataset.status;document.getElementById('status-title').textContent=`${pendingStatus==='Cancelled'?'Cancel appointment':`Mark ${pendingStatus}`}?`;document.getElementById('status-context').textContent=`${record()?.title} · ${record()?.time} · ${ui.zone}`;document.getElementById('statusDialog').showModal();return;}
 if(t.closest('[data-confirm-status]')){const r=record();if(d.canCreateAppointment&&r?.state==='Scheduled'){r.state=pendingStatus;r.filter.state=({Completed:'completed','No Show':'no_show',Cancelled:'cancelled'}[pendingStatus]);flash=`${pendingStatus} shown in the local preview. No real appointment changed.`;}draw(true);return;}
 if(t.closest('[data-proposal-resume]')){const reqId=snapshot.id;snapshot=null;navigate('form',reqId,'from-request');return;}
 const date=t.closest('[data-book-date]');const time=t.closest('[data-book-time]');if(date||time){if(date){p.date=date.dataset.bookDate;p.time='';}else p.time=time.dataset.bookTime;const key=date?'data-book-date':'data-book-time',value=date?p.date:p.time;draw();document.querySelector(`[${key}="${value}"]`)?.focus();return;}
 if(t.closest('[data-public-prev]')){step=Math.max(0,step-1);errors={};draw(true);return;}
 const tab=t.closest('[data-step]');if(tab){const next=Number(tab.dataset.step);if(next>step){const form=main.querySelector('form');const err=validatePublic(form);if(Object.keys(err).length){showErrors(form,err);return;}if(next>step+1)return;}step=next;errors={};draw(true);return;}
 const anchor=t.closest('[data-route]');if(!anchor)return;event.preventDefault();
 const route=anchor.dataset.route;const path=new URL(anchor.href).pathname;const recordId=Number(path.match(/\/(\d+)\//)?.[1]);
 if(route==='appointment_create')navigate('form');
 else if(route==='staff_lead_create')navigate('request-form');
 else if(route==='appointment_detail')navigate('detail',recordId);
 else if(route==='appointment_update')navigate('form',recordId,'edit');
 else if(route==='staff_lead_detail')navigate('request',recordId);
 else if(route==='staff_lead_update')navigate('request-form',recordId,'edit');
 else if(route==='appointment_list'){
  const u=new URL(anchor.href);values=Object.fromEntries(keys.map(k=>[k,u.searchParams.get(k)||'']));page=1;navigate('workspace');
 }else chrome.previewRoute(anchor);
});
document.addEventListener('click',event=>{if(event.target.closest('[data-external-contact]')){event.preventDefault();flash='Contact link preview only. No message or call was started.';draw();}});
document.addEventListener('auxclick',event=>{if(event.target.closest('a[data-route],a[data-view],a[data-page]'))event.preventDefault();});
window.addEventListener('popstate',()=>{const q=new URLSearchParams(location.search);view=q.get('view')||'workspace';id=Number(q.get('id'))||801;mode=q.get('mode')||'create';values=Object.fromEntries(keys.map(k=>[k,q.get(k)||'']));page=Number(q.get('page'))||1;errors={};draw(true);});
draw();

document.addEventListener('keydown',event=>{if(event.key==='Escape'){const menu=document.querySelector('.context-menu[open]');if(menu){menu.open=false;menu.querySelector('summary').focus();}}});
document.addEventListener('click',event=>{if(!event.target.closest('.context-menu'))document.querySelectorAll('.context-menu[open]').forEach(menu=>{menu.open=false;});});
