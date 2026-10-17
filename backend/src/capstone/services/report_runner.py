import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import select

from capstone.core.errors import ApiError
from capstone.db.models import LearningReport, utc_now
from capstone.db.session import write_transaction


class ReportRunner:
    def __init__(self, factory, generation):
        self.factory, self.generation = factory, generation
        self.stopping = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="learning-report")

    def start(self):
        with self.factory() as session, write_transaction(session):
            for report in session.scalars(
                select(LearningReport).where(LearningReport.status == "generating")
            ):
                report.status, report.error_code = "failed", "REPORT_INTERRUPTED"
                report.error_message = "上次文字生成被中断，原统计快照保留，请主动重新生成。"

    def stop(self):
        self.stopping.set()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, identifier):
        self.executor.submit(self._run, identifier)

    def _run(self, identifier):
        try:
            with self.factory() as session:
                report = session.get(LearningReport, identifier)
                if report.status != "generating" or self.stopping.is_set():
                    return
                snapshot = report.snapshot
            prompt = [
                {
                    "role": "system",
                    "content": "你是数据结构学习助手。只根据给定的固定统计快照，"
                    "用中文 Markdown 写学习报告，"
                    "说明本日期范围的学习活动、作答表现、待巩固内容和下一步建议。"
                    "统计包含核验题库及 AI 题，AI 依保存参考答案计分。"
                    "不新增或改写数字、日期、题目或链接，不估算学习时长。"
                    "独立新题少于 5 道必须说证据不足，讨论或刷原题不代表掌握。"
                    "日期范围统计与不限日期的当前待复习数量要分别说明，"
                    "不将短期表现当成长期掌握程度。"
                    "completed_answers 是有效答疑次数，不含 insufficient_materials 资料不足回复；"
                    "资料不足只表示未找到依据，不代表完成了知识讲解。"
                    "这是历史快照，后续记录或题目核验不会自动修改它。",
                },
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
            ]
            content = ""
            stream = self.generation.stream(prompt, self.stopping)
            try:
                for delta in stream:
                    if self.stopping.is_set():
                        return
                    if not isinstance(delta, str) or len(content) + len(delta) > 16000:
                        raise ValueError("Invalid report output")
                    content += delta
            finally:
                if close := getattr(stream, "close", None):
                    close()
            if not content.strip():
                raise ValueError("Empty report")
            with self.factory() as session, write_transaction(session):
                report = session.get(LearningReport, identifier)
                if report.status == "generating" and not self.stopping.is_set():
                    report.content, report.status, report.generated_at = (
                        content.strip(),
                        "completed",
                        utc_now(),
                    )
        except Exception as error:
            if self.stopping.is_set():
                return
            with self.factory() as session, write_transaction(session):
                report = session.get(LearningReport, identifier)
                if report.status == "generating":
                    report.status = "failed"
                    report.error_code = (
                        error.detail["code"] if isinstance(error, ApiError) else "REPORT_FAILED"
                    )
                    report.error_message = (
                        error.detail["message"]
                        if isinstance(error, ApiError)
                        else "文字报告生成失败，原统计快照保留。"
                    )
