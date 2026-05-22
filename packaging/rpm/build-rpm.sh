#!/usr/bin/env bash
# Build a Fedora / RHEL / openSUSE .rpm package from a PyInstaller --onedir
# bundle.
#
# Inputs (env):
#   VERSION   — semver string, e.g. 2.7.0 (required)
#   ARCH      — rpm arch: x86_64 | aarch64 (default x86_64)
#   BUNDLE    — path to the PyInstaller `dist/pythinker/` directory (required)
#   OUTDIR    — where to drop the .rpm (default ./dist/linux)
#
# Output:
#   ${OUTDIR}/pythinker-ai-${VERSION}.${ARCH}.rpm  + .sha256 sidecar

set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${BUNDLE:?BUNDLE is required (path to PyInstaller dist/pythinker dir)}"
ARCH="${ARCH:-x86_64}"
OUTDIR="${OUTDIR:-./dist/linux}"

case "${ARCH}" in
  x86_64|aarch64) ;;
  *) echo "Unsupported ARCH: ${ARCH} (use x86_64 or aarch64)" >&2; exit 2 ;;
esac

if [[ ! -d "${BUNDLE}" ]]; then
  echo "BUNDLE directory not found: ${BUNDLE}" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="${HERE}/pythinker-ai.spec"
[[ -f "${SPEC}" ]] || { echo "Missing spec: ${SPEC}" >&2; exit 2; }

TOP="$(mktemp -d)"
trap 'rm -rf "${TOP}"' EXIT

mkdir -p "${TOP}/BUILD/bundle" "${TOP}/RPMS" "${TOP}/SRPMS" "${TOP}/SPECS"
cp -a "${BUNDLE}/." "${TOP}/BUILD/bundle/"
cp "${SPEC}" "${TOP}/SPECS/"

rpmbuild \
  --define "_topdir ${TOP}" \
  --define "rpm_version ${VERSION}" \
  --define "rpm_arch ${ARCH}" \
  --define "_binary_payload w7.xzdio" \
  --target "${ARCH}" \
  -bb "${TOP}/SPECS/pythinker-ai.spec"

BUILT="${TOP}/RPMS/${ARCH}/pythinker-ai-${VERSION}-1.fc$(rpm --eval '%{fedora}' 2>/dev/null || echo '0').${ARCH}.rpm"
if [[ ! -f "${BUILT}" ]]; then
  # Fall back to whatever rpmbuild produced (dist tag varies by host).
  BUILT="$(find "${TOP}/RPMS/${ARCH}" -name '*.rpm' | head -n1)"
fi
[[ -f "${BUILT}" ]] || { echo "rpmbuild produced no .rpm under ${TOP}/RPMS/${ARCH}" >&2; exit 1; }

mkdir -p "${OUTDIR}"
# Normalize filename to drop the .fcNN dist tag — GH Release uses one stable name.
NORMALIZED="${OUTDIR}/pythinker-ai-${VERSION}.${ARCH}.rpm"
cp "${BUILT}" "${NORMALIZED}"
(cd "${OUTDIR}" && sha256sum "$(basename "${NORMALIZED}")" >"$(basename "${NORMALIZED}").sha256")

echo "Built ${NORMALIZED}"
echo "SHA256: $(cat "${NORMALIZED}.sha256")"
