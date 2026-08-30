#!/usr/bin/env bash
# Shared helpers for setup_linux.sh and setup_macos.sh.
#
# Everything the two platforms do identically lives here: the marker protocol
# the launcher reads, the Python virtualenv, pip, npm, and the .env files.
# Each platform script supplies only what genuinely differs - how to install
# system packages - by defining install_system_packages() before sourcing.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$PROJECT_ROOT/Backend"
FRONTEND="$PROJECT_ROOT/Frontend"
VENV="$BACKEND/.venv"

MODE="install"
SKIP_SYSTEM=0
FAILURES=0

for arg in "$@"; do
    case "$arg" in
        install|update) MODE="$arg" ;;
        --skip-system)  SKIP_SYSTEM=1 ;;
    esac
done

# --- marker protocol -------------------------------------------------------
# The launcher (setup.py) parses these to drive its live view. Any other line
# is treated as ordinary command output.

say_step()   { printf '::step %s\n' "$*"; }
say_ok()     { printf '::ok %s\n' "$*"; }
say_fail()   { printf '::fail %s\n' "$*"; }
say_warn()   { printf '::warn %s\n' "$*"; }
say_info()   { printf '::info %s\n' "$*"; }
say_pause()  { printf '::pause %s\n' "$*"; }
say_resume() { printf '::resume\n'; }

# run_step "label" cmd...  - run a command as one reported step.
run_step() {
    local label="$1"; shift
    say_step "$label"
    if "$@" 2>&1; then
        say_ok
        return 0
    fi
    local rc=$?
    say_fail "exit $rc"
    FAILURES=$((FAILURES + 1))
    return $rc
}

have() { command -v "$1" >/dev/null 2>&1; }

# Run a command as root, showing it first. Pauses the spinner so that sudo's
# password prompt is not overwritten as it is being read.
as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@" 2>&1
        return $?
    fi
    if ! have sudo; then
        say_fail "sudo not found and not running as root"
        return 1
    fi
    say_pause "running: sudo $*"
    sudo "$@" 2>&1
    local rc=$?
    say_resume
    return $rc
}

# Ask sudo to cache credentials once, up front, rather than prompting in the
# middle of a package install where the spinner is redrawing the line.
prime_sudo() {
    [ "$(id -u)" -eq 0 ] && return 0
    have sudo || return 0
    sudo -n true 2>/dev/null && return 0
    say_pause "sudo password needed to install system packages"
    sudo -v
    local rc=$?
    say_resume
    return $rc
}

# --- shared steps ----------------------------------------------------------

python_bin() {
    # Prefer a version that satisfies the project's floor.
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if have "$candidate"; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

setup_venv() {
    local py
    if ! py="$(python_bin)"; then
        say_step "Python virtualenv"
        say_fail "no Python 3.11+ found on PATH"
        FAILURES=$((FAILURES + 1))
        return 1
    fi

    if [ -x "$VENV/bin/python" ]; then
        say_step "Python virtualenv"
        say_ok "reusing $( "$VENV/bin/python" --version 2>&1 )"
    else
        say_step "Python virtualenv"
        if "$py" -m venv "$VENV" 2>&1; then
            say_ok "created with $("$py" --version 2>&1)"
        else
            say_fail "could not create $VENV"
            FAILURES=$((FAILURES + 1))
            return 1
        fi
    fi

    run_step "pip (bootstrap)" "$VENV/bin/python" -m pip install --quiet --upgrade pip setuptools wheel

    if [ "$MODE" = "update" ]; then
        # --upgrade only, deliberately not --upgrade-strategy eager: eager
        # pulls every transitive dependency to its newest release, which is a
        # good way to break a working install. The pins in requirements.txt
        # are what we want moved forward.
        run_step "Backend dependencies (upgrade)" \
            "$VENV/bin/python" -m pip install --upgrade -r "$BACKEND/requirements.txt"
    else
        run_step "Backend dependencies" \
            "$VENV/bin/python" -m pip install -r "$BACKEND/requirements.txt"
    fi
}

setup_frontend() {
    if ! have npm; then
        say_step "Frontend dependencies"
        say_fail "npm not found on PATH"
        FAILURES=$((FAILURES + 1))
        return 1
    fi

    if [ "$MODE" = "update" ]; then
        run_step "Frontend dependencies (upgrade)" \
            npm --prefix "$FRONTEND" update --no-fund --no-audit
    elif [ -f "$FRONTEND/package-lock.json" ]; then
        # ci is reproducible, but it refuses when the lockfile has drifted from
        # package.json. Fall back rather than failing the whole run.
        say_step "Frontend dependencies"
        if npm --prefix "$FRONTEND" ci --no-fund --no-audit 2>&1; then
            say_ok "from package-lock.json"
        else
            say_warn "lockfile out of sync, falling back to npm install"
            run_step "Frontend dependencies (install)" \
                npm --prefix "$FRONTEND" install --no-fund --no-audit
        fi
    else
        run_step "Frontend dependencies" npm --prefix "$FRONTEND" install --no-fund --no-audit
    fi
}

setup_env_files() {
    local py
    py="$(python_bin)" || py="python3"
    "$py" "$PROJECT_ROOT/scripts/init_env.py" 2>&1
}

verify_install() {
    say_step "Verify backend imports"
    if [ -x "$VENV/bin/python" ] && \
       (cd "$BACKEND" && "$VENV/bin/python" -c "import app.api.server" 2>&1); then
        say_ok "FastAPI app imports cleanly"
    else
        say_warn "backend did not import - check the errors above"
    fi

    say_step "Verify Tesseract OCR"
    if have tesseract; then
        say_ok "$(tesseract --version 2>&1 | head -1)"
    else
        say_warn "not installed - OCR features will be unavailable"
    fi
}

main_unix() {
    if [ "$SKIP_SYSTEM" -eq 1 ]; then
        say_step "System packages"
        say_warn "skipped by request (--skip-system)"
    else
        install_system_packages
    fi

    setup_venv
    setup_frontend
    setup_env_files
    verify_install

    if [ "$FAILURES" -gt 0 ]; then
        say_info "$FAILURES step(s) failed"
        return 1
    fi
    return 0
}
