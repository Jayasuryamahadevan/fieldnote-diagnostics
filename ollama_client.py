"""Compatibility re-export. Prefer ``from fieldnote.ollama_client import ...``."""

from fieldnote.ollama_client import (
    DEFAULT_MODEL,
    OllamaError,
    ask,
    available,
    chat,
    default_model,
    host,
    list_models,
    server_status,
)

__all__ = [
    "DEFAULT_MODEL",
    "OllamaError",
    "ask",
    "available",
    "chat",
    "default_model",
    "host",
    "list_models",
    "server_status",
]
