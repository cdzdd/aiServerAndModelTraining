import { ApiError } from './errors'

interface RequestOptions { method?: string; body?: unknown; authenticated?: boolean }
export function createApiClient(onUnauthorized: () => void) {
  let csrfToken: string | null = null
  let version = 0
  const activeStreams=new Set<AbortController>()
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
  async function* stream(path:string,body:unknown,signal:AbortSignal):AsyncGenerator<Uint8Array> {
    const current=version
    const changed=()=>new ApiError(0,'SESSION_CHANGED','登录状态已变化，请重试。')
    if(!csrfToken) {
      const result=await request<{csrf_token:string}>('/auth/csrf',{authenticated:false})
      if(current!==version) throw changed()
      csrfToken=result.csrf_token
    }
    const controller=new AbortController()
    const abort=()=>controller.abort()
    if(signal.aborted) abort()
    else signal.addEventListener('abort',abort,{once:true})
    activeStreams.add(controller)
    const timeout=setTimeout(abort,60_000)
    let reader:ReadableStreamDefaultReader<Uint8Array>|undefined
    try {
      const response=await fetch('/api/v1'+path,{
        method:'POST',credentials:'same-origin',signal:controller.signal,
        headers:{Accept:'text/event-stream','Content-Type':'application/json','X-CSRF-Token':csrfToken},
        body:JSON.stringify(body),
      })
      if(current!==version) throw changed()
      if(!response.ok) {
        const payload=await response.json().catch(()=>undefined)
        if(current!==version) throw changed()
        if(response.status===401) onUnauthorized()
        if(payload?.error?.code==='CSRF_FAILED') csrfToken=null
        throw new ApiError(response.status,payload?.error?.code ?? 'HTTP_ERROR',payload?.error?.message ?? '请求失败，请稍后重试。',payload?.error?.details)
      }
      if(!response.body) throw new ApiError(0,'STREAM_PROTOCOL','回答流中断，请刷新历史后重试。')
      reader=response.body.getReader()
      while(true) {
        const part=await reader.read()
        if(current!==version) throw changed()
        if(part.done) break
        yield part.value
      }
    } catch(error) {
      if(current!==version) throw changed()
      if(error instanceof ApiError) throw error
      if(signal.aborted) throw new ApiError(0,'CANCELLED','已停止生成。')
      if(controller.signal.aborted) throw new ApiError(0,'STREAM_TIMEOUT','回答超时，请刷新历史后重试。')
      throw new ApiError(0,'NETWORK_ERROR','网络连接失败，请检查连接后重试。')
    } finally {
      clearTimeout(timeout)
      signal.removeEventListener('abort',abort)
      activeStreams.delete(controller)
      if(reader) {await reader.cancel().catch(()=>{});reader.releaseLock()}
    }
  }
  return {request,upload,download,stream,setCsrfToken(token: string | null) { csrfToken=token; version++;for(const controller of activeStreams)controller.abort() }}
}
