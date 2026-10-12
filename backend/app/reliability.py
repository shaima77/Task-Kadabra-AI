"""Retry / timeout / fallback wrapper used by every fallible step.

`run_step` gives each step three guarantees:
  - a per-attempt **timeout** (so a slow search or reasoning call can't hang the request),
  - a bounded number of **retries** (default 3, from settings),
  - a deterministic **fallback** used when all attempts fail — so the journey degrades
    gracefully instead of 500-ing.

A `validate` callback lets a *deterministic* check reject a bad result and trigger a retry.
Pairing validation with a fallback is what reduces wasted LLM calls: once we've retried a
bounded number of times, we stop calling the model and use a cheap deterministic result.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("datafinder.reliability")

_UNSET = object()


class StepFailed(RuntimeError):
    """Raised when a step exhausts its retries and no fallback was provided."""


class ValidationFailure(RuntimeError):
    """A result was produced but failed deterministic validation; retryable."""


async def run_step(
    factory: Callable[[], Awaitable[Any]],
    *,
    label: str,
    attempts: int = 3,
    timeout: Optional[float] = None,
    validate: Optional[Callable[[Any], list[str]]] = None,
    fallback: Any = _UNSET,
) -> Any:
    """Run `factory()` up to `attempts` times.

    factory   : zero-arg callable returning a fresh awaitable each attempt.
    timeout   : seconds for a single attempt (None = no timeout).
    validate  : returns a list of error strings; non-empty -> retry.
    fallback  : value, or (sync/async) callable, used if all attempts fail.
                If omitted, StepFailed is raised instead.
    """
    attempts = max(1, attempts)
    last_error: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            awaitable = factory()
            result = await (asyncio.wait_for(awaitable, timeout) if timeout else awaitable)

            if validate is not None:
                errors = validate(result)
                if errors:
                    raise ValidationFailure(f"{label}: {', '.join(errors)}")

            if attempt > 1:
                log.info("step '%s' recovered on attempt %d/%d", label, attempt, attempts)
            return result

        except asyncio.TimeoutError as exc:
            last_error = exc
            log.warning("step '%s' attempt %d/%d timed out after %ss", label, attempt, attempts, timeout)
        except ValidationFailure as exc:
            last_error = exc
            log.warning("step '%s' attempt %d/%d invalid: %s", label, attempt, attempts, exc)
        except Exception as exc:  # noqa: BLE001 - we genuinely want to retry on anything
            last_error = exc
            log.warning("step '%s' attempt %d/%d errored: %s", label, attempt, attempts, exc)

        if attempt < attempts:
            await asyncio.sleep(min(0.4 * attempt, 1.5))  # brief backoff

    if fallback is not _UNSET:
        log.error("step '%s' failed after %d attempts (%s); using fallback",
                  label, attempts, last_error)
        value = fallback() if callable(fallback) else fallback
        if inspect.isawaitable(value):
            value = await value
        return value

    raise StepFailed(f"step '{label}' failed after {attempts} attempts: {last_error}") from last_error
