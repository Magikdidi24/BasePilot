# -*- mode: python ; coding: utf-8 -*-
# Build: pip install pyinstaller, then
# pyinstaller --noconfirm --clean BasePilot.spec
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('app')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # app/data holds the OCR models (PP-OCRv6, run by ONNX Runtime: its hook brings its DLLs)
    datas=[('templates', 'templates'), ('assets', 'assets'), ('app/data', 'app/data')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)

# Files the bot never loads: OpenCV's video decoder (FFmpeg), Qt's software OpenGL and its
# translations (the UI is in English), Pillow's AVIF codec.
_UNUSED = ('opencv_videoio_ffmpeg', 'opengl32sw.dll', '_avif.')


def _kept(entry):
    dest = entry[0].replace('\\', '/').lower()
    return not (any(part in dest for part in _UNUSED) or dest.startswith('pyside6/translations/'))


a.binaries = [b for b in a.binaries if _kept(b)]
a.datas = [d for d in a.datas if _kept(d)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BasePilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\basepilot_logo.ico'],
)
