import tomllib
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

_BASE_DIR = Path(__file__).parent


def _read_app_version() -> str:
    # The project isn't installed as a package (uv.lock treats it as a
    # `virtual` root, no [build-system]) — importlib.metadata has no
    # distribution to look up, so read pyproject.toml directly instead.
    with (_BASE_DIR.parent / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


APP_VERSION = _read_app_version()

_env = Environment(
    loader=FileSystemLoader(str(_BASE_DIR / "templates")),
    autoescape=True,
    cache_size=0,
)
_env.globals["app_version"] = APP_VERSION

templates = Jinja2Templates(env=_env)
