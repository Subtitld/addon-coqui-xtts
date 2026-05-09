"""Subtitld add-on entry point for Coqui XTTS-v2.

This is the heavyweight reference TTS add-on. The XTTS-v2 model is ~1.8 GB
and supports zero-shot voice cloning from a 6-second reference clip — the
add-on advertises that as a `voice_clone:true` capability in the manifest
and exposes it via a special `xtts-clone` voice id.

Differs from the Piper add-on in three ways:

  - **Slow startup**: model load is 5-30 s on CPU. We honor the longer
    `startup_timeout_sec=120` from the manifest.
  - **Per-request voice ref**: clones expect a `voice_ref_audio` param
    pointing at a short clip; the host writes a per-speaker reference
    file and references it in each `tts.synthesize` request.
  - **Cancellation actually matters**: a 60-word sentence on CPU can
    take 30 s. We don't preempt mid-batch, but we'll skip queued
    requests when we see a `cancel`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import wave
from pathlib import Path

log = logging.getLogger('coqui-xtts')
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format='[coqui-xtts] %(levelname)s %(message)s')

PROTOCOL = 1
ADDON_ID = 'coqui-xtts'
VERSION = '1.0.3'


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()


def write_frame(frame: dict) -> None:
    line = json.dumps(frame, ensure_ascii=False)
    with _write_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def emit_progress(rid, value, message=''):
    write_frame({'id': rid, 'type': 'progress',
                 'data': {'value': max(0.0, min(1.0, float(value))), 'message': message}})


def emit_error(rid, code, message, retryable=False):
    write_frame({'id': rid, 'type': 'error',
                 'data': {'code': code, 'message': message, 'retryable': retryable}})


def emit_result(rid, data):
    write_frame({'id': rid, 'type': 'result', 'data': data})


# ---------------------------------------------------------------------------
# XTTS state — loaded lazily on first request
# ---------------------------------------------------------------------------
_xtts_lock = threading.Lock()
_xtts_model = None
_pending_cancel: set[str] = set()
_pending_cancel_lock = threading.Lock()


def _models_dir() -> Path:
    addon_dir = Path(__file__).resolve().parent
    env_override = os.environ.get('XTTS_ADDON_MODELS_DIR')
    if env_override:
        return Path(os.path.expandvars(os.path.expanduser(env_override)))
    return addon_dir / 'models'


def _load_xtts(device: str = 'cpu'):
    """Load the XTTS-v2 model from `models/xtts_v2/`. Heavy — caller should
    emit a progress frame before invoking."""
    global _xtts_model
    with _xtts_lock:
        if _xtts_model is not None:
            return _xtts_model

        try:
            from TTS.api import TTS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f'coqui-tts python package not available: {exc}') from exc

        # The lib expects a registered model name; we hardcode XTTS-v2.
        os.environ['COQUI_TOS_AGREED'] = '1'  # accept license inside the bundle
        models_dir = _models_dir() / 'xtts_v2'
        if models_dir.is_dir():
            # Local checkpoint path layout — TTS.tts.utils accepts this.
            tts = TTS(model_path=str(models_dir),
                      config_path=str(models_dir / 'config.json'),
                      progress_bar=False).to(device)
        else:
            tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2',
                      progress_bar=False).to(device)
        _xtts_model = tts
        return tts


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------
def handle_tts_synthesize(rid: str, params: dict, default_device: str, default_speaker_wav: str | None) -> None:
    text = params.get('text')
    voice_id = params.get('voice')
    output_path = params.get('output_path')
    language = (params.get('language') or 'en')[:2]
    if not text or not voice_id or not output_path:
        emit_error(rid, 'bad_params', 'text, voice, and output_path are all required')
        return

    with _pending_cancel_lock:
        if rid in _pending_cancel:
            _pending_cancel.discard(rid)
            emit_error(rid, 'cancelled', 'cancelled before synthesis started')
            return

    speaker_wav = params.get('voice_ref_audio') or default_speaker_wav
    use_clone = (voice_id == 'xtts-clone') or speaker_wav

    if voice_id == 'xtts-clone' and not speaker_wav:
        emit_error(rid, 'bad_params',
                   'xtts-clone voice requires `voice_ref_audio` (path to 6+s reference clip)')
        return

    emit_progress(rid, 0.05, 'Loading XTTS model (first call may take a while)...')
    try:
        tts = _load_xtts(default_device)
    except Exception as exc:
        log.exception('xtts load failed')
        emit_error(rid, 'internal', f'failed to load XTTS: {exc}')
        return

    emit_progress(rid, 0.4, 'Synthesizing...')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        kwargs = {'text': text, 'language': language, 'file_path': output_path}
        if use_clone and speaker_wav:
            kwargs['speaker_wav'] = speaker_wav
        else:
            # Fallback to a built-in speaker name for non-clone voices.
            kwargs['speaker'] = voice_id.replace('xtts-', '')
        tts.tts_to_file(**kwargs)
    except Exception as exc:
        log.exception('xtts synth failed')
        emit_error(rid, 'internal', f'synthesize failed: {exc}')
        return

    duration = sample_rate = channels = 0
    try:
        with wave.open(output_path, 'rb') as ro:
            sample_rate = ro.getframerate()
            channels = ro.getnchannels()
            duration = ro.getnframes() / float(sample_rate or 1)
    except Exception:
        pass

    emit_progress(rid, 0.99, 'Finalizing...')
    emit_result(rid, {
        'path': output_path,
        'duration_sec': duration,
        'sample_rate': sample_rate,
        'channels': channels,
    })


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    # Pull voice/language inventory from manifest.
    manifest_path = Path(__file__).resolve().parent / 'manifest.json'
    voices: list[dict] = []
    languages: list[str] = []
    config_defaults: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            voices = manifest.get('voices') or []
            languages = manifest.get('languages') or []
            config_defaults = {f.get('key'): f.get('default')
                               for f in (manifest.get('config_schema') or {}).get('fields', [])
                               if f.get('default') is not None}
        except Exception:
            log.exception('manifest parse failed')

    # User overrides come in via env vars set by the host (the host reads
    # config from CONFIG['addons']['options']['coqui-xtts']).
    default_device = os.environ.get('XTTS_DEVICE') or config_defaults.get('device', 'cpu')
    default_speaker_wav = os.environ.get('XTTS_VOICE_REF_AUDIO') or None

    write_frame({
        'type': 'hello',
        'protocol': PROTOCOL,
        'addon': ADDON_ID,
        'version': VERSION,
        'capabilities': [
            {'task': 'tts.synthesize', 'languages': languages, 'voices': voices,
             'voice_clone': True},
        ],
    })

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            frame = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        ftype = frame.get('type')
        rid = frame.get('id', '')

        if ftype == 'shutdown':
            log.info('shutdown received; exiting')
            return 0
        if ftype == 'cancel':
            target = (frame.get('data') or {}).get('target') or frame.get('target')
            if target:
                with _pending_cancel_lock:
                    _pending_cancel.add(target)
            continue
        if ftype == 'tts.synthesize':
            threading.Thread(
                target=handle_tts_synthesize,
                args=(rid, frame.get('params') or {}, default_device, default_speaker_wav),
                daemon=True,
            ).start()
            continue

        emit_error(rid, 'bad_params', f'unknown request type: {ftype!r}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
