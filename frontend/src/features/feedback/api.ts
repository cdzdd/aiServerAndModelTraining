import { session } from '../auth/session'
import type { MessageView } from '../chat/api'

export type Rating='up'|'down'
export type FeedbackStatus='open'|'resolved'
export interface FeedbackView {
  id:string;message_id:string;conversation_id:string;user_id:string;rating:Rating;comment:string;
  status:FeedbackStatus;resolution:string;resolved_by:string|null;resolved_at:string|null;
  created_at:string;updated_at:string
}
export interface FeedbackPage {items:FeedbackView[];total:number;page:number;page_size:number}
export interface FeedbackDetailView {feedback:FeedbackView;message_available:boolean;message:MessageView|null}
const messagePath=(id:string)=>'/messages/'+encodeURIComponent(id)+'/feedback'
const feedbackPath=(id:string)=>'/feedback/'+encodeURIComponent(id)
const adminPath=(id:string)=>'/admin/feedback/'+encodeURIComponent(id)
export const getOwnFeedback=(messageId:string)=>session.api.request<FeedbackView|null>(messagePath(messageId))
export const submitFeedback=(messageId:string,body:{rating:Rating;comment:string})=>session.api.request<FeedbackView>(messagePath(messageId),{method:'POST',body})
export const editFeedback=(id:string,body:{rating:Rating;comment:string})=>session.api.request<FeedbackView>(feedbackPath(id),{method:'PATCH',body})
export function listFeedback(page=1,status='',rating='') {
  const query=new URLSearchParams({page:String(page)})
  if(status) query.set('status',status)
  if(rating) query.set('rating',rating)
  return session.api.request<FeedbackPage>('/admin/feedback?'+query)
}
export const getFeedbackDetail=(id:string)=>session.api.request<FeedbackDetailView>(adminPath(id))
export const resolveFeedback=(id:string,body:{status:FeedbackStatus;resolution:string})=>session.api.request<FeedbackView>(adminPath(id),{method:'PATCH',body})
