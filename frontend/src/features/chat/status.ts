import type { ProgressStage } from './stream'

export const progressLabels: Record<ProgressStage,string> = {
  preparing:'正在准备回答…',
  rewriting:'正在整理追问…',
  retrieving:'正在查找资料…',
  queued:'正在排队等待模型…',
  generating:'模型正在生成…',
  validating:'正在核对引用…',
}

const failureReasons: Record<string,string> = {
  MODEL_OFFLINE:'本地模型未连接，请稍后重试或申请人工客服。',
  COMPUTE_BUSY:'模型服务忙碌，请稍后手动重试。',
  PROVIDER_RATE_LIMITED:'模型请求过于频繁，请稍后重试。',
  PROVIDER_TIMEOUT:'模型服务响应超时，请稍后重试。',
  RAG_TIMEOUT:'回答处理超时，请稍后重试。',
  PROVIDER_UNAVAILABLE:'模型服务暂不可用，请稍后重试。',
  PROVIDER_AUTH_FAILED:'模型服务认证失败，请联系管理员。',
  PROVIDER_CONFIG_ERROR:'模型服务配置有误，请联系管理员。',
  PROVIDER_BAD_REQUEST:'模型暂不支持这次请求，请调整问题后重试。',
  PROVIDER_STREAM_INTERRUPTED:'模型响应中断，请稍后重试。',
  PROVIDER_PROTOCOL_ERROR:'模型响应格式无效，请稍后重试。',
  PROVIDER_EMPTY_RESPONSE:'模型未返回有效内容，请稍后重试。',
  PROVIDER_UNSUPPORTED_RESPONSE:'模型响应无法使用，请稍后重试。',
  STREAM_PROTOCOL:'回答连接中断，请刷新历史确认结果后重试。',
  SOURCE_CHANGED:'资料或访问权限已变化，请重新提问。',
  AUTHORITY_CHANGED:'账号或会话权限已变化，请重新登录或检查访问权限。',
  MODEL_INDEX_MISMATCH:'知识索引需要更新，请联系管理员。',
  MODEL_UNAVAILABLE:'知识检索模型暂不可用，请稍后重试。',
  MODEL_INTEGRITY:'知识检索模型需要检查，请联系管理员。',
  ENCODE_FAILED:'知识检索暂不可用，请稍后重试。',
  CANCELLED:'已停止生成，可手动重新提问。',
  SERVER_RESTARTED:'服务已重启，请手动重新提问。',
}

export function failureReason(code:string|null, status:'failed'|'cancelled'):string {
  return failureReasons[code ?? ''] ?? (status==='cancelled'
    ? '这次生成已取消，可手动重新提问。'
    : '回答未能完成，请刷新历史确认结果后重试。')
}
