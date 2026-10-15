# 知序 · 数据结构课程学习助手

基于 RAG 的桌面网页项目，后端使用 Python / FastAPI，前端使用 Vue 3、TypeScript 和 Vite。
业务数据保存到 SQLite，文档向量使用 Qdrant 本地持久化模式。

目前完成基础工程初始化：网页导航、服务连接状态、后端健康接口、本地存储连接、迁移框架、开发脚本与依赖锁文件。
账户与知识库的数据基础已完成：四张业务表、首个迁移和课程目录初始化。
注册、登录、退出、刷新恢复登录、显示名称修改及桌面账户页面已实现，注册时自动创建个人知识库。
知识库列表、详情和课程目录页面已接入真实数据，并检查个人库访问权限。
资料上传、预览、下载、删除、失败重试和文档处理管线已接入网页；学习对话的保存、真实检索管线与流式页面已实现，题目、错题和报告尚未实现。生成模型与 Embedding 的具体调用适配仍待接入，默认未配置时资料不会标为就绪。
首批公开内容已整理为 3 份中文笔记、15 道固定题和 30 个评估问题，来源与许可见 [内容说明](content/README.md)。维护者可用导入命令将笔记登记为课程资料；向量就绪须接入真实 Embedding，题库练习仍待接入。

## 环境

- Python 3.13（本次验证版本 3.13.7；工程声明兼容 3.12–3.13）。
- Node.js 22.12+（本次验证版本 24.11.1）。
- uv 与 pnpm 10（本次使用 pnpm 10.33.0）。
- 首版使用一个后端进程，共享一个 Qdrant 本地客户端。

## 安装与启动

在仓库根目录的 PowerShell 中执行：

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }

Push-Location backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -X utf8 -m capstone.seed
uv run --locked python -X utf8 -m capstone.import_course
Pop-Location

Push-Location frontend
pnpm.cmd install --frozen-lockfile
Pop-Location
```

已有 .env 时保留原文件并按 [.env.example](.env.example) 补充配置。本轮初始化已在本机安装依赖，无须配置模型密钥。
当前迁移 0001 创建四张账户与目录表，0002 加入文档、片段及文档任务，0003 加入会话和消息，共九张业务表，其余表随功能加入。
课程初始化可重复执行，写入一个课程库和 31 个目录节点（8 个章节、23 个子知识点），保留已有 ID 和个人数据；不创建演示账号或课程文档。
它不会自动执行迁移，数据库未升级时会提示先执行 upgrade head。-X utf8 保证初始化命令输出中文时使用 UTF-8。

分别在两个终端中运行：

```powershell
# 终端 1：后端
.\scripts\start-backend.ps1

# 终端 2：网页
.\scripts\start-frontend.ps1
```

网页地址：`http://127.0.0.1:5173`；接口文档：`http://127.0.0.1:8000/docs`；
健康接口：`http://127.0.0.1:8000/api/v1/health`。网页 /api 通过 Vite 代理到后端。

后端开发可使用 `.\scripts\start-backend.ps1 -Reload`。终端中按 Ctrl+C 停止各自服务。
若 PowerShell 执行策略阻止本地脚本，可在当前调用使用
`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1`，其他脚本同理。

## 账户操作

1. 启动后打开网页，未登录会进入登录页；首次使用点击“创建账号”。
2. 输入用户名和密码，显示名称选填。用户名 3–32 位英文字母、数字或下划线，密码 8–128 个字符。
3. 注册成功直接进入首页，并自动创建“我的资料”；已有账号直接登录。刷新网页会恢复未过期的登录。
4. 右上角账户菜单可修改显示名称或退出。退出回到登录页，个人资料仍保留。
5. “我的知识库”显示本人个人库与只读课程库，点击卡片查看基础信息；下方可搜索、展开八章课程目录。个人库可保存资料、查看状态、预览、下载、重试及删除；课程库提供只读资料及来源许可。

账户实现保持简单，密码用 pwdlib 保存标准哈希；登录通过服务端会话 Cookie 保持，默认 7 天，不要求邮箱或验证码。
CAPSTONE_SESSION_DAYS 可设置为 1–30 天；已有 .env 未添加该配置时使用默认值。

## 资料操作与当前限制

在“我的知识库”选择个人库，上传文本型 PDF、TXT 或 Markdown，默认最多 20 MiB。文件保存后可预览或下载；文本支持 UTF-8、GB18030，扫描与加密 PDF 暂不支持。处理完成前不参与学习检索。页面保留失败原因与重试入口，删除前确认，删除后文件不可读取并后台清理。历史学习记录保留。

课程导入命令可重复执行，校验文件摘要、知识点和许可，仅登记资料，不伪造向量。后台启动后执行队列；未接通 Embedding 时文件保留并显示处理失败。具体调用协议和服务后续确认，目前只有统一服务接口，尚不能通过环境变量配置真实模型。接通真实服务后，维护者可执行 `uv run --locked python -X utf8 -m capstone.import_course --retry-failed` 重试课程资料；学生在个人库点击重试。

## 学习对话

首页点击“开始学习”，在会话列表新建学习，默认使用课程＋我的资料，可选择仅课程或仅个人。就绪资料列表的“学习这份资料”携带文档与知识点建立限定范围会话。会话设置可改名、调整范围、归档和恢复。

接通模型后可提问或连续追问，选择直接讲解、提示或例子；回答中的 `[资料1]` 可在当前页打开实际检索片段、页码或行位置。数组 `a[0]` 不作为引用。删除资料后显示历史片段和来源已删除，原文件入口关闭；没有命中依据时明确资料不足。

可取消正在生成的回答，重试最近失败或取消的问题；刷新恢复会话及正在生成的流，断线时“重新连接”不重复提交。草稿按账号和会话保存在当前浏览器会话中，退出清理；服务端只保存已发送问题。会话可分页，长记录支持查看更早消息。总结和知识点练习衔接随后续模块加入。

当前具体模型调用仍未接通：创建会话和查看历史可用，提问明确提示服务未配置并保留输入，不生成演示回答。检索和流式测试使用显式模型替身及真实 Qdrant，不代表模型效果验收。实现参照 [Qdrant 过滤](https://qdrant.tech/documentation/search/filtering/) 和 [FastAPI 流式响应](https://fastapi.tiangolo.com/advanced/stream-data/)。

## 检查

```powershell
.\scripts\check.ps1
```

包含后端 Ruff 检查与格式检查、接口及存储测试、迁移差异检查，以及网页状态测试、TypeScript 检查与生产构建。
测试使用临时数据目录，验证 SQLite 配置、Qdrant 重启持久化和锁释放、存储故障的健康状态。
同时验证九表迁移、关键约束、事务回滚、UTC 时间和课程初始化；测试不会降级或清空实际运行数据库。
账户测试覆盖自动建库、重复用户名、错误密码、注册失败回滚、会话过期与退出、来源及请求凭据校验。
知识库测试覆盖双账号隔离、课程库只读信息、目录与分页；网页状态测试验证换账号、快速切库、登录失效及网络错误。网页状态测试使用 Node，不启动浏览器。
文档测试使用真实文件、解析器和 Qdrant，Embedding 测试替身仅用于测试；覆盖重复文件、重启恢复、处理失败、清理重试、课程导入和私人资料隔离，不等同于真实模型验收。
本阶段不运行浏览器自动检查，也不开发手机端适配。

## 目录

```text
backend/
  src/capstone/     FastAPI、配置、路由和数据库基础
  migrations/      Alembic 框架及后续业务迁移
  tests/           存储、迁移、业务约束与课程初始化测试
frontend/
  src/             桌面导航、页面入口和 API 调用
scripts/           Windows 启动与检查入口
content/           可合法使用的公开课程笔记、固定题库、评估问题与来源许可
data/              本地 SQLite、原始资料和向量；实际数据不提交
docs/              项目规划、设计、自检和开发说明
```

设计依据：[项目规划](docs/项目规划.md)、[设计索引](docs/design/README.md)、
[开发指南](docs/开发指南.md)、[下一阶段实施规划](docs/下一阶段实施规划.md)。账户、知识库与资料管理基础已完成，接下来接通真实模型，完成练习、错题和报告；首版整体建议 16 个业务实体。旧 docs/design/schema.sql 是历史草案，不作为当前初始化脚本执行。
练习采用可切换的题库 / 实时 AI 出题方式，AI 出题不限定算法模板或程序验算能力。

实现结构参考 [FastAPI 模块组织](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、
[Vite 开始指南](https://vite.dev/guide/)、
[Qdrant 本地模式](https://github.com/qdrant/qdrant-client#local-mode) 和
[Alembic 迁移指南](https://alembic.sqlalchemy.org/en/latest/tutorial.html)。
