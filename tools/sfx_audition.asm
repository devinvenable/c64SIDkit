; =============================================================================
; SFX Audition — Interactive C64 SID sound effect player
; Assemble: acme -f cbm -o tools/sfx_audition.prg tools/sfx_audition.asm
; =============================================================================

; --- C64 hardware addresses ---
SID_BASE    = $D400
SID_V1_FREQ_LO  = $D400
SID_V1_FREQ_HI  = $D401
SID_V1_PW_LO    = $D402
SID_V1_PW_HI    = $D403
SID_V1_CR        = $D404
SID_V1_AD        = $D405
SID_V1_SR        = $D406

SID_V2_FREQ_LO  = $D407
SID_V2_FREQ_HI  = $D408
SID_V2_PW_LO    = $D409
SID_V2_PW_HI    = $D40A
SID_V2_CR        = $D40B
SID_V2_AD        = $D40C
SID_V2_SR        = $D40D

SID_V3_FREQ_LO  = $D40E
SID_V3_FREQ_HI  = $D40F
SID_V3_PW_LO    = $D410
SID_V3_PW_HI    = $D411
SID_V3_CR        = $D412
SID_V3_AD        = $D413
SID_V3_SR        = $D414

SID_FC_LO       = $D415
SID_FC_HI       = $D416
SID_RES_FILT    = $D417
SID_MODE_VOL    = $D418

VIC_RASTER   = $D012
VIC_CTRL1    = $D011
VIC_IRQ_EN   = $D01A
CIA1_ICR     = $DC0D
IRQ_STATUS   = $D019
IRQ_VECTOR   = $0314

SCREEN_BASE  = $0400
COLOR_BASE   = $D800
BORDER_COLOR = $D020
BG_COLOR     = $D021

KERNAL_SCNKEY = $FF9F   ; scan keyboard
KERNAL_GETIN  = $FFE4   ; get key from buffer

NUM_SFX      = 24
VISIBLE_ROWS = 19       ; rows available for list (rows 3-21)
LIST_START_ROW = 3
SFX_DATA_SIZE = 7
SFX_SWEEP_SIZE = 6

; Waveform display codes
WAV_TRI   = $10
WAV_SAW   = $20
WAV_PULSE = $40
WAV_NOISE = $80

; --- Zero page variables ---
zp_temp       = $FB
zp_temp2      = $FC
zp_ptr_lo     = $FD
zp_ptr_hi     = $FE

; =============================================================================
; BASIC stub: 10 SYS 2064
; =============================================================================
        * = $0801
        !word +, 10
        !byte $9E
        !text "2064", 0
+       !word 0

; =============================================================================
; Main entry point at $0810
; =============================================================================
        * = $0810

init:
        sei

        ; Clear SID
        ldx #$18
-       lda #$00
        sta SID_BASE,x
        dex
        bpl -

        ; Default: volume 15, no filter
        lda #$0F
        sta SID_MODE_VOL

        ; Clear voice state
        ldx #2
-       lda #$00
        sta voice_active,x
        sta voice_frames,x
        sta voice_sfx_idx,x
        sta voice_sweep_pos,x
        sta voice_vib_phase,x
        dex
        bpl -

        ; Set up raster IRQ
        lda #$7F
        sta CIA1_ICR        ; disable CIA1 IRQs
        lda CIA1_ICR        ; ack pending
        lda #$01
        sta VIC_IRQ_EN      ; enable raster IRQ
        lda #$00
        sta VIC_RASTER      ; raster line 0
        lda VIC_CTRL1
        and #$7F            ; clear bit 8 of raster
        sta VIC_CTRL1
        lda #<irq_handler
        sta IRQ_VECTOR
        lda #>irq_handler
        sta IRQ_VECTOR+1

        ; Initialize cursor/scroll
        lda #$00
        sta cursor_pos
        sta scroll_offset

        ; Setup screen
        lda #$00            ; black
        sta BORDER_COLOR
        sta BG_COLOR

        jsr draw_screen

        cli

; =============================================================================
; Main loop — scan keyboard
; =============================================================================
main_loop:
        jsr KERNAL_GETIN
        beq main_loop       ; no key

        cmp #$91            ; cursor up
        beq key_up
        cmp #$11            ; cursor down
        beq key_down
        cmp #$0D            ; RETURN
        beq key_play
        cmp #$20            ; SPACE
        beq key_play
        cmp #$51            ; Q
        beq key_quit
        cmp #$71            ; q (lowercase)
        beq key_quit
        jmp main_loop

key_up:
        lda cursor_pos
        beq main_loop       ; already at top
        dec cursor_pos
        ; Adjust scroll if cursor went above visible area
        lda cursor_pos
        cmp scroll_offset
        bcs +
        dec scroll_offset
+       jsr draw_list
        jmp main_loop

key_down:
        lda cursor_pos
        cmp #NUM_SFX-1
        beq main_loop       ; already at bottom
        inc cursor_pos
        ; Adjust scroll if cursor went below visible area
        lda cursor_pos
        sec
        sbc scroll_offset
        cmp #VISIBLE_ROWS
        bcc +
        inc scroll_offset
+       jsr draw_list
        jmp main_loop

key_play:
        lda cursor_pos
        jsr play_sfx
        jmp main_loop

key_quit:
        sei
        ; Restore CIA IRQ
        lda #$81
        sta CIA1_ICR
        lda #$00
        sta VIC_IRQ_EN
        ; Silence SID
        ldx #$18
-       lda #$00
        sta SID_BASE,x
        dex
        bpl -
        ; Restore default IRQ vector
        lda #$31
        sta IRQ_VECTOR
        lda #$EA
        sta IRQ_VECTOR+1
        cli
        rts

; =============================================================================
; Draw full screen
; =============================================================================
draw_screen:
        ; Clear screen
        ldx #$00
        lda #$20            ; space
-       sta SCREEN_BASE,x
        sta SCREEN_BASE+$100,x
        sta SCREEN_BASE+$200,x
        sta SCREEN_BASE+$2E8,x
        dex
        bne -

        ; Set all colors to light blue
        ldx #$00
        lda #$0E
-       sta COLOR_BASE,x
        sta COLOR_BASE+$100,x
        sta COLOR_BASE+$200,x
        sta COLOR_BASE+$2E8,x
        dex
        bne -

        ; Draw title (row 0)
        ldx #$00
-       lda title_text,x
        beq +
        sta SCREEN_BASE+2,x
        inx
        bne -
+
        ; Set title color to white
        ldx #$00
-       lda title_text,x
        beq +
        lda #$01            ; white
        sta COLOR_BASE+2,x
        inx
        bne -
+

        ; Draw separator (row 1)
        ldx #$00
        lda #$40            ; horizontal line PETSCII
-       sta SCREEN_BASE+40,x
        lda #$0B            ; dark grey
        sta COLOR_BASE+40,x
        inx
        cpx #40
        bne -

        ; Draw separator (row 22)
        ldx #$00
        lda #$40
-       sta SCREEN_BASE+880,x
        lda #$0B
        sta COLOR_BASE+880,x
        inx
        cpx #40
        bne -

        ; Draw footer (row 23)
        ldx #$00
-       lda footer_text,x
        beq +
        sta SCREEN_BASE+920,x
        lda #$05            ; green
        sta COLOR_BASE+920,x
        inx
        bne -
+

        ; Draw status line (row 2) — column headers
        ldx #$00
-       lda header_text,x
        beq +
        sta SCREEN_BASE+80+2,x
        lda #$0F            ; light grey
        sta COLOR_BASE+80+2,x
        inx
        bne -
+

        jsr draw_list
        rts

; =============================================================================
; Draw the SFX list (scrollable)
; =============================================================================
draw_list:
        lda #$00
        sta zp_temp         ; row counter

.row_loop:
        ; Calculate which SFX index this row represents
        lda zp_temp
        clc
        adc scroll_offset
        cmp #NUM_SFX
        bcc .row_in_range
        jmp .clear_row       ; past end of list, clear row
.row_in_range:
        sta zp_temp2        ; sfx index for this row

        ; Calculate screen position: (LIST_START_ROW + row) * 40
        lda zp_temp
        clc
        adc #LIST_START_ROW
        jsr calc_row_addr   ; result in zp_ptr

        ; Clear this row first
        ldy #39
        lda #$20
-       sta (zp_ptr_lo),y
        dey
        bpl -

        ; Check if this is the selected row
        lda zp_temp2
        cmp cursor_pos
        bne .not_selected

        ; Draw cursor marker ">" at column 0
        ldy #$00
        lda #$3E            ; ">"
        sta (zp_ptr_lo),y

        ; Set row to reverse (highlight) via color
        ldy #$00
        lda zp_temp
        clc
        adc #LIST_START_ROW
        jsr calc_color_addr
        ldy #39
        lda #$01            ; white for selected
-       sta (zp_ptr_lo),y
        dey
        bpl -
        jmp .draw_name

.not_selected:
        ; Normal color
        lda zp_temp
        clc
        adc #LIST_START_ROW
        jsr calc_color_addr
        ldy #39
        lda #$0E            ; light blue
-       sta (zp_ptr_lo),y
        dey
        bpl -

.draw_name:
        ; Get screen address again
        lda zp_temp
        clc
        adc #LIST_START_ROW
        jsr calc_row_addr

        ; Draw SFX name starting at column 2
        ; Look up name pointer: sfx_name_ptrs[zp_temp2]
        lda zp_temp2
        asl                 ; *2 for word index
        tax
        lda sfx_name_ptrs,x
        sta $02             ; temp pointer
        lda sfx_name_ptrs+1,x
        sta $03

        ldy #$02            ; start at screen column 2
.name_loop:
        sty $04             ; save screen column
        ; Read char from name string
        ldy #$00
        lda ($02),y
        beq .name_done
        ; Store at screen position
        ldy $04
        sta (zp_ptr_lo),y
        ; Advance source pointer
        inc $02
        bne +
        inc $03
+       ; Advance screen column
        iny
        cpy #20             ; max column (18 chars from col 2)
        bcc .name_loop

.name_done:
        ; Draw voice info at column 21
        ; Look up sfx_data for this preset
        lda zp_temp2
        ; Multiply by 7
        sta $04
        asl                 ; *2
        asl                 ; *4
        asl                 ; *8... no, need *7
        ; Use: idx*8 - idx = idx*7
        lda zp_temp2
        asl
        asl
        asl                 ; *8
        sec
        sbc zp_temp2        ; *7
        tax

        ; Voice number
        lda sfx_data,x
        clc
        adc #$30            ; ASCII '0' + voice
        ldy #22
        sta (zp_ptr_lo),y
        lda #$56            ; 'V'
        ldy #21
        sta (zp_ptr_lo),y

        ; Waveform name at column 24
        lda sfx_data+1,x    ; CR byte
        and #$F0            ; waveform bits
        ldy #24
        cmp #WAV_TRI
        bne +
        lda #$14            ; 'T'
        sta (zp_ptr_lo),y
        iny
        lda #$12            ; 'R'
        sta (zp_ptr_lo),y
        iny
        lda #$09            ; 'I'
        sta (zp_ptr_lo),y
        jmp .draw_freq
+       cmp #WAV_SAW
        bne +
        lda #$13            ; 'S'
        sta (zp_ptr_lo),y
        iny
        lda #$01            ; 'A'
        sta (zp_ptr_lo),y
        iny
        lda #$17            ; 'W'
        sta (zp_ptr_lo),y
        jmp .draw_freq
+       cmp #WAV_PULSE
        bne +
        lda #$10            ; 'P'
        sta (zp_ptr_lo),y
        iny
        lda #$15            ; 'U'
        sta (zp_ptr_lo),y
        iny
        lda #$0C            ; 'L'
        sta (zp_ptr_lo),y
        jmp .draw_freq
+       ; NOISE
        lda #$0E            ; 'N'
        sta (zp_ptr_lo),y
        iny
        lda #$13            ; 'S'
        sta (zp_ptr_lo),y
        iny
        lda #$05            ; 'E'
        sta (zp_ptr_lo),y

.draw_freq:
        ; Draw frequency as hex at column 29: $XXYY
        ; sfx_data+2,x = freq_hi, sfx_data+3,x = freq_lo
        ; x still points to sfx_data base for this entry
        stx $04             ; save data offset
        lda #$24            ; '$'
        ldy #29
        sta (zp_ptr_lo),y

        ldx $04
        lda sfx_data+2,x    ; freq_hi
        lsr
        lsr
        lsr
        lsr
        jsr hex_digit
        ldy #30
        sta (zp_ptr_lo),y

        ldx $04
        lda sfx_data+2,x
        and #$0F
        jsr hex_digit
        ldy #31
        sta (zp_ptr_lo),y

        ldx $04
        lda sfx_data+3,x    ; freq_lo
        lsr
        lsr
        lsr
        lsr
        jsr hex_digit
        ldy #32
        sta (zp_ptr_lo),y

        ldx $04
        lda sfx_data+3,x
        and #$0F
        jsr hex_digit
        ldy #33
        sta (zp_ptr_lo),y

        ; Check for sweep/vibrato indicators at column 35
        lda zp_temp2
        ; Multiply by 6
        sta $05
        asl                 ; *2
        clc
        adc $05             ; *3
        asl                 ; *6
        tax
        lda sfx_sweep+3,x   ; flags byte
        beq .next_row
        ; Show modulation indicator
        and #$01            ; sweep?
        beq .check_vib
        lda #$13            ; 'S' for sweep
        ldy #35
        sta (zp_ptr_lo),y
.check_vib:
        ldx $05
        txa
        asl
        clc
        adc $05
        asl
        tax
        lda sfx_sweep+3,x
        and #$04            ; vibrato?
        beq .next_row
        lda #$16            ; 'V' for vibrato
        ldy #36
        sta (zp_ptr_lo),y

        jmp .next_row

.clear_row:
        ; Clear this row
        lda zp_temp
        clc
        adc #LIST_START_ROW
        jsr calc_row_addr
        ldy #39
        lda #$20
-       sta (zp_ptr_lo),y
        dey
        bpl -

.next_row:
        inc zp_temp
        lda zp_temp
        cmp #VISIBLE_ROWS
        bcc .row_loop_jmp
        rts

.row_loop_jmp:
        jmp .row_loop

; Convert nibble in A to PETSCII hex digit screen code
hex_digit:
        cmp #$0A
        bcc +
        ; A-F
        sec
        sbc #$09            ; A=1, B=2, etc. (PETSCII screen codes)
        rts
+       ; 0-9
        clc
        adc #$30            ; '0'=48
        rts

; Calculate screen row address: row in A -> address in zp_ptr
calc_row_addr:
        ; row * 40 = row * 32 + row * 8
        tax
        lda row_addr_lo,x
        sta zp_ptr_lo
        lda row_addr_hi,x
        sta zp_ptr_hi
        rts

; Calculate color RAM address for row: row in A -> address in zp_ptr
calc_color_addr:
        tax
        lda row_addr_lo,x
        sta zp_ptr_lo
        lda row_addr_hi,x
        clc
        adc #>(COLOR_BASE - SCREEN_BASE)
        sta zp_ptr_hi
        rts

; =============================================================================
; Play SFX — index in A
; =============================================================================
play_sfx:
        sta $06             ; save sfx index

        ; Stop all active voices and clear state for deterministic retrigger
        jsr clear_all_voices

        ; Look up 7-byte data: sfx_data + index * 7
        tax
        ; Compute index * 7
        asl                 ; *2
        asl                 ; *4
        asl                 ; *8 oops, *8-idx = *7
        ; A = idx*8, need idx*7
        lda $06
        asl
        asl
        asl
        sec
        sbc $06
        tax                 ; X = offset into sfx_data

        ; Byte 0: voice (1-3)
        lda sfx_data,x
        sta $07             ; voice number
        ; Byte 1: CR
        lda sfx_data+1,x
        sta $08
        ; Byte 2: freq_hi
        lda sfx_data+2,x
        sta $09
        ; Byte 3: freq_lo
        lda sfx_data+3,x
        sta $0A
        ; Byte 4: AD
        lda sfx_data+4,x
        sta $0B
        ; Byte 5: SR
        lda sfx_data+5,x
        sta $0C
        ; Byte 6: pw_hi
        lda sfx_data+6,x
        sta $0D

        ; Apply filter state for this SFX before gating on voices
        jsr apply_filter_for_sfx

        ; Play primary voice from sfx_data
        jsr play_loaded_voice

        ; Optional layered voice from sfx_layer_data (CR=0 => no layer)
        ldy $06
        tya
        asl
        asl
        asl                 ; *8
        sec
        sbc $06             ; *7
        tay
        lda sfx_layer_data+1,y
        beq .done
        lda sfx_layer_data,y
        sta $07
        lda sfx_layer_data+1,y
        sta $08
        lda sfx_layer_data+2,y
        sta $09
        lda sfx_layer_data+3,y
        sta $0A
        lda sfx_layer_data+4,y
        sta $0B
        lda sfx_layer_data+5,y
        sta $0C
        lda sfx_layer_data+6,y
        sta $0D
        jsr play_loaded_voice
.done:
        rts

; Per-preset filter routing — loads from tables indexed by SFX number in $06.
apply_filter_for_sfx:
        ldy $06
        lda sfx_filter_mode,y
        beq .af_no_filter
        ; Filter enabled — set cutoff, resonance+routing, mode+vol
        pha                     ; save mode byte
        lda #$00
        sta SID_FC_LO
        lda sfx_filter_cutoff,y
        sta SID_FC_HI
        lda sfx_filter_resonance,y
        asl
        asl
        asl
        asl                     ; shift resonance to top nibble
        ora sfx_filter_voice,y  ; OR in voice routing bits
        sta SID_RES_FILT
        pla                     ; restore mode byte
        ora #$0F                ; add volume 15
        sta SID_MODE_VOL
        rts
.af_no_filter:
        lda #$0F                ; volume 15, no filter
        sta SID_MODE_VOL
        lda #$00
        sta SID_RES_FILT
        rts

clear_all_voices:
        lda #$00
        sta SID_V1_CR
        sta SID_V2_CR
        sta SID_V3_CR
        ldx #2
.cav_loop:
        sta voice_active,x
        sta voice_frames,x
        sta voice_sfx_idx,x
        sta voice_cr,x
        sta voice_freq_hi,x
        sta voice_freq_lo,x
        sta voice_sweep_flags,x
        sta voice_sweep_tgt_hi,x
        sta voice_sweep_tgt_lo,x
        sta voice_sweep_frames,x
        sta voice_sweep_pos,x
        sta voice_vib_phase,x
        sta voice_vib_rate,x
        sta voice_vib_depth,x
        dex
        bpl .cav_loop
        rts

play_loaded_voice:
        ; Determine voice base address offset
        lda $07
        cmp #$01
        beq .voice1
        cmp #$02
        beq .voice2
        jmp .voice3

.voice1:
        ldx #$00            ; SID offset for voice 1
        ldy #$00            ; voice index 0
        jmp .set_sid
.voice2:
        ldx #$07            ; SID offset for voice 2
        ldy #$01
        jmp .set_sid
.voice3:
        ldx #$0E            ; SID offset for voice 3
        ldy #$02

.set_sid:
        ; Save voice index
        sty $0E

        ; Gate off first (kill any playing sound)
        lda $08
        and #$FE            ; clear gate bit
        sta SID_BASE+4,x    ; CR with gate off

        ; Set ADSR
        lda $0B
        sta SID_BASE+5,x    ; AD
        lda $0C
        sta SID_BASE+6,x    ; SR

        ; Set pulse width
        lda #$00
        sta SID_BASE+2,x    ; PW lo
        lda $0D
        sta SID_BASE+3,x    ; PW hi

        ; Set frequency
        lda $0A
        sta SID_BASE,x      ; freq lo
        lda $09
        sta SID_BASE+1,x    ; freq hi

        ; Gate on
        ldx $0E             ; voice index
        lda $08
        sta voice_cr,x      ; save CR for gate-off later

        ; Set CR with gate
        lda $07
        cmp #$01
        beq .gate_v1
        cmp #$02
        beq .gate_v2
        ; Voice 3
        lda $08
        sta SID_V3_CR
        jmp .setup_state
.gate_v1:
        lda $08
        sta SID_V1_CR
        jmp .setup_state
.gate_v2:
        lda $08
        sta SID_V2_CR

.setup_state:
        ; Set up voice tracking state
        ldx $0E             ; voice index (0-2)
        lda #$01
        sta voice_active,x
        lda $06
        sta voice_sfx_idx,x

        ; Look up duration from preset duration table
        ldy $06
        lda sfx_duration,y
        sta voice_frames,x

        ; Store initial frequency for sweep
        lda $09
        sta voice_freq_hi,x
        lda $0A
        sta voice_freq_lo,x

        ; Set up sweep state
        lda $06
        sta zp_temp
        asl
        clc
        adc zp_temp
        asl
        tay                 ; Y = sweep table offset

        lda sfx_sweep+3,y   ; flags
        sta voice_sweep_flags,x
        lda sfx_sweep,y     ; target_hi
        sta voice_sweep_tgt_hi,x
        lda sfx_sweep+1,y   ; target_lo
        sta voice_sweep_tgt_lo,x
        lda sfx_sweep+2,y   ; frames
        sta voice_sweep_frames,x
        lda #$00
        sta voice_sweep_pos,x
        sta voice_vib_phase,x

        ; Vibrato params
        lda sfx_sweep+4,y   ; vib_rate
        sta voice_vib_rate,x
        lda sfx_sweep+5,y   ; vib_depth
        sta voice_vib_depth,x

        rts

; =============================================================================
; Raster IRQ handler — called ~50 times/sec
; =============================================================================
irq_handler:
        ; Acknowledge raster IRQ
        lda #$01
        sta IRQ_STATUS

        ; Update each voice
        ldx #$00
        jsr update_voice
        ldx #$01
        jsr update_voice
        ldx #$02
        jsr update_voice

        ; Pull registers and return from IRQ
        jmp $EA31           ; KERNAL IRQ return

; =============================================================================
; Update a single voice — voice index in X
; =============================================================================
update_voice:
        lda voice_active,x
        beq .uv_done

        ; Decrement frame counter
        dec voice_frames,x
        bne .uv_sweep

        ; Frame counter expired — gate off
        lda voice_cr,x
        and #$FE            ; clear gate
        cpx #$00
        bne +
        sta SID_V1_CR
        jmp .uv_deactivate
+       cpx #$01
        bne +
        sta SID_V2_CR
        jmp .uv_deactivate
+       sta SID_V3_CR

.uv_deactivate:
        lda #$00
        sta voice_active,x
        ; Restore volume-only (no filter) when voice deactivates
        lda #$0F
        sta SID_MODE_VOL
        lda #$00
        sta SID_RES_FILT
.uv_done:
        rts

.uv_sweep:
        ; Check sweep enabled
        lda voice_sweep_flags,x
        and #$01
        bne .uv_do_sweep
        jmp .uv_vibrato
.uv_do_sweep:
        ; Check if sweep is still running
        lda voice_sweep_pos,x
        cmp voice_sweep_frames,x
        bcc .uv_sweep_active
        jmp .uv_vibrato      ; sweep done
.uv_sweep_active:

        inc voice_sweep_pos,x

        ; Linear interpolation: freq = start + (target - start) * pos / frames
        ; Simplified: compute delta per frame, add to current
        ; For simplicity, use linear approach for both (exponential is close enough
        ; for audition purposes at frame rate)

        ; Load current freq
        lda voice_freq_hi,x
        sta $10
        lda voice_freq_lo,x
        sta $11

        ; Target
        lda voice_sweep_tgt_hi,x
        sta $12
        lda voice_sweep_tgt_lo,x
        sta $13

        ; Compute direction: target - current
        lda $13
        sec
        sbc $11
        sta $14             ; delta lo
        lda $12
        sbc $10
        sta $15             ; delta hi

        ; Divide delta by remaining frames
        ; remaining = sweep_frames - sweep_pos + 1
        lda voice_sweep_frames,x
        sec
        sbc voice_sweep_pos,x
        clc
        adc #$01
        sta $16             ; remaining frames

        ; Simple: step = delta / remaining (8-bit divide of high byte)
        ; For better accuracy, we'll just do a proportional step
        ; step_hi = delta_hi / remaining
        lda $15
        bpl .sweep_down_check
        ; Negative delta (descending sweep)
        ; Negate
        lda #$00
        sec
        sbc $14
        sta $14
        lda #$00
        sbc $15
        sta $15
        ; Divide
        jsr .divide_delta
        ; Subtract from current freq
        lda $11
        sec
        sbc $14             ; result lo
        sta voice_freq_lo,x
        lda $10
        sbc $15             ; result hi
        sta voice_freq_hi,x
        jmp .uv_set_freq

.sweep_down_check:
        ; Positive or zero delta (ascending sweep)
        jsr .divide_delta
        ; Add to current freq
        lda $11
        clc
        adc $14             ; result lo
        sta voice_freq_lo,x
        lda $10
        adc $15             ; result hi
        sta voice_freq_hi,x

.uv_set_freq:
        ; Write frequency to SID
        lda voice_freq_lo,x
        sta $17
        lda voice_freq_hi,x
        sta $18
        jmp .write_freq

.divide_delta:
        ; Divide 16-bit $15:$14 by 8-bit $16
        ; Result back in $15:$14
        lda $16
        beq .div_done       ; avoid div by zero
        cmp #$01
        beq .div_done       ; divide by 1 = no-op

        ; Simple shift-based divide: if remaining > delta_hi, result is small
        ; Use repeated subtraction for simplicity (max ~60 iterations)
        lda #$00
        sta $17             ; result hi
        sta $18             ; result lo

        ; 16-bit / 8-bit division
        lda #$00
        sta $19             ; remainder
        ldy #16             ; 16 bits
.div_loop:
        asl $14
        rol $15
        rol $19
        lda $19
        sec
        sbc $16
        bcc .div_no_sub
        sta $19
        inc $14
.div_no_sub:
        dey
        bne .div_loop
        ; Result in $15:$14
.div_done:
        rts

.uv_vibrato:
        ; Check vibrato enabled
        lda voice_sweep_flags,x
        and #$04
        beq .uv_write_freq_current

        ; Simple triangle LFO vibrato
        inc voice_vib_phase,x
        lda voice_vib_phase,x
        and #$1F            ; period of 32 frames
        cmp #$10
        bcs .vib_neg

        ; Positive half: add depth * phase/16
        ; Simple: add depth when phase 0-15, subtract when 16-31
        lda voice_vib_depth,x
        lsr                 ; half depth
        clc
        adc voice_freq_hi,x
        sta $18
        lda voice_freq_lo,x
        sta $17
        jmp .write_freq

.vib_neg:
        ; Negative half: subtract depth
        lda voice_freq_hi,x
        sec
        sbc voice_vib_depth,x
        bcs +
        lda #$00            ; clamp to 0
+       sta $18
        lda voice_freq_lo,x
        sta $17
        jmp .write_freq

.uv_write_freq_current:
        lda voice_freq_lo,x
        sta $17
        lda voice_freq_hi,x
        sta $18

.write_freq:
        ; Write $18:$17 (hi:lo) to SID voice X
        cpx #$00
        bne +
        lda $17
        sta SID_V1_FREQ_LO
        lda $18
        sta SID_V1_FREQ_HI
        rts
+       cpx #$01
        bne +
        lda $17
        sta SID_V2_FREQ_LO
        lda $18
        sta SID_V2_FREQ_HI
        rts
+       lda $17
        sta SID_V3_FREQ_LO
        lda $18
        sta SID_V3_FREQ_HI
        rts

; =============================================================================
; Data tables
; =============================================================================

; Screen row address lookup (row 0-24)
row_addr_lo:
        !byte <(SCREEN_BASE+0*40), <(SCREEN_BASE+1*40), <(SCREEN_BASE+2*40)
        !byte <(SCREEN_BASE+3*40), <(SCREEN_BASE+4*40), <(SCREEN_BASE+5*40)
        !byte <(SCREEN_BASE+6*40), <(SCREEN_BASE+7*40), <(SCREEN_BASE+8*40)
        !byte <(SCREEN_BASE+9*40), <(SCREEN_BASE+10*40), <(SCREEN_BASE+11*40)
        !byte <(SCREEN_BASE+12*40), <(SCREEN_BASE+13*40), <(SCREEN_BASE+14*40)
        !byte <(SCREEN_BASE+15*40), <(SCREEN_BASE+16*40), <(SCREEN_BASE+17*40)
        !byte <(SCREEN_BASE+18*40), <(SCREEN_BASE+19*40), <(SCREEN_BASE+20*40)
        !byte <(SCREEN_BASE+21*40), <(SCREEN_BASE+22*40), <(SCREEN_BASE+23*40)
        !byte <(SCREEN_BASE+24*40)
row_addr_hi:
        !byte >(SCREEN_BASE+0*40), >(SCREEN_BASE+1*40), >(SCREEN_BASE+2*40)
        !byte >(SCREEN_BASE+3*40), >(SCREEN_BASE+4*40), >(SCREEN_BASE+5*40)
        !byte >(SCREEN_BASE+6*40), >(SCREEN_BASE+7*40), >(SCREEN_BASE+8*40)
        !byte >(SCREEN_BASE+9*40), >(SCREEN_BASE+10*40), >(SCREEN_BASE+11*40)
        !byte >(SCREEN_BASE+12*40), >(SCREEN_BASE+13*40), >(SCREEN_BASE+14*40)
        !byte >(SCREEN_BASE+15*40), >(SCREEN_BASE+16*40), >(SCREEN_BASE+17*40)
        !byte >(SCREEN_BASE+18*40), >(SCREEN_BASE+19*40), >(SCREEN_BASE+20*40)
        !byte >(SCREEN_BASE+21*40), >(SCREEN_BASE+22*40), >(SCREEN_BASE+23*40)
        !byte >(SCREEN_BASE+24*40)

; Title and footer strings (PETSCII screen codes — uppercase)
title_text:
        !scr "sfx audition - up/down + return", 0
header_text:
        !scr "  name              v wav  freq", 0
footer_text:
        !scr " space=play  q=quit", 0

; Cursor position and scroll
cursor_pos:     !byte 0
scroll_offset:  !byte 0

; =============================================================================
; SFX name strings (PETSCII screen codes, null-terminated)
; =============================================================================
sfx_name_0:  !scr "fire", 0
sfx_name_1:  !scr "explode", 0
sfx_name_2:  !scr "hit", 0
sfx_name_3:  !scr "weakpoint hit", 0
sfx_name_4:  !scr "enemy hit", 0
sfx_name_5:  !scr "march", 0
sfx_name_6:  !scr "kraft alarm", 0
sfx_name_7:  !scr "game over", 0
sfx_name_8:  !scr "death", 0
sfx_name_9:  !scr "warp", 0
sfx_name_10: !scr "portal ping", 0
sfx_name_11: !scr "powerup", 0
sfx_name_12: !scr "bounce", 0
sfx_name_13: !scr "blaster bolt", 0
sfx_name_14: !scr "xwing blaster", 0
sfx_name_15: !scr "heavy repeater", 0
sfx_name_16: !scr "turbolaser", 0
sfx_name_17: !scr "tie cannon", 0
sfx_name_18: !scr "shield on", 0
sfx_name_19: !scr "ion cannon", 0
sfx_name_20: !scr "powerup spread", 0
sfx_name_21: !scr "powerup shield", 0
sfx_name_22: !scr "combo", 0
sfx_name_23: !scr "powerup speed", 0

; Name pointer table
sfx_name_ptrs:
        !word sfx_name_0,  sfx_name_1,  sfx_name_2,  sfx_name_3
        !word sfx_name_4,  sfx_name_5,  sfx_name_6,  sfx_name_7
        !word sfx_name_8,  sfx_name_9,  sfx_name_10, sfx_name_11
        !word sfx_name_12, sfx_name_13, sfx_name_14, sfx_name_15
        !word sfx_name_16, sfx_name_17, sfx_name_18, sfx_name_19
        !word sfx_name_20, sfx_name_21, sfx_name_22, sfx_name_23

; =============================================================================
; SFX data table: 7 bytes per entry (voice, CR, freq_hi, freq_lo, AD, SR, pw_hi)
; =============================================================================
sfx_data:
  !byte $01, $21, $18, $00, $06, $06, $00  ; fire (v1 SAW)
  !byte $02, $81, $08, $00, $09, $09, $00  ; explode (v2 NOISE)
  !byte $01, $41, $0C, $00, $04, $03, $04  ; hit (v1 PULSE)
  !byte $01, $41, $09, $00, $07, $27, $05  ; weakpoint_hit (v1 PULSE)
  !byte $01, $81, $10, $00, $02, $00, $00  ; enemy_hit (v1 NOISE)
  !byte $03, $11, $06, $00, $04, $04, $00  ; march (v3 TRI)
  !byte $03, $11, $04, $00, $02, $08, $00  ; kraft_alarm (v3 TRI)
  !byte $01, $41, $18, $00, $22, $A8, $08  ; game_over (v1 PULSE)
  !byte $02, $81, $14, $00, $0A, $0C, $00  ; death (v2 NOISE)
  !byte $03, $11, $04, $00, $28, $88, $00  ; warp (v3 TRI)
  !byte $01, $11, $20, $00, $02, $00, $00  ; portal_ping (v1 TRI)
  !byte $03, $11, $1C, $D6, $08, $A0, $00  ; powerup (v3 TRI)
  !byte $01, $21, $30, $00, $00, $00, $00  ; bounce (v1 SAW)
  !byte $01, $21, $28, $00, $06, $04, $00  ; blaster_bolt (v1 SAW)
  !byte $01, $21, $80, $00, $04, $03, $00  ; xwing_blaster (v1 SAW)
  !byte $01, $21, $53, $26, $05, $04, $00  ; heavy_repeater (v1 SAW)
  !byte $01, $21, $42, $85, $07, $06, $00  ; turbolaser (v1 SAW)
  !byte $01, $41, $80, $00, $03, $02, $26  ; tie_cannon (v1 PULSE)
  !byte $03, $11, $27, $E9, $68, $A8, $00  ; shield_on_v3 (v3 TRI)
  !byte $01, $41, $31, $E4, $08, $07, $14  ; ion_cannon (v1 PULSE)
  !byte $03, $41, $35, $37, $06, $C4, $10  ; powerup_spread (v3 PULSE)
  !byte $03, $11, $13, $F5, $48, $D6, $00  ; powerup_shield (v3 TRI)
  !byte $01, $21, $10, $00, $09, $00, $00  ; combo (v1 SAW)
  !byte $03, $21, $1A, $9B, $05, $A3, $00  ; powerup_speed (v3 SAW)

; Layered SFX extra voice table: same 7-byte format as sfx_data.
; Entry is zeroed when no extra voice is needed.
sfx_layer_data:
  !byte $00, $00, $00, $00, $00, $00, $00  ; fire
  !byte $03, $11, $02, $00, $0C, $0A, $00  ; explode layer: v3 TRI rumble
  !byte $00, $00, $00, $00, $00, $00, $00  ; hit
  !byte $00, $00, $00, $00, $00, $00, $00  ; weakpoint_hit
  !byte $00, $00, $00, $00, $00, $00, $00  ; enemy_hit
  !byte $00, $00, $00, $00, $00, $00, $00  ; march
  !byte $00, $00, $00, $00, $00, $00, $00  ; kraft_alarm
  !byte $00, $00, $00, $00, $00, $00, $00  ; game_over
  !byte $03, $11, $06, $00, $06, $09, $00  ; death layer: v3 TRI tail
  !byte $02, $21, $06, $00, $1A, $66, $00  ; warp layer: v2 SAW harmonic
  !byte $00, $00, $00, $00, $00, $00, $00  ; portal_ping
  !byte $00, $00, $00, $00, $00, $00, $00  ; powerup
  !byte $00, $00, $00, $00, $00, $00, $00  ; bounce
  !byte $00, $00, $00, $00, $00, $00, $00  ; blaster_bolt
  !byte $00, $00, $00, $00, $00, $00, $00  ; xwing_blaster
  !byte $00, $00, $00, $00, $00, $00, $00  ; heavy_repeater
  !byte $00, $00, $00, $00, $00, $00, $00  ; turbolaser
  !byte $00, $00, $00, $00, $00, $00, $00  ; tie_cannon
  !byte $00, $00, $00, $00, $00, $00, $00  ; shield_on_v3
  !byte $00, $00, $00, $00, $00, $00, $00  ; ion_cannon
  !byte $00, $00, $00, $00, $00, $00, $00  ; powerup_spread
  !byte $00, $00, $00, $00, $00, $00, $00  ; powerup_shield
  !byte $00, $00, $00, $00, $00, $00, $00  ; combo
  !byte $00, $00, $00, $00, $00, $00, $00  ; powerup_speed

; Per-SFX filter tables (indexed by SFX number, 1 byte each):
; mode: 0=off, $10=lowpass, $20=bandpass, $40=highpass
sfx_filter_mode:
  !byte $10  ; fire (lowpass)
  !byte $00  ; explode (off)
  !byte $10  ; hit (lowpass)
  !byte $00  ; weakpoint_hit (off)
  !byte $00  ; enemy_hit (off)
  !byte $00  ; march (off)
  !byte $00  ; kraft_alarm (off)
  !byte $00  ; game_over (off)
  !byte $00  ; death (off)
  !byte $00  ; warp (off)
  !byte $00  ; portal_ping (off)
  !byte $00  ; powerup (off)
  !byte $00  ; bounce (off)
  !byte $00  ; blaster_bolt (off)
  !byte $00  ; xwing_blaster (off)
  !byte $00  ; heavy_repeater (off)
  !byte $00  ; turbolaser (off)
  !byte $00  ; tie_cannon (off)
  !byte $00  ; shield_on_v3 (off)
  !byte $00  ; ion_cannon (off)
  !byte $00  ; powerup_spread (off)
  !byte $00  ; powerup_shield (off)
  !byte $00  ; combo (off)
  !byte $00  ; powerup_speed (off)

; cutoff: FC_HI value per preset
sfx_filter_cutoff:
  !byte $2F  ; fire
  !byte $00  ; explode
  !byte $90  ; hit
  !byte $00  ; weakpoint_hit
  !byte $00  ; enemy_hit
  !byte $00  ; march
  !byte $00  ; kraft_alarm
  !byte $00  ; game_over
  !byte $00  ; death
  !byte $00  ; warp
  !byte $00  ; portal_ping
  !byte $00  ; powerup
  !byte $00  ; bounce
  !byte $00  ; blaster_bolt
  !byte $00  ; xwing_blaster
  !byte $00  ; heavy_repeater
  !byte $00  ; turbolaser
  !byte $00  ; tie_cannon
  !byte $00  ; shield_on_v3
  !byte $00  ; ion_cannon
  !byte $00  ; powerup_spread
  !byte $00  ; powerup_shield
  !byte $00  ; combo
  !byte $00  ; powerup_speed

; resonance: top nibble of RES_FILT (0-15)
sfx_filter_resonance:
  !byte $05  ; fire
  !byte $00  ; explode
  !byte $0F  ; hit
  !byte $00  ; weakpoint_hit
  !byte $00  ; enemy_hit
  !byte $00  ; march
  !byte $00  ; kraft_alarm
  !byte $00  ; game_over
  !byte $00  ; death
  !byte $00  ; warp
  !byte $00  ; portal_ping
  !byte $00  ; powerup
  !byte $00  ; bounce
  !byte $00  ; blaster_bolt
  !byte $00  ; xwing_blaster
  !byte $00  ; heavy_repeater
  !byte $00  ; turbolaser
  !byte $00  ; tie_cannon
  !byte $00  ; shield_on_v3
  !byte $00  ; ion_cannon
  !byte $00  ; powerup_spread
  !byte $00  ; powerup_shield
  !byte $00  ; combo
  !byte $00  ; powerup_speed

; voice routing: bit mask (voice 1=bit0, 2=bit1, 3=bit2)
sfx_filter_voice:
  !byte $04  ; fire (voice 3)
  !byte $00  ; explode
  !byte $02  ; hit (voice 2)
  !byte $00  ; weakpoint_hit
  !byte $00  ; enemy_hit
  !byte $00  ; march
  !byte $00  ; kraft_alarm
  !byte $00  ; game_over
  !byte $00  ; death
  !byte $00  ; warp
  !byte $00  ; portal_ping
  !byte $00  ; powerup
  !byte $00  ; bounce
  !byte $00  ; blaster_bolt
  !byte $00  ; xwing_blaster
  !byte $00  ; heavy_repeater
  !byte $00  ; turbolaser
  !byte $00  ; tie_cannon
  !byte $00  ; shield_on_v3
  !byte $00  ; ion_cannon
  !byte $00  ; powerup_spread
  !byte $00  ; powerup_shield
  !byte $00  ; combo
  !byte $00  ; powerup_speed

; =============================================================================
; SFX sweep table: 6 bytes per entry (target_hi, target_lo, frames, flags, vib_rate, vib_depth)
; flags: bit0=sweep, bit1=exp_curve, bit2=vibrato
; =============================================================================
sfx_sweep:
  !byte $00,$00,$00,$00,$00,$00  ; fire
  !byte $00,$00,$00,$00,$00,$00  ; explode
  !byte $00,$00,$00,$00,$00,$00  ; hit
  !byte $00,$00,$00,$00,$00,$00  ; weakpoint_hit
  !byte $00,$00,$00,$00,$00,$00  ; enemy_hit
  !byte $00,$00,$00,$00,$00,$00  ; march
  !byte $00,$00,$00,$00,$00,$00  ; kraft_alarm
  !byte $00,$00,$00,$00,$00,$00  ; game_over
  !byte $00,$00,$00,$00,$00,$00  ; death
  !byte $00,$00,$00,$00,$00,$00  ; warp
  !byte $00,$00,$00,$00,$00,$00  ; portal_ping
  !byte $00,$00,$00,$00,$00,$00  ; powerup
  !byte $00,$00,$00,$00,$00,$00  ; bounce
  !byte $03,$00,$08,$03,$00,$00  ; blaster_bolt (sweep exp)
  !byte $09,$FB,$06,$03,$00,$00  ; xwing_blaster (sweep exp)
  !byte $04,$FD,$0A,$03,$00,$00  ; heavy_repeater (sweep exp)
  !byte $02,$A9,$12,$03,$00,$00  ; turbolaser (sweep exp)
  !byte $1A,$9C,$05,$03,$00,$00  ; tie_cannon (sweep exp)
  !byte $00,$00,$00,$04,$3C,$64  ; shield_on_v3 (vibrato only)
  !byte $01,$FF,$14,$03,$00,$00  ; ion_cannon (sweep exp)
  !byte $6A,$6D,$1E,$07,$20,$3C  ; powerup_spread (sweep exp + vibrato)
  !byte $10,$A1,$28,$05,$10,$50  ; powerup_shield (sweep linear + vibrato)
  !byte $00,$00,$00,$00,$00,$00  ; combo
  !byte $4F,$D2,$19,$07,$30,$28  ; powerup_speed (sweep exp + vibrato)

; =============================================================================
; Duration frames per SFX (gate-off timing)
; =============================================================================
sfx_duration:
  !byte 10   ; fire
  !byte 15   ; explode
  !byte 8    ; hit
  !byte 12   ; weakpoint_hit
  !byte 6    ; enemy_hit
  !byte 10   ; march
  !byte 10   ; kraft_alarm
  !byte 45   ; game_over
  !byte 20   ; death
  !byte 60   ; warp
  !byte 5    ; portal_ping
  !byte 15   ; powerup
  !byte 3    ; bounce
  !byte 8    ; blaster_bolt
  !byte 6    ; xwing_blaster
  !byte 10   ; heavy_repeater
  !byte 18   ; turbolaser
  !byte 5    ; tie_cannon
  !byte 60   ; shield_on_v3
  !byte 20   ; ion_cannon
  !byte 30   ; powerup_spread
  !byte 45   ; powerup_shield
  !byte 10   ; combo
  !byte 25   ; powerup_speed

; =============================================================================
; Voice state (3 voices, indexed 0-2)
; =============================================================================
voice_active:       !byte 0, 0, 0
voice_frames:       !byte 0, 0, 0
voice_sfx_idx:      !byte 0, 0, 0
voice_cr:           !byte 0, 0, 0
voice_freq_hi:      !byte 0, 0, 0
voice_freq_lo:      !byte 0, 0, 0
voice_sweep_flags:  !byte 0, 0, 0
voice_sweep_tgt_hi: !byte 0, 0, 0
voice_sweep_tgt_lo: !byte 0, 0, 0
voice_sweep_frames: !byte 0, 0, 0
voice_sweep_pos:    !byte 0, 0, 0
voice_vib_phase:    !byte 0, 0, 0
voice_vib_rate:     !byte 0, 0, 0
voice_vib_depth:    !byte 0, 0, 0
