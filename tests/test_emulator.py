"""Tests for SID voice emulator."""

import numpy as np

from sid_sfx.schema import SfxPatch, Waveform
from sid_sfx.sid_emulator import SidVoiceEmulator


def test_render_produces_samples():
    emu = SidVoiceEmulator(sample_rate=44100)
    samples = emu.render(
        waveform=Waveform.SAWTOOTH,
        frequency=0x1800,
        attack=0, decay=6, sustain=0, release=6,
        duration_ms=200.0,
    )
    assert len(samples) > 0
    assert samples.dtype == np.float32


def test_render_bounded():
    """Output should be in [-1, 1]."""
    emu = SidVoiceEmulator()
    for wf in Waveform:
        samples = emu.render(
            waveform=wf,
            frequency=0x1000,
            attack=0, decay=4, sustain=8, release=4,
            pw_hi=0x08,
            duration_ms=300.0,
        )
        assert np.all(samples >= -1.01)
        assert np.all(samples <= 1.01)


def test_envelope_attack_peak():
    """With nonzero attack, samples should ramp up."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.PULSE,
        frequency=0x1000,
        attack=4, decay=4, sustain=15, release=4,
        pw_hi=0x08,
        duration_ms=500.0,
    )
    # Early samples should be quieter than mid samples
    early = np.abs(samples[:100]).mean()
    mid = np.abs(samples[2000:3000]).mean()
    assert mid > early


def test_noise_waveform():
    """Noise should produce varied output."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.NOISE,
        frequency=0x1000,
        attack=0, decay=8, sustain=0, release=0,
        duration_ms=200.0,
    )
    # Should have some variance (not silence)
    assert np.std(samples[:2000]) > 0.01


def test_zero_frequency():
    """Very low frequency should not crash."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x0001,
        attack=0, decay=4, sustain=0, release=0,
        duration_ms=100.0,
    )
    assert len(samples) > 0
