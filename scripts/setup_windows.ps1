<#
.SYNOPSIS
    Windows setup for Digits Dont Lie.

.DESCRIPTION
    Normally launched by scripts/setup.py, which renders the ::markers this
    prints. It also runs standalone:

        powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Mode install
        powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Mode update -SkipSystem
#>

[CmdletBinding()]
param(
    [ValidateSet('install', 'update')]
    [string]$Mode = 'install',
    [switch]$SkipSystem
)

$ErrorActionPreference = 'Continue'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Backend     = Join-Path $ProjectRoot 'Backend'
$Frontend    = Join-Path $ProjectRoot 'Frontend'
$Venv        = Join-Path $Backend '.venv'
$script:Failures = 0

# --- marker protocol -------------------------------------------------------
# Written straight to stdout rather than through Write-Host, so the launcher
# receives them in order even when the stream is redirected.

function Say-Raw  { param([string]$Text) [Console]::Out.WriteLine($Text); [Console]::Out.Flush() }
function Say-Step { param([string]$Text) Say-Raw "::step $Text" }
function Say-Ok   { param([string]$Text = '') Say-Raw "::ok $Text" }
function Say-Fail { param([string]$Text = '') Say-Raw "::fail $Text"; $script:Failures++ }
function Say-Warn { param([string]$Text = '') Say-Raw "::warn $Text" }
function Say-Info { param([string]$Text = '') Say-Raw "::info $Text" }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# A freshly installed Python or Node is not on the PATH of the already-running
# process. Re-read it from the registry so later steps can find them without
# the user having to close and reopen the terminal.
function Update-PathFromRegistry {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = ($machine, $user | Where-Object { $_ }) -join ';'
}

# Run a command as one reported step, streaming its output to the launcher.
function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )
    Say-Step $Label
    try {
        # Clear it first: $LASTEXITCODE persists from whatever native command
        # ran last, so a scriptblock that fails to run at all would otherwise
        # inherit a stale success.
        $global:LASTEXITCODE = 0
        & $Action 2>&1 | ForEach-Object { Say-Raw ($_ | Out-String).TrimEnd() }
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            Say-Fail "exit $LASTEXITCODE"
            return $false
        }
        Say-Ok
        return $true
    } catch {
        Say-Fail $_.Exception.Message
        return $false
    }
}

# --- system packages -------------------------------------------------------

function Install-SystemPackages {
    Say-Step 'System packages'

    if (Test-Command 'winget') {
        $packages = @(
            @{ Id = 'Python.Python.3.12';       Name = 'Python 3.12' },
            @{ Id = 'OpenJS.NodeJS.LTS';        Name = 'Node.js LTS' },
            @{ Id = 'UB-Mannheim.TesseractOCR'; Name = 'Tesseract OCR' }
        )
        $verb = if ($Mode -eq 'update') { 'upgrade' } else { 'install' }

        foreach ($package in $packages) {
            # Not $args: that is an automatic variable in PowerShell.
            $wingetArgs = @(
                $verb, '--id', $package.Id, '--exact', '--silent',
                '--accept-package-agreements', '--accept-source-agreements'
            )
            & winget @wingetArgs 2>&1 | Out-Null
            # winget reports "no applicable upgrade" and "already installed"
            # as failures. Neither is one, so confirm by presence instead.
        }
        Update-PathFromRegistry
        Say-Ok "handled via winget ($verb)"

    } elseif (Test-Command 'choco') {
        if (-not (Test-Admin)) {
            Say-Fail 'Chocolatey needs an elevated prompt - re-run this terminal as Administrator'
            return
        }
        $verb = if ($Mode -eq 'update') { 'upgrade' } else { 'install' }
        & choco $verb -y python nodejs-lts tesseract 2>&1 |
            ForEach-Object { Say-Raw ($_ | Out-String).TrimEnd() }
        Update-PathFromRegistry
        Say-Ok "handled via Chocolatey ($verb)"

    } else {
        Say-Warn 'neither winget nor Chocolatey found'
        Say-Info 'install Python 3.11+, Node 20+ and Tesseract OCR manually, then re-run with --skip-system'
    }
}

# --- Python ----------------------------------------------------------------

# Returns @{ Exe = <string>; Pre = <string[]> }, or $null if nothing suitable
# is installed. Exe and Pre are kept apart rather than packed into one array:
# slicing an array to drop its first element is a trap in PowerShell, because
# $a[1..($a.Length-1)] on a single-element array reads as the descending range
# 1..0 and yields $null plus the element, instead of nothing.
function Resolve-Python {
    $probe = 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)'

    # The py launcher knows about every installed version; prefer it.
    if (Test-Command 'py') {
        foreach ($version in @('-3.13', '-3.12', '-3.11', '-3')) {
            & py $version -c $probe 2>$null
            if ($LASTEXITCODE -eq 0) { return @{ Exe = 'py'; Pre = @($version) } }
        }
    }
    foreach ($name in @('python3', 'python')) {
        if (Test-Command $name) {
            & $name -c $probe 2>$null
            if ($LASTEXITCODE -eq 0) { return @{ Exe = $name; Pre = @() } }
        }
    }
    return $null
}

# Run the resolved interpreter with the given arguments.
function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )
    $all = @($Python.Pre) + $Arguments
    & $Python.Exe @all 2>&1
}

function Setup-Venv {
    $python = Resolve-Python
    $venvPython = Join-Path $Venv 'Scripts\python.exe'

    if (Test-Path $venvPython) {
        Say-Step 'Python virtualenv'
        Say-Ok "reusing $(& $venvPython --version 2>&1)"
    } else {
        Say-Step 'Python virtualenv'
        if ($null -eq $python) {
            Say-Fail 'no Python 3.11+ found on PATH'
            return
        }
        Invoke-Python -Python $python -Arguments @('-m', 'venv', $Venv) |
            ForEach-Object { Say-Raw ($_ | Out-String).TrimEnd() }
        if (-not (Test-Path $venvPython)) {
            Say-Fail "could not create $Venv"
            return
        }
        Say-Ok 'created'
    }

    Invoke-Step 'pip (bootstrap)' {
        & $venvPython -m pip install --quiet --upgrade pip setuptools wheel
    } | Out-Null

    $requirements = Join-Path $Backend 'requirements.txt'
    if ($Mode -eq 'update') {
        # --upgrade only, deliberately not --upgrade-strategy eager: see the
        # note in lib_unix.sh. Eager upgrades break working installs.
        Invoke-Step 'Backend dependencies (upgrade)' {
            & $venvPython -m pip install --upgrade -r $requirements
        } | Out-Null
    } else {
        Invoke-Step 'Backend dependencies' {
            & $venvPython -m pip install -r $requirements
        } | Out-Null
    }
}

# --- Frontend --------------------------------------------------------------

function Setup-Frontend {
    if (-not (Test-Command 'npm')) {
        Say-Step 'Frontend dependencies'
        Say-Fail 'npm not found on PATH - open a new terminal so the Node install is picked up, then re-run'
        return
    }

    if ($Mode -eq 'update') {
        Invoke-Step 'Frontend dependencies (upgrade)' {
            & npm --prefix $Frontend update --no-fund --no-audit
        } | Out-Null
        return
    }

    if (Test-Path (Join-Path $Frontend 'package-lock.json')) {
        Say-Step 'Frontend dependencies'
        & npm --prefix $Frontend ci --no-fund --no-audit 2>&1 |
            ForEach-Object { Say-Raw ($_ | Out-String).TrimEnd() }
        if ($LASTEXITCODE -eq 0) {
            Say-Ok 'from package-lock.json'
            return
        }
        Say-Warn 'lockfile out of sync, falling back to npm install'
    }

    Invoke-Step 'Frontend dependencies (install)' {
        & npm --prefix $Frontend install --no-fund --no-audit
    } | Out-Null
}

# --- Environment files and verification ------------------------------------

function Setup-EnvFiles {
    $python = Resolve-Python
    if ($null -eq $python) {
        Say-Step 'Environment files'
        Say-Fail 'no Python available to run init_env.py'
        return
    }
    $initEnv = Join-Path $ScriptDir 'init_env.py'
    Invoke-Python -Python $python -Arguments @($initEnv) |
        ForEach-Object { Say-Raw ($_ | Out-String).TrimEnd() }
}

function Test-Install {
    $venvPython = Join-Path $Venv 'Scripts\python.exe'
    Say-Step 'Verify backend imports'
    if (Test-Path $venvPython) {
        Push-Location $Backend
        & $venvPython -c 'import app.api.server' 2>&1 | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
        Pop-Location
        if ($ok) { Say-Ok 'FastAPI app imports cleanly' }
        else     { Say-Warn 'backend did not import - re-run with --verbose to see why' }
    } else {
        Say-Warn 'no virtualenv to check'
    }

    Say-Step 'Verify Tesseract OCR'
    if (Test-Command 'tesseract') {
        $version = (& tesseract --version 2>&1 | Select-Object -First 1)
        Say-Ok "$version"
    } else {
        Say-Warn 'not installed - OCR features will be unavailable'
    }
}

# --- main ------------------------------------------------------------------

if ($SkipSystem) {
    Say-Step 'System packages'
    Say-Warn 'skipped by request (--skip-system)'
} else {
    Install-SystemPackages
}

Setup-Venv
Setup-Frontend
Setup-EnvFiles
Test-Install

if ($script:Failures -gt 0) {
    Say-Info "$($script:Failures) step(s) failed"
    exit 1
}
exit 0
