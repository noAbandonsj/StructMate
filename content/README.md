# 初版公开课程内容

整理日期：2026-10-14。这里保存可随项目维护的课程内容，不存放用户上传的私人文件。

- course/ 下有线性表、栈与队列、二叉树三个中文学习笔记。笔记按来源整理并加入本项目例子、教学约定，非逐字翻译。
- manifest.json 记录每份笔记的路径、知识点、文本 SHA-256 及来源；摘要按 UTF-8、LF 换行计算，兼容 Windows 检出后的换行差异。sources.json 保存作者、许可和原始链接。
- question-bank.json 是 15 道固定题目的首批数据，每个初始主题 5 道；题干与选项为项目编写，知识依据可追溯到笔记和原始来源。
- rag-evaluation.json 是 30 个固定评估问题，其中 24 个有支持依据，6 个要求识别现有资料不足；没有填入模型实测结果。

这批内容尚未导入业务库或向量集合，也未作为网页可用资料发布。后续资料导入和题库初始化复用这些文件，不能因源文件存在就把文档标为 ready。

## 来源与许可

Open Data Structures（Pat Morin）的 [项目主页](https://opendatastructures.org/) 明确采用 [CC BY 2.5 CA](https://creativecommons.org/licenses/by/2.5/ca/)，允许复制与改编并要求署名。笔记保留标题、作者、许可链接并标明整理与补充；适用部分沿用该许可。

二叉树遍历依据 [OpenDSA 的源模块](https://github.com/OpenDSA/OpenDSA/blob/master/RST/en/Binary/BinaryTreeTraversal.rst)，作者 Cliff Shaffer；模块标明 Copyright (c) 2012-2020 by the OpenDSA Project Contributors，采用 MIT 许可。完整通知保存在 [许可文件](licenses/opendsa-MIT.txt)。

外部来源为知识依据，不表示原作者审阅了项目例子或题库。题目核对依据、条件与确定性计算记录在 verification 字段；实时 AI 题仍采用独立来源标记和参考答案，不放入该核验题库。

## 内容维护

修改题目时重新核对题干、选项、答案、解析与来源。已分发题目的历史快照不得被源文件修改覆盖；后续入库时保留此边界。
后端 tests/test_content.py 检查文件摘要、知识点与来源关系、题目结构及确定性操作题答案。它不调用模型，也不宣称 RAG 效果已验证。
