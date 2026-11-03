<#
  One-command setup on Windows, then the guided discovery of Fakturama's controls.

  Run from the project folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File scripts\windows_setup.ps1

  What it does:
    1. Finds Python 3.11 64-bit (x64); installs it with winget if it is missing.
    2. Creates .venv and installs requirements.txt.
    3. Runs the tests (including Windows OCR on the sample image).
    4. Waits until Fakturama is running, then starts "main.py discover".

  Options:
      -SkipDiscovery   stop after the tests
#>
param([switch]$SkipDiscovery)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nSTOPPED: $text" -ForegroundColor Red; exit 1 }

function Find-Python311 {
    try {
        $exe = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    } catch {}
    return $null
}

# 1. Python 3.11, x64 build (some dependencies have no ARM64 builds)
Step "1/4 Python 3.11 (64-bit x64)"
$python = Find-Python311
if (-not $python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "Python 3.11 not found. Install the 64-bit (x64) version from python.org, tick 'Add python.exe to PATH', then run this script again."
    }
    Write-Host "Python 3.11 not found; installing it with winget..."
    winget install --id Python.Python.3.11 --exact --architecture x64 --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $python = Find-Python311
    if (-not $python) { Fail "Python 3.11 was installed but is not found yet. Close PowerShell, open a new one and run this script again." }
}
$platform = (& $python -c "import sysconfig; print(sysconfig.get_platform())").Trim()
if ($platform -ne "win-amd64") {
    Fail "The Python 3.11 at $python is '$platform'. Install the 64-bit x64 Python 3.11 from python.org (also on ARM Windows) and run this script again."
}
Write-Host "Using $python ($platform)"

# 2. Virtual environment and dependencies
Step "2/4 Virtual environment and dependencies"
$venvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv" }
}
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see the messages above)" }

# 3. Tests
Step "3/4 Tests"
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "If the OCR test says the language is missing, run this in an administrator PowerShell:" -ForegroundColor Yellow
    Write-Host '    Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"' -ForegroundColor Yellow
    Fail "Some tests failed. Send the output above."
}

if ($SkipDiscovery) {
    Write-Host "`nSetup done. Run this script again without -SkipDiscovery to record Fakturama's controls." -ForegroundColor Green
    exit 0
}

# 4. Discovery
Step "4/4 Discovery of Fakturama's controls"
function Test-Fakturama {
    # Only Fakturama's own process (or its Java runtime), not editors or folders named "Fakturama-Task".
    $found = Get-Process | Where-Object { $_.MainWindowTitle -like "*Fakturama*" -and $_.ProcessName -match "^(Fakturama|javaw?)$" }
    return $null -ne $found
}
while (-not (Test-Fakturama)) {
    $answer = Read-Host "Start Fakturama and wait for its main window, then press Enter (type 'go' to continue anyway)"
    if ($answer -eq "go") { break }
}
& $venvPython main.py discover
if ($LASTEXITCODE -ne 0) { Fail "Discovery stopped with an error. Send the output above." }
Write-Host "`nAll done. Send the .zip file named above." -ForegroundColor Green
