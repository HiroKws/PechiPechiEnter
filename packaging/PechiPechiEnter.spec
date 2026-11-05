# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — ぺちぺちエンター / PechiPechiEnter (onedir, 2 exes).

Build (from the repository root):

    pyinstaller --noconfirm packaging\\PechiPechiEnter.spec

Produces ``dist/PechiPechiEnter/`` containing:

    PechiPechiEnter.exe      the resident tray app (no console window)
    PechiPechiEnterCmd.exe   the same program with a console, for --once /
                             --version / --dry-run (a windowed exe has nowhere
                             to print, and the CLI surface is frozen)

Deliberate choices:

* **onedir, not onefile** — a resident tool must start instantly; onefile
  unpacks ~30MB to %TEMP% on every launch.
* **assets are placed at ``enter_router/assets``** — ``ui/tray.py`` resolves them
  as ``Path(__file__).resolve().parents[1] / "assets"`` and PyInstaller keeps a
  frozen module's ``__file__`` inside the bundle, so this layout needs no code
  change (verified: the tray icon and the settings window icon both load).
* **no UAC manifest** — the router itself runs as a normal user; only the
  installer elevates (it needs HKLM for the TSF registration).
"""
from pathlib import Path

REPO = Path(SPECPATH).resolve().parent          # .../packaging
SRC = REPO / "src"
ASSETS = SRC / "enter_router" / "assets"
ICON = ASSETS / "enter-router.ico"
VERSION_FILE = REPO / "build" / "version_info.txt"   # written by make_version_info.py

a = Analysis(
    [str(SRC / "enter_router" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(ASSETS), "enter_router/assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here is imported at runtime; dropping them keeps the folder smaller
    # and the file count down (an unsigned binary that gets scanned is nicer when
    # there are fewer of them).
    excludes=["pytest", "_pytest", "doctest", "pydoc_data", "tkinter.test",
              "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

_common = {
    "exclude_binaries": True,
    "icon": str(ICON) if ICON.exists() else None,
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,                     # UPX-packed binaries trip AV heuristics
}
if VERSION_FILE.exists():
    _common["version"] = str(VERSION_FILE)

exe = EXE(pyz, a.scripts, [], name="PechiPechiEnter", console=False, **_common)
exe_cli = EXE(pyz, a.scripts, [], name="PechiPechiEnterCmd", console=True, **_common)

coll = COLLECT(
    exe,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PechiPechiEnter",
)
