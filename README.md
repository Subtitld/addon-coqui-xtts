# Coqui XTTS-v2 add-on for Subtitld

Multilingual neural TTS with **6-second voice cloning** based on
[Coqui XTTS-v2](https://huggingface.co/coqui/XTTS-v2). Heavy: the model is
~1.8 GB, peak RAM around 4-6 GB, CPU inference is several seconds per line.

## Building

```bash
# CPU build (also works for AMD/Intel without CUDA)
pip install coqui-tts==0.24.* pyinstaller torch --extra-index-url https://download.pytorch.org/whl/cpu
pyinstaller coqui-xtts-addon.spec --distpath dist/
cd dist/coqui-xtts-addon
zip -r ../coqui-xtts-1.0.0-linux-x86_64.zip . ../../manifest.json ../../LICENSE ../../README.md
```

For CUDA builds, install the matching `torch` wheel (`+cu121`, `+cu118`, etc.)
and ship a separate zip per CUDA version.

## License gotcha

XTTS-v2 model weights are distributed under the **Coqui Public Model License (CPML)**:
free for non-commercial use, paid commercial license required from Coqui. The
add-on glue itself (this folder's code) is MIT, but redistribution of the
weights in a hosted catalog requires confirming the license terms with users.

The model files are *not* bundled — they're downloaded on first run from
HuggingFace, with a UI confirmation prompt that links to the CPML.

## Voice cloning

The `xtts-clone` voice id treats the per-request `voice_ref_audio` parameter
as the reference: any 6+ second mono WAV of the speaker. Without an explicit
reference, the add-on falls back to the addon-config-level
`voice_ref_audio` (a default reference clip the user picks once).
