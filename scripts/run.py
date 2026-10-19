#!/usr/bin/env python3
"""Digits Dont Lie - start both servers with one command.

Usage:

    python3 scripts/run.py            production build, the one to demo with
    python3 scripts/run.py --dev      Next.js dev server with hot reload
    python3 scripts/run.py --rebuild  force a fresh production build first
    python3 scripts/run.py --backend-only
    python3 scripts/run.py --frontend-only

Backend  http://127.0.0.1:8000   (FastAPI, uvicorn)
Frontend http://localhost:3000   (Next.js)

Ctrl+C stops both. Run scripts/setup.py first if either tree is missing its
dependencies; this script only starts what is already installed.

Standard library only, on purpose - it must run before anyone has activated
a virtualenv.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "Backend"
FRONTEND = PROJECT_ROOT / "Frontend"
WINDOWS = os.name == "nt"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = "8000"
# Next reads PORT itself; mirror it so the banner matches where it lands.
FRONTEND_PORT = os.environ.get("PORT", "3000")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def info(msg: str) -> None:
    print(_paint("  ->", "36") + f" {msg}", flush=True)


def fail(msg: str) -> None:
    print(_paint("  !!", "31") + f" {msg}", file=sys.stderr, flush=True)


def _pump(stream, label: str, colour: str) -> None:
    """Copy one child's output to ours, a line at a time, tagged."""
    tag = _paint(f"[{label}]", colour)
    for line in iter(stream.readline, ""):
        print(f"{tag} {line.rstrip()}", flush=True)
    stream.close()


# ---------------------------------------------------------------------------
# Locating what setup.py installed
# ---------------------------------------------------------------------------


def venv_python() -> Path | None:
    exe = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    return exe if exe.exists() else None


def npm() -> str | None:
    # npm ships as npm.cmd on Windows, which subprocess will not find bare.
    return shutil.which("npm.cmd") if WINDOWS else shutil.which("npm")


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def spawn(cmd: list[str], cwd: Path, label: str, colour: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # Keep Ctrl+C from reaching the children directly; we stop them in
        # order ourselves so the shutdown output stays readable.
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
        start_new_session=not WINDOWS,
    )
    threading.Thread(
        target=_pump, args=(proc.stdout, label, colour), daemon=True
    ).start()
    return proc


def stop(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is not None:
        return
    info(f"stopping {label}")
    try:
        if WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def build_frontend(npm_bin: str) -> bool:
    info("building the frontend (first run takes a minute)")
    return subprocess.run([npm_bin, "run", "build"], cwd=str(FRONTEND)).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the Digits Dont Lie backend and frontend."
    )
    parser.add_argument(
        "--dev", action="store_true", help="Next.js dev server instead of the build"
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="rebuild the frontend before starting"
    )
    parser.add_argument("--backend-only", action="store_true", help="skip the frontend")
    parser.add_argument("--frontend-only", action="store_true", help="skip the backend")
    args = parser.parse_args()

    want_backend = not args.frontend_only
    want_frontend = not args.backend_only

    python = venv_python()
    if want_backend and python is None:
        fail(f"no virtualenv at {BACKEND / '.venv'} - run: python3 scripts/setup.py")
        return 1

    npm_bin = npm()
    if want_frontend:
        if npm_bin is None:
            fail("npm not found on PATH - run: python3 scripts/setup.py")
            return 1
        if not (FRONTEND / "node_modules").is_dir():
            fail("Frontend/node_modules is missing - run: python3 scripts/setup.py")
            return 1

    # A production build is what a demo should be served from: dev mode
    # compiles each route on first visit, which stalls the opening click.
    if want_frontend and not args.dev:
        if args.rebuild or not (FRONTEND / ".next").is_dir():
            if not build_frontend(npm_bin):
                fail("frontend build failed")
                return 1

    running: list[tuple[subprocess.Popen, str]] = []

    if want_backend:
        info(f"backend  http://{BACKEND_HOST}:{BACKEND_PORT}")
        running.append(
            (
                spawn(
                    [
                        str(python),
                        "-m",
                        "uvicorn",
                        "app.api.server:app",
                        "--host",
                        BACKEND_HOST,
                        "--port",
                        BACKEND_PORT,
                    ],
                    BACKEND,
                    "backend",
                    "35",
                ),
                "backend",
            )
        )

    if want_frontend:
        info(f"frontend http://localhost:{FRONTEND_PORT}")
        running.append(
            (
                spawn(
                    [npm_bin, "run", "dev" if args.dev else "start"],
                    FRONTEND,
                    "frontend",
                    "34",
                ),
                "frontend",
            )
        )

    info("Ctrl+C to stop")

    exit_code = 0
    try:
        # Wait on whichever child exits first; if one dies the pair is no
        # longer useful, so take the other down with it.
        while True:
            for proc, label in running:
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    continue
                if proc.returncode != 0:
                    fail(f"{label} exited with code {proc.returncode}")
                    exit_code = proc.returncode
                else:
                    info(f"{label} exited")
                raise SystemExit(exit_code)
    except KeyboardInterrupt:
        print()
    except SystemExit as stop_signal:
        exit_code = stop_signal.code or 0

    for proc, label in reversed(running):
        stop(proc, label)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
