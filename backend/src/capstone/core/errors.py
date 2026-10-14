from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def storage_error(_request: Request, _error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            content={"code": "STORAGE_UNAVAILABLE", "message": "数据服务暂不可用，请稍后重试。"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        content = error.detail
        if not isinstance(content, dict):
            content = {"code": "HTTP_ERROR", "message": str(content)}
        return JSONResponse(
            content=content,
            status_code=error.status_code,
            headers={**(error.headers or {}), "Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        # Validation details include original input; never echo submitted passwords.
        messages = {
            "username": "用户名须为 3–32 位英文字母、数字或下划线。",
            "password": "密码须为 8–128 个字符。",
            "display_name": "显示名称须为 1–32 个字符。",
        }
        first_error = error.errors()[0]
        field = str(first_error["loc"][-1]) if first_error["loc"] else ""
        message = messages.get(field, "请求格式不正确，请检查输入内容。")
        if first_error["type"] == "extra_forbidden":
            message = "请求包含不支持的字段。"
        return JSONResponse(
            content={"code": "VALIDATION_ERROR", "message": message},
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )
