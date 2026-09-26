import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

function accounts() {
  return JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.knowledge.seed_browser'],{
    input:JSON.stringify({prefix:'kb-e2e-hand-'+randomUUID().slice(0,12)}),encoding:'utf8',
  })) as Record<'admin'|'user'|'agent',{id:string;username:string}>
}
async function login(page:Page,username:string) {
  await page.goto('/login')
  await page.getByLabel('用户名',{exact:true}).fill(username)
  await page.getByLabel('密码',{exact:true}).fill('synthetic-browser-password')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.getByRole('navigation',{name:'主导航'})).toBeVisible()
}
async function api(page:Page,path:string,method='GET',body?:unknown) {
  return page.evaluate(async({path,method,body})=>{
    const token=method==='GET'?null:await fetch('/api/v1/auth/csrf').then(response=>response.json())
    const response=await fetch('/api/v1'+path,{method,headers:token?{'Content-Type':'application/json','X-CSRF-Token':token.csrf_token}:{},body:body===undefined?undefined:JSON.stringify(body)})
    return {status:response.status,body:response.status===204?null:await response.json()}
  },{path,method,body})
}

test('owner and agents hand off, exchange text and close with current permissions',async({page,browser})=>{
  test.setTimeout(120_000)
  const users=accounts(),other=accounts()
  const adminContext=await browser.newContext(),admin=await adminContext.newPage()
  const agentContext=await browser.newContext(),agent=await agentContext.newPage()
  const rivalContext=await browser.newContext(),rival=await rivalContext.newPage()
  try {
    await login(admin,users.admin.username)
    const kb=await api(admin,'/knowledge-bases','POST',{name:'chat-e2e-'+randomUUID().slice(0,8),visibility:'public'})
    expect(kb.status).toBe(201)
    await login(page,users.user.username)
    await page.getByRole('link',{name:'问答会话'}).click()
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel(kb.body.name as string).check()
    await page.getByRole('button',{name:'创建会话'}).click()
    await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/)
    const conversationId=page.url().split('/').at(-1)!
    await page.getByRole('button',{name:'申请人工客服'}).click()
    await expect(page.getByRole('region',{name:'当前会话'}).getByText('等待客服',{exact:true})).toBeVisible()
    await page.getByRole('textbox',{name:'消息内容'}).fill('请人工处理这件事')
    await page.getByRole('button',{name:'发送留言'}).click()
    await expect(page.getByText('请人工处理这件事')).toBeVisible()

    await login(agent,users.agent.username)
    await agent.getByRole('link',{name:'人工客服队列'}).click()
    expect(await agent.getByRole('region',{name:'待接单队列'}).textContent()).not.toContain('请人工处理这件事')
    let target:{id:string;conversation_id:string}|undefined,index=-1
    for(let queuePage=1;queuePage<=10 && !target;queuePage++) {
      const queue=await api(agent,'/handoffs?page='+queuePage)
      expect(queue.status).toBe(200)
      index=queue.body.items.findIndex((item:{conversation_id:string})=>item.conversation_id===conversationId)
      if(index>=0) target=queue.body.items[index]
      else await agent.getByRole('button',{name:'下一页'}).click()
    }
    expect(target).toBeDefined()
    const handoffId=target!.id
    const desktop=agent.viewportSize()!
    await agent.screenshot({path:'../.local/handoff-queue-desktop.png',fullPage:true})
    await agent.setViewportSize({width:390,height:844})
    expect(await agent.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await agent.screenshot({path:'../.local/handoff-queue-mobile.png',fullPage:true})
    await agent.setViewportSize(desktop)
    await login(rival,other.agent.username)
    expect((await api(rival,'/conversations/'+conversationId)).status).toBe(404)
    expect((await api(rival,'/handoffs/'+handoffId)).status).toBe(404)
    await agent.getByRole('region',{name:'待接单队列'}).getByRole('listitem').nth(index).getByRole('button',{name:'接单'}).click()
    await expect(agent.getByRole('heading',{name:'会话工作台'})).toBeVisible()
    await expect(agent.getByText('请人工处理这件事')).toBeVisible()
    await expect(agent.getByRole('article').filter({hasText:'请人工处理这件事'}).locator('.message-heading strong')).toHaveText('用户')
    expect((await api(rival,'/conversations/'+conversationId)).status).toBe(404)
    await expect(page.getByRole('region',{name:'当前会话'}).getByText('人工处理中',{exact:true})).toBeVisible({timeout:10_000})

    await agent.getByRole('textbox',{name:'回复内容'}).fill('客服已接单，请继续说明')
    await agent.getByRole('button',{name:'发送回复'}).click()
    await expect(agent.getByRole('article').filter({hasText:'客服已接单，请继续说明'}).locator('.message-heading strong')).toHaveText('客服')
    await expect(page.getByText('客服已接单，请继续说明')).toBeVisible({timeout:10_000})
    await page.getByRole('textbox',{name:'消息内容'}).fill('谢谢，问题解决了')
    await page.getByRole('button',{name:'发送留言'}).click()
    await expect(agent.getByText('谢谢，问题解决了')).toBeVisible({timeout:10_000})
    await agent.screenshot({path:'../.local/handoff-workbench-desktop.png',fullPage:true})
    await agent.setViewportSize({width:390,height:844})
    expect(await agent.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await agent.screenshot({path:'../.local/handoff-workbench-mobile.png',fullPage:true})
    await agent.setViewportSize(desktop)
    await agent.getByRole('button',{name:'关闭会话'}).click()
    await expect(agent.getByText('已关闭',{exact:true})).toBeVisible()
    await expect(page.getByText('会话已关闭，仅可阅读历史。')).toBeVisible({timeout:10_000})
    expect(await api(page,'/conversations/'+conversationId+'/messages','POST',{content:'关闭后发送',client_message_id:randomUUID()})).toMatchObject({status:409})
    await page.reload()
    await expect(page.getByText('会话已关闭，仅可阅读历史。')).toBeVisible()
  } finally {await adminContext.close();await agentContext.close();await rivalContext.close()}
})

test('requesting handoff during streaming cancels the old assistant answer',async({page,browser})=>{
  test.setTimeout(120_000)
  const users=accounts(),adminContext=await browser.newContext(),admin=await adminContext.newPage()
  try {
    await login(admin,users.admin.username)
    const kb=await api(admin,'/knowledge-bases','POST',{name:'chat-e2e-'+randomUUID().slice(0,8),visibility:'public'})
    expect(kb.status).toBe(201)
    await login(page,users.user.username)
    await page.getByRole('link',{name:'问答会话'}).click()
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel(kb.body.name as string).check()
    await page.getByRole('button',{name:'创建会话'}).click()
    await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/)
    const conversationId=page.url().split('/').at(-1)!
    await page.getByRole('textbox',{name:'消息内容'}).fill('慢速问题，需要人工')
    await page.getByRole('button',{name:'发送问题'}).click()
    await expect(page.getByRole('button',{name:'停止生成'})).toBeVisible()
    await page.getByRole('button',{name:'申请人工客服'}).click()
    await expect(page.getByRole('region',{name:'当前会话'}).getByText('等待客服',{exact:true})).toBeVisible()
    await expect.poll(async()=>{
      const result=await api(page,'/conversations/'+conversationId+'/messages')
      if(result.status!==200) throw new Error(JSON.stringify(result))
      return result.body.items.filter((item:{role:string;status:string})=>item.role==='assistant').map((item:{status:string})=>item.status)
    }).toEqual(['cancelled'])
    expect((await api(page,'/conversations/'+conversationId)).body.mode).toBe('queued')
  } finally {await adminContext.close()}
})
