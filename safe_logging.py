"""Application-wide redaction for credentials embedded in log records."""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from typing import Any


REDACTED = "[REDACTED]"
_TELEGRAM_BOT_PATH = re.compile(r"(?<=/bot)[^/\s?#]+")
_ADAPTY_API_KEY_APP_ENV = re.compile(r"ADAPTY_API_KEY_APP\d+")


def _normalized_secrets(values: Iterable[str]) -> tuple[str, ...]:
    secrets: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        secrets.add(raw)
        parts = raw.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in {"bearer", "token", "api-key"}:
            secrets.add(parts[1].strip())
    return tuple(sorted((item for item in secrets if item), key=len, reverse=True))


class SecretRedactionFilter(logging.Filter):
    """Redact configured secrets before a handler formats a log record."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self.secrets = _normalized_secrets(secrets)

    def redact(self, value: str) -> str:
        text = value
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        return _TELEGRAM_BOT_PATH.sub(REDACTED, text)

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_value(item) for key, item in value.items()}
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact_value(record.msg)
        record.args = self._redact_value(record.args)
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = self.redact(formatted)
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


def configure_secret_redaction(secrets: Iterable[str] | None = None) -> None:
    """Install redaction on every current root handler.

    Call immediately after ``logging.basicConfig`` so application and dependency
    records, including urllib3 retries, are protected.
    """
    if secrets is None:
        secrets = (
            os.getenv("TELEGRAM_BOT_TOKEN", ""),
            os.getenv("ADAPTY_DASHBOARD_TOKEN", ""),
            os.getenv("ADAPTY_ASA_AUTH_TOKEN", ""),
            *(
                value
                for key, value in os.environ.items()
                if _ADAPTY_API_KEY_APP_ENV.fullmatch(key) and value.strip()
            ),
        )
    redaction_filter = SecretRedactionFilter(secrets)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.filters = [
            existing
            for existing in handler.filters
            if not isinstance(existing, SecretRedactionFilter)
        ]
        handler.addFilter(redaction_filter)
