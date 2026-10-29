"""Bind each published citation to a literal excerpt from its numbered source."""

import json
import re

OPEN = "<citation>"
CLOSE = "</citation>"
BARE_CITATION = re.compile(r"\[资料\d+\]")
PARTIAL_CITATION = re.compile(r"\[(?:资(?:料\d*)?)?")
METADATA = re.compile(
    r"^\s*(?:所属章节|适用程度|来源说明|资料来源|作者|版权|许可|license|source)\s*[:：]",
    re.IGNORECASE,
)


def evidence_body(text):
    """Titles and provenance alone cannot substantiate a learning claim."""
    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            lines.append(line)
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = None
        elif marker:
            fence = marker[1]
            lines.append(line)
        elif not re.match(r"^\s*#{1,6}\s+", line) and not METADATA.match(line):
            lines.append(line)
    return "\n".join(lines).strip()


def normalize(text):
    return re.sub(r"\s+", "", text)


def has_evidence(text):
    return len(normalize(evidence_body(text))) >= 8


def reference_context(citations):
    blocks = []
    for citation in citations:
        number = citation["number"]
        location = citation.get("heading") or ""
        if citation.get("page_number"):
            location += f" · 第 {citation['page_number']} 页"
        if citation.get("line_start"):
            location += f" · 第 {citation['line_start']}—{citation['line_end']} 行"
        blocks.append(
            f"[资料{number}]\n文件：{citation.get('filename', '')}\n位置：{location}\n"
            f"原文：\n{citation['text']}\n[/资料{number}]"
        )
    return "\n\n".join(blocks) or "（本轮没有可引用的资料片段）"


def render_citations(raw, candidates, *, final=False):
    """Withhold incomplete evidence tags; only validated tags become buttons.

    Re-render the bounded accumulated answer at each persistence checkpoint, so
    split transport deltas cannot expose private protocol data or alter numbers.
    Markdown code is literal and is never treated as an evidence declaration.
    """
    sources = {item["number"]: item for item in candidates}
    approved, output = {}, []
    position, fence = 0, None
    while position < len(raw):
        if position == 0 or raw[position - 1] == "\n":
            end = raw.find("\n", position)
            end = len(raw) if end < 0 else end + 1
            line = raw[position:end]
            marker = re.match(r" {0,3}(`{3,}|~{3,})(.*)", line)
            if fence:
                output.append(line)
                if (
                    marker
                    and marker[1][0] == fence[0]
                    and len(marker[1]) >= len(fence)
                    and not marker[2].strip()
                ):
                    fence = None
                position = end
                continue
            if marker:
                fence = marker[1]
                output.append(line)
                position = end
                continue
            if line.startswith(("    ", "\t")):
                output.append(line)
                position = end
                continue
        if raw[position] == "`":
            ticks = re.match(r"`+", raw[position:])[0]
            closing = re.search(
                r"(?<!`)" + re.escape(ticks) + r"(?!`)", raw[position + len(ticks) :]
            )
            if closing is None:
                if final:
                    output.append(raw[position:])
                break
            end = position + len(ticks) + closing.end()
            output.append(raw[position:end])
            position = end
            continue
        if raw.startswith(OPEN, position):
            end = raw.find(CLOSE, position + len(OPEN))
            if end < 0:
                break
            try:
                value = json.loads(raw[position + len(OPEN) : end])
                number, quote = value["number"], value["quote"]
                source = sources.get(number) if type(number) is int else None
                normalized = normalize(quote) if isinstance(quote, str) else ""
                if (
                    source is not None
                    and 8 <= len(normalized) <= 500
                    and normalized in normalize(source["text"])
                    and normalized in normalize(evidence_body(source["text"]))
                ):
                    item = approved.setdefault(number, {**source, "evidence_quotes": []})
                    if quote not in item["evidence_quotes"]:
                        item["evidence_quotes"].append(quote)
                    output.append(f"[资料{number}]")
            except (ValueError, KeyError, TypeError):
                pass
            position = end + len(CLOSE)
            continue
        bare = BARE_CITATION.match(raw, position)
        if bare:
            position = bare.end()
            continue
        if len(raw) - position < len(OPEN):
            tail = raw[position:]
            # Incomplete metadata must not leak on completion or cancellation.
            if OPEN.startswith(tail) and (not final or len(tail) > 1):
                break
        if not final and raw[position] == "[" and PARTIAL_CITATION.fullmatch(raw, position):
            break
        output.append(raw[position])
        position += 1
    return "".join(output), [approved[number] for number in sorted(approved)]
