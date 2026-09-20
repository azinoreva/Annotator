"""
ollama_client.py

Production-grade wrapper around the `ollama` Python package.

Responsibilities
----------------
1. Verify that the Ollama runtime is installed and reachable via subprocess.
2. Ensure the requested model is available locally (pull if missing).
3. Provide a single, safe entry point (`chat`) for sending messages to the
   model through `ollama.chat`.

Only `logging` is used for diagnostics — no bare `print` calls.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ollama import chat

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Library-friendly default; the host application can override this.
    _handler = logging.NullHandler()
    logger.addHandler(_handler)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL: str = "llama3.2"
DEFAULT_TIMEOUT: int = 300          # seconds for subprocess calls
DEFAULT_CHAT_TIMEOUT: float = 120.0  # seconds for chat requests


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
# Subprocess helpers
# ---------------------------------------------------------------------------
def _run_ollama_cli(
    args: Sequence[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """
    Execute the `ollama` CLI with the given arguments.

    Raises
    ------
    OllamaNotInstalledError
        If the `ollama` binary is not on PATH.
    OllamaRuntimeError
        On non-zero exit, timeout, or unexpected OS-level failure.
    """
    binary = shutil.which("ollama")
    if binary is None:
        msg = "Ollama CLI not found on PATH. Install from https://ollama.com."
        logger.error(msg)
        raise OllamaNotInstalledError(msg)

    cmd = [binary, *args]
    logger.debug("Executing subprocess: %s", cmd)

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"`ollama {' '.join(args)}` timed out after {timeout}s."
        logger.error(msg)
        raise OllamaRuntimeError(msg) from exc
    except OSError as exc:
        msg = f"OS error while invoking ollama: {exc}"
        logger.exception(msg)
        raise OllamaRuntimeError(msg) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        msg = (
            f"`ollama {' '.join(args)}` failed with exit code "
            f"{completed.returncode}: {stderr or '<no stderr>'}"
        )
        logger.error(msg)
        raise OllamaRuntimeError(msg)

    return completed


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------
def _list_local_models() -> set[str]:
    """Return the set of model names currently available locally."""
    completed = _run_ollama_cli(["list"])
    models: set[str] = set()
    for line in completed.stdout.splitlines()[1:]:  # skip header
        line = line.strip()
        if not line:
            continue
        # First whitespace-delimited token is the model name.
        models.add(line.split()[0])
    logger.debug("Locally available models: %s", models)
    return models


def _model_is_available(model: str) -> bool:
    """Return True when `model` (or a matching tag) is present locally."""
    local = _list_local_models()
    if model in local:
        return True
    # Allow un-tagged references, e.g. "llama3.2" -> "llama3.2:latest".
    base = model.split(":", 1)[0]
    return any(name == base or name.startswith(f"{base}:") for name in local)


def ensure_model(
    model: str = DEFAULT_MODEL,
    *,
    auto_pull: bool = True,
    pull_timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Guarantee that `model` is present locally; pull it if missing.

    Returns
    -------
    str
        The model name that should be used for subsequent calls.

    Raises
    ------
    OllamaClientError
        If the model is unavailable and cannot be pulled.
    """
    if not model or not isinstance(model, str):
        raise ValueError("`model` must be a non-empty string.")

    try:
        if _model_is_available(model):
            logger.info("Model '%s' is available locally.", model)
            return model
    except OllamaClientError:
        # Runtime unreachable — let the caller decide how to react.
        raise

    if not auto_pull:
        msg = f"Model '{model}' is not available locally and auto_pull is disabled."
        logger.error(msg)
        raise OllamaRuntimeError(msg)

    logger.info("Model '%s' not found locally — pulling.", model)
    try:
        _run_ollama_cli(["pull", model], timeout=pull_timeout)
    except OllamaRuntimeError as exc:
        msg = f"Failed to pull model '{model}': {exc}"
        logger.error(msg)
        raise OllamaRuntimeError(msg) from exc

    logger.info("Successfully pulled model '%s'.", model)
    return model


# ---------------------------------------------------------------------------
# Chat entry point
# ---------------------------------------------------------------------------
def chat(
    messages: Sequence[Mapping[str, Any]] | str,
    *,
    model: str = DEFAULT_MODEL,
    auto_pull: bool = True,
    retries: int = 2,
    options: Mapping[str, Any] | None = None,
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
        Number of additional attempts on transient runtime failures.
    options
        Optional Ollama model options (temperature, num_ctx, …).
    **kwargs
        Forwarded verbatim to :func:`ollama.chat`.

    Returns
    -------
    ChatResult
        Normalized result containing the assistant's reply text.

    Raises
    ------
    OllamaChatError
        If all attempts to obtain a completion fail.
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
        resolved_model = ensure_model(model, auto_pull=auto_pull)
    except OllamaClientError as exc:
        raise OllamaChatError(str(exc)) from exc

    last_error: Exception | None = None
    attempts = retries + 1

    for attempt in range(1, attempts + 1):
        try:
            logger.debug(
                "Chat attempt %d/%d using model '%s'.",
                attempt,
                attempts,
                resolved_model,
            )
            response = ollama.chat(
                model=resolved_model,
                messages=normalized,
                options=dict(options) if options else None,
                **kwargs,
            )
            content = _extract_content(response)
            logger.info(
                "Chat succeeded with model '%s' (%d chars).",
                resolved_model,
                len(content),
            )
            return ChatResult(
                content=content,
                model=resolved_model,
                raw=response if isinstance(response, Mapping) else {},
            )
        except (ollama.ResponseError, ollama.RequestError) as exc:
            last_error = exc
            logger.warning(
                "Ollama API error on attempt %d/%d: %s",
                attempt,
                attempts,
                exc,
            )
        except Exception as exc:  # noqa: BLE001 — defensive boundary
            last_error = exc
            logger.exception(
                "Unexpected error on chat attempt %d/%d: %s",
                attempt,
                attempts,
                exc,
            )

    msg = (
        f"Chat failed for model '{resolved_model}' after {attempts} "
        f"attempt(s): {last_error}"
    )
    logger.error(msg)
    raise OllamaChatError(msg) from last_error


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
    # Mapping form (typical for `ollama.chat`).
    if isinstance(response, Mapping):
        message = response.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                return content
        content = response.get("content")
        if isinstance(content, str):
            return content
    # Attribute form (pydantic-style objects in some versions).
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


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
def chat_stream(
    messages: Sequence[Mapping[str, Any]] | str,
    *,
    model: str = DEFAULT_MODEL,
    auto_pull: bool = True,
    options: Mapping[str, Any] | None = None,
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
        resolved_model = ensure_model(model, auto_pull=auto_pull)
    except OllamaClientError as exc:
        raise OllamaChatError(str(exc)) from exc

    try:
        stream = ollama.chat(
            model=resolved_model,
            messages=normalized,
            stream=True,
            options=dict(options) if options else None,
            **kwargs,
        )
        for chunk in stream:
            try:
                yield _extract_content(chunk)
            except OllamaChatError:
                logger.warning("Skipping malformed stream chunk.")
                continue
    except (ollama.ResponseError, ollama.RequestError) as exc:
        logger.error("Streaming chat failed: %s", exc)
        raise OllamaChatError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected streaming error: %s", exc)
        raise OllamaChatError(str(exc)) from exc


__all__ = [
    "ChatResult",
    "DEFAULT_MODEL",
    "OllamaChatError",
    "OllamaClientError",
    "OllamaNotInstalledError",
    "OllamaRuntimeError",
    "chat",
    "chat_stream",
    "ensure_model",
]