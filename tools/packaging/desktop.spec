# -*- mode: python ; coding: utf-8 -*-
"""tools.packaging.desktop.spec

PyInstaller specification for ClearMark Windows Desktop Host.
Builds a windowed onedir distribution containing bundled Python runtime,
standard libraries, ClearMark cleaning engine, System Tray, and web UI.

Target: ClearMark v2.2.0-rc1
"""

import sys
from pathlib import Path

block_cipher = None
project_root = Path.cwd()
scripts_dir = project_root / "service" / "scripts"

datas = [
    (str(project_root / "service" / "web"), "service/web"),
    (str(project_root / "service" / "scripts"), "service/scripts"),
    (str(project_root / "assets" / "ClearMark.ico"), "assets"),
    (str(project_root / "assets" / "ClearMark.png"), "assets"),
]

# Discover all modules in service/scripts
hiddenimports = [
    "service",
    "service.desktop",
    "service.desktop.desktop_host",
    "service.desktop.system_tray",
    "service.scripts",
    "service.scripts.server",
    "service.scripts.cli",
    "ctypes",
    "ctypes.wintypes",
    "http.server",
    "urllib.request",
    "urllib.error",
    "urllib.parse",
    "secrets",
    "json",
    "logging",
    "socket",
    "threading",
    "time",
    "webbrowser",
]

for p in scripts_dir.glob("*.py"):
    mod = p.stem
    hiddenimports.append(mod)
    hiddenimports.append(f"service.scripts.{mod}")

for sub in ["docx", "pptx", "xlsx"]:
    sub_dir = scripts_dir / sub
    if sub_dir.is_dir():
        hiddenimports.append(sub)
        hiddenimports.append(f"service.scripts.{sub}")
        for p in sub_dir.glob("*.py"):
            mod = p.stem
            hiddenimports.append(f"{sub}.{mod}")
            hiddenimports.append(f"service.scripts.{sub}.{mod}")

a = Analysis(
    [str(project_root / "service" / "desktop" / "desktop_host.py")],
    pathex=[
        str(project_root),
        str(scripts_dir),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClearMark",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "ClearMark.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClearMark",
)
