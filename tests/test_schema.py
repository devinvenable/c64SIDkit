"""Tests for SFX patch schema."""

import json
import tempfile
from pathlib import Path

from sid_sfx.schema import (
    SfxPatch, Waveform,
    hz_to_sid_freq, sid_freq_to_hz, note_to_hz, note_to_sid_freq,
)


def test_patch_defaults():
    p = SfxPatch(name="test")
    assert p.voice == 1
    assert p.waveform == Waveform.PULSE
    assert p.cr_byte == 0x41


def test_to_bytes_length():
    p = SfxPatch(name="test")
    assert len(p.to_bytes()) == 7


def test_to_bytes_format():
    """Verify byte order: voice, CR, FH, FL, AD, SR, PW_H."""
    p = SfxPatch(
        name="fire", voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x18, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=6,
        pw_hi=0x00,
    )
    b = p.to_bytes()
    assert b == bytes([0x01, 0x21, 0x18, 0x00, 0x06, 0x06, 0x00])


def test_roundtrip_bytes():
    original = SfxPatch(
        name="test", voice=2, waveform=Waveform.NOISE,
        freq_hi=0x08, freq_lo=0x42,
        attack=3, decay=9, sustain=5, release=7,
        pw_hi=0x10,
    )
    data = original.to_bytes()
    restored = SfxPatch.from_bytes(data, name="test")
    assert restored.voice == original.voice
    assert restored.waveform == original.waveform
    assert restored.freq_hi == original.freq_hi
    assert restored.freq_lo == original.freq_lo
    assert restored.attack == original.attack
    assert restored.decay == original.decay
    assert restored.sustain == original.sustain
    assert restored.release == original.release
    assert restored.pw_hi == original.pw_hi


def test_roundtrip_json():
    p = SfxPatch(name="laser", voice=1, waveform=Waveform.SAWTOOTH,
                 freq_hi=0x20, freq_lo=0x00, attack=0, decay=4,
                 sustain=0, release=2, pw_hi=0x00)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    p.save_json(path)
    loaded = SfxPatch.load_json(path)
    assert loaded.name == p.name
    assert loaded.to_bytes() == p.to_bytes()
    Path(path).unlink()


def test_ad_sr_bytes():
    p = SfxPatch(name="t", attack=0xA, decay=0x5, sustain=0xF, release=0x3)
    assert p.ad_byte == 0xA5
    assert p.sr_byte == 0xF3


def test_frequency_property():
    p = SfxPatch(name="t", freq_hi=0x18, freq_lo=0xAB)
    assert p.frequency == 0x18AB
    p.frequency = 0x2000
    assert p.freq_hi == 0x20
    assert p.freq_lo == 0x00


def test_hz_to_sid_freq_a4():
    """A4 = 440 Hz should give ~7217 for PAL clock."""
    sid = hz_to_sid_freq(440.0)
    hz_back = sid_freq_to_hz(sid)
    assert abs(hz_back - 440.0) < 0.1


def test_note_to_hz():
    assert abs(note_to_hz(69) - 440.0) < 0.01  # A4
    assert abs(note_to_hz(60) - 261.63) < 0.1   # C4


def test_validation():
    import pytest
    with pytest.raises(ValueError):
        SfxPatch(name="bad", voice=4)
    with pytest.raises(ValueError):
        SfxPatch(name="bad", attack=16)
    with pytest.raises(ValueError):
        SfxPatch(name="bad", freq_hi=256)


def test_sweep_defaults_no_sweep():
    """Patch without sweep fields should have no sweep."""
    p = SfxPatch(name="test")
    assert not p.has_sweep
    assert p.sweep_target == 0


def test_sweep_target_property():
    p = SfxPatch(name="t", sweep_target_hi=0x03, sweep_target_lo=0x00)
    assert p.sweep_target == 0x0300
    assert p.has_sweep
    p.sweep_target = 0x2800
    assert p.sweep_target_hi == 0x28
    assert p.sweep_target_lo == 0x00


def test_sweep_to_bytes_unchanged():
    """Sweep fields must NOT change the 7-byte hardware export."""
    p = SfxPatch(
        name="sweep_test", voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x28, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=4,
        pw_hi=0x00,
        sweep_target_hi=0x03, sweep_target_lo=0x00,
        sweep_type="exponential",
    )
    b = p.to_bytes()
    assert len(b) == 7
    # Same as without sweep
    p_no_sweep = SfxPatch(
        name="no_sweep", voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x28, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=4,
        pw_hi=0x00,
    )
    assert b == p_no_sweep.to_bytes()


def test_sweep_roundtrip_json():
    """Sweep fields should survive save_json/load_json round-trip."""
    p = SfxPatch(
        name="bolt", voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x28, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=4,
        pw_hi=0x00,
        sweep_target_hi=0x03, sweep_target_lo=0x00,
        sweep_type="exponential",
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    p.save_json(path)
    loaded = SfxPatch.load_json(path)
    assert loaded.sweep_target_hi == 0x03
    assert loaded.sweep_target_lo == 0x00
    assert loaded.sweep_type == "exponential"
    assert loaded.has_sweep
    Path(path).unlink()


def test_sweep_validation():
    import pytest
    with pytest.raises(ValueError):
        SfxPatch(name="bad", sweep_target_hi=256)
    with pytest.raises(ValueError):
        SfxPatch(name="bad", sweep_type="cubic")
