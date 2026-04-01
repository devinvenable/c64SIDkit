"""Render an SfxPatch to a WAV file for preview."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

from sid_sfx.schema import SfxPatch, ATTACK_MS, DECAY_RELEASE_MS
from sid_sfx.sid_emulator import SidVoiceEmulator


def estimate_duration_ms(patch: SfxPatch) -> float:
    """Estimate a reasonable render duration from envelope parameters."""
    attack_ms = ATTACK_MS[patch.attack]
    decay_ms = DECAY_RELEASE_MS[patch.decay]
    release_ms = DECAY_RELEASE_MS[patch.release]
    # Use frame duration as minimum, envelope as guide
    frame_ms = patch.duration_frames * (1000.0 / 60.0)
    envelope_ms = attack_ms + decay_ms + 50.0 + release_ms
    return max(frame_ms, min(envelope_ms, 5000.0))


def render_patch(patch: SfxPatch, sample_rate: int = 44100) -> np.ndarray:
    """Render a patch to float32 audio samples."""
    emu = SidVoiceEmulator(sample_rate=sample_rate)
    duration_ms = estimate_duration_ms(patch)

    attack_ms = ATTACK_MS[patch.attack]
    decay_ms = DECAY_RELEASE_MS[patch.decay]
    gate_off_ms = attack_ms + decay_ms + 50.0

    return emu.render(
        waveform=patch.waveform,
        frequency=patch.frequency,
        attack=patch.attack,
        decay=patch.decay,
        sustain=patch.sustain,
        release=patch.release,
        pw_hi=patch.pw_hi,
        duration_ms=duration_ms,
        gate_off_ms=gate_off_ms,
        sweep_target=patch.sweep_target,
        sweep_type=patch.sweep_type,
    )


def render_patch_to_wav(patch: SfxPatch, path: str | Path, sample_rate: int = 44100):
    """Render a patch and write to a 16-bit mono WAV file."""
    samples = render_patch(patch, sample_rate)

    # Normalize and convert to 16-bit PCM
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.9  # Leave headroom

    pcm = (samples * 32767).astype(np.int16)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
