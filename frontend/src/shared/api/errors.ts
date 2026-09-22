export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: unknown = undefined) { super(message) }
}
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求失败，请稍后重试。'
  if (error.status === 401) return error.code === 'INVALID_CREDENTIALS' ? '用户名或密码错误。' : '登录已失效，请重新登录。'
  if (error.code === 'CSRF_FAILED') return '操作验证已过期，请重试。'
  if (error.status === 403) return '没有访问权限，请联系管理员。'
  if (error.status === 429) return '操作过于频繁，请稍后重试。'
  return error.message
}
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.details)) return {}
  const messages: Record<string,string> = {username:'用户名需为 3–50 个字符。',password:'密码需为 12–128 个字符。',display_name:'请填写有效的显示名称。'}
  const result: Record<string,string> = {}
  for (const detail of error.details) {
    const field=detail?.location?.at(-1)
    if (typeof field === 'string' && messages[field]) result[field]=messages[field]
  }
  return result
}

