"""Tests for asm and WAV export."""

import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

import sid_sfx.wav_export as wav_export
from sid_sfx.schema import SfxPatch, Waveform
from sid_sfx.asm_export import (
    patch_to_bytes, patches_to_asm, patch_to_asm_line, patches_to_c_array,
    patches_to_asm_tables, patch_to_sweep_bytes, EXP_CURVE_LUT, BLASTER_WEIGHTS,
)
from sid_sfx.wav_export import render_patch_to_wav
from sid_sfx.presets import PRESETS


def test_patch_to_asm_line():
    p = SfxPatch(name="fire", voice=1, waveform=Waveform.SAWTOOTH,
                 freq_hi=0x18, freq_lo=0x00, attack=0, decay=6,
                 sustain=0, release=6, pw_hi=0x00)
    line = patch_to_asm_line(p)
    assert ".byte $01, $21, $18, $00, $06, $06, $00" in line
    assert "; fire" in line


def test_patches_to_asm_has_index():
    patches = [PRESETS["fire"], PRESETS["explode"]]
    asm = patches_to_asm(patches)
    assert "SFX_FIRE = 0" in asm
    assert "SFX_EXPLODE = 1" in asm
    assert "sfx_data:" in asm


def test_patches_to_asm_no_index():
    patches = [PRESETS["fire"]]
    asm = patches_to_asm(patches, include_index=False)
    assert "SFX_" not in asm


def test_patches_to_c_array():
    patches = [PRESETS["hit"]]
    c = patches_to_c_array(patches)
    assert "0x01" in c
    assert "hit" in c


def test_wav_export():
    p = PRESETS["fire"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    render_patch_to_wav(p, path)
    # Verify it's a valid WAV
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        assert wf.getnframes() > 0
    Path(path).unlink()


def test_all_presets_export():
    """All presets should produce valid 7-byte data."""
    for name, preset in PRESETS.items():
        b = patch_to_bytes(preset)
        assert len(b) == 7, f"Preset {name} produced {len(b)} bytes"


def test_all_presets_render():
    """All presets should render to WAV without error."""
    for name, preset in PRESETS.items():
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        render_patch_to_wav(preset, path)
        with wave.open(path, "rb") as wf:
            assert wf.getnframes() > 0, f"Preset {name} rendered 0 frames"
        Path(path).unlink()


def test_preset_fire_matches_game():
    """Verify fire preset matches game engine bytes exactly."""
    p = PRESETS["fire"]
    assert p.to_bytes() == bytes([0x01, 0x21, 0x18, 0x00, 0x06, 0x06, 0x00])


def test_preset_explode_matches_game():
    p = PRESETS["explode"]
    assert p.to_bytes() == bytes([0x02, 0x81, 0x08, 0x00, 0x09, 0x09, 0x00])


# --- Separate-table format tests ---

def test_sweep_bytes_no_sweep():
    """Non-swept patch produces zeroed sweep bytes."""
    p = PRESETS["fire"]
    assert not p.has_sweep
    assert patch_to_sweep_bytes(p) == bytes(6)


def test_sweep_bytes_with_sweep():
    """Swept patch produces correct 6-byte sweep entry."""
    p = PRESETS["blaster_bolt"]
    b = patch_to_sweep_bytes(p)
    assert len(b) == 6
    assert b[0] == 0x03  # target_hi
    assert b[1] == 0x00  # target_lo
    assert b[2] == p.duration_frames  # frames (sweep_frames=0 falls back to duration_frames)
    assert b[3] == 0x03  # flags: enable(1) | exponential(2)


def test_sweep_bytes_linear():
    """Linear sweep sets only enable bit."""
    p = SfxPatch(
        name="test_linear", voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x20, freq_lo=0x00, attack=0, decay=4, sustain=0, release=0,
        sweep_target_hi=0x10, sweep_target_lo=0x00, sweep_type="linear",
        sweep_frames=12,
    )
    b = patch_to_sweep_bytes(p)
    assert b[3] == 0x01  # enable only, no exponential bit
    assert b[2] == 12  # uses explicit sweep_frames


def test_patches_to_asm_tables_has_both_tables():
    """Separate-table export produces sfx_data and sfx_sweep labels."""
    patches = [PRESETS["fire"], PRESETS["blaster_bolt"]]
    asm = patches_to_asm_tables(patches)
    assert "sfx_data:" in asm
    assert "sfx_sweep:" in asm
    assert "SFX_FIRE = 0" in asm
    assert "SFX_BLASTER_BOLT = 1" in asm


def test_patches_to_asm_tables_includes_curve_lut():
    """Separate-table export includes exponential curve LUT."""
    asm = patches_to_asm_tables([PRESETS["fire"]])
    assert "exp_curve_lut:" in asm


def test_patches_to_asm_tables_includes_blaster_weights():
    """Separate-table export includes blaster weight table."""
    asm = patches_to_asm_tables([PRESETS["fire"]])
    assert "blaster_weights:" in asm


def test_patches_to_asm_tables_optional_sections():
    """Can disable curve LUT and blaster weights."""
    asm = patches_to_asm_tables(
        [PRESETS["fire"]],
        include_curve_lut=False,
        include_blaster_weights=False,
    )
    assert "exp_curve_lut:" not in asm
    assert "blaster_weights:" not in asm


def test_exp_curve_lut_properties():
    """Exponential curve LUT is 16 bytes, monotonically increasing, 0-255."""
    assert len(EXP_CURVE_LUT) == 16
    assert EXP_CURVE_LUT[0] == 0
    assert EXP_CURVE_LUT[-1] == 255
    for i in range(1, 16):
        assert EXP_CURVE_LUT[i] > EXP_CURVE_LUT[i - 1]


def test_blaster_weights_distribution():
    """Blaster weight table has correct distribution."""
    assert len(BLASTER_WEIGHTS) == 8
    assert BLASTER_WEIGHTS.count(0) == 3  # xwing 3/8
    assert BLASTER_WEIGHTS.count(1) == 2  # heavy_repeater 2/8
    assert BLASTER_WEIGHTS.count(2) == 1  # turbolaser 1/8
    assert BLASTER_WEIGHTS.count(3) == 1  # tie_cannon 1/8
    assert BLASTER_WEIGHTS.count(4) == 1  # ion_cannon 1/8


def test_backward_compat_flat_export():
    """Original flat export still works unchanged."""
    patches = list(PRESETS.values())
    asm = patches_to_asm(patches)
    assert "sfx_data:" in asm
    assert "sfx_sweep:" not in asm  # flat format has no sweep table
    for p in patches:
        assert p.name in asm


def test_round_trip_sweep():
    """Exported sweep bytes can be parsed back to match original params."""
    for name, p in PRESETS.items():
        b = patch_to_sweep_bytes(p)
        if p.has_sweep:
            assert b[0] == p.sweep_target_hi
            assert b[1] == p.sweep_target_lo
            expected_frames = p.sweep_frames if p.sweep_frames > 0 else p.duration_frames
            assert b[2] == expected_frames
            assert b[3] & 0x01 == 1  # enable bit
            is_exp = (b[3] & 0x02) >> 1
            assert (is_exp == 1) == (p.sweep_type == "exponential")
        else:
            if not p.has_vibrato:
                assert b == bytes(6)
            else:
                assert b[0:3] == bytes(3)  # no sweep target/frames
                assert b[3] & 0x04 == 0x04  # vibrato bit set


def test_vibrato_sweep_bytes():
    """Vibrato-only patch produces correct 6-byte entry with vibrato flag."""
    p = PRESETS["shield_on_v3"]
    b = patch_to_sweep_bytes(p)
    assert len(b) == 6
    assert b[3] & 0x04 == 0x04  # vibrato enable bit
    assert b[3] & 0x01 == 0x00  # no sweep enable bit
    assert b[4] > 0  # vib_rate encoded
    assert b[5] > 0  # vib_depth encoded


def test_vibrato_preset_renders():
    """shield_on_v3 preset renders without error."""
    from sid_sfx.wav_export import render_patch
    import numpy as np
    p = PRESETS["shield_on_v3"]
    samples = render_patch(p)
    assert len(samples) > 0
    assert samples.dtype == np.float32


def test_render_patch_defaults_to_resid_8580(monkeypatch):
    patch = PRESETS["fire"]
    captured = {}

    def fake_resid(p, sample_rate=0, chip_model=""):
        captured["patch"] = p
        captured["sample_rate"] = sample_rate
        captured["chip_model"] = chip_model
        return np.zeros(8, dtype=np.float32)

    monkeypatch.setattr(wav_export, "render_patch_resid", fake_resid)
    samples = wav_export.render_patch(patch)

    assert samples.dtype == np.float32
    assert captured["patch"] is patch
    assert captured["sample_rate"] == 44100
    assert captured["chip_model"] == "8580"


def test_render_patch_supports_svf_fallback(monkeypatch):
    patch = PRESETS["fire"]
    captured = {}

    class FakeEmulator:
        def __init__(self, sample_rate):
            captured["sample_rate"] = sample_rate

        def render(self, **kwargs):
            captured["kwargs"] = kwargs
            return np.zeros(8, dtype=np.float32)

    monkeypatch.setattr(wav_export, "SidVoiceEmulator", FakeEmulator)
    samples = wav_export.render_patch(patch, emulator="svf", sample_rate=22050)

    assert samples.dtype == np.float32
    assert captured["sample_rate"] == 22050
    assert captured["kwargs"]["frequency"] == patch.frequency


def test_render_patch_rejects_unknown_emulator():
    with pytest.raises(ValueError, match="Unsupported emulator"):
        wav_export.render_patch(PRESETS["fire"], emulator="unknown")
