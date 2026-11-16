import {fixture,escapeHtml as e,routeUrl,states} from './fixtures.js';
import {icons} from './icons.js';
export function mount(render,ui){
 const params=new URLSearchParams(location.search);const data=fixture(params.get('state')||'populated');
 const app=document.getElementById('app');app.innerHTML=render(data);const mq=matchMedia('(min-width:768px)');const previews=()=>document.querySelectorAll('[data-preview-more]').forEach(el=>el.open=mq.matches);previews();mq.addEventListener('change',previews);window.labEvents=[];window.labState=data;window.labStates=states;ui.init();
 const announce=text=>{document.getElementById('live-status').textContent=text;};
 const record=(type,detail)=>{window.labEvents.push({type,...detail});};
 const setTheme=mode=>{document.documentElement.dataset.bsTheme=mode;document.documentElement.dataset.theme='motionmate-'+mode;try{localStorage.setItem('mm-services-lab-theme',mode);}catch{};const b=document.querySelector('[data-theme-toggle]');b.setAttribute('aria-label',mode==='dark'?'Switch to light theme':'Switch to dark theme');b.innerHTML=icons[mode==='dark'?'sun':'moon'];};
 setTheme(document.documentElement.dataset.bsTheme||'light');
 function preview(anchor){const name=anchor.dataset.route;const url=routeUrl(name,anchor.dataset.id,anchor.dataset.query||'');document.getElementById('routeTitle').textContent=anchor.dataset.previewTitle||anchor.textContent.trim()||'Navigation preview';document.getElementById('routeName').textContent=name;document.getElementById('routePath').textContent=url;record('navigation',{route:name,id:anchor.dataset.id||null,query:anchor.dataset.query||'',url});const fromDrawer=anchor.closest('#navigationDrawer');const trigger=fromDrawer?document.querySelector('[data-menu-open]'):anchor.closest('#account-menu')?document.querySelector('[data-account-toggle]'):anchor;ui.closeAccount();if(fromDrawer)ui.close('navigationDrawer',()=>ui.open('routePreview',trigger));else ui.open('routePreview',trigger);}
 app.addEventListener('click',async event=>{
  const button=event.target.closest('a,button');if(!button)return;
  if(button.matches('[data-route]')){event.preventDefault();event.stopPropagation();preview(button);}
  if(button.matches('[data-theme-toggle]')){event.preventDefault();setTheme(document.documentElement.dataset.bsTheme==='dark'?'light':'dark');}
  if(button.matches('[data-menu-open]')){event.preventDefault();ui.open('navigationDrawer',button);}
  if(button.matches('[data-account-toggle]')){event.preventDefault();event.stopPropagation();ui.account(button);}
  if(button.matches('[data-close]')){event.preventDefault();ui.close(button.dataset.close);}
  if(button.matches('[data-setup-open]')){event.preventDefault();event.stopPropagation();ui.open(data.name==='guide'?'onboardingGuidePanel':'onboardingWelcomeModal',button);}
  if(button.matches('[data-copy]')){
   button.disabled=true;button.setAttribute('aria-busy','true');
   try{if(params.get('copy')==='denied')throw new Error('Denied simulation');await navigator.clipboard.writeText(data.bookingUrl);announce('Link copied');record('copy',{result:'success',value:data.bookingUrl});}
   catch{announce('Copy unavailable — select the link to copy');record('copy',{result:'denied'});document.getElementById('booking-url').focus();document.getElementById('booking-url').select();}
   finally{button.disabled=false;button.removeAttribute('aria-busy');}
  }
  if(button.matches('[data-spotlight]')){ui.close('onboardingGuidePanel',()=>{const target=document.querySelector('[data-onboarding-target="business-settings"]');target.scrollIntoView({block:'center',behavior:'instant'});target.tabIndex=-1;target.focus({preventScroll:true});target.classList.add('spotlight');record('spotlight',{target:'business-settings'});});}
 });
 app.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();const form=event.target;const fields=Object.fromEntries(new FormData(form));record('onboarding',{method:'POST',route:'agent_dashboard',fields});announce('Setup action previewed. No records were changed.');if(fields.onboarding_action==='select_journey'){ui.close('onboardingWelcomeModal',()=>ui.open('onboardingGuidePanel',document.querySelector('[data-setup-open]')));}else if(['dismiss_welcome','continue_later'].includes(fields.onboarding_action)){ui.close(form.closest('[data-overlay]').id);} });
 document.addEventListener('keydown',ev=>{if(ev.key==='Escape')ui.closeAccount();});
 document.addEventListener('click',ev=>{if(!ev.target.closest('[data-account-container]'))ui.closeAccount();});
 const account=document.getElementById('account-menu');account.addEventListener('keydown',ev=>{if(ui.ownsAccountKeyboard)return;const links=[...account.querySelectorAll('a')];const i=links.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End'].includes(ev.key)){ev.preventDefault();const next=ev.key==='Home'?0:ev.key==='End'?links.length-1:(i+(ev.key==='ArrowDown'?1:-1)+links.length)%links.length;links[next].focus();}});
 if(data.name==='welcome')ui.open('onboardingWelcomeModal',document.querySelector('[data-setup-open]'));
 if(data.name==='guide')ui.open('onboardingGuidePanel',document.querySelector('[data-setup-open]'));
 window.labReady=true;
}
