import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import UserEditor from './UserEditor.vue'
const user={id:'11111111-1111-4111-8111-111111111111',username:'alice',display_name:'小林',role:'admin' as const,is_active:true,created_at:'2026-09-22T00:00:00Z'}
enableAutoUnmount(afterEach)
it('sends snake_case user changes and publishes the returned user',async()=>{
  const calls:{url:string;options:RequestInit}[]=[]
  vi.stubGlobal('fetch',async(url:string,options:RequestInit)=>{
    calls.push({url,options})
    return new Response(JSON.stringify(url.endsWith('/csrf')?{csrf_token:'edit-token'}:{...user,role:'agent',is_active:false,display_name:'新名称'}))
  })
  const page=mount(UserEditor,{props:{user}})
  await page.get('input[name="display_name"]').setValue('新名称')
  await page.get('select').setValue('agent')
  await page.get('input[type="checkbox"]').setValue(false)
  await page.get('form').trigger('submit')
  await flushPromises()
  const update=calls.find(call=>call.options.method==='PATCH')!
  expect(update.url).toBe('/api/v1/admin/users/11111111-1111-4111-8111-111111111111')
  expect(JSON.parse(update.options.body as string)).toEqual({display_name:'新名称',role:'agent',is_active:false})
  expect(page.emitted('saved')?.[0]?.[0]).toMatchObject({role:'agent',is_active:false,display_name:'新名称'})
})
it('keeps editing available and explains a last administrator rejection',async()=>{
  vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/csrf')?{csrf_token:'edit-token'}:{error:{code:'CONFLICT',message:'不能停用或降级最后一个有效管理员',request_id:'r'}}),{status:url.endsWith('/csrf')?200:409}))
  const page=mount(UserEditor,{props:{user}})
  await page.get('form').trigger('submit');await flushPromises()
  expect(page.get('[role="alert"]').text()).toContain('最后一个有效管理员')
  expect(page.emitted('saved')).toBeUndefined()
  expect(page.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
})

