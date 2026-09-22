import { expect, test, type Page } from '@playwright/test'
const fixtureUser={id:'11111111-1111-4111-8111-111111111111',username:'alice',display_name:'小林',role:'user',is_active:true,created_at:'2026-09-22T00:00:00Z'}
async function mockAuth(page:Page, role:string|null=null) {
  const state={user:role?{...fixtureUser,role}:null, users:[{...fixtureUser,role:'admin'}], listStatus:200, meOffline:false, conflict:false, patches:[] as unknown[], registrations:[] as unknown[]}
  await page.route('**/api/v1/**',async route=>{
    const request=route.request()
    const path=new URL(request.url()).pathname
    const send=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)})
    if(request.method()!=='GET') expect(request.headers()['x-csrf-token']).toBe(state.user?'signed-in-token':'pre-login-token')
    if(path==='/api/v1/auth/csrf') return send({csrf_token:state.user?'signed-in-token':'pre-login-token'})
    if(path==='/api/v1/auth/me') {
      if(state.meOffline) return route.abort('internetdisconnected')
      return state.user?send(state.user):send({error:{code:'UNAUTHENTICATED',message:'未登录',request_id:'r'}},401)
    }
    if(path==='/api/v1/auth/login') {
      const fields=request.postDataJSON()
      expect(Object.keys(fields).sort()).toEqual(['password','username'])
      state.user={...fixtureUser,role:fields.username==='admin'?'admin':fields.username==='agent'?'agent':'user'}
      return send({user:state.user,csrf_token:'signed-in-token'})
    }
    if(path==='/api/v1/auth/register') {
      state.registrations.push(request.postDataJSON())
      return send(fixtureUser,201)
    }
    if(path==='/api/v1/auth/logout') {state.user=null;return route.fulfill({status:204})}
    if(path==='/api/v1/admin/users') {
      if(state.listStatus!==200) return send({error:{code:state.listStatus===401?'UNAUTHENTICATED':'FORBIDDEN',message:'没有访问权限',request_id:'r'}},state.listStatus)
      return send({items:state.users,total:state.users.length,page:1,page_size:20})
    }
    if(path.startsWith('/api/v1/admin/users/') && request.method()==='PATCH') {
      if(state.conflict) return send({error:{code:'CONFLICT',message:'不能停用或降级最后一个有效管理员',request_id:'r'}},409)
      const patch=request.postDataJSON();state.patches.push(patch)
      state.users[0]={...state.users[0]!,...patch}
      if(state.user?.id===state.users[0].id) state.user={...state.user,...patch}
      return send(state.users[0])
    }
    throw new Error('Unhandled contract endpoint '+request.method()+' '+path)
  })
  return state
}
async function login(page:Page,username='alice') {
  await page.getByLabel('用户名',{exact:true}).fill(username)
  await page.getByLabel('密码',{exact:true}).fill('example-password-123')
  await page.getByRole('button',{name:'登录',exact:true}).click()
}
test('anonymous route, login, refresh and logout preserve safe session boundaries',async({page})=>{
  await mockAuth(page)
  await page.goto('/user')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await login(page)
  await expect(page.getByRole('heading',{name:'我的服务'})).toBeVisible()
  await expect(page.getByRole('link',{name:'用户管理'})).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading',{name:'我的服务'})).toBeVisible()
  expect(await page.evaluate(()=>({local:localStorage.length,session:sessionStorage.length}))).toEqual({local:0,session:0})
  await page.getByRole('button',{name:'退出登录'}).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByText('小林',{exact:true})).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole('heading',{name:'我的服务'})).toHaveCount(0)
})
test('registration uses only contracted fields and leads to login',async({page})=>{
  const state=await mockAuth(page)
  await page.goto('/register')
  await page.getByLabel('用户名',{exact:true}).fill('alice')
  await page.getByLabel('显示名称',{exact:true}).fill('小林')
  await page.getByLabel('密码',{exact:true}).fill('example-password-123')
  await page.getByRole('button',{name:'注册',exact:true}).click()
  await expect(page.getByText('注册成功，请登录。')).toBeVisible()
  expect(state.registrations).toEqual([{username:'alice',password:'example-password-123',display_name:'小林'}])
})
test('untrusted redirect stays in the application',async({page})=>{
  await mockAuth(page)
  await page.goto('/login?redirect=//evil.test')
  await login(page)
  await expect(page).toHaveURL(/\/user$/)
})
test('user cannot enter admin pages and agent has a separate home',async({page})=>{
  const state=await mockAuth(page,'user')
  await page.goto('/admin/users')
  await expect(page.getByRole('heading',{name:'没有访问权限'})).toBeVisible()
  await expect(page.getByRole('link',{name:'用户管理'})).toHaveCount(0)
  state.user={...fixtureUser,role:'agent'}
  await page.goto('/agent')
  await expect(page.getByRole('heading',{name:'客服工作台'})).toBeVisible()
  await expect(page.getByText('人工接单功能尚未开放。')).toBeVisible()
})
test('administrator changes roles and activation then loses private admin access on self demotion',async({page})=>{
  const state=await mockAuth(page,'admin')
  await page.goto('/admin/users')
  await page.getByRole('button',{name:'编辑 alice'}).click()
  await page.getByLabel('角色',{exact:true}).selectOption('agent')
  await page.getByRole('button',{name:'保存修改'}).click()
  await expect(page).toHaveURL(/\/agent$/)
  expect(state.patches).toEqual([{display_name:'小林',role:'agent',is_active:true}])
  await expect(page.getByRole('link',{name:'用户管理'})).toHaveCount(0)
})
test('last administrator rejection is understandable and can be corrected',async({page})=>{
  const state=await mockAuth(page,'admin');state.conflict=true
  await page.goto('/admin/users')
  await page.getByRole('button',{name:'编辑 alice'}).click()
  await page.getByLabel('启用账号').uncheck()
  await page.getByRole('button',{name:'保存修改'}).click()
  await expect(page.getByRole('alert')).toContainText('最后一个有效管理员')
  await expect(page.getByRole('button',{name:'保存修改'})).toBeEnabled()
})
test('API 401 clears private pages and explains expiration',async({page})=>{
  const state=await mockAuth(page,'admin');state.listStatus=401
  await page.goto('/admin/users')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('alert')).toContainText('登录已失效')
  await expect(page.getByRole('button',{name:'编辑 alice'})).toHaveCount(0)
})
test('403 and empty list have distinct recoverable states',async({page})=>{
  const state=await mockAuth(page,'admin');state.listStatus=403
  await page.goto('/admin/users')
  await expect(page.getByRole('alert')).toContainText('没有访问权限')
  state.listStatus=200;state.users=[]
  await page.getByRole('button',{name:'重试',exact:true}).click()
  await expect(page.getByText('暂无用户。')).toBeVisible()
})
test('offline session restoration can retry on a narrow screen',async({page})=>{
  await page.setViewportSize({width:375,height:812})
  const state=await mockAuth(page,'user');state.meOffline=true
  await page.goto('/user')
  await expect(page.getByRole('heading',{name:'暂时无法确认登录状态'})).toBeVisible()
  state.meOffline=false
  await page.getByRole('button',{name:'重试',exact:true}).click()
  await expect(page.getByRole('heading',{name:'我的服务'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.getByRole('button',{name:'退出登录'}).click()
  await login(page)
  await expect(page.getByRole('heading',{name:'我的服务'})).toBeVisible()
})


test('pending user save cannot be replaced by another editor',async({page})=>{
  const state=await mockAuth(page,'admin')
  state.users.push({...fixtureUser,id:'22222222-2222-4222-8222-222222222222',username:'bob',role:'user'})
  let release!:()=>void
  const pending=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/v1/admin/users/*',async route=>{await pending;await route.fallback()})
  await page.goto('/admin/users')
  await page.getByRole('button',{name:'编辑 alice'}).click()
  await page.getByLabel('角色',{exact:true}).selectOption('agent')
  await page.getByRole('button',{name:'保存修改'}).click()
  await expect(page.getByRole('button',{name:'编辑 bob'})).toBeDisabled()
  release()
  await expect(page).toHaveURL(/\/agent$/)
})
test('self role synchronization survives navigating away during the save',async({page})=>{
  await mockAuth(page,'admin')
  let release!:()=>void
  const pending=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/v1/admin/users/*',async route=>{await pending;await route.fallback()})
  await page.goto('/admin/users')
  await page.getByRole('button',{name:'编辑 alice'}).click()
  await page.getByLabel('角色',{exact:true}).selectOption('agent')
  await page.getByRole('button',{name:'保存修改'}).click()
  await page.getByRole('link',{name:'管理概览',exact:true}).click()
  await expect(page).toHaveURL(/\/admin$/)
  release()
  await expect(page.getByRole('link',{name:'用户管理'})).toHaveCount(0)
  await expect(page.getByRole('heading',{name:'客服工作台'})).toBeVisible()
})


test('login submission disables duplicate attempts and displays server field errors',async({page})=>{
  await mockAuth(page)
  let release!:()=>void
  const pending=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/v1/auth/login',async route=>{
    await pending
    await route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({error:{code:'VALIDATION_ERROR',message:'请求参数无效',request_id:'r',details:[{location:['body','password'],code:'string_too_short'}]}})})
  })
  await page.goto('/login')
  await login(page)
  await expect(page.getByRole('button',{name:'登录中…'})).toBeDisabled()
  release()
  await expect(page.getByLabel('密码',{exact:true})).toHaveAttribute('aria-invalid','true')
  await expect(page.getByText('密码需为 12–128 个字符。')).toBeVisible()
  await expect(page.getByRole('button',{name:'登录',exact:true})).toBeEnabled()
})
test('administrator can disable another user and sees the returned list state',async({page})=>{
  const state=await mockAuth(page,'admin')
  state.users=[{...fixtureUser,id:'22222222-2222-4222-8222-222222222222',username:'bob',role:'user'}]
  await page.goto('/admin/users')
  await page.getByRole('button',{name:'编辑 bob'}).click()
  await page.getByLabel('启用账号').uncheck()
  await page.getByRole('button',{name:'保存修改'}).click()
  await expect(page.getByText('已停用',{exact:true})).toBeVisible()
  await expect(page.getByRole('status')).toContainText('用户已更新')
  await expect(page).toHaveURL(/\/admin\/users$/)
})

