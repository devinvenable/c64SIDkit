"""Tests for asm and WAV export."""

import tempfile
import wave
from pathlib import Path

from sid_sfx.schema import SfxPatch, Waveform
from sid_sfx.asm_export import patch_to_bytes, patches_to_asm, patch_to_asm_line, patches_to_c_array
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
