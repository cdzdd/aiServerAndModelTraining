import { session } from '../auth/session'

export interface KnowledgeBase {id:string;name:string;description:string;visibility:'public'|'restricted';is_active:boolean;version:number}
export interface Faq {id:string;kb_id:string;question:string;answer:string;is_active:boolean;version:number;indexed_version:number|null;updated_at:string}
export interface Page<T> {items:T[];total:number;page:number;page_size:number}
export interface KnowledgeInput {name:string;description:string;visibility:'public'|'restricted'}
export interface FaqInput {question:string;answer:string;is_active:boolean}
export interface Members {user_ids:string[];version:number}
const request=session.api.request
const kbPath=(id:string)=>'/knowledge-bases/'+encodeURIComponent(id)
export function listKnowledge(page=1) {
  const prefix=session.state.user?.role==='admin'?'/admin':''
  return request<Page<KnowledgeBase>>(prefix+'/knowledge-bases?page='+page)
}
export function getKnowledge(id:string) {return request<KnowledgeBase>(kbPath(id))}
export function createKnowledge(body:KnowledgeInput) {return request<KnowledgeBase>('/knowledge-bases',{method:'POST',body})}
export function updateKnowledge(kb:KnowledgeBase,changes:Partial<KnowledgeInput>&{is_active?:boolean}) {
  return request<KnowledgeBase>(kbPath(kb.id),{method:'PATCH',body:{...changes,expected_version:kb.version}})
}
export function getMembers(id:string) {return request<Members>(kbPath(id)+'/members')}
export function setMembers(id:string,user_ids:string[],expected_version:number) {
  return request<Members>(kbPath(id)+'/members',{method:'PUT',body:{user_ids,expected_version}})
}
export function listFaqs(id:string,page=1) {return request<Page<Faq>>(kbPath(id)+'/faqs?page='+page)}
export function saveFaq(kbId:string,body:FaqInput,faq?:Faq) {
  return faq?request<Faq>('/faqs/'+encodeURIComponent(faq.id),{method:'PATCH',body:{...body,expected_version:faq.version}})
    :request<Faq>(kbPath(kbId)+'/faqs',{method:'POST',body})
}
export function disableFaq(id:string) {return request<void>('/faqs/'+encodeURIComponent(id),{method:'DELETE'})}
export function indexLabel(faq:Faq) {
  return !faq.is_active?'已停用':faq.indexed_version===faq.version?'索引版本一致':'待索引'
}

