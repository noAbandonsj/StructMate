import json
from threading import Event

import httpx2 as httpx
import pytest

from capstone.core.errors import ApiError
from capstone.core.model_config import ModelConnection
from capstone.core.model_http import DeepSeekGeneration, QwenEmbedding, endpoint


def connection(**values):
    return ModelConnection(
        base_url="https://models.example.test/compatible-mode/v1",
        model="test-model",
        api_key="private-http-test-key",
        **values,
    )


def frame(content=None, reason=None, **delta):
    return (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": {"content": content, **delta}, "finish_reason": reason}
                ]
            },
            ensure_ascii=False,
        )
        + "\r\n\r\n"
    ).encode()


def sse_response(data):
    return httpx.Response(200, content=data, headers={"Content-Type": "text/event-stream"})


def test_generation_sse_unicode_comments_usage_reasoning_and_complete_finish():
    responses = []

    def handle(request):
        assert str(request.url) == "https://models.example.test/compatible-mode/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer private-http-test-key"
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["thinking"] == {"type": "disabled"}
        assert payload["messages"] == [{"role": "user", "content": "栈的规则？"}]
        response = sse_response(
            b": keepalive\r\n\r\n"
            + frame(reasoning_content="private reasoning")
            + frame("后进")
            + frame("先出")
            + frame(reason="stop")
            + b'data: {"choices":[],"usage":{"total_tokens":9}}\r\n\r\ndata: [DONE]\r\n\r\n'
        )
        responses.append(response)
        return response

    generation = DeepSeekGeneration(connection(), transport=httpx.MockTransport(handle))
    assert (
        "".join(generation.stream([{"role": "user", "content": "栈的规则？"}], Event()))
        == "后进先出"
    )
    assert responses[0].is_closed


@pytest.mark.parametrize(
    "body",
    [
        frame("partial"),
        frame("partial") + b"data: [DONE]\n\n",
        b"data: not-json\n\n",
        b'data: {"error":{"message":"private-provider-detail"}}\n\n',
        frame("partial", reason="length"),
        frame(reason="stop") + b"data: [DONE]\n\n",
        frame("partial", reason="content_filter"),
        frame("partial") + b"data: {",
    ],
    ids=[
        "eof",
        "missing-stop",
        "bad-json",
        "provider-error",
        "truncated",
        "empty",
        "filter",
        "broken-frame",
    ],
)
def test_generation_invalid_or_incomplete_stream_is_never_success(body):
    model = DeepSeekGeneration(
        connection(), transport=httpx.MockTransport(lambda _: sse_response(body))
    )
    with pytest.raises(ApiError) as error:
        list(model.stream([{"role": "user", "content": "问题"}], Event()))
    assert "private-provider-detail" not in str(error.value)
    assert error.value.detail["code"].startswith("GENERATION_")


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_FAILED"),
        (403, "AUTH_FAILED"),
        (429, "RATE_LIMITED"),
        (500, "UNAVAILABLE"),
        (400, "REQUEST_REJECTED"),
        (302, "REQUEST_REJECTED"),
    ],
)
def test_http_failures_are_sanitized_and_not_retried_or_redirected(status, code):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": "private-provider-detail"},
            headers={"Location": "https://other.example.test"},
        )

    for kind, invoke in (
        (
            "GENERATION",
            lambda transport: list(
                DeepSeekGeneration(connection(), transport=transport).stream([], Event())
            ),
        ),
        (
            "EMBEDDING",
            lambda transport: QwenEmbedding(connection(), transport=transport).embed(["数据"]),
        ),
    ):
        with pytest.raises(ApiError) as error:
            invoke(httpx.MockTransport(handle))
        assert error.value.detail["code"] == kind + "_" + code
        assert "private-provider-detail" not in str(error.value)
        assert "private-http-test-key" not in str(error.value)
    assert len(calls) == 2


def test_embedding_splits_batches_restores_order_checks_dimension_and_stable_identity():
    sizes = []

    def handle(request):
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.content)
        sizes.append(len(payload["input"]))
        assert payload["dimensions"] == 3 and payload["encoding_format"] == "float"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(value), 1.0, 2.0]}
                    for index, value in reversed(list(enumerate(payload["input"])))
                ]
            },
        )

    original = connection(expected_dimension=3)
    model = QwenEmbedding(original, transport=httpx.MockTransport(handle))
    result = model.embed([str(index) for index in range(23)])
    assert sizes == [10, 10, 3] and result.validate(23) == 3
    assert [vector[0] for vector in result.vectors] == list(range(23))
    other = original.model_copy(update={"api_key": None})
    assert (
        QwenEmbedding(other, transport=httpx.MockTransport(handle)).embed(["0"]).fingerprint
        == result.fingerprint
    )
    changed = original.model_copy(update={"model": "different-model"})
    assert (
        QwenEmbedding(changed, transport=httpx.MockTransport(handle)).embed(["0"]).fingerprint
        != result.fingerprint
    )


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"index": 0, "embedding": [0.0, 0.0]}],
        [{"index": 0, "embedding": [float("nan"), 1.0]}],
        [{"index": True, "embedding": [1.0, 2.0]}],
        [{"index": 1, "embedding": [1.0, 2.0]}],
        [{"index": 0, "embedding": ["1", 2.0]}],
        [{"index": 0, "embedding": "base64-value"}],
    ],
    ids=["missing", "zero", "nan", "bool-index", "wrong-index", "string-number", "base64"],
)
def test_embedding_rejects_invalid_values_and_indices(rows):
    model = QwenEmbedding(
        connection(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": rows})),
    )
    with pytest.raises(ApiError) as error:
        model.embed(["文本"])
    assert error.value.detail["code"].startswith("EMBEDDING_")


def test_dimension_mismatch_and_cross_batch_change_fail_without_partial_return():
    def handle(_):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})

    with pytest.raises(ApiError, match="DIMENSION_MISMATCH"):
        QwenEmbedding(
            connection(expected_dimension=3), transport=httpx.MockTransport(handle)
        ).embed(["文本"])
    calls = []

    def changed(request):
        inputs = json.loads(request.content)["input"]
        calls.append(len(inputs))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [1.0] * (2 if len(calls) == 1 else 3)}
                    for index in range(len(inputs))
                ]
            },
        )

    with pytest.raises(ApiError):
        QwenEmbedding(connection(), transport=httpx.MockTransport(changed)).embed(["文本"] * 11)
    assert calls == [10, 1]


def test_timeout_and_network_error_do_not_expose_transport_details():
    for exception, code in (
        (httpx.ReadTimeout("private-provider-detail"), "TIMEOUT"),
        (httpx.ConnectError("private-provider-detail"), "UNAVAILABLE"),
    ):

        def fail(_):
            raise exception

        with pytest.raises(ApiError) as error:
            list(
                DeepSeekGeneration(connection(), transport=httpx.MockTransport(fail)).stream(
                    [], Event()
                )
            )
        assert error.value.detail["code"] == "GENERATION_" + code
        assert "private-provider-detail" not in str(error.value)


def test_cancel_before_request_and_after_first_delta_closes_response():
    calls, responses = [], []

    def handle(request):
        calls.append(request)
        response = sse_response(
            frame("first") + frame("second") + frame(reason="stop") + b"data: [DONE]\n\n"
        )
        responses.append(response)
        return response

    model = DeepSeekGeneration(connection(), transport=httpx.MockTransport(handle))
    cancelled = Event()
    cancelled.set()
    assert list(model.stream([], cancelled)) == [] and not calls
    cancelled.clear()
    stream = model.stream([], cancelled)
    assert next(stream) == "first"
    cancelled.set()
    assert list(stream) == [] and responses[0].is_closed


def test_endpoint_accepts_api_roots_or_complete_endpoint_without_duplicates():
    assert (
        endpoint("https://api.deepseek.com", "chat/completions")
        == "https://api.deepseek.com/chat/completions"
    )
    assert (
        endpoint("https://host.test/compatible-mode/v1/embeddings?version=1", "embeddings")
        == "https://host.test/compatible-mode/v1/embeddings?version=1"
    )
