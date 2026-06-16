from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from cairn.routers import difficulty as difficulty_router
from cairn.routers import progress as progress_router
from cairn.routers import settings as settings_router
from cairn.routers import tunes as tunes_router
from cairn.templating import templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="The Cairn")

app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

app.include_router(tunes_router.router)
app.include_router(settings_router.router)
app.include_router(difficulty_router.router)
app.include_router(progress_router.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
