import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_conversations import TestGeneration as RecordedGeneration
from test_documents import TestEmbedding

from capstone.core.settings import Settings
from capstone.db.models import User
from capstone.evaluate_rag import EvaluationUnavailable, load_cases, location_checks, run_evaluation


def test_fixed_evaluation_splits_keep_holdout_out_of_default_run():
    development, holdout, all_cases = load_cases(), load_cases("holdout"), load_cases("all")
    assert (len(development), len(holdout), len(all_cases)) == (20, 10, 30)
    assert not {item["id"] for item in development} & {item["id"] for item in holdout}
    assert sum(item["expectation"] == "insufficient" for item in all_cases) == 6
    with pytest.raises(ValueError):
        load_cases("unknown")


def test_unconfigured_evaluation_has_no_results_or_learning_records(migrated_database, tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    with pytest.raises(EvaluationUnavailable, match="评估未执行"):
        run_evaluation(settings, load_cases()[:1], wait_seconds=5)
    assert list((tmp_path / "evaluations").iterdir()) == []
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_evaluator_uses_real_pipeline_and_labels_injected_services_test_only(
    migrated_database, tmp_path
):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        generation_base_url="https://generation.example.test",
        generation_model="test-model",
        generation_api_key="private-evaluation-key",
    )
    generation = RecordedGeneration()
    cases = load_cases()[:2]
    cases[0]["answer_rubric"] = ["DO_NOT_SEND_THIS_RUBRIC_TO_GENERATION"]
    report = run_evaluation(
        settings,
        cases,
        wait_seconds=6,
        test_only_embedding=TestEmbedding(),
        test_only_generation=generation,
    )
    assert report["execution_kind"] == "test_only"
    assert report["status"] == "awaiting_review" and report["completed_pairs"] == 2
    assert report["reviewed_cases"] == 0 and report["case_count"] == 2
    assert len(report["corpus"]) == 3 and all(
        item["embedding_dimension"] == 3 for item in report["corpus"]
    )
    assert len(generation.prompts) == 4
    assert all(
        prompt[-1]["content"] in {case["question"] for case in cases}
        for prompt in generation.prompts
    )
    assert "DO_NOT_SEND_THIS_RUBRIC" not in json.dumps(generation.prompts)
    assert "private-evaluation-key" not in json.dumps(report)
    assert "generation.example.test" not in json.dumps(report)
    for case in report["cases"]:
        assert case["rag"]["citations"]
        assert all(citation["source_info"]["content_code"] for citation in case["rag"]["citations"])
        assert case["review"]["rag_factual_correct"] is None
        assert case["review"]["rag_citations_support_claims"] is None
    assert list((tmp_path / "evaluations").iterdir()) == []
    with Session(migrated_database) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("failed_component", ["generation", "embedding"])
def test_failed_calls_never_become_successful_evaluation_results(
    migrated_database, tmp_path, failed_component
):
    class FailedGeneration(RecordedGeneration):
        def stream(self, messages, cancelled):
            raise RuntimeError("private-provider-test-key")
            yield

    class FailedEmbedding(TestEmbedding):
        def embed(self, texts):
            raise RuntimeError("private-provider-test-key")

    settings = Settings(_env_file=None, data_dir=tmp_path)
    generation = FailedGeneration() if failed_component == "generation" else RecordedGeneration()
    embedding = FailedEmbedding() if failed_component == "embedding" else TestEmbedding()
    if failed_component == "embedding":
        with pytest.raises(EvaluationUnavailable) as error:
            run_evaluation(
                settings,
                load_cases()[:1],
                wait_seconds=5,
                test_only_embedding=embedding,
                test_only_generation=generation,
            )
        assert "private-provider-test-key" not in str(error.value)
        assert not generation.prompts
    else:
        report = run_evaluation(
            settings,
            load_cases()[:1],
            wait_seconds=5,
            test_only_embedding=embedding,
            test_only_generation=generation,
        )
        assert report["status"] == "partial" and report["completed_pairs"] == 0
        assert report["cases"][0]["baseline"]["status"] == "failed"
        assert report["cases"][0]["rag"]["status"] == "failed"
        assert "private-provider-test-key" not in json.dumps(report)
    assert list((tmp_path / "evaluations").iterdir()) == []


def test_location_match_only_uses_actual_document_and_heading_not_answer_words():
    case = load_cases()[0]
    rag = {
        "content": "逻辑和链表 [资料1] [资料99]",
        "citations": [
            {"number": 1, "source_info": {"content_code": "wrong-document"}, "heading": "线性序列"},
        ],
    }
    checks = location_checks(case, rag)
    assert checks["expected_location_matches"][0]["matched"] is False
    assert checks["unknown_citation_tokens"] == [99]
    rag["citations"][0]["source_info"]["content_code"] = "linear-list"
    assert location_checks(case, rag)["expected_location_matches"][0]["matched"] is True


def test_evaluation_cli_refuses_unconfigured_run_without_writing_metrics(tmp_path):
    output = tmp_path / "not-created.json"
    environment = {**os.environ, "CAPSTONE_DATA_DIR": str(tmp_path)}
    for kind in ("GENERATION", "EMBEDDING"):
        for name in ("BASE_URL", "MODEL", "API_KEY"):
            environment[f"CAPSTONE_{kind}_{name}"] = ""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "capstone.evaluate_rag", "--output", str(output)],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 2, result.stderr
    assert "评估未执行" in result.stdout
    assert not output.exists()
    assert list((tmp_path / "evaluations").iterdir()) == []
