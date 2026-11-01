"""Structured JSON logging: one line per event, parseable by machines.

Why JSON and not pretty text: every later chunk correlates an API request, a
worker attempt and a retry with the same ``request_id``/``delivery_id``. Grepping
is for humans; these lines are for the log pipeline and for tests that assert on
what was logged.
"""

from __future__ import annotations

import json
import logging
import sys

# Attributes that LogRecord always carries; everything else in __dict__ is
# context we were handed via `extra=` and should be emitted as a field.
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # Our request middleware already emits one access line with a request_id;
    # uvicorn's own access log would duplicate it without the correlation id.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
