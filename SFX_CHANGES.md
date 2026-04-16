# SFX Integration — Canonical Reference

**Source of truth**: The JSON patches in `patches/` and the `game-export` command.
Never hand-copy bytes. Always regenerate from:

```bash
python -m sid_sfx.cli game-export \
  patches/heavy_repeater_filtered.json \
  patches/turbolaser_filtered.json \
  patches/tie_cannon_filtered.json \
  patches/ion_cannon_filtered.json \
  patches/xwing_blaster_filtered.json \
  patches/xwing_blaster_octdown.json \
  patches/staging/heavy_repeater_octdown.json \
  patches/staging/ion_cannon_octdown.json \
  patches/staging/turbolaser_octdown.json
```

This outputs the exact `sfx_blaster_data`, `sfx_blaster_sweep`, and `fire_weight_table`
in game format (filter_cutoff as byte 0, 4-byte sweep entries). Paste directly into
`dankarmada.asm` replacing the existing tables.

---

## Integrated Sounds (12 replacements)

### Blaster variants (voice 1, play_fire_sfx)

| Index | Patch | Freq | Waveform | Notes |
|-------|-------|------|----------|-------|
| 0 | xwing_blaster (original) | 573Hz | Sawtooth | Kept from A/B test |
| 1 | heavy_repeater_filtered | 477Hz | Sawtooth | Matches original range |
| 2 | turbolaser_filtered | 794Hz | Sawtooth | Matches original range |
| 3 | tie_cannon_filtered | 477Hz | Pulse | PW=$0C |
| 4 | ion_cannon_filtered | 596Hz | Pulse | PW=$14 |
| 5 | xwing_blaster_filtered | 573Hz | Sawtooth | Filtered variant |
| 6 | xwing_blaster_octdown | 287Hz | Sawtooth | Half original freq |
| 7 | heavy_repeater_octdown | 239Hz | Sawtooth | Half heavy_repeater freq |
| 8 | ion_cannon_octdown | 298Hz | Pulse | Half ion_cannon freq, PW=$14 |
| 9 | turbolaser_octdown | 397Hz | Sawtooth | Half turbolaser freq |

All blasters go through game band-pass filter (res=$F, cutoff=$90, line 8303-8309).
Preview tool auto-applies this filter on voice 1 patches.

### Powerup drones (voice 3, looped)

| Patch | Freq | Waveform | ADSR | Notes |
|-------|------|----------|------|-------|
| powerup_shield | 300Hz | Triangle | A1/D1/S4/R6 | Sweep to 250Hz, 4Hz vibrato |
| powerup_speed | 400Hz | Sawtooth | A1/D1/S4/R6 | 10Hz vibrato, no sweep |

Low sustain (4), flat attack — quiet background drones.
`powerup_spread` kept original (rejected in A/B test).

### Shield on (voice 3)

| Patch | Freq | Waveform | ADSR | Notes |
|-------|------|----------|------|-------|
| shield_on_v3 | 600Hz | Triangle | A6/D8/S10/R8 | 15Hz vibrato, 60 frames |

---

## Approved But Not Yet Integrated

These passed A/B testing but have no game routine assigned:

| Patch | Purpose | Integration Path | Notes |
|-------|---------|------------------|-------|
| shield_off_v2 | Shield deactivation | Hook into `play_shield_off_sfx` routine (voice 3) | Triangle waveform, 35→8 Hz exponential sweep, 18 frames |
| shield_off_v3 | Shield deactivation (deeper) | Alternative to v2, hook into `play_shield_off_sfx` | Triangle waveform, 20→3 Hz exponential sweep, 24 frames |
| spread_fire_v2 | Spread weapon fire | Hook into `play_fire_sfx` when spread weapon active (voice 3) | Pulse waveform, 8 Hz, 6 frames, rapid machine-gun character |

## Game-Event Patches (Canon K59)

These game-event patches are approved but need JSON patches created and integration paths defined:

| Patch | Purpose | Integration Path | Status |
|-------|---------|------------------|--------|
| heavy_repeater | Blaster variant | Add to game-export command as additional blaster index | Needs JSON patch |
| spread_shot | Spread weapon fire | Hook into play_fire_sfx when spread active | Needs JSON patch |
| boss_intro | Boss introduction | Hook into boss_intro routine | Needs JSON patch |
| boss_defeat | Boss defeated | Hook into boss_defeat routine | Needs JSON patch |
| level_clear | Level completed | Hook into level_clear routine | Needs JSON patch |
| game_over | Game over | Hook into game_over routine | Needs JSON patch |

---

## Important: Preview vs Game Accuracy

The preview tool now auto-applies the game's band-pass filter (res=$F, cutoff=$90) to
all voice 1 patches. This ensures what you hear in preview matches gameplay.

```bash
# Normal preview (with game filter):
python -m sid_sfx.cli preview patches/heavy_repeater_filtered.json

# Raw preview (no game filter):
python -m sid_sfx.cli preview patches/heavy_repeater_filtered.json --no-game-filter
```
