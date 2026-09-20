"""
Thin adapter between the annotation/morality engines and the active Ollama model.

The active model is set once at startup from STATE["model_name"] (see main.py);
`ask_model` falls back to the ai_access default if nothing was set.
"""

from __future__ import annotations

from typing import Optional

from .ai_access import DEFAULT_MODEL, chat

_active_model: Optional[str] = None


def set_active_model(model_name: Optional[str]) -> None:
    """Record the model name that `ask_model` should use."""
    global _active_model
    _active_model = model_name or None


def get_active_model() -> str:
    """Return the currently active model name (falls back to ai_access default)."""
    return _active_model or DEFAULT_MODEL


def ask_model(prompt: str, *, model: Optional[str] = None) -> str:
    """
    Send a single user prompt to the active model and return the reply text.

    This is what routes/annotator.py's FeedAnnotationEngine expects.
    """
    resolved = model or get_active_model()
    return chat(prompt, model=resolved).content