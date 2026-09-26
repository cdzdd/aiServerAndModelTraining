import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

function accounts() {
  return JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.knowledge.seed_browser'],{
    input:JSON.stringify({prefix:'kb-e2e-feedback-'+randomUUID().slice(0,12)}),encoding:'utf8',
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

test('owner feedback persists, administrator resolves, owner edit reopens, and another user cannot access it',async({page,browser})=>{
  test.setTimeout(120_000)
  const users=accounts(),other=accounts()
  const ownerComment='缺少办理时间-'+randomUUID().slice(0,8)
  const adminContext=await browser.newContext(),admin=await adminContext.newPage()
  const strangerContext=await browser.newContext(),stranger=await strangerContext.newPage()
  try {
    await login(admin,users.admin.username)
    const kb=await api(admin,'/knowledge-bases','POST',{name:'chat-e2e-'+randomUUID().slice(0,8),visibility:'public'})
    expect(kb.status).toBe(201)
    const uploaded=await admin.evaluate(async(kbId:string)=>{
      const token=await fetch('/api/v1/auth/csrf').then(response=>response.json())
      const form=new FormData()
      form.append('file',new File(['办理业务需要身份证。'],'反馈验收.txt',{type:'text/plain'}))
      const response=await fetch('/api/v1/knowledge-bases/'+kbId+'/documents',{method:'POST',headers:{'X-CSRF-Token':token.csrf_token},body:form})
      return {status:response.status,body:await response.json()}
    },kb.body.id as string)
    expect(uploaded.status).toBe(202)
    execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.chat.e2e_app'],{
      input:JSON.stringify({document_id:uploaded.body.document_id}),encoding:'utf8',
    })
    const originalDocument=await api(admin,'/documents/'+uploaded.body.document_id)
    expect(originalDocument.status).toBe(200)

    await login(page,users.user.username)
    await page.getByRole('link',{name:'问答会话'}).click()
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel(kb.body.name as string).check()
    await page.getByRole('button',{name:'创建会话'}).click()
    await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/)
    const conversationId=page.url().split('/').at(-1)!
    await page.getByRole('textbox',{name:'消息内容'}).fill('办理业务需要什么？')
    await page.getByRole('button',{name:'发送问题'}).click()
    const answer='资料原文：办理业务需要身份证。 [1]'
    await expect(page.getByText(answer)).toBeVisible()
    const control=page.locator('.feedback-control')
    await expect(control).toHaveCount(1)
    await control.getByLabel('没帮助').check()
    await control.locator('textarea').fill(ownerComment)
    await control.getByRole('button',{name:'提交反馈'}).click()
    await expect(control.getByText('待处理')).toBeVisible()
    const messages=await api(page,'/conversations/'+conversationId+'/messages')
    expect(messages.status).toBe(200)
    const assistant=messages.body.items.find((item:{role:string})=>item.role==='assistant')
    const own=await api(page,'/messages/'+assistant.id+'/feedback')
    expect(own.status).toBe(200)
    expect(own.body.comment).toBe(ownerComment)
    const feedbackId=own.body.id as string

    await admin.getByRole('link',{name:'回答反馈'}).click()
    await expect(admin.getByText(ownerComment)).toBeVisible()
    await admin.locator('tr').filter({hasText:ownerComment}).getByRole('link',{name:'查看详情'}).click()
    await expect(admin.getByText(answer)).toBeVisible()
    await admin.getByRole('textbox',{name:'处理说明'}).fill('已核对办理材料')
    await admin.getByRole('button',{name:'标记已处理'}).click()
    await expect(admin.getByText('反馈已处理。')).toBeVisible()
    await admin.screenshot({path:'../.local/feedback-desktop.png',fullPage:true})
    await admin.setViewportSize({width:390,height:844})
    expect(await admin.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await admin.screenshot({path:'../.local/feedback-mobile.png',fullPage:true})

    await page.reload()
    await expect(control.getByText('已处理')).toBeVisible()
    await expect(control.getByText('已核对办理材料')).toBeVisible()
    await control.locator('textarea').fill('仍缺少办理地点')
    await control.getByRole('button',{name:'保存反馈修改'}).click()
    await expect(control.getByText('待处理')).toBeVisible()
    await expect(control.getByText('已核对办理材料')).toHaveCount(0)
    const reopened=await api(admin,'/admin/feedback/'+feedbackId)
    expect(reopened.body.feedback.status).toBe('open')
    expect(reopened.body.feedback.resolution).toBe('')
    await page.getByRole('textbox',{name:'消息内容'}).fill('再次询问办理材料')
    await page.getByRole('button',{name:'发送问题'}).click()
    await expect(page.getByText('结合前文，'+answer)).toBeVisible()
    expect(await page.getByText('仍缺少办理地点').count()).toBe(0)

    await login(stranger,other.user.username)
    expect((await api(stranger,'/messages/'+assistant.id+'/feedback')).status).toBe(404)
    expect((await api(stranger,'/feedback/'+feedbackId,'PATCH',{comment:'越权'})).status).toBe(404)
    expect((await api(stranger,'/admin/feedback/'+feedbackId)).status).toBe(403)
    const finalDocument=await api(admin,'/documents/'+uploaded.body.document_id)
    expect(finalDocument.status).toBe(200)
    expect(finalDocument.body.active_revision_id).toBe(originalDocument.body.active_revision_id)
    expect((await api(page,'/conversations/'+conversationId+'/messages')).body.items.find((item:{id:string})=>item.id===assistant.id).content).toBe(answer)
  } finally {await adminContext.close();await strangerContext.close()}
})
