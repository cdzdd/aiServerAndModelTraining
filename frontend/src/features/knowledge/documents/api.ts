import { session } from '../../auth/session'
import type { Page } from '../api'

export interface Revision { id:string;filename:string;content_sha256:string;parser_version:string;created_at:string }
export interface IngestionJob { id:string;kind:'parse'|'index';state:'queued'|'running'|'succeeded'|'failed';attempts:number;error_code:string|null;error_message:string|null;created_at:string;finished_at:string|null }
export interface DocumentSummary {
  id:string;kb_id:string;filename:string;status:'uploaded'|'processing'|'parsed'|'ready'|'failed'|'disabled'|'deleted';
  active_revision_id:string|null;candidate_revision_id:string|null;created_at:string;
  active_revision:Revision|null;candidate_revision:Revision|null;latest_job:IngestionJob|null
}
export interface UploadResult { document_id:string;job_id:string;status:'uploaded' }
const path=(id:string)=>'/documents/'+encodeURIComponent(id)
export const listDocuments=(kbId:string,page=1)=>session.api.request<Page<DocumentSummary>>('/knowledge-bases/'+encodeURIComponent(kbId)+'/documents?page='+page)
export const getDocument=(id:string)=>session.api.request<DocumentSummary>(path(id))
export const uploadDocument=(kbId:string,file:File,onProgress:(percent:number)=>void)=>{
  const body=new FormData();body.append('file',file)
  return session.api.upload<UploadResult>('/knowledge-bases/'+encodeURIComponent(kbId)+'/documents',body,onProgress)
}
export const replaceDocument=(id:string,file:File,onProgress:(percent:number)=>void)=>{
  const body=new FormData();body.append('file',file)
  return session.api.upload<UploadResult>(path(id)+'/revisions',body,onProgress)
}
export const setDocumentActive=(id:string,isActive:boolean)=>session.api.request<DocumentSummary>(path(id),{method:'PATCH',body:{is_active:isActive}})
export const deleteDocument=(id:string)=>session.api.request<void>(path(id),{method:'DELETE'})
export const reindexDocument=(id:string)=>session.api.request<{job_id:string}>(path(id)+'/reindex',{method:'POST'})
export const downloadDocument=(id:string)=>session.api.download(path(id)+'/download')

export function statusLabel(status:DocumentSummary['status']) {
  const labels={uploaded:'等待解析',processing:'正在解析',parsed:'解析完成，待建立索引',ready:'已建立索引',failed:'处理失败',disabled:'已停用',deleted:'已删除'}
  return labels[status]
}
