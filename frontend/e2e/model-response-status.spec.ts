import { expect, test } from '@playwright/test'

test('shows model progress, preserves a failed question and reloads its safe history reason',async({page})=>{
  const user={id:'owner',username:'reader',display_name:'读者',role:'user',is_active:true,created_at:'2026-11-26T00:00:00Z'}
  const conversation={id:'c',user_id:'owner',title:'借阅咨询',kb_ids:['kb'],mode:'bot',assigned_agent_id:null,created_at:'2026-11-26T00:00:00Z',updated_at:'2026-11-26T00:00:00Z'}
  const question={id:'u',conversation_id:'c',role:'user',author_id:'owner',content:'怎样确认图书续借成功？',status:'complete',citations:[],client_message_id:'client',in_reply_to_id:null,answer_status:null,evidence_level:null,intent:null,latency_ms:null,error_code:null,created_at:'2026-11-26T00:00:00Z',evidence_hidden:false}
  const failedReply={...question,id:'a',role:'assistant',author_id:null,content:'',status:'failed',client_message_id:null,in_reply_to_id:'u',error_code:'MODEL_OFFLINE'}
  let failed=false
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname
    const pagination=(items:unknown[])=>({items,total:items.length,page:1,page_size:50})
    const responses:Record<string,unknown>={
      '/api/v1/auth/me':user,
      '/api/v1/auth/csrf':{csrf_token:'test'},
      '/api/v1/conversations':pagination([conversation]),
      '/api/v1/conversations/c':conversation,
      '/api/v1/conversations/c/messages':pagination(failed?[question,failedReply]:[]),
      '/api/v1/model/status':{state:failed?'offline':'ready',provider:'queued',model_id:'local-model',available:!failed},
    }
    if(!(path in responses)) throw new Error('Unexpected fixture route '+path)
    await route.fulfill({json:responses[path]})
  })
  await page.addInitScript(()=>{
    const originalFetch=window.fetch.bind(window)
    const encoder=new TextEncoder()
    const fixture=window as unknown as {finishModelFailure?:()=>void;modelRequests:number}
    fixture.modelRequests=0
    window.fetch=async(input,init)=>{
      const path=typeof input==='string'?input:input instanceof Request?input.url:input.href
      const url=new URL(path,window.location.href)
      if(!url.pathname.endsWith('/messages/stream')) return originalFetch(input,init)
      if(url.searchParams.get('progress')!=='true') throw new Error('Progress capability must be requested explicitly')
      fixture.modelRequests++
      return new Response(new ReadableStream({start(controller){
        controller.enqueue(encoder.encode('event: meta\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\nevent: progress\ndata: {"stage":"queued"}\n\n'))
        fixture.finishModelFailure=()=>{
          controller.enqueue(encoder.encode('event: error\ndata: {"code":"MODEL_OFFLINE","message":"本地模型未连接"}\n\n'))
          controller.close()
        }
      }}),{headers:{'Content-Type':'text/event-stream'}})
    }
  })
  await page.goto('/chat/c')
  await page.getByRole('textbox',{name:'消息内容'}).fill(question.content)
  await page.getByRole('button',{name:'发送问题',exact:true}).click()
  await expect(page.getByLabel('消息历史').getByText('正在排队等待模型…')).toBeVisible()
  failed=true
  await page.evaluate(()=>{(window as unknown as {finishModelFailure:()=>void}).finishModelFailure()})
  await expect(page.getByLabel('消息历史')).toContainText('本地模型未连接')
  await expect(page.getByRole('textbox',{name:'消息内容'})).toHaveValue(question.content)
  await expect(page.getByRole('button',{name:'申请人工客服',exact:true})).toBeEnabled()
  expect(await page.evaluate(()=>(window as unknown as {modelRequests:number}).modelRequests)).toBe(1)
  await page.reload()
  await expect(page.getByLabel('消息历史')).toContainText('本地模型未连接')
  await expect(page.getByRole('button',{name:'重试这条提问',exact:true})).toBeVisible()
  expect(await page.evaluate(()=>(window as unknown as {modelRequests:number}).modelRequests)).toBe(0)
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})
