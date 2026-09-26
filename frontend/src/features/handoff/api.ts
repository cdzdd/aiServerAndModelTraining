import { session } from '../auth/session'
import type { Page } from '../knowledge/api'

export interface HandoffView {
  id:string;conversation_id:string;state:'queued'|'human'|'closed';requested_at:string;
  claimed_at:string|null;closed_at:string|null;assigned_agent_id:string|null
}
export interface QueueItem {id:string;conversation_id:string;requested_at:string;state:'queued'}

const handoffPath=(id:string)=>'/handoffs/'+encodeURIComponent(id)
export const requestHandoff=(conversationId:string)=>session.api.request<HandoffView>('/conversations/'+encodeURIComponent(conversationId)+'/handoff',{method:'POST'})
export const listQueue=(page=1)=>session.api.request<Page<QueueItem>>('/handoffs?page='+page)
export const getHandoff=(id:string)=>session.api.request<HandoffView>(handoffPath(id))
export const claimHandoff=(id:string)=>session.api.request<HandoffView>(handoffPath(id)+'/claim',{method:'POST'})
export const closeHandoff=(id:string)=>session.api.request<HandoffView>(handoffPath(id)+'/close',{method:'POST'})
