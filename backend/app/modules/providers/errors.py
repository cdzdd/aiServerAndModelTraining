from typing import Literal

ProviderErrorCode = Literal[
    "PROVIDER_CONFIG_ERROR",
    "PROVIDER_BAD_REQUEST",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_TIMEOUT",
    "PROVIDER_STREAM_INTERRUPTED",
    "PROVIDER_PROTOCOL_ERROR",
    "PROVIDER_EMPTY_RESPONSE",
    "PROVIDER_UNSUPPORTED_RESPONSE",
]

MESSAGES: dict[ProviderErrorCode, str] = {
    "PROVIDER_CONFIG_ERROR": "模型配置无效，请检查服务端配置",
    "PROVIDER_BAD_REQUEST": "模型请求参数不受支持",
    "PROVIDER_AUTH_FAILED": "模型服务认证失败",
    "PROVIDER_RATE_LIMITED": "模型服务请求过于频繁",
    "PROVIDER_UNAVAILABLE": "模型服务暂不可用",
    "PROVIDER_TIMEOUT": "模型服务响应超时",
    "PROVIDER_STREAM_INTERRUPTED": "模型响应未完整结束",
    "PROVIDER_PROTOCOL_ERROR": "模型响应格式无效",
    "PROVIDER_EMPTY_RESPONSE": "模型未返回有效文本",
    "PROVIDER_UNSUPPORTED_RESPONSE": "模型返回了不受支持的内容类型",
}


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode):
        self.code = code
        self.message = MESSAGES[code]
        super().__init__(self.message)
