"""Write the Windows version resource (``build/version_info.txt``) for PyInstaller.

    python packaging/make_version_info.py            # version from the package
    python packaging/make_version_info.py 1.2.3      # explicit (release workflow)

The resource is what Explorer shows under プロパティ → 詳細, and it is the only
place the *Japanese* product name appears in the exe itself (the file name stays
ASCII: PechiPechiEnter.exe).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "build" / "version_info.txt"

PUBLISHER = "Hirohisa Kawase"
PRODUCT = "ぺちぺちエンター"
PRODUCT_EN = "PechiPechiEnter"


def package_version() -> str:
    sys.path.insert(0, str(REPO / "src"))
    from enter_router import __version__
    return __version__


def quad(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in version.replace("-", ".").split(".") if p.isdigit()]
    parts += [0] * (4 - len(parts))
    return tuple(parts[:4])  # type: ignore[return-value]


def render(version: str) -> str:
    fv = quad(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={fv},
    prodvers={fv},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041104b0',
        [StringStruct('CompanyName', {PUBLISHER!r}),
         StringStruct('FileDescription', {PRODUCT!r}),
         StringStruct('FileVersion', {'{}.{}.{}.{}'.format(*fv)!r}),
         StringStruct('InternalName', {PRODUCT_EN!r}),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', {PRODUCT_EN + '.exe'!r}),
         StringStruct('ProductName', {PRODUCT!r}),
         StringStruct('ProductVersion', {version!r})])
    ]),
    VarFileInfo([VarStruct('Translation', [1041, 1200])])
  ]
)
"""


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else package_version()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(version), encoding="utf-8")
    print(f"wrote {OUT} (version {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
