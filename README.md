# 知序 · 数据结构课程学习助手

基于 RAG 的桌面网页项目，后端使用 Python / FastAPI，前端使用 Vue 3、TypeScript 和 Vite。
业务数据保存到 SQLite，文档向量使用 Qdrant 本地持久化模式。

目前完成基础工程初始化：网页导航、服务连接状态、后端健康接口、本地存储连接、迁移框架、开发脚本与依赖锁文件。
账户与知识库的数据基础已完成：四张业务表、首个迁移和课程目录初始化。
注册、登录、退出、刷新恢复登录、显示名称修改及桌面账户页面已实现，注册时自动创建个人知识库。
知识库列表、详情和课程目录页面已接入真实数据，并检查个人库访问权限。
文档处理、真实答疑、题目、错题和报告尚未实现；学习入口明确显示准备状态。

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
Pop-Location

Push-Location frontend
pnpm.cmd install --frozen-lockfile
Pop-Location
```

已有 .env 时保留原文件并按 [.env.example](.env.example) 补充配置。本轮初始化已在本机安装依赖，无须配置模型密钥。
当前迁移 0001 创建用户、会话、知识库和知识点四张业务表，其余表随功能加入。
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
5. “我的知识库”显示本人个人库与只读课程库，点击卡片查看基础信息；下方可搜索、展开八章课程目录。资料上传与课程文件导入将在后续开放。

账户实现保持简单，密码用 pwdlib 保存标准哈希；登录通过服务端会话 Cookie 保持，默认 7 天，不要求邮箱或验证码。
CAPSTONE_SESSION_DAYS 可设置为 1–30 天；已有 .env 未添加该配置时使用默认值。

## 检查

```powershell
.\scripts\check.ps1
```

包含后端 Ruff 检查与格式检查、接口及存储测试、迁移差异检查，以及网页状态测试、TypeScript 检查与生产构建。
测试使用临时数据目录，验证 SQLite 配置、Qdrant 重启持久化和锁释放、存储故障的健康状态。
同时验证四表迁移、关键约束、事务回滚、UTC 时间和课程初始化；测试不会降级或清空实际运行数据库。
账户测试覆盖自动建库、重复用户名、错误密码、注册失败回滚、会话过期与退出、来源及请求凭据校验。
知识库测试覆盖双账号隔离、课程库只读信息、目录与分页；网页状态测试验证换账号、快速切库、登录失效及网络错误。网页状态测试使用 Node，不启动浏览器。
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
data/              本地 SQLite、原始资料和向量；实际数据不提交
docs/              项目规划、设计、自检和开发说明
```

设计依据：[项目规划](docs/项目规划.md)、[设计索引](docs/design/README.md)、
[开发指南](docs/开发指南.md)、[下一阶段实施规划](docs/下一阶段实施规划.md)。账户与知识库基础已完成，接下来实现资料入库与 RAG；首版整体建议 16 个业务实体。旧 docs/design/schema.sql 是历史草案，不作为当前初始化脚本执行。
练习采用可切换的题库 / 实时 AI 出题方式，AI 出题不限定算法模板或程序验算能力。

实现结构参考 [FastAPI 模块组织](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、
[Vite 开始指南](https://vite.dev/guide/)、
[Qdrant 本地模式](https://github.com/qdrant/qdrant-client#local-mode) 和
[Alembic 迁移指南](https://alembic.sqlalchemy.org/en/latest/tutorial.html)。
