"""VICE-based SID emulator backend for cycle-accurate WAV preview.

Generates a minimal C64 .prg binary that programs the SID registers
exactly as the game engine would, then runs it through VICE (x64sc)
to capture the audio output as a WAV file.

This gives the most accurate preview of how patches sound in-game,
since VICE performs full C64 emulation including IRQ timing and the
analog SID filter model.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from sid_sfx.schema import SfxPatch, ATTACK_MS, DECAY_RELEASE_MS

# PAL timing constants
PAL_CLOCK = 985248          # cycles per second
PAL_CYCLES_PER_FRAME = 19656  # cycles per frame (50 Hz)

# SID register base addresses per voice (offsets from $D400)
VOICE_BASE = {1: 0x00, 2: 0x07, 3: 0x0E}

# SID register offsets within a voice
REG_FREQ_LO = 0
REG_FREQ_HI = 1
REG_PW_LO = 2
REG_PW_HI = 3
REG_CR = 4
REG_AD = 5
REG_SR = 6

# Global SID registers
REG_FILT_LO = 0x15     # Filter cutoff lo (bits 0-2)
REG_FILT_HI = 0x16     # Filter cutoff hi (bits 3-10)
REG_RES_FILT = 0x17    # Resonance + filter routing
REG_MODE_VOL = 0x18    # Filter mode + volume


def _find_vice() -> str:
    """Find the VICE x64sc binary."""
    for name in ("x64sc", "x64"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "VICE not found: install VICE and ensure x64sc or x64 is on PATH"
    )


def _build_prg(patch: SfxPatch) -> bytes:
    """Build a minimal C64 .prg that plays the given SFX patch.

    The .prg structure:
      - 2-byte load address ($0801)
      - BASIC stub: 10 SYS <ml_addr>
      - Machine language that:
        1. Sets SID registers (ADSR, freq, waveform, filter, volume)
        2. Gates on
        3. Runs a frame loop with pitch sweep and vibrato
        4. Gates off at the right time
        5. Waits for release, then loops forever
    """
    load_addr = 0x0801

    # BASIC stub: 10 SYS <addr>
    # ML starts right after the BASIC program end marker
    basic_stub = bytes([
        0x0B, 0x08,       # pointer to next BASIC line ($080B)
        0x0A, 0x00,       # line number 10
        0x9E,             # SYS token
    ])
    # We'll fill in the SYS target after calculating it
    # BASIC stub is: ptr(2) + linenum(2) + SYS(1) + digits + EOL(1) + endprog(2)

    # Calculate ML start address
    # Stub so far is 5 bytes, then digits, then 3 more bytes (EOL + end marker)
    ml_addr = load_addr + 5 + 4 + 3  # 4 digits for address, = $080D = 2061
    sys_digits = str(ml_addr).encode('ascii')
    basic_stub = bytes([
        0x0B, 0x08,
        0x0A, 0x00,
        0x9E,
    ]) + sys_digits + bytes([
        0x00,             # end of BASIC line
        0x00, 0x00,       # end of BASIC program
    ])
    ml_addr = load_addr + len(basic_stub)

    # Build machine language
    ml = bytearray()
    vb = VOICE_BASE[patch.voice]

    def lda_imm(val):
        ml.extend([0xA9, val & 0xFF])

    def sta_abs(addr):
        ml.extend([0x8D, addr & 0xFF, (addr >> 8) & 0xFF])

    def sid_write(reg, val):
        lda_imm(val)
        sta_abs(0xD400 + reg)

    # --- Set up SID registers ---
    # ADSR first (before gate, as SID latches these)
    sid_write(vb + REG_AD, patch.ad_byte)
    sid_write(vb + REG_SR, patch.sr_byte)

    # Frequency
    sid_write(vb + REG_FREQ_LO, patch.freq_lo)
    sid_write(vb + REG_FREQ_HI, patch.freq_hi)

    # Pulse width (only matters for pulse waveform but harmless to set)
    sid_write(vb + REG_PW_LO, 0x00)
    sid_write(vb + REG_PW_HI, patch.pw_hi)

    # Filter setup
    filter_mode = getattr(patch, "filter_mode", "off")
    has_filter = filter_mode != "off"
    if has_filter:
        filter_cutoff = int(getattr(patch, "filter_cutoff", 0x90))
        filter_resonance = int(getattr(patch, "filter_resonance", 0xF))
        # Map 8-bit cutoff to 11-bit: hi byte = cutoff, lo 3 bits = 0
        cutoff_11 = max(0, min(2047, filter_cutoff << 3))
        cutoff_lo = cutoff_11 & 0x07
        cutoff_hi = (cutoff_11 >> 3) & 0xFF
        sid_write(REG_FILT_LO, cutoff_lo)
        sid_write(REG_FILT_HI, cutoff_hi)
        # Resonance + voice routing
        voice_filter_bit = 1 << (patch.voice - 1)
        res_filt = ((filter_resonance & 0x0F) << 4) | voice_filter_bit
        sid_write(REG_RES_FILT, res_filt)
        # Mode + volume
        mode_bits = {"lowpass": 0x10, "bandpass": 0x20, "highpass": 0x40}
        mode_vol = mode_bits.get(filter_mode, 0x10) | 0x0F
        sid_write(REG_MODE_VOL, mode_vol)
    else:
        sid_write(REG_MODE_VOL, 0x0F)  # max volume, no filter

    # Gate ON (waveform | gate bit)
    sid_write(vb + REG_CR, patch.cr_byte)

    # --- Frame loop ---
    # For simple patches (no sweep/vibrato), just wait the right number of
    # frames then gate off. For sweep/vibrato, we do per-frame frequency updates.
    #
    # We use a simple approach: store frame count in zero page, loop with
    # a raster wait (wait for $D012 to wrap), update freq each frame.

    has_sweep = patch.has_sweep
    has_vibrato = patch.has_vibrato
    is_loop = getattr(patch, "loop", False)

    # Calculate gate-off frame
    if is_loop:
        loop_seconds = getattr(patch, "loop_preview_seconds", 5.0)
        gate_off_frame = int(loop_seconds * 50)  # PAL 50fps
    else:
        attack_ms = ATTACK_MS[patch.attack]
        decay_ms = DECAY_RELEASE_MS[patch.decay]
        gate_off_ms = attack_ms + decay_ms + 50.0
        gate_off_frame = max(1, int(gate_off_ms / 20.0))  # 20ms per PAL frame

    # Total frames to render (gate off + release + padding)
    if is_loop:
        total_frames = gate_off_frame + 10  # small tail
    else:
        release_ms = DECAY_RELEASE_MS[patch.release]
        release_frames = max(1, int(release_ms / 20.0))
        total_frames = gate_off_frame + release_frames + 5

    # Sweep parameters
    if has_sweep:
        sweep_frames = patch.sweep_frames if patch.sweep_frames > 0 else patch.duration_frames
    else:
        sweep_frames = 0

    if has_sweep or has_vibrato:
        # Complex path: per-frame frequency updates via a lookup table
        # Pre-compute frequency for each frame and store as a table
        freq_table = _compute_freq_table(patch, total_frames, sweep_frames)
        prg = _build_prg_with_freq_table(
            load_addr, basic_stub, patch, freq_table,
            gate_off_frame, total_frames, has_filter,
        )
        return prg
    else:
        # Simple path: just wait frames, gate off, wait more, halt
        # Use zero-page $02 as frame counter (safe to use)
        ZP_COUNTER = 0x02

        # LDA #0; STA $02  (init counter)
        lda_imm(0)
        sta_abs(ZP_COUNTER)

        # Frame wait loop start
        frame_loop_addr = ml_addr + len(ml)

        # Wait for raster line 255 (bottom of screen) — simple frame sync
        # wait_raster: LDA $D012; CMP #$FF; BNE wait_raster
        wait_addr = ml_addr + len(ml)
        ml.extend([0xAD, 0x12, 0xD0])   # LDA $D012
        ml.extend([0xC9, 0xFF])           # CMP #$FF
        ml.extend([0xD0, 0xFB])           # BNE -5 (back to LDA $D012)

        # Wait for raster to leave 255 (so we don't trigger again same frame)
        # wait_leave: LDA $D012; CMP #$FF; BEQ wait_leave
        ml.extend([0xAD, 0x12, 0xD0])   # LDA $D012
        ml.extend([0xC9, 0xFF])           # CMP #$FF
        ml.extend([0xF0, 0xFB])           # BEQ -5

        # INC frame counter
        ml.extend([0xEE, ZP_COUNTER & 0xFF, (ZP_COUNTER >> 8) & 0xFF])  # INC $0002

        # Check if counter == gate_off_frame
        ml.extend([0xAD, ZP_COUNTER & 0xFF, (ZP_COUNTER >> 8) & 0xFF])  # LDA $0002
        ml.extend([0xC9, min(gate_off_frame, 255)])   # CMP #gate_off
        ml.extend([0xD0, 0x05])           # BNE +5 (skip gate off)

        # Gate OFF: waveform without gate bit
        lda_imm(patch.waveform.value)
        sta_abs(0xD400 + vb + REG_CR)

        # Check if counter == total_frames
        ml.extend([0xAD, ZP_COUNTER & 0xFF, (ZP_COUNTER >> 8) & 0xFF])  # LDA $0002
        ml.extend([0xC9, min(total_frames, 255)])  # CMP #total
        ml.extend([0xD0, 0x03])           # BNE +3 (back to frame loop)

        # Done: JMP to self (halt)
        halt_addr = ml_addr + len(ml)
        ml.extend([0x4C, halt_addr & 0xFF, (halt_addr >> 8) & 0xFF])

        # JMP back to frame loop
        ml.extend([0x4C, frame_loop_addr & 0xFF, (frame_loop_addr >> 8) & 0xFF])

        return struct.pack('<H', load_addr) + basic_stub + bytes(ml)


def _compute_freq_table(
    patch: SfxPatch, total_frames: int, sweep_frames: int
) -> list[int]:
    """Compute per-frame 16-bit frequency values including sweep and vibrato."""
    import math

    start_freq = patch.frequency
    end_freq = patch.sweep_target if patch.has_sweep else start_freq
    vibrato_rate = float(getattr(patch, "vibrato_rate", 0.0) or 0.0)
    vibrato_depth = int(getattr(patch, "vibrato_depth", 0) or 0)

    freqs = []
    for frame in range(total_frames):
        # Sweep
        if patch.has_sweep and sweep_frames > 0 and frame < sweep_frames:
            frac = frame / max(1, sweep_frames - 1)
            if patch.sweep_type == "exponential" and start_freq > 0 and end_freq > 0:
                freq = int(start_freq * ((end_freq / start_freq) ** frac))
            else:
                freq = int(start_freq + (end_freq - start_freq) * frac)
        elif patch.has_sweep and frame >= sweep_frames:
            freq = end_freq
        else:
            freq = start_freq

        # Vibrato
        if vibrato_rate > 0 and vibrato_depth > 0:
            t = frame / 50.0  # PAL 50fps
            mod = vibrato_depth * math.sin(2.0 * math.pi * vibrato_rate * t)
            freq = int(freq + mod)

        freqs.append(max(0, min(0xFFFF, freq)))

    return freqs


def _build_prg_with_freq_table(
    load_addr: int,
    basic_stub: bytes,
    patch: SfxPatch,
    freq_table: list[int],
    gate_off_frame: int,
    total_frames: int,
    has_filter: bool,
) -> bytes:
    """Build a .prg with a frequency lookup table for per-frame updates.

    Uses a 16-bit index into a freq_lo/freq_hi table pair, updated each frame.
    """
    vb = VOICE_BASE[patch.voice]

    # We'll build: BASIC stub + ML code + freq tables
    # ML code does: init SID, then per-frame: read freq from table, write SID, wait frame
    ml = bytearray()
    ml_addr = load_addr + len(basic_stub)

    def lda_imm(val):
        ml.extend([0xA9, val & 0xFF])

    def sta_abs(addr):
        ml.extend([0x8D, addr & 0xFF, (addr >> 8) & 0xFF])

    def sid_write(reg, val):
        lda_imm(val)
        sta_abs(0xD400 + reg)

    # Zero page usage: $02 = frame counter lo, $03 = frame counter hi (not needed if <256)
    ZP_FRAME = 0x02

    # --- Init SID ---
    sid_write(vb + REG_AD, patch.ad_byte)
    sid_write(vb + REG_SR, patch.sr_byte)
    sid_write(vb + REG_FREQ_LO, patch.freq_lo)
    sid_write(vb + REG_FREQ_HI, patch.freq_hi)
    sid_write(vb + REG_PW_LO, 0x00)
    sid_write(vb + REG_PW_HI, patch.pw_hi)

    filter_mode = getattr(patch, "filter_mode", "off")
    if filter_mode != "off":
        filter_cutoff = int(getattr(patch, "filter_cutoff", 0x90))
        filter_resonance = int(getattr(patch, "filter_resonance", 0xF))
        cutoff_11 = max(0, min(2047, filter_cutoff << 3))
        sid_write(REG_FILT_LO, cutoff_11 & 0x07)
        sid_write(REG_FILT_HI, (cutoff_11 >> 3) & 0xFF)
        voice_filter_bit = 1 << (patch.voice - 1)
        res_filt = ((filter_resonance & 0x0F) << 4) | voice_filter_bit
        sid_write(REG_RES_FILT, res_filt)
        mode_bits = {"lowpass": 0x10, "bandpass": 0x20, "highpass": 0x40}
        mode_vol = mode_bits.get(filter_mode, 0x10) | 0x0F
        sid_write(REG_MODE_VOL, mode_vol)
    else:
        sid_write(REG_MODE_VOL, 0x0F)

    # Gate ON
    sid_write(vb + REG_CR, patch.cr_byte)

    # Init frame counter
    lda_imm(0)
    sta_abs(ZP_FRAME)

    # --- Frame loop ---
    frame_loop_addr = ml_addr + len(ml)

    # Wait for raster 255
    ml.extend([0xAD, 0x12, 0xD0])   # LDA $D012
    ml.extend([0xC9, 0xFF])           # CMP #$FF
    ml.extend([0xD0, 0xFB])           # BNE -5

    # Wait for raster to leave 255
    ml.extend([0xAD, 0x12, 0xD0])   # LDA $D012
    ml.extend([0xC9, 0xFF])           # CMP #$FF
    ml.extend([0xF0, 0xFB])           # BEQ -5

    # Load frame counter into X for table lookup
    ml.extend([0xAE, ZP_FRAME & 0xFF, (ZP_FRAME >> 8) & 0xFF])  # LDX $0002

    # Read freq_lo from table: LDA table_lo,X; STA $D400+freq_lo
    # We'll patch these addresses after we know where the tables are
    freq_lo_lda_offset = len(ml)
    ml.extend([0xBD, 0x00, 0x00])  # LDA $XXXX,X (placeholder)
    sta_abs(0xD400 + vb + REG_FREQ_LO)

    # Read freq_hi from table: LDA table_hi,X; STA $D400+freq_hi
    freq_hi_lda_offset = len(ml)
    ml.extend([0xBD, 0x00, 0x00])  # LDA $XXXX,X (placeholder)
    sta_abs(0xD400 + vb + REG_FREQ_HI)

    # INC frame counter
    ml.extend([0xEE, ZP_FRAME & 0xFF, (ZP_FRAME >> 8) & 0xFF])

    # Check gate off
    ml.extend([0xAD, ZP_FRAME & 0xFF, (ZP_FRAME >> 8) & 0xFF])  # LDA $0002
    ml.extend([0xC9, min(gate_off_frame, 255)])
    ml.extend([0xD0, 0x05])  # BNE +5

    # Gate OFF
    lda_imm(patch.waveform.value)
    sta_abs(0xD400 + vb + REG_CR)

    # Check total frames
    ml.extend([0xAD, ZP_FRAME & 0xFF, (ZP_FRAME >> 8) & 0xFF])
    ml.extend([0xC9, min(total_frames, 255)])
    ml.extend([0xD0, 0x03])  # BNE +3

    # Halt
    halt_addr = ml_addr + len(ml)
    ml.extend([0x4C, halt_addr & 0xFF, (halt_addr >> 8) & 0xFF])

    # JMP frame_loop
    ml.extend([0x4C, frame_loop_addr & 0xFF, (frame_loop_addr >> 8) & 0xFF])

    # --- Frequency tables (appended after ML) ---
    table_lo_addr = ml_addr + len(ml)
    n = min(total_frames, 256)  # Max 256 frames with 8-bit index
    freq_lo_data = bytes([freq_table[i] & 0xFF for i in range(n)])
    ml.extend(freq_lo_data)

    table_hi_addr = ml_addr + len(ml)
    freq_hi_data = bytes([(freq_table[i] >> 8) & 0xFF for i in range(n)])
    ml.extend(freq_hi_data)

    # Patch table addresses into the LDA abs,X instructions
    ml[freq_lo_lda_offset + 1] = table_lo_addr & 0xFF
    ml[freq_lo_lda_offset + 2] = (table_lo_addr >> 8) & 0xFF
    ml[freq_hi_lda_offset + 1] = table_hi_addr & 0xFF
    ml[freq_hi_lda_offset + 2] = (table_hi_addr >> 8) & 0xFF

    return struct.pack('<H', load_addr) + basic_stub + bytes(ml)


def render_patch_vice(
    patch: SfxPatch,
    sample_rate: int = 44100,
    chip_model: str = "8580",
) -> np.ndarray:
    """Render an SfxPatch using VICE for cycle-accurate SID emulation.

    Args:
        patch: The SFX patch to render.
        sample_rate: Output sample rate.
        chip_model: "6581" or "8580".

    Returns:
        float32 numpy array of audio samples [-1, 1].
    """
    vice_bin = _find_vice()
    prg_data = _build_prg(patch)

    # Calculate total cycles needed
    is_loop = getattr(patch, "loop", False)
    if is_loop:
        loop_seconds = getattr(patch, "loop_preview_seconds", 5.0)
        render_seconds = loop_seconds + 0.5
    else:
        attack_ms = ATTACK_MS[patch.attack]
        decay_ms = DECAY_RELEASE_MS[patch.decay]
        release_ms = DECAY_RELEASE_MS[patch.release]
        gate_off_ms = attack_ms + decay_ms + 50.0
        total_ms = max(
            patch.duration_frames * 20.0,
            gate_off_ms + release_ms,
        )
        render_seconds = min(total_ms / 1000.0, 5.0) + 0.5

    # Add startup overhead (~3 seconds for VICE autostart boot + BASIC init)
    startup_seconds = 3.5
    total_cycles = int((startup_seconds + render_seconds) * PAL_CLOCK)

    with tempfile.TemporaryDirectory() as tmpdir:
        prg_path = Path(tmpdir) / "sfx.prg"
        wav_path = Path(tmpdir) / "output.wav"

        prg_path.write_bytes(prg_data)

        # Build VICE command
        cmd = [
            vice_bin,
            "-console",
            "-sound",
            "-sounddev", "wav",
            "-soundarg", str(wav_path),
            "-soundrate", str(sample_rate),
            "-soundoutput", "1",        # mono
            "-soundbufsize", "1000",    # large buffer for warp mode
        ]

        # Chip model
        if chip_model == "6581":
            cmd.extend(["-sidmodel", "0"])
        else:
            cmd.extend(["-sidmodel", "1"])

        cmd.extend([
            "-limitcycles", str(total_cycles),
            "-autostartprgmode", "1",   # inject into RAM
            str(prg_path),
        ])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if not wav_path.exists():
            raise RuntimeError(
                f"VICE failed to produce WAV output.\n"
                f"stderr: {result.stderr[-500:] if result.stderr else '(empty)'}"
            )

        # Read WAV and convert to float32
        with wave.open(str(wav_path), "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                raise RuntimeError("VICE produced empty WAV file")
            raw = wf.readframes(n_frames)
            sr = wf.getframerate()

        pcm = np.frombuffer(raw, dtype=np.int16)
        audio = pcm.astype(np.float32) / 32768.0

        # Trim the silent startup portion. The C64 boot + BASIC init takes
        # ~3s before the program runs. Find where audio actually starts.
        audio = _trim_startup_silence(audio, sr)

        return audio


def _trim_startup_silence(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Trim silent startup from VICE output, keeping a small lead-in."""
    # Find first sample above noise threshold
    threshold = 0.001
    abs_audio = np.abs(audio)

    # Use a sliding window RMS to find where audio starts
    window = sample_rate // 100  # 10ms window
    if len(audio) < window:
        return audio

    # Find first window where RMS exceeds threshold
    start_idx = 0
    for i in range(0, len(audio) - window, window):
        rms = np.sqrt(np.mean(audio[i:i+window] ** 2))
        if rms > threshold:
            start_idx = max(0, i - window)  # keep one window of lead-in
            break

    return audio[start_idx:]
