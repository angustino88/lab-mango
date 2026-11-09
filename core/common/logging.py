"""Logging support: attach the current request's correlation ID to every log record.

``RequestCorrelationMiddleware`` stores the ID on the request. This module also keeps it in a
context variable so log lines written anywhere during the request (services, queries, signals) can
be joined to the response's ``X-Request-ID`` header and error envelope.
"""

import logging
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def current_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Add ``record.request_id`` so formatters can use ``%(request_id)s``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


__all__ = ["RequestIdFilter", "current_request_id", "set_request_id"]
