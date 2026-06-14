from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

_BASE_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(str(_BASE_DIR / "templates")),
    autoescape=True,
    cache_size=0,
)

templates = Jinja2Templates(env=_env)
