import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

function accounts() {
  return JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.knowledge.seed_browser'],{
    input:JSON.stringify({prefix:'kb-e2e-chat-'+randomUUID().slice(0,12)}),encoding:'utf8',
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

test('real login, cited stream, history, stop/retry, revocation and ownership',async({page,browser})=>{
  test.setTimeout(150_000)
  const users=accounts()
  const adminContext=await browser.newContext(),admin=await adminContext.newPage()
  const strangerContext=await browser.newContext(),stranger=await strangerContext.newPage()
  try {
    await login(admin,users.admin.username)
    const kb=await api(admin,'/knowledge-bases','POST',{name:'chat-e2e-'+randomUUID().slice(0,8),visibility:'public'})
    expect(kb.status).toBe(201)
    const uploaded=await admin.evaluate(async(kbId:string)=>{
      const token=await fetch('/api/v1/auth/csrf').then(response=>response.json())
      const form=new FormData()
      form.append('file',new File(['办理业务需要身份证。'],'验收资料.txt',{type:'text/plain'}))
      const response=await fetch('/api/v1/knowledge-bases/'+kbId+'/documents',{method:'POST',headers:{'X-CSRF-Token':token.csrf_token},body:form})
      return {status:response.status,body:await response.json()}
    },kb.body.id as string)
    expect(uploaded.status).toBe(202)
    const fixture=JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.chat.e2e_app'],{
      input:JSON.stringify({document_id:uploaded.body.document_id}),encoding:'utf8',
    })) as {chunk_id:string;document_id:string}
    expect(fixture.document_id).toBe(uploaded.body.document_id)

    await login(page,users.user.username)
    await page.getByRole('link',{name:'问答会话'}).click()
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel(kb.body.name as string).check()
    await page.getByRole('button',{name:'创建会话'}).click()
    await expect(page.getByRole('heading',{name:'新会话'})).toBeVisible()
    const conversationId=page.url().split('/').at(-1)!
    expect(conversationId).toMatch(/^[0-9a-f-]{36}$/)
    await page.getByRole('textbox',{name:'消息内容'}).fill('办理业务需要什么？')
    await page.getByRole('button',{name:'发送问题'}).click()
    await expect(page.getByText('资料原文：办理业务需要身份证。 [1]')).toBeVisible()
    await expect(page.getByRole('button',{name:'查看引用'})).toBeVisible()
    await page.getByRole('button',{name:'查看引用'}).click()
    await expect(page.getByRole('complementary',{name:'回答引用'}).getByText('办理业务需要身份证。')).toBeVisible()
    const download=page.waitForEvent('download')
    await page.getByRole('button',{name:'下载来源文件'}).click()
    expect((await download).suggestedFilename()).toBe('验收资料.txt')
    await page.screenshot({path:'../.local/chat-desktop.png',fullPage:true})
    const desktop=page.viewportSize()!
    await page.setViewportSize({width:390,height:844})
    await expect(page.getByRole('button',{name:'关闭引用'})).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await page.screenshot({path:'../.local/chat-mobile.png',fullPage:true})
    await page.setViewportSize(desktop)

    await page.reload()
    await expect(page.getByText('资料原文：办理业务需要身份证。 [1]')).toBeVisible()
    await page.getByRole('textbox',{name:'消息内容'}).fill('再确认办理材料')
    await page.getByRole('button',{name:'发送问题'}).click()
    await expect(page.getByText('结合前文，资料原文：办理业务需要身份证。 [1]')).toBeVisible()

    const streamKeys:string[]=[]
    page.on('request',request=>{
      if(request.url().endsWith('/messages/stream') && request.postDataJSON()?.client_message_id) streamKeys.push(request.postDataJSON().client_message_id as string)
    })
    await page.getByRole('textbox',{name:'消息内容'}).fill('慢速问题')
    await page.getByRole('button',{name:'发送问题'}).click()
    await expect(page.getByRole('button',{name:'停止生成'})).toBeVisible()
    await page.getByRole('button',{name:'停止生成'}).click()
    await expect(page.getByText('已停止生成；可手动重试。')).toBeVisible()
    await expect(page.getByText('已取消')).toBeVisible({timeout:15_000})
    await page.getByRole('button',{name:'重试提问'}).click()
    await expect.poll(()=>streamKeys.length).toBe(2)
    expect(streamKeys[0]).not.toBe(streamKeys[1])
    await page.getByRole('button',{name:'停止生成'}).click()

    const other=accounts()
    await login(stranger,other.user.username)
    expect((await api(stranger,'/conversations/'+conversationId)).status).toBe(404)

    const patched=await api(admin,'/documents/'+fixture.document_id,'PATCH',{is_active:false})
    expect(patched.status).toBe(200)
    await page.getByRole('button',{name:'刷新历史'}).click()
    await expect(page.getByText('该回答所依据的资料当前不可访问').first()).toBeVisible()
    await expect(page.getByRole('button',{name:'查看引用'})).toHaveCount(0)
  } finally {await adminContext.close();await strangerContext.close()}
})
