#!/usr/bin/env bash
# Cross-OS native installer for Pythinker.
#
# Detects host OS + architecture, downloads the matching PyInstaller-frozen
# tarball from the GitHub release, verifies its SHA-256, and lands the binary
# at $PREFIX/bin/pythinker-ai (default $HOME/.local/bin).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker/main/scripts/install-native.sh | bash
#   curl -fsSL ... | bash -s -- --version 2.7.0
#   curl -fsSL ... | bash -s -- --prefix /opt/pythinker
#
# Supported targets:
#   Linux x86_64      -> pythinker-{ver}-x86_64-unknown-linux-gnu.tar.gz
#   Linux aarch64     -> pythinker-{ver}-aarch64-unknown-linux-gnu.tar.gz
#   macOS arm64       -> pythinker-{ver}-aarch64-apple-darwin.tar.gz
#
# Intel macOS is not a published target — fall back to Homebrew or pip.

set -euo pipefail

REPO="${PYTHINKER_AI_REPO:-mohamed-elkholy95/Pythinker}"
VERSION=""
PREFIX="${HOME}/.local"

log()  { printf '\033[36m[pythinker]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[pythinker]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[pythinker]\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:?--version requires a value}"; shift 2 ;;
    --prefix)  PREFIX="${2:?--prefix requires a value}";   shift 2 ;;
    --help|-h)
      sed -n '3,18p' "$0"
      exit 0
      ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || die "Missing required tool: $1"; }
need curl
need tar
# Prefer sha256sum (coreutils on Linux), fall back to shasum (macOS).
if command -v sha256sum >/dev/null 2>&1; then
  SHA256_CMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  SHA256_CMD="shasum -a 256"
else
  die "Need sha256sum or shasum to verify download integrity"
fi

# --- Detect target -----------------------------------------------------------
UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"
case "${UNAME_S}-${UNAME_M}" in
  Linux-x86_64)        TARGET="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64)       TARGET="aarch64-unknown-linux-gnu" ;;
  Linux-arm64)         TARGET="aarch64-unknown-linux-gnu" ;;
  Darwin-arm64)        TARGET="aarch64-apple-darwin" ;;
  Darwin-x86_64)
    die "Intel macOS has no PyInstaller tarball. Use:
  brew install mohamed-elkholy95/pythinker/pythinker-ai
or:
  pip install pythinker-ai"
    ;;
  *) die "Unsupported host: ${UNAME_S} ${UNAME_M}" ;;
esac
log "Detected target: ${TARGET}"

# --- Resolve version (latest if not pinned) ----------------------------------
if [[ -z "${VERSION}" ]]; then
  log "Resolving latest release from ${REPO}…"
  LATEST_URL="https://api.github.com/repos/${REPO}/releases/latest"
  VERSION="$(curl -fsSL "${LATEST_URL}" \
    | grep -E '"tag_name"\s*:' \
    | head -n1 \
    | sed -E 's/.*"tag_name"\s*:\s*"v?([^"]+)".*/\1/')"
  [[ -n "${VERSION}" ]] || die "Could not determine latest version from ${LATEST_URL}"
  log "Latest version: ${VERSION}"
fi

ASSET="pythinker-${VERSION}-${TARGET}.tar.gz"
BASE_URL="https://github.com/${REPO}/releases/download/v${VERSION}"
TARBALL_URL="${BASE_URL}/${ASSET}"
SHA_URL="${TARBALL_URL}.sha256"

# --- Download + verify -------------------------------------------------------
TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

log "Downloading ${ASSET}…"
curl -fsSL --output "${TMPDIR}/${ASSET}"      "${TARBALL_URL}" \
  || die "Failed to download ${TARBALL_URL}"
curl -fsSL --output "${TMPDIR}/${ASSET}.sha256" "${SHA_URL}" \
  || die "Failed to download ${SHA_URL}"

log "Verifying SHA-256…"
EXPECTED="$(awk '{print $1}' "${TMPDIR}/${ASSET}.sha256")"
ACTUAL="$(${SHA256_CMD} "${TMPDIR}/${ASSET}" | awk '{print $1}')"
if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
  die "SHA-256 mismatch
  expected: ${EXPECTED}
  actual:   ${ACTUAL}"
fi
log "SHA-256 OK"

# --- Install -----------------------------------------------------------------
INSTALL_LIB="${PREFIX}/lib/pythinker"
INSTALL_BIN="${PREFIX}/bin"
mkdir -p "${INSTALL_LIB}" "${INSTALL_BIN}"

log "Unpacking into ${INSTALL_LIB}…"
# Tarball contains a top-level `pythinker/` dir from PyInstaller --onedir.
tar -xzf "${TMPDIR}/${ASSET}" -C "${TMPDIR}"
# Wipe any prior install of the same prefix so stale data files don't linger.
rm -rf "${INSTALL_LIB:?}/"*
cp -a "${TMPDIR}/pythinker/." "${INSTALL_LIB}/"

# Thin launcher (one PATH entry instead of dumping the whole bundle dir on PATH).
LAUNCHER="${INSTALL_BIN}/pythinker-ai"
cat >"${LAUNCHER}" <<LAUNCH
#!/bin/sh
exec "${INSTALL_LIB}/pythinker-ai" "\$@"
LAUNCH
chmod 0755 "${LAUNCHER}"

log "Installed pythinker ${VERSION} at ${LAUNCHER}"

# --- PATH advice -------------------------------------------------------------
case ":${PATH}:" in
  *":${INSTALL_BIN}:"*) ;;
  *)
    warn "${INSTALL_BIN} is not on your PATH yet."
    warn "Add this to your shell rc (e.g. ~/.bashrc or ~/.zshrc):"
    warn "  export PATH=\"${INSTALL_BIN}:\$PATH\""
    ;;
esac

log "Run: pythinker-ai --version"
