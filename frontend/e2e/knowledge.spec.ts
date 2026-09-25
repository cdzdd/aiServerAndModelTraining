import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

function accounts() {
  return JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.knowledge.seed_browser'],{
    input:JSON.stringify({prefix:'kb-e2e-'+randomUUID().slice(0,12)}),encoding:'utf8',
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
    const token=method==='GET'?null:await fetch('/api/v1/auth/csrf').then(r=>r.json())
    const response=await fetch('/api/v1'+path,{method,headers:token?{'Content-Type':'application/json','X-CSRF-Token':token.csrf_token}:{},body:body===undefined?undefined:JSON.stringify(body)})
    return {status:response.status,body:response.status===204?null:await response.json()}
  },{path,method,body})
}

async function findKnowledge(page:Page,name:string) {
  await expect(page.getByRole('button',{name:'刷新列表'})).toBeEnabled()
  const link=page.getByRole('link',{name,exact:true})
  while(!(await link.count())) {
    const next=page.getByRole('button',{name:'下一页',exact:true})
    await expect(next).toBeEnabled()
    await next.click()
    await expect(page.getByRole('button',{name:'刷新列表'})).toBeEnabled()
  }
  await expect(link).toBeVisible()
}
test('administrator manages FAQ and membership; user and agent sessions obey revocation immediately',async({page,browser})=>{
  const users=accounts()
  const readerContext=await browser.newContext(), agentContext=await browser.newContext()
  const reader=await readerContext.newPage(),agent=await agentContext.newPage()
  try {
    await login(page,users.admin.username)
    await page.getByRole('link',{name:'知识库',exact:true}).click()
    await page.getByRole('button',{name:'新建知识库'}).click()
    const name='虚构校园-'+randomUUID().slice(0,8)
    await page.getByLabel('知识库名称',{exact:true}).fill(name)
    await page.getByLabel('知识库说明').fill('验收合成资料')
    await page.getByRole('button',{name:'创建知识库',exact:true}).click()
    await findKnowledge(page,name)
    await page.getByRole('link',{name,exact:true}).click()
    await expect(page).toHaveURL(/\/knowledge\/[0-9a-f-]{36}$/)
    const kbId=page.url().split('/').at(-1)!
    await page.getByRole('button',{name:'新增 FAQ'}).click()
    await page.getByLabel('问题',{exact:true}).fill('虚构图书馆开放时间？')
    await page.getByLabel('答案',{exact:true}).fill('本虚构样例设定为九点开放。')
    await page.getByRole('button',{name:'保存 FAQ'}).click()
    await expect(page.getByText('虚构图书馆开放时间？',{exact:true})).toBeVisible()
    await expect(page.getByText('待索引',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'管理成员'}).click()
    await expect(page.getByRole('button',{name:'保存成员'})).toBeEnabled()
    // Candidate accounts are paginated; locate by paging without dropping selected members.
    const pending=new Set([users.user.username,users.agent.username])
    while(pending.size) {
      for(const username of pending) {
        const checkbox=page.getByLabel(username,{exact:true})
        if(await checkbox.count()) {await checkbox.check();pending.delete(username)}
      }
      if(pending.size) {
        await expect(page.getByRole('button',{name:'下一页账号'})).toBeEnabled()
        await page.getByRole('button',{name:'下一页账号'}).click()
        await expect(page.getByRole('button',{name:'保存成员'})).toBeEnabled()
      }
    }
    await page.getByRole('button',{name:'保存成员'}).click()
    await expect(page.getByText('成员已更新。')).toBeVisible()
    await login(reader,users.user.username)
    await login(agent,users.agent.username)
    for(const p of [reader,agent]) {
      await p.goto('/knowledge/'+kbId)
      await expect(p.getByText('本虚构样例设定为九点开放。',{exact:true})).toBeVisible()
      await expect(p.getByRole('button',{name:'新增 FAQ'})).toHaveCount(0)
      expect((await api(p,'/knowledge-bases/'+kbId+'/faqs','POST',{question:'越权',answer:'越权'})).status).toBe(403)
    }
    const denied=await api(page,'/knowledge-bases','POST',{name:'另一个虚构限制库',visibility:'restricted'})
    expect((await api(reader,'/knowledge-bases/'+denied.body.id)).status).toBe(404)
    await page.getByRole('button',{name:'编辑 FAQ'}).click()
    await page.getByLabel('答案',{exact:true}).fill('修改后的虚构答案。')
    await page.getByRole('button',{name:'保存 FAQ'}).click()
    await expect(page.getByText('修改后的虚构答案。',{exact:true})).toBeVisible()
    await page.screenshot({path:'../.local/knowledge-detail.png',fullPage:true})
    const current=await api(page,'/knowledge-bases/'+kbId)
    expect((await api(page,'/knowledge-bases/'+kbId+'/members','PUT',{user_ids:[],expected_version:current.body.version})).status).toBe(200)
    for(const p of [reader,agent]) {
      expect((await api(p,'/knowledge-bases/'+kbId+'/faqs')).status).toBe(404)
      await p.reload()
      await expect(p.getByRole('alert')).toContainText('不存在或不可见')
      await expect(p.getByText('修改后的虚构答案。',{exact:true})).toHaveCount(0)
    }
    await page.getByRole('button',{name:'停用 FAQ',exact:true}).click()
    await expect(page.getByText('已停用',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'启用 FAQ',exact:true}).click()
    await expect(page.getByText('待索引',{exact:true})).toBeVisible()
  } finally {await readerContext.close();await agentContext.close()}
})

test('disabled library can be restored; FAQ text is escaped on a narrow screen',async({page})=>{
  const users=accounts()
  await login(page,users.admin.username)
  const name='虚构公开-'+randomUUID().slice(0,8)
  const created=await api(page,'/knowledge-bases','POST',{name,visibility:'public'})
  expect(created.status).toBe(201)
  const kbId=created.body.id
  expect((await api(page,'/knowledge-bases/'+kbId+'/faqs','POST',{question:'<img src=x onerror=alert(1)>',answer:'<script>throw new Error("xss")</script>'})).status).toBe(201)
  await page.setViewportSize({width:390,height:844})
  await page.goto('/knowledge/'+kbId)
  await expect(page.getByText('<img src=x onerror=alert(1)>',{exact:true})).toBeVisible()
  await expect(page.locator('main img')).toHaveCount(0)
  await page.goto('/knowledge')
  await findKnowledge(page,name)
  const row=page.getByRole('row').filter({has:page.getByRole('link',{name,exact:true})})
  await row.getByRole('button',{name:'停用知识库'}).click()
  await expect(page.getByRole('row').filter({hasText:name}).getByText('已停用')).toBeVisible()
  expect((await api(page,'/knowledge-bases/'+kbId)).status).toBe(404)
  await page.getByRole('row').filter({hasText:name}).getByRole('button',{name:'启用知识库'}).click()
  await expect(page.getByRole('link',{name,exact:true})).toBeVisible()
  expect((await api(page,'/knowledge-bases/'+kbId)).status).toBe(200)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:'../.local/knowledge-mobile.png',fullPage:true})
})
