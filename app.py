"""Compatibility ASGI target for ``uvicorn app:app``.

Prefer ``uvicorn fieldnote.app:app`` or ``fieldnote serve``.
"""

from fieldnote.app import app

__all__ = ["app"]
