// Synthetic presentation projections, never models or a second booking system.
// Eligibility, classification, role decisions and timestamps are supplied here.
const rows = [
  {kind:'request',id:701,title:'Jamie Rivera',client:'Harbour View Apartments',clientId:501,classification:'Lead',source:'Online',service:'Property maintenance consultation',staff:'Unassigned',time:'Not scheduled',preferred:'Nov 15, 2026 · 07:00',state:'Needs follow-up',requestStatus:'New',filter:{state:'needs_follow_up',source:'online',classification:'LEAD',staff:'',service:'41'},search:'Jamie Rivera Harbour View Apartments jamie@example.test +1 555 0101 Property maintenance consultation'},
  {kind:'request',id:702,title:'Taylor Bennett',client:'Island Property Services',clientId:502,classification:'Prospect',source:'Online',service:'Property maintenance consultation',staff:'Unassigned',time:'Not scheduled',preferred:'Nov 15, 2026 · 10:00',state:'Needs follow-up',requestStatus:'Contacted',filter:{state:'needs_follow_up',source:'online',classification:'PROSPECT',staff:'',service:'41'},search:'Taylor Bennett Island Property Services taylor@example.test +1 555 0102 Property maintenance consultation'},
  {kind:'request',id:703,title:'Casey Laurent',client:'Casey Laurent',clientId:null,classification:'Unknown',source:'Internal',service:'Safety inspection',staff:'Unassigned',time:'Not scheduled',preferred:null,state:'Needs follow-up',requestStatus:'New',filter:{state:'needs_follow_up',source:'internal',classification:'unknown',staff:'',service:'42'},search:'Casey Laurent casey@example.test +1 555 0103 Safety inspection'},
  {kind:'appointment',id:801,title:'Initial site visit',client:'Jamie Rivera',clientId:501,classification:'Active Client',source:'Online',service:'Property maintenance consultation',staff:'Alex Morgan',time:'Nov 14, 2026 · 07:00',end:'Nov 14, 2026 · 08:00',instant:'2026-11-14T11:00:00Z',endInstant:'2026-11-14T12:00:00Z',state:'Scheduled',filter:{state:'scheduled',source:'online',classification:'ACTIVE',staff:'91',service:'41'},search:'Initial site visit Property maintenance consultation Jamie Rivera Harbour View Apartments jamie@example.test'},
  {kind:'appointment',id:802,title:'Maintenance review',client:'Taylor Bennett',clientId:502,classification:'Prospect',source:'Internal',service:'Safety inspection',staff:'Alex Morgan',time:'Nov 14, 2026 · 10:00',end:'Nov 14, 2026 · 11:00',instant:'2026-11-14T14:00:00Z',endInstant:'2026-11-14T15:00:00Z',state:'Completed',filter:{state:'completed',source:'internal',classification:'PROSPECT',staff:'91',service:'42'},search:'Maintenance review Safety inspection Taylor Bennett Island Property Services taylor@example.test'},
  {kind:'appointment',id:803,title:'Safety walkthrough',client:'Casey Laurent',clientId:503,classification:'Active Client',source:'Unspecified',service:'Safety inspection',staff:'Unassigned',time:'Nov 14, 2026 · 13:00',end:'Nov 14, 2026 · 14:00',instant:'2026-11-14T17:00:00Z',endInstant:'2026-11-14T18:00:00Z',state:'Cancelled',filter:{state:'cancelled',source:'unknown',classification:'ACTIVE',staff:'',service:'42'},search:'Safety walkthrough Safety inspection Casey Laurent casey@example.test'},
  {kind:'appointment',id:804,title:'Follow-up consultation',client:'Jordan Ellis',clientId:504,classification:'Inactive',source:'Online',service:'Property maintenance consultation',staff:'Sam Chen',time:'Nov 14, 2026 · 16:00',end:'Nov 14, 2026 · 17:00',instant:'2026-11-14T20:00:00Z',endInstant:'2026-11-14T21:00:00Z',state:'No Show',filter:{state:'no_show',source:'online',classification:'INACTIVE',staff:'92',service:'41'},search:'Follow-up consultation Property maintenance consultation Jordan Ellis Seaview Guesthouse jordan@example.test'},
  {kind:'appointment',id:805,title:'Studio inspection',client:'Riley James',clientId:505,classification:'Archived',source:'Unspecified',service:'Safety inspection',staff:'Sam Chen',time:'Nov 15, 2026 · 07:00',end:'Nov 15, 2026 · 08:00',instant:'2026-11-15T11:00:00Z',endInstant:'2026-11-15T12:00:00Z',state:'Scheduled',filter:{state:'scheduled',source:'unknown',classification:'ARCHIVED',staff:'92',service:'42'},search:'Studio inspection Safety inspection Riley James Market Street Studio riley@example.test'}
];

export const filterOptions = {
  state: [['','All states'],['needs_follow_up','Needs follow-up'],['scheduled','Scheduled'],['completed','Completed'],['cancelled','Cancelled'],['no_show','No Show']],
  source: [['','All sources'],['online','Online'],['internal','Internal'],['unknown','Unspecified']],
  classification: [['','All classifications'],['LEAD','Lead'],['PROSPECT','Prospect'],['ACTIVE','Active Client'],['INACTIVE','Inactive'],['ARCHIVED','Archived'],['unknown','Unknown']],
  staff: [['','All staff'],['91','Alex Morgan'],['92','Sam Chen']],
  service: [['','All services'],['41','Property maintenance consultation'],['42','Safety inspection']]
};
const owner = {role:'Owner',canCreateAppointment:true,canCreateRequest:true,appointmentRead:true,requestRead:true};
// Role fixtures are explicit source-audited projections, not a policy evaluator.
const scenarios = {
  populated: {...owner},
  admin: {role:'Admin',canCreateAppointment:true,canCreateRequest:true,appointmentRead:true,requestRead:true},
  staff: {role:'Staff',canCreateAppointment:true,canCreateRequest:true,appointmentRead:true,requestRead:true},
  accountant: {role:'Accountant',canCreateAppointment:false,canCreateRequest:false,appointmentRead:true,requestRead:true,notice:'You have read-only appointment access in this workspace.'},
  viewer: {role:'Viewer',canCreateAppointment:false,canCreateRequest:false,appointmentRead:true,requestRead:true,notice:'You have read-only appointment access in this workspace.'},
  'read-only': {...owner,canCreateAppointment:false,canCreateRequest:false,notice:'You have read-only appointment access in this workspace.'},
  'request-only': {...owner,canCreateAppointment:false,appointmentRead:false,rows:rows.slice(0,3),notice:'Service requests are available here. Scheduled appointments require appointment access.'},
  'appointments-only': {...owner,canCreateRequest:false,requestRead:false,rows:rows.slice(3)},
  locked: {...owner,canCreateAppointment:false,canCreateRequest:false,appointmentRead:false,requestRead:false,rows:[],locked:true},
  empty: {...owner,rows:[]},
  long: {...owner,rows:rows.map(row => ({...row,title:row.title+' · Consultation for the waterfront property and accessibility review',client:row.client+' · Harbour Association for Community Services and Property Administration',service:row.service+' · Comprehensive seasonal assessment and follow-up planning',search:row.search+' Consultation for the waterfront property and accessibility review Harbour Association for Community Services and Property Administration Comprehensive seasonal assessment and follow-up planning'}))},
  loading: {...owner,pending:true},
  error: {...owner,error:true},
  invalid: {...owner,invalid:true},
  // Fifty on page one, two on page two: preserves the existing 50-row page size.
  pagination: {...owner,rows:Array.from({length:52},(_,i) => ({...rows[3],id:900+i,title:`Synthetic visit ${i+1}`,client:`Synthetic client ${i+1}`,clientId:600+i,search:`Synthetic visit ${i+1} Synthetic client ${i+1} Property maintenance consultation`}))}
};
export function fixture(name = 'populated') {
  const selected = scenarios[name] || scenarios.populated;
  return structuredClone({name:scenarios[name] ? name : 'populated',timezone:'America/Lower_Princes · UTC−04:00',clock:'2026-11-14T09:00:00Z',rows,...selected});
}
