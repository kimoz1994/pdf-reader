# -*- mode: python ; coding: utf-8 -*-
"""Standalone Windows build for the PDF reader (#118).

Run from the repo root:

    python -m PyInstaller --noconfirm pdf_reader.spec

Output: dist/pdf_reader/pdf_reader.exe
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)  # noqa: F821 - SPECPATH injected by PyInstaller
GUI = ROOT / "pdf_reader" / "gui_app"

# QtPdf ships as a plugin module PyInstaller's static analysis does not
# always trace (it is only imported via PyQt6.QtPdf), and PyMuPDF's
# submodules (including its `fitz` alias) are resolved dynamically.
hiddenimports = collect_submodules("PyQt6.QtPdf") + collect_submodules(
    "pymupdf"
)

# Qt's page renderer lives in a plugins/renderers/ directory PyInstaller's
# PyQt6 hook does not collect by default -> QPdfView paints nothing.
_datas = collect_data_files(
    "PyQt6", includes=["Qt6/plugins/renderers/*", "Qt6/plugins/sqldrivers/*"]
)

# Conda envs keep the sqlite3 C library outside python's DLLs dir, so
# the `_sqlite3.pyd` dependency scan misses it -> ImportError at runtime.
_binaries = []
_sqlite3_dll = Path(sys.prefix) / "Library" / "bin" / "sqlite3.dll"
if _sqlite3_dll.exists():
    _binaries.append((str(_sqlite3_dll), "."))

a = Analysis(
    [str(GUI / "main.py")],
    pathex=[str(GUI)],  # flat imports: services.*, main_window, views.*
    binaries=_binaries,
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdf_reader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app
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
    name="pdf_reader",
)
