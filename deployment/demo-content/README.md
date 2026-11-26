# 知识服务台内容发布 · 2026-11-26

本内容包供运维负责人在已升级的 QA 服务中导入。6 个启用的知识库对所有已登录用户可读，包含 36 条 FAQ。普通用户、客服和管理员各拥有 12 段历史会话，共 139 条消息，其中 55 条助手回答带 FAQ 引用。17 段涉及人工交接，初始状态分别为 9 段排队、4 段处理中、4 段已关闭，另有 19 段机器人会话。

`service-content.json` 是可逐条审阅的内容底稿。内容由首次录入时的名单生成，与本地的指定库、FAQ、会话、原始消息、时间和引用逐一匹配，交接状态取该批素材首次录入的状态。操作演示时追加的消息和接单动作均未选入。源库中的账户名、密码与哈希、节点或会话凭据、源记录 UUID、向量、测试库与测试会话不随包交付。既有基金专属库和其他项目仍按原流程维护。

## 导入前

1. 只使用运维 PR 登记的同批运行包与内容附件。从受控渠道取得附件，用 PR 登记的 SHA-256 校验整个 ZIP，再解压到新建的私有目录。该目录应只有 `README.md`、`service-content.json`、`import_content.py` 三个普通文件。后台程序和运行环境来自发布的 API 镜像。可重复构建附件，内容底稿和导入程序均在业务仓库 `deployment/demo-content/`。
2. 运维负责人在维护窗口完成 QA 镜像部署，检查目标 QA 服务和索引 worker 就绪。导入前保持业务停写，保留该库 PostgreSQL 与 uploads 的一致备份：在 `/opt/ferrari/ops` 执行 `/opt/ferrari/bin/python scripts/ops.py backup knowledge-qa --maintenance-window`，记录备份批次并按运维手册运行隔离的 restore-check。备份、部署和内容导入按顺序执行。
3. 由运维在 QA 的“注册账号”页分别创建三个全新的专用用户名，分别使用密码管理器生成的强随机密码。用现有有权管理员登录“用户管理”，将三人分别设置为普通用户、客服、管理员并保持启用。分别登录新账号，在浏览器开发者工具的 Network 面板查看本账户同源 GET /api/v1/auth/me 返回的 id 和 role，核对后将三个 UUID 分别设为下文的 DEMO_USER_ID、DEMO_AGENT_ID、DEMO_ADMIN_ID。不要复制 Cookie、CSRF 或响应头。只向获授权的负责人私下交付凭据，尤其是有真实管理权限的管理员。核对三者的 UUID、用途、角色和归属，确保没有真实业务会话和接单记录。不要复用原生产管理员、访客、客服、计算节点或基金账号。导入工具只核对三个显式选择的 QA 用户 UUID，不创建、改权或重置账号。账号选择与密码始终不写入此包。

## 在目标 API 容器内导入

在已解压并校验的内容目录运行以下命令。保持同一 Bash 会话。三个 ID 变量填写新建账号的实际 UUID。命令以 Compose 标签定位正在运行的 QA api，并通过标准输入把两个小文件传至容器专属临时目录。无需远程访问数据库或开放端口。

```bash
set -eu
: "${DEMO_USER_ID:?填写专用普通用户 UUID}" "${DEMO_AGENT_ID:?填写专用客服 UUID}" "${DEMO_ADMIN_ID:?填写专用管理员 UUID}"
mapfile -t containers < <(docker ps -q --filter label=com.docker.compose.project=ferrari-knowledge-qa --filter label=com.docker.compose.service=api)
test "${#containers[@]}" -eq 1
api=${containers[0]}
docker inspect --format '{{.Config.Image}}' "$api"  # 与本批 QA release 的 api 标签核对
staging=$(docker exec "$api" mktemp -d /tmp/service-content.XXXXXXXX)
for file in import_content.py service-content.json; do
  docker exec -i "$api" sh -c 'umask 077; cat > "$1"' sh "$staging/$file" < "$file"
  local_sum=$(sha256sum "$file" | cut -d' ' -f1)
  remote_sum=$(docker exec "$api" sha256sum "$staging/$file" | cut -d' ' -f1)
  test "$local_sum" = "$remote_sum"
done
run_content() { docker exec -e PYTHONPATH=/app/backend "$api" python "$staging/import_content.py" "$@"; }
actors=(--user-id "$DEMO_USER_ID" --agent-id "$DEMO_AGENT_ID" --admin-id "$DEMO_ADMIN_ID")
run_content knowledge
```

`knowledge` 在一个事务中以本交付独立的确定性 ID 新建或核对知识库与 FAQ，交给本项目的 index-worker 建立索引。已有同名但不同 ID 的库会导致整个步骤回滚，由运维私下核对归属。不得将它自动合并到现有库。

等 36 条 FAQ 的当前版本索引完成后接着运行：

```bash
run_content history "${actors[@]}"
run_content verify "${actors[@]}"
docker exec "$api" rm -- "$staging/import_content.py" "$staging/service-content.json"
docker exec "$api" rmdir -- "$staging"
```

`history` 先验证账号和 36 条 FAQ 的索引版本，要求每个引文能在目标库当前 BGE 切片中唯一匹配，重建使用目标 UUID 的引用、消息回复关系和工单指派关系，再在一个事务中写入整批会话。提示等待索引时可在 worker 就绪后重试 `history`；处理失败的索引应先检查原因，必要时重跑 `knowledge` 重试对应失败任务。不会触发模型生成或补记费用、Token 用量、登录会话、操作审计。既有节点认证和生产账号密码不参与这个过程。

`verify` 逐条核对同一份角色映射、资料、引用和交接关系。每一阶段有专用数据库互斥锁。相同素材和映射重复执行保持总数不变。目标记录被人工编辑、已接单或会话已有新增消息时，导入或复核会报告差异，不覆盖现场。此基准复核应安排在开放演示操作之前。失败阶段自动回滚，该阶段之前已经成功的事务保持原状。

## 验收与回退

分别登录三个专用角色，核对首页入口、每个知识库 6 条 FAQ，任选一条带引用的历史回答展开原文。用户应看到自己的 12 段历史；客服除自己的 12 段外，还能阅读自己已接的 8 段；管理员可查看本批全部 36 段及其他依法授权可见的原有记录。客服/管理员队列新增 9 条，排队摘要不显示消息正文。检查原基金服务、原 FAQ、计算节点配置和现有用户业务正常。新增的演示管理员仅由获授权人员使用。

出现冲突时先停在当前阶段，保留错误信息并检查内容和映射，切勿删库或修改旧消息来让检查通过。若要整批撤回，先封存受影响实例和此后新增写入，由负责人在确认的维护窗口按生产恢复流程使用导入前一致备份；先在临时库验证还原结果并确认上线后新增数据的处理方案。仅切回旧镜像不会回退已写入的数据。
