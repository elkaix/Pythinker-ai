#!/usr/bin/env bash
# Legacy uv-based installer for Pythinker.
#
# DEPRECATED: This shell wrapper is kept for backward compatibility with old
# automation. New installs should use the native installers — Homebrew tap on
# macOS, .deb on Debian/Ubuntu, .rpm on Fedora/RHEL, or scripts/install-native.sh
# on any POSIX host. See the README install table.
#
# Set PYTHINKER_AI_INSTALL_QUIET_DEPRECATION=1 to silence the banner.

set -euo pipefail

if [[ "${PYTHINKER_AI_INSTALL_QUIET_DEPRECATION:-0}" != "1" ]]; then
  cat >&2 <<'BANNER'

[pythinker] WARNING: scripts/install.sh is deprecated.
[pythinker] Prefer the native installer for your platform:
[pythinker]   brew install mohamed-elkholy95/pythinker/pythinker-ai      (macOS)
[pythinker]   sudo dpkg  -i pythinker-ai_*_amd64.deb                     (Debian/Ubuntu)
[pythinker]   sudo rpm   -i pythinker-ai-*.x86_64.rpm                    (Fedora/RHEL)
[pythinker]   curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker/main/scripts/install-native.sh | bash
[pythinker] Silence this banner with PYTHINKER_AI_INSTALL_QUIET_DEPRECATION=1.

BANNER
fi

# Fall back to uv tool install — the historical behavior of this script.
if ! command -v uv >/dev/null 2>&1; then
  echo "[pythinker] uv is required by the legacy installer. Install it first:" >&2
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

exec uv tool install --upgrade pythinker-ai "$@"
