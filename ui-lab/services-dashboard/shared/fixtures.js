// Synthetic presentation payloads only. Never import Django or infer settlement here.
export const states = ['populated','empty','future','past','appointments-locked','invoices-locked','booking-locked','locked','long','staff','viewer','accountant','admin','read-only','grace','sharing-absent','welcome','guide','loading','error','financial-edge','timezone-boundary'];
export const routes = {
 agent_dashboard:'/crm/agent/dashboard/',appointment_list:'/appointments/',appointment_detail:'/appointments/{id}/',staff_lead_detail:'/crm/staff/leads/{id}/',invoice_list:'/billings/',invoice_detail:'/billings/{id}/',staff_client_list:'/crm/staff/clients/',business_service_list:'/crm/settings/services/',business_booking_settings:'/businesses/settings/booking/',business_settings:'/businesses/settings/',business_subscription:'/businesses/subscription/',business_team_members:'/businesses/team/',data_import:'/crm/staff/data-import/',public_booking:'/book/ui-lab-services/',logout:'/accounts/logout/'
};
export const journeys = [
 {key:'setup_business',title:'Set Up My Business',description:'Complete your profile, add services, and set availability.',progress:'2 of 3 complete',percent:67,tasks:['Complete business profile','Add your first service','Set your availability']},
 {key:'manage_clients',title:'Start Managing Clients',description:'Manage customers, service requests, and appointments.',progress:'3 of 3 complete',percent:100,tasks:['Add your first client','Create your first service request','Schedule your first appointment']},
 {key:'booked_and_paid',title:'Get Booked & Paid',description:'Configure online booking and manage customer invoices.',progress:'3 of 3 complete',percent:100,tasks:['Open or configure online booking','Create your first invoice','Send or download your first invoice']}
];
const people=[['Jamie Rivera','Harbour View Apartments'],['Taylor Bennett','Island Property Services'],['Casey Laurent','Household'],['Jordan Ellis','Seaview Guesthouse'],['Riley James','Market Street Studio']];
export function fixture(name='populated') {
 if(!states.includes(name))name='populated';
 const role=['staff','viewer','accountant','admin'].includes(name)?name:'owner';
 const manager=['owner','admin'].includes(role);
 const data={name,role,user:'Alex Morgan',workspace:'Harbour Services · UI Audit',timezone:'America/Lower_Princes',zoneLabel:'America/Lower_Princes · UTC−04:00',date:'Saturday, 14 November 2026',clock:'2026-11-14T09:00:00Z',currency:'USD',prefix:'INV',canSettings:manager,canTeam:manager,canSubscription:role==='owner',canBooking:['owner','admin','staff'].includes(role),canClients:role!=='viewer',canInvoice:role!=='viewer',canRequests:['owner','admin','staff'].includes(role),guideVisible:manager,write:true,appointmentsEnabled:true,invoicesEnabled:true,bookingEnabled:true,shareReady:true,today:5,upcoming:5,clients:5,newClients:5,open:5,newRequests:3,monthRequests:5,online:2,drafts:2,issued:3,dueCount:3,issuedValue:'$750.00',outstanding:'$750.00',bookingUrl:'https://motionmate.example.test/book/ui-lab-services/',financialNote:'Issued invoice value is not cash received.',appointmentRows:people.map(([customer,company],i)=>({id:101+i,customer,company,service:'Property maintenance consultation',title:'Initial site visit',time:['7:00 AM','10:00 AM','1:00 PM','4:00 PM','7:00 PM'][i],date:'Today',instant:`2026-11-14T${[11,14,17,20,23][i]}:00:00Z`,status:'Scheduled'})),requests:people.map(([customer,company],i)=>({id:201+i,customer,company,service:'Property maintenance consultation',preferred:`Nov 15 · ${['7:00 AM','10:00 AM','1:00 PM','4:00 PM','7:00 PM'][i]}`,online:i<2,status:i<3?'New':'Contacted'})),invoices:[{id:303,number:'AUD-1003',customer:'Casey Laurent',company:'Household',amount:'$375.00',currency:'USD',lifecycle:'Issued',payment:'Unpaid'},{id:302,number:'AUD-1002',customer:'Taylor Bennett',company:'Island Property Services',amount:'$250.00',currency:'USD',lifecycle:'Issued',payment:'Unpaid'},{id:301,number:'AUD-1001',customer:'Jamie Rivera',company:'Harbour View Apartments',amount:'$125.00',currency:'USD',lifecycle:'Issued',payment:'Unpaid'}]};
 if(name==='empty'){Object.assign(data,{today:0,upcoming:0,clients:0,newClients:0,open:0,newRequests:0,monthRequests:0,online:0,drafts:0,issued:0,dueCount:0,issuedValue:'$0.00',outstanding:'$0.00',shareReady:false,appointmentRows:[],requests:[],invoices:[]});}
 if(name==='future'){data.today=0;data.appointmentRows.forEach(r=>{r.date='Nov 15';r.instant=r.instant.replace('11-14','11-15');});}
 if(name==='past'){data.appointmentRows=[];data.upcoming=0;}
 if(['appointments-locked','locked'].includes(name)){data.appointmentsEnabled=false;data.appointmentRows=[];}
 if(['invoices-locked','locked'].includes(name)){data.invoicesEnabled=false;data.invoices=[];}
 if(['booking-locked','locked'].includes(name)){data.bookingEnabled=false;data.shareReady=false;}
 if(name==='sharing-absent')data.shareReady=false;
 if(name==='read-only'){data.write=false;data.alert='This Motionmate workspace is temporarily read-only.';data.canBooking=false;}
 if(name==='grace')data.alert='Your business subscription requires attention. Workspace access remains available temporarily.';
 if(name==='long'){
  data.workspace='Caribbean Property Maintenance and Guest Services Operations';data.issuedValue='$9,876,543.21';data.outstanding='$1,234,567.89';data.bookingUrl='https://motionmate.example.test/book/'+'caribbean-property-maintenance-'.repeat(5);
  data.requests.forEach(r=>{r.customer='Alexandria-Catherine Montgomery-Worthington';r.company='Caribbean Residential Property Management and Hospitality Support Services';});
  data.appointmentRows.forEach(r=>{r.company='Caribbean Residential Property Management and Hospitality Support Services';});
 }
 if(name==='financial-edge'){
  data.dueCount=3;data.outstanding='$275.00';data.issuedValue='$750.00';data.financialNote='Money summaries shown in USD. Invoice counts can span currencies. Review cases are excluded from collectible follow-up.';
  data.invoices=[{id:313,number:'AUD-1013',customer:'Casey Laurent',company:'Household',amount:'$275.00',currency:'USD',lifecycle:'Issued',payment:'Partially paid',note:'Refund due · $25.00'},{id:312,number:'AUD-1012',customer:'Taylor Bennett',company:'Island Property Services',amount:'€140.00',currency:'EUR',lifecycle:'Issued',payment:'Unpaid'},{id:311,number:'AUD-1011',customer:'Jamie Rivera',company:'Harbour View Apartments',amount:'€90.00',currency:'EUR',lifecycle:'Issued',payment:'Unpaid'}];
 }
 if(name==='timezone-boundary'){
  data.timezone='Europe/Berlin';data.zoneLabel='Europe/Berlin · UTC+01:00';data.date='Sunday, 25 October 2026';data.clock='2026-10-25T00:00:00Z';data.today=2;data.upcoming=2;
  data.appointmentRows=data.appointmentRows.slice(0,2).map((r,i)=>({...r,time:'2:30 AM',date:i===0?'Today · UTC+02:00':'Today · UTC+01:00',instant:i===0?'2026-10-25T00:30:00Z':'2026-10-25T01:30:00Z'}));
 }
 return data;
}
export const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function routeUrl(name,id,query=''){return (routes[name]||'#').replace('{id}',encodeURIComponent(id??''))+query;}
export function linkAttrs(name,id,query=''){return `href="${routeUrl(name,id,query)}" data-route="${name}"${id?` data-id="${id}"`:''}${query?` data-query="${query}"`:''}`;}
