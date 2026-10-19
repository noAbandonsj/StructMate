from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class UploadBodyLimit:
    def __init__(self, app: ASGIApp, maximum: int):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and (
                (path.startswith("/api/v1/knowledge-bases/") and path.endswith("/documents"))
                or path == "/api/v1/admin/course/documents"
            )
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = -1
        error = {"code": "FILE_TOO_LARGE", "message": "文件超过大小限制，请拆分后上传。"}
        if declared > self.maximum or declared < 0:
            await JSONResponse(error, status_code=413, headers={"Cache-Control": "no-store"})(
                scope, receive, send
            )
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.maximum:
                raise HTTPException(413, detail=error)
            return message

        await self.app(scope, limited_receive, send)
