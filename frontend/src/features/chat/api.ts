import { session } from '../auth/session'
import type { KnowledgeBase, Page } from '../knowledge/api'
import type { Citation } from './stream'

export interface ConversationView {
  id:string;user_id:string;title:string;kb_ids:string[];mode:'bot'|'queued'|'human'|'closed';
  assigned_agent_id:string|null;created_at:string;updated_at:string
}
export interface MessageView {
  id:string;conversation_id:string;role:'user'|'assistant'|'agent'|'system';author_id:string|null;
  content:string;status:'generating'|'complete'|'failed'|'cancelled';citations:Citation[];
  client_message_id:string|null;in_reply_to_id:string|null;answer_status:string|null;evidence_level:string|null;
  intent:string|null;latency_ms:number|null;error_code:string|null;created_at:string;evidence_hidden:boolean
}
const conversationPath=(id:string)=>'/conversations/'+encodeURIComponent(id)
export const listAvailableKnowledge=(page=1)=>session.api.request<Page<KnowledgeBase>>('/knowledge-bases?page='+page)
export const listConversations=(page=1)=>session.api.request<Page<ConversationView>>('/conversations?page='+page)
export const createConversation=(kbIds:string[])=>session.api.request<ConversationView>('/conversations',{method:'POST',body:{kb_ids:kbIds}})
export const getConversation=(id:string)=>session.api.request<ConversationView>(conversationPath(id))
export const deleteConversation=(id:string)=>session.api.request<void>(conversationPath(id),{method:'DELETE'})
export const listMessages=(id:string,page=1)=>session.api.request<Page<MessageView>>(conversationPath(id)+'/messages?page='+page)
export const postText=(id:string,content:string,key:string)=>session.api.request<MessageView>(conversationPath(id)+'/messages',{method:'POST',body:{content,client_message_id:key}})
export const streamQuestion=(id:string,content:string,key:string,signal:AbortSignal)=>session.api.stream(conversationPath(id)+'/messages/stream',{content,client_message_id:key},signal)
export const downloadCitation=(citation:Citation)=>session.api.download('/documents/'+encodeURIComponent(citation.source_id)+'/download')
