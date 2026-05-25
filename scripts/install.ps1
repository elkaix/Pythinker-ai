# Legacy uv-based installer for Pythinker on Windows PowerShell.
#
# DEPRECATED: This wrapper exists for backward compatibility. New Windows
# installs should use PythinkerSetup-{version}.exe from the GitHub release.
#
# Set $env:PYTHINKER_AI_INSTALL_QUIET_DEPRECATION = "1" to silence the banner.

$ErrorActionPreference = "Stop"

if ($env:PYTHINKER_AI_INSTALL_QUIET_DEPRECATION -ne "1") {
    Write-Warning @"

scripts/install.ps1 is deprecated.
Prefer the native Windows installer:
  https://github.com/mohamed-elkholy95/Pythinker/releases/latest
  -> PythinkerSetup-<version>.exe
Silence this banner with `$env:PYTHINKER_AI_INSTALL_QUIET_DEPRECATION = "1"`.

"@
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error @"
uv is required by the legacy installer. Install it first:
  irm https://astral.sh/uv/install.ps1 | iex
"@
    exit 1
}

& uv tool install --upgrade pythinker-ai @args
exit $LASTEXITCODE
