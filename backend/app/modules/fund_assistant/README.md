# 基金业务助手内部接口

此模块是固定基金平台集成，不是任意租户、模型或工具网关。基金后端持有服务端密钥，由已登录基金账号生成`X-Fund-User-Id`正整数；浏览器不接触密钥或QA登录凭据。开启时需要`FUND_ASSISTANT_SERVICE_KEY`（32～256字符秘密）和`FUND_ASSISTANT_KB_ID`（专属restricted KB UUID）。两者未配时内部路由404，原问答网站默认行为不变。

所有接口位于`/internal/fund-assistant`，都要求`Authorization: Bearer <服务密钥>`与`X-Fund-User-Id`。来源用户ID由基金后端当前认证身份提供，不从基金请求正文/浏览器header透传。密钥与计算节点token完全独立，不能用节点token调用助手，也不能用助手密钥领取模型任务。

| 方法及相对路径 | 输入 | 结果 |
| --- | --- | --- |
| GET `/status` | 无 | `{available,reason,activeRequests,capacity,queueDepth}`；reason为ready/offline/busy/knowledge_pending/disabled |
| GET `/conversations` | 无 | `{items:[{id,title,createdAt,updatedAt}],total}`；最多最近100会话 |
| POST `/conversations` | `{}`或`{title}`，标题最多50字符 | 201，会话摘要；KB固定，不允许传入kb_ids |
| GET `/conversations/{id}` | 无 | 摘要、整体status、最多最近50条messages，消息JSON预算192KiB，超出略去更旧消息 |
| POST `/conversations/{id}/messages` | `{content,requestId}`；1～2000有效字符，UUID幂等键 | 202 `{conversationId,requestId,status}`，后台生成，立即返回 |
| POST `/conversations/{id}/cancel` | 无 | `{conversationId,status:"cancelled"}`；仅取消自己的当前生成 |

消息为`{id,role,content,status,createdAt,requestId,errorCode,sources:[{title,quote}]}`。status为queued/generating/completed/failed/cancelled；无消息的会话整体为idle。来源只有经过当前权限及版本重检的标题与原文片段，不返回其他用户身份、QA私有链接、内部session或服务凭据。原库/资料撤权后历史沿用原QA的证据隐藏投影。同一requestId与同一问题重放只读取已接受结果；用于不同问题返回409 `ASSISTANT_REQUEST_CONFLICT`，不会重复生成。

每个基金用户首次创建会话时原子建立随机唯一的技术User及映射，该账号没有可验证密码、没有公开下发的登录会话，也没有新增的改密接口。用户名先由数据库唯一约束占位，普通注册不能接管已有技术账号。技术身份仅为这一个私有KB创建成员关系；RAG每次固定该KB，不能因其他公共KB存在而扩大检索范围。没有基金数据库凭据、交易接口或工具调用代码。

请求复用既有chat全局槽（当前2）和compute队列（16），只通过同一个已配置queued provider调用原台式机。内部AuthSession只存随机不可还原hash，有效75秒，在生成终止后删除；原compute的User/AuthSession/Conversation/Message合法性检查完全保留。总生成deadline60秒，超时/取消不自动重试；重启沿用chat恢复把遗留生成标失败。worker原claim/heartbeat成功后更新last_seen_at，30秒未活动显示offline；节点协议、token及模型不变。离线/未索引503，容量满429，不把不可用写成成功回答，不改变原QA readiness。

## 专属资料导入

canonical资料由基金仓库`docs/assistant-knowledge`维护。运维传入仅含小Markdown的目录，在QA镜像既有backend环境内运行：

```sh
python -m app.modules.fund_assistant.import_knowledge --knowledge-dir /private/path/assistant-knowledge
```

首次输出`kb_id`，由运维写入私有环境变量，重新部署/启动API后生效；以后用同一`--kb-id <UUID>`（或环境中的固定ID）更新。输入只允许1～32个非链接普通`.md`文件，单个64KiB、总计256KiB、正文最多10000字符，第一行为独立标题且不可重复。目录内所有文件均会验证，拒绝未知文件/目录或链接。

每篇为一条FAQ，CLI只写专有标记的restricted知识库；拒绝修改其他KB。同内容导入幂等，变化递增版本，移除的篇目停用，既有索引立即失效；CLI只排入原FAQ索引任务，仍需既有index-worker实际建索引，不伪写indexed_version。至少一条可用FAQ/向量且全部启用FAQ版本已索引后，助手才显示资料就绪。

## 部署边界

基金server只能通过运维核定的内部连接访问QA API，不新增数据库或模型公网端口。不应把宿主回环地址误用为容器内宿主地址。QA现有Caddy仅转发浏览器API、health、compute，本模块不加入公网web转发；运维可在外层对该路径显式404。服务器对桌面节点仍使用现有HTTPS计算接口及已授权来源白名单，不向浏览器暴露内部助手入口。密钥、节点配置、环境文件及访问证据不提交Git或Release。

本接口提供教学模拟业务解释；没有代客交易或真实资金能力。回答选择与引用沿原RAG执行，基金实例额外固定只读及不荐股、不预测收益约束。模型不在线时基金后端应降级显示离线说明，基金交易、清算及账户功能不得依赖本接口可用性。
