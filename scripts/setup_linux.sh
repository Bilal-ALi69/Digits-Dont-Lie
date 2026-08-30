#!/usr/bin/env bash
# Linux setup for Digits Dont Lie.
#
# Normally launched by scripts/setup.py, which renders the ::markers this
# prints. It also runs standalone:
#
#     bash scripts/setup_linux.sh install
#     bash scripts/setup_linux.sh update --skip-system

set -uo pipefail

# Packages per distribution family. Names differ more than you would hope:
# Debian splits the venv module into its own package, and every distro spells
# the English OCR training data differently.
install_system_packages() {
    say_step "System packages"

    local manager=""
    for candidate in pacman apt-get dnf zypper apk; do
        if have "$candidate"; then manager="$candidate"; break; fi
    done

    if [ -z "$manager" ]; then
        say_warn "no known package manager - install Python 3.11+, Node 20+ and Tesseract manually"
        return 0
    fi

    prime_sudo || { say_fail "could not obtain sudo"; FAILURES=$((FAILURES + 1)); return 1; }

    local rc=0
    case "$manager" in
        pacman)
            as_root pacman -Sy --needed --noconfirm \
                python python-pip nodejs npm tesseract tesseract-data-eng || rc=$?
            ;;
        apt-get)
            as_root apt-get update -qq || rc=$?
            as_root apt-get install -y --no-install-recommends \
                python3 python3-venv python3-pip nodejs npm \
                tesseract-ocr tesseract-ocr-eng || rc=$?
            ;;
        dnf)
            as_root dnf install -y \
                python3 python3-pip nodejs npm \
                tesseract tesseract-langpack-eng || rc=$?
            ;;
        zypper)
            as_root zypper --non-interactive install \
                python3 python3-pip nodejs npm tesseract-ocr || rc=$?
            ;;
        apk)
            as_root apk add --no-cache \
                python3 py3-pip nodejs npm tesseract-ocr tesseract-ocr-data-eng || rc=$?
            ;;
    esac

    if [ "$rc" -ne 0 ]; then
        say_fail "$manager exited $rc"
        FAILURES=$((FAILURES + 1))
        return 1
    fi
    say_ok "installed via $manager"

    # Debian and Ubuntu ship Node far behind the 20 this project needs.
    if have node; then
        local major
        major="$(node --version 2>/dev/null | sed 's/^v//' | cut -d. -f1)"
        if [ -n "$major" ] && [ "$major" -lt 20 ] 2>/dev/null; then
            say_warn "Node $major is older than the required 20 - install a newer build from nodejs.org or nvm"
        fi
    fi
}

# shellcheck source=lib_unix.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_unix.sh"
main_unix
