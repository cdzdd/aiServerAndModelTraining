import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { session } from '../auth/session'
import FaqEditor from './FaqEditor.vue'

const faq = {id:'11111111-1111-4111-8111-111111111111',kb_id:'22222222-2222-4222-8222-222222222222',question:'虚构问题',answer:'虚构答案',is_active:true,version:3,indexed_version:2,updated_at:'2026-09-24T12:00:00Z'}
enableAutoUnmount(afterEach)
afterEach(()=>{vi.unstubAllGlobals();session.api.setCsrfToken(null)})

it('rejects blank content without sending a write',async()=>{
  let writes=0
  vi.stubGlobal('fetch',async()=>{writes++;return new Response('{}')})
  const wrapper=mount(FaqEditor,{props:{kbId:faq.kb_id}})
  await wrapper.get('[name="question"]').setValue('   ')
  await wrapper.get('[name="answer"]').setValue('答案')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('问题和答案不能为空')
  expect(writes).toBe(0)
})

it('saves versioned changes with CSRF and displays pending indexing',async()=>{
  const writes: {url:string;options:RequestInit}[]=[]
  vi.stubGlobal('fetch',async(url:string,options:RequestInit)=>{
    if(url.endsWith('/csrf')) return new Response(JSON.stringify({csrf_token:'test-csrf'}))
    writes.push({url,options})
    return new Response(JSON.stringify({...faq,answer:'修改答案',version:4}))
  })
  const wrapper=mount(FaqEditor,{props:{kbId:faq.kb_id,faq}})
  expect(wrapper.text()).toContain('待索引')
  await wrapper.get('[name="answer"]').setValue('修改答案')
  await wrapper.get('form').trigger('submit');await flushPromises()
  expect(writes).toHaveLength(1)
  expect(writes[0]!.url).toBe('/api/v1/faqs/'+faq.id)
  expect(writes[0]!.options.method).toBe('PATCH')
  expect(new Headers(writes[0]!.options.headers).get('X-CSRF-Token')).toBe('test-csrf')
  expect(JSON.parse(writes[0]!.options.body as string)).toEqual({question:faq.question,answer:'修改答案',is_active:true,expected_version:3})
  expect(wrapper.emitted('saved')?.[0]?.[0]).toMatchObject({version:4,indexed_version:2})
})

it('keeps the draft on a conflict and allows cancelling to reload',async()=>{
  vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/csrf')?{csrf_token:'test'}:{error:{code:'CONFLICT',message:'内容已被修改，请刷新后重试'}}),{status:url.endsWith('/csrf')?200:409}))
  const wrapper=mount(FaqEditor,{props:{kbId:faq.kb_id,faq}})
  await wrapper.get('[name="answer"]').setValue('保留草稿')
  await wrapper.get('form').trigger('submit');await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('刷新')
  expect((wrapper.get('[name="answer"]').element as HTMLTextAreaElement).value).toBe('保留草稿')
  expect(wrapper.emitted('saved')).toBeUndefined()
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
})

it('blocks duplicate saves until the response completes',async()=>{
  session.api.setCsrfToken('test')
  let resolve!: (value:Response)=>void
  let writes=0
  vi.stubGlobal('fetch',()=>{writes++;return new Promise<Response>(r=>{resolve=r})})
  const wrapper=mount(FaqEditor,{props:{kbId:faq.kb_id,faq}})
  await wrapper.get('form').trigger('submit')
  await wrapper.get('form').trigger('submit')
  expect(writes).toBe(1)
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  resolve(new Response(JSON.stringify({...faq,version:4})))
  await flushPromises()
  expect(wrapper.emitted('saved')).toHaveLength(1)
})

