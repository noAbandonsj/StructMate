"""Serve the prebuilt desktop app in the same process as the API."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from capstone.core.settings import REPOSITORY_ROOT

FRONTEND_DIST = REPOSITORY_ROOT / "frontend" / "dist"


def install_frontend(app: FastAPI):
    directory = FRONTEND_DIST.resolve()
    index = directory / "index.html"
    assets = directory / "assets"
    if not index.is_file() or not assets.is_dir():
        raise RuntimeError("网页构建不存在，请先在 frontend 执行 pnpm.cmd build。")
    app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def desktop(path: str):
        # Keep API failures and missing files distinct from SPA route refreshes.
        if (
            path.split("/", 1)[0] in {"api", "docs", "redoc", "openapi.json"}
            or "." in Path(path).name
        ):
            raise HTTPException(404)
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
