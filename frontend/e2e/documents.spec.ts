import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

function accounts() {
  return JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.knowledge.seed_browser'],{
    input:JSON.stringify({prefix:'kb-e2e-doc-'+randomUUID().slice(0,12)}),encoding:'utf8',
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
    return {status:response.status,body:response.status===204 || !response.headers.get('content-type')?.includes('application/json')?null:await response.json()}
  },{path,method,body})
}

test('admin uploads and replaces a document; reader loses download access after disable and delete',async({page,browser})=>{
  test.setTimeout(120_000)
  const users=accounts()
  const readerContext=await browser.newContext(),reader=await readerContext.newPage()
  try {
    await login(page,users.admin.username)
    const kb=await api(page,'/knowledge-bases','POST',{name:'文档验收-'+randomUUID().slice(0,8),visibility:'public'})
    expect(kb.status).toBe(201)
    await page.goto('/knowledge/'+kb.body.id)
    await page.getByRole('button',{name:'上传文档',exact:true}).click()
    await page.getByLabel('选择文件').setInputFiles({name:'初稿.txt',mimeType:'text/plain',buffer:Buffer.from('这是一份虚构的文档。')})
    const initialUpload=page.waitForResponse(response=>response.url().endsWith('/knowledge-bases/'+kb.body.id+'/documents') && response.request().method()==='POST')
    await page.getByRole('region',{name:'上传文档'}).getByRole('button',{name:'上传文档'}).click()
    expect((await initialUpload).status()).toBe(202)
    await expect(page.getByText('上传完成，已提交解析任务。')).toBeVisible()
    const row=page.getByRole('article').filter({hasText:'初稿.txt'})
    await expect(row).toBeVisible()
    const documents=await api(page,'/knowledge-bases/'+kb.body.id+'/documents')
    expect(documents.status).toBe(200)
    const documentId=documents.body.items[0].id as string
    let parsed=false
    for(let attempt=0;attempt<20;attempt++) {
      const detail=await api(page,'/documents/'+documentId)
      expect(detail.status).toBe(200)
      if(detail.body.status==='parsed') {
        expect(detail.body.active_revision_id).toBeNull()
        expect(detail.body.candidate_revision).not.toBeNull()
        expect(detail.body.latest_job.kind).toBe('index')
        expect(detail.body.latest_job.state).toBe('queued')
        parsed=true
        break
      }
      expect(detail.body.status).not.toBe('failed')
      execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','app.modules.ingestion.worker','--once'],{encoding:'utf8'})
    }
    expect(parsed).toBe(true)
    await expect(row.getByText('解析完成，待建立索引',{exact:true})).toBeVisible()
    await page.screenshot({path:'../.local/documents-desktop.png',fullPage:true})
    const desktop=page.viewportSize()!
    await page.setViewportSize({width:390,height:844})
    await expect(row.getByText('解析完成，待建立索引',{exact:true})).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await page.screenshot({path:'../.local/documents-mobile.png',fullPage:true})
    await page.setViewportSize(desktop)
    const download=page.waitForEvent('download')
    await row.getByRole('button',{name:'下载原文件'}).click()
    expect((await download).suggestedFilename()).toBe('初稿.txt')

    await login(reader,users.user.username)
    await reader.goto('/knowledge/'+kb.body.id)
    await expect(reader.getByRole('article').filter({hasText:'初稿.txt'})).toBeVisible()
    await expect(reader.getByRole('button',{name:'上传新版本'})).toHaveCount(0)
    expect((await api(reader,'/documents/'+documentId+'/download')).status).toBe(200)

    await row.getByRole('button',{name:'上传新版本'}).click()
    await page.getByLabel('选择文件').setInputFiles({name:'修订稿.md',mimeType:'text/markdown',buffer:Buffer.from('# 虚构修订\n正文。')})
    const replacement=page.waitForResponse(response=>response.url().endsWith('/documents/'+documentId+'/revisions') && response.request().method()==='POST')
    await page.getByRole('region',{name:'上传新版本'}).getByRole('button',{name:'上传新版本'}).click()
    expect((await replacement).status()).toBe(202)
    await expect(page.getByRole('article').filter({hasText:'修订稿.md'})).toBeVisible()
    await page.getByRole('article').filter({hasText:'修订稿.md'}).getByRole('button',{name:'停用文档'}).click()
    await expect(page.getByRole('article').filter({hasText:'修订稿.md'}).getByText('已停用',{exact:true})).toBeVisible()
    expect((await api(reader,'/documents/'+documentId+'/download')).status).toBe(404)
    await reader.getByRole('button',{name:'刷新文档'}).click()
    await expect(reader.getByText('暂无文档。')).toBeVisible()
    await page.getByRole('article').filter({hasText:'修订稿.md'}).getByRole('button',{name:'启用文档'}).click()
    await expect(page.getByRole('article').filter({hasText:'修订稿.md'})).toBeVisible()
    page.once('dialog',dialog=>dialog.accept())
    await page.getByRole('article').filter({hasText:'修订稿.md'}).getByRole('button',{name:'删除文档'}).click()
    await expect(page.getByText('文档已删除。')).toBeVisible()
    expect((await api(reader,'/documents/'+documentId+'/download')).status).toBe(404)
  } finally {await readerContext.close()}
})
