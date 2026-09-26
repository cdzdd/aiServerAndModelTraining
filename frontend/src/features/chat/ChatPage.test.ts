import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { session } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import ChatPage from './ChatPage.vue'
import * as api from './api'

vi.mock('./api',()=>({
  listConversations:vi.fn(),getConversation:vi.fn(),listMessages:vi.fn(),listAvailableKnowledge:vi.fn(),
  createConversation:vi.fn(),deleteConversation:vi.fn(),postText:vi.fn(),streamQuestion:vi.fn(),
}))
enableAutoUnmount(afterEach)
const conversation={id:'c',user_id:'owner',title:'历史提问',kb_ids:['kb'],mode:'bot' as const,assigned_agent_id:null,created_at:'2026-09-26T00:00:00Z',updated_at:'2026-09-26T00:00:00Z'}
const message={id:'a',conversation_id:'c',role:'assistant' as const,author_id:null,content:'安全答案',status:'complete' as const,citations:[],client_message_id:null,in_reply_to_id:'u',answer_status:'answered',evidence_level:'sufficient',intent:'knowledge',latency_ms:5,error_code:null,created_at:'2026-09-26T00:00:00Z',evidence_hidden:false}
const page=<T,>(items:T[])=>({items,total:items.length,page:1,page_size:50})
async function mountPage(mode:'bot'|'queued'|'closed'='bot') {
  session.api.setCsrfToken('test')
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:{id:'owner',username:'owner',display_name:'Owner',role:'user',is_active:true,created_at:''},csrf_token:'test'})))
  await session.login({username:'owner',password:'test'})
  vi.mocked(api.listConversations).mockResolvedValue(page([{...conversation,mode}]))
  vi.mocked(api.getConversation).mockResolvedValue({...conversation,mode})
  vi.mocked(api.listMessages).mockResolvedValue(page([]))
  vi.mocked(api.listAvailableKnowledge).mockResolvedValue(page([]))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/chat/:id?',component:ChatPage}]})
  await router.push('/chat/c');await router.isReady()
  const wrapper=mount(ChatPage,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}
afterEach(async()=>{
  vi.stubGlobal('fetch',async()=>new Response(null,{status:204}))
  session.api.setCsrfToken('cleanup')
  await session.logout()
  vi.unstubAllGlobals();vi.clearAllMocks();vi.useRealTimers()
})

it('streams a bot answer and refreshes persisted history after done',async()=>{
  let usedKey=''
  vi.mocked(api.streamQuestion).mockImplementation((_id,_content,key)=>{
    usedKey=key
    vi.mocked(api.listMessages).mockResolvedValue(page([message]))
    return (async function*(){yield new TextEncoder().encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\nevent: delta\ndata: {"text":"安全答案"}\n\nevent: done\ndata: {"answer_status":"answered","evidence_level":"sufficient","intent":"knowledge"}\n\n')})()
  })
  const wrapper=await mountPage()
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('问题')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  expect(usedKey).toMatch(/^[0-9a-f-]{36}$/)
  expect(wrapper.text()).toContain('安全答案')
  expect(wrapper.text()).not.toContain('生成中…')
})

it('uses ordinary text POST in queued mode without invoking the AI stream',async()=>{
  vi.mocked(api.postText).mockResolvedValue({...message,role:'user',author_id:'owner',content:'留言'})
  const wrapper=await mountPage('queued')
  expect(wrapper.text()).toContain('等待客服')
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('留言')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  expect(api.postText).toHaveBeenCalledWith('c','留言',expect.stringMatching(/^[0-9a-f-]{36}$/))
  expect(api.streamQuestion).not.toHaveBeenCalled()
})

it('makes closed conversations read-only',async()=>{
  const wrapper=await mountPage('closed')
  expect(wrapper.text()).toContain('已关闭')
  expect(wrapper.find('textarea[aria-label="消息内容"]').exists()).toBe(false)
})

it('stops a stream and retries manually with a fresh client key',async()=>{
  const keys:string[]=[],encoder=new TextEncoder()
  vi.mocked(api.streamQuestion).mockImplementation((_id,_content,key,signal)=>{
    keys.push(key)
    if(keys.length===1) return (async function*(){
      yield encoder.encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\n')
      await new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new ApiError(0,'CANCELLED','已停止生成。')),{once:true}))
    })()
    return (async function*(){yield encoder.encode('event: meta\ndata: {"user_message_id":"u2","assistant_message_id":"a2"}\n\nevent: done\ndata: {"answer_status":"no_answer","evidence_level":"none","intent":"knowledge"}\n\n')})()
  })
  const wrapper=await mountPage()
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('再问一次')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='停止生成')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('已停止生成')
  await wrapper.findAll('button').find(button=>button.text()==='重试提问')!.trigger('click')
  await flushPromises()
  expect(keys).toHaveLength(2)
  expect(keys[0]).not.toBe(keys[1])
})

it('refreshes a delayed cancelled record without starting another AI request',async()=>{
  const encoder=new TextEncoder(),pending={...message,status:'generating' as const,content:'部分回答'},cancelled={...message,status:'cancelled' as const,content:'部分回答'}
  vi.mocked(api.streamQuestion).mockImplementation((_id,_content,_key,signal)=>(async function*(){
    yield encoder.encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\n')
    await new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new ApiError(0,'CANCELLED','已停止生成。')),{once:true}))
  })())
  const wrapper=await mountPage()
  let reads=0
  vi.mocked(api.listMessages).mockImplementation(async()=>page([++reads===1?pending:cancelled]))
  vi.useFakeTimers()
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('取消这个问题')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='停止生成')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('生成中…')
  await vi.advanceTimersByTimeAsync(2000)
  await flushPromises()
  expect(wrapper.text()).toContain('已取消')
  expect(api.streamQuestion).toHaveBeenCalledTimes(1)
})

it('loads an older message page only once when its button is clicked twice quickly',async()=>{
  const wrapper=await mountPage()
  const first=Array.from({length:50},(_,index)=>({...message,id:'m'+index,content:'记录'+index}))
  let olderResolve!:(value:{items:typeof message[];total:number;page:number;page_size:number})=>void
  let delayed=false,olderCalls=0
  vi.mocked(api.listMessages).mockImplementation(async(_id,target=1)=>{
    if(target===2) return {items:[{...message,id:'last'}],total:51,page:2,page_size:50}
    if(!delayed) return {items:first,total:51,page:1,page_size:50}
    olderCalls++
    return new Promise(resolve=>{olderResolve=resolve})
  })
  await wrapper.findAll('button').find(button=>button.text()==='刷新历史')!.trigger('click')
  await flushPromises()
  delayed=true
  const button=wrapper.findAll('button').find(value=>value.text()==='加载更早消息')!
  await button.trigger('click')
  await button.trigger('click')
  expect(olderCalls).toBe(1)
  olderResolve({items:first,total:51,page:1,page_size:50})
  await flushPromises()
  expect(wrapper.findAll('.message')).toHaveLength(51)
})

it('keeps a rate-limit explanation visible after refreshing history',async()=>{
  vi.mocked(api.streamQuestion).mockImplementation(()=>(async function*(){throw new ApiError(429,'RATE_LIMITED','今日提问次数已用完');yield new Uint8Array()})())
  const wrapper=await mountPage()
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('还有问题')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('操作过于频繁')
  expect(wrapper.text()).toContain('重试提问')
})

it('closes an open citation panel when refreshed history hides the evidence',async()=>{
  const citation={index:1,chunk_id:'chunk',kb_id:'kb',source_type:'faq' as const,source_id:'faq',title:'撤销前来源',quote:'原始引用',revision_id:null,faq_version:1,page_number:null,paragraph_number:null,line_number:null}
  const wrapper=await mountPage()
  vi.mocked(api.listMessages).mockResolvedValue(page([{...message,citations:[citation]}]))
  await wrapper.findAll('button').find(button=>button.text()==='刷新历史')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text().includes('查看引用'))!.trigger('click')
  expect(wrapper.text()).toContain('原始引用')
  vi.mocked(api.listMessages).mockResolvedValue(page([{...message,citations:[],evidence_hidden:true,content:'来源已不可用'}]))
  await wrapper.findAll('button').find(button=>button.text()==='刷新历史')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('原始引用')
})
