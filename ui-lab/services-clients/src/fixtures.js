// Synthetic review projections. This file evaluates no real permission or finance policy.
export const sections = [
 ['basic','Client identity',['client_type','first_name','last_name','company_name','email','phone']],
 ['location','Address',['street_address','country','district','postal_code']],
 ['business','Business details',['business_legal_name','trade_name','industry','website','registration_number','business_description']],
 ['contact','Contact preferences',['job_title','department','secondary_email','secondary_phone','whatsapp_number','preferred_language','preferred_contact_method']],
 ['relationship','Relationship & CRM',['client_status','priority','lead_source','assigned_to','interested_services']],
 ['notes','Notes & consent',['notes','communication_notes','message','consent_to_contact']]
];
export const options = {
 client_type:[['BUSINESS','Business'],['INDIVIDUAL','Individual']],
 client_status:[['LEAD','Lead'],['PROSPECT','Prospect'],['ACTIVE','Active Client'],['INACTIVE','Inactive'],['ARCHIVED','Archived']],
 priority:[['LOW','Low'],['MEDIUM','Medium'],['HIGH','High']],
 preferred_contact_method:[['EMAIL','Email'],['PHONE','Phone'],['WHATSAPP','WhatsApp']],
 lead_source:[['','Unspecified'],['WEBSITE','Website'],['REFERRAL','Referral'],['WALK_IN','Walk-in'],['INSTAGRAM','Instagram'],['FACEBOOK','Facebook'],['LINKEDIN','LinkedIn'],['PHONE','Phone Inquiry'],['OTHER','Other']],
 assigned_to:[['','Unassigned'],['1','Alex Morgan'],['2','Sam Rivera']],
 country:[['Sint Maarten','Sint Maarten'],['Netherlands','Netherlands'],['Anguilla','Anguilla']]
};
export const districts=[['','Not supplied'],['PHILIPSBURG','Philipsburg'],['COLE_BAY','Cole Bay'],['SIMPSON_BAY','Simpson Bay']];
export const labels={client_type:'Client type',first_name:'First name',last_name:'Last name',company_name:'Company name',email:'Email',phone:'Phone',street_address:'Street address',country:'Country',district:'District',postal_code:'Postal code',business_legal_name:'Business legal name',trade_name:'Trade name',industry:'Industry',website:'Website',registration_number:'Registration number',business_description:'Business description',job_title:'Job title / role',department:'Department',secondary_email:'Secondary email',secondary_phone:'Secondary phone',whatsapp_number:'WhatsApp number',preferred_language:'Preferred language',preferred_contact_method:'Preferred contact method',client_status:'Client status',priority:'Priority',lead_source:'Client source',assigned_to:'Assigned to',interested_services:'Interested services',notes:'General notes',communication_notes:'Communication notes',message:'Initial message / request',consent_to_contact:'Contact consent confirmed'};
export const required=['client_type','first_name','last_name','company_name','email','phone','street_address','preferred_contact_method','client_status','priority'];
export const textareas=['business_description','interested_services','notes','communication_notes','message'];
export const lengths={first_name:80,last_name:80,company_name:120,email:254,phone:40,street_address:255,country:100,district:100,postal_code:20,business_legal_name:160,trade_name:160,industry:100,registration_number:60,job_title:100,department:100,secondary_email:254,secondary_phone:40,whatsapp_number:40,preferred_language:50,website:200};
export const blank=()=>Object.fromEntries([...sections.flatMap(s=>s[2]).map(k=>[k,'']),['client_type','BUSINESS'],['country','Sint Maarten'],['postal_code','N/A'],['preferred_contact_method','EMAIL'],['client_status','ACTIVE'],['priority','MEDIUM'],['consent_to_contact',true]]);
const base={...blank(),id:101,first_name:'Alice',last_name:'Thompson',company_name:'Seabreeze Studio',email:'alice@example.test',phone:'+1 721 555 0101',street_address:'18 Front Street',district:'PHILIPSBURG',business_legal_name:'Seabreeze Studio N.V.',trade_name:'Seabreeze',industry:'Hospitality',website:'https://example.test',job_title:'Operations manager',preferred_language:'English',lead_source:'REFERRAL',assigned_to:'2',interested_services:'Studio maintenance and seasonal deep cleaning',notes:'Use the courtyard entrance. Please call before arriving.',communication_notes:'Email works best for estimates. Call for same-day schedule changes.',message:'Looking for recurring studio maintenance.',is_active:true,last_contacted_at:'12 Nov 2026, 10:30',next_follow_up_at:'Not scheduled',created_at:'06 Oct 2026',updated_at:'12 Nov 2026'};
export function fixtures(scenario){
 const names=[['Alice','Thompson','Seabreeze Studio'],['Ben','Williams','Harbour Dental'],['Camille','Laurent','Atelier Camille'],['Daniel','James','Island Kitchen'],['Elena','Martinez','Blue Bay Wellness'],['Farah','Ali','Palm House'],['Gabriel','Peters','Peters Consulting'],['Hana','Chen','Lotus Studio'],['Isaac','Brown','Marina Collective'],['Jade','Richardson','Coastal Office'],['Kai','Brooks','Bright Ideas'],['Leah','Wilson','Leah Wilson'],['Maya','de Vries','Maya Design']];
 const rows=names.map(([first_name,last_name,company_name],i)=>({...base,id:101+i,first_name,last_name,company_name,email:`${first_name.toLowerCase()}@example.test`,district:i%2?'COLE_BAY':'PHILIPSBURG',client_type:i===11?'INDIVIDUAL':'BUSINESS',is_active:i!==5,client_status:i===5?'INACTIVE':i===2?'PROSPECT':'ACTIVE',assigned_to:i%3?'2':'',notes:i?'':base.notes}));
 if(scenario==='long'){rows[0]={...rows[0],first_name:'Alexandria-Catherine',last_name:'van der Meer-Richardson',company_name:'Caribbean Arts, Hospitality and Community Services Cooperative',email:'alexandria.catherine.vandermeer.richardson@example.test',street_address:'Suite 402, Community Arts and Enterprise Centre, 125 Waterfront Boulevard',notes:'Please coordinate with the facilities manager before arrival. '.repeat(15)};}
 if(scenario==='partial'){rows[0]={...base,id:101,first_name:'',last_name:'',company_name:'',email:'',phone:'',street_address:'',district:'',notes:''};}
 return scenario==='empty'?[]:rows;
}
export const scenarios=['populated','long','partial','empty','admin','staff','accountant','viewer','read-only','locked','no-invoices','no-appointments','no-history','quota','loading','error','invalid','import-blocked','invoice-review'];
export function projection(s){
 const role=['admin','staff','accountant','viewer'].includes(s)?s:'owner';
 const write=!['read-only','locked','viewer'].includes(s);
 return {role,read:s!=='locked',write,manage:write,archive:write&&['owner','admin'].includes(role),invoices:!['locked','no-invoices'].includes(s),appointments:!['locked','no-appointments'].includes(s),schedule:write&&role!=='accountant',quota:s==='quota'};
}
export const displayName=c=>[c.first_name,c.last_name].filter(Boolean).join(' ')||c.company_name||`Client #${c.id}`;
