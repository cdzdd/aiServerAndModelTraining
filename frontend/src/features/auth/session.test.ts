import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSession } from './session'
import { ApiError } from '../../shared/api/errors'

const user = { id: '11111111-1111-4111-8111-111111111111', username: 'alice', display_name: '小林', role: 'admin', is_active: true, created_at: '2026-09-22T00:00:00Z' }
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), {status, headers: {'Content-Type':'application/json'}}) }
afterEach(() => vi.unstubAllGlobals())

describe('cookie session and API contract', () => {
  it('restores the server identity once and never persists credentials in browser storage', async () => {
    const fetcher = vi.fn(async () => json(user))
    vi.stubGlobal('fetch', fetcher)
    const session = createSession()
    await Promise.all([session.restore(), session.restore()])
    expect(session.state.user).toEqual(user)
    expect(session.state.initialized).toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0]).toMatchObject(['/api/v1/auth/me', {credentials:'same-origin'}])
    expect(localStorage.length + sessionStorage.length).toBe(0)
  })
  it('does not publish an identity until restoration completes', async () => {
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', () => new Promise<Response>(resolve => {finish=resolve}))
    const session = createSession()
    const pending = session.restore()
    expect(session.state.loading).toBe(true)
    expect(session.state.user).toBeNull()
    finish(json(user)); await pending
    expect(session.state.loading).toBe(false)
    expect(session.state.user?.role).toBe('admin')
  })
  it('obtains pre-login CSRF, rotates it after login and sends the new token on logout', async () => {
    const calls: {url: string; options: RequestInit}[] = []
    vi.stubGlobal('fetch', async (url: string, options: RequestInit) => {
      calls.push({url, options})
      if (url.endsWith('/csrf')) return json({csrf_token:'before'})
      if (url.endsWith('/login')) return json({user,csrf_token:'after'})
      return new Response(null,{status:204})
    })
    const session = createSession()
    await session.login({username:'alice',password:'long-password'})
    expect(session.state.user).toEqual(user)
    await session.logout()
    expect(calls.map(call=>call.url)).toEqual(['/api/v1/auth/csrf','/api/v1/auth/login','/api/v1/auth/logout'])
    expect(new Headers(calls[1]!.options.headers).get('X-CSRF-Token')).toBe('before')
    expect(JSON.parse(calls[1]!.options.body as string)).toEqual({username:'alice',password:'long-password'})
    expect(new Headers(calls[2]!.options.headers).get('X-CSRF-Token')).toBe('after')
    expect(calls.every(call=>call.options.credentials==='same-origin')).toBe(true)
    expect(session.state.user).toBeNull()
  })
  it('clears private state on any authenticated 401', async () => {
    vi.stubGlobal('fetch', async () => json(user))
    const session=createSession(); await session.restore()
    vi.stubGlobal('fetch', async () => json({error:{code:'UNAUTHORIZED',message:'登录失效',request_id:'r'}},401))
    await expect(session.api.request('/admin/users')).rejects.toMatchObject({status:401})
    expect(session.state.user).toBeNull()
    expect(session.state.expired).toBe(true)
  })
  it('keeps anonymous restoration separate from an expired signed-in session', async () => {
    vi.stubGlobal('fetch', async () => json({error:{code:'UNAUTHORIZED',message:'未登录',request_id:'r'}},401))
    const session=createSession(); await session.restore()
    expect(session.state.initialized).toBe(true)
    expect(session.state.user).toBeNull()
    expect(session.state.expired).toBe(false)
  })
  it('preserves 403 details without retrying or clearing the signed-in user', async () => {
    vi.stubGlobal('fetch', async () => json(user))
    const session=createSession(); await session.restore()
    const denied=vi.fn(async()=>json({error:{code:'FORBIDDEN',message:'没有访问权限',request_id:'r'}},403))
    vi.stubGlobal('fetch', denied)
    await expect(session.api.request('/admin/users')).rejects.toMatchObject({status:403,code:'FORBIDDEN'})
    expect(denied).toHaveBeenCalledTimes(1)
    expect(session.state.user?.id).toBe(user.id)
  })
  it('allows an explicit retry after a network restoration failure', async () => {
    vi.stubGlobal('fetch', async()=>{throw new TypeError('offline')})
    const session=createSession()
    await expect(session.restore()).rejects.toBeInstanceOf(ApiError)
    expect(session.state.initialized).toBe(false)
    vi.stubGlobal('fetch', async()=>json(user))
    await session.restore()
    expect(session.state.user?.id).toBe(user.id)
  })
  it('ignores a late restoration response after logout', async () => {
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', async (url:string) => {
      if(url.endsWith('/me')) return new Promise<Response>(resolve=>{finish=resolve})
      if(url.endsWith('/csrf')) return json({csrf_token:'before'})
      return new Response(null,{status:204})
    })
    const session=createSession(); const restoring=session.restore()
    await session.logout()
    finish(json(user)); await restoring
    expect(session.state.user).toBeNull()
  })
  it('does not claim logout succeeded when the server is unreachable', async () => {
    vi.stubGlobal('fetch', async()=>json(user))
    const session=createSession(); await session.restore()
    vi.stubGlobal('fetch', async()=>{throw new TypeError('offline')})
    await expect(session.logout()).rejects.toBeInstanceOf(ApiError)
    expect(session.state.user?.id).toBe(user.id)
  })
})


it('does not let a late 401 from an old session invalidate the next login',async()=>{
  let finish!:(response:Response)=>void
  vi.stubGlobal('fetch',async(url:string)=>{
    if(url.endsWith('/me')) return json(user)
    if(url.endsWith('/csrf')) return json({csrf_token:'before'})
    if(url.endsWith('/logout')) return new Response(null,{status:204})
    if(url.endsWith('/login')) return json({user:{...user,id:'22222222-2222-4222-8222-222222222222',username:'new'},csrf_token:'new-token'})
    return new Promise<Response>(resolve=>{finish=resolve})
  })
  const session=createSession();await session.restore()
  const oldRequest=session.api.request('/admin/users').catch(error=>error)
  await session.logout();await session.login({username:'new',password:'example-password'})
  finish(json({error:{code:'UNAUTHENTICATED',message:'expired'}},401))
  await oldRequest
  expect(session.state.user?.username).toBe('new')
  expect(session.state.expired).toBe(false)
})
it('does not send a queued write after the session changes during CSRF acquisition',async()=>{
  let finish!:(response:Response)=>void
  const writes:string[]=[]
  vi.stubGlobal('fetch',async(url:string)=>{
    if(url.endsWith('/me')) return json(user)
    if(url.endsWith('/csrf')) return new Promise<Response>(resolve=>{finish=resolve})
    writes.push(url);return json(user)
  })
  const session=createSession();await session.restore()
  const pending=session.api.request('/admin/users/'+user.id,{method:'PATCH',body:{role:'agent'}}).catch(error=>error)
  session.api.setCsrfToken('replacement-token')
  finish(json({csrf_token:'old-token'}));await pending
  expect(writes).toEqual([])
})


it('a superseded logout response cannot clear a newer login',async()=>{
  let finish!:(response:Response)=>void
  vi.stubGlobal('fetch',async(url:string)=>{
    if(url.endsWith('/me')) return json(user)
    if(url.endsWith('/csrf')) return json({csrf_token:'before'})
    if(url.endsWith('/logout')) return new Promise<Response>(resolve=>{finish=resolve})
    return json({user:{...user,username:'new'},csrf_token:'new-token'})
  })
  const session=createSession();await session.restore()
  const logout=session.logout()
  await vi.waitFor(()=>expect(finish).toBeTypeOf('function'))
  await session.login({username:'new',password:'example-password'})
  finish(new Response(null,{status:204}));await logout
  expect(session.state.user?.username).toBe('new')
})

