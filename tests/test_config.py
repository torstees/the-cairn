import os
import subprocess
import sys

_REQUIRED_VARS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SESSION_SECRET_KEY")


def test_config_loads_values_when_env_vars_set() -> None:
    env = {**os.environ, "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret", "SESSION_SECRET_KEY": "key"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from cairn.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET_KEY;"
            "print(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET_KEY)",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "id secret key"


def test_config_raises_when_required_env_var_missing_outside_pytest() -> None:
    # Import cairn.config from a subprocess with no `pytest` in sys.modules, so
    # the module's own test-context detection doesn't suppress the failure —
    # this reproduces what happens if the app boots with a missing secret.
    env = {k: v for k, v in os.environ.items() if k not in _REQUIRED_VARS}
    result = subprocess.run(
        [sys.executable, "-c", "import cairn.config"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "GOOGLE_CLIENT_ID must be set" in result.stderr
