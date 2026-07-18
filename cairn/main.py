import logging
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from cairn.config import SESSION_SECRET_KEY
from cairn.dependencies import NotAuthenticatedError, get_current_user, get_current_user_optional, get_db
from cairn.logging_config import setup_logging
from cairn.models import User
from cairn.routers import auth as auth_router
from cairn.routers import boxes as boxes_router
from cairn.routers import content as content_router
from cairn.routers import difficulty as difficulty_router
from cairn.routers import enrollments as enrollments_router
from cairn.routers import lists as lists_router
from cairn.routers import practice as practice_router
from cairn.routers import progress as progress_router
from cairn.routers import recordings as recordings_router
from cairn.routers import settings as settings_router
from cairn.routers import shared as shared_router
from cairn.routers import thesession_link as thesession_link_router
from cairn.routers import tune_sets as tune_sets_router
from cairn.routers import tunes as tunes_router
from cairn.routers import tunings as tunings_router
from cairn.routers import warmups as warmups_router
from cairn.services.content import get_content, render_markdown
from cairn.services.dashboard import get_dashboard_data
from cairn.templating import APP_VERSION, templates

_GUEST_LANDING_SLUG = "getting-started"

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
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)


@app.exception_handler(NotAuthenticatedError)
async def handle_not_authenticated(request: Request, exc: NotAuthenticatedError) -> RedirectResponse:
    return RedirectResponse(f"/auth/login?next={quote(exc.next_path, safe='')}")


app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

app.include_router(auth_router.router)
# Deliberate exception to "everything requires login" (see TODO 11.3): a
# ShareLink token is itself the credential for exactly the one shared item.
app.include_router(shared_router.router)
_login_required = [Depends(get_current_user)]
app.include_router(progress_router.router, dependencies=_login_required)
app.include_router(boxes_router.router, dependencies=_login_required)
app.include_router(lists_router.router, dependencies=_login_required)
app.include_router(practice_router.router, dependencies=_login_required)
app.include_router(enrollments_router.router, dependencies=_login_required)
app.include_router(tunings_router.router, dependencies=_login_required)
app.include_router(recordings_router.router, dependencies=_login_required)
# tunes/warmups/sets/content are NOT gated at the router level (see #225): each
# lets a guest browse its public-catalog view routes (list/detail), while every
# mutation route declares its own Depends(get_current_user) individually.
app.include_router(tunes_router.router)
app.include_router(thesession_link_router.router, dependencies=_login_required)
app.include_router(settings_router.router, dependencies=_login_required)
app.include_router(difficulty_router.router, dependencies=_login_required)
app.include_router(warmups_router.router)
app.include_router(tune_sets_router.router)
app.include_router(content_router.router)


@app.get("/version")
async def get_version() -> dict[str, str]:
    return {"version": APP_VERSION}


@app.head("/")
async def index_head() -> Response:
    # Uptime/status checkers (e.g. shields.io's website badge) probe with HEAD
    # and carry no session cookie — this must stay public, unlike the GET
    # below, or they'd report the app as down even though it's actually up.
    return Response(status_code=200)


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> HTMLResponse:
    if user is None:
        # A guest (see #228) gets a public landing page, not the personal
        # dashboard -- there's nothing of their own to show, and redirecting
        # straight to /auth/login gave them no chance to look around first.
        content = await get_content(db, _GUEST_LANDING_SLUG)
        rendered_body = render_markdown(content.body) if content else None
        return templates.TemplateResponse(request, "landing.html", {"rendered_body": rendered_body})
    data = await get_dashboard_data(db, user.id)
    return templates.TemplateResponse(request, "dashboard.html", {"data": data})
