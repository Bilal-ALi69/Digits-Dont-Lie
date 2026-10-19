#!/usr/bin/env python3
"""Digits Dont Lie - build the portable zip.

    python3 scripts/package.py                 write Digits_Dont_Lie_portable.zip
    python3 scripts/package.py --no-secrets    ship .env templates instead of the
                                               real .env files
    python3 scripts/package.py -o <path>       write somewhere else

What goes in is the source tree, the setup and run scripts, and the docs -
everything a fresh machine needs in order to build itself. What stays out is
everything a machine has to build for itself: .venv, node_modules, .next, and
the assorted caches. Those are compiled for one OS and CPU, so copying them
between devices produces a broken install rather than a portable one. The
receiving machine runs scripts/setup.py once and regenerates them natively.

Standard library only - this has to run anywhere.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_NAME = "Digits_Dont_Lie"
DEFAULT_OUTPUT = PROJECT_ROOT / f"{BUNDLE_NAME}_portable.zip"

# Directory names dropped wherever they appear.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "out",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".impeccable",
    "graphify-out",
    ".idea",
    ".vscode",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".zip", ".tsbuildinfo", ".log", ".key", ".pem"}

SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "opencode.json.save"}

# Carried only when secrets are included; they are git-ignored, so the walk
# below would otherwise be the only thing deciding their fate.
SECRET_FILES = (
    Path("Backend/.env"),
    Path("Frontend/.env.local"),
)


def wanted(path: Path, include_secrets: bool) -> bool:
    rel = path.relative_to(PROJECT_ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
        return False
    if not include_secrets and rel in SECRET_FILES:
        return False
    if rel.name.endswith(".egg-info"):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable zip.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-secrets",
        action="store_true",
        help="leave Backend/.env and Frontend/.env.local out of the archive",
    )
    args = parser.parse_args()

    include_secrets = not args.no_secrets
    output = args.output.resolve()

    files = sorted(
        p
        for p in PROJECT_ROOT.rglob("*")
        if p.is_file() and not p.is_symlink() and wanted(p, include_secrets)
    )
    if not files:
        print("nothing to package", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(PROJECT_ROOT)
            info = zipfile.ZipInfo.from_file(path, Path(BUNDLE_NAME) / rel)
            # Preserve the executable bit so setup.sh/run.sh still run after
            # the archive has been through a Windows machine.
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as fh:
                zf.writestr(info, fh.read())

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"  {output}")
    print(f"  {len(files)} files, {size_mb:.1f} MB")
    if include_secrets:
        carried = [str(s) for s in SECRET_FILES if (PROJECT_ROOT / s).exists()]
        if carried:
            print(f"  contains live secrets: {', '.join(carried)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
