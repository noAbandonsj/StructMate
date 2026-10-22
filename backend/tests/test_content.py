import json
from collections import Counter
from hashlib import sha256

from capstone.core.settings import REPOSITORY_ROOT
from capstone.seed import CHAPTERS

CONTENT = REPOSITORY_ROOT / "content"
COURSE_PACKET = REPOSITORY_ROOT / "backend/tests/fixtures/course"


def load(name: str) -> list[dict]:
    directory = COURSE_PACKET if name == "manifest.json" else CONTENT
    return json.loads((directory / name).read_text(encoding="utf-8"))


def evidence_exists(evidence: dict) -> bool:
    document = next(
        item for item in load("manifest.json") if item["code"] == evidence["document_code"]
    )
    return "\n## " + evidence["heading"] + "\n" in (COURSE_PACKET / document["path"]).read_text(
        encoding="utf-8"
    )


def test_course_files_have_attribution_sources_and_stable_hashes() -> None:
    sources = load("sources.json")
    source_ids = {item["id"] for item in sources}
    assert len(source_ids) == len(sources)
    codes = {item[0] for item in CHAPTERS}
    documents = load("manifest.json")
    assert len(documents) == 3
    for item in documents:
        path = (COURSE_PACKET / item["path"]).resolve()
        assert path.is_relative_to(COURSE_PACKET.resolve())
        text = path.read_text(encoding="utf-8")
        assert sha256(text.encode("utf-8")).hexdigest() == item["sha256"]
        assert item["sha256_format"] == "utf8-lf"
        assert item["chapter_code"] in codes
        assert set(item["source_ids"]) <= source_ids
        assert "许可" in text and "改动" in text
    for source in sources:
        assert source["author"] and source["license_url"].startswith("https://")
        assert source["permission_evidence_url"].startswith("https://")
        if source["license"] == "MIT":
            notice = (CONTENT / source["local_notice"]).read_text(encoding="utf-8")
            assert source["copyright_notice"] in notice
            assert "Permission is hereby granted" in notice


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
