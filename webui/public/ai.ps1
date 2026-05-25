# Native installer bootstrap for Pythinker on Windows PowerShell.
#
# Canonical one-liner:
#   irm https://pythinker.com/ai.ps1 | iex
#
# Downloads the latest PythinkerSetup-<version>.exe from GitHub Releases,
# verifies its SHA-256 sidecar, then runs the Inno Setup installer silently.
#
# Optional source checkout usage:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Version 2.7.1
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -AllUsers

param(
    [string]$Version = "",
    [string]$Repo = $(if ($env:PYTHINKER_AI_REPO) { $env:PYTHINKER_AI_REPO } else { "mohamed-elkholy95/Pythinker" }),
    [switch]$AllUsers,
    [switch]$KeepInstaller
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
catch {
    # PowerShell 7+ on newer runtimes may not expose ServicePointManager; HTTPS still works there.
}

function Write-PythinkerLog {
    param([string]$Message)
    Write-Host "[pythinker] $Message" -ForegroundColor Cyan
}

function Write-PythinkerWarn {
    param([string]$Message)
    Write-Warning "[pythinker] $Message"
}

function Fail {
    param([string]$Message)
    Write-Host "[pythinker] $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Download {
    param(
        [string]$Uri,
        [string]$OutFile
    )
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $OutFile
    }
    catch {
        Fail "Failed to download $Uri`: $($_.Exception.Message)"
    }
}

if ([Environment]::Is64BitOperatingSystem -eq $false) {
    Fail "Pythinker only publishes a 64-bit Windows installer."
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $latestUrl = "https://api.github.com/repos/$Repo/releases/latest"
    Write-PythinkerLog "Resolving latest release from $Repo..."
    try {
        $latest = Invoke-RestMethod -Uri $latestUrl -Headers @{ Accept = "application/vnd.github+json" }
        $Version = [string]$latest.tag_name
        $Version = $Version.TrimStart("v")
    }
    catch {
        Fail "Could not determine latest version from $latestUrl`: $($_.Exception.Message)"
    }
    if ([string]::IsNullOrWhiteSpace($Version)) {
        Fail "Latest release did not include a tag_name."
    }
    Write-PythinkerLog "Latest version: $Version"
}

if ($Version -notmatch '^[0-9]+(\.[0-9]+){1,3}([a-zA-Z0-9.+-]+)?$') {
    Fail "Refusing suspicious version value: $Version"
}

$asset = "PythinkerSetup-$Version.exe"
$baseUrl = "https://github.com/$Repo/releases/download/v$Version"
$exeUrl = "$baseUrl/$asset"
$shaUrl = "$exeUrl.sha256"

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "pythinker-ai-install-$PID"
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$exePath = Join-Path $tempRoot $asset
$shaPath = "$exePath.sha256"

try {
    Write-PythinkerLog "Downloading $asset..."
    Invoke-Download -Uri $exeUrl -OutFile $exePath
    Invoke-Download -Uri $shaUrl -OutFile $shaPath

    Write-PythinkerLog "Verifying SHA-256..."
    $expected = ((Get-Content -Raw $shaPath).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -Path $exePath).Hash.ToLowerInvariant()
    if ($expected -ne $actual) {
        Fail "SHA-256 mismatch. Expected $expected but got $actual."
    }
    Write-PythinkerLog "SHA-256 OK"

    $installerArgs = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if ($AllUsers) {
        $installerArgs += "/ALLUSERS"
    }

    Write-PythinkerLog "Running installer..."
    $proc = Start-Process -FilePath $exePath -ArgumentList $installerArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Fail "Installer exited with code $($proc.ExitCode)."
    }

    Write-PythinkerLog "Installed Pythinker $Version."
    Write-PythinkerLog "Open a new PowerShell, then run: pythinker-ai --version"
}
finally {
    if (-not $KeepInstaller) {
        Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
    }
    else {
        Write-PythinkerWarn "Kept downloaded installer at $tempRoot"
    }
}
