import type { Role, Session } from '../features/auth/session'
export function homeFor(role:Role) {return '/'+role}
export function safeRedirect(value:unknown):string {return typeof value==='string' && ['/user','/agent','/admin','/admin/users'].includes(value) ? value : '/'}
export function createAuthGuard(session:Session) {
  return async (to:{path:string;fullPath:string;meta:{public?:boolean;guest?:boolean;roles?:Role[]}}) => {
    if(to.meta.public && !to.meta.guest) return true
    try {await session.restore()} catch {return {path:'/session-error',query:{redirect:safeRedirect(to.fullPath)}}}
    const user=session.state.user
    if(to.meta.guest) return user ? homeFor(user.role) : true
    if(!user) return {path:'/login',query:{redirect:safeRedirect(to.fullPath)}}
    if(to.path==='/') return homeFor(user.role)
    if(to.meta.roles && !to.meta.roles.includes(user.role)) return '/forbidden'
    return true
  }
}

