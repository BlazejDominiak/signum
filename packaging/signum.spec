# -*- mode: python ; coding: utf-8 -*-
"""Konfiguracja PyInstaller dla Signum (onedir, bez konsoli).

Budowanie (z katalogu głównego repozytorium):
    .venv\\Scripts\\pyinstaller packaging\\signum.spec --noconfirm
"""

import re
from pathlib import Path

ROOT = Path(SPECPATH).parent  # katalog główny repozytorium
version_source = (ROOT / "src" / "signum" / "__init__.py").read_text(encoding="utf-8")
version_match = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', version_source, re.M)
if version_match is None:
    raise ValueError("Nie znaleziono trzyczęściowej wersji Signum")
app_version = ".".join(version_match.groups())
version_tuple = tuple(map(int, version_match.groups())) + (0,)
version_file = ROOT / "build" / "signum-version-info.txt"
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Signum contributors'),
        StringStruct('FileDescription', 'Signum — document signature detection'),
        StringStruct('FileVersion', '{app_version}'),
        StringStruct('InternalName', 'Signum'),
        StringStruct('LegalCopyright', 'Copyright (c) 2026 Signum contributors'),
        StringStruct('OriginalFilename', 'Signum.exe'),
        StringStruct('ProductName', 'Signum'),
        StringStruct('ProductVersion', '{app_version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""",
    encoding="utf-8",
)

a = Analysis(
    [str(ROOT / "src" / "signum" / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "src/signum/core/classification_profiles.json"), "signum/core"),
        (str(ROOT / "src/signum/ai/runtime_probe.py"), "signum/ai"),
        (str(ROOT / "src" / "signum" / "ai" / "vjev_bootstrap.py"), "signum/ai"),
        (str(ROOT / "src" / "signum" / "ai" / "jevk5_text_worker.py"), "signum/ai"),
        (str(ROOT / "src" / "signum" / "ui" / "resources" / "signum.ico"), "signum/ui/resources"),
        (str(ROOT / "src" / "signum" / "ui" / "resources" / "signum.png"), "signum/ui/resources"),
    ],
    hiddenimports=[
        # Backend keyring dla Windows ładowany dynamicznie przez entry-points.
        "keyring.backends.Windows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nieużywane, ciężkie moduły Qt — mniejsza paczka.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Signum",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "src" / "signum" / "ui" / "resources" / "signum.ico"),
    version=str(version_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Signum",
)
