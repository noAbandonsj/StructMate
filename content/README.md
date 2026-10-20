# 内容维护说明

系统不自带课程学习资料和推荐外链。课程资料由管理员登录后，在侧栏“课程资料管理”上传、关联知识点、填写来源与许可，并处理为可用于学习的状态；普通用户可阅读已就绪课程资料，也可维护自己的个人资料。

升级迁移 0010 会移除旧版 6 条预置外链及 3 份自带课程笔记。原文件与向量由既有删除队列清理，历史对话及引用快照保留；管理员上传的课程资料与用户个人资料不受影响。

本目录保留 question-bank.json 的 15 道核验练习题、rag-evaluation.json 的 30 个开发评估问题，以及 sources.json 和 licenses/ 的出处与许可记录。练习题可通过 `uv run --locked python -X utf8 -m capstone.manage_questions import` 导入；已分发题目的历史快照不因源文件更改而覆盖。它们不会作为课程文档或外链加入推荐。

旧课程笔记、清单及外链样例已移到 backend/tests/fixtures/，仅供自动化测试和隔离 RAG 评估使用，不导入日常学习数据库。笔记保留 Open Data Structures 的 CC BY 2.5 CA 署名与 OpenDSA 的 MIT 许可。评估器仍会在一次性数据库中加载测试语料，不更改管理员维护的课程库。

本机批量导入工具只接受明确指定的内容包：`capstone.import_course --directory <内容包目录>` 或 `capstone.manage_resources --file <资源JSON路径>`，没有默认内容包。日常课程维护请使用管理员页面。管理员步骤见 [维护说明](../docs/管理员课程资料维护说明.md)。
