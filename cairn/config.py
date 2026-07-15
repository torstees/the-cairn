import os
import sys

_TESTING = "pytest" in sys.modules


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value and not _TESTING:
        raise RuntimeError(f"{name} must be set in the environment")
    return value


GOOGLE_CLIENT_ID = _require("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _require("GOOGLE_CLIENT_SECRET")
SESSION_SECRET_KEY = _require("SESSION_SECRET_KEY")
