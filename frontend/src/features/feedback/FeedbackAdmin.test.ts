import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import FeedbackListPage from './FeedbackListPage.vue'
import FeedbackDetail from './FeedbackDetail.vue'
import { getFeedbackDetail, listFeedback, resolveFeedback } from './api'

const routeId=ref('f')
vi.mock('vue-router',()=>({useRoute:()=>({params:{get feedbackId(){return routeId.value}}}),RouterLink:{props:['to'],template:'<a><slot /></a>'}}))
vi.mock('./api',()=>({getFeedbackDetail:vi.fn(),listFeedback:vi.fn(),resolveFeedback:vi.fn()}))
enableAutoUnmount(afterEach)
const record={id:'f',message_id:'m',conversation_id:'c',user_id:'u',rating:'down' as const,comment:'<script>bad</script>',status:'open' as const,resolution:'',resolved_by:null,resolved_at:null,created_at:'2026-09-26T00:00:00Z',updated_at:'2026-09-26T00:00:00Z'}
beforeEach(()=>{vi.clearAllMocks();routeId.value='f'})

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
