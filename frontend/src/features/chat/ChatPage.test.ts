import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { session } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import ChatPage from './ChatPage.vue'
import * as api from './api'
import type { ConversationView } from './api'
import * as handoff from '../handoff/api'

vi.mock('./api',()=>({
  listConversations:vi.fn(),getConversation:vi.fn(),listMessages:vi.fn(),listAvailableKnowledge:vi.fn(),
  createConversation:vi.fn(),deleteConversation:vi.fn(),postText:vi.fn(),streamQuestion:vi.fn(),
  getModelStatus:vi.fn(),
}))
vi.mock('../handoff/api',()=>({requestHandoff:vi.fn()}))
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
  vi.mocked(api.getModelStatus).mockResolvedValue({state:'ready',provider:'queued',model_id:'local-model',available:true})
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

it('displays an offline model status without disabling human support or discarding the draft',async()=>{
  const wrapper=await mountPage()
  vi.mocked(api.getModelStatus).mockResolvedValue({state:'offline',provider:'queued',model_id:'local-model',available:false})
  await wrapper.get('button[aria-label="刷新模型状态"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('本地模型未连接')
  expect(wrapper.findAll('button').find(button=>button.text()==='申请人工客服')!.attributes('disabled')).toBeUndefined()
  vi.mocked(api.streamQuestion).mockImplementation(()=>(async function*(){throw new ApiError(503,'MODEL_OFFLINE','本地模型未连接');yield new Uint8Array()})())
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('需要查询借阅规则')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  expect(wrapper.get('textarea').element.value).toBe('需要查询借阅规则')
  expect(api.streamQuestion).toHaveBeenCalledTimes(1)
})

it('shows progress until a terminal event and preserves the persisted failure explanation',async()=>{
  let finish!:()=>void
  const wrapper=await mountPage()
  const failed={...message,status:'failed' as const,error_code:'PROVIDER_TIMEOUT',content:''}
  vi.mocked(api.streamQuestion).mockImplementation(()=>(async function*(){
    yield new TextEncoder().encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\nevent: progress\ndata: {"stage":"generating"}\n\n')
    await new Promise<void>(resolve=>{finish=resolve})
    vi.mocked(api.listMessages).mockResolvedValue(page([failed]))
    yield new TextEncoder().encode('event: error\ndata: {"code":"PROVIDER_TIMEOUT","message":"模型服务响应超时"}\n\n')
  })())
  await wrapper.get('textarea').setValue('借阅规则')
  await wrapper.get('form.composer').trigger('submit');await flushPromises()
  expect(wrapper.get('.message-list').text()).toContain('模型正在生成')
  finish();await flushPromises()
  expect(wrapper.get('.message-list').text()).toContain('模型服务响应超时')
  expect(wrapper.get('.message-list').text()).not.toContain('模型正在生成')
  expect(wrapper.get('textarea').element.value).toBe('借阅规则')
})

it('retries a persisted failed reply with the original question and a new request key only on click',async()=>{
  const wrapper=await mountPage()
  const question={...message,id:'u',role:'user' as const,author_id:'owner',in_reply_to_id:null,content:'原来的借阅问题'}
  vi.mocked(api.listMessages).mockResolvedValue(page([question,{...message,status:'failed',content:'',error_code:'MODEL_OFFLINE'}]))
  await wrapper.findAll('button').find(button=>button.text()==='刷新历史')!.trigger('click');await flushPromises()
  expect(api.streamQuestion).not.toHaveBeenCalled()
  await wrapper.get('textarea').setValue('另一条尚未发送的问题')
  vi.mocked(api.streamQuestion).mockImplementation(()=>(async function*(){yield new TextEncoder().encode('event: meta\ndata: {"user_message_id":"new-u","assistant_message_id":"new-a"}\n\nevent: done\ndata: {"answer_status":"no_answer","evidence_level":"none","intent":"knowledge"}\n\n')})())
  await wrapper.get('button[aria-label="重试这条提问"]').trigger('click');await flushPromises()
  expect(api.streamQuestion).toHaveBeenCalledWith('c','原来的借阅问题',expect.stringMatching(/^[0-9a-f-]{36}$/),expect.any(AbortSignal))
  expect(wrapper.get('textarea').element.value).toBe('另一条尚未发送的问题')
})

it('describes other providers as configured and shows an unavailable check without blocking composition',async()=>{
  const wrapper=await mountPage()
  vi.mocked(api.getModelStatus).mockResolvedValue({state:'ready',provider:'cloud',model_id:'cloud-model',available:true})
  await wrapper.get('button[aria-label="刷新模型状态"]').trigger('click');await flushPromises()
  expect(wrapper.get('[aria-label="模型服务状态"]').text()).toContain('已配置云端模型')
  expect(wrapper.get('[aria-label="模型服务状态"]').text()).not.toContain('已连接')
  vi.mocked(api.getModelStatus).mockRejectedValue(new ApiError(503,'UNAVAILABLE','内部错误'))
  await wrapper.get('button[aria-label="刷新模型状态"]').trigger('click');await flushPromises()
  expect(wrapper.get('[aria-label="模型服务状态"]').text()).toContain('暂时无法确认模型状态')
  expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
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

it('requests human support once while an answer is streaming and switches to queued text',async()=>{
  let aborted=false
  vi.mocked(api.streamQuestion).mockImplementation((_id,_content,_key,signal)=>(async function*(){
    yield new TextEncoder().encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\n')
    await new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(new ApiError(0,'CANCELLED','stopped'))},{once:true}))
  })())
  vi.mocked(handoff.requestHandoff).mockImplementation(async()=>{
    vi.mocked(api.getConversation).mockResolvedValue({...conversation,mode:'queued'})
    return {id:'h',conversation_id:'c',state:'queued',requested_at:'',claimed_at:null,closed_at:null,assigned_agent_id:null}
  })
  const wrapper=await mountPage()
  await wrapper.get('textarea[aria-label="消息内容"]').setValue('正在生成')
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
  const button=wrapper.findAll('button').find(value=>value.text()==='申请人工客服')!
  await button.trigger('click')
  await button.trigger('click')
  await flushPromises()
  expect(handoff.requestHandoff).toHaveBeenCalledTimes(1)
  expect(aborted).toBe(true)
  expect(wrapper.text()).toContain('等待客服')
  expect(wrapper.findAll('button').some(value=>value.text()==='发送留言')).toBe(true)
})

it('polls queued history without overlapping requests and stops after closure',async()=>{
  vi.useFakeTimers()
  const wrapper=await mountPage('queued')
  let release!:(value:ConversationView)=>void,reads=0
  vi.mocked(api.getConversation).mockImplementation(()=>{reads++;return new Promise(resolve=>{release=resolve})})
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  release({...conversation,mode:'closed'})
  await flushPromises()
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  expect(wrapper.text()).toContain('仅可阅读历史')
})

it('keeps older loaded messages while polling a queued conversation',async()=>{
  vi.useFakeTimers()
  const wrapper=await mountPage('queued')
  const older=Array.from({length:50},(_,index)=>({...message,id:'old'+index,content:'旧消息'+index}))
  vi.mocked(api.listMessages).mockImplementation(async(_id,target=1)=>target===1?{items:older,total:51,page:1,page_size:50}:{items:[{...message,id:'latest'}],total:51,page:2,page_size:50})
  await wrapper.findAll('button').find(value=>value.text()==='刷新历史')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(value=>value.text()==='加载更早消息')!.trigger('click')
  await flushPromises()
  expect(wrapper.findAll('.message')).toHaveLength(51)
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  expect(wrapper.findAll('.message')).toHaveLength(51)
})

it('ignores a handoff response after leaving the old chat instance',async()=>{
  let release!:(value:{id:string;conversation_id:string;state:'queued';requested_at:string;claimed_at:null;closed_at:null;assigned_agent_id:null})=>void
  vi.mocked(handoff.requestHandoff).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const wrapper=await mountPage()
  const reads=vi.mocked(api.getConversation).mock.calls.length
  await wrapper.findAll('button').find(value=>value.text()==='申请人工客服')!.trigger('click')
  wrapper.unmount()
  release({id:'h',conversation_id:'c',state:'queued',requested_at:'',claimed_at:null,closed_at:null,assigned_agent_id:null})
  await flushPromises()
  expect(api.getConversation).toHaveBeenCalledTimes(reads)
})

it('does not revive an old handoff after navigating away and returning to the same chat',async()=>{
  vi.useFakeTimers()
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:{id:'owner',username:'owner',display_name:'Owner',role:'user',is_active:true,created_at:''},csrf_token:'test'})))
  await session.login({username:'owner',password:'test'})
  vi.mocked(api.listConversations).mockResolvedValue(page([conversation]))
  vi.mocked(api.getConversation).mockResolvedValue(conversation)
  vi.mocked(api.listMessages).mockResolvedValue(page([]))
  let release!:(value:{id:string;conversation_id:string;state:'queued';requested_at:string;claimed_at:null;closed_at:null;assigned_agent_id:null})=>void
  vi.mocked(handoff.requestHandoff).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/chat/:id',component:ChatPage},{path:'/elsewhere',component:{template:'<p>别处</p>'}}]})
  await router.push('/chat/c');await router.isReady()
  const wrapper=mount(RouterView,{global:{plugins:[router]}})
  await flushPromises()
  await wrapper.findAll('button').find(value=>value.text()==='申请人工客服')!.trigger('click')
  await router.push('/elsewhere');await flushPromises()
  await router.push('/chat/c');await flushPromises()
  const reads=vi.mocked(api.getConversation).mock.calls.length
  vi.mocked(api.getConversation).mockResolvedValue({...conversation,mode:'queued'})
  release({id:'h',conversation_id:'c',state:'queued',requested_at:'',claimed_at:null,closed_at:null,assigned_agent_id:null})
  await flushPromises()
  await vi.advanceTimersByTimeAsync(3000)
  expect(api.getConversation).toHaveBeenCalledTimes(reads)
  wrapper.unmount()
})
