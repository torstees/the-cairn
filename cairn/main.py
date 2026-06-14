from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).parent

app = FastAPI(title="The Cairn")

app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")

# cache_size=0 works around a Python 3.14 incompatibility in Jinja2's LRUCache
_jinja_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=True,
    cache_size=0,
)
templates = Jinja2Templates(env=_jinja_env)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
