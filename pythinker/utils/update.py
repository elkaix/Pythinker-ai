"""PyPI update-check + self-upgrade helpers.

Two surfaces:

* Pure helpers (``parse_pypi_response``, ``select_latest_version``,
  ``detect_install_method``, ``upgrade_command``) — no I/O, easy to unit-test.
* Side-effect wrappers (``fetch_pypi_metadata``, ``check_for_update``) — perform
  the network request and read/write the cache file under ``get_update_dir()``.

Notify-only by default. ``pythinker-ai update`` does the actual upgrade behind a
``filelock``; long-running daemons just emit a one-line banner.
"""

from __future__ import annotations

import asyncio
import enum
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from packaging.version import InvalidVersion, Version

from pythinker import __version__
from pythinker.config.paths import get_update_dir

PACKAGE_NAME = "pythinker-ai"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"

DEFAULT_TIMEOUT_S = 3.0
DEFAULT_CACHE_TTL_S = 24 * 3600
DEFAULT_FAILURE_TTL_S = 15 * 60  # short TTL on PyPI failure so transient outages don't pin users

ENV_DISABLE = "PYTHINKER_AI_NO_UPDATE_CHECK"
ENV_NO_AUTO_UPDATE = "PYTHINKER_AI_CLI_NO_AUTO_UPDATE"

CACHE_FILENAME = "state.json"
LOCK_FILENAME = ".lock"

GITHUB_REPO = "mohamed-elkholy95/Pythinker"
POSIX_INSTALL_URL = "https://pythinker.com/ai"
WINDOWS_INSTALL_URL = "https://pythinker.com/ai.ps1"
GITHUB_RELEASES_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class InstallMethod(str, enum.Enum):
    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    PIP_VENV = "pip-venv"
    PIP_SYSTEM = "pip-system"
    EDITABLE = "editable"
    CONTAINER = "container"
    # Native installers added in 2.7.0. Each one ships from the GitHub Release
    # alongside the PyPI wheel; the in-app `pythinker-ai update` command verifies
    # SHA-256 of the downloaded asset before re-running the installer.
    HOMEBREW = "homebrew"
    DEB = "deb"
    RPM = "rpm"
    NATIVE_TARBALL = "native-tarball"
    WINDOWS_EXE = "windows-exe"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str | None
    update_available: bool
    is_yanked: bool
    install_method: InstallMethod
    checked_ok: bool
    error_kind: str | None  # "network" | "parse" | "no-acceptable-release" | None
    error_message: str | None
    fetched_at: float
    cache_expires_at: float
    from_cache: bool
    last_notified: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def parse_pypi_response(payload: dict[str, Any]) -> tuple[list[str], dict[str, bool]]:
    """Return ``(versions_newest_first, yanked_map)`` from a PyPI JSON payload.

    ``yanked_map`` maps version → True when *any* file for that version is
    yanked.  PyPI's "yank" is per-file but in practice yanking a release
    yanks all its files; treat any yanked file as a fully yanked release.
    """
    releases = payload.get("releases") or {}
    if not isinstance(releases, dict):
        return [], {}

    parsed: list[tuple[Version, str]] = []
    yanked_map: dict[str, bool] = {}
    for raw_version, files in releases.items():
        if not isinstance(raw_version, str):
            continue
        try:
            v = Version(raw_version)
        except InvalidVersion:
            continue
        parsed.append((v, raw_version))
        is_yanked = False
        if isinstance(files, list):
            is_yanked = any(isinstance(f, dict) and bool(f.get("yanked")) for f in files)
        yanked_map[raw_version] = is_yanked

    parsed.sort(key=lambda t: t[0], reverse=True)
    return [raw for _, raw in parsed], yanked_map


def select_latest_version(
    versions: list[str],
    yanked: dict[str, bool],
    *,
    include_prereleases: bool = False,
) -> str | None:
    """Pick the highest acceptable version (skipping yanks and pre-releases by default)."""
    for raw in versions:
        if yanked.get(raw):
            continue
        try:
            v = Version(raw)
        except InvalidVersion:
            continue
        if v.is_prerelease and not include_prereleases:
            continue
        return raw
    return None


def detect_install_method() -> InstallMethod:
    """Best-effort detection of how this pythinker was installed.

    Used to route the upgrade through the right tool.  Errs on the side of
    ``UNKNOWN`` when we can't be confident — the caller refuses auto-upgrade
    in that case.

    Detection order matters: native installers (homebrew/deb/rpm/exe/
    pyinstaller-tarball) are checked *first*, because a PyInstaller-frozen
    bundle's ``sys.prefix`` does not point at a real Python prefix and the
    legacy heuristics would otherwise mis-label it as PIP_SYSTEM.
    """
    # 1. Frozen PyInstaller bundle (the native installers all ship one).
    if getattr(sys, "frozen", False):
        return _detect_frozen_install_method()

    # 2. Editable / source checkout: pythinker imports from outside site-packages.
    try:
        import pythinker as _pythinker

        pkg_path = Path(_pythinker.__file__).resolve()
    except Exception:
        pkg_path = None

    if pkg_path and "site-packages" not in pkg_path.parts and "dist-packages" not in pkg_path.parts:
        return InstallMethod.EDITABLE

    if _running_in_container():
        return InstallMethod.CONTAINER

    prefix = Path(sys.prefix).resolve()
    parts = [p.lower() for p in prefix.parts]

    # uv tool: the venv lives under .../uv/tools/<name>/  (POSIX) or %LOCALAPPDATA%\uv\tools\
    for i, part in enumerate(parts):
        if part == "uv" and i + 1 < len(parts) and parts[i + 1] == "tools":
            return InstallMethod.UV_TOOL

    # pipx: the venv lives under .../pipx/venvs/<name>/
    for i, part in enumerate(parts):
        if part == "pipx" and i + 1 < len(parts) and parts[i + 1] == "venvs":
            return InstallMethod.PIPX

    # Generic venv (pip install in a virtualenv).
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return InstallMethod.PIP_VENV

    # System Python — refuse to mutate without explicit user action.
    return InstallMethod.PIP_SYSTEM


def _detect_frozen_install_method() -> InstallMethod:
    """Disambiguate native installs once we know we're in a PyInstaller bundle.

    The frozen binary lives at ``sys.executable``; the surrounding directory
    tells us which native installer dropped it:

      * ``%LOCALAPPDATA%\\Programs\\Pythinker`` or ``%ProgramFiles%\\Pythinker`` -> Inno EXE
      * ``/opt/homebrew/Cellar/pythinker-ai`` or ``/usr/local/Cellar/...``   -> Homebrew
      * dpkg / rpm report ownership of the binary                           -> DEB / RPM
      * ``~/.local/lib/pythinker`` or any other prefix                      -> native tarball
    """
    exe = Path(sys.executable).resolve()
    exe_parts_lower = [p.lower() for p in exe.parts]

    # Windows Inno install dirs.
    if sys.platform == "win32":
        marker_paths = (
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
        )
        for marker in marker_paths:
            if marker and marker.lower() in str(exe).lower():
                if "pythinker" in exe_parts_lower:
                    return InstallMethod.WINDOWS_EXE
        return InstallMethod.WINDOWS_EXE  # any frozen .exe on Windows

    # Homebrew Cellar layout: /opt/homebrew/Cellar/pythinker-ai/<ver>/...
    if "cellar" in exe_parts_lower:
        return InstallMethod.HOMEBREW

    # dpkg / rpm ownership query — definitive on Linux when the tools exist.
    if sys.platform.startswith("linux"):
        owner = _query_linux_package_owner(exe)
        if owner == "dpkg":
            return InstallMethod.DEB
        if owner == "rpm":
            return InstallMethod.RPM

    # Default for any other frozen layout (curl-bash native tarball).
    return InstallMethod.NATIVE_TARBALL


def _query_linux_package_owner(exe_path: Path) -> str | None:
    """Return ``"dpkg"`` / ``"rpm"`` if a package manager owns ``exe_path``."""
    import shutil
    import subprocess

    # The frozen binary lives under /usr/lib/pythinker for both .deb and .rpm;
    # the launcher at /usr/bin/pythinker-ai is what dpkg/rpm tracks. Resolve to
    # one of those before querying.
    candidates: list[Path] = [exe_path]
    launcher = Path("/usr/bin/pythinker-ai")
    if launcher.exists():
        candidates.append(launcher)

    if shutil.which("dpkg-query"):
        for cand in candidates:
            try:
                proc = subprocess.run(
                    ["dpkg-query", "-S", str(cand)],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if proc.returncode == 0 and "pythinker-ai" in proc.stdout:
                return "dpkg"

    if shutil.which("rpm"):
        for cand in candidates:
            try:
                proc = subprocess.run(
                    ["rpm", "-qf", str(cand)],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if proc.returncode == 0 and "pythinker-ai" in proc.stdout:
                return "rpm"

    return None


def _running_in_container() -> bool:
    """Cheap container heuristic.  Not bulletproof; conservative on false positives."""
    if Path("/.dockerenv").exists():
        return True
    cgroup = Path("/proc/1/cgroup")
    if cgroup.exists():
        try:
            text = cgroup.read_text(errors="replace")
        except OSError:
            return False
        for marker in ("docker", "kubepods", "containerd", "podman"):
            if marker in text:
                return True
    return False


def upgrade_command(method: InstallMethod) -> list[str] | None:
    """Return the argv to run for an upgrade, or ``None`` if we should refuse.

    The caller is responsible for printing the suggested command when
    auto-run is refused.  Never use ``uv tool install`` for upgrades — it
    would replace any version constraint the user pinned at install time.
    """
    if method is InstallMethod.UV_TOOL:
        return ["uv", "tool", "upgrade", PACKAGE_NAME]
    if method is InstallMethod.PIPX:
        return ["pipx", "upgrade", PACKAGE_NAME]
    if method is InstallMethod.PIP_VENV:
        return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME]
    if method is InstallMethod.HOMEBREW:
        # `brew update` first so the tap formula refresh actually surfaces a
        # newer version; `brew upgrade` is a no-op otherwise.
        return ["sh", "-c", f"brew update && brew upgrade {PACKAGE_NAME}"]
    # DEB / RPM / NATIVE_TARBALL / WINDOWS_EXE upgrade in `native_upgrade()`
    # because they need to download + SHA-verify the asset before invoking
    # dpkg / rpm / installer. PIP_SYSTEM, EDITABLE, CONTAINER, UNKNOWN: print only.
    return None


def target_install_command(method: InstallMethod, version: str) -> list[str] | None:
    """Return the argv to install ``version`` exactly, or ``None`` if unsafe.

    Distinct from :func:`upgrade_command` because:

    - ``uv tool upgrade`` honors the existing version pin and silently no-ops
      when the pin excludes ``version``. Exact-version installs need
      ``uv tool install --reinstall "<pkg>==<ver>"`` to overwrite the pin.
    - ``pipx upgrade`` always picks the latest. ``pipx install --force`` can
      target a specific version.
    - ``pip install --force-reinstall "<pkg>==<ver>"`` is the canonical
      exact-version reinstall path.

    EDITABLE / CONTAINER / UNKNOWN refuse exact-version installs because the
    install method doesn't have a stable repackaging path; the maintainer
    must rebuild the image / re-clone / pip install from source manually.
    """
    if method is InstallMethod.UV_TOOL:
        return ["uv", "tool", "install", "--reinstall", f"{PACKAGE_NAME}=={version}"]
    if method is InstallMethod.PIPX:
        return ["pipx", "install", "--force", f"{PACKAGE_NAME}=={version}"]
    if method is InstallMethod.PIP_VENV:
        return [
            sys.executable, "-m", "pip", "install", "--force-reinstall",
            f"{PACKAGE_NAME}=={version}",
        ]
    # PIP_SYSTEM is allowed but printed-only (system pip mutation needs
    # explicit user consent); EDITABLE / CONTAINER / UNKNOWN refuse outright.
    return None


def suggested_target_command(method: InstallMethod, version: str) -> str:
    """Copy-pasteable exact-version command for every install method."""
    cmd = target_install_command(method, version)
    if cmd is not None:
        return " ".join(cmd)
    if method is InstallMethod.PIP_SYSTEM:
        return f'python -m pip install --force-reinstall "{PACKAGE_NAME}=={version}"'
    if method is InstallMethod.EDITABLE:
        return (
            f"git fetch --tags && git checkout v{version} && uv sync --all-extras  "
            "# editable installs follow the working tree, not a published version"
        )
    if method is InstallMethod.CONTAINER:
        return (
            f"docker pull <image>:{version}  "
            f"# or rebuild the image with {PACKAGE_NAME}=={version} pinned"
        )
    if method is InstallMethod.HOMEBREW:
        return (
            f"brew uninstall {PACKAGE_NAME} && "
            f"brew install mohamed-elkholy95/pythinker/{PACKAGE_NAME}@{version}  "
            "# requires a version-pinned formula in the tap"
        )
    if method is InstallMethod.DEB:
        return (
            f"curl -fL -o /tmp/pythinker.deb "
            f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/{PACKAGE_NAME}_{version}_$(dpkg --print-architecture).deb "
            f"&& sudo dpkg -i /tmp/pythinker.deb"
        )
    if method is InstallMethod.RPM:
        return (
            f"sudo rpm -U https://github.com/{GITHUB_REPO}/releases/download/v{version}/{PACKAGE_NAME}-{version}.$(uname -m).rpm"
        )
    if method is InstallMethod.NATIVE_TARBALL:
        return f"curl -fsSL {POSIX_INSTALL_URL} | bash -s -- --version {version}"
    if method is InstallMethod.WINDOWS_EXE:
        return f"& ([scriptblock]::Create((irm {WINDOWS_INSTALL_URL}))) -Version {version}"
    return f'pip install --force-reinstall "{PACKAGE_NAME}=={version}"'


def suggested_upgrade_command(method: InstallMethod) -> str:
    """Always return a copy-pasteable command, even when auto-upgrade is refused."""
    cmd = upgrade_command(method)
    if cmd is not None:
        return " ".join(cmd)
    if method is InstallMethod.PIP_SYSTEM:
        return f"python -m pip install --upgrade {PACKAGE_NAME}"
    if method is InstallMethod.EDITABLE:
        return "git pull && uv sync --all-extras  # or: pip install -e ."
    if method is InstallMethod.CONTAINER:
        return f"docker pull <image>  # or rebuild the image with the new {PACKAGE_NAME} version"
    if method is InstallMethod.DEB:
        return (
            f"# `pythinker-ai update` downloads + verifies + installs the matching "
            f"{PACKAGE_NAME}_<ver>_$(dpkg --print-architecture).deb  (needs sudo)"
        )
    if method is InstallMethod.RPM:
        return (
            f"# `pythinker-ai update` downloads + verifies + installs the matching "
            f"{PACKAGE_NAME}-<ver>.$(uname -m).rpm  (needs sudo)"
        )
    if method is InstallMethod.NATIVE_TARBALL:
        return f"curl -fsSL {POSIX_INSTALL_URL} | bash"
    if method is InstallMethod.WINDOWS_EXE:
        return f"irm {WINDOWS_INSTALL_URL} | iex"
    return f"pip install --upgrade {PACKAGE_NAME}"


# ---------------------------------------------------------------------------
# Side-effect wrappers (network + filesystem)
# ---------------------------------------------------------------------------


async def fetch_pypi_metadata(*, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Fetch the PyPI JSON metadata blob.  Caller handles all exceptions."""
    timeout = httpx.Timeout(timeout_s, connect=min(2.0, timeout_s))
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(PYPI_JSON_URL, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()


def _cache_file() -> Path:
    return get_update_dir() / CACHE_FILENAME


def _read_cache() -> dict[str, Any] | None:
    path = _cache_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(data: dict[str, Any]) -> None:
    path = _cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: temp file then rename.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.debug("update: failed to write update cache at {}", path)


def _info_from_cache(cache: dict[str, Any]) -> UpdateInfo | None:
    """Reconstruct an ``UpdateInfo`` from a cache record.  Returns ``None`` if invalid."""
    try:
        return UpdateInfo(
            current=cache["current"],
            latest=cache.get("latest"),
            update_available=bool(cache.get("update_available")),
            is_yanked=bool(cache.get("is_yanked")),
            install_method=InstallMethod(cache.get("install_method", InstallMethod.UNKNOWN.value)),
            checked_ok=bool(cache.get("checked_ok")),
            error_kind=cache.get("error_kind"),
            error_message=cache.get("error_message"),
            fetched_at=float(cache.get("fetched_at", 0)),
            cache_expires_at=float(cache.get("cache_expires_at", 0)),
            from_cache=True,
            last_notified=cache.get("last_notified"),
        )
    except (KeyError, ValueError):
        return None


def _persist_info(info: UpdateInfo, *, last_notified: str | None = None) -> None:
    payload = asdict(info)
    payload["install_method"] = info.install_method.value
    payload["from_cache"] = False  # caller will mark from_cache when re-reading
    if last_notified is not None:
        payload["last_notified"] = last_notified
    _write_cache(payload)


def mark_notified(version: str) -> None:
    """Record that the user has been notified about ``version`` so we don't repeat."""
    cache = _read_cache() or {}
    cache["last_notified"] = version
    _write_cache(cache)


async def check_for_update(
    *,
    include_prereleases: bool = False,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
    failure_ttl_s: int = DEFAULT_FAILURE_TTL_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    force_refresh: bool = False,
) -> UpdateInfo:
    """Return the current update state, hitting the cache first."""
    if os.environ.get(ENV_DISABLE) == "1":
        return _disabled_info()

    cache = _read_cache() if not force_refresh else None
    now = time.time()
    if cache and cache.get("cache_expires_at", 0) > now:
        cached = _info_from_cache(cache)
        if cached is not None and cached.current == __version__:
            return cached

    method = detect_install_method()
    try:
        payload = await fetch_pypi_metadata(timeout_s=timeout_s)
    except (httpx.TimeoutException, httpx.HTTPError) as e:
        return _failure_info(method, "network", str(e), now=now, ttl=failure_ttl_s)
    except Exception as e:  # noqa: BLE001 — last-resort guard; never fail the caller
        return _failure_info(method, "parse", str(e), now=now, ttl=failure_ttl_s)

    versions, yanked = parse_pypi_response(payload)
    latest = select_latest_version(versions, yanked, include_prereleases=include_prereleases)
    is_yanked_current = bool(yanked.get(__version__, False))

    if latest is None:
        info = UpdateInfo(
            current=__version__,
            latest=None,
            update_available=False,
            is_yanked=is_yanked_current,
            install_method=method,
            checked_ok=True,
            error_kind="no-acceptable-release",
            error_message="PyPI returned no acceptable release after filtering",
            fetched_at=now,
            cache_expires_at=now + cache_ttl_s,
            from_cache=False,
            last_notified=(cache or {}).get("last_notified"),
        )
        _persist_info(info, last_notified=info.last_notified)
        return info

    try:
        update_available = Version(latest) > Version(__version__)
    except InvalidVersion:
        update_available = False

    info = UpdateInfo(
        current=__version__,
        latest=latest,
        update_available=update_available,
        is_yanked=is_yanked_current,
        install_method=method,
        checked_ok=True,
        error_kind=None,
        error_message=None,
        fetched_at=now,
        cache_expires_at=now + cache_ttl_s,
        from_cache=False,
        last_notified=(cache or {}).get("last_notified"),
    )
    _persist_info(info, last_notified=info.last_notified)
    return info


def _disabled_info() -> UpdateInfo:
    return UpdateInfo(
        current=__version__,
        latest=None,
        update_available=False,
        is_yanked=False,
        install_method=detect_install_method(),
        checked_ok=False,
        error_kind="disabled",
        error_message=f"Update check disabled via {ENV_DISABLE}=1",
        fetched_at=0.0,
        cache_expires_at=0.0,
        from_cache=False,
    )


def _failure_info(
    method: InstallMethod, kind: str, message: str, *, now: float, ttl: int
) -> UpdateInfo:
    info = UpdateInfo(
        current=__version__,
        latest=None,
        update_available=False,
        is_yanked=False,
        install_method=method,
        checked_ok=False,
        error_kind=kind,
        error_message=message[:200],
        fetched_at=now,
        cache_expires_at=now + ttl,
        from_cache=False,
    )
    _persist_info(info)
    return info


# ---------------------------------------------------------------------------
# Convenience wrappers used by the CLI banner / doctor / status hooks
# ---------------------------------------------------------------------------


def check_for_update_sync(**kwargs: Any) -> UpdateInfo:
    """Synchronous shim around :func:`check_for_update` for callers in sync contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        # We're inside a running loop — don't deadlock; fail gracefully.
        return _disabled_info()
    return asyncio.run(check_for_update(**kwargs))


def format_banner(info: UpdateInfo) -> str | None:
    """Return a short single-line update banner, or ``None`` when nothing to say."""
    if info.is_yanked:
        suggest = info.latest or "the latest non-yanked release"
        return (
            f"⚠  Your pythinker {info.current} was yanked from PyPI. "
            f"Upgrade to {suggest} via: {suggested_upgrade_command(info.install_method)}"
        )
    if info.update_available and info.latest:
        return (
            f"ℹ  pythinker {info.latest} is available (you have {info.current}). "
            f"Run: {suggested_upgrade_command(info.install_method)}"
        )
    return None


# ---------------------------------------------------------------------------
# Native-installer upgrade path (DEB / RPM / native tarball / Windows EXE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativeAsset:
    """Describes one GitHub-Release artifact for a (method, version, arch) triple."""

    filename: str
    method: InstallMethod
    needs_sudo: bool


def native_asset_for(method: InstallMethod, version: str) -> NativeAsset | None:
    """Compute the release-asset filename matching the host arch for ``method``.

    Returns ``None`` when ``method`` doesn't ship a GH-Release artifact.
    """
    import platform

    machine = platform.machine().lower()
    if method is InstallMethod.DEB:
        arch = "amd64" if machine in ("x86_64", "amd64") else (
            "arm64" if machine in ("aarch64", "arm64") else None
        )
        if arch is None:
            return None
        return NativeAsset(
            filename=f"{PACKAGE_NAME}_{version}_{arch}.deb",
            method=method,
            needs_sudo=True,
        )
    if method is InstallMethod.RPM:
        if machine not in ("x86_64", "aarch64"):
            return None
        return NativeAsset(
            filename=f"{PACKAGE_NAME}-{version}.{machine}.rpm",
            method=method,
            needs_sudo=True,
        )
    if method is InstallMethod.NATIVE_TARBALL:
        if sys.platform.startswith("linux"):
            if machine in ("x86_64", "amd64"):
                target = "x86_64-unknown-linux-gnu"
            elif machine in ("aarch64", "arm64"):
                target = "aarch64-unknown-linux-gnu"
            else:
                return None
        elif sys.platform == "darwin":
            if machine in ("arm64", "aarch64"):
                target = "aarch64-apple-darwin"
            else:
                return None
        else:
            return None
        return NativeAsset(
            filename=f"pythinker-{version}-{target}.tar.gz",
            method=method,
            needs_sudo=False,
        )
    if method is InstallMethod.WINDOWS_EXE:
        return NativeAsset(
            filename=f"PythinkerSetup-{version}.exe",
            method=method,
            needs_sudo=False,
        )
    return None


def _release_asset_url(version: str, filename: str) -> str:
    return f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/{filename}"


def _download_with_sha256(url: str, sha_url: str, dest: Path, *, timeout_s: float = 60.0) -> None:
    """Download ``url`` to ``dest``; verify against the ``.sha256`` sidecar.

    Raises :class:`RuntimeError` on any download or verification failure. The
    sidecar must be the upstream ``shasum`` format (``<hexdigest>  <filename>``).
    """
    import hashlib

    timeout = httpx.Timeout(timeout_s, connect=10.0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        sha_resp = client.get(sha_url)
        sha_resp.raise_for_status()
        expected = sha_resp.text.strip().split()[0].lower()
        if len(expected) != 64 or not all(c in "0123456789abcdef" for c in expected):
            raise RuntimeError(f"Invalid SHA-256 sidecar at {sha_url}: {sha_resp.text!r}")

        with client.stream("GET", url) as r:
            r.raise_for_status()
            hasher = hashlib.sha256()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
                    hasher.update(chunk)
            actual = hasher.hexdigest().lower()
            if actual != expected:
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"SHA-256 mismatch for {url}\n  expected: {expected}\n  actual:   {actual}"
                )


def native_upgrade(method: InstallMethod, version: str, *, dry_run: bool = False) -> int:
    """Download the release asset, verify SHA-256, and run the matching installer.

    Returns the process exit code (0 == success). Raises :class:`RuntimeError`
    if the asset can't be resolved or verification fails — the caller is
    expected to translate that into a CLI error.

    For DEB / RPM the installer needs root; this helper spawns ``sudo`` so the
    user sees a single prompt. For NATIVE_TARBALL it re-runs the short
    ``https://pythinker.com/ai`` curl-bash installer. For WINDOWS_EXE it executes
    the Inno installer with the silent flags documented in the .iss.

    ``version`` is validated as PEP 440 before any shell interpolation —
    callers come from CLI args / PyPI strings, but defense-in-depth guards
    against a future refactor relaxing the constraint.
    """
    import subprocess

    try:
        Version(version)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"Invalid version {version!r} (must be PEP 440)"
        ) from exc

    asset = native_asset_for(method, version)
    if asset is None:
        raise RuntimeError(
            f"No GitHub-Release asset is published for method={method.value} on this host."
        )

    if dry_run:
        url = _release_asset_url(version, asset.filename)
        logger.info("native_upgrade dry-run: would download {} (needs_sudo={})", url, asset.needs_sudo)
        return 0

    # Special-case the native tarball: the installer script already does the
    # download + SHA-256 check itself, so we just shell out to it.
    if method is InstallMethod.NATIVE_TARBALL:
        cmd = [
            "bash",
            "-c",
            f"curl -fsSL {POSIX_INSTALL_URL} | bash -s -- --version {version}",
        ]
        return subprocess.run(cmd, check=False).returncode

    # Download + verify for everything else.
    tmpdir = Path(get_update_dir()) / "downloads" / version
    tmpdir.mkdir(parents=True, exist_ok=True)
    dest = tmpdir / asset.filename
    url = _release_asset_url(version, asset.filename)
    _download_with_sha256(url, url + ".sha256", dest)

    if method is InstallMethod.DEB:
        cmd = ["sudo", "dpkg", "-i", str(dest)]
        rc = subprocess.run(cmd, check=False).returncode
        if rc != 0:
            # Fall back to `apt-get -f install` to fix any dep gap dpkg flagged.
            subprocess.run(["sudo", "apt-get", "-f", "install", "-y"], check=False)
        return rc

    if method is InstallMethod.RPM:
        cmd = ["sudo", "rpm", "-U", str(dest)]
        return subprocess.run(cmd, check=False).returncode

    if method is InstallMethod.WINDOWS_EXE:
        cmd = [str(dest), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        return subprocess.run(cmd, check=False).returncode

    raise RuntimeError(f"native_upgrade is not implemented for {method.value}")


__all__ = [
    "DEFAULT_CACHE_TTL_S",
    "DEFAULT_FAILURE_TTL_S",
    "DEFAULT_TIMEOUT_S",
    "ENV_DISABLE",
    "ENV_NO_AUTO_UPDATE",
    "GITHUB_RELEASES_LATEST",
    "GITHUB_REPO",
    "InstallMethod",
    "NativeAsset",
    "PACKAGE_NAME",
    "PYPI_JSON_URL",
    "UpdateInfo",
    "check_for_update",
    "check_for_update_sync",
    "detect_install_method",
    "fetch_pypi_metadata",
    "format_banner",
    "mark_notified",
    "native_asset_for",
    "native_upgrade",
    "parse_pypi_response",
    "select_latest_version",
    "suggested_target_command",
    "suggested_upgrade_command",
    "target_install_command",
    "upgrade_command",
]
