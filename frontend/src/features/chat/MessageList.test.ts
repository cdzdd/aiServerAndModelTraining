import { afterEach, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import MessageList from './MessageList.vue'
import type { MessageView } from './api'

enableAutoUnmount(afterEach)
const base:MessageView={id:'m',conversation_id:'c',role:'assistant',author_id:null,content:'<img src=x onerror=alert(1)>',status:'complete',citations:[],client_message_id:null,in_reply_to_id:'u',answer_status:'answered',evidence_level:'sufficient',intent:'knowledge',latency_ms:5,error_code:null,created_at:'2026-09-26T00:00:00Z',evidence_hidden:false}

it('renders message and citation text safely and opens its source list',()=>{
  const citation={index:1,chunk_id:'chunk',kb_id:'kb',source_type:'document' as const,source_id:'doc',title:'<script>x</script>',quote:'原文',revision_id:'rev',faq_version:null,page_number:2,paragraph_number:null,line_number:null}
  const wrapper=mount(MessageList,{props:{messages:[{...base,citations:[citation]}]}})
  expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('script').exists()).toBe(false)
  wrapper.get('button[aria-label="查看引用"]').trigger('click')
  expect(wrapper.emitted('citations')?.[0]?.[0]).toEqual([citation])
})

it('does not offer revoked citations or present cancelled output as complete',()=>{
  const wrapper=mount(MessageList,{props:{messages:[{...base,id:'hidden',content:'该回答所依据的资料当前不可访问',evidence_hidden:true,citations:[]},{...base,id:'cancelled',content:'部分内容',status:'cancelled'}]}})
  expect(wrapper.find('button[aria-label="查看引用"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('已取消')
  expect(wrapper.text()).toContain('该回答所依据的资料当前不可访问')
})

it('shows feedback only for owner-visible completed assistant replies',()=>{
  const wrapper=mount(MessageList,{props:{canFeedback:true,messages:[base,{...base,id:'cancelled',status:'cancelled'},{...base,id:'agent',role:'agent'}]}})
  expect(wrapper.findAll('.feedback-control')).toHaveLength(1)
  expect(wrapper.find('.feedback-control').attributes('aria-label')).toContain('m')
})

it('defaults feedback controls off for the agent workbench',()=>{
  const wrapper=mount(MessageList,{props:{messages:[base]}})
  expect(wrapper.find('.feedback-control').exists()).toBe(false)
})

it('labels the customer and support agent distinctly in shared history',()=>{
  const wrapper=mount(MessageList,{props:{messages:[{...base,id:'customer',role:'user',content:'客户问题'},{...base,id:'agent',role:'agent',content:'客服回复'}]}})
  expect(wrapper.findAll('.message-heading strong').map(value=>value.text())).toEqual(['用户','客服'])
})

it('shows safe persisted failure reasons, falls back for old rows and never displays unknown codes',()=>{
  const wrapper=mount(MessageList,{props:{messages:[
    {...base,id:'offline',content:'',status:'failed',error_code:'MODEL_OFFLINE'},
    {...base,id:'timeout',content:'',status:'failed',error_code:'RAG_TIMEOUT'},
    {...base,id:'legacy',content:'',status:'failed',error_code:null},
    {...base,id:'unknown',content:'',status:'failed',error_code:'PRIVATE_TRACE_secret'},
  ]}})
  expect(wrapper.text()).toContain('本地模型未连接')
  expect(wrapper.text()).toContain('回答处理超时')
  expect(wrapper.text()).toContain('回答未能完成')
  expect(wrapper.text()).not.toContain('PRIVATE_TRACE_secret')
})

it('places the current stage and a manual retry at their own message',async()=>{
  const wrapper=mount(MessageList,{props:{
    messages:[{...base,id:'waiting',content:'',status:'generating'},{...base,id:'failed',content:'',status:'failed'}],
    progress:{messageId:'waiting',stage:'queued'},retryableMessageIds:['failed'],
  }})
  expect(wrapper.findAll('.message')[0]!.text()).toContain('正在排队等待模型')
  expect(wrapper.findAll('.message')[1]!.text()).not.toContain('正在排队等待模型')
  await wrapper.get('button[aria-label="重试这条提问"]').trigger('click')
  expect(wrapper.emitted('retry')).toEqual([['failed']])
})
