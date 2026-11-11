# -*- mode: python ; coding: utf-8 -*-
# Build: pip install pyinstaller pefile, stage tesseract_bundle/ (see README), then
# pyinstaller --noconfirm --clean BasePilot.spec
import os

import pefile
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('app')

TESSERACT = 'tesseract_bundle'


def tesseract_datas(root=TESSERACT):
    '''tesseract.exe, the DLLs it loads (followed through their imports) and the English
    model: what pytesseract runs. The install also carries training tools, their libraries
    (ICU, pango, cairo...) and other models, ~120 MB the bot never uses.'''
    present = {f.lower(): f for f in os.listdir(root) if f.lower().endswith('.dll')}
    needed = set()
    todo = ['tesseract.exe']
    while todo:
        name = todo.pop()
        pe = pefile.PE(os.path.join(root, present.get(name.lower(), name)), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
            dll = entry.dll.decode('ascii', 'replace').lower()
            if dll in present and dll not in needed:
                needed.add(dll)
                todo.append(dll)
        pe.close()
    datas = [(os.path.join(root, f), 'tesseract') for f in ['tesseract.exe'] + sorted(present[d] for d in needed)]
    tessdata = os.path.join(root, 'tessdata')
    datas.append((os.path.join(tessdata, 'eng.traineddata'), os.path.join('tesseract', 'tessdata')))
    for sub in ('configs', 'tessconfigs'):
        if os.path.isdir(os.path.join(tessdata, sub)):
            datas.append((os.path.join(tessdata, sub), os.path.join('tesseract', 'tessdata', sub)))
    return datas


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('assets', 'assets'), ('app/data', 'app/data')] + tesseract_datas(),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)

# Files the bot never loads: OpenCV's video decoder (FFmpeg), Qt's software OpenGL and its
# translations (the UI is in English), Pillow's AVIF codec; and the top-level copies of
# Tesseract's DLLs that PyInstaller adds as dependencies of the bundle's exe (tesseract.exe
# loads them from its own folder).
_UNUSED = ('opencv_videoio_ffmpeg', 'opengl32sw.dll', '_avif.')
_BUNDLE = os.path.abspath(TESSERACT).lower()


def _kept(entry):
    (dest, src) = (entry[0].replace('\\', '/').lower(), os.path.abspath(entry[1]).lower())
    if any(part in dest for part in _UNUSED) or dest.startswith('pyside6/translations/'):
        return False
    return not (src.startswith(_BUNDLE) and not dest.startswith('tesseract/'))


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
