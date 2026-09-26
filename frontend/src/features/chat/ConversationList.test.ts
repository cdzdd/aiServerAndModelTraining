import { afterEach, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ConversationList from './ConversationList.vue'
import type { ConversationView } from './api'

enableAutoUnmount(afterEach)
const conversation:ConversationView={id:'c',user_id:'owner',title:'历史提问',kb_ids:['kb'],mode:'human',assigned_agent_id:'agent',created_at:'2026-09-26T00:00:00Z',updated_at:'2026-09-26T00:00:00Z'}
it('lets an assigned agent open a human conversation without deleting the owner history',async()=>{
  const wrapper=mount(ConversationList,{props:{items:[conversation],selectedId:null,userId:'agent',role:'agent',page:1,total:1,loading:false}})
  expect(wrapper.text()).toContain('人工处理中')
  expect(wrapper.find('button[aria-label="删除会话"]').exists()).toBe(false)
  await wrapper.get('button[aria-label="打开会话"]').trigger('click')
  expect(wrapper.emitted('select')?.[0]?.[0]).toBe('c')
})
it('lets the owner request a soft delete',async()=>{
  const wrapper=mount(ConversationList,{props:{items:[conversation],selectedId:'c',userId:'owner',role:'user',page:1,total:1,loading:false}})
  await wrapper.get('button[aria-label="删除会话"]').trigger('click')
  expect(wrapper.emitted('delete')?.[0]?.[0]).toBe('c')
})
