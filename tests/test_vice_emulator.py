"""Tests for VICE emulator backend."""

import shutil
import struct

import numpy as np
import pytest

from sid_sfx.schema import SfxPatch, Waveform
from sid_sfx.vice_emulator import (
    _build_prg,
    _compute_freq_table,
    render_patch_vice,
    VOICE_BASE,
)

# Skip all integration tests if VICE is not installed
has_vice = shutil.which("x64sc") is not None or shutil.which("x64") is not None


# --- Unit tests for .prg generation ---

def test_build_prg_has_basic_stub():
    """Generated .prg should start with a valid BASIC stub."""
    patch = SfxPatch(name="test", waveform=Waveform.SAWTOOTH, freq_hi=0x10)
    prg = _build_prg(patch)

    # First two bytes are load address $0801
    load_addr = struct.unpack_from('<H', prg, 0)[0]
    assert load_addr == 0x0801

    # Should contain SYS token (0x9E)
    assert 0x9E in prg[2:15]


def test_build_prg_sets_sid_volume():
    """Generated .prg should set SID volume register ($D418)."""
    patch = SfxPatch(name="test", waveform=Waveform.PULSE, freq_hi=0x10)
    prg = _build_prg(patch)

    # Look for STA $D418 pattern: 8D 18 D4
    data = bytes(prg)
    assert b'\x8d\x18\xd4' in data


def test_build_prg_sets_gate():
    """Generated .prg should set control register with gate bit."""
    patch = SfxPatch(name="test", waveform=Waveform.SAWTOOTH, freq_hi=0x10)
    prg = _build_prg(patch)
    data = bytes(prg)

    # CR byte for sawtooth + gate = 0x21
    # Should see LDA #$21 somewhere: A9 21
    assert bytes([0xA9, 0x21]) in data

    # Voice 1 CR register offset is $D404: 8D 04 D4
    assert b'\x8d\x04\xd4' in data


def test_build_prg_with_filter():
    """Filtered patch should set filter registers."""
    patch = SfxPatch(
        name="test", waveform=Waveform.SAWTOOTH, freq_hi=0x10,
        filter_mode="bandpass", filter_cutoff=0x90, filter_resonance=0xF,
    )
    prg = _build_prg(patch)
    data = bytes(prg)

    # Should set $D417 (res/filt): 8D 17 D4
    assert b'\x8d\x17\xd4' in data
    # Should set $D418 (mode/vol): 8D 18 D4
    assert b'\x8d\x18\xd4' in data


def test_build_prg_with_sweep():
    """Swept patch should include frequency table."""
    patch = SfxPatch(
        name="test", waveform=Waveform.SAWTOOTH,
        freq_hi=0x26, freq_lo=0x18,
        sweep_target_hi=0x04, sweep_target_lo=0xC3,
        sweep_type="exponential",
        attack=0, decay=6, sustain=0, release=5,
    )
    prg = _build_prg(patch)

    # Swept patches use LDA abs,X (opcode 0xBD) for table lookups
    assert 0xBD in prg


def test_build_prg_voice_2():
    """Voice 2 should use offset registers ($D407+)."""
    patch = SfxPatch(name="test", voice=2, waveform=Waveform.PULSE, freq_hi=0x10)
    prg = _build_prg(patch)
    data = bytes(prg)

    # Voice 2 CR register is $D40B: 8D 0B D4
    assert b'\x8d\x0b\xd4' in data


def test_compute_freq_table_no_sweep():
    """Without sweep, all frames should have the same frequency."""
    patch = SfxPatch(name="test", freq_hi=0x10, freq_lo=0x00)
    freqs = _compute_freq_table(patch, total_frames=10, sweep_frames=0)
    assert all(f == patch.frequency for f in freqs)


def test_compute_freq_table_sweep():
    """Sweep should interpolate between start and target frequency."""
    patch = SfxPatch(
        name="test", freq_hi=0x20, freq_lo=0x00,
        sweep_target_hi=0x10, sweep_target_lo=0x00,
        sweep_type="linear",
    )
    freqs = _compute_freq_table(patch, total_frames=20, sweep_frames=10)
    # First frame should be start freq
    assert freqs[0] == patch.frequency
    # Last sweep frame should be near target
    assert abs(freqs[9] - patch.sweep_target) < 2
    # After sweep, should hold at target
    assert freqs[15] == patch.sweep_target


# --- Integration tests (require VICE) ---

@pytest.mark.skipif(not has_vice, reason="VICE not installed")
def test_render_vice_produces_audio():
    """VICE backend should produce non-silent audio."""
    patch = SfxPatch(
        name="test_vice",
        waveform=Waveform.SAWTOOTH,
        freq_hi=0x10, freq_lo=0x00,
        attack=0, decay=4, sustain=0, release=0,
        duration_frames=8,
    )
    audio = render_patch_vice(patch, sample_rate=44100)
    assert len(audio) > 0
    assert audio.dtype == np.float32
    # Should have some non-silent content
    assert np.max(np.abs(audio)) > 0.001


@pytest.mark.skipif(not has_vice, reason="VICE not installed")
def test_render_vice_with_filter():
    """VICE backend should handle filtered patches."""
    patch = SfxPatch(
        name="test_vice_filter",
        waveform=Waveform.SAWTOOTH,
        freq_hi=0x26, freq_lo=0x18,
        attack=0, decay=6, sustain=0, release=5,
        filter_mode="bandpass",
        filter_cutoff=0x90,
        filter_resonance=0xF,
        duration_frames=8,
    )
    audio = render_patch_vice(patch, sample_rate=44100)
    assert len(audio) > 0
    assert np.max(np.abs(audio)) > 0.001


@pytest.mark.skipif(not has_vice, reason="VICE not installed")
def test_render_vice_with_sweep():
    """VICE backend should handle swept patches."""
    patch = SfxPatch(
        name="test_vice_sweep",
        waveform=Waveform.SAWTOOTH,
        freq_hi=0x26, freq_lo=0x18,
        sweep_target_hi=0x04, sweep_target_lo=0xC3,
        sweep_type="exponential",
        attack=0, decay=6, sustain=0, release=5,
        duration_frames=8,
    )
    audio = render_patch_vice(patch, sample_rate=44100)
    assert len(audio) > 0
    assert np.max(np.abs(audio)) > 0.001


@pytest.mark.skipif(not has_vice, reason="VICE not installed")
def test_wav_export_vice_backend():
    """render_patch() should accept emulator='vice'."""
    from sid_sfx.wav_export import render_patch

    patch = SfxPatch(
        name="test_export",
        waveform=Waveform.SAWTOOTH,
        freq_hi=0x10, freq_lo=0x00,
        attack=0, decay=4, sustain=0, release=0,
        duration_frames=8,
    )
    audio = render_patch(patch, emulator="vice")
    assert len(audio) > 0
    assert audio.dtype == np.float32
