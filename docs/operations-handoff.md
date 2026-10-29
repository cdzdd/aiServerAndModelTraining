# Ferrari 运维交接

业务源码留在本仓库。运维配置位于[Ferrari_Server projects/knowledge-qa](https://github.com/cdzdd/Ferrari_Server/tree/main/projects/knowledge-qa)，运行类型`python-pgvector-v1`；发布规则以[最新契约](https://github.com/cdzdd/Ferrari_Server/blob/main/docs/python-pgvector-runtime.md)为准，不在此复制公共规则。

构建入口为`python scripts/deploy/ferrari_build.py --model-dir <已校验BGE目录> --output-dir <本工作树忽略目录>`，前提和用法见[scripts/README](../scripts/README.md)。它从干净提交构建Linux镜像；固定BGE随显式Ferrari目标入镜像，默认本地构建保持原行为。装包继续使用运维仓库的`package_qa.py`。

项目ID/Compose提案为`knowledge-qa`/`ferrari-knowledge-qa`，2048MiB/2CPU，服务器回环18082、桌面转发18089；均待运维实机核定。ECS运行业务/PG/BGE，台式机主动领取固定Ollama任务。正式秘密、管理员、节点和私有通道由运维创建，不复用验收数据库或凭据。

冻结版本、镜像ID、运行包、真实验证及限制见[交付报告](operations/ferrari-delivery-report.md)，最新PR与功能合并记录见[todo-022](tasks/todo-022.md)。本地运行、运行包可读和PR合并均不替代实际ECS发布；公网沿016/017及运维对应流程单独验收。
