import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from capstone.core.errors import ApiError
from capstone.core.settings import Settings


@dataclass(frozen=True)
class Fragment:
    text: str
    page_number: int | None = None
    heading: str | None = None
    line_start: int | None = None
    line_end: int | None = None


def text_fragments(text: str, *, markdown: bool, page: int | None = None) -> list[Fragment]:
    result: list[Fragment] = []
    lines = text.splitlines()
    block: list[str] = []
    start = 1
    headings: dict[int, str] = {}
    fence: str | None = None

    def flush(end: int) -> None:
        if block and "\n".join(block).strip():
            result.append(
                Fragment(
                    "\n".join(block).strip(),
                    page,
                    " / ".join(headings[level] for level in sorted(headings)) or None,
                    start if page is None else None,
                    end if page is None else None,
                )
            )
        block.clear()

    for index, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line) if markdown and fence is None else None
        if match:
            flush(index - 1)
            level = len(match[1])
            headings = {key: value for key, value in headings.items() if key < level}
            headings[level] = match[2]
        marker = None
        if markdown:
            stripped = line.lstrip()
            if stripped.startswith(chr(96) * 3):
                marker = chr(96) * 3
            elif stripped.startswith("~~~"):
                marker = "~~~"
            elif stripped == "$$":
                marker = "$$"
        if not block:
            start = index
        if marker:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        if not line.strip() and fence is None:
            flush(index - 1)
        else:
            block.append(line)
    flush(len(lines))
    return result


def parse_file(path: Path, file_type: str, settings: Settings) -> list[Fragment]:
    if file_type == "pdf":
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ApiError(422, "PDF_ENCRYPTED", "暂不支持加密 PDF，请上传未加密的文本资料。")
            if len(reader.pages) > settings.pdf_max_pages:
                raise ApiError(422, "PDF_TOO_LONG", "PDF 页数超出限制，请拆分后上传。")
            result, count = [], 0
            for page_number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                count += len(text)
                if count > settings.document_max_chars:
                    raise ApiError(422, "DOCUMENT_TOO_LONG", "提取的文字过多，请拆分文件。")
                result.extend(text_fragments(text, markdown=False, page=page_number))
        except ApiError:
            raise
        except Exception:
            raise ApiError(
                422, "PDF_INVALID", "无法读取这个 PDF，请检查文件或改用 TXT、Markdown。"
            ) from None
    else:
        text = decode_text(path.read_bytes())
        if len(text) > settings.document_max_chars:
            raise ApiError(422, "DOCUMENT_TOO_LONG", "文字过多，请拆分文件。")
        result = text_fragments(text, markdown=file_type == "md")
    if not result:
        raise ApiError(422, "NO_TEXT", "没有提取到文字；扫描 PDF 暂不支持，请上传文本资料。")
    return result


def decode_text(raw: bytes) -> str:
    if b"\x00" in raw:
        raise ApiError(422, "TEXT_INVALID", "文件不是可读取的文本，请检查编码或格式。")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError:
            raise ApiError(422, "TEXT_INVALID", "请使用 UTF-8 或 GB18030 编码的文本。") from None


def split_fragments(fragments: list[Fragment], maximum: int) -> list[Fragment]:
    result: list[Fragment] = []
    for fragment in fragments:
        # Keep paragraphs, code and formulas together when reasonably sized.
        if len(fragment.text) <= maximum * 2:
            result.append(fragment)
            continue
        block: list[str] = []
        size = 0
        start = fragment.line_start
        end = start
        for offset, line in enumerate(fragment.text.splitlines()):
            parts = [line[index : index + maximum] for index in range(0, len(line), maximum)] or [
                ""
            ]
            for part in parts:
                if block and size + len(part) + 1 > maximum:
                    result.append(
                        Fragment(
                            "\n".join(block), fragment.page_number, fragment.heading, start, end
                        )
                    )
                    block, size = [], 0
                    start = None if fragment.line_start is None else fragment.line_start + offset
                block.append(part)
                end = None if fragment.line_start is None else fragment.line_start + offset
                size += len(part) + 1
        if block:
            result.append(
                Fragment(
                    "\n".join(block),
                    fragment.page_number,
                    fragment.heading,
                    start,
                    end,
                )
            )
    return result
