"""Run the fixed corpus evaluation in an isolated app, using the configured real services.

Requires the development dependencies (TestClient). Test services are accepted only
by the Python entry point and make the entire result explicitly test_only.
"""

import argparse
import json
import re
import time
from hashlib import sha256
from math import isfinite
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from capstone import __version__
from capstone.core.settings import REPOSITORY_ROOT, Settings
from capstone.db.models import Document, utc_now
from capstone.import_course import import_course_data
from capstone.main import create_app
from capstone.seed import seed_course_data

CONTENT = REPOSITORY_ROOT / "content"
ORIGIN = "https://evaluation.local"


class EvaluationUnavailable(RuntimeError):
    pass


def load_cases(split="development"):
    if split not in {"development", "holdout", "all"}:
        raise ValueError("请选择 development、holdout 或 all")
    cases = json.loads((CONTENT / "rag-evaluation.json").read_text(encoding="utf-8"))
    return [item for item in cases if split == "all" or item["split"] == split]


def checked(response):
    if not 200 <= response.status_code < 300:
        # Never copy response bodies, credentials or transport exceptions to evidence.
        raise RuntimeError(f"评估业务接口返回 HTTP {response.status_code}")
    return response.json()


def plain_answer(generation, question):
    started = time.monotonic()
    content = ""
    try:
        stream = generation.stream(
            [
                {
                    "role": "system",
                    "content": "你是数据结构课程学习助手。用中文清楚回答，"
                    "按概念、例子、算法步骤组织；不确定时明确说明，不编造资料引用。",
                },
                {"role": "user", "content": question},
            ],
            Event(),
        )
        try:
            for delta in stream:
                if not isinstance(delta, str) or len(content) + len(delta) > 40000:
                    raise ValueError("Invalid evaluation output")
                content += delta
        finally:
            if close := getattr(stream, "close", None):
                close()
        if not content.strip():
            raise ValueError("Empty evaluation output")
        result = {"status": "completed", "content": content, "error_code": None}
    except Exception:
        result = {"status": "failed", "content": "", "error_code": "BASELINE_FAILED"}
    return {**result, "elapsed_seconds": round(time.monotonic() - started, 3)}


def rag_answer(client, headers, case, wait_seconds):
    started = time.monotonic()
    try:
        conversation = checked(
            client.post(
                "/api/v1/conversations",
                headers=headers,
                json={
                    "title": "评估 " + case["id"],
                    "scope": "course",
                },
            )
        )
        queued = checked(
            client.post(
                f"/api/v1/conversations/{conversation['id']}/messages",
                headers=headers,
                json={"client_request_id": uuid4().hex, "content": case["question"]},
            )
        )
        deadline = time.monotonic() + wait_seconds
        while True:
            records = checked(client.get(f"/api/v1/conversations/{conversation['id']}/messages"))[
                "items"
            ]
            answer = next(item for item in records if item["id"] == queued["assistant_message_id"])
            if answer["status"] != "generating":
                break
            if time.monotonic() >= deadline:
                client.post(f"/api/v1/messages/{answer['id']}/cancel", headers=headers)
                raise TimeoutError
            time.sleep(0.05)
        error_code = answer["error_code"]
        if error_code and not re.fullmatch(r"[A-Z0-9_]{1,64}", error_code):
            error_code = "RAG_FAILED"
        result = {
            "status": answer["status"],
            "content": answer["content"],
            "citations": answer["citations"],
            "error_code": error_code,
        }
    except Exception:
        result = {
            "status": "failed",
            "content": "",
            "citations": [],
            "error_code": "RAG_EVALUATION_FAILED",
        }
    return {**result, "elapsed_seconds": round(time.monotonic() - started, 3)}


def location_checks(case, rag):
    matches = [
        {
            **expected,
            "matched": any(
                (citation.get("source_info") or {}).get("content_code") == expected["document_code"]
                and expected["heading"] in (citation.get("heading") or "")
                for citation in rag["citations"]
            ),
        }
        for expected in case["expected_support"]
    ]
    cited = [int(value) for value in re.findall(r"\[资料(\d+)\]", rag["content"])]
    known = {citation["number"] for citation in rag["citations"]}
    return {
        "expected_location_matches": matches,
        "citation_tokens": cited,
        "unknown_citation_tokens": [number for number in cited if number not in known],
    }


def run_evaluation(
    settings,
    cases,
    *,
    wait_seconds=180,
    test_only_embedding=None,
    test_only_generation=None,
    progress=None,
):
    """Use a disposable DB, files and Qdrant; never create learning records in the user's DB."""
    if not cases or not isfinite(wait_seconds) or not 0 < wait_seconds <= 600:
        raise ValueError("评估集不能为空，等待秒数须大于 0 且不超过 600")
    work_root = (settings.data_dir / "evaluations").resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    started_at = utc_now().isoformat()
    with TemporaryDirectory(prefix="rag-runtime-", dir=work_root) as directory:
        runtime = Path(directory).resolve()
        assert runtime.parent == work_root
        runtime_settings = settings.model_copy(
            update={"data_dir": runtime, "cors_origins": [ORIGIN]}
        )
        migration = Config(str(REPOSITORY_ROOT / "backend/alembic.ini"))
        migration.attributes["settings"] = runtime_settings
        command.upgrade(migration, "head")
        app = create_app(
            runtime_settings,
            embedding_service=test_only_embedding,
            generation_service=test_only_generation,
        )
        with TestClient(app, base_url=ORIGIN) as client:
            if (
                not app.state.embedding_service.available
                or not app.state.generation_service.available
            ):
                raise EvaluationUnavailable(
                    "生成或 Embedding 服务配置不完整，请填写地址、模型和密钥；"
                    "评估未执行，不生成实测结果。"
                )
            seed_course_data(app.state.engine)
            import_course_data(app.state.engine, runtime_settings)
            app.state.document_worker.notify()
            deadline = time.monotonic() + wait_seconds
            while True:
                with app.state.session_factory() as session:
                    documents = session.scalars(select(Document)).all()
                    if any(item.status == "failed" for item in documents):
                        raise EvaluationUnavailable(
                            "评估课程资料处理失败，未开始问答；请检查实际向量服务。"
                        )
                    if len(documents) == 3 and all(item.status == "ready" for item in documents):
                        corpus = [
                            {
                                "content_code": item.source_info["content_code"],
                                "content_hash": item.content_hash,
                                "embedding_fingerprint": item.embedding_fingerprint,
                                "embedding_dimension": item.embedding_dimension,
                            }
                            for item in documents
                        ]
                        break
                if time.monotonic() >= deadline:
                    raise EvaluationUnavailable("评估课程资料未在等待时间内就绪，未开始问答。")
                time.sleep(0.05)
            account = checked(
                client.post(
                    "/api/v1/auth/register",
                    headers={"Origin": ORIGIN},
                    json={"username": "rag_evaluation", "password": token_urlsafe(24)},
                )
            )
            headers = {"Origin": ORIGIN, "X-CSRF-Token": account["csrf_token"]}
            results = []
            for index, case in enumerate(cases, 1):
                baseline = plain_answer(app.state.generation_service, case["question"])
                rag = rag_answer(client, headers, case, wait_seconds)
                results.append(
                    {
                        "id": case["id"],
                        "split": case["split"],
                        "question": case["question"],
                        "expectation": case["expectation"],
                        "answer_rubric": case["answer_rubric"],
                        "baseline": baseline,
                        "rag": rag,
                        "checks": location_checks(case, rag),
                        "review": {
                            "baseline_factual_correct": None,
                            "rag_factual_correct": None,
                            "rag_citations_support_claims": None,
                            "rag_handles_insufficient_evidence": None,
                            "notes": "",
                        },
                    }
                )
                if progress:
                    progress(index, len(cases), case["id"])
            client.post("/api/v1/auth/logout", headers=headers)
    # The app has stopped and released Qdrant before TemporaryDirectory removes runtime data.
    completed = sum(
        item["baseline"]["status"] == item["rag"]["status"] == "completed" for item in results
    )
    return {
        "schema_version": 1,
        "app_version": __version__,
        "execution_kind": "test_only"
        if test_only_embedding is not None or test_only_generation is not None
        else "configured_services",
        "status": "awaiting_review" if completed == len(results) else "partial",
        "started_at": started_at,
        "finished_at": utc_now().isoformat(),
        "generation_model": settings.generation_model,
        "embedding_model": settings.embedding_model,
        "retrieval_min_score": settings.retrieval_min_score,
        "dataset_sha256": sha256((CONTENT / "rag-evaluation.json").read_bytes()).hexdigest(),
        "corpus": corpus,
        "case_count": len(results),
        "completed_pairs": completed,
        "reviewed_cases": 0,
        "note": "位置匹配只检查实际引用的文档与标题，不证明答案正确或引用支持结论。"
        "资料不足问题和答案质量须人工核对，失败不计为正确。测试替身结果不可用作真实模型验收。",
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="隔离运行普通回答与纯向量 RAG 评估，需要真实模型及开发依赖"
    )
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--wait-seconds", type=float, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings()
    output = args.output or settings.data_dir / "evaluations" / (
        "rag-" + uuid4().hex[:12] + ".json"
    )
    if output.exists():
        parser.error("输出文件已存在，请指定新路径，避免覆盖已有实测记录")
    try:
        result = run_evaluation(
            settings,
            load_cases(args.split),
            wait_seconds=args.wait_seconds,
            progress=lambda done, total, identifier: print(
                f"[{done}/{total}] {identifier}", flush=True
            ),
        )
    except (EvaluationUnavailable, ValueError) as error:
        print(str(error))
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(
        f"已保存 {result['case_count']} 题，完成 {result['completed_pairs']} 对回答；"
        "质量核对尚未完成。"
    )
    print(f"结果：{output.resolve()}")
    return 0 if result["status"] == "awaiting_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
