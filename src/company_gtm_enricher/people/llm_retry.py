"""Bounded retries for a single model request; response validation stays outside."""
from __future__ import annotations

from collections.abc import Callable
import time
from typing import TypeVar

from openai import APIConnectionError, APITimeoutError

from .providers import FatalProviderError


_Response = TypeVar("_Response")


def _value(value: object, key: str):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _is_transient(error: Exception) -> bool:
    if isinstance(error, FatalProviderError):
        return False
    body = _value(error, "body")
    codes = (
        _value(error, "code"),
        _value(body, "code"),
        _value(_value(body, "error"), "code"),
    )
    if any(code == "insufficient_quota" for code in codes):
        return False
    status = _value(error, "status_code")
    if type(status) is int and status in (400, 401, 403, 404):
        return False
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return True
    return type(status) is int and (status in (408, 409, 429) or 500 <= status <= 599)


def call_with_retries(
    call: Callable[[], _Response],
    *,
    max_retries: int = 2,
    before_attempt: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> _Response:
    """Make at most three calls, counting every attempt and preserving final errors.

    ``call`` should contain only the SDK request, with SDK retries disabled.
    Responses, including refusals or incomplete output, return unchanged so their
    validation cannot accidentally spend additional requests. Failed attempts
    wait one and then two seconds; errors and response bodies are never logged.
    """
    if type(max_retries) is not int or not 0 <= max_retries <= 2:
        raise ValueError("Model request retries must be an integer from 0 to 2.")
    if not callable(call):
        raise ValueError("Model request must be callable.")
    if before_attempt is not None and not callable(before_attempt):
        raise ValueError("The attempt callback must be callable or None.")
    if not callable(sleep):
        raise ValueError("The retry sleep function must be callable.")

    retries = 0
    while True:
        if before_attempt is not None:
            before_attempt()
        try:
            return call()
        except Exception as error:
            if retries >= max_retries or not _is_transient(error):
                raise
            sleep(2 ** retries)
            retries += 1
