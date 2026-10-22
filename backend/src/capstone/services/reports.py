from datetime import date

from sqlalchemy import select

from capstone.core.errors import ApiError
from capstone.db.models import LearningReport, utc_now
from capstone.db.session import write_transaction
from capstone.services.learning_stats import learning_stats
from capstone.services.practice import request_digest


def get_report(session, identifier, user_id):
    report = session.scalar(
        select(LearningReport).where(
            LearningReport.id == identifier, LearningReport.user_id == user_id
        )
    )
    if report is None:
        raise ApiError(404, "REPORT_NOT_FOUND", "报告不存在或不可访问。")
    return report


def create_report(session, user_id, data, available):
    signature = {
        "from_date": data.from_date.isoformat() if data.from_date else None,
        "to_date": data.to_date.isoformat() if data.to_date else None,
    }
    digest = request_digest(signature)
    with write_transaction(session):
        previous = session.scalar(
            select(LearningReport).where(
                LearningReport.user_id == user_id,
                LearningReport.request_id == data.client_request_id,
            )
        )
        if previous:
            if previous.request_hash != digest:
                raise ApiError(409, "REQUEST_CONFLICT", "请求标识已用于不同日期范围。")
            return previous, False
        cutoff = utc_now()
        snapshot = learning_stats(session, user_id, data.from_date, data.to_date, cutoff)
        report = LearningReport(
            user_id=user_id,
            from_date=date.fromisoformat(snapshot["from_date"]),
            to_date=date.fromisoformat(snapshot["to_date"]),
            cutoff_at=cutoff,
            snapshot=snapshot,
            request_id=data.client_request_id,
            request_hash=digest,
        )
        if not available:
            report.status, report.error_code = "failed", "GENERATION_NOT_CONFIGURED"
            report.error_message = (
                "生成模型尚未接通；真实统计快照已保存，可查看和导出，文字报告未生成。"
            )
        session.add(report)
    return report, available


def report_info(report):
    return {
        "id": report.id,
        "client_request_id": report.request_id,
        "from_date": report.from_date,
        "to_date": report.to_date,
        "cutoff_at": report.cutoff_at,
        "created_at": report.created_at,
        "generated_at": report.generated_at,
        "status": report.status,
        "snapshot": report.snapshot,
        "content": report.content,
        "error_code": report.error_code,
        "error_message": report.error_message,
    }


def report_markdown(report):
    data = report.snapshot
    independent = data["categories"]["first_independent"]

    def percent(value):
        return "未评估" if value is None else f"{value * 100:.1f}%"

    labels = {
        "first_independent": "首次独立新题",
        "first_hinted": "首次提示作答",
        "repeat": "重复练习",
        "review": "错题复习",
    }
    lines = [
        "# 学习报告",
        "",
        f"日期范围：{report.from_date} 至 {report.to_date}（Asia/Shanghai，两端包含）",
        f"统计截止：{report.cutoff_at.isoformat()}",
        f"文字生成时间：{report.generated_at.isoformat() if report.generated_at else '尚未生成'}",
        "",
        "## 真实统计快照",
        "",
        f"- 有效作答：{data['attempts']['count']} 次",
        f"- 首次独立新题：{independent['count']} 道，正确率 {percent(independent['accuracy'])}",
        f"- 范围内新增错题：{data['wrong_questions']['new_in_range']} 道",
        f"- 截止时当前待复习：{data['wrong_questions']['current_pending']} 道（不限日期范围）",
        f"- 提问：{data['learning']['asked_questions']} 次；"
        f"有效答疑：{data['learning']['completed_answers']} 次；"
        f"资料不足 {data['learning']['insufficient_materials']} 次",
        f"- 实际记录活跃天数：{data['learning']['active_days']} 天；未估算学习时长",
        "",
        "| 作答类别 | 次数 | 答对 | 正确率 |",
        "| --- | --- | --- | --- |",
    ]
    for category, label in labels.items():
        item = data["categories"][category]
        lines.append(
            f"| {label} | {item['count']} | {item['correct_count']} | {percent(item['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## 章节统计",
            "",
            "| 章节 | 作答 | 独立新题 | 独立正确率 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for chapter in data["chapters"]:
        lines.append(
            f"| {chapter['name']} | {chapter['attempts']['count']} | "
            f"{chapter['independent']['count']} | "
            f"{percent(chapter['independent']['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## 文字说明",
            "",
            report.content or "文字报告尚未生成；以上为真实记录的统计快照。",
            "",
            "## 统计口径",
            "",
            data["basis"],
            "独立新题少于 5 道时证据不足。报告保留生成时快照，"
            "后续作答或题目停用不会改写本报告，可重新生成查看新口径。",
            "",
        ]
    )
    return "\n".join(lines)
