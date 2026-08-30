#!/usr/bin/env bash
# macOS setup for Digits Dont Lie.
#
# Normally launched by scripts/setup.py. It also runs standalone:
#
#     bash scripts/setup_macos.sh install
#     bash scripts/setup_macos.sh update --skip-system

set -uo pipefail

install_system_packages() {
    say_step "System packages"

    if ! have brew; then
        say_warn "Homebrew not found - install it from https://brew.sh, then re-run"
        say_info "without brew, install Python 3.11+, Node 20+ and Tesseract by hand"
        return 0
    fi

    # Homebrew installs into a prefix the user owns, so this needs no sudo.
    local rc=0
    brew update --quiet 2>&1 || say_warn "brew update failed - continuing with the current formulae"

    local formulae=(python@3.12 node tesseract)
    if [ "$MODE" = "update" ]; then
        brew upgrade "${formulae[@]}" 2>&1 || rc=$?
        # brew upgrade exits non-zero when a formula is already current.
        rc=0
    else
        for formula in "${formulae[@]}"; do
            if brew list --formula "$formula" >/dev/null 2>&1; then
                continue
            fi
            brew install "$formula" 2>&1 || rc=$?
        done
    fi

    if [ "$rc" -ne 0 ]; then
        say_fail "brew exited $rc"
        FAILURES=$((FAILURES + 1))
        return 1
    fi
    say_ok "installed via Homebrew"

    # Apple Silicon puts brew under /opt/homebrew, which is not on the default
    # PATH of a shell that has never sourced a brew shellenv.
    if [ -d /opt/homebrew/bin ] && ! printf '%s' "$PATH" | grep -q /opt/homebrew/bin; then
        say_info 'add to your shell profile: eval "$(/opt/homebrew/bin/brew shellenv)"'
    fi
}

# shellcheck source=lib_unix.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_unix.sh"
main_unix
