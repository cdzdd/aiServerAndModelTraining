import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { ApiError } from '../../shared/api/errors'
import FeedbackControl from './FeedbackControl.vue'
import { getOwnFeedback, submitFeedback, editFeedback } from './api'

vi.mock('./api',()=>({getOwnFeedback:vi.fn(),submitFeedback:vi.fn(),editFeedback:vi.fn()}))
enableAutoUnmount(afterEach)
const saved={id:'f',message_id:'m',conversation_id:'c',user_id:'u',rating:'down' as const,comment:'不准确',status:'resolved' as const,resolution:'已核对',resolved_by:'admin',resolved_at:'2026-09-26T00:00:00Z',created_at:'2026-09-26T00:00:00Z',updated_at:'2026-09-26T00:00:00Z'}
beforeEach(()=>vi.clearAllMocks())

it('loads persisted feedback, edits it once and shows reopened state',async()=>{
  vi.mocked(getOwnFeedback).mockResolvedValue(saved)
  vi.mocked(editFeedback).mockResolvedValue({...saved,comment:'仍不准确',status:'open',resolution:'',resolved_by:null,resolved_at:null})
  const wrapper=mount(FeedbackControl,{props:{messageId:'m'}})
  await flushPromises()
  expect(wrapper.text()).toContain('已处理')
  expect(wrapper.text()).toContain('已核对')
  await wrapper.get('textarea').setValue('仍不准确')
  await wrapper.get('button[aria-label="保存反馈修改"]').trigger('click')
  await flushPromises()
  expect(editFeedback).toHaveBeenCalledWith('f',{rating:'down',comment:'仍不准确'})
  expect(wrapper.text()).toContain('待处理')
  expect(wrapper.text()).not.toContain('已核对')
})

it('submits only once and keeps a failed request visible',async()=>{
  vi.mocked(getOwnFeedback).mockResolvedValue(null)
  let reject!: (error:unknown)=>void
  vi.mocked(submitFeedback).mockReturnValue(new Promise((_resolve,fail)=>{reject=fail}))
  const wrapper=mount(FeedbackControl,{props:{messageId:'m'}})
  await flushPromises()
  await wrapper.get('input[value="down"]').setValue()
  await wrapper.get('textarea').setValue('有误')
  await wrapper.get('button[aria-label="提交反馈"]').trigger('click')
  await wrapper.get('button[aria-label="提交反馈"]').trigger('click')
  expect(submitFeedback).toHaveBeenCalledTimes(1)
  reject(new ApiError(429,'RATE_LIMIT','太快了'))
  await flushPromises()
  expect(wrapper.text()).toContain('操作过于频繁')
})

it('discards a late response after the message changes',async()=>{
  let resolve!: (value:typeof saved)=>void
  vi.mocked(getOwnFeedback).mockReturnValueOnce(new Promise(done=>{resolve=done})).mockResolvedValueOnce(null)
  const wrapper=mount(FeedbackControl,{props:{messageId:'m'}})
  await wrapper.setProps({messageId:'other'})
  await flushPromises()
  resolve(saved)
  await nextTick()
  expect(wrapper.text()).not.toContain('已核对')
})

it('reloads an existing row after a conflicting create so the owner can edit it',async()=>{
  vi.mocked(getOwnFeedback).mockResolvedValueOnce(null).mockResolvedValueOnce(saved)
  vi.mocked(submitFeedback).mockRejectedValue(new ApiError(409,'FEEDBACK_EXISTS','已有反馈'))
  const wrapper=mount(FeedbackControl,{props:{messageId:'m'}})
  await flushPromises()
  await wrapper.get('input[value="up"]').setValue()
  await wrapper.get('button[aria-label="提交反馈"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('button[aria-label="保存反馈修改"]').exists()).toBe(true)
  expect(wrapper.get('[role="alert"]').text()).toContain('反馈已存在')
})
