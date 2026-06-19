from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from cairn.routers import boxes as boxes_router
from cairn.routers import difficulty as difficulty_router
from cairn.routers import lists as lists_router
from cairn.routers import progress as progress_router
from cairn.routers import settings as settings_router
from cairn.routers import tunes as tunes_router
from cairn.templating import templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="The Cairn")


class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response


app.add_middleware(NoCacheHTMLMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

app.include_router(tunes_router.router)
app.include_router(settings_router.router)
app.include_router(difficulty_router.router)
app.include_router(progress_router.router)
app.include_router(boxes_router.router)
app.include_router(lists_router.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
