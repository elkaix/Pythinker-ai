#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb package from a PyInstaller --onedir bundle.
#
# Inputs (env):
#   VERSION   — semver string, e.g. 2.7.0 (required)
#   ARCH      — debian arch: amd64 | arm64 (default amd64)
#   BUNDLE    — path to the PyInstaller `dist/pythinker/` directory (required)
#   OUTDIR    — where to drop the .deb (default ./dist/linux)
#
# Output:
#   ${OUTDIR}/pythinker-ai_${VERSION}_${ARCH}.deb  + .sha256 sidecar
#
# Layout produced inside the package:
#   /usr/lib/pythinker/        -- the frozen bundle
#   /usr/bin/pythinker         -- thin launcher exec'ing /usr/lib/pythinker/pythinker
#   /usr/share/doc/pythinker-ai/{copyright,changelog.Debian.gz}

set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${BUNDLE:?BUNDLE is required (path to PyInstaller dist/pythinker dir)}"
ARCH="${ARCH:-amd64}"
OUTDIR="${OUTDIR:-./dist/linux}"

case "${ARCH}" in
  amd64|arm64) ;;
  *) echo "Unsupported ARCH: ${ARCH} (use amd64 or arm64)" >&2; exit 2 ;;
esac

if [[ ! -d "${BUNDLE}" ]]; then
  echo "BUNDLE directory not found: ${BUNDLE}" >&2
  exit 2
fi

PKG_NAME="pythinker-ai"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

ROOT="${WORK}/pkgroot"
mkdir -p \
  "${ROOT}/DEBIAN" \
  "${ROOT}/usr/lib/pythinker" \
  "${ROOT}/usr/bin" \
  "${ROOT}/usr/share/doc/${PKG_NAME}"

# Copy the frozen bundle.
cp -a "${BUNDLE}/." "${ROOT}/usr/lib/pythinker/"

# Thin launcher — keeps $PATH tidy (one entry, not the whole bundle dir).
cat >"${ROOT}/usr/bin/pythinker" <<'LAUNCH'
#!/bin/sh
exec /usr/lib/pythinker/pythinker "$@"
LAUNCH
chmod 0755 "${ROOT}/usr/bin/pythinker"

# control file
INSTALLED_SIZE=$(du -sk "${ROOT}/usr" | awk '{print $1}')
cat >"${ROOT}/DEBIAN/control" <<CONTROL
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Mohamed Elkholy <moelkholy1995@gmail.com>
Homepage: https://github.com/mohamed-elkholy95/Pythinker
Description: Tiny async agent framework with chat channels, memory, MCP, and an OpenAI-compatible API
 Pythinker is a Python, asyncio-native agent runtime that runs one assistant
 across many chat platforms and APIs. This package ships a self-contained
 PyInstaller bundle of the \`pythinker\` CLI; no Python install required.
CONTROL

# copyright (MIT)
cat >"${ROOT}/usr/share/doc/${PKG_NAME}/copyright" <<'COPY'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: pythinker-ai
Source: https://github.com/mohamed-elkholy95/Pythinker

Files: *
Copyright: 2025-2026 Mohamed Elkholy
License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in
 all copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
COPY

# Minimal changelog (gzipped, as Debian policy requires).
cat >"${WORK}/changelog" <<CHANGE
${PKG_NAME} (${VERSION}) unstable; urgency=medium

  * Release ${VERSION}. See https://github.com/mohamed-elkholy95/Pythinker/blob/main/CHANGELOG.md

 -- Mohamed Elkholy <moelkholy1995@gmail.com>  $(date -u +"%a, %d %b %Y %H:%M:%S +0000")
CHANGE
gzip -9n -c "${WORK}/changelog" >"${ROOT}/usr/share/doc/${PKG_NAME}/changelog.Debian.gz"

mkdir -p "${OUTDIR}"
OUT="${OUTDIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build --root-owner-group "${ROOT}" "${OUT}"

(cd "${OUTDIR}" && sha256sum "$(basename "${OUT}")" >"$(basename "${OUT}").sha256")

echo "Built ${OUT}"
echo "SHA256: $(cat "${OUT}.sha256")"
