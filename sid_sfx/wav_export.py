"""Render an SfxPatch to a WAV file for preview."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from sid_sfx.schema import SfxPatch, ATTACK_MS, DECAY_RELEASE_MS
from sid_sfx.resid_emulator import render_patch_resid
from sid_sfx.sid_emulator import SidVoiceEmulator


def estimate_duration_ms(patch: SfxPatch) -> float:
    """Estimate a reasonable render duration from envelope parameters."""
    attack_ms = ATTACK_MS[patch.attack]
    decay_ms = DECAY_RELEASE_MS[patch.decay]
    release_ms = DECAY_RELEASE_MS[patch.release]
    # Use frame duration as minimum, envelope as guide
    frame_ms = patch.duration_frames * (1000.0 / 50.0)  # C64 PAL: 50fps
    envelope_ms = attack_ms + decay_ms + 50.0 + release_ms
    return max(frame_ms, min(envelope_ms, 5000.0))


def render_patch(
    patch: SfxPatch,
    sample_rate: int = 44100,
    emulator: str = "resid",
    chip_model: str = "8580",
) -> np.ndarray:
    """Render a patch to float32 audio samples."""
    if emulator == "vice":
        from sid_sfx.vice_emulator import render_patch_vice
        return render_patch_vice(patch, sample_rate=sample_rate, chip_model=chip_model)
    if emulator == "resid":
        try:
            return render_patch_resid(patch, sample_rate=sample_rate, chip_model=chip_model)
        except RuntimeError:
            # Keep preview/WAV export functional even when pyresidfp is unavailable.
            emulator = "svf"
    if emulator != "svf":
        raise ValueError(f"Unsupported emulator {emulator!r}; expected 'resid', 'svf', or 'vice'")

    emu = SidVoiceEmulator(sample_rate=sample_rate)

    is_loop = getattr(patch, "loop", False)
    if is_loop:
        loop_seconds = getattr(patch, "loop_preview_seconds", 5.0)
        duration_ms = loop_seconds * 1000.0
        gate_off_ms = duration_ms  # gate stays open
    else:
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
        vibrato_rate=patch.vibrato_rate,
        vibrato_depth=patch.vibrato_depth,
        filter_mode=patch.filter_mode,
        filter_cutoff=patch.filter_cutoff,
        filter_resonance=patch.filter_resonance,
        filter_cutoff_sweep=patch.filter_cutoff_sweep,
    )


def render_patch_to_wav(
    patch: SfxPatch,
    path: str | Path,
    sample_rate: int = 44100,
    emulator: str = "resid",
    chip_model: str = "8580",
):
    """Render a patch and write to a 16-bit mono WAV file."""
    samples = render_patch(
        patch,
        sample_rate=sample_rate,
        emulator=emulator,
        chip_model=chip_model,
    )

    # Normalize and convert to 16-bit PCM
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.9  # Leave headroom

    # Prepend a few ms of silence so reSID transients don't start at sample 0,
    # then apply fade-in/out to prevent click/pop artifacts.
    pre_silence = int(0.003 * sample_rate)  # 3ms lead-in
    samples = np.concatenate([np.zeros(pre_silence, dtype=samples.dtype), samples])

    fade_samples = min(int(0.005 * sample_rate), len(samples) // 4)  # 5ms or 1/4 length
    if fade_samples > 0:
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        samples[:fade_samples] *= fade_in
        samples[-fade_samples:] *= fade_out

    pcm = (samples * 32767).astype(np.int16)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
