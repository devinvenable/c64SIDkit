"""reSID-based SID emulator for accurate WAV preview with analog filter.

Uses pyresidfp (C++ reSID-fp bindings) for cycle-accurate SID emulation
including the analog filter model. Replaces the simple SVF approximation.
"""

from __future__ import annotations

import numpy as np
from datetime import timedelta

try:
    from pyresidfp.sound_interface_device import SoundInterfaceDevice, Voice
    from pyresidfp._pyresidfp import ChipModel
except ModuleNotFoundError:  # pragma: no cover - exercised by integration environment
    SoundInterfaceDevice = None
    Voice = None
    ChipModel = None

from sid_sfx.schema import SfxPatch, ATTACK_MS, DECAY_RELEASE_MS


# Map voice number to pyresidfp Voice enum
VOICE_MAP = {1: Voice.ONE, 2: Voice.TWO, 3: Voice.THREE} if Voice else {}

# Map voice number to register write helpers
VOICE_REGS = {
    1: {"freq_lo": 0x00, "freq_hi": 0x01, "pw_lo": 0x02, "pw_hi": 0x03,
        "cr": 0x04, "ad": 0x05, "sr": 0x06},
    2: {"freq_lo": 0x07, "freq_hi": 0x08, "pw_lo": 0x09, "pw_hi": 0x0A,
        "cr": 0x0B, "ad": 0x0C, "sr": 0x0D},
    3: {"freq_lo": 0x0E, "freq_hi": 0x0F, "pw_lo": 0x10, "pw_hi": 0x11,
        "cr": 0x12, "ad": 0x13, "sr": 0x14},
}


def render_patch_resid(
    patch: SfxPatch,
    sample_rate: int = 44100,
    chip_model: str = "8580",
) -> np.ndarray:
    """Render an SfxPatch using reSID-fp for accurate analog filter emulation.

    Args:
        patch: The SFX patch to render.
        sample_rate: Output sample rate.
        chip_model: "6581" or "8580".

    Returns:
        float32 numpy array of audio samples [-1, 1].
    """
    if SoundInterfaceDevice is None or ChipModel is None:
        raise RuntimeError("reSID backend unavailable: install pyresidfp to use emulator='resid'")

    model = ChipModel.MOS6581 if chip_model == "6581" else ChipModel.MOS8580
    sid = SoundInterfaceDevice(
        model=model,
        clock_frequency=SoundInterfaceDevice.PAL_CLOCK_FREQUENCY,
        sampling_frequency=float(sample_rate),
    )

    v = patch.voice
    voice = VOICE_MAP[v]

    # Set frequency
    sid.oscillator(voice, patch.frequency)

    # Set pulse width (12-bit: pw_hi is top 4 bits)
    sid.pulse_width(voice, patch.pw_hi << 4)

    # Set ADSR
    sid.attack_decay(voice, patch.ad_byte)
    sid.sustain_release(voice, patch.sr_byte)

    # Set filter if enabled
    filter_mode = getattr(patch, "filter_mode", "off")
    filter_cutoff = int(getattr(patch, "filter_cutoff", 0x90))
    filter_resonance = int(getattr(patch, "filter_resonance", 0xF))
    filter_cutoff_sweep = int(getattr(patch, "filter_cutoff_sweep", 0))
    has_filter = filter_mode != "off"
    if has_filter:
        # Filter cutoff: 11-bit value. Map our 8-bit cutoff to 11-bit.
        cutoff_11 = max(0, min(2047, filter_cutoff << 3))
        sid.filter_cutoff(cutoff_11)

        # Resonance (top nibble) + filter routing (bottom nibble)
        # Route the active voice through filter
        voice_filter_bit = 1 << (v - 1)  # voice 1=bit0, 2=bit1, 3=bit2
        res_filt = ((filter_resonance & 0x0F) << 4) | voice_filter_bit
        sid.write_register(0x17, res_filt)  # $D417 Res/Filt

        # Mode/volume: filter mode in top nibble, max volume in bottom
        mode_bits = {"lowpass": 0x10, "bandpass": 0x20, "highpass": 0x40}
        mode_vol = mode_bits.get(filter_mode, 0x10) | 0x0F
        sid.write_register(0x18, mode_vol)  # $D418 Mode/Vol
    else:
        # No filter, just max volume
        sid.write_register(0x18, 0x0F)  # $D418 Mode/Vol

    # Gate ON (waveform + gate bit)
    sid.control(voice, patch.cr_byte)

    # Calculate timing
    attack_ms = ATTACK_MS[patch.attack]
    decay_ms = DECAY_RELEASE_MS[patch.decay]
    release_ms = DECAY_RELEASE_MS[patch.release]
    frame_ms = patch.duration_frames * (1000.0 / 60.0)

    is_loop = getattr(patch, "loop", False)
    if is_loop:
        # Looped: gate stays open for the full preview duration, no release
        loop_seconds = getattr(patch, "loop_preview_seconds", 5.0)
        total_ms = loop_seconds * 1000.0
        gate_off_ms = total_ms  # gate never turns off during render
    else:
        gate_off_ms = attack_ms + decay_ms + 50.0
        total_ms = max(frame_ms, gate_off_ms + release_ms)
        total_ms = min(total_ms, 5000.0)

    # Render in per-frame chunks for sweep support
    frame_duration_ms = 1000.0 / 60.0  # ~16.67ms per frame
    n_frames = int(total_ms / frame_duration_ms) + 1
    gate_off_frame = int(gate_off_ms / frame_duration_ms)
    sweep_duration_frames = max(1, int(getattr(patch, "sweep_frames", 0) or patch.duration_frames))

    # Optional vibrato support (if vibrato fields exist in newer schemas).
    # If absent, defaults to zero and has no effect.
    vibrato_rate_hz = float(getattr(patch, "vibrato_rate_hz", getattr(patch, "vibrato_rate", 0.0)) or 0.0)
    vibrato_depth_cents = float(
        getattr(patch, "vibrato_depth_cents", getattr(patch, "vibrato_depth", 0.0)) or 0.0
    )
    vibrato_delay_frames = max(0, int(getattr(patch, "vibrato_delay_frames", 0) or 0))

    all_samples = []

    for frame in range(n_frames):
        current_ms = frame * frame_duration_ms

        # Handle pitch sweep
        has_sweep = bool(getattr(patch, "has_sweep", False))
        if has_sweep and frame < sweep_duration_frames:
            frac = frame / max(1, sweep_duration_frames - 1)
            start_freq = patch.frequency
            end_freq = int(getattr(patch, "sweep_target", 0))
            sweep_type = str(getattr(patch, "sweep_type", "exponential"))
            if sweep_type == "exponential" and start_freq > 0 and end_freq > 0:
                freq = int(start_freq * ((end_freq / start_freq) ** frac))
            else:
                freq = int(start_freq + (end_freq - start_freq) * frac)
            if (
                vibrato_rate_hz > 0.0
                and vibrato_depth_cents != 0.0
                and frame >= vibrato_delay_frames
            ):
                phase = 2.0 * np.pi * vibrato_rate_hz * (current_ms / 1000.0)
                freq = int(freq * (2.0 ** ((vibrato_depth_cents * np.sin(phase)) / 1200.0)))
            freq = max(0, min(0xFFFF, freq))
            sid.oscillator(voice, freq)
        elif (
            vibrato_rate_hz > 0.0
            and vibrato_depth_cents != 0.0
            and frame >= vibrato_delay_frames
        ):
            phase = 2.0 * np.pi * vibrato_rate_hz * (current_ms / 1000.0)
            freq = int(patch.frequency * (2.0 ** ((vibrato_depth_cents * np.sin(phase)) / 1200.0)))
            freq = max(0, min(0xFFFF, freq))
            sid.oscillator(voice, freq)

        # Handle filter cutoff sweep
        if has_filter and filter_cutoff_sweep > 0 and frame < patch.duration_frames:
            frac = frame / max(1, patch.duration_frames - 1)
            start_cut = filter_cutoff
            end_cut = filter_cutoff_sweep
            cut = int(start_cut + (end_cut - start_cut) * frac)
            sid.filter_cutoff(max(0, min(2047, cut << 3)))

        # Gate off at the right time
        if frame == gate_off_frame:
            sid.control(voice, patch.waveform.value)  # waveform without gate

        # Clock one frame
        samples = sid.clock(timedelta(milliseconds=frame_duration_ms))
        all_samples.extend(samples)

    # Convert to float32 [-1, 1]
    audio = np.array(all_samples, dtype=np.float32) / 32768.0
    return audio
