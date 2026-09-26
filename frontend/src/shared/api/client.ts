import { ApiError } from './errors'

interface RequestOptions { method?: string; body?: unknown; authenticated?: boolean }
export function createApiClient(onUnauthorized: () => void) {
  let csrfToken: string | null = null
  let version = 0
  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const current = version
    const changed = () => new ApiError(0, 'SESSION_CHANGED', '登录状态已变化，请重试。')
    const method = options.method ?? 'GET'
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !csrfToken) {
      const result = await request<{csrf_token:string}>('/auth/csrf', {authenticated:false})
      if (current !== version) throw changed()
      csrfToken = result.csrf_token
    }
    const headers = new Headers({Accept:'application/json'})
    if (options.body !== undefined) headers.set('Content-Type','application/json')
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) headers.set('X-CSRF-Token',csrfToken)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15_000)
    try {
      const response = await fetch('/api/v1' + path, {
        method, credentials:'same-origin', headers, signal:controller.signal,
        body:options.body === undefined ? undefined : JSON.stringify(options.body),
      })
      const payload = response.status === 204 ? undefined : await response.json().catch(() => undefined)
      if (current !== version) throw changed()
      if (!response.ok) {
        if (response.status === 401 && options.authenticated !== false) onUnauthorized()
        if (payload?.error?.code === 'CSRF_FAILED') csrfToken = null
        throw new ApiError(response.status, payload?.error?.code ?? 'HTTP_ERROR',
          payload?.error?.message ?? '请求失败，请稍后重试。', payload?.error?.details)
      }
      return payload as T
    } catch (error) {
      if (error instanceof ApiError) throw error
      throw new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查连接后重试。')
    } finally { clearTimeout(timeout) }
  }
  async function upload<T>(path:string,body:FormData,onProgress:(percent:number)=>void):Promise<T> {
    const current=version
    if(!csrfToken) {
      const result=await request<{csrf_token:string}>('/auth/csrf',{authenticated:false})
      if(current!==version) throw new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。')
      csrfToken=result.csrf_token
    }
    return new Promise<T>((resolve,reject)=>{
      const xhr=new XMLHttpRequest()
      xhr.open('POST','/api/v1'+path)
      xhr.withCredentials=true
      xhr.timeout=60_000
      xhr.setRequestHeader('Accept','application/json')
      xhr.setRequestHeader('X-CSRF-Token',csrfToken!)
      xhr.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded*100/event.total))}
      xhr.onerror=xhr.ontimeout=xhr.onabort=()=>reject(new ApiError(0,'NETWORK_ERROR','网络连接失败，请检查连接后重试。'))
      xhr.onload=()=>{
        if(current!==version) {reject(new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。'));return}
        let payload
        try {payload=JSON.parse(xhr.responseText)} catch {payload=undefined}
        if(xhr.status<200 || xhr.status>=300) {
          if(xhr.status===401) onUnauthorized()
          if(payload?.error?.code==='CSRF_FAILED') csrfToken=null
          reject(new ApiError(xhr.status,payload?.error?.code ?? 'HTTP_ERROR',payload?.error?.message ?? '请求失败，请稍后重试。',payload?.error?.details))
          return
        }
        resolve(payload as T)
      }
      xhr.send(body)
    })
  }
  async function download(path:string):Promise<Blob> {
    const current=version
    const controller=new AbortController()
    const timeout=setTimeout(()=>controller.abort(),60_000)
    try {
      const response=await fetch('/api/v1'+path,{credentials:'same-origin',headers:{Accept:'application/octet-stream'},signal:controller.signal})
      if(current!==version) throw new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。')
      if(!response.ok) {
        const payload=await response.json().catch(()=>undefined)
        if(current!==version) throw new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。')
        if(response.status===401) onUnauthorized()
        throw new ApiError(response.status,payload?.error?.code ?? 'HTTP_ERROR',payload?.error?.message ?? '请求失败，请稍后重试。',payload?.error?.details)
      }
      const blob=await response.blob()
      if(current!==version) throw new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。')
      return blob
    } catch(error) {
      if(error instanceof ApiError) throw error
      throw new ApiError(0,'NETWORK_ERROR','网络连接失败，请检查连接后重试。')
    } finally {clearTimeout(timeout)}
  }
  return {request,upload,download,setCsrfToken(token: string | null) { csrfToken=token; version++ }}
}
