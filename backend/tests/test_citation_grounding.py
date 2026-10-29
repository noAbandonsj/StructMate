import json
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_conversations import new_conversation, send, wait_answer
from test_documents import TestEmbedding, register, upload, wait_document

from capstone.core.settings import Settings
from capstone.db.models import DocumentChunk
from capstone.main import create_app
from capstone.services.citation_grounding import has_evidence, render_citations
from capstone.services.parsing import split_fragments, text_fragments
from capstone.services.retrieval import retrieve

DEFINITION = "栈只允许在同一端插入和删除，遵循后进先出；队列在队尾插入、队头删除。"
EXAMPLE = "把输入 7、8、9 全部存入后再全部取出，栈的顺序为 9、8、7，队列为 7、8、9。"
SOURCES = [
    {"number": 1, "text": "## 1. 栈与队列的基本区别"},
    {"number": 2, "text": DEFINITION},
    {"number": 3, "text": EXAMPLE},
]


def citation(number, quote):
    return (
        "<citation>"
        + json.dumps({"number": number, "quote": quote}, ensure_ascii=False)
        + "</citation>"
    )


def test_heading_body_merge_preserves_original_lines_sections_code_and_formula():
    raw = (
        "# 栈与队列\n\n## 基本区别\n\n" + DEFINITION + "\n\n补充说明：两者都是线性结构。\n\n"
        "```c\n// # 这不是标题\npush(1);\n\npop();\n```\n\n"
        "$$\nO(1)\n\n$$\n\n## 示例\n\n" + EXAMPLE + "\n"
    )
    chunks = split_fragments(text_fragments(raw, markdown=True), 1200)
    assert len(chunks) == 2
    assert chunks[0].heading == "栈与队列 / 基本区别"
    assert "```c\n// # 这不是标题\npush(1);\n\npop();\n```" in chunks[0].text
    assert "$$\nO(1)\n\n$$" in chunks[0].text
    lines = raw.splitlines()
    for chunk in chunks:
        assert chunk.text == "\n".join(lines[chunk.line_start - 1 : chunk.line_end])
        assert has_evidence(chunk.text)
    assert DEFINITION not in chunks[1].text
    assert chunks[1].text.startswith("## 示例\n\n")


def test_short_pdf_paragraphs_merge_only_within_same_page():
    chunks = split_fragments(
        text_fragments(
            "第一段讲解栈的后进先出。\n\n第二段讲解队列的先进先出。", markdown=False, page=1
        )
        + text_fragments("另一页的独立正文内容。", markdown=False, page=2),
        1200,
    )
    assert len(chunks) == 2
    assert chunks[0].page_number == 1 and chunks[0].line_start is None
    assert "\n\n" in chunks[0].text
    assert chunks[1].page_number == 2


@pytest.mark.parametrize(
    "text", ["# 栈与队列的基本区别", "来源说明：本材料用于学习测试。", "# 标题\n所属章节：栈与队列"]
)
def test_titles_and_provenance_cannot_be_evidence(text):
    assert not has_evidence(text)


def test_admin_regression_rejects_shifted_sources_and_bare_numbers():
    raw = (
        "栈的定义"
        + citation(1, DEFINITION)
        + "，正确引用"
        + citation(2, DEFINITION)
        + "。例子错误引用"
        + citation(2, EXAMPLE)
        + "，正确引用"
        + citation(3, EXAMPLE)
        + "。[资料1][资料999]，数组 a[0]。"
    )
    content, sources = render_citations(raw, SOURCES, final=True)
    assert content == "栈的定义，正确引用[资料2]。例子错误引用，正确引用[资料3]。，数组 a[0]。"
    assert [source["number"] for source in sources] == [2, 3]
    assert sources[0]["evidence_quotes"] == [DEFINITION]
    assert sources[1]["evidence_quotes"] == [EXAMPLE]


def test_stream_never_exposes_protocol_and_binds_each_occurrence_independently():
    raw = "栈与队列的区别：" + citation(2, DEFINITION) + "继续解释。" + citation(2, EXAMPLE)
    previous = ""
    for end in range(1, len(raw) + 1):
        content, sources = render_citations(raw[:end], SOURCES)
        assert "<citation" not in content and '"quote"' not in content
        assert content.startswith(previous)
        previous = content
        assert all(source["number"] == 2 for source in sources)
    content, sources = render_citations(raw, SOURCES, final=True)
    assert content.count("[资料2]") == 1
    assert sources[0]["evidence_quotes"] == [DEFINITION]


@pytest.mark.parametrize(
    "tag",
    [
        "<citation>{bad}</citation>",
        '<citation>{"number":2,"quote":',
        "<cita",
        citation(2, "栈与队列"),
        citation(True, DEFINITION),
        citation(99, DEFINITION),
        citation(1, "栈与队列的基本区别"),
    ],
)
def test_invalid_and_incomplete_declarations_publish_no_citation(tag):
    content, sources = render_citations("回答正文。" + tag, SOURCES, final=True)
    assert content == "回答正文。" and sources == []


def test_code_examples_are_literal_and_cannot_register_citations():
    literal = citation(2, DEFINITION)
    raw = f"`[资料2]`\n```html\n{literal}\n[资料2]\n```\n真正引用" + literal
    content, sources = render_citations(raw, SOURCES, final=True)
    assert f"```html\n{literal}\n[资料2]\n```" in content
    assert content.endswith("真正引用[资料2]")
    assert len(sources) == 1


def test_retrieval_filters_before_numbering_and_deduplicates(migrated_database, tmp_path):
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(create_app(settings, embedding_service=TestEmbedding())) as client:
        library, headers = register(client)
        user_id = UUID(client.get("/api/v1/auth/me").json()["user"]["id"])
        uploaded = upload(client, library, headers)["document"]["id"]
        wait_document(client, uploaded, "ready")
        with Session(migrated_database) as session, session.begin():
            existing = session.scalar(select(DocumentChunk))
            existing.text = SOURCES[0]["text"]
            body = DocumentChunk(
                id=uuid4(),
                document_id=existing.document_id,
                index_revision=existing.index_revision,
                position=99,
                text=DEFINITION,
            )
            session.add(body)
            session.flush()

            def hit(chunk):
                return SimpleNamespace(
                    payload={
                        "chunk_id": str(chunk.id),
                        "document_id": str(chunk.document_id),
                        "index_revision": chunk.index_revision,
                    }
                )

            hits = [hit(existing), hit(body), hit(body)]
        vectors = SimpleNamespace(search=lambda *args: hits)
        result = retrieve(
            sessionmaker(bind=migrated_database),
            TestEmbedding(),
            vectors,
            settings,
            user_id,
            "combined",
            [],
            "栈和队列",
        )
        assert len(result) == 1 and result[0]["number"] == 1
        assert result[0]["text"] == DEFINITION


def test_invalid_grounding_does_not_fail_chat_and_is_not_published(
    migrated_database, tmp_path, monkeypatch
):
    import capstone.services.chat_runner as runner

    class Generation:
        available = True

        def stream(self, messages, cancelled):
            assert "[资料2]" in messages[0]["content"]
            yield "正常讲解。" + citation(1, DEFINITION) + citation(2, DEFINITION)
            yield "错误例子。" + citation(2, EXAMPLE)

    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path)
    with TestClient(
        create_app(settings, embedding_service=TestEmbedding(), generation_service=Generation())
    ) as client:
        library, headers = register(client)
        document = upload(client, library, headers)["document"]["id"]
        wait_document(client, document, "ready")
        sources = [{**source, "document_id": document} for source in SOURCES]
        monkeypatch.setattr(runner.ChatRetrieval, "search", lambda *args: sources)
        identifier = new_conversation(client, headers)
        assert send(client, headers, identifier).status_code == 202
        answer = wait_answer(client, identifier)
        assert answer["content"] == "正常讲解。[资料2]错误例子。"
        assert [source["number"] for source in answer["citations"]] == [2]
        assert answer["citations"][0]["evidence_quotes"] == [DEFINITION]
        assert set(int(n) for n in re.findall(r"\[资料(\d+)\]", answer["content"])) == {2}
