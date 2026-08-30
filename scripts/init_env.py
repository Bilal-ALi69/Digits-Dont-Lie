#!/usr/bin/env python3
"""Create Backend/.env and Frontend/.env.local from their templates.

Called by every platform setup script, so the rules live in one place.

Two things matter here and are easy to get wrong:

1. An existing value is never overwritten. Re-running setup on a machine that
   already has a working Groq key must not wipe it.
2. The backend's API_KEY and the frontend's BACKEND_API_KEY must be the same
   string, or every proxied request answers 401. They are generated together.

Prints the same ::marker protocol the shell scripts use, so its progress
appears in the launcher's live view.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = ROOT / "Backend" / ".env"
BACKEND_EXAMPLE = ROOT / "Backend" / ".env.example"
FRONTEND_ENV = ROOT / "Frontend" / ".env.local"
FRONTEND_EXAMPLE = ROOT / "Frontend" / ".env.local.example"


def marker(kind: str, text: str = "") -> None:
    print(f"::{kind} {text}".rstrip(), flush=True)


def read_value(path: Path, key: str) -> str | None:
    """Current value of `key`, or None if the file or the key is absent."""
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def set_value(path: Path, key: str, value: str) -> None:
    """Set `key` in-place, preserving comments and ordering."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.partition("=")[0].strip() == key:
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_from_template(env: Path, template: Path) -> bool:
    """Create `env` from `template` if absent. True if it was created."""
    if env.is_file():
        return False
    if not template.is_file():
        marker("fail", f"missing template: {template.relative_to(ROOT)}")
        raise SystemExit(1)
    env.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        env.chmod(0o600)  # best effort; a no-op on Windows
    except OSError:
        pass
    return True


def main() -> int:
    marker("step", "Environment files")

    created = []
    if ensure_from_template(BACKEND_ENV, BACKEND_EXAMPLE):
        created.append("Backend/.env")
    if ensure_from_template(FRONTEND_ENV, FRONTEND_EXAMPLE):
        created.append("Frontend/.env.local")

    api_key = read_value(BACKEND_ENV, "API_KEY") or ""
    generated = False
    if not api_key:
        api_key = secrets.token_urlsafe(32)
        set_value(BACKEND_ENV, "API_KEY", api_key)
        generated = True

    # The frontend proxy must present exactly the key the backend expects.
    if read_value(FRONTEND_ENV, "BACKEND_API_KEY") != api_key:
        set_value(FRONTEND_ENV, "BACKEND_API_KEY", api_key)

    if not read_value(FRONTEND_ENV, "BACKEND_URL"):
        set_value(FRONTEND_ENV, "BACKEND_URL", "http://127.0.0.1:8000")

    notes = []
    if created:
        notes.append("created " + ", ".join(created))
    else:
        notes.append("already present, left alone")
    if generated:
        notes.append("generated API_KEY")
    marker("ok", "; ".join(notes))

    if not read_value(BACKEND_ENV, "GROQ_API_KEY"):
        marker(
            "info",
            "GROQ_API_KEY is empty - AI explanations stay off until you set it in Backend/.env",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
