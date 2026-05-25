"""Public short installer endpoints mirror the maintained installer scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_posix_short_installer_asset_matches_script():
    assert (ROOT / "webui/public/ai").read_text(encoding="utf-8") == (
        ROOT / "scripts/install-native.sh"
    ).read_text(encoding="utf-8")


def test_windows_short_installer_asset_matches_script():
    assert (ROOT / "webui/public/ai.ps1").read_text(encoding="utf-8") == (
        ROOT / "scripts/install.ps1"
    ).read_text(encoding="utf-8")
