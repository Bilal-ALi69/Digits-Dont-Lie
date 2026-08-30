#!/usr/bin/env python3
"""Digits Dont Lie - cross-platform setup launcher.

Usage:

    python3 scripts/setup.py             install everything
    python3 scripts/setup.py --update    upgrade an existing install
    python3 scripts/setup.py --check     report what is missing, change nothing
    python3 scripts/setup.py --yes       do not pause for confirmation
    python3 scripts/setup.py --verbose   show all output from the platform script

It works out which operating system and package manager this machine has,
then hands the real work to the matching platform script:

    Linux    scripts/setup_linux.sh
    macOS    scripts/setup_macos.sh
    Windows  scripts/setup_windows.ps1

This file imports nothing outside the standard library, deliberately. It is
the program that runs before any dependency has been installed, so it cannot
rely on one being present.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Digits Dont Lie"
MIN_PYTHON = (3, 11)
MIN_NODE = 20

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


# ---------------------------------------------------------------------------
# Terminal capabilities
#
# Everything below degrades rather than fails. A terminal that cannot do
# colour gets plain text; one that cannot render box-drawing characters gets
# ASCII. The installer must stay readable when piped to a file or a CI log.
# ---------------------------------------------------------------------------


def _enable_windows_vt() -> bool:
    """Turn on ANSI escape handling in cmd.exe. No-op elsewhere."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:
        return False


class Style:
    """Colour and glyph set chosen once, from what the terminal admits to."""

    def __init__(self) -> None:
        self.tty = sys.stdout.isatty()
        vt_ok = _enable_windows_vt()

        # NO_COLOR is honoured when set to anything non-empty; FORCE_COLOR
        # only forces when it is set to something truthy, so FORCE_COLOR=0
        # and FORCE_COLOR= mean "off" rather than "on".
        no_color = bool(os.environ.get("NO_COLOR", ""))
        dumb = os.environ.get("TERM", "") in ("dumb", "")
        forced = os.environ.get("FORCE_COLOR", "").lower() not in ("", "0", "false", "no")

        self.color = forced or (self.tty and vt_ok and not no_color and not (dumb and os.name != "nt"))
        self.truecolor = self.color and os.environ.get("COLORTERM", "") in ("truecolor", "24bit")
        self.unicode = self._probe_unicode()

        if self.unicode:
            self.tick, self.cross, self.warn_g, self.dot, self.arrow = "✓", "✗", "!", "•", "→"
            self.tl, self.tr, self.bl, self.br, self.h, self.v = "╭", "╮", "╰", "╯", "─", "│"
            self.frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        else:
            self.tick, self.cross, self.warn_g, self.dot, self.arrow = "+", "x", "!", "*", "->"
            self.tl, self.tr, self.bl, self.br, self.h, self.v = "+", "+", "+", "+", "-", "|"
            self.frames = "|/-\\"

    @staticmethod
    def _probe_unicode() -> bool:
        enc = sys.stdout.encoding or ""
        try:
            "✓╭─⠋".encode(enc)
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def bold(self, t: str) -> str:
        return self._c("1", t)

    def dim(self, t: str) -> str:
        return self._c("2", t)

    def red(self, t: str) -> str:
        return self._c("31;1", t)

    def green(self, t: str) -> str:
        return self._c("32;1", t)

    def yellow(self, t: str) -> str:
        return self._c("33;1", t)

    def blue(self, t: str) -> str:
        return self._c("36;1", t)

    def accent(self, t: str) -> str:
        # A warm amber when the terminal can do 24-bit colour, else plain cyan.
        if self.truecolor:
            return self._c("38;2;226;160;63", t)
        return self.blue(t)


S = Style()


def term_width(default: int = 80) -> int:
    try:
        return max(48, min(shutil.get_terminal_size((default, 24)).columns, 100))
    except Exception:
        return default


def banner() -> None:
    w = term_width()
    inner = w - 2
    title = APP_NAME
    subtitle = "environment setup"

    print()
    print(S.accent(S.tl + S.h * inner + S.tr))
    for line, painter in ((title, S.bold), (subtitle, S.dim)):
        pad = inner - len(line) - 2
        left = pad // 2 + 1
        right = pad - pad // 2 + 1
        print(S.accent(S.v) + " " * left + painter(line) + " " * right + S.accent(S.v))
    print(S.accent(S.bl + S.h * inner + S.br))
    print()


def section(text: str) -> None:
    print(f"\n{S.bold(text)}")
    print(S.dim(S.h * min(len(text) + 4, term_width())))


# ---------------------------------------------------------------------------
# Step renderer
#
# The platform scripts print structured markers (::step, ::ok, ::fail, ...)
# amid their ordinary output. This class turns that stream into a live view:
# one line per step, a spinner while it runs, and the command's own chatter
# kept in a buffer that is only dumped if the step fails.
# ---------------------------------------------------------------------------


class Steps:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.live = S.tty and not verbose
        self._lock = threading.Lock()
        self._spinner: threading.Thread | None = None
        self._stop = threading.Event()
        self._label = ""
        self._detail = ""
        self._frame = 0
        self.ok_count = 0
        self.fail_count = 0
        self.warn_count = 0
        self.failures: list[str] = []
        self.buffer: list[str] = []

    # -- spinner ------------------------------------------------------------

    def _render(self) -> None:
        """Redraw the in-progress line. Caller must hold the lock."""
        if not self.live:
            return
        glyph = S.frames[self._frame % len(S.frames)]
        line = f"  {S.accent(glyph)} {self._label}"
        if self._detail:
            room = term_width() - len(self._label) - 8
            if room > 12:
                snippet = self._detail[:room].rstrip()
                line += f"  {S.dim(snippet)}"
        sys.stdout.write("\r\033[2K" + line)
        sys.stdout.flush()

    def _spin(self) -> None:
        while not self._stop.wait(0.09):
            with self._lock:
                self._frame += 1
                self._render()

    def start(self, label: str) -> None:
        self.finish_pending()
        with self._lock:
            self._label = label
            self._detail = ""
            self._frame = 0
            self.buffer = []
        if self.live:
            with self._lock:
                self._render()
            self._stop.clear()
            self._spinner = threading.Thread(target=self._spin, daemon=True)
            self._spinner.start()
        else:
            print(f"  {S.dim(S.dot)} {label}")

    def _halt_spinner(self) -> None:
        if self._spinner is not None:
            self._stop.set()
            self._spinner.join(timeout=1.0)
            self._spinner = None

    def _emit(self, glyph: str, label: str, note: str = "") -> None:
        self._halt_spinner()
        with self._lock:
            text = f"  {glyph} {label}"
            if note:
                text += f"  {S.dim(note)}"
            if self.live:
                sys.stdout.write("\r\033[2K")
            print(text)
            sys.stdout.flush()
            self._label = ""

    def finish_pending(self) -> None:
        """Close an unterminated step, so a crashed script leaves no spinner."""
        if self._label:
            self._emit(S.yellow(S.warn_g), self._label, "interrupted")

    # -- outcomes -----------------------------------------------------------

    def ok(self, label: str = "", note: str = "") -> None:
        self.ok_count += 1
        self._emit(S.green(S.tick), label or self._label, note)

    def fail(self, label: str = "", note: str = "") -> None:
        name = label or self._label
        self.fail_count += 1
        self.failures.append(name)
        tail = list(self.buffer)
        self._emit(S.red(S.cross), name, note)
        for line in tail[-12:]:
            print(S.dim(f"      {line}"))

    def warn(self, label: str = "", note: str = "") -> None:
        self.warn_count += 1
        self._emit(S.yellow(S.warn_g), label or self._label, note)

    def info(self, text: str) -> None:
        self._halt_spinner()
        if self.live:
            sys.stdout.write("\r\033[2K")
        print(f"    {S.dim(text)}")

    def pause(self, message: str = "") -> None:
        """Halt the spinner and hand the terminal to the child process.

        Used before sudo prompts for a password: a spinner redrawing the line
        would overwrite the prompt as the user is reading it.
        """
        self._halt_spinner()
        with self._lock:
            if self.live:
                sys.stdout.write("\r\033[2K")
                sys.stdout.flush()
        if message:
            print(f"    {S.yellow(S.warn_g)} {message}")

    def resume(self) -> None:
        """Give the line back to the spinner after a prompt has cleared."""
        if self.live and self._label and self._spinner is None:
            self._stop.clear()
            self._spinner = threading.Thread(target=self._spin, daemon=True)
            self._spinner.start()

    def output(self, line: str) -> None:
        """A plain line of the child process's own output."""
        self.buffer.append(line)
        if self.verbose:
            print(S.dim(f"      {line}"))
        elif self.live and self._label:
            with self._lock:
                self._detail = line.strip()
                self._render()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    if "=" not in raw or raw.startswith("#"):
                        continue
                    key, _, value = raw.partition("=")
                    data[key.strip()] = value.strip().strip('"').strip("'")
            break
        except OSError:
            continue
    return data


LINUX_MANAGERS = (
    ("pacman", "pacman"),
    ("apt-get", "apt"),
    ("dnf", "dnf"),
    ("zypper", "zypper"),
    ("apk", "apk"),
)


def detect() -> dict[str, str]:
    system = platform.system()
    info = {
        "system": system,
        "arch": platform.machine() or "unknown",
        "distro": "",
        "manager": "",
        "family": "",
    }

    if system == "Linux":
        rel = read_os_release()
        info["distro"] = rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux"
        info["family"] = f"{rel.get('ID', '')} {rel.get('ID_LIKE', '')}".strip()
        for binary, name in LINUX_MANAGERS:
            if shutil.which(binary):
                info["manager"] = name
                break
    elif system == "Darwin":
        info["distro"] = f"macOS {platform.mac_ver()[0] or ''}".strip()
        info["manager"] = "brew" if shutil.which("brew") else ""
    elif system == "Windows":
        info["distro"] = f"Windows {platform.release()}"
        for binary, name in (("winget", "winget"), ("choco", "choco")):
            if shutil.which(binary):
                info["manager"] = name
                break

    return info


def _version_of(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else ""


def _first_int(text: str) -> int | None:
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def preflight() -> list[tuple[str, bool, str]]:
    """Return (component, satisfied, detail) for each prerequisite."""
    results: list[tuple[str, bool, str]] = []

    py_ok = sys.version_info[:2] >= MIN_PYTHON
    results.append(
        ("Python", py_ok, f"{platform.python_version()} (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")
    )

    node = shutil.which("node")
    if node:
        raw = _version_of([node, "--version"])
        major = _first_int(raw.lstrip("v"))
        ok = major is not None and major >= MIN_NODE
        results.append(("Node.js", ok, f"{raw or 'unknown'} (need {MIN_NODE}+)"))
    else:
        results.append(("Node.js", False, "not installed"))

    for label, binary, args in (
        ("npm", "npm", ["--version"]),
        ("Tesseract OCR", "tesseract", ["--version"]),
        ("git", "git", ["--version"]),
    ):
        path = shutil.which(binary)
        if path:
            results.append((label, True, _version_of([path] + args) or "installed"))
        else:
            results.append((label, False, "not installed"))

    return results


def platform_script(system: str) -> tuple[Path, list[str]] | None:
    """The script for this OS, plus the command prefix that runs it."""
    if system == "Linux":
        script = SCRIPTS_DIR / "setup_linux.sh"
        return script, [shutil.which("bash") or "/bin/bash", str(script)]
    if system == "Darwin":
        script = SCRIPTS_DIR / "setup_macos.sh"
        return script, [shutil.which("bash") or "/bin/bash", str(script)]
    if system == "Windows":
        script = SCRIPTS_DIR / "setup_windows.ps1"
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            return None
        return script, [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    return None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


MARKERS = {
    "::step": "step",
    "::ok": "ok",
    "::fail": "fail",
    "::warn": "warn",
    "::info": "info",
    "::pause": "pause",
    "::resume": "resume",
}


def run_platform_script(cmd: list[str], steps: Steps) -> int:
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(PROJECT_ROOT),
        )
    except OSError as exc:
        steps.fail("launch platform script", str(exc))
        return 127

    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            head, _, rest = line.partition(" ")
            kind = MARKERS.get(head)
            if kind == "step":
                steps.start(rest)
            elif kind == "ok":
                steps.ok(note=rest)
            elif kind == "fail":
                steps.fail(note=rest)
            elif kind == "warn":
                steps.warn(note=rest)
            elif kind == "info":
                steps.info(rest)
            elif kind == "pause":
                steps.pause(rest)
            elif kind == "resume":
                steps.resume()
            elif line.strip():
                steps.output(line)
    except KeyboardInterrupt:
        proc.terminate()
        steps.finish_pending()
        raise
    finally:
        code = proc.wait()
        steps.finish_pending()
    return code


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(S.yellow("  stdin is not a terminal; re-run with --yes to proceed unattended."))
        return False
    try:
        answer = input(f"{prompt} {S.dim('[y/N]')} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description=f"Set up the {APP_NAME} development environment.",
    )
    parser.add_argument("--update", action="store_true", help="upgrade an existing install")
    parser.add_argument("--check", action="store_true", help="report only; change nothing")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation prompts")
    parser.add_argument("--verbose", "-v", action="store_true", help="show all subprocess output")
    parser.add_argument(
        "--skip-system",
        action="store_true",
        help="do not install system packages (no sudo/admin needed)",
    )
    args = parser.parse_args(argv)

    banner()

    host = detect()
    section("Machine")
    rows = [
        ("Operating system", host["distro"] or host["system"]),
        ("Architecture", host["arch"]),
        ("Package manager", host["manager"] or "none detected"),
        ("Project root", str(PROJECT_ROOT)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {S.dim(label.ljust(width))}  {value}")

    section("Prerequisites")
    checks = preflight()
    width = max(len(name) for name, _, _ in checks)
    missing = []
    for name, ok, detail in checks:
        glyph = S.green(S.tick) if ok else S.yellow(S.warn_g)
        print(f"  {glyph} {name.ljust(width)}  {S.dim(detail)}")
        if not ok:
            missing.append(name)

    if args.check:
        print()
        if missing:
            print(S.yellow(f"  {len(missing)} item(s) need attention: {', '.join(missing)}"))
            print(S.dim("  Run without --check to install them."))
            return 1
        print(S.green(f"  {S.tick} Everything this project needs is already present."))
        return 0

    if host["system"] not in ("Linux", "Darwin", "Windows"):
        print(S.red(f"\n  Unsupported operating system: {host['system']}"))
        print(S.dim("  Follow the manual steps in README.md instead."))
        return 2

    target = platform_script(host["system"])
    if target is None:
        print(S.red("\n  Could not find a PowerShell interpreter to run the Windows script."))
        return 2
    script, cmd = target
    if not script.exists():
        print(S.red(f"\n  Missing platform script: {script}"))
        return 2

    mode = "update" if args.update else "install"
    child_args = [mode]
    if args.skip_system:
        child_args.append("--skip-system")
    if host["system"] == "Windows":
        cmd = cmd + ["-Mode", mode] + (["-SkipSystem"] if args.skip_system else [])
    else:
        cmd = cmd + child_args

    section("Plan")
    print(f"  {S.dim('Script')}    {script.name}")
    print(f"  {S.dim('Mode')}      {mode}")
    if args.skip_system:
        print(f"  {S.dim('System')}    skipped by request")
    elif missing:
        print(f"  {S.dim('System')}    will install: {', '.join(missing)}")
        needs_root = host["system"] in ("Linux",) or (
            host["system"] == "Darwin" and not shutil.which("brew")
        )
        if needs_root:
            print(f"  {S.yellow(S.warn_g)} {S.dim('This needs sudo. Each command is shown before it runs.')}")
    else:
        print(f"  {S.dim('System')}    nothing missing")
    print(f"  {S.dim('Then')}      Python venv {S.arrow} pip install {S.arrow} npm install {S.arrow} .env files")
    print()

    if not confirm("  Proceed?", args.yes):
        print(S.dim("  Cancelled. Nothing was changed."))
        return 130

    section("Setup")
    steps = Steps(verbose=args.verbose)
    started = time.time()
    try:
        code = run_platform_script(cmd, steps)
    except KeyboardInterrupt:
        print(S.yellow("\n  Interrupted. Re-run when ready; the script picks up where it can."))
        return 130

    elapsed = time.time() - started
    section("Result")
    summary = (
        f"{S.green(str(steps.ok_count) + ' ok')}"
        f"   {S.yellow(str(steps.warn_count) + ' warned')}"
        f"   {S.red(str(steps.fail_count) + ' failed')}"
        f"   {S.dim(f'{elapsed:.1f}s')}"
    )
    print(f"  {summary}")

    if code != 0 or steps.fail_count:
        print()
        print(S.red(f"  Setup did not finish cleanly (exit {code})."))
        for name in steps.failures:
            print(S.dim(f"    {S.dot} {name}"))
        print(S.dim("  Re-run with --verbose to see the full output."))
        return code or 1

    print()
    print(S.green(f"  {S.tick} Ready."))
    print()
    print(S.bold("  Start the backend"))
    if host["system"] == "Windows":
        print(S.dim("    cd Backend; .venv\\Scripts\\activate; uvicorn app.api.server:app --reload --port 8000"))
    else:
        print(S.dim("    cd Backend && source .venv/bin/activate && uvicorn app.api.server:app --reload --port 8000"))
    print(S.bold("  Start the frontend"))
    print(S.dim("    cd Frontend && npm run dev") + S.dim("        http://localhost:3000"))
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
