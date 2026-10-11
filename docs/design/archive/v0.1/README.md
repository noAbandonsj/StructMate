# 详细设计索引

更新：2026-10-10。后端选型：FastAPI + SQLite + Qdrant 本地持久化模式。当前完成设计与模拟交互，真实后端、模型和文档处理尚未实现。

| 文件 | 内容 |
| --- | --- |
| [页面设计.md](页面设计.md) | 六个页面、路由、线框、异常状态、当前原型范围和实施顺序 |
| [数据库设计.md](数据库设计.md) | 两组 ER 图、字段职责、权限、版本、幂等和统计口径 |
| [schema.sql](schema.sql) | 空 SQLite 数据库可执行的建表设计，26 张表及 learning_stats 视图 |
| [接口设计.md](接口设计.md) | /api/v1 接口清单、鉴权、异步任务、SSE、练习和报告契约 |
| [verify_design.py](verify_design.py) | 内存数据库约束检查，不创建实际业务数据库 |
| [verify_wireframe.cjs](verify_wireframe.cjs) | 可点击线框的浏览器交互与响应布局检查 |
| [qa/](qa/) | 交互检查结果与浅色、深色、手机宽度截图 |

可点击线框在本次对话中展示。所有作答与上传均为本地模拟，模拟记录不进入未来业务数据库。

## 验证方法

数据库检查：

```powershell
python .\docs\design\verify_design.py
```

浏览器检查需要现有 Playwright 包与浏览器，脚本不会安装或下载：

```text
node docs/design/verify_wireframe.cjs <playwright-module-path> <browser-exe> <rendered-preview-html> <qa-output-directory>
```

线框预览通过 visualize 的 render.py 将对话源片段包装为本地预览；重新渲染现有预览时添加 `--force`。内存验证只覆盖数据库约束；浏览器验证只覆盖模拟页面，不代表真实 RAG 或模型接入成功。

## 实施入口

先建立 `backend/`，实现配置、健康接口、数据库迁移、认证、知识库与上传处理。保留生成模型和 Embedding 适配接口，模型凭据仅放后端环境配置。首条演示流程为登录、上传文本资料、等待入库、提问、查看真实引用。
