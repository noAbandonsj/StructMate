import json
import re
from collections import Counter
from hashlib import sha256

import pytest

from capstone.core.settings import REPOSITORY_ROOT
from capstone.seed import KNOWLEDGE_POINTS

CONTENT = REPOSITORY_ROOT / "content"


def load(name: str) -> list[dict]:
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def evidence_exists(evidence: dict) -> bool:
    document = next(
        item for item in load("manifest.json") if item["code"] == evidence["document_code"]
    )
    return "\n## " + evidence["heading"] + "\n" in (CONTENT / document["path"]).read_text(
        encoding="utf-8"
    )


def test_course_files_have_attribution_sources_and_stable_hashes() -> None:
    sources = load("sources.json")
    source_ids = {item["id"] for item in sources}
    assert len(source_ids) == len(sources)
    codes = {item[0] for item in KNOWLEDGE_POINTS}
    documents = load("manifest.json")
    assert len(documents) == 3
    for item in documents:
        path = (CONTENT / item["path"]).resolve()
        assert path.is_relative_to(CONTENT.resolve())
        text = path.read_text(encoding="utf-8")
        assert sha256(text.encode("utf-8")).hexdigest() == item["sha256"]
        assert item["sha256_format"] == "utf8-lf"
        assert set(item["knowledge_point_codes"]) <= codes
        assert set(item["source_ids"]) <= source_ids
        assert "许可" in text and "改动" in text
    for source in sources:
        assert source["author"] and source["license_url"].startswith("https://")
        assert source["permission_evidence_url"].startswith("https://")
        if source["license"] == "MIT":
            notice = (CONTENT / source["local_notice"]).read_text(encoding="utf-8")
            assert source["copyright_notice"] in notice
            assert "Permission is hereby granted" in notice


def test_bank_structure_and_evidence_are_consistent() -> None:
    questions = load("question-bank.json")
    assert len({item["code"] for item in questions}) == len(questions) == 15
    assert Counter(item["evidence"]["document_code"] for item in questions) == {
        "linear-list": 5,
        "stack-queue": 5,
        "binary-tree": 5,
    }
    codes = {item[0] for item in KNOWLEDGE_POINTS}
    source_ids = {item["id"] for item in load("sources.json")}
    for item in questions:
        assert item["knowledge_point_code"] in codes
        assert item["difficulty"] == "basic"
        keys = [option["key"] for option in item["options"]]
        assert len(keys) == len(set(keys))
        assert item["answer"] in keys
        assert len(keys) == (2 if item["type"] == "true_false" else 4)
        assert all(option["text"].strip() for option in item["options"])
        assert item["explanation"] and item["verification"]["notes"]
        assert set(item["source_ids"]) <= source_ids
        assert evidence_exists(item["evidence"])


def traversal(data: dict, node: str | None) -> list[str]:
    if node is None:
        return []
    left, right = data["nodes"][node]
    before, after = traversal(data, left), traversal(data, right)
    return before + [node] + after if data["order"] == "inorder" else before + after + [node]


@pytest.mark.parametrize(
    "item",
    [item for item in load("question-bank.json") if "input" in item["verification"]],
    ids=lambda item: item["code"],
)
def test_operation_answers_match_independent_calculation(item: dict) -> None:
    data = item["verification"]["input"]
    answer = next(option["text"] for option in item["options"] if option["key"] == item["answer"])
    match data["kind"]:
        case "array_insert":
            values = list(data["array"])
            values.insert(data["index"], data["value"])
            moved = len(data["array"]) - data["index"]
            assert int(answer) == moved
            assert values == [10, 15, 20, 30, 40]
        case "stack":
            values, popped = [], []
            for operation in data["operations"]:
                if operation[0] == "push":
                    values.append(operation[1])
                else:
                    popped.append(values.pop())
            assert [int(value) for value in re.findall(r"\d+", answer)] == popped
            assert values == [1]
        case "circular_capacity":
            rear = 0
            while (rear + 1) % data["capacity"] != 0:
                rear += 1
            assert int(answer) == rear
        case "circular_length":
            slots, position = [], data["front"]
            while position != data["rear"]:
                slots.append(position)
                position = (position + 1) % data["capacity"]
            assert int(answer) == len(slots)
        case "traversal":
            assert answer.split() == traversal(data, data["root"])
        case "unsorted_counterexample":
            values = [int(value) for value in traversal(data, data["root"])]
            assert values != sorted(values) and item["answer"] == "false"
        case _:
            pytest.fail("Unknown calculation kind")


def test_evaluation_separates_supported_missing_and_held_out_questions() -> None:
    items = load("rag-evaluation.json")
    assert len({item["id"] for item in items}) == len(items) == 30
    assert Counter(item["expectation"] for item in items) == {"supported": 24, "insufficient": 6}
    assert Counter(item["split"] for item in items) == {"development": 20, "holdout": 10}
    for item in items:
        assert item["question"] and item["answer_rubric"]
        if item["expectation"] == "supported":
            assert item["expected_support"] and all(
                evidence_exists(evidence) for evidence in item["expected_support"]
            )
        else:
            assert item["expected_support"] == []
        assert "model_result" not in item
