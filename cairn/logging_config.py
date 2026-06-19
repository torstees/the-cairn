import json
import logging
import logging.config
import os
import sys
from pathlib import Path

try:
    from rich.logging import RichHandler as _RichHandler  # noqa: F401

    _IS_RICH = True
except ImportError:
    _IS_RICH = False


def is_cloud() -> bool:
    """Detect GCP environment (Cloud Run, GCE, App Engine, Cloud Jobs)."""
    return any(os.environ.get(v) for v in ("K_SERVICE", "K_REVISION", "GOOGLE_CLOUD_PROJECT", "GAE_APPLICATION"))


def is_interactive() -> bool:
    if hasattr(sys, "ps1"):
        return True
    try:
        return os.isatty(sys.stdin.fileno())
    except Exception:
        # stdin may not be a real fd under Docker, systemd, or a web server
        return False


class GCPJsonFormatter(logging.Formatter):
    """Emits one JSON object per line for Cloud Logging structured log ingestion.

    GCP expects 'severity' (not 'levelname'). Any extra fields passed via
    logger.info("msg", extra={"tune_id": 1}) are included as top-level keys
    and become indexed fields in Cloud Logging.
    """

    _STANDARD_ATTRS = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS:
                payload[key] = value
        return json.dumps(payload)


def setup_logging(level: str | None = None, log_file: str | None = None) -> None:
    """Configure logging for the current environment.

    - Cloud (GCP): structured JSON to stdout for Cloud Logging ingestion.
    - Local interactive shell with rich installed: rich pretty-printer.
    - Everything else: plain timestamped text.

    level defaults to the CAIRN_LOG_LEVEL env var, then INFO.
    log_file is ignored in cloud environments.
    """
    effective_level = level or os.environ.get("CAIRN_LOG_LEVEL", "INFO").upper()
    cloud = is_cloud()
    use_rich = not cloud and is_interactive() and _IS_RICH

    config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "rich": {"datefmt": "%H:%M:%S"},
            "detailed": {"format": "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"},
            "json": {"()": "cairn.logging_config.GCPJsonFormatter"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if cloud else "detailed",
                "level": effective_level,
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": effective_level,
        },
        "loggers": {
            # uvicorn.access is replaced by our request middleware
            "uvicorn.access": {"level": "WARNING", "propagate": False},
        },
    }

    if use_rich:
        config["handlers"]["console"].update(
            {
                "class": "rich.logging.RichHandler",
                "formatter": "rich",
                "rich_tracebacks": True,
                "markup": True,
            }
        )

    if log_file and not cloud:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        config["handlers"]["file"] = {
            "class": "logging.FileHandler",
            "filename": log_file,
            "formatter": "detailed",
            "level": effective_level,
        }
        config["root"]["handlers"].append("file")

    logging.config.dictConfig(config)

    mode = "cloud/JSON" if cloud else ("rich" if use_rich else "text")
    logging.getLogger(__name__).debug("Logging initialised in %s mode at %s", mode, effective_level)
