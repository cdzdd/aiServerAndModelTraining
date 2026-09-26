import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

interface Account {id:string;username:string;password:string}
const users=JSON.parse(process.env.ANALYTICS_E2E_USERS!) as Record<'admin'|'user'|'agent',Account>
const schema=process.env.ANALYTICS_E2E_SCHEMA!
async function login(page:Page,user:Account) {
  await page.goto('/login')
  await page.getByLabel('用户名',{exact:true}).fill(user.username)
  await page.getByLabel('密码',{exact:true}).fill(user.password)
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.getByRole('navigation',{name:'主导航'})).toBeVisible()
}
async function api(page:Page,path:string) {
  return page.evaluate(async path=>{
    const response=await fetch('/api/v1'+path)
    return {status:response.status,body:await response.json()}
  },path)
}

test('fixed PostgreSQL statistics, Shanghai boundaries, safe audit and administrator-only access',async({page,browser})=>{
  test.setTimeout(120_000)
  const fixture=JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.analytics.seed_browser'],{
    input:JSON.stringify({action:'populate',schema}),encoding:'utf8',
  })) as {range:{from:string;to:string};expected:Record<string,number|string>}
  const userContext=await browser.newContext(),userPage=await userContext.newPage()
  const agentContext=await browser.newContext(),agentPage=await agentContext.newPage()
  try {
    await login(page,users.admin)
    const query=new URLSearchParams(fixture.range)
    const result=await api(page,'/admin/stats?'+query)
    expect(result.status).toBe(200)
    const stats=result.body
    expect(stats.logins.successful).toBe(fixture.expected.successful_logins)
    expect(stats.generations.accepted).toBe(fixture.expected.accepted)
    expect(stats.generations.distinct_users).toBe(fixture.expected.distinct_users)
    expect(stats.generations.complete).toBe(fixture.expected.complete)
    expect(stats.generations.failed).toBe(fixture.expected.failed)
    expect(stats.generations.cancelled).toBe(fixture.expected.cancelled)
    expect(stats.generations.generating).toBe(fixture.expected.generating)
    expect(stats.generations.no_answer_ratio.value).toBe(fixture.expected.no_answer_ratio)
    expect(stats.feedback.satisfaction.value).toBe(fixture.expected.satisfaction)
    expect(stats.latency.average_ms).toBe(fixture.expected.average_ms)
    expect(stats.tokens.prompt_tokens.known_sum).toBe(fixture.expected.prompt_known_sum)
    expect(stats.tokens.prompt_tokens.missing_count).toBe(fixture.expected.prompt_missing_count)
    expect(stats.tokens.cost.amount).toBeNull()
    expect(stats.popular_questions[0].count).toBe(fixture.expected.popular_first_count)
    expect(stats.daily.map((day:{accepted:number})=>day.accepted)).toEqual([7,7])
    const sentinel=String(fixture.expected.raw_audit_sentinel)
    expect(sentinel).toBe('analytics-raw-secret-sentinel')
    const audits=await api(page,'/admin/audit-events?'+query)
    expect(audits.status).toBe(200)
    const legacy=audits.body.items.filter((item:{action:string})=>item.action==='auth.login')
    expect(legacy).toHaveLength(3)
    expect(JSON.stringify(audits.body)).not.toContain(sentinel)
    for(const item of legacy) {
      const detail=await api(page,'/admin/audit-events/'+item.id)
      expect(detail.status).toBe(200)
      expect(JSON.stringify(detail.body)).not.toContain(sentinel)
      expect(detail.body.metadata).toEqual({})
    }

    await page.getByRole('link',{name:'管理统计'}).click()
    await page.getByLabel('开始日期').fill('2024-01-02')
    await page.getByLabel('结束日期').fill('2024-01-03')
    await page.getByRole('button',{name:'应用日期'}).click()
    await expect(page.locator('.metric').filter({hasText:'已受理问答请求'})).toContainText('14')
    await expect(page.locator('.metric').filter({hasText:'独立提问用户'})).toContainText('3')
    await expect(page.locator('.metric').filter({hasText:'无答案比例'})).toContainText('20%')
    await expect(page.getByText('费用未知')).toBeVisible()
    await expect(page.getByText('已知部分').first()).toBeVisible()
    await expect(page.getByText('虚构：图书馆开放吗？')).toBeVisible()
    await expect(page.getByRole('img',{name:/每日趋势/})).toBeVisible()
    await expect(page.getByText('当前状态（不受所选日期限制）')).toBeVisible()
    await page.screenshot({path:'../.local/admin-stats-desktop.png',fullPage:true})
    await page.setViewportSize({width:390,height:844})
    await page.screenshot({path:'../.local/admin-stats-mobile.png',fullPage:true})
    await page.locator('.charts .panel').first().screenshot({path:'../.local/admin-trend-mobile.png'})
    const layout=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:window.innerWidth,overflow:Array.from(document.querySelectorAll('*')).filter(element=>element.getBoundingClientRect().right>window.innerWidth+1).slice(0,8).map(element=>`${element.tagName}.${element.className}`)}))
    expect(layout.scroll,layout.overflow.join(', ')).toBeLessThanOrEqual(layout.width)

    await page.getByLabel('结束日期').fill('2024-01-02')
    await page.getByRole('button',{name:'应用日期'}).click()
    await expect(page.locator('.metric').filter({hasText:'已受理问答请求'})).toContainText('7')
    const oneDay=await api(page,'/admin/stats?from=2024-01-02T00%3A00%3A00%2B08%3A00&to=2024-01-03T00%3A00%3A00%2B08%3A00')
    expect(oneDay.body.generations.accepted).toBe(7)

    await page.getByRole('link',{name:'审计记录'}).click()
    await page.getByLabel('审计开始日期').fill('2024-01-02')
    await page.getByLabel('审计结束日期').fill('2024-01-03')
    await page.getByRole('button',{name:'查询审计'}).click()
    await expect(page.getByText('auth.login').first()).toBeVisible()
    expect(await page.getByText(users.admin.password).count()).toBe(0)
    await page.getByRole('button',{name:'查看审计详情'}).first().click()
    await expect(page.getByRole('region',{name:'审计详情'})).toBeVisible()
    expect(await page.getByRole('region',{name:'审计详情'}).getByText(users.admin.password).count()).toBe(0)
    expect(await page.getByText(sentinel).count()).toBe(0)

    await login(userPage,users.user)
    expect((await api(userPage,'/admin/stats')).status).toBe(403)
    expect((await api(userPage,'/admin/audit-events')).status).toBe(403)
    expect(await userPage.getByRole('link',{name:'管理统计'}).count()).toBe(0)
    await userPage.goto('/admin/stats')
    await expect(userPage).toHaveURL(/\/forbidden$/)
    await login(agentPage,users.agent)
    expect((await api(agentPage,'/admin/stats')).status).toBe(403)
    expect((await api(agentPage,'/admin/audit-events')).status).toBe(403)
  } finally {await userContext.close();await agentContext.close()}
})
