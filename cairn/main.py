import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from cairn.dependencies import get_db
from cairn.logging_config import setup_logging
from cairn.routers import boxes as boxes_router
from cairn.routers import content as content_router
from cairn.routers import difficulty as difficulty_router
from cairn.routers import lists as lists_router
from cairn.routers import practice as practice_router
from cairn.routers import progress as progress_router
from cairn.routers import settings as settings_router
from cairn.routers import thesession_link as thesession_link_router
from cairn.routers import tune_sets as tune_sets_router
from cairn.routers import tunes as tunes_router
from cairn.routers import warmups as warmups_router
from cairn.services.dashboard import get_dashboard_data
from cairn.templating import APP_VERSION, templates

setup_logging()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(title="The Cairn")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response


app.add_middleware(RequestLoggingMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

app.include_router(tunes_router.router)
app.include_router(thesession_link_router.router)
app.include_router(settings_router.router)
app.include_router(difficulty_router.router)
app.include_router(progress_router.router)
app.include_router(boxes_router.router)
app.include_router(lists_router.router)
app.include_router(practice_router.router)
app.include_router(warmups_router.router)
app.include_router(tune_sets_router.router)
app.include_router(content_router.router)


_STUB_USER_ID = 1


@app.get("/version")
async def get_version() -> dict[str, str]:
    return {"version": APP_VERSION}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = await get_dashboard_data(db, _STUB_USER_ID)
    return templates.TemplateResponse(request, "dashboard.html", {"data": data})
