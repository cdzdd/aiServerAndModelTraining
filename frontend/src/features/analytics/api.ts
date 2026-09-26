import { session } from '../auth/session'

export interface Ratio {numerator:number;denominator:number;value:number|null}
export interface TokenField {value:number|null;known_sum:number;known_count:number;missing_count:number;coverage:number|null}
export interface StatsView {
  range:{from:string;to:string;timezone:'Asia/Shanghai'};as_of:string
  logins:{successful:number}
  generations:{accepted:number;distinct_users:number;complete:number;failed:number;cancelled:number;generating:number;answered:number;clarify:number;no_answer:number;unclassified_complete:number;no_answer_ratio:Ratio}
  latency:{average_ms:number|null;sample_count:number;missing_count:number}
  tokens:{terminal_count:number;pending_count:number;prompt_tokens:TokenField;completion_tokens:TokenField;total_tokens:TokenField;cost:{amount:null;status:'unknown';reason:string}}
  handoffs:{period:{requested:number;claimed:number;closed:number};current:{queued:number;human:number}}
  feedback:{total:number;up:number;down:number;open:number;resolved:number;satisfaction:Ratio}
  ingestion:{period_jobs:{parse:JobStates;index:JobStates};current_documents:{uploaded:number;processing:number;parsed:number;ready:number;failed:number;disabled:number;deleted:number}}
  daily:DailyStat[];popular_questions:{preview:string;count:number;truncated:boolean}[]
}
export interface JobStates {queued:number;running:number;succeeded:number;failed:number}
export interface DailyStat {date:string;accepted:number;complete:number;failed:number;cancelled:number;generating:number;no_answer:number}
export interface AuditEventView {
  id:string;actor_id:string|null;action:string;summary:string;target_type:string;target_id:string|null;outcome:string;request_id:string|null;created_at:string;metadata:Record<string,unknown>
}
export interface AuditPage {items:AuditEventView[];total:number;page:number;page_size:number}
export interface AuditFilters {page:number;from?:string;to?:string;action?:string;outcome?:string;actor_id?:string;target_type?:string;target_id?:string}

function rangeQuery(from?:string,to?:string) {
  const query=new URLSearchParams()
  if(from && to) {query.set('from',from);query.set('to',to)}
  return query
}
export function getStats(from?:string,to?:string) {
  const query=rangeQuery(from,to).toString()
  return session.api.request<StatsView>('/admin/stats'+(query?'?'+query:''))
}
export function listAuditEvents(filters:AuditFilters) {
  const query=rangeQuery(filters.from,filters.to)
  query.set('page',String(filters.page))
  for(const key of ['action','outcome','actor_id','target_type','target_id'] as const) if(filters[key]) query.set(key,filters[key])
  return session.api.request<AuditPage>('/admin/audit-events?'+query)
}
export const getAuditEvent=(id:string)=>session.api.request<AuditEventView>('/admin/audit-events/'+encodeURIComponent(id))

export function shanghaiRange(start:string,end:string):{from:string;to:string}|null {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end) || start>end) return null
  if([start,end].some(value=>{const date=new Date(value+'T00:00:00Z');return Number.isNaN(date.getTime()) || date.toISOString().slice(0,10)!==value})) return null
  const [year,month,day]=end.split('-').map(Number)
  const next=new Date(Date.UTC(year,month-1,day+1)).toISOString().slice(0,10)
  return {from:start+'T00:00:00+08:00',to:next+'T00:00:00+08:00'}
}
export function shanghaiTime(value:string) {
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value))
}
