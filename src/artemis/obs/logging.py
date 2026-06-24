"""Structured JSON logging with no-PII redaction for Artemis observability."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from artemis.config import Settings
from artemis.paths import slot_root

REDACTED = "***REDACTED***"
_SECRET_KEY_NAMES = {
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "bearer",
    "dek",
    "ref",
    "handle",
    "credential",
}
_CONTENT_KEY_NAMES = {"content", "request_text", "text", "prompt", "messages", "response"}
_BLOB_RE = re.compile(r"^[A-Za-z0-9+/=_-]+$")
_CONFIGURED = False

_RESERVED_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


def obs_dir(s: Settings) -> Path:
    """Return the per-slot observability directory without creating it."""
    return slot_root(s) / "obs"


def redact(value: object) -> object:
    """Redact secret-shaped values and drop content fields recursively.

    Key-name rules are the primary control. The base64/hex-like string boundary
    is defence-in-depth for accidental raw credential values.
    """
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, str):
        if len(value) >= 20 and _BLOB_RE.fullmatch(value):
            return REDACTED
        value = re.sub(r"[A-Za-z0-9+/=_-]{20,}", REDACTED, value)
        return value
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            key_name = str(key).lower()
            if key_name in _CONTENT_KEY_NAMES:
                continue
            if any(secret in key_name for secret in _SECRET_KEY_NAMES):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _json_safe(value: object) -> object:
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


class JsonFormatter(logging.Formatter):
    """Format log records as one redacted JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = record.getMessage()
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": _json_safe(redact(rendered)),
        }
        extras: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key in _CONTENT_KEY_NAMES:
                continue
            extras[key] = _json_safe(redact(value))
        if extras:
            payload["extra"] = extras
        if record.exc_info is not None:
            exc_type, exc, _traceback = record.exc_info
            type_name = exc_type.__name__ if exc_type is not None else "Exception"
            payload["error"] = f"{type_name}: {str(redact(str(exc)))[:200]}"
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class RedactionFilter(logging.Filter):
    """Mutate log records so content fields are dropped and secrets redacted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            redacted_args = redact(record.args)
            if isinstance(redacted_args, tuple):
                record.args = redacted_args
            elif isinstance(redacted_args, Mapping):
                record.args = {str(key): value for key, value in redacted_args.items()}
            else:
                record.args = (redacted_args,)
        for key in list(record.__dict__):
            if key in _RESERVED_RECORD_ATTRS:
                continue
            if key in _CONTENT_KEY_NAMES:
                delattr(record, key)
            else:
                setattr(record, key, redact(getattr(record, key)))
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure idempotent stdout JSON logging for the root logger."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root.handlers = [handler]
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return an Artemis-scoped logger."""
    return logging.getLogger(f"artemis.{name}")
