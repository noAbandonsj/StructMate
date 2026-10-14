import re
from pathlib import Path
from uuid import UUID

from capstone.core.errors import ApiError


def validate_upload(filename: str | None, data: bytes, maximum: int) -> tuple[str, str]:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 240 or any(ord(character) < 32 for character in name):
        raise ApiError(422, "FILENAME_INVALID", "文件名无效或过长，请修改后上传。")
    suffix = Path(name).suffix.lower()
    types = {".pdf": "pdf", ".txt": "txt", ".md": "md", ".markdown": "md"}
    if suffix not in types:
        raise ApiError(415, "FILE_TYPE_UNSUPPORTED", "请上传文本型 PDF、TXT 或 Markdown。")
    if not data:
        raise ApiError(422, "FILE_EMPTY", "文件为空，请选择有内容的资料。")
    if len(data) > maximum:
        raise ApiError(413, "FILE_TOO_LARGE", "文件超过大小限制，请拆分后上传。")
    kind = types[suffix]
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        raise ApiError(422, "PDF_INVALID", "文件内容不是有效的 PDF。")
    if kind != "pdf" and b"\x00" in data:
        raise ApiError(422, "TEXT_INVALID", "文件内容不是可读取的文本。")
    return name, kind


class BlobStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.(pdf|txt|md)", key):
            raise ApiError(503, "FILE_UNAVAILABLE", "资料文件暂不可用，请稍后重试。")
        path = self.directory / key
        if path.resolve().parent != self.directory:
            raise ApiError(503, "FILE_UNAVAILABLE", "资料文件暂不可用，请稍后重试。")
        return path

    def save(self, document_id: UUID, kind: str, data: bytes) -> str:
        key = f"{document_id.hex}.{kind}"
        path = self.path(key)
        created = False
        try:
            with path.open("xb") as file:
                created = True
                file.write(data)
        except OSError:
            if created:
                path.unlink(missing_ok=True)
            raise ApiError(
                503, "FILE_WRITE_FAILED", "文件保存失败，请检查可用空间或稍后重试。"
            ) from None
        return key

    def remove(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
