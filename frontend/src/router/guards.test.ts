import { describe, expect, it, vi } from 'vitest'
import { createSession } from '../features/auth/session'
import { createAuthGuard, safeRedirect } from './guards'
const user={id:'11111111-1111-4111-8111-111111111111',username:'alice',display_name:'小林',role:'user',is_active:true,created_at:'2026-09-22T00:00:00Z'}
describe('route access',()=>{
  it('sends anonymous visitors to login with a safe return destination',async()=>{
    vi.stubGlobal('fetch',async()=>new Response('{}',{status:401}))
    const guard=createAuthGuard(createSession())
    expect(await guard({path:'/admin/users',fullPath:'/admin/users',meta:{roles:['admin']}})).toEqual({path:'/login',query:{redirect:'/admin/users'}})
  })
  it('denies an ordinary user before an admin page is entered',async()=>{
    vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(user)))
    expect(await createAuthGuard(createSession())({path:'/admin/users',fullPath:'/admin/users',meta:{roles:['admin']}})).toBe('/forbidden')
  })
  it('uses a recoverable page when identity cannot be checked',async()=>{
    vi.stubGlobal('fetch',async()=>{throw new TypeError('offline')})
    expect(await createAuthGuard(createSession())({path:'/user',fullPath:'/user',meta:{}})).toEqual({path:'/session-error',query:{redirect:'/user'}})
  })
  it('does not resolve private navigation while identity is pending',async()=>{
    let finish!:(response:Response)=>void
    vi.stubGlobal('fetch',()=>new Promise<Response>(resolve=>{finish=resolve}))
    let resolved=false
    const pending=createAuthGuard(createSession())({path:'/user',fullPath:'/user',meta:{roles:['user']}}).then(value=>{resolved=true;return value})
    await Promise.resolve();expect(resolved).toBe(false)
    finish(new Response(JSON.stringify(user)))
    expect(await pending).toBe(true)
  })
  it.each(['https://evil.test','//evil.test','/\\evil.test','/%2f%2fevil.test','/admin/users?next=https://evil.test','/login',null,['/admin']])('rejects untrusted return destination %s',value=>{
    expect(safeRedirect(value)).toBe('/')
  })
  it('preserves an allowed private destination',()=>expect(safeRedirect('/admin/users')).toBe('/admin/users'))
})

