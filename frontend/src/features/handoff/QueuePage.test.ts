import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { session, type Role } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import QueuePage from './QueuePage.vue'
import * as api from './api'

vi.mock('./api',()=>({listQueue:vi.fn(),claimHandoff:vi.fn()}))
enableAutoUnmount(afterEach)
const item={id:'handoff-id',conversation_id:'private-cid',requested_at:'2026-09-26T00:00:00Z',state:'queued' as const}
async function mountQueue(role:Role) {
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:{id:role,username:role,display_name:role,role,is_active:true,created_at:''},csrf_token:'test'})))
  await session.login({username:role,password:'test'})
  vi.mocked(api.listQueue).mockResolvedValue({items:[item],total:1,page:1,page_size:20})
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/handoffs',component:QueuePage},{path:'/handoffs/:handoffId',component:{template:'<p>已接单</p>'}}]})
  await router.push('/handoffs');await router.isReady()
  const wrapper=mount(QueuePage,{global:{plugins:[router]}})
  await flushPromises()
  return {wrapper,router}
}
afterEach(async()=>{
  vi.stubGlobal('fetch',async()=>new Response(null,{status:204}))
  session.api.setCsrfToken('cleanup')
  await session.logout()
  vi.unstubAllGlobals();vi.clearAllMocks()
})

it('shows only minimal queue metadata and lets an agent claim once',async()=>{
  vi.mocked(api.claimHandoff).mockResolvedValue({id:item.id,conversation_id:item.conversation_id,state:'human',requested_at:item.requested_at,claimed_at:'',closed_at:null,assigned_agent_id:'agent'})
  const {wrapper,router}=await mountQueue('agent')
  expect(wrapper.text()).toContain('待接单')
  expect(wrapper.text()).not.toContain('private-cid')
  expect(wrapper.text()).not.toContain('会话标题')
  const button=wrapper.findAll('button').find(value=>value.text()==='接单')!
  await button.trigger('click')
  await button.trigger('click')
  await flushPromises()
  expect(api.claimHandoff).toHaveBeenCalledTimes(1)
  expect(router.currentRoute.value.path).toBe('/handoffs/handoff-id')
})

it('does not offer claim to admins',async()=>{
  const {wrapper}=await mountQueue('admin')
  expect(wrapper.findAll('button').some(value=>value.text()==='接单')).toBe(false)
})

it('refreshes the queue after a competing agent wins',async()=>{
  vi.mocked(api.claimHandoff).mockRejectedValue(new ApiError(409,'CONVERSATION_STATE','已被领取'))
  const {wrapper}=await mountQueue('agent')
  vi.mocked(api.listQueue).mockResolvedValue({items:[],total:0,page:1,page_size:20})
  await wrapper.findAll('button').find(value=>value.text()==='接单')!.trigger('click')
  await flushPromises()
  expect(api.listQueue).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('已被领取')
  expect(wrapper.findAll('button').some(value=>value.text()==='接单')).toBe(false)
})

it('ignores a claim that finishes after the queue page unmounts',async()=>{
  let release!:(value:{id:string;conversation_id:string;state:'human';requested_at:string;claimed_at:string;closed_at:null;assigned_agent_id:string})=>void
  vi.mocked(api.claimHandoff).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const {wrapper,router}=await mountQueue('agent')
  await wrapper.findAll('button').find(value=>value.text()==='接单')!.trigger('click')
  wrapper.unmount()
  release({id:item.id,conversation_id:item.conversation_id,state:'human',requested_at:item.requested_at,claimed_at:'',closed_at:null,assigned_agent_id:'agent'})
  await flushPromises()
  expect(router.currentRoute.value.path).not.toBe('/handoffs/handoff-id')
})

it('does not refetch a stale queue after an unmounted claim returns conflict',async()=>{
  let reject!:(reason:unknown)=>void
  vi.mocked(api.claimHandoff).mockImplementation(()=>new Promise((_resolve,fail)=>{reject=fail}))
  const {wrapper}=await mountQueue('agent')
  await wrapper.findAll('button').find(value=>value.text()==='接单')!.trigger('click')
  wrapper.unmount()
  reject(new ApiError(409,'CONVERSATION_STATE','已被领取'))
  await flushPromises()
  expect(api.listQueue).toHaveBeenCalledTimes(1)
})

it('does not navigate back to a claimed handoff after leaving the queue route',async()=>{
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:{id:'agent',username:'agent',display_name:'Agent',role:'agent',is_active:true,created_at:''},csrf_token:'test'})))
  await session.login({username:'agent',password:'test'})
  vi.mocked(api.listQueue).mockResolvedValue({items:[item],total:1,page:1,page_size:20})
  let release!:(value:{id:string;conversation_id:string;state:'human';requested_at:string;claimed_at:string;closed_at:null;assigned_agent_id:string})=>void
  vi.mocked(api.claimHandoff).mockImplementation(()=>new Promise(resolve=>{release=resolve}))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/handoffs',component:QueuePage},{path:'/handoffs/:id',component:{template:'<p>工作台</p>'}},{path:'/elsewhere',component:{template:'<p>别处</p>'}}]})
  await router.push('/handoffs');await router.isReady()
  const wrapper=mount(RouterView,{global:{plugins:[router]}})
  await flushPromises()
  await wrapper.findAll('button').find(value=>value.text()==='接单')!.trigger('click')
  await router.push('/elsewhere');await flushPromises()
  release({id:item.id,conversation_id:item.conversation_id,state:'human',requested_at:item.requested_at,claimed_at:'',closed_at:null,assigned_agent_id:'agent'})
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/elsewhere')
  wrapper.unmount()
})

it('can claim from the queue route with a trailing slash',async()=>{
  vi.mocked(api.claimHandoff).mockResolvedValue({id:item.id,conversation_id:item.conversation_id,state:'human',requested_at:item.requested_at,claimed_at:'',closed_at:null,assigned_agent_id:'agent'})
  const {wrapper,router}=await mountQueue('agent')
  await router.push('/handoffs/')
  await wrapper.findAll('button').find(value=>value.text()==='接单')!.trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/handoffs/handoff-id')
})
