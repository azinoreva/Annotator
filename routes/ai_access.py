"""
routes/ai_access.py

Production-grade wrapper around the `ollama` Python package.

Responsibilities
----------------
1. Provide a single, bounded availability probe (`runtime_available`) so the
   host app can decide "is Ollama reachable?" without hanging.
2. Ensure a requested model is pulled locally via the HTTP API (no shelling
   out to the CLI on every call), using a short-lived TTL cache for speed.
3. Expose `chat` / `chat_stream` with an explicit timeout, retries that only
   cover *transient* failures, and exponential backoff + jitter — never a
   busy-spin.

Design notes
------------
- One shared ``ollama.Client`` per host + timeout tier, built lazily behind a
  lock (the worker calls ``chat`` from ``asyncio.to_thread``).
- No name shadowing of the `ollama` API (the previous version rebound the
  imported `chat` symbol with its wrapper, silently recursing forever).
- Every outbound call is bounded by an ``httpx`` timeout. Ollama's default is
  ``timeout=None`` (block forever), which made the old availability loop hang.
- Only `logging` is used for diagnostics — no bare `print` calls.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import httpx
import ollama
from ollama import ResponseError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Library-friendly default; the host application can override this.
    logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST_ENV = "OLLAMA_HOST"
DEFAULT_HOST = "http://127.0.0.1:11434"

DEFAULT_MODEL: str = "llama3.2"

# httpx timeouts (seconds). These are the real bound on every HTTP call.
CONNECT_TIMEOUT: float = 5.0      # dialing the socket must not take forever
REQUEST_TIMEOUT: float = 120.0    # ordinary chat / list requests
PULL_TIMEOUT: float = 3600.0      # model pulls can legitimately run long
PROBE_TIMEOUT: float = 5.0        # availability probe is deliberately short

# Availability check caching: positive answers are trusted longer, negative
# ones expire fast so a recovering daemon is noticed quickly.
AVAILABILITY_TTL: float = 60.0
NEGATIVE_TTL: float = 15.0

RETRY_BASE_DELAY: float = 0.5    # exponential backoff base (seconds)
RETRY_MAX_DELAY: float = 8.0     # backoff cap
RETRY_JITTER: float = 0.25       # fraction of delay added/removed randomly

# HTTP statuses that are worth retrying. 4xx (except 408/429) are permanent
# client errors — retrying a 401 or a bad request forever is a busy-loop.
_TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Statuses that mean "this value of `model` will never work" — fail fast.
_BAD_REQUEST_STATUSES = frozenset({400, 401, 403, 404, 409, 422})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class OllamaClientError(RuntimeError):
    """Base exception raised for all client-level failures."""


class OllamaNotInstalledError(OllamaClientError):
    """Raised when the `ollama` binary cannot be located on PATH."""


class OllamaRuntimeError(OllamaClientError):
    """Raised when the Ollama runtime or model operations fail."""


class OllamaChatError(OllamaClientError):
    """Raised when a chat completion fails after retries."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChatResult:
    """Normalized result returned by :func:`chat`."""

    content: str
    model: str
    raw: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared clients (thread-safe, lazily created, cached per host + tier)
# ---------------------------------------------------------------------------
_client_lock: threading.Lock = threading.Lock()
_request_client: dict[str, ollama.Client] = {}      # REQUEST_TIMEOUT
_pull_client: dict[str, ollama.Client] = {}         # PULL_TIMEOUT
_probe_client: dict[str, ollama.Client] = {}        # PROBE_TIMEOUT


def _normalize_host(host: str | None) -> str:
    return host or os.getenv(HOST_ENV) or DEFAULT_HOST


def _get_client(host: str | None) -> ollama.Client:
    base = _normalize_host(host)
    with _client_lock:
        client = _request_client.get(base)
        if client is None:
            client = ollama.Client(
                host=base,
                timeout=httpx.Timeout(
                    REQUEST_TIMEOUT,
                    connect=CONNECT_TIMEOUT,
                ),
            )
            _request_client[base] = client
        return client


def _get_pull_client(host: str | None) -> ollama.Client:
    base = _normalize_host(host)
    with _client_lock:
        client = _pull_client.get(base)
        if client is None:
            client = ollama.Client(
                host=base,
                timeout=httpx.Timeout(PULL_TIMEOUT, connect=CONNECT_TIMEOUT),
            )
            _pull_client[base] = client
        return client


def _get_probe_client(host: str | None) -> ollama.Client:
    base = _normalize_host(host)
    with _client_lock:
        client = _probe_client.get(base)
        if client is None:
            # Uniform short timeout: a stuck daemon must fail fast here.
            client = ollama.Client(
                host=base,
                timeout=httpx.Timeout(PROBE_TIMEOUT),
            )
            _probe_client[base] = client
        return client


# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------
def runtime_available(host: str | None = None) -> bool:
    """
    Return True when the Ollama runtime responds on ``host``.

    Bounded by ``PROBE_TIMEOUT`` and never raises — callers can safely poll
    this from a loop without hanging the event loop or a thread.
    """
    try:
        _get_probe_client(host).list()
        return True
    except Exception:  # noqa: BLE001 — probing is intentionally total
        logger.debug("Ollama runtime not available on %s.", _normalize_host(host))
        return False


# ---------------------------------------------------------------------------
# Model management (HTTP API + TTL cache, no subprocess per call)
# ---------------------------------------------------------------------------
_availability_cache: dict[str, tuple[bool, float]] = {}


def _model_is_available(model: str, host: str | None) -> bool:
    """Return True when `model` (or its un-tagged base) is present locally.

    Cached for ``AVAILABILITY_TTL`` (or ``NEGATIVE_TTL`` on failure) so the
    steady-state path does not hit the HTTP API on every single message.
    """
    base_host = _normalize_host(host)
    key = f"{base_host}|{model}"
    with _client_lock:
        cached = _availability_cache.get(key)
        if cached is not None:
            available, checked_at = cached
            ttl = AVAILABILITY_TTL if available else NEGATIVE_TTL
            if time.monotonic() - checked_at < ttl:
                return available

    available = False
    try:
        listing = _get_client(host).list()
        local: set[str] = set()
        for m in getattr(listing, "models", None) or []:
            name = getattr(m, "model", None)
            if isinstance(name, str):
                local.add(name)
            elif isinstance(m, Mapping):
                name = m.get("model") or m.get("name")
                if isinstance(name, str):
                    local.add(name)
        base = model.split(":", 1)[0]
        available = model in local or any(
            name == base or name.startswith(f"{base}:") for name in local
        )
    except Exception as exc:  # noqa: BLE001 — negative result, don't raise
        logger.debug("Model availability check failed: %s", exc)

    with _client_lock:
        _availability_cache[key] = (available, time.monotonic())
    return available


def _pull_model(model: str, host: str | None) -> None:
    """Pull `model` through the HTTP API (never the CLI)."""
    for chunk in _get_pull_client(host).pull(model, stream=True):
        err = getattr(chunk, "error", None)
        if err is None and isinstance(chunk, Mapping):
            err = chunk.get("error")
        if err:
            raise OllamaRuntimeError(
                f"Failed to pull model '{model}': {err}"
            )
        status = getattr(chunk, "status", None)
        if status is None and isinstance(chunk, Mapping):
            status = chunk.get("status")
        if status:
            logger.info("  pull: %s", status)


def ensure_model(
    model: str = DEFAULT_MODEL,
    *,
    auto_pull: bool = True,
    pull_timeout: float | None = None,
    host: str | None = None,
) -> str:
    """
    Guarantee that `model` is present locally; pull it if missing.

    Returns
    -------
    str
        The model name that should be used for subsequent calls.

    Raises
    ------
    OllamaRuntimeError
        If the runtime is unreachable, or the model cannot be pulled.
    """
    del pull_timeout  # kept for back-compat; the client governs the timeout
    if not model or not isinstance(model, str):
        raise ValueError("`model` must be a non-empty string.")

    if _model_is_available(model, host):
        logger.info("Model '%s' is available locally.", model)
        return model

    if not auto_pull:
        raise OllamaRuntimeError(
            f"Model '{model}' is not available locally and auto_pull is disabled."
        )

    logger.info("Model '%s' not found locally — pulling.", model)
    _pull_model(model, host)
    logger.info("Successfully pulled model '%s'.", model)

    # Refresh the cache so the very next call does not re-list.
    with _client_lock:
        _availability_cache[f"{_normalize_host(host)}|{model}"] = (
            True,
            time.monotonic(),
        )
    return model


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------
def _is_transient(exc: Exception) -> bool:
    """Return True when a retry is reasonable for this exception."""
    if isinstance(exc, ConnectionError):
        return True  # ollama Client wraps httpx.ConnectError into this
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, ResponseError):
        return exc.status_code in _TRANSIENT_STATUSES
    return False


def _is_permanent(exc: Exception) -> bool:
    """Return True when retrying can never help (fail fast)."""
    if isinstance(exc, ResponseError):
        return exc.status_code in _BAD_REQUEST_STATUSES
    return False


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter; bounded."""
    base = min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * (2 ** (attempt - 1)))
    jitter = 1.0 + random.uniform(-RETRY_JITTER, RETRY_JITTER)
    return max(0.05, base * jitter)


def _raise_chat_error(model: str, attempts: int, last_error: Exception) -> None:
    msg = (
        f"Chat failed for model '{model}' after {attempts} attempt(s): "
        f"{last_error}"
    )
    logger.error(msg)
    raise OllamaChatError(msg) from last_error


# ---------------------------------------------------------------------------
# Chat entry point
# ---------------------------------------------------------------------------
def _iter_chat(
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str,
    options: Mapping[str, Any] | None,
    host: str | None,
    **kwargs: Any,
) -> Iterable[str]:
    """
    Yield content chunks from a *streaming* chat completion.

    Streaming means the httpx read timeout is enforced *between tokens*,
    not across the whole response, so a slow-but-progressing generation
    (common for small local models) is no longer killed by a fixed wall
    clock. Underlying errors (httpx timeouts, ResponseError, ...) propagate
    unchanged so callers can classify them for retries.
    """
    stream = _get_client(host).chat(
        model=model,
        messages=messages,
        stream=True,
        options=dict(options) if options else None,
        **kwargs,
    )
    for chunk in stream:
        try:
            content = _extract_content(chunk)
        except OllamaChatError:
            # Ollama emits a trailing "done" chunk that carries no content.
            continue
        if content:
            yield content


def chat(
    messages: Sequence[Mapping[str, Any]] | str,
    *,
    model: str = DEFAULT_MODEL,
    auto_pull: bool = True,
    retries: int = 2,
    options: Mapping[str, Any] | None = None,
    host: str | None = None,
    **kwargs: Any,
) -> ChatResult:
    """
    Send one or more messages to `model` and return the assistant reply.

    Parameters
    ----------
    messages
        Either a string (converted to a single user message) or a sequence of
        Ollama-style message dicts, e.g. ``[{"role": "user", "content": "hi"}]``.
    model
        Name of the model to use. Pulled automatically if missing and
        ``auto_pull`` is True.
    auto_pull
        Whether to pull the model if it is not already available locally.
    retries
        Number of additional attempts on *transient* failures. Permanent
        (4xx) errors fail immediately without burning the retry budget.
    options
        Optional Ollama model options (temperature, num_ctx, …).
    host
        Ollama base URL. Defaults to ``$OLLAMA_HOST`` then
        :data:`DEFAULT_HOST`.
    **kwargs
        Forwarded verbatim to :func:`ollama.chat`.

    Internally the completion is requested as a *stream* and accumulated, so
    the httpx read timeout applies between tokens rather than to the whole
    generation.

    Returns
    -------
    ChatResult
        Normalized result containing the assistant's reply text.

    Raises
    ------
    OllamaChatError
        If no non-transient success is obtained within the retry budget.
    """
    if isinstance(messages, str):
        normalized: list[Mapping[str, Any]] = [
            {"role": "user", "content": messages}
        ]
    else:
        normalized = list(messages)

    if not normalized:
        raise ValueError("`messages` must contain at least one message.")
    if retries < 0:
        raise ValueError("`retries` must be >= 0.")

    # ---- Ensure model availability (fail fast before entering retry loop) --
    try:
        resolved_model = ensure_model(model, auto_pull=auto_pull, host=host)
    except OllamaClientError as exc:
        raise OllamaChatError(str(exc)) from exc

    attempts = retries + 1
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            logger.debug(
                "Chat attempt %d/%d using model '%s'.",
                attempt,
                attempts,
                resolved_model,
            )
            parts: list[str] = []
            for chunk in _iter_chat(
                normalized,
                model=resolved_model,
                options=options,
                host=host,
                **kwargs,
            ):
                parts.append(chunk)
            content = "".join(parts)
            if not content:
                raise RuntimeError("Model returned an empty response.")
            logger.info(
                "Chat succeeded with model '%s' (%d chars).",
                resolved_model,
                len(content),
            )
            return ChatResult(
                content=content,
                model=resolved_model,
                raw={"content": content},
            )
        except Exception as exc:  # noqa: BLE001 — normalize & classify
            last_error = exc
            if _is_permanent(exc):
                logger.error(
                    "Permanent error on chat attempt %d/%d: %s",
                    attempt,
                    attempts,
                    exc,
                )
                break
            if not _is_transient(exc):
                logger.error(
                    "Non-retryable error on chat attempt %d/%d: %s",
                    attempt,
                    attempts,
                    exc,
                )
                break
            logger.warning(
                "Transient error on chat attempt %d/%d: %s",
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                time.sleep(_backoff_delay(attempt))

    _raise_chat_error(resolved_model, attempts, last_error or RuntimeError("unknown"))
    # Unreachable — _raise_chat_error always raises.  (Kept for type checkers.)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------
def chat_stream(
    messages: Sequence[Mapping[str, Any]] | str,
    *,
    model: str = DEFAULT_MODEL,
    auto_pull: bool = True,
    options: Mapping[str, Any] | None = None,
    host: str | None = None,
    **kwargs: Any,
) -> Iterable[str]:
    """
    Yield incremental content chunks from a streaming chat completion.

    Errors encountered mid-stream are logged and terminate iteration; callers
    that need exceptions should use :func:`chat` instead.
    """
    if isinstance(messages, str):
        normalized: list[Mapping[str, Any]] = [
            {"role": "user", "content": messages}
        ]
    else:
        normalized = list(messages)

    if not normalized:
        raise ValueError("`messages` must contain at least one message.")

    try:
        resolved_model = ensure_model(model, auto_pull=auto_pull, host=host)
    except OllamaClientError as exc:
        raise OllamaChatError(str(exc)) from exc

    try:
        for chunk in _iter_chat(
            normalized,
            model=resolved_model,
            options=options,
            host=host,
            **kwargs,
        ):
            yield chunk
    except (ResponseError, ConnectionError) as exc:
        logger.error("Streaming chat failed: %s", exc)
        raise OllamaChatError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected streaming error: %s", exc)
        raise OllamaChatError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------
def _extract_content(response: Any) -> str:
    """
    Pull the assistant's textual content out of an Ollama chat response.

    Supports both mapping-style (`response["message"]["content"]`) and
    attribute-style (`response.message.content`) shapes, across ollama-py
    versions.
    """
    # Mapping form (typical for `ollama.chat` / older clients).
    if isinstance(response, Mapping):
        message = response.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                return content
        content = response.get("content")
        if isinstance(content, str):
            return content
    # Attribute form (pydantic-style objects in modern versions);
    # ChatResponse.message is a pydantic Message, so .content works.
    message = getattr(response, "message", None)
    if message is not None:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content

    msg = f"Unrecognized Ollama response shape: {type(response).__name__}"
    logger.error(msg)
    raise OllamaChatError(msg)


__all__ = [
    "ChatResult",
    "DEFAULT_HOST",
    "DEFAULT_MODEL",
    "OllamaChatError",
    "OllamaClientError",
    "OllamaNotInstalledError",
    "OllamaRuntimeError",
    "chat",
    "chat_stream",
    "ensure_model",
    "runtime_available",
]