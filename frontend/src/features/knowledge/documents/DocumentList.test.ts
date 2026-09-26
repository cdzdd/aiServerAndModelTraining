import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { session } from '../../auth/session'
import DocumentList from './DocumentList.vue'

const kbId='22222222-2222-4222-8222-222222222222'
const document={
  id:'11111111-1111-4111-8111-111111111111',kb_id:kbId,filename:'新版本.txt',status:'parsed',
  active_revision_id:'33333333-3333-4333-8333-333333333333',candidate_revision_id:'44444444-4444-4444-8444-444444444444',
  created_at:'2026-09-25T12:00:00Z',
  active_revision:{id:'33333333-3333-4333-8333-333333333333',filename:'旧版本.txt',content_sha256:'a'.repeat(64),parser_version:'1',created_at:'2026-09-24T12:00:00Z'},
  candidate_revision:{id:'44444444-4444-4444-8444-444444444444',filename:'新版本.txt',content_sha256:'b'.repeat(64),parser_version:'1',created_at:'2026-09-25T12:00:00Z'},
  latest_job:{id:'55555555-5555-4555-8555-555555555555',kind:'index',state:'queued',attempts:0,error_code:null,error_message:null,created_at:'2026-09-25T12:00:00Z',finished_at:null},
}
enableAutoUnmount(afterEach)
afterEach(async()=>{
  vi.stubGlobal('fetch',async()=>new Response(null,{status:204}))
  session.api.setCsrfToken('cleanup')
  await session.logout()
  vi.unstubAllGlobals()
})

it('shows active and candidate versions separately and calls parsed pending index',async()=>{
  session.api.setCsrfToken('csrf')
  vi.stubGlobal('fetch',async(url:string)=>url.endsWith('/auth/login')?new Response(JSON.stringify({user:{id:'a',username:'reader',display_name:'Reader',role:'user',is_active:true,created_at:''},csrf_token:'csrf'})):new Response(JSON.stringify({items:[document],total:1,page:1,page_size:20})))
  await session.login({username:'reader',password:'test'})
  const wrapper=mount(DocumentList,{props:{kbId}})
  await flushPromises()
  expect(wrapper.text()).toContain('旧版本.txt')
  expect(wrapper.text()).toContain('新版本.txt')
  expect(wrapper.text()).toContain('解析完成，待建立索引')
  expect(wrapper.text()).toContain('当前有效版本')
  expect(wrapper.text()).toContain('新版本处理')
  expect(wrapper.get('button[aria-label="下载原文件"]').text()).toContain('下载原文件')
  expect(wrapper.text()).not.toContain('上传新版本')
  expect(wrapper.text()).not.toContain('删除文档')
})

it('admin can retry failed parsing and receives an error on a failed write',async()=>{
  session.api.setCsrfToken('csrf')
  const failed={...document,status:'failed',active_revision_id:null,active_revision:null,candidate_revision:null,latest_job:{...document.latest_job,state:'failed',kind:'parse',error_code:'NO_TEXT',error_message:'未提取到文本'}}
  const calls:string[]=[]
  vi.stubGlobal('fetch',async(url:string,options:RequestInit={})=>{
    calls.push((options.method??'GET')+' '+url)
    if(url.endsWith('/auth/login')) return new Response(JSON.stringify({user:{id:'a',username:'admin',display_name:'Admin',role:'admin',is_active:true,created_at:''},csrf_token:'csrf'}))
    if(options.method==='POST') return new Response(JSON.stringify({error:{code:'CONFLICT',message:'已有任务正在执行'}}),{status:409})
    return new Response(JSON.stringify({items:[failed],total:1,page:1,page_size:20}))
  })
  await session.login({username:'admin',password:'test'})
  const wrapper=mount(DocumentList,{props:{kbId}})
  await flushPromises()
  expect(wrapper.text()).toContain('未提取到文本')
  await wrapper.get('button[aria-label="重试解析"]').trigger('click')
  await flushPromises()
  expect(calls).toContain('POST /api/v1/documents/'+document.id+'/reindex')
  expect(wrapper.get('[role="alert"]').text()).toContain('已有任务正在执行')
})

it('ignores a stale list response after knowledge base changes',async()=>{
  let resolveOld!: (response:Response)=>void
  vi.stubGlobal('fetch',(url:string)=>url.includes(kbId)?new Promise<Response>(r=>{resolveOld=r}):Promise.resolve(new Response(JSON.stringify({items:[],total:0,page:1,page_size:20}))))
  const wrapper=mount(DocumentList,{props:{kbId}})
  await wrapper.setProps({kbId:'66666666-6666-4666-8666-666666666666'})
  await flushPromises()
  resolveOld(new Response(JSON.stringify({items:[document],total:1,page:1,page_size:20})))
  await flushPromises()
  expect(wrapper.text()).toContain('暂无文档')
  expect(wrapper.text()).not.toContain('旧版本.txt')
})

it('shows a download authorization error in the document panel',async()=>{
  vi.stubGlobal('fetch',async(url:string)=>url.endsWith('/download')?new Response(JSON.stringify({error:{code:'FORBIDDEN',message:'禁止访问'}}),{status:403}):new Response(JSON.stringify({items:[document],total:1,page:1,page_size:20})))
  const wrapper=mount(DocumentList,{props:{kbId}})
  await flushPromises()
  await wrapper.get('button[aria-label="下载原文件"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('没有访问权限')
})
