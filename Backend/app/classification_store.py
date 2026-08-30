"""In-memory store for classification tokens used in the two-stage classify→confirm flow."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


_EXPIRY_SECONDS = 10 * 60  # 10 minutes


@dataclass
class _Entry:
    candidate_types: list[str]
    created_at: float = field(default_factory=time.monotonic)


_store: dict[str, _Entry] = {}


def _sweep() -> None:
    """Remove expired entries. Called opportunistically on each store operation."""
    now = time.monotonic()
    expired = [k for k, v in _store.items() if now - v.created_at > _EXPIRY_SECONDS]
    for k in expired:
        del _store[k]


def store_classification(candidate_types: list[str]) -> str:
    """Store candidate type strings and return an opaque token."""
    _sweep()
    token = secrets.token_urlsafe(16)
    _store[token] = _Entry(candidate_types=list(candidate_types))
    return token


def validate_classification(token: str, confirmed_type: str) -> str | None:
    """Validate that *confirmed_type* is among the stored candidates for *token*.

    Returns ``None`` on success, or a human-readable error string on failure.
    """
    _sweep()
    entry = _store.get(token)
    if entry is None:
        return "Unknown or expired classification_id. Run /api/classify first."
    if confirmed_type not in entry.candidate_types:
        return (
            f"Confirmed type '{confirmed_type}' was not among the classification "
            f"candidates: {entry.candidate_types}"
        )
    return None
