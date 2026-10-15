# 初版公开课程内容

整理日期：2026-10-14。这里保存可随项目维护的课程内容，不存放用户上传的私人文件。

- course/ 下有线性表、栈与队列、二叉树三个中文学习笔记。笔记按来源整理并加入本项目例子、教学约定，非逐字翻译。
- manifest.json 记录每份笔记的路径、知识点、文本 SHA-256 及来源；摘要按 UTF-8、LF 换行计算，兼容 Windows 检出后的换行差异。sources.json 保存作者、许可和原始链接。
- question-bank.json 是 15 道固定题目的首批数据，每个初始主题 5 道；题干与选项为项目编写，知识依据可追溯到笔记和原始来源。
- rag-evaluation.json 是 30 个固定评估问题，其中 24 个有支持依据，6 个要求识别现有资料不足；没有填入模型实测结果。

在 backend 执行 `uv run --locked python -X utf8 -m capstone.import_course`，将三个笔记及来源许可登记到课程库，重复内容不重复写入。先执行迁移与 capstone.seed。后端处理队列，真实 Embedding 与向量写入成功后才为 ready；未配置时保留文件并失败。接通服务后可加 `--retry-failed` 重处理既有失败资料。命令不另开 Qdrant 客户端，可与单进程后端共用队列。题库可通过 `uv run --locked python -X utf8 -m capstone.manage_questions import` 导入并用于练习，不依赖模型；重复包不重复写入，修改后的题目生成新记录，原分发快照保留。评估问题尚未实际调用模型。

## 来源与许可

Open Data Structures（Pat Morin）的 [项目主页](https://opendatastructures.org/) 明确采用 [CC BY 2.5 CA](https://creativecommons.org/licenses/by/2.5/ca/)，允许复制与改编并要求署名。笔记保留标题、作者、许可链接并标明整理与补充；适用部分沿用该许可。

二叉树遍历依据 [OpenDSA 的源模块](https://github.com/OpenDSA/OpenDSA/blob/master/RST/en/Binary/BinaryTreeTraversal.rst)，作者 Cliff Shaffer；模块标明 Copyright (c) 2012-2020 by the OpenDSA Project Contributors，采用 MIT 许可。完整通知保存在 [许可文件](licenses/opendsa-MIT.txt)。

外部来源为知识依据，不表示原作者审阅了项目例子或题库。题目核对依据、条件与确定性计算记录在 verification 字段；实时 AI 题仍采用独立来源标记和参考答案，不放入该核验题库。

## 内容维护

修改题目时重新核对题干、选项、答案、解析与来源。已分发题目的历史快照不得被源文件修改覆盖；后续入库时保留此边界。
后端 tests/test_content.py 检查文件摘要、知识点与来源关系、题目结构及确定性操作题答案。它不调用模型，也不宣称 RAG 效果已验证。

## 推荐资源

resources.json 登记 6 条已核对的 Open Data Structures 资源外链，记录课程章节、维护者评定难度、语言、作者、许可与核对日期（2026-10-15）。仅保存链接及项目编写的阅读简介，不下载网页正文。难度是阅读建议，不是原作者的难度认证。维护者在 backend 执行 `uv run --locked python -X utf8 -m capstone.manage_resources`，或使用 `--file` 指定同结构 JSON；整包校验后事务导入，按 code 更新，重复不新增；is_active=false 停用。运行前需迁移与初始化目录。页面只显示启用记录，外部站点今后可能变更，需要维护者复核链接；不是每次展示都重新联网检查。

固定问题现可由 `capstone.evaluate_rag` 评估命令读取；默认 development 20 题，holdout 10 题需明确选择。命令不会将 rubric 或 expected_support 提供给模型，结果中的引用来自实际消息记录；位置匹配不替代人工质量判断。当前未接通真实模型，尚无实测结果，详见 [评估说明](../docs/RAG评估说明.md)。
