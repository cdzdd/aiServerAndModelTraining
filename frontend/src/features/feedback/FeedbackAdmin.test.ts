import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { session, type User } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import FeedbackListPage from './FeedbackListPage.vue'
import FeedbackDetail from './FeedbackDetail.vue'
import { getFeedbackDetail, listFeedback, resolveFeedback } from './api'

const routeId=ref('f')
vi.mock('vue-router',()=>({useRoute:()=>({params:{get feedbackId(){return routeId.value}}}),RouterLink:{props:['to'],template:'<a><slot /></a>'}}))
vi.mock('./api',()=>({getFeedbackDetail:vi.fn(),listFeedback:vi.fn(),resolveFeedback:vi.fn()}))
enableAutoUnmount(afterEach)
const record={id:'f',message_id:'m',conversation_id:'c',user_id:'u',rating:'down' as const,comment:'<script>bad</script>',status:'open' as const,resolution:'',resolved_by:null,resolved_at:null,created_at:'2026-09-26T00:00:00Z',updated_at:'2026-09-26T00:00:00Z'}
beforeEach(()=>{vi.clearAllMocks();routeId.value='f'})
afterEach(()=>vi.unstubAllGlobals())
async function loginAdmin() {
  const user:User={id:'admin',username:'admin',display_name:'admin',role:'admin',is_active:true,created_at:''}
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user,csrf_token:'test'})))
  await session.login({username:'admin',password:'test'})
  return user
}

it('filters administrator feedback and escapes owner comments',async()=>{
  vi.mocked(listFeedback).mockResolvedValue({items:[record],total:1,page:1,page_size:20})
  const wrapper=mount(FeedbackListPage)
  await flushPromises()
  expect(wrapper.text()).toContain('<script>bad</script>')
  expect(wrapper.find('script').exists()).toBe(false)
  await wrapper.get('select[aria-label="处理状态筛选"]').setValue('open')
  await flushPromises()
  expect(listFeedback).toHaveBeenLastCalledWith(1,'open','')
})

it('resolves, reopens and keeps the message hidden when unavailable',async()=>{
  vi.mocked(getFeedbackDetail).mockResolvedValue({feedback:record,message_available:false,message:null})
  vi.mocked(resolveFeedback).mockResolvedValueOnce({...record,status:'resolved',resolution:'已核对'}).mockResolvedValueOnce(record)
  const wrapper=mount(FeedbackDetail)
  await flushPromises()
  expect(wrapper.text()).toContain('原回答不可查看')
  await wrapper.get('textarea[aria-label="处理说明"]').setValue('已核对')
  await wrapper.get('button[aria-label="标记已处理"]').trigger('click')
  await flushPromises()
  expect(resolveFeedback).toHaveBeenCalledWith('f',{status:'resolved',resolution:'已核对'})
  expect(wrapper.text()).toContain('已处理')
  await wrapper.get('button[aria-label="重新打开反馈"]').trigger('click')
  await flushPromises()
  expect(resolveFeedback).toHaveBeenLastCalledWith('f',{status:'open',resolution:''})
})

it('ignores a late detail response after route identity changes',async()=>{
  let finish!: (value:{feedback:typeof record;message_available:boolean;message:null})=>void
  vi.mocked(getFeedbackDetail).mockReturnValueOnce(new Promise(done=>{finish=done})).mockResolvedValueOnce({feedback:{...record,id:'next',comment:'new'},message_available:false,message:null})
  const wrapper=mount(FeedbackDetail)
  routeId.value='next'
  await flushPromises()
  finish({feedback:record,message_available:false,message:null})
  await flushPromises()
  expect(wrapper.text()).toContain('new')
  expect(wrapper.text()).not.toContain('<script>bad</script>')
})

it('clears old comments after an explicit permission failure and after a role downgrade',async()=>{
  const admin=await loginAdmin()
  vi.mocked(listFeedback).mockResolvedValue({items:[record],total:1,page:1,page_size:20})
  const wrapper=mount(FeedbackListPage)
  await flushPromises()
  expect(wrapper.text()).toContain('<script>bad</script>')
  vi.mocked(listFeedback).mockRejectedValue(new ApiError(403,'FORBIDDEN','forbidden'))
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('<script>bad</script>')
  expect(wrapper.get('[role="alert"]').text()).toContain('没有访问权限')
  vi.mocked(listFeedback).mockResolvedValue({items:[record],total:1,page:1,page_size:20})
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('<script>bad</script>')
  session.acceptUserUpdate({...admin,role:'user'})
  await flushPromises()
  expect(wrapper.text()).not.toContain('<script>bad</script>')
})

it('clears old answer and buttons when processing access is revoked',async()=>{
  await loginAdmin()
  vi.mocked(getFeedbackDetail).mockResolvedValue({feedback:record,message_available:false,message:null})
  vi.mocked(resolveFeedback).mockRejectedValue(new ApiError(403,'FORBIDDEN','forbidden'))
  const wrapper=mount(FeedbackDetail)
  await flushPromises()
  await wrapper.get('textarea').setValue('已核对')
  await wrapper.get('button[aria-label="标记已处理"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('<script>bad</script>')
  expect(wrapper.find('button[aria-label="标记已处理"]').exists()).toBe(false)
  expect(wrapper.get('[role="alert"]').text()).toContain('没有访问权限')
  vi.mocked(getFeedbackDetail).mockResolvedValue({feedback:record,message_available:false,message:null})
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('<script>bad</script>')
})
