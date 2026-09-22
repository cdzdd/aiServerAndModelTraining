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
  return {request, setCsrfToken(token: string | null) { csrfToken=token; version++ }}
}

