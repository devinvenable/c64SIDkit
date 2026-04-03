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


def test_sweep_renders():
    """Sweep should produce valid output."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.SAWTOOTH,
        frequency=0x2800,
        attack=0, decay=6, sustain=0, release=4,
        duration_ms=200.0,
        sweep_target=0x0300,
        sweep_type="exponential",
    )
    assert len(samples) > 0
    assert samples.dtype == np.float32


def test_sweep_bounded():
    """Swept output should be in [-1, 1]."""
    emu = SidVoiceEmulator()
    for wf in [Waveform.SAWTOOTH, Waveform.TRIANGLE, Waveform.PULSE]:
        samples = emu.render(
            waveform=wf,
            frequency=0x2800,
            attack=0, decay=4, sustain=8, release=4,
            pw_hi=0x08,
            duration_ms=200.0,
            sweep_target=0x0300,
            sweep_type="exponential",
        )
        assert np.all(samples >= -1.01)
        assert np.all(samples <= 1.01)


def test_linear_sweep():
    """Linear sweep should also work."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x2000,
        attack=0, decay=6, sustain=0, release=0,
        duration_ms=200.0,
        sweep_target=0x0400,
        sweep_type="linear",
    )
    assert len(samples) > 0


def test_no_sweep_backward_compat():
    """sweep_target=0 should produce same result as no sweep."""
    emu = SidVoiceEmulator()
    s1 = emu.render(
        waveform=Waveform.SAWTOOTH,
        frequency=0x1800,
        attack=0, decay=6, sustain=0, release=6,
        duration_ms=200.0,
    )
    s2 = emu.render(
        waveform=Waveform.SAWTOOTH,
        frequency=0x1800,
        attack=0, decay=6, sustain=0, release=6,
        duration_ms=200.0,
        sweep_target=0,
    )
    np.testing.assert_array_equal(s1, s2)


def test_vibrato_renders():
    """Vibrato should produce valid output."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x27E9,
        attack=6, decay=8, sustain=10, release=8,
        duration_ms=500.0,
        vibrato_rate=15.0,
        vibrato_depth=100,
    )
    assert len(samples) > 0
    assert samples.dtype == np.float32


def test_vibrato_bounded():
    """Vibrato output should be in [-1, 1]."""
    emu = SidVoiceEmulator()
    samples = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x27E9,
        attack=6, decay=8, sustain=10, release=8,
        duration_ms=500.0,
        vibrato_rate=15.0,
        vibrato_depth=100,
    )
    assert np.all(samples >= -1.01)
    assert np.all(samples <= 1.01)


def test_vibrato_modulates_frequency():
    """Vibrato should produce different output than no vibrato."""
    emu = SidVoiceEmulator()
    s_no_vib = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x27E9,
        attack=0, decay=8, sustain=10, release=8,
        duration_ms=200.0,
    )
    s_vib = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x27E9,
        attack=0, decay=8, sustain=10, release=8,
        duration_ms=200.0,
        vibrato_rate=15.0,
        vibrato_depth=100,
    )
    assert not np.array_equal(s_no_vib, s_vib)


def test_no_vibrato_backward_compat():
    """vibrato_rate=0 should produce same result as no vibrato."""
    emu = SidVoiceEmulator()
    s1 = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x1800,
        attack=0, decay=6, sustain=0, release=6,
        duration_ms=200.0,
    )
    s2 = emu.render(
        waveform=Waveform.TRIANGLE,
        frequency=0x1800,
        attack=0, decay=6, sustain=0, release=6,
        duration_ms=200.0,
        vibrato_rate=0.0,
        vibrato_depth=0,
    )
    np.testing.assert_array_equal(s1, s2)
