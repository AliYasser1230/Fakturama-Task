from __future__ import annotations

import time
from typing import Callable, TypeVar

from image_to_cash.errors import ControlNotFound, VerificationFailed, WaitTimeout

T = TypeVar("T")

TRANSIENT_UI_ERRORS = {"COMError", "ElementNotAvailable", "ElementNotEnabled", "ElementNotVisible"}


def is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (ControlNotFound, VerificationFailed)) or type(exc).__name__ in TRANSIENT_UI_ERRORS


def wait_until(
    condition: Callable[[], T],
    *,
    timeout: float,
    what: str,
    interval: float = 0.2,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    deadline = clock() + timeout
    last_error: BaseException | None = None
    while True:
        try:
            result = condition()
        except Exception as exc:
            if not is_transient(exc):
                raise
            last_error = exc
        else:
            if result:
                return result
        if clock() >= deadline:
            detail = f"; last error: {last_error}" if last_error else ""
            raise WaitTimeout(f"waited {timeout:g}s for {what}{detail}")
        sleep(interval)


def wait_stable(
    read: Callable[[], T],
    *,
    timeout: float,
    what: str,
    settle: float = 0.6,
    interval: float = 0.2,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    deadline = clock() + timeout
    last = object()
    since = clock()
    while True:
        try:
            current = read()
        except Exception as exc:
            if not is_transient(exc):
                raise
            current = object()
        now = clock()
        if current != last:
            last, since = current, now
        elif now - since >= settle:
            return current
        if now >= deadline:
            raise WaitTimeout(f"waited {timeout:g}s for {what} to stop changing")
        sleep(interval)
