# 知序 · 数据结构课程学习助手

FastAPI / SQLAlchemy 后端，Vue 3 / TypeScript / Vite 前端。SQLite 保存业务数据，Qdrant 保存文档向量，适用于本机单进程部署。

课程分类统一为八个内置章节：绪论与算法分析、线性表、栈与队列、串、数组与广义表、树与二叉树、图、查找、排序。资料、对话、练习、错题和报告使用同一章节目录，没有子知识点或独立主题分类。

系统不自带学习资料或题库，不提供资料推荐模块。课程资料由管理员上传维护，个人资料由所属用户维护。学习对话和实时 AI 练习都不要求先上传资料；相关资料自动作为补充参考。

## 安装与启动

需要 Python 3.12–3.13、Node.js 22.12+、uv 与 pnpm 10。已有 `.env` 请保留，服务密钥只在后端使用。

在仓库根目录的 PowerShell 执行：

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
Push-Location backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -X utf8 -m capstone.seed
Pop-Location
Push-Location frontend
pnpm.cmd install --frozen-lockfile
Pop-Location
```

分别启动后端和前端：

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

前端地址：<http://127.0.0.1:5173>；后端地址：<http://127.0.0.1:8000>。Vite 代理 `/api` 到后端。API 文档为 `/docs`，健康接口为 `/api/v1/health`。健康通过只说明存储可用，不代表模型或 RAG 已就绪。

构建后可由同一个后端进程提供网页：

```powershell
Push-Location frontend
pnpm.cmd build
Pop-Location
.\scripts\start-backend.ps1 -ServeWeb
```

访问 <http://127.0.0.1:8000>。仅启动一个后端 worker，避免多个进程同时打开本地 Qdrant 目录。

## 使用流程

1. 注册或登录，系统为账号创建个人知识库。
2. 在知识库按章节查找资料；个人文件可选关联章节，课程文件必须关联章节并说明来源许可。
3. 学习对话默认使用课程资料＋我的学习资料，无需选择范围；从某份资料进入时针对该资料学习。列表只显示未归档会话，每项旁的图标可重命名或归档。没有资料或没有相关检索结果时正常回答，有相关片段时显示真实引用。
4. 在练习中心选择一个章节，默认基础难度、5 题，练习要求与参考资料可选。统一实时 AI 出题并复核，未配置生成模型时明确不可出题。
5. 完成整组有效题目后统一提交，再查看判题、解析与来源；错误自动进入错题本。重复请求不重复计分，失败保留草稿。
6. 错题按章节、状态或题干筛选；不同上海日期连续两次答对可标记该题已巩固，再次答错回到待复习。
7. 按需生成对话总结、保存学习报告并导出 Markdown。统计与模型生成文字分开；少于 5 道独立新题显示证据不足，不估算学习时长。

现行报告保存生成时快照，后续作答不会改写已保存报告。资料删除会保留当前学习记录中的引用说明，但不可用于新的检索。

## 维护

章节名称和顺序集中在 `backend/src/capstone/core/chapters.py`，数据库查询与校验位于 `services/chapters.py`。初始化可重复执行，保留章节 ID，不创建演示账号或课程文件。调整已有分类需编写迁移。

管理员登录后可在“课程资料管理”上传、重新处理、删除课程文件并查看维护记录。角色只通过本机 `capstone.manage_admin` 命令授予或撤销，服务端始终检查权限。详情见 [管理员课程资料维护说明](docs/管理员课程资料维护说明.md)。

停用确认有误的 AI 题目：

```powershell
Push-Location backend
uv run --locked python -X utf8 -m capstone.manage_questions --id <题目UUID> --reason "确认的原因"
Pop-Location
```

批量资料导入必须显式指定内容包路径；没有默认学习资料。格式与边界见 [内容维护说明](content/README.md)。逐题提交、反馈、题库导入、多策略和多知识点请求已删除，旧请求直接拒绝。

## 数据与升级

业务数据在 `data/`，连接配置在根目录 `.env`。停止后端后备份 SQLite、上传文件、Qdrant 及索引配置；密钥单独保管，不提交 Git。

**0013 会清空旧对话、题目、练习、作答、错题和报告。** 账号、知识库、上传资料、文档任务和管理员维护资源保留。迁移同时删除父子知识点模型及已下线流程字段；不保留历史读取兼容。降级也会清空学习记录，不能恢复已删除数据，回退需使用升级前备份。

0014 移除消息的回答方式字段及约束，保留现有消息与引用，并一次性更新原提问请求摘要。提示或举例要求直接写在问题中，服务端统一按正文生成回答。

0015 移除旧的资料不足结果字段；直接删除旧固定回复及其配对问题、旧口径报告，不保留历史格式兼容。新对话仅依赖生成模型，检索默认最多等待 3 秒，超时或已知检索服务故障时正常回答。通过 CAPSTONE_CHAT_RETRIEVAL_TIMEOUT_SECONDS 调整等待预算；后台按错误码记录降级，不记录问题、片段或供应商原文。

首次安装仍按迁移链升级到最新版本。历史迁移文件用于建立和升级数据库，不是运行时兼容层，不应直接修改已发布迁移。

## 开发检查

```powershell
.\scripts\check.ps1
```

包含后端 Ruff、格式、接口及存储测试、Alembic 模型差异检查，以及前端状态测试、TypeScript 检查与构建。测试使用临时目录和模型替身，不能替代真实模型验收。

目录：`backend/src/capstone/api` 接口边界，`core` 配置及输入契约，`services` 业务事务与模型任务，`db` 持久化；`frontend/src/api` 请求契约，`state` 页面状态，`views` 与 `components` 展示。`content` 仅保留独立评估问题和许可记录。

相关说明：[练习与章节](docs/练习与章节说明.md)、[架构与清理检查](docs/架构与清理检查.md)、[部署与使用](docs/部署与使用说明.md)、[模型接入](docs/模型接入说明.md)、[RAG 评估](docs/RAG评估说明.md)。
