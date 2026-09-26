import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { session, type Role } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import AgentConversationPage from './AgentConversationPage.vue'
import * as handoff from './api'
import type { HandoffView } from './api'
import * as chat from '../chat/api'
import type { MessageView } from '../chat/api'

vi.mock('./api',()=>({getHandoff:vi.fn(),closeHandoff:vi.fn()}))
vi.mock('../chat/api',()=>({getConversation:vi.fn(),listMessages:vi.fn(),postText:vi.fn()}))
enableAutoUnmount(afterEach)
const transfer={id:'h',conversation_id:'c',state:'human' as const,requested_at:'2026-09-26T00:00:00Z',claimed_at:'2026-09-26T00:01:00Z',closed_at:null,assigned_agent_id:'agent'}
const conversation={id:'c',user_id:'owner',title:'需要人工处理',kb_ids:['kb'],mode:'human' as const,assigned_agent_id:'agent',created_at:'',updated_at:''}
const message={id:'m',conversation_id:'c',role:'user' as const,author_id:'owner',content:'用户留言',status:'complete' as const,citations:[],client_message_id:null,in_reply_to_id:null,answer_status:null,evidence_level:null,intent:null,latency_ms:null,error_code:null,created_at:'2026-09-26T00:00:00Z',evidence_hidden:false}
const page=(items:typeof message[])=>({items,total:items.length,page:1,page_size:50})
async function mountPage(role:Role) {
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:{id:role,username:role,display_name:role,role,is_active:true,created_at:''},csrf_token:'test'})))
  await session.login({username:role,password:'test'})
  vi.mocked(handoff.getHandoff).mockResolvedValue(transfer)
  vi.mocked(chat.getConversation).mockResolvedValue(conversation)
  vi.mocked(chat.listMessages).mockResolvedValue(page([message]))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/handoffs/:handoffId',component:AgentConversationPage}]})
  await router.push('/handoffs/h');await router.isReady()
  const wrapper=mount(AgentConversationPage,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}
afterEach(async()=>{
  vi.stubGlobal('fetch',async()=>new Response(null,{status:204}))
  session.api.setCsrfToken('cleanup')
  await session.logout()
  vi.unstubAllGlobals();vi.clearAllMocks();vi.useRealTimers()
})

it('shows claimed history, sends agent text without AI, and closes read-only',async()=>{
  vi.mocked(chat.postText).mockResolvedValue({...message,id:'reply',role:'agent',author_id:'agent',content:'客服回复'})
  vi.mocked(handoff.closeHandoff).mockImplementation(async()=>{
    vi.mocked(handoff.getHandoff).mockResolvedValue({...transfer,state:'closed',closed_at:'2026-09-26T00:02:00Z'})
    vi.mocked(chat.getConversation).mockResolvedValue({...conversation,mode:'closed'})
    return {...transfer,state:'closed',closed_at:'2026-09-26T00:02:00Z'}
  })
  const wrapper=await mountPage('agent')
  expect(wrapper.text()).toContain('用户留言')
  await wrapper.get('textarea[aria-label="回复内容"]').setValue('客服回复')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(chat.postText).toHaveBeenCalledWith('c','客服回复',expect.stringMatching(/^[0-9a-f-]{36}$/))
  await wrapper.findAll('button').find(value=>value.text()==='关闭会话')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('已关闭')
  expect(wrapper.find('textarea[aria-label="回复内容"]').exists()).toBe(false)
})

it('lets an admin close but not impersonate the assigned agent',async()=>{
  const wrapper=await mountPage('admin')
  expect(wrapper.find('textarea[aria-label="回复内容"]').exists()).toBe(false)
  expect(wrapper.findAll('button').some(value=>value.text()==='关闭会话')).toBe(true)
})

it('does not load history after an unassigned agent receives 404',async()=>{
  const wrapper=await mountPage('agent')
  vi.mocked(handoff.getHandoff).mockRejectedValue(new ApiError(404,'NOT_FOUND','不可见'))
  await wrapper.findAll('button').find(value=>value.text()==='刷新会话')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('用户留言')
  expect(wrapper.text()).toContain('不可访问')
})

it('polls human conversation without overlap and stops after close',async()=>{
  vi.useFakeTimers()
  const wrapper=await mountPage('agent')
  let release!:(value:HandoffView)=>void,reads=0
  vi.mocked(handoff.getHandoff).mockImplementation(()=>{reads++;return new Promise(resolve=>{release=resolve})})
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  release({...transfer,state:'closed',closed_at:'2026-09-26T00:02:00Z'})
  vi.mocked(chat.getConversation).mockResolvedValue({...conversation,mode:'closed'})
  await flushPromises()
  await vi.advanceTimersByTimeAsync(3000)
  expect(reads).toBe(1)
  expect(wrapper.text()).toContain('已关闭')
})

it('keeps loaded older messages after polling current history',async()=>{
  vi.useFakeTimers()
  const wrapper=await mountPage('agent')
  const older=Array.from({length:50},(_,index)=>({...message,id:'old'+index,content:'旧消息'+index}))
  vi.mocked(chat.listMessages).mockImplementation(async(_id,target=1)=>target===1?{items:older,total:51,page:1,page_size:50}:{items:[{...message,id:'latest'}],total:51,page:2,page_size:50})
  await wrapper.findAll('button').find(value=>value.text()==='刷新会话')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(value=>value.text()==='加载更早消息')!.trigger('click')
  await flushPromises()
  expect(wrapper.findAll('.message')).toHaveLength(51)
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  expect(wrapper.findAll('.message')).toHaveLength(51)
})

it('ignores an old reply after leaving the workbench',async()=>{
  let release!:(value:MessageView)=>void
  vi.mocked(chat.postText).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const wrapper=await mountPage('agent')
  await wrapper.get('textarea[aria-label="回复内容"]').setValue('旧回复')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const reads=vi.mocked(handoff.getHandoff).mock.calls.length
  wrapper.unmount()
  release({...message,id:'reply',role:'agent',content:'旧回复'})
  await flushPromises()
  expect(handoff.getHandoff).toHaveBeenCalledTimes(reads)
})

it('continues polling after a close request fails',async()=>{
  vi.useFakeTimers()
  vi.mocked(handoff.closeHandoff).mockRejectedValue(new ApiError(503,'UNAVAILABLE','稍后重试'))
  const wrapper=await mountPage('agent')
  await wrapper.findAll('button').find(value=>value.text()==='关闭会话')!.trigger('click')
  await flushPromises()
  const reads=vi.mocked(handoff.getHandoff).mock.calls.length
  await vi.advanceTimersByTimeAsync(3000)
  expect(vi.mocked(handoff.getHandoff).mock.calls.length).toBeGreaterThan(reads)
})

it('ignores a close result after the workbench unmounts',async()=>{
  let release!:(value:HandoffView)=>void
  vi.mocked(handoff.closeHandoff).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const wrapper=await mountPage('agent')
  await wrapper.findAll('button').find(value=>value.text()==='关闭会话')!.trigger('click')
  const reads=vi.mocked(handoff.getHandoff).mock.calls.length
  wrapper.unmount()
  release({...transfer,state:'closed',closed_at:'2026-09-26T00:02:00Z'})
  await flushPromises()
  expect(handoff.getHandoff).toHaveBeenCalledTimes(reads)
})
