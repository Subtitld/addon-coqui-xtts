# PyInstaller spec for coqui-xtts add-on.
# Build with: pyinstaller coqui-xtts-addon.spec --distpath dist/
# Resulting dist/coqui-xtts-addon/ + manifest.json + LICENSE + README.md
# is zipped into coqui-xtts-<version>-<platform>.zip for the catalog.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# TTS pulls a *lot* of optional submodules — collect_submodules walks the
# package and gives us the union, then PyInstaller drops anything not used
# during analysis.
#
# The idiap/coqui-ai-TTS fork inlined some helpers (`coqpit`, `trainer`)
# that were separate packages in the original Coqui distribution; older
# releases still expect them, newer ones don't. Wrap each lookup so a
# missing dep is a no-op rather than a freeze-time failure — the actual
# import chain pulled by the addon code (only `TTS.api` and `TTS.utils`)
# is what matters for runtime correctness.
def _safe_collect(fn, name):
    try:
        return fn(name)
    except Exception:
        return []


hiddenimports = (
    _safe_collect(collect_submodules, 'TTS')
    + _safe_collect(collect_submodules, 'coqpit')
    + _safe_collect(collect_submodules, 'trainer')
    # `TTS.tts.models.xtts` imports torchaudio at module scope. PyInstaller
    # *should* pick that up via static analysis, but the v1.0.3 frozen
    # bundle shipped without it — collect explicitly so we never depend on
    # static-analysis lucky breaks.
    + _safe_collect(collect_submodules, 'torchaudio')
)
datas = (
    _safe_collect(collect_data_files, 'TTS')
    + _safe_collect(collect_data_files, 'trainer')
    + _safe_collect(collect_data_files, 'torchaudio')
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
