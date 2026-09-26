import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import AuditLogPage from './AuditLogPage.vue'
import { getAuditEvent, listAuditEvents, type AuditEventView } from './api'
import { ApiError } from '../../shared/api/errors'
import { session, type User } from '../auth/session'

vi.mock('./api',async()=>({...await vi.importActual<typeof import('./api')>('./api'),getAuditEvent:vi.fn(),listAuditEvents:vi.fn()}))
enableAutoUnmount(afterEach)
afterEach(()=>vi.unstubAllGlobals())
beforeEach(()=>vi.clearAllMocks())
const item:AuditEventView={id:'e',actor_id:'actor',action:'feedback.resolve',summary:'处理回答反馈',target_type:'feedback',target_id:'target',outcome:'success',request_id:'request',created_at:'2026-09-25T09:10:00Z',metadata:{changed_fields:['status','resolution'],status:'resolved'}}

it('filters and opens a safe audit detail without interpreting metadata as HTML',async()=>{
  vi.mocked(listAuditEvents).mockResolvedValue({items:[item],total:1,page:1,page_size:20})
  vi.mocked(getAuditEvent).mockResolvedValue({...item,summary:'<script>bad</script>'})
  const wrapper=mount(AuditLogPage)
  await flushPromises()
  expect(wrapper.text()).toContain('处理回答反馈')
  await wrapper.get('input[aria-label="动作筛选"]').setValue('feedback.resolve')
  await wrapper.get('button[aria-label="查询审计"]').trigger('click')
  await flushPromises()
  expect(listAuditEvents).toHaveBeenLastCalledWith(expect.objectContaining({page:1,action:'feedback.resolve'}))
  await wrapper.get('button[aria-label="查看审计详情"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('<script>bad</script>')
  expect(wrapper.find('script').exists()).toBe(false)
})

it('clears old privileged rows after access is denied but keeps a retry path',async()=>{
  vi.mocked(listAuditEvents).mockResolvedValueOnce({items:[item],total:1,page:1,page_size:20}).mockRejectedValueOnce(new ApiError(403,'FORBIDDEN','forbidden')).mockResolvedValueOnce({items:[],total:0,page:1,page_size:20})
  const wrapper=mount(AuditLogPage)
  await flushPromises()
  expect(wrapper.text()).toContain('处理回答反馈')
  await wrapper.get('button[aria-label="查询审计"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('处理回答反馈')
  expect(wrapper.get('[role="alert"]').text()).toContain('没有访问权限')
  await wrapper.get('button[aria-label="重试审计"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('暂无审计记录')
})

it('hides old rows and ignores a pending detail after same-ID administrator demotion',async()=>{
  const admin:User={id:'admin',username:'admin',display_name:'admin',role:'admin',is_active:true,created_at:''}
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:admin,csrf_token:'test'})))
  await session.login({username:'admin',password:'test'})
  vi.mocked(listAuditEvents).mockResolvedValue({items:[item],total:1,page:1,page_size:20})
  let finish!: (result:AuditEventView)=>void
  vi.mocked(getAuditEvent).mockReturnValue(new Promise(done=>{finish=done}))
  const wrapper=mount(AuditLogPage)
  await flushPromises()
  await wrapper.get('button[aria-label="查看审计详情"]').trigger('click')
  session.acceptUserUpdate({...admin,role:'user'})
  finish(item)
  await flushPromises()
  expect(wrapper.text()).not.toContain('处理回答反馈')
  expect(wrapper.find('[aria-label="审计详情"]').exists()).toBe(false)
})

it('retries the attempted first page after a new filter fails while viewing page two',async()=>{
  vi.mocked(listAuditEvents).mockResolvedValueOnce({items:[item],total:40,page:1,page_size:20}).mockResolvedValueOnce({items:[item],total:40,page:2,page_size:20}).mockRejectedValueOnce(new Error('temporary failure')).mockResolvedValueOnce({items:[item],total:1,page:1,page_size:20})
  const wrapper=mount(AuditLogPage)
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='下一页')!.trigger('click')
  await flushPromises()
  await wrapper.get('input[aria-label="动作筛选"]').setValue('feedback.resolve')
  await wrapper.get('button[aria-label="查询审计"]').trigger('click')
  await flushPromises()
  expect(listAuditEvents).toHaveBeenLastCalledWith(expect.objectContaining({page:1,action:'feedback.resolve'}))
  await wrapper.get('button[aria-label="重试审计"]').trigger('click')
  await flushPromises()
  expect(listAuditEvents).toHaveBeenLastCalledWith(expect.objectContaining({page:1,action:'feedback.resolve'}))
})
