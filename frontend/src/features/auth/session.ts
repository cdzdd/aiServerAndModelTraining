import { reactive, readonly } from 'vue'
import { createApiClient } from '../../shared/api/client'
import { ApiError } from '../../shared/api/errors'

export type Role = 'user' | 'agent' | 'admin'
export interface User { id: string; username: string; display_name: string; role: Role; is_active: boolean; created_at: string }
export interface Credentials { username: string; password: string }

export function createSession() {
  const state = reactive<{user:User|null; initialized:boolean; loading:boolean; expired:boolean}>({user:null,initialized:false,loading:false,expired:false})
  let version=0
  let restoring: Promise<void> | null=null
  function clear() {
    version++
    state.user=null
    state.initialized=true
    api.setCsrfToken(null)
  }
  const api=createApiClient(() => {
    state.expired=Boolean(state.user)
    clear()
  })
  async function restore(force=false) {
    if (restoring) return restoring
    if (state.initialized && !force) return
    const current=version
    state.loading=true
    restoring=(async()=>{
      try {
        const user=await api.request<User>('/auth/me')
        if(current===version) {state.user=user;state.initialized=true}
      } catch(error) {
        if(!(error instanceof ApiError && error.status===401)) throw error
      } finally {state.loading=false;restoring=null}
    })()
    return restoring
  }
  async function login(credentials:Credentials) {
    const current=++version
    const result=await api.request<{user:User;csrf_token:string}>('/auth/login',{method:'POST',body:credentials,authenticated:false})
    if(current!==version) return
    state.user=result.user;state.initialized=true;state.expired=false
    api.setCsrfToken(result.csrf_token)
  }
  async function register(fields:Credentials & {display_name:string}) {
    return api.request<User>('/auth/register',{method:'POST',body:fields,authenticated:false})
  }
  async function logout() {
    try {await api.request<void>('/auth/logout',{method:'POST'})}
    catch(error) {if(!(error instanceof ApiError && error.status===401)) throw error}
    clear()
    state.expired=false
  }
  return {state:readonly(state),api,restore,login,register,logout}
}
export const session=createSession()
export type Session=ReturnType<typeof createSession>

