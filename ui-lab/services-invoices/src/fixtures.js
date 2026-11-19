// Supplied synthetic projections. These are not accounting or authorization code.
export const scenarios=['populated','draft','partial','paid','cancelled','zero-tax','zero-value','review','legacy-unverified','refund','currency-retained','empty','long','many-lines','invalid','owner','admin','staff','accountant','viewer','read-only','locked','quota','missing-email','appointment','client-locked','payment-error','no-notes','loading','error'];
export const screens=['list','create','edit','detail','payment','adjust','document','email'];
export const clients=[{id:'101',name:'Alice Thompson',company:'Seabreeze Studio',email:'alice@seabreeze.example.test',phone:'+1 721 555 0101',street:'18 Front Street',city:'Philipsburg',country:'Sint Maarten'},{id:'102',name:'Ben Williams',company:'Harbour Dental',email:'ben@harbour.example.test',phone:'+1 721 555 0102',street:'24 Welfare Road',city:'Cole Bay',country:'Sint Maarten'}];
export const services=[{id:'31',name:'Studio maintenance',price:'125',description:'Studio maintenance visit'},{id:'32',name:'Seasonal deep cleaning',price:'200',description:'Seasonal deep cleaning'},{id:'33',name:'Site consultation',price:'75',description:'On-site consultation'}];
export const blankLine=()=>({service_id:'',description:'',quantity:'1',unit_price:'',save_as_service:false,service_category_id:'',new_service_category_name:''});
export const blankDraft=()=>({client_id:'',notes:'',lines:[blankLine()]});
export function permissions(scenario){
 const role=['owner','admin','staff','accountant','viewer'].includes(scenario)?scenario:'owner';
 const read=scenario!=='locked',write=read&&role!=='viewer'&&scenario!=='read-only';
 return {role,read,write,manage:write,delete:write&&['owner','admin'].includes(role),adjust:write&&['owner','admin','accountant'].includes(role),verified:write&&['owner','admin','accountant'].includes(role),quota:scenario==='quota'};
}
export function sample(scenario='populated'){
 const c={...clients[0]};
 if(scenario==='missing-email')c.email='';
 if(scenario==='long'){c.name='Alexandra Catherine van der Linden Thompson';c.company='Seabreeze Association for Community Services and Waterfront Property Administration';c.street='Building 18, second floor, courtyard entrance behind the community administration office';}
 const i={id:601,number:'INV-2026-0042',created:'18 Nov 2026',lifecycle:'ISSUED',status:'SENT',payment:'Unpaid',client:c,currency:'USD',taxRate:6,subtotal:300,tax:18,total:318,net:0,balance:318,refund:0,credits:0,review:false,legacy:false,emailSubmitted:false,notes:'Thank you for choosing Harbour Services.\nPlease include the invoice number with your payment.',lines:[{service_id:'31',description:'Studio maintenance visit',quantity:'2',unit_price:'125',lineTotal:250},{service_id:'',description:'Replacement supplies',quantity:'1',unit_price:'50',lineTotal:50}]};
 if(scenario==='draft'){i.lifecycle='DRAFT';i.status='DRAFT';i.payment='';i.balance=0;}
 if(['partial','populated','owner','admin','staff','accountant','viewer'].includes(scenario)){i.payment='Partially paid';i.net=100;i.balance=218;}
 if(scenario==='paid'){i.payment='Paid';i.net=318;i.balance=0;}
 if(scenario==='cancelled'){i.lifecycle='CANCELLED';i.status='CANCELLED';i.payment='';i.balance=0;}
 if(scenario==='zero-tax'){i.taxRate=0;i.tax=0;i.total=300;i.balance=300;}
 if(scenario==='zero-value'){i.lines=[{service_id:'',description:'Complimentary site review',quantity:'1',unit_price:'0',lineTotal:0}];i.subtotal=0;i.tax=0;i.total=0;i.balance=0;i.payment='No payment required';}
 if(['review','legacy-unverified'].includes(scenario)){i.review=true;i.legacy=scenario==='legacy-unverified';i.status=i.legacy?'PAID':'SENT';i.payment='';i.balance=null;}
 if(scenario==='refund'){i.payment='Paid';i.net=318;i.balance=0;i.refund=50;}
 if(scenario==='currency-retained'){i.currency='EUR';i.payment='Partially paid';i.net=100;i.balance=218;}
 if(scenario==='many-lines'){i.lines=Array.from({length:48},(_,n)=>({service_id:'',description:`Scheduled maintenance item ${String(n+1).padStart(2,'0')} · Window, equipment and shared studio spaces`,quantity:'1',unit_price:'25',lineTotal:25}));i.subtotal=1200;i.tax=72;i.total=1272;i.balance=1272;}
 if(scenario==='long'){i.notes='Thank you for the opportunity to support your community. '.repeat(14)+'\nPlease quote the complete invoice reference when contacting our administration team.';i.lines[0].description='Studio maintenance, inspection of all courtyard equipment and shared areas, seasonal cleaning and administration handover';}
 if(scenario==='no-notes')i.notes='';
 i.entries=i.net&&!i.review?[{kind:'Receipt',amount:i.net,remaining:i.net,method:'Bank transfer',reference:'BANK-2026-0019',audit:'Received and checked'}]:[];
 return i;
}
export function records(scenario){
 if(scenario==='empty')return [];
 return ['partial','draft','paid','zero-tax','review','cancelled','zero-value','refund'].map((s,n)=>({...sample(s),id:601+n,number:`INV-2026-${String(42+n).padStart(4,'0')}`,client:n%2?{...clients[1]}:sample(scenario).client,scenario:s}));
}
export const lifecycleLabel=i=>({DRAFT:'Draft',ISSUED:'Issued',CANCELLED:'Cancelled'}[i.lifecycle]);
export const money=(n,currency='USD')=>n==null?'Unverified — review required':`${currency} ${Number(n).toFixed(2)}`;
