# todo-026 改造计划

## 设计取舍

复用ComputeWorker最近活动时间与ComputeJob有效租约，保持原queued协议、模型ID、token和60秒总期限。节点健康与网页数据库健康分别表达。模型原文仍缓冲并通过引用及权限复核后才展示。

节点在线窗口沿用基金助手已有30秒规则，运行中有效租约也作为在线证据。队列入队前检查模型可用性，排队后再次检查失联，避免只在进入请求时判断。忙碌不等同于离线，已有运行任务不能因正常处理而被误判。

失败发生在已受理请求之后时，保持原失败占位及配额记录；离线错误准确保存在消息error_code，不伪造正文或自动重试。

## 接口与工作划分

### 1 后端状态与失败

- compute.service新增可复用的模型可用性查询，供queued和基金status使用。
- 新增GET /api/v1/model/status，要求登录，返回state（ready/busy/offline）、provider和model_id及available。普通用户不获得worker或job元数据。
- queued在入队和等待结果时检查状态，离线使用MODEL_OFFLINE；运行任务仍以原租约、取消、超时机制终结。
- 错误码在provider和RAG安全消息表登记，保持标准错误及消息持久化。

### 2 等待阶段

- SSE在meta之后支持progress事件，payload为stage，枚举preparing、rewriting、retrieving、queued、generating、validating。
- GenerationStream用轻量上下文收集RAG/provider当前阶段，在等待异步结果时发送阶段变化，先重新校验当前请求身份和会话状态。
- 不增加数据库进度列或通用消息系统，不改变基金内部轮询协议。progress不携带问题、证据或模型token。

### 3 页面

- stream解码器接受并严格校验progress，ChatPage在当前生成消息展示阶段。
- 通过登录态状态API显示模型在线/忙碌/离线，保留草稿和手动重试，人工入口可继续使用。
- MessageList对failed/cancelled与已保存error_code展示安全中文原因；错误不再只显示在页首。

### 4 节点

- 增加只读doctor命令与启动前检查，辨识200健康、401可达、403来源被拒、TLS/网络失败及精确模型是否存在。
- 提供同一正式配置的单实例保护和可识别的启停方式、节点启动/退出安全日志，复用现有Ollama与冻结依赖。
- 无凭据轮换、无限重启、自动重放、模型下载或云端安全策略修改。

## 验证与集成

按模块先补失败行为测试，分别覆盖在线窗口/有效租约、不同模型、忙碌、入队后失联、正常返回、取消/权限变化和旧失败记录。前端覆盖progress解码、错误展示与状态切换；节点覆盖403、TLS失败、重复启动和秘密不入日志。用隔离PostgreSQL、独立端口8186/5386/15486运行node scripts/dev.mjs check和专项。

先完成代码和本地真实模型链路，再评审、业务PR与状态收尾。运维侧现场403须由获授权的来源核验与白名单处理解决，随后验证last_seen、真实新问题的任务成功、引用和原业务健康，按实际结果记录。
