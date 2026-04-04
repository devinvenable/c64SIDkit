# SFX Integration Changes for dankarmada

Summary of approved sound replacements from c64audio A/B testing session.
12 replacements, 2 kept original. All patches tested via reSID 8580 preview.

---

## 1. BLASTER FIRE (`play_fire_sfx` — line 8210)

The blaster system uses a weighted random table (`fire_weight_table` at line 10755)
to select from 5 blaster variants in `sfx_blaster_data` (line 10739) and
`sfx_blaster_sweep` (line 10747).

### Kept original
- **Index 0: xwing_blaster** — no change (`blaster_bolt` rejected in A/B test)

### Replace these entries in `sfx_blaster_data` and `sfx_blaster_sweep`:

**Index 1: heavy_repeater** → `heavy_repeater_filtered`
```asm
; sfx_blaster_data index 1 (line 10741)
; OLD: .byte $90, $21, $1F, $BF, $07, $08, $00
; NEW:
  .byte $90, $21, $28, $00, $07, $05, $00  ; heavy_repeater_filtered (saw, 601Hz)
; sfx_blaster_sweep index 1 (line 10749)
; OLD: .byte $03, $2C, $0C, $03
; NEW:
  .byte $04, $00, $0C, $03                 ; sweep target $0400 (60Hz), 12 frames
```

**Index 1 alt: heavy_repeater_octdown** (optional second variant)
```asm
; If adding as new index, data:
  .byte $90, $21, $53, $26, $05, $04, $00  ; heavy_repeater_octdown (saw, 1250Hz)
; Sweep:
  .byte $04, $FD, $0A, $03                 ; target $04FD (75Hz), 10 frames
```

**Index 2: turbolaser** → `turbolaser_filtered`
```asm
; sfx_blaster_data index 2 (line 10742)
; OLD: .byte $90, $21, $34, $CB, $07, $09, $00
; NEW:
  .byte $90, $21, $42, $85, $07, $06, $00  ; turbolaser_filtered (saw, 1000Hz)
; sfx_blaster_sweep index 2 (line 10750)
; OLD: .byte $02, $1C, $12, $03
; NEW:
  .byte $02, $A9, $12, $03                 ; sweep target $02A9 (40Hz), 18 frames
```

**Index 2 alt: turbolaser_octdown** (optional second variant — same registers)
```asm
; Same bytes as turbolaser_filtered (identical export)
  .byte $90, $21, $42, $85, $07, $06, $00
  .byte $02, $A9, $12, $03
```

**Index 3: tie_cannon** → `tie_cannon_filtered`
```asm
; sfx_blaster_data index 3 (line 10743)
; OLD: .byte $B0, $21, $1F, $BF, $06, $08, $00
; NEW:
  .byte $90, $41, $32, $00, $05, $04, $0C  ; tie_cannon_filtered (pulse, 752Hz, PW=$0C)
; sfx_blaster_sweep index 3 (line 10751)
; OLD: .byte $03, $F7, $0A, $03
; NEW:
  .byte $08, $00, $08, $03                 ; sweep target $0800 (120Hz), 8 frames
```

**Index 4: ion_cannon** → `ion_cannon_filtered`
```asm
; sfx_blaster_data index 4 (line 10744)
; OLD: .byte $90, $41, $27, $99, $08, $09, $14
; NEW:
  .byte $90, $41, $31, $E4, $08, $07, $14  ; ion_cannon_filtered (pulse, 750Hz)
; sfx_blaster_sweep index 4 (line 10752)
; OLD: .byte $01, $95, $14, $03
; NEW:
  .byte $01, $FF, $14, $03                 ; sweep target $01FF (30Hz), 20 frames
```

**Index 0: xwing_blaster** → `xwing_blaster_filtered` + `xwing_blaster_octdown`
The original xwing was kept, but the two new variants were also approved.
Options:
- Replace index 0 with `xwing_blaster_filtered` and add `xwing_blaster_octdown` as index 5
- Or adjust `fire_weight_table` to include more variety

`xwing_blaster_filtered`:
```asm
  .byte $90, $21, $30, $00, $06, $05, $00  ; xwing_blaster_filtered (saw, 722Hz)
  .byte $06, $00, $08, $03                 ; sweep target $0600 (90Hz), 8 frames
```

`xwing_blaster_octdown`:
```asm
  .byte $90, $21, $80, $00, $04, $03, $00  ; xwing_blaster_octdown (saw, 1924Hz)
  .byte $09, $FB, $06, $03                 ; sweep target $09FB (150Hz), 6 frames
```

### Suggested new weight table (more variety)
```asm
; OLD: fire_weight_table: .byte 0, 0, 0, 1, 1, 2, 3, 4
; Suggestion with filtered xwing variants mixed in:
fire_weight_table:
  .byte 0, 5, 6, 1, 1, 2, 3, 4
; Where 5=xwing_blaster_filtered, 6=xwing_blaster_octdown
; (requires expanding sfx_blaster_data/sweep to 7 entries)
```

---

## 2. SHIELD ON (`play_shield_on_sfx` — line 8677)

### Replace: `shield_on` → `shield_on_v3`

Voice 3, triangle, 600Hz with 15Hz vibrato — Star Trek force field wobble.

```asm
play_shield_on_sfx:
    jsr sting_cutoff_check
    lda #$10               ; triangle, gate OFF (retrigger)
    sta SIDV3CR

    ; freq: 600Hz (unchanged)
    lda #$E9
    sta SIDV3FR
    sta sweep_freq_lo
    lda #$27
    sta SIDV3FH
    sta sweep_freq_hi

    ; ADSR: A6/D8, S10/R8 (unchanged)
    lda #$68
    sta SIDV3AD
    lda #$A8
    sta SIDV3SR

    ; sweep: no pitch target, 60 frames, vibrato rate=15Hz depth=100 SID units
    lda #$00
    sta sweep_target_lo
    sta sweep_target_hi
    lda #60
    sta sweep_frames
    ; NEW: flags=$A4 — rate index 2 (5fr period ≈ 12Hz), depth index 1 (1/4)
    ; Closest to 15Hz vibrato at depth ~100 within engine constraints
    lda #$A4               ; bits 4-5=2 (rate=5fr), bits 6-7=2 (depth=3/8)
    sta sweep_flags
    lda #3
    sta sweep_active
    jsr init_sfx_sweep
    lda #$11               ; triangle + gate ON
    sta SIDV3CR
    rts
```

---

## 3. POWERUP SUSTAINED DRONES (`play_powerup_sfx` — line 10405)

These are looped sounds — gate stays open while powerup is active.
Key change: **lower sustain (4), minimal attack/decay (1/1)** for quiet background drones.

### Replace: `powerup_shield` → new sustained drone

```asm
play_powerup_shield_sfx:  ; line 10462
    lda #$00
    sta SIDV3CR                 ; gate off (retrigger)
    ; NEW ADSR: A1/D1, S4/R6 — flat quiet entry, no spike
    lda #$11                    ; attack=1, decay=1
    sta SIDV3AD
    lda #$46                    ; sustain=4, release=6
    sta SIDV3SR
    lda #$D6
    sta SIDV3PW
    lda #$04
    sta SIDV3PH
    ; freq: 300Hz ($13F5)
    lda #$F5
    sta SIDV3FR
    lda #$13
    sta SIDV3FH
    lda #$11                    ; triangle + gate on
    sta SIDV3CR
    ; sweep: target $10A1 (250Hz), 40 frames, linear, 4Hz vibrato depth 80
    lda #$F5
    sta sweep_freq_lo
    lda #$13
    sta sweep_freq_hi
    lda #$A1
    sta sweep_target_lo
    lda #$10
    sta sweep_target_hi
    lda #$28                    ; 40 frames
    sta sweep_frames
    lda #$19                    ; vibrato: rate=6fr (≈4Hz), depth=1/8
    sta sweep_flags
    lda #3
    sta sweep_active
    jsr init_sfx_sweep
    rts
```

### Replace: `powerup_speed` → new sustained drone

```asm
play_powerup_speed_sfx:  ; line 10498
    lda #$00
    sta SIDV3CR                 ; gate off (retrigger)
    ; NEW ADSR: A1/D1, S4/R6 — flat quiet entry
    lda #$11                    ; attack=1, decay=1
    sta SIDV3AD
    lda #$46                    ; sustain=4, release=6
    sta SIDV3SR
    lda #$D6
    sta SIDV3PW
    lda #$04
    sta SIDV3PH
    ; freq: 400Hz ($1A9B)
    lda #$9B
    sta SIDV3FR
    lda #$1A
    sta SIDV3FH
    lda #$21                    ; sawtooth + gate on
    sta SIDV3CR
    ; sweep: no pitch target, vibrato only: 10Hz, depth 50
    lda #$9B
    sta sweep_freq_lo
    lda #$1A
    sta sweep_freq_hi
    lda #$00
    sta sweep_target_lo
    sta sweep_target_hi
    lda #$FF                    ; 255 frames (sustained)
    sta sweep_frames
    lda #$39                    ; vibrato: rate=3fr (≈10Hz), depth=1/8
    sta sweep_flags
    lda #3
    sta sweep_active
    jsr init_sfx_sweep
    rts
```

### Kept original: `powerup_spread` — no change

---

## 4. NEW SOUNDS (no existing game equivalent)

These patches were approved but have no current in-game routine to replace.
They need new routines or event hooks:

| Patch | Purpose | 7-byte |
|---|---|---|
| shield_off_v2 | Shield deactivation event | Needs `play_shield_off_sfx` routine |
| shield_off_v3 | Shield deactivation (deeper) | Alternative to v2 |
| spread_fire_v2 | Spread weapon fire sound | Could hook into `play_fire_sfx` when spread active |

---

## Files changed

All source patches with WAV previews are in `/home/devin/src/2026/c64audio/patches/`.
Reference extractions of current game sounds are in `/home/devin/src/2026/c64audio/reference/`.

To regenerate any WAV preview:
```bash
cd /home/devin/src/2026/c64audio
python -m sid_sfx.cli preview patches/<name>.json
```
