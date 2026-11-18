import {render,errorsMarkup,field} from './render.js';
import {fixtures,projection,blank,displayName,sections,scenarios} from './fixtures.js';
import {icon} from '../../design-system/components.js';
const query=new URLSearchParams(location.search);
const screens=['list','profile','create','edit','upload','preview','result','draft'];
const m={screen:screens.includes(query.get('screen'))?query.get('screen'):'list',scenario:scenarios.includes(query.get('scenario'))?query.get('scenario'):'populated',clientId:Number(query.get('client')||101),filters:{q:query.get('q')||'',district:query.get('district')||'',is_active:query.get('is_active')||''},rows:[],selected:new Set(),sort:'name',desc:false,page:1,all:false,invoicePage:Number(query.get('invoice_page')||1)===2?2:1,errors:{},draft:blank(),quick:blank(),parent:{title:'Weekly studio maintenance',notes:'Keep the courtyard entrance available.',client:'Alice Thompson'},notice:'',filename:''};
m.rows=fixtures(m.scenario);m.p=projection(m.scenario);m.client=m.rows.find(c=>c.id===m.clientId)||fixtures('populated')[0];
if(m.screen==='edit')m.draft={...m.client};
if(m.scenario==='invalid'&&['create','edit'].includes(m.screen)){m.draft.email='not-an-email';m.errors={email:'Enter a valid email address.',street_address:'This field is required.'};m.draft.street_address='';}
let returnFocus=null;
function project(){
 m.p=projection(m.scenario);m.client=m.rows.find(c=>c.id===m.clientId)||m.client;
 m.filtered=m.rows.filter(c=>{
 const q=m.filters.q.trim().toLowerCase();const active=m.filters.is_active;
 return (!q||['first_name','last_name','email','phone','company_name'].some(k=>c[k].toLowerCase().includes(q)))&&(!m.filters.district||c.district===m.filters.district)&&(!['true','1','false','0'].includes(active)||c.is_active===['true','1'].includes(active));
 });
 const key={name:'first_name',company:'company_name',active:'is_active'}[m.sort]||m.sort;
 m.filtered.sort((a,b)=>String(a[key]).localeCompare(String(b[key]))*(m.desc?-1:1));
 m.pages=Math.max(1,Math.ceil(m.filtered.length/10));m.page=Math.min(m.pages,Math.max(1,m.page));
 m.visible=m.all?m.filtered:m.filtered.slice((m.page-1)*10,m.page*10);
}
function url(){const q=new URLSearchParams({screen:m.screen,scenario:m.scenario,theme:document.documentElement.dataset.bsTheme});if(m.clientId!==101)q.set('client',m.clientId);for(const [k,v]of Object.entries(m.filters))if(v)q.set(k,v);if(m.invoicePage!==1)q.set('invoice_page',m.invoicePage);return `?${q}`;}
function draw({focus=false,historyMode='replace'}={}){
 project();document.documentElement.style.overflow='';document.getElementById('app').innerHTML=render(m);
 if(!m.p.read){document.querySelector('h1').textContent='Clients workspace';document.querySelector('.page-header .supporting').textContent='Motionmate Services';document.querySelector('#archiveDialog')?.remove();document.querySelector('#quickDialog')?.remove();}
 document.title=`${document.querySelector('h1').textContent} · Motionmate Services design v1`;
 updateTheme();history[historyMode==='push'?'pushState':'replaceState']({},'',url());window.labReady=true;
 if(focus)document.querySelector('main').focus();
}
function go(screen,id=101,jump){
 m.notice='';if(screen==='create'&&m.screen!=='create'){m.draft=blank();m.errors={};}if(screen==='edit'&&(m.screen!=='edit'||id!==m.clientId)){m.draft={...(m.rows.find(c=>c.id===id)||m.client)};m.errors={};}
 m.screen=screen;m.clientId=id;draw({focus:true,historyMode:'push'});
 if(jump){const section=document.getElementById(`section-${jump}`);if(section){section.open=true;section.querySelector('textarea,input,select')?.focus();}}
 scrollTo({top:0,behavior:'instant'});
}
function updateTheme(){const b=document.querySelector('[data-theme-toggle]');const dark=document.documentElement.dataset.bsTheme==='dark';b.setAttribute('aria-label',`Switch to ${dark?'light':'dark'} theme`);b.innerHTML=icon(dark?'sun':'moon');}
function openDialog(id,trigger){returnFocus=trigger;document.getElementById(id).showModal();document.documentElement.style.overflow='hidden';if(id==='navigationDrawer')document.querySelector('[data-open]').setAttribute('aria-expanded','true');}
function closeDialog(dialog){dialog.close();document.documentElement.style.overflow='';document.querySelector('[data-open]').setAttribute('aria-expanded','false');if(returnFocus?.isConnected&&returnFocus.checkVisibility())returnFocus.focus();}
function intent(a){document.getElementById('route-name').textContent=a.dataset.route||'Export unavailable';document.getElementById('route-path').textContent=a.getAttribute('href')||'The existing Export control has no implemented action. No export is added by this design.';openDialog('routePreview',a);}
function validate(form,prefix=''){
 const errors={};for(const el of form.querySelectorAll('input:not([type=hidden]),select,textarea')){
 const k=el.name.replace(prefix,'');if(el.required&&!el.value.trim())errors[k]='This field is required.';
 else if(el.value&&!el.validity.valid)errors[k]=el.type==='email'?'Enter a valid email address.':el.type==='url'?'Enter a valid URL.':'Check this value.';
 }return errors;
}
function announce(text){document.getElementById('feedback').textContent=text;}
document.addEventListener('click',event=>{
 const el=event.target.closest('a,button');if(!el)return;
 if(el.matches('[data-theme-toggle]')){const t=document.documentElement.dataset.bsTheme==='dark'?'light':'dark';document.documentElement.dataset.bsTheme=t;document.documentElement.dataset.theme=`motionmate-${t}`;try{localStorage.setItem('mm-services-lab-theme',t);}catch{}updateTheme();history.replaceState({},'',url());return;}
 if(el.matches('[data-account-toggle]')){const pop=document.getElementById('account-menu');pop.hidden=!pop.hidden;el.setAttribute('aria-expanded',String(!pop.hidden));if(!pop.hidden)pop.querySelector('a').focus();return;}
 if(el.dataset.open){openDialog(el.dataset.open,el);return;}
 if(el.hasAttribute('data-close')){closeDialog(el.closest('dialog'));return;}
 if(el.dataset.screen){event.preventDefault();go(el.dataset.screen,Number(el.dataset.id||101),el.dataset.jump);return;}
 if(el.hasAttribute('data-section-link')||el.hasAttribute('data-error-link')){event.preventDefault();const target=document.getElementById(el.getAttribute('href').slice(1));if(target?.tagName==='DETAILS'){target.open=true;target.querySelector('input,select,textarea')?.focus();}else if(target){target.closest('details')?.setAttribute('open','');target.focus();}return;}
 if(el.dataset.invoicePage){event.preventDefault();m.invoicePage=Number(el.dataset.invoicePage);draw();document.querySelector('#client-invoices h2').scrollIntoView();return;}
 if(el.dataset.route){event.preventDefault();if(el.closest('dialog')?.open)closeDialog(el.closest('dialog'));intent(el);return;}
 if(el.dataset.sort){m.desc=m.sort===el.dataset.sort?!m.desc:false;m.sort=el.dataset.sort;draw();document.querySelector(`[data-sort="${m.sort}"]`)?.focus();return;}
 const action=el.dataset.action;if(!action)return;
 if(action==='reset'){m.filters={q:'',district:'',is_active:''};m.page=1;m.selected.clear();draw();announce('Filters reset.');}
 if(action==='next'||action==='previous'){m.page+=action==='next'?1:-1;draw();document.querySelector('#directory-title').setAttribute('tabindex','-1');document.querySelector('#directory-title').focus();}
 if(action==='all'){m.all=!m.all;draw();document.querySelector('[data-action="all"]').focus();}
 if(action==='direction'){m.desc=!m.desc;draw();document.querySelector('[data-action="direction"]').focus();}
 if(action==='clear-selection'){m.selected.clear();draw();document.querySelector('#mobile-sort').focus();}
 if(action==='export')intent(el);
 if(action==='retry'){m.scenario='populated';draw();announce('Supplied client view restored.');}
 if(action==='archive'&&m.p.archive&&m.client.is_active)openDialog('archiveDialog',el);
 if(action==='close-archive')closeDialog(document.getElementById('archiveDialog'));
 if(action==='confirm-archive'&&m.p.archive){m.client.is_active=false;if(m.client.client_status==='ACTIVE')m.client.client_status='INACTIVE';document.documentElement.style.overflow='';m.screen='list';m.notice=`${displayName(m.client)} was archived. Existing invoices and appointments were kept. Preview only.`;draw({focus:true});}
 if(action==='quick'&&m.p.manage){m.quick=blank();document.querySelector('[data-quick-form]').reset();openDialog('quickDialog',el);}
 if(action==='close-quick')closeDialog(document.getElementById('quickDialog'));
});
document.addEventListener('input',event=>{
 const el=event.target;
 if(el.closest('[data-client-form]'))m.draft[el.name]=el.type==='checkbox'?el.checked:el.value;
 if(el.closest('[data-quick-form]'))m.quick[el.name.replace('new_client-','')]=el.value;
 if(el.id==='parent-title')m.parent.title=el.value;if(el.id==='parent-notes')m.parent.notes=el.value;
});
document.addEventListener('change',event=>{
 const el=event.target;
 if(el.id==='review-screen'){go(el.value);return;}
 if(el.id==='review-scenario'){const q=new URLSearchParams({screen:m.screen,scenario:el.value,theme:document.documentElement.dataset.bsTheme});location.search=q;return;}
 if(el.matches('[data-sort-select]')){m.sort=el.value;m.desc=false;draw();document.getElementById('mobile-sort').focus();}
 if(el.matches('[data-select]')){const id=Number(el.dataset.select);if(el.checked)m.selected.add(id);else m.selected.delete(id);const focused=el.dataset.select;draw();document.querySelector(`[data-select="${focused}"]`)?.focus();}
 if(el.hasAttribute('data-select-all')){m.filtered.forEach(c=>el.checked?m.selected.add(c.id):m.selected.delete(c.id));draw();document.querySelector('[data-select-all]')?.focus();}
 if(el.name==='country'&&m.screen==='create'){
 const open=[...document.querySelectorAll('details[open]')].map(d=>d.id);draw();open.forEach(id=>document.getElementById(id)?.setAttribute('open',''));document.querySelector('[name="country"]').focus();
 }
});
document.addEventListener('submit',event=>{
 event.preventDefault();const form=event.target;
 if(form.matches('[data-filter]')){m.filters=Object.fromEntries(new FormData(form));m.page=1;m.selected.clear();draw();announce(`${m.filtered.length} clients match your filters.`);}
 if(form.matches('[data-client-form]')&&m.p.manage&&!(m.screen==='create'&&m.p.quota)){
 m.errors=validate(form);if(Object.keys(m.errors).length){draw();document.querySelector('[data-error-summary]').focus();return;}
 if(m.screen==='edit'){Object.assign(m.client,m.draft);m.screen='profile';m.notice='Client updated successfully. Preview only.';}
 else{m.rows.push({...m.draft,id:Math.max(200,...m.rows.map(c=>c.id))+1,is_active:true,created_at:'17 Nov 2026',updated_at:'17 Nov 2026'});m.filters={q:'',district:'',is_active:''};m.screen='list';m.notice='Client created successfully. Preview only.';}
 draw({focus:true});
 }
 if(form.matches('[data-import-form]')&&m.p.manage){m.filename=form.querySelector('[type=file]').files[0]?.name||'sample-clients.csv';go('preview');}
 if(form.matches('[data-import-confirm]')&&m.p.manage&&m.scenario!=='import-blocked'&&!m.p.quota){if(!m.imported){m.rows.push({...blank(),id:501,first_name:'Noah',last_name:'Adams',client_status:'LEAD',consent_to_contact:false,is_active:true},{...blank(),id:502,company_name:'Pine Studio',client_status:'LEAD',consent_to_contact:false,is_active:true});m.imported=true;}go('result');}
 if(form.matches('[data-quick-form]')&&m.p.manage){
 const errors=validate(form,'new_client-');const target=form.querySelector('[data-quick-errors]');target.innerHTML=errorsMarkup(errors,'new_client-');
 for(const el of form.querySelectorAll('[aria-invalid]')){el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');}
 for(const old of form.querySelectorAll('.field-error'))old.remove();
 for(const [key,message]of Object.entries(errors)){const input=form.elements.namedItem('new_client-'+key);input.setAttribute('aria-invalid','true');const error=document.createElement('p');error.className='field-error';error.id=`quick-error-${key}`;error.textContent=message;input.setAttribute('aria-describedby',error.id);input.after(error);}
 if(Object.keys(errors).length){target.querySelector('[data-error-summary]').focus();return;}
 if(m.p.quota){target.innerHTML='<div class="mm-notice error" role="alert">Client capacity reached. Your draft remains in place.</div>';return;}
 m.parent.client=displayName(m.quick);document.getElementById('parent-client').value=m.parent.client;closeDialog(document.getElementById('quickDialog'));announce('New client selected. Your draft is preserved. Preview only.');
 }
});
document.addEventListener('keydown',event=>{
 const pop=document.getElementById('account-menu');
 if(event.key==='Escape'&&!pop.hidden){pop.hidden=true;document.querySelector('[data-account-toggle]').setAttribute('aria-expanded','false');document.querySelector('[data-account-toggle]').focus();}
 const dialog=document.querySelector('dialog[open]');if(!dialog)return;
 if(event.key==='Escape'){event.preventDefault();closeDialog(dialog);}
 if(event.key==='Tab'){const controls=[...dialog.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(e=>!e.disabled&&e.checkVisibility());if(event.shiftKey&&document.activeElement===controls[0]){event.preventDefault();controls.at(-1).focus();}else if(!event.shiftKey&&document.activeElement===controls.at(-1)){event.preventDefault();controls[0].focus();}}
});
document.addEventListener('click',event=>{if(!event.target.closest('.account-container')){const pop=document.getElementById('account-menu');pop.hidden=true;document.querySelector('[data-account-toggle]').setAttribute('aria-expanded','false');}});
window.addEventListener('popstate',()=>{const q=new URLSearchParams(location.search);m.screen=q.get('screen')||'list';m.clientId=Number(q.get('client')||101);if(m.screen==='edit')m.draft={...(m.rows.find(c=>c.id===m.clientId)||m.client)};draw({focus:true});});
draw();

document.addEventListener("focusin",event=>{if(!event.target.closest(".account-container")){document.getElementById("account-menu").hidden=true;document.querySelector("[data-account-toggle]").setAttribute("aria-expanded","false");}});
