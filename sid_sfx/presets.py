"""Built-in SFX presets matching the game's existing sound effects.

These mirror the 15 SFX definitions from the C64 game engine's sound_auditor.asm.
"""

from sid_sfx.schema import SfxPatch, Waveform


PRESETS = {
    "fire": SfxPatch(
        name="fire",
        voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x18, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=6,
        pw_hi=0x00, duration_frames=10,
        description="Sawtooth laser zap — sharp attack, quick decay",
    ),
    "explode": SfxPatch(
        name="explode",
        voice=2, waveform=Waveform.NOISE,
        freq_hi=0x08, freq_lo=0x00,
        attack=0, decay=9, sustain=0, release=9,
        pw_hi=0x00, duration_frames=15,
        description="Noise burst explosion — mid-frequency noise with slow decay",
    ),
    "hit": SfxPatch(
        name="hit",
        voice=1, waveform=Waveform.PULSE,
        freq_hi=0x0C, freq_lo=0x00,
        attack=0, decay=4, sustain=0, release=3,
        pw_hi=0x04, duration_frames=8,
        description="Short harsh pulse buzz — player damage",
    ),
    "weakpoint_hit": SfxPatch(
        name="weakpoint_hit",
        voice=1, waveform=Waveform.PULSE,
        freq_hi=0x09, freq_lo=0x00,
        attack=0, decay=7, sustain=2, release=7,
        pw_hi=0x05, duration_frames=12,
        description="Deeper metallic pulse — weakpoint damage with sustain",
    ),
    "enemy_hit": SfxPatch(
        name="enemy_hit",
        voice=1, waveform=Waveform.NOISE,
        freq_hi=0x10, freq_lo=0x00,
        attack=0, decay=2, sustain=0, release=0,
        pw_hi=0x00, duration_frames=6,
        description="Very short noise burst — enemy takes damage",
    ),
    "march": SfxPatch(
        name="march",
        voice=3, waveform=Waveform.TRIANGLE,
        freq_hi=0x06, freq_lo=0x00,
        attack=0, decay=4, sustain=0, release=4,
        pw_hi=0x00, duration_frames=10,
        description="Low triangle thud — marching bass",
    ),
    "kraft_alarm": SfxPatch(
        name="kraft_alarm",
        voice=3, waveform=Waveform.TRIANGLE,
        freq_hi=0x04, freq_lo=0x00,
        attack=0, decay=2, sustain=0, release=8,
        pw_hi=0x00, duration_frames=10,
        description="Rising triangle alarm tone",
    ),
    "game_over": SfxPatch(
        name="game_over",
        voice=1, waveform=Waveform.PULSE,
        freq_hi=0x18, freq_lo=0x00,
        attack=2, decay=2, sustain=10, release=8,
        pw_hi=0x08, duration_frames=45,
        description="Descending pulse tone with long sustain — game over",
    ),
    "death": SfxPatch(
        name="death",
        voice=2, waveform=Waveform.NOISE,
        freq_hi=0x14, freq_lo=0x00,
        attack=0, decay=10, sustain=0, release=12,
        pw_hi=0x00, duration_frames=20,
        description="Noise crash with long decay — player death",
    ),
    "warp": SfxPatch(
        name="warp",
        voice=3, waveform=Waveform.TRIANGLE,
        freq_hi=0x04, freq_lo=0x00,
        attack=2, decay=8, sustain=8, release=8,
        pw_hi=0x00, duration_frames=60,
        description="Slow rising triangle sweep — warp effect",
    ),
    "portal_ping": SfxPatch(
        name="portal_ping",
        voice=1, waveform=Waveform.TRIANGLE,
        freq_hi=0x20, freq_lo=0x00,
        attack=0, decay=2, sustain=0, release=0,
        pw_hi=0x00, duration_frames=5,
        description="Very brief high triangle blip — portal ping",
    ),
    "powerup": SfxPatch(
        name="powerup",
        voice=3, waveform=Waveform.TRIANGLE,
        freq_hi=0x1C, freq_lo=0xD6,
        attack=0, decay=8, sustain=10, release=0,
        pw_hi=0x00, duration_frames=15,
        description="Rising triangle arpeggio — powerup collect",
    ),
    "bounce": SfxPatch(
        name="bounce",
        voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x30, freq_lo=0x00,
        attack=0, decay=0, sustain=0, release=0,
        pw_hi=0x00, duration_frames=3,
        description="Ultra-short high sawtooth blip — bounce",
    ),
    "blaster_bolt": SfxPatch(
        name="blaster_bolt",
        voice=1, waveform=Waveform.SAWTOOTH,
        freq_hi=0x28, freq_lo=0x00,
        attack=0, decay=6, sustain=0, release=4,
        pw_hi=0x00, duration_frames=8,
        sweep_target_hi=0x03, sweep_target_lo=0x00,
        sweep_type="exponential",
        description="Descending sawtooth sweep — blaster bolt 'pew'",
    ),
}
