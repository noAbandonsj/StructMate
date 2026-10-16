"""DeepSeek generation and Qwen embeddings over their compatible HTTP interfaces."""

import json
import time
from collections import deque
from contextlib import contextmanager
from hashlib import sha256
from threading import Event, Thread
from urllib.parse import urlsplit, urlunsplit

import httpx2 as httpx

from capstone.core.errors import ApiError
from capstone.core.model_ports import EmbeddingBatch, UnconfiguredEmbedding, UnconfiguredGeneration

MAX_FRAME = 1024 * 1024
MAX_EMBEDDING_RESPONSE = 8 * 1024 * 1024


def endpoint(base_url, suffix):
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if not path.endswith("/" + suffix):
        path += "/" + suffix
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def failure(kind, code, message):
    return ApiError(503, f"{kind}_{code}", message)


def check_status(response, kind):
    status = response.status_code
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise failure(kind, "AUTH_FAILED", "模型鉴权失败，请检查后端密钥、服务地域和访问权限。")
    if status == 429:
        raise failure(kind, "RATE_LIMITED", "模型请求频率或额度受限，请稍后重试或检查服务额度。")
    if status >= 500:
        raise failure(kind, "UNAVAILABLE", "模型服务暂不可用，请稍后重试。")
    raise failure(kind, "REQUEST_REJECTED", "模型请求被拒绝，请检查接口地址、模型标识及参数。")


@contextmanager
def request_client(connection, transport=None, cancelled=None):
    """A request owns its client; cancellation never closes another request's connection."""
    headers = {"Content-Type": "application/json"}
    if connection.api_key:
        headers["Authorization"] = "Bearer " + connection.api_key.get_secret_value()
    client = httpx.Client(
        headers=headers,
        timeout=connection.timeout_seconds,
        follow_redirects=False,
        transport=transport,
    )
    finished, expired = Event(), Event()
    deadline = time.monotonic() + connection.timeout_seconds

    def watch():
        while not finished.wait(0.05):
            if time.monotonic() >= deadline:
                expired.set()
            if expired.is_set() or cancelled is not None and cancelled.is_set():
                try:
                    client.close()
                except Exception:
                    pass  # The request reports cancellation/timeout without transport details.
                return

    watcher = Thread(target=watch, daemon=True, name="model-request-cancel")
    watcher.start()
    try:
        with client:
            yield client, expired
    finally:
        finished.set()
        client.close()
        watcher.join(timeout=1)


def events(response):
    buffer, fields = b"", []
    size = 0
    for chunk in response.iter_bytes():
        buffer += chunk
        if len(buffer) + size > MAX_FRAME:
            raise ValueError("Oversized SSE frame")
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.removesuffix(b"\r")
            if not line:
                if fields:
                    yield b"\n".join(fields).decode("utf-8")
                fields, size = [], 0
            elif line.startswith(b"data:"):
                payload = line[5:].lstrip(b" ")
                fields.append(payload)
                size += len(payload)
    if buffer or fields:
        raise ValueError("Interrupted SSE frame")


class DeepSeekGeneration:
    available = True

    def __init__(self, connection, *, transport=None):
        self.connection, self.transport = connection, transport

    def stream(self, messages, cancelled):
        if cancelled.is_set():
            return
        expired = Event()
        try:
            with request_client(self.connection, self.transport, cancelled) as (client, expired):
                payload = {
                    "model": self.connection.model,
                    "messages": messages,
                    "stream": True,
                    "thinking": {"type": "disabled"},
                    "max_tokens": 8192,
                }
                with client.stream(
                    "POST", endpoint(self.connection.base_url, "chat/completions"), json=payload
                ) as response:
                    check_status(response, "GENERATION")
                    if not response.headers.get("content-type", "").startswith("text/event-stream"):
                        raise ValueError("Expected SSE")
                    stopped, has_text = False, False
                    for data in events(response):
                        if cancelled.is_set():
                            return
                        if expired.is_set():
                            raise httpx.ReadTimeout("Deadline")
                        if data.strip() == "[DONE]":
                            if not stopped or not has_text:
                                raise ValueError("Incomplete model output")
                            return
                        frame = json.loads(data)
                        if not isinstance(frame, dict) or frame.get("error"):
                            raise ValueError("Invalid model event")
                        choices = frame.get("choices")
                        if choices == [] and "usage" in frame:
                            continue
                        if not isinstance(choices, list) or len(choices) != 1:
                            raise ValueError("Invalid choices")
                        choice = choices[0]
                        if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                            raise ValueError("Invalid choice")
                        delta = choice.get("delta")
                        if not isinstance(delta, dict) or delta.get("tool_calls"):
                            raise ValueError("Invalid text delta")
                        if delta.get("role") not in {None, "assistant"}:
                            raise ValueError("Invalid stream role")
                        content = delta.get("content")
                        if content is not None and not isinstance(content, str):
                            raise ValueError("Invalid text delta")
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if reason == "length":
                                raise failure(
                                    "GENERATION",
                                    "TRUNCATED",
                                    "回答达到输出上限，请缩小问题或减少题量后重试。",
                                )
                            if reason != "stop":
                                raise ValueError("Model did not finish normally")
                            stopped = True
                        if content:
                            if stopped and reason is None:
                                raise ValueError("Text after stop")
                            has_text = has_text or bool(content.strip())
                            yield content
                    raise ValueError("Stream ended without DONE")
        except Exception as error:
            if cancelled.is_set():
                return
            if expired.is_set() or isinstance(error, httpx.TimeoutException):
                raise failure("GENERATION", "TIMEOUT", "生成模型请求超时，请稍后重试。") from None
            if isinstance(error, ApiError):
                raise error from None
            if isinstance(error, httpx.RequestError):
                raise failure(
                    "GENERATION", "UNAVAILABLE", "无法连接生成模型，请检查后端服务配置。"
                ) from None
            raise failure(
                "GENERATION", "INVALID", "生成服务返回无效或中断的数据，请重试。"
            ) from None


class QwenEmbedding:
    available = True

    def __init__(self, connection, *, transport=None):
        self.connection, self.transport = connection, transport

    def embed(self, texts):
        if (
            not isinstance(texts, list)
            or not texts
            or any(not isinstance(text, str) or not text.strip() for text in texts)
        ):
            raise failure("EMBEDDING", "INVALID_INPUT", "向量输入不能为空。")
        expired = Event()
        try:
            vectors, dimension = [], None
            url = endpoint(self.connection.base_url, "embeddings")
            # Keep batches within v4's ten-text limit, also valid for Qwen 3.7 Flash.
            batches = deque(texts[start : start + 10] for start in range(0, len(texts), 10))
            while batches:
                inputs = batches.popleft()
                payload = {
                    "model": self.connection.model,
                    "input": inputs,
                    "encoding_format": "float",
                }
                if self.connection.expected_dimension is not None:
                    payload["dimensions"] = self.connection.expected_dimension
                with request_client(self.connection, self.transport) as (client, expired):
                    with client.stream("POST", url, json=payload) as response:
                        check_status(response, "EMBEDDING")
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if expired.is_set():
                                raise httpx.ReadTimeout("Deadline")
                            if len(raw) > MAX_EMBEDDING_RESPONSE:
                                raise ValueError("Oversized embedding response")
                        data = json.loads(raw)
                rows = (
                    data.get("data") if isinstance(data, dict) and not data.get("error") else None
                )
                if not isinstance(rows, list) or len(rows) != len(inputs):
                    raise ValueError("Invalid embedding rows")
                if (
                    self.connection.model == "qwen3.7-text-embedding-flash"
                    and len(inputs) > 1
                    and all(
                        isinstance(row, dict)
                        and type(row.get("index")) is int
                        and row["index"] == 0
                        for row in rows
                    )
                ):
                    # Observed Flash gateway behavior: every batch index is zero.
                    # Discard ambiguous vectors; single-input requests establish the mapping.
                    batches.extendleft([text] for text in reversed(inputs))
                    continue
                indexed = {}
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid embedding row")
                    index = row.get("index")
                    if type(index) is not int or not 0 <= index < len(inputs) or index in indexed:
                        raise ValueError("Invalid embedding index")
                    indexed[index] = row.get("embedding")
                current = [indexed[index] for index in range(len(inputs))]
                if any(not isinstance(vector, list) for vector in current):
                    raise ValueError("Invalid embedding vector")
                current_dimension = EmbeddingBatch(current, "0" * 64).validate(len(inputs))
                if (
                    self.connection.expected_dimension is not None
                    and current_dimension != self.connection.expected_dimension
                ):
                    raise failure(
                        "EMBEDDING",
                        "DIMENSION_MISMATCH",
                        "实际向量维度与配置不一致，请检查后端配置。",
                    )
                if dimension is not None and current_dimension != dimension:
                    raise ValueError("Embedding dimensions changed between batches")
                dimension = current_dimension
                vectors.extend(current)
            identity = json.dumps(
                {
                    "protocol": "compatible-embeddings-v1",
                    "endpoint": url,
                    "model": self.connection.model,
                    "dimension": dimension,
                },
                sort_keys=True,
            )
            return EmbeddingBatch(vectors, sha256(identity.encode()).hexdigest())
        except Exception as error:
            if expired.is_set() or isinstance(error, httpx.TimeoutException):
                raise failure("EMBEDDING", "TIMEOUT", "向量模型请求超时，请稍后重试。") from None
            if isinstance(error, ApiError):
                raise error from None
            if isinstance(error, httpx.RequestError):
                raise failure(
                    "EMBEDDING", "UNAVAILABLE", "无法连接向量模型，请检查后端服务配置。"
                ) from None
            raise failure(
                "EMBEDDING", "INVALID", "向量服务返回无效数据，请检查配置或重试。"
            ) from None


def generation_service(connection):
    return (
        DeepSeekGeneration(connection)
        if connection and connection.api_key
        else UnconfiguredGeneration(connection)
    )


def embedding_service(connection):
    return (
        QwenEmbedding(connection)
        if connection and connection.api_key
        else UnconfiguredEmbedding(connection)
    )
