# PyInstaller spec for coqui-xtts add-on.
# Build with: pyinstaller coqui-xtts-addon.spec --distpath dist/
# Resulting dist/coqui-xtts-addon/ + manifest.json + LICENSE + README.md
# is zipped into coqui-xtts-<version>-<platform>.zip for the catalog.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# TTS pulls a *lot* of optional submodules — collect_submodules walks the
# package and gives us the union, then PyInstaller drops anything not used
# during analysis.
hiddenimports = (
    collect_submodules('TTS')
    + collect_submodules('coqpit')
    + collect_submodules('trainer')
)
datas = (
    collect_data_files('TTS')
    + collect_data_files('trainer')
    + [('manifest.json', '.')]
)

block_cipher = None

a = Analysis(
    ['coqui_xtts_addon.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'jax', 'flax'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='coqui-xtts-addon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='coqui-xtts-addon',
)
