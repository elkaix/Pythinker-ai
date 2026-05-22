# PyInstaller spec for Pythinker
#
# Builds a single-executable bundle of the `pythinker` CLI that runs without a
# Python installation. Invoked from the release-native.yml workflow on four
# runners (Linux x86_64, Linux aarch64, macOS arm64, Windows x86_64).
#
# To run manually:
#     pyinstaller packaging/pyinstaller/pythinker.spec --clean --noconfirm
#
# Output: dist/pythinker/  (folder bundle; one-folder mode is faster cold-start
# than one-file and tarballs roughly the same size after gzip).

# ruff: noqa
# mypy: ignore-errors

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent
PKG = ROOT / "pythinker"


def _pkg_data():
    """Collect every non-Python file shipped inside the `pythinker` package.

    PyInstaller does not honour `tool.hatch.build.include` — it walks the
    filesystem. Without these entries the frozen binary boots, then dies the
    first time the agent loop tries to read a skill or template.
    """
    bundled = []
    patterns = [
        "**/*.md",
        "**/*.yaml",
        "**/*.yml",
        "**/*.json",
        "**/*.txt",
        "**/*.sh",
        "**/*.j2",
        "**/*.html",
        "**/*.css",
        "**/*.js",
        "**/*.svg",
        "**/*.png",
        "**/*.ico",
        "**/*.woff",
        "**/*.woff2",
    ]
    for pat in patterns:
        for src in PKG.glob(pat):
            if "__pycache__" in src.parts:
                continue
            rel_dir = src.parent.relative_to(ROOT).as_posix()
            bundled.append((str(src), rel_dir))
    return bundled


def _bridge_files():
    """Force-include the WhatsApp Node bridge so users can run it without an
    sdist checkout. Mirrors the `force-include` block in pyproject.toml."""
    bridge_root = ROOT / "bridge"
    out = []
    if not bridge_root.exists():
        return out
    out.append((str(bridge_root / "package.json"), "pythinker/bridge"))
    out.append((str(bridge_root / "package-lock.json"), "pythinker/bridge"))
    out.append((str(bridge_root / "tsconfig.json"), "pythinker/bridge"))
    src_dir = bridge_root / "src"
    if src_dir.exists():
        for src in src_dir.rglob("*"):
            if src.is_file() and "node_modules" not in src.parts:
                rel = src.parent.relative_to(bridge_root).as_posix()
                out.append((str(src), f"pythinker/bridge/{rel}"))
    return out


def _web_dist():
    """Bundle the built WebUI assets if they exist on disk at spec time."""
    dist_dir = PKG / "web" / "dist"
    out = []
    if not dist_dir.exists():
        return out
    for src in dist_dir.rglob("*"):
        if src.is_file():
            rel = src.parent.relative_to(ROOT).as_posix()
            out.append((str(src), rel))
    return out


datas = []
datas += _pkg_data()
datas += _bridge_files()
datas += _web_dist()
datas += collect_data_files("pythinker", include_py_files=False)

hiddenimports = []
hiddenimports += collect_submodules("pythinker")
# Provider/channel modules are lazy-imported by registry name → PyInstaller
# can't see them statically. Sweeping the package keeps the bundle complete.
hiddenimports += [
    "tomllib",
    "encodings.idna",
]

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "test",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pythinker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="pythinker",
)
