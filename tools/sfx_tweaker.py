#!/usr/bin/env python3
"""Pygame SID synth tweaker — real-time sliders for SFX parameter tuning via pyresidfp."""

from __future__ import annotations

import copy
import io
import os
import sys
import time
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pygame

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sid_sfx.presets import PRESETS
from sid_sfx.schema import SfxPatch, Waveform, sid_freq_to_hz
from sid_sfx.wav_export import render_patch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_W, WINDOW_H = 1100, 740
SAMPLE_RATE = 44100

BG_COLOR = (64, 49, 141)
PANEL_COLOR = (40, 30, 100)
TEXT_COLOR = (200, 200, 220)
ACCENT_COLOR = (120, 100, 200)
SLIDER_BG = (30, 20, 70)
SLIDER_FG = (100, 180, 255)
SLIDER_KNOB = (220, 200, 255)
LABEL_COLOR = (150, 150, 180)
STATUS_COLOR = (255, 220, 100)
ACTIVE_COLOR = (100, 255, 120)

WAVEFORM_NAMES = ["TRIANGLE", "SAWTOOTH", "PULSE", "NOISE"]
WAVEFORM_VALUES = [Waveform.TRIANGLE, Waveform.SAWTOOTH, Waveform.PULSE, Waveform.NOISE]
FILTER_MODES = ["off", "lowpass", "bandpass", "highpass"]
LOOP_NAMES = ["ONE-SHOT", "SUSTAIN"]

AUTO_REPEAT_INTERVAL = 1.5  # seconds


# ---------------------------------------------------------------------------
# Slider widget
# ---------------------------------------------------------------------------

@dataclass
class Slider:
    """A horizontal slider widget."""
    label: str
    x: int
    y: int
    w: int
    h: int
    min_val: int
    max_val: int
    value: int
    fmt: str = "dec"  # "dec", "hex", "wave", "filter"

    dragging: bool = False

    @property
    def knob_x(self) -> float:
        if self.max_val == self.min_val:
            return self.x
        frac = (self.value - self.min_val) / (self.max_val - self.min_val)
        return self.x + frac * self.w

    def hit_test(self, mx: int, my: int) -> bool:
        return (self.x - 8 <= mx <= self.x + self.w + 8 and
                self.y - 4 <= my <= self.y + self.h + 4)

    def update_from_mouse(self, mx: int):
        frac = max(0.0, min(1.0, (mx - self.x) / max(1, self.w)))
        self.value = int(round(self.min_val + frac * (self.max_val - self.min_val)))

    def value_str(self) -> str:
        if self.fmt == "hex":
            return f"${self.value:02X}"
        elif self.fmt == "wave":
            return WAVEFORM_NAMES[self.value]
        elif self.fmt == "filter":
            return FILTER_MODES[self.value]
        elif self.fmt == "loop":
            return LOOP_NAMES[self.value]
        return str(self.value)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        # Label
        lbl = font.render(self.label, True, LABEL_COLOR)
        surface.blit(lbl, (self.x, self.y - 16))

        # Track
        track_rect = pygame.Rect(self.x, self.y + 2, self.w, self.h - 4)
        pygame.draw.rect(surface, SLIDER_BG, track_rect, border_radius=3)

        # Fill
        kx = int(self.knob_x)
        fill_rect = pygame.Rect(self.x, self.y + 2, kx - self.x, self.h - 4)
        if fill_rect.width > 0:
            pygame.draw.rect(surface, SLIDER_FG, fill_rect, border_radius=3)

        # Knob
        pygame.draw.circle(surface, SLIDER_KNOB, (kx, self.y + self.h // 2), 7)

        # Value text
        val = font.render(self.value_str(), True, TEXT_COLOR)
        surface.blit(val, (self.x + self.w + 10, self.y - 2))


# ---------------------------------------------------------------------------
# Audio rendering & playback
# ---------------------------------------------------------------------------

_render_lock = threading.Lock()


def render_to_sound(patch: SfxPatch) -> Optional[pygame.mixer.Sound]:
    """Render patch via pyresidfp and return a pygame Sound object."""
    p = copy.deepcopy(patch)

    try:
        samples = render_patch(p, sample_rate=SAMPLE_RATE, emulator="resid")
    except Exception as e:
        print(f"Render error: {e}", file=sys.stderr)
        return None

    # Normalize
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.8

    # Fade in/out to avoid clicks
    fade = min(int(0.005 * SAMPLE_RATE), len(samples) // 4)
    if fade > 0:
        samples[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        samples[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

    pcm = (samples * 32767).astype(np.int16)

    # Write to in-memory WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    buf.seek(0)

    return pygame.mixer.Sound(buf)


# ---------------------------------------------------------------------------
# Build patch from slider state
# ---------------------------------------------------------------------------

def build_patch_from_sliders(sliders: dict[str, Slider], preset_name: str) -> SfxPatch:
    wf_idx = sliders["waveform"].value
    fm_idx = sliders["filter_mode"].value
    return SfxPatch(
        name=preset_name,
        voice=sliders["voice"].value,
        waveform=WAVEFORM_VALUES[wf_idx],
        freq_hi=sliders["freq_hi"].value,
        freq_lo=sliders["freq_lo"].value,
        attack=sliders["attack"].value,
        decay=sliders["decay"].value,
        sustain=sliders["sustain"].value,
        release=sliders["release"].value,
        pw_hi=sliders["pw_hi"].value,
        duration_frames=sliders["duration"].value,
        sweep_target_hi=sliders["sweep_hi"].value,
        sweep_target_lo=sliders["sweep_lo"].value,
        sweep_frames=sliders["sweep_frames"].value,
        filter_mode=FILTER_MODES[fm_idx],
        filter_cutoff=sliders["filter_cutoff"].value,
        filter_resonance=sliders["filter_res"].value,
        loop=bool(sliders["loop"].value),
        vibrato_rate=float(sliders["vib_rate"].value),
        vibrato_depth=sliders["vib_depth"].value,
    )


def load_preset_to_sliders(patch: SfxPatch, sliders: dict[str, Slider]):
    sliders["voice"].value = patch.voice
    sliders["waveform"].value = WAVEFORM_VALUES.index(patch.waveform)
    sliders["freq_hi"].value = patch.freq_hi
    sliders["freq_lo"].value = patch.freq_lo
    sliders["attack"].value = patch.attack
    sliders["decay"].value = patch.decay
    sliders["sustain"].value = patch.sustain
    sliders["release"].value = patch.release
    sliders["pw_hi"].value = patch.pw_hi
    sliders["duration"].value = patch.duration_frames
    sliders["sweep_hi"].value = patch.sweep_target_hi
    sliders["sweep_lo"].value = patch.sweep_target_lo
    sliders["sweep_frames"].value = patch.sweep_frames
    sliders["filter_mode"].value = FILTER_MODES.index(patch.filter_mode)
    sliders["filter_cutoff"].value = patch.filter_cutoff
    sliders["filter_res"].value = patch.filter_resonance
    sliders["loop"].value = 1 if patch.loop else 0
    sliders["vib_rate"].value = int(patch.vibrato_rate)
    sliders["vib_depth"].value = patch.vibrato_depth


# ---------------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------------

def format_save_output(patch: SfxPatch) -> str:
    """Format patch as both Python constructor and raw hex."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  Patch: {patch.name}")
    lines.append("=" * 60)

    # Python constructor
    lines.append("")
    lines.append("# Python (paste into presets.py):")
    lines.append(f'    "{patch.name}": SfxPatch(')
    lines.append(f'        name="{patch.name}",')
    lines.append(f"        voice={patch.voice}, waveform=Waveform.{patch.waveform.name},")
    lines.append(f"        freq_hi=0x{patch.freq_hi:02X}, freq_lo=0x{patch.freq_lo:02X},")
    lines.append(f"        attack={patch.attack}, decay={patch.decay}, sustain={patch.sustain}, release={patch.release},")
    lines.append(f"        pw_hi=0x{patch.pw_hi:02X}, duration_frames={patch.duration_frames},")
    if patch.has_sweep:
        lines.append(f'        sweep_target_hi=0x{patch.sweep_target_hi:02X}, sweep_target_lo=0x{patch.sweep_target_lo:02X},')
        lines.append(f'        sweep_frames={patch.sweep_frames}, sweep_type="exponential",')
    if patch.filter_mode != "off":
        lines.append(f'        filter_cutoff=0x{patch.filter_cutoff:02X}, filter_resonance=0x{patch.filter_resonance:X}, filter_mode="{patch.filter_mode}",')
    if patch.vibrato_rate > 0 or patch.vibrato_depth > 0:
        lines.append(f"        vibrato_rate={patch.vibrato_rate}, vibrato_depth={patch.vibrato_depth},")
    if patch.loop:
        lines.append(f"        loop=True,")
    lines.append("    ),")

    # Raw hex
    raw = patch.to_bytes()
    lines.append("")
    lines.append("# Raw 7-byte SFX hex (voice, CR, freq_hi, freq_lo, AD, SR, pw_hi):")
    lines.append(f"  {' '.join(f'${b:02X}' for b in raw)}")

    if patch.has_sweep:
        lines.append("")
        lines.append("# Sweep hex (target_hi, target_lo, frames, 0, 0, 0):")
        sweep_bytes = bytes([patch.sweep_target_hi, patch.sweep_target_lo, patch.sweep_frames, 0, 0, 0])
        lines.append(f"  {' '.join(f'${b:02X}' for b in sweep_bytes)}")

    # Human-readable summary
    freq_hz = sid_freq_to_hz(patch.frequency)
    lines.append("")
    lines.append(f"# {patch.waveform.name} @ {freq_hz:.0f}Hz  v{patch.voice}  "
                 f"A={patch.attack} D={patch.decay} S={patch.sustain} R={patch.release}")
    if patch.has_sweep:
        target_hz = sid_freq_to_hz(patch.sweep_target)
        lines.append(f"# Sweep → {target_hz:.0f}Hz in {patch.sweep_frames}fr")
    if patch.filter_mode != "off":
        lines.append(f"# Filter: {patch.filter_mode} cutoff=${patch.filter_cutoff:02X} res={patch.filter_resonance}")
    if patch.vibrato_rate > 0 or patch.vibrato_depth > 0:
        lines.append(f"# Vibrato: rate={patch.vibrato_rate}Hz depth={patch.vibrato_depth}")
    if patch.loop:
        lines.append("# Mode: SUSTAIN (loop)")
    lines.append("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def create_sliders() -> dict[str, Slider]:
    """Create all parameter sliders in a two-column layout."""
    sliders: dict[str, Slider] = {}
    sx, sw, sh = 20, 200, 14
    dy = 38  # vertical spacing

    # Left column
    col1_x = sx
    y = 50

    sliders["freq_hi"] = Slider("Freq Hi", col1_x, y, sw, sh, 0, 255, 0x50, "hex"); y += dy
    sliders["freq_lo"] = Slider("Freq Lo", col1_x, y, sw, sh, 0, 255, 0x00, "hex"); y += dy
    sliders["waveform"] = Slider("Waveform", col1_x, y, sw, sh, 0, 3, 1, "wave"); y += dy
    sliders["attack"] = Slider("Attack", col1_x, y, sw, sh, 0, 15, 0); y += dy
    sliders["decay"] = Slider("Decay", col1_x, y, sw, sh, 0, 15, 3); y += dy
    sliders["sustain"] = Slider("Sustain", col1_x, y, sw, sh, 0, 15, 1); y += dy
    sliders["release"] = Slider("Release", col1_x, y, sw, sh, 0, 15, 3); y += dy
    sliders["pw_hi"] = Slider("Pulse Width", col1_x, y, sw, sh, 0, 255, 0x04, "hex"); y += dy
    sliders["voice"] = Slider("Voice", col1_x, y, sw, sh, 1, 3, 1); y += dy

    # Right column
    col2_x = 370
    y = 50

    sliders["sweep_hi"] = Slider("Sweep Hi", col2_x, y, sw, sh, 0, 255, 0x10, "hex"); y += dy
    sliders["sweep_lo"] = Slider("Sweep Lo", col2_x, y, sw, sh, 0, 255, 0x00, "hex"); y += dy
    sliders["sweep_frames"] = Slider("Sweep Frames", col2_x, y, sw, sh, 0, 60, 3); y += dy
    sliders["duration"] = Slider("Duration (fr)", col2_x, y, sw, sh, 1, 60, 10); y += dy
    sliders["filter_mode"] = Slider("Filter Mode", col2_x, y, sw, sh, 0, 3, 2, "filter"); y += dy
    sliders["filter_cutoff"] = Slider("Filter Cutoff", col2_x, y, sw, sh, 0, 255, 0x90, "hex"); y += dy
    sliders["filter_res"] = Slider("Filter Res", col2_x, y, sw, sh, 0, 15, 15); y += dy
    sliders["loop"] = Slider("Mode", col2_x, y, sw, sh, 0, 1, 0, "loop"); y += dy
    sliders["vib_rate"] = Slider("Vibrato Rate", col2_x, y, sw, sh, 0, 60, 0); y += dy
    sliders["vib_depth"] = Slider("Vibrato Depth", col2_x, y, sw, sh, 0, 255, 0); y += dy

    return sliders


def main():
    preset_names = list(PRESETS.keys())
    preset_idx = 0

    # Parse CLI arg for starting preset
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in PRESETS:
            preset_idx = preset_names.index(arg)
        else:
            print(f"Unknown preset '{arg}'. Available: {', '.join(preset_names)}")
            sys.exit(1)

    current_preset = preset_names[preset_idx]

    # Init pygame
    pygame.init()
    pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=1024)
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption(f"SFX Tweaker — {current_preset}")

    font = pygame.font.SysFont("monospace", 14, bold=True)
    small_font = pygame.font.SysFont("monospace", 12)
    big_font = pygame.font.SysFont("monospace", 18, bold=True)

    sliders = create_sliders()
    load_preset_to_sliders(PRESETS[current_preset], sliders)

    auto_repeat = True
    last_play_time = 0.0
    last_save_msg = ""
    last_save_time = 0.0
    status_msg = ""
    is_rendering = False
    current_sound: Optional[pygame.mixer.Sound] = None
    needs_render = True  # render on first loop
    was_sustain = False

    clock = pygame.time.Clock()
    running = True

    print(f"SFX Tweaker ready — preset: {current_preset}")
    print("  SPACE=toggle repeat  P=play once  S=save  L/R arrows=cycle presets  ESC=quit")

    while running:
        now = time.time()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                elif event.key == pygame.K_SPACE:
                    auto_repeat = not auto_repeat
                    status_msg = f"Auto-repeat: {'ON' if auto_repeat else 'OFF'}"

                elif event.key == pygame.K_p:
                    # Play once immediately
                    patch = build_patch_from_sliders(sliders, current_preset)
                    snd = render_to_sound(patch)
                    if snd:
                        if current_sound:
                            current_sound.stop()
                        current_sound = snd
                        current_sound.play()
                        last_play_time = now
                    status_msg = "Playing..."

                elif event.key == pygame.K_s:
                    patch = build_patch_from_sliders(sliders, current_preset)
                    output = format_save_output(patch)
                    print(output)
                    # Auto-save JSON patch file
                    patch_path = Path(__file__).resolve().parent.parent / "patches" / f"{current_preset}.json"
                    patch.save_json(patch_path)
                    last_save_msg = f"Saved: {current_preset} → {patch_path.name}"
                    last_save_time = now
                    status_msg = last_save_msg

                elif event.key in (pygame.K_l, pygame.K_RIGHT):
                    preset_idx = (preset_idx + 1) % len(preset_names)
                    current_preset = preset_names[preset_idx]
                    load_preset_to_sliders(PRESETS[current_preset], sliders)
                    pygame.display.set_caption(f"SFX Tweaker — {current_preset}")
                    needs_render = True
                    status_msg = f"Loaded: {current_preset}"

                elif event.key == pygame.K_LEFT:
                    preset_idx = (preset_idx - 1) % len(preset_names)
                    current_preset = preset_names[preset_idx]
                    load_preset_to_sliders(PRESETS[current_preset], sliders)
                    pygame.display.set_caption(f"SFX Tweaker — {current_preset}")
                    needs_render = True
                    status_msg = f"Loaded: {current_preset}"

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for s in sliders.values():
                    if s.hit_test(mx, my):
                        s.dragging = True
                        s.update_from_mouse(mx)
                        needs_render = True

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                for s in sliders.values():
                    s.dragging = False

            elif event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                for s in sliders.values():
                    if s.dragging:
                        old_val = s.value
                        s.update_from_mouse(mx)
                        if s.value != old_val:
                            needs_render = True

        # Auto-repeat playback
        is_sustain = bool(sliders["loop"].value)
        if is_sustain and not was_sustain:
            # Just switched to sustain — start looping
            patch = build_patch_from_sliders(sliders, current_preset)
            snd = render_to_sound(patch)
            if snd:
                if current_sound:
                    current_sound.stop()
                current_sound = snd
                current_sound.play(loops=-1)
                needs_render = False
        elif not is_sustain and was_sustain:
            # Just switched back to one-shot — stop the loop
            if current_sound:
                current_sound.stop()
            needs_render = True
        elif is_sustain and needs_render:
            # Sustain active — re-render and restart loop on parameter change
            patch = build_patch_from_sliders(sliders, current_preset)
            snd = render_to_sound(patch)
            if snd:
                if current_sound:
                    current_sound.stop()
                current_sound = snd
                current_sound.play(loops=-1)
                needs_render = False
        elif auto_repeat and (now - last_play_time) >= AUTO_REPEAT_INTERVAL:
            # One-shot: retrigger periodically
            if needs_render or current_sound is None:
                patch = build_patch_from_sliders(sliders, current_preset)
                snd = render_to_sound(patch)
                if snd:
                    current_sound = snd
                    needs_render = False
            if current_sound:
                current_sound.stop()
                current_sound.play()
                last_play_time = now
        was_sustain = is_sustain

        # ---- Draw ----
        screen.fill(BG_COLOR)

        # Title
        title = big_font.render(f"SFX Tweaker", True, TEXT_COLOR)
        screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 10))

        # Draw all sliders
        for s in sliders.values():
            s.draw(screen, small_font)

        # --- Right panel: current values ---
        panel_x = 700
        panel_y = 50
        py = panel_y

        pygame.draw.rect(screen, PANEL_COLOR,
                         pygame.Rect(panel_x - 10, panel_y - 10, 390, 440),
                         border_radius=8)

        patch = build_patch_from_sliders(sliders, current_preset)
        freq_hz = sid_freq_to_hz(patch.frequency)

        info_lines = [
            f"Preset: {current_preset}",
            "",
            f"Frequency: ${patch.freq_hi:02X}.{patch.freq_lo:02X}  ({freq_hz:.1f} Hz)",
            f"Waveform:  {patch.waveform.name}",
            f"Voice:     {patch.voice}",
            "",
            f"Attack:    {patch.attack:2d}   Decay:   {patch.decay:2d}",
            f"Sustain:   {patch.sustain:2d}   Release: {patch.release:2d}",
            f"AD byte:   ${patch.ad_byte:02X}   SR byte: ${patch.sr_byte:02X}",
            "",
            f"Pulse W:   ${patch.pw_hi:02X}",
            f"Duration:  {patch.duration_frames} frames ({patch.duration_frames/60*1000:.0f}ms)",
            "",
        ]

        if patch.has_sweep:
            target_hz = sid_freq_to_hz(patch.sweep_target)
            info_lines.extend([
                f"Sweep:     ${patch.sweep_target_hi:02X}.{patch.sweep_target_lo:02X}  ({target_hz:.1f} Hz)",
                f"Sweep fr:  {patch.sweep_frames}",
            ])
        else:
            info_lines.append("Sweep:     (none)")
        info_lines.append("")

        info_lines.append(f"Filter:    {patch.filter_mode}")
        if patch.filter_mode != "off":
            info_lines.append(f"Cutoff:    ${patch.filter_cutoff:02X}  Res: {patch.filter_resonance}")
        info_lines.append("")

        raw = patch.to_bytes()
        info_lines.append(f"Raw 7B:    {' '.join(f'${b:02X}' for b in raw)}")
        info_lines.append(f"CR byte:   ${patch.cr_byte:02X}")

        for line in info_lines:
            surf = small_font.render(line, True, TEXT_COLOR)
            screen.blit(surf, (panel_x, py))
            py += 18

        # --- Status bar ---
        bar_y = WINDOW_H - 50
        pygame.draw.rect(screen, PANEL_COLOR,
                         pygame.Rect(0, bar_y, WINDOW_W, 50))

        # Left: controls help
        help_text = "SPACE=repeat  P=play  S=save  L/R=preset  ESC=quit"
        help_surf = small_font.render(help_text, True, LABEL_COLOR)
        screen.blit(help_surf, (10, bar_y + 8))

        # Center: auto-repeat indicator
        repeat_text = f"Auto-repeat: {'ON' if auto_repeat else 'OFF'}"
        repeat_color = ACTIVE_COLOR if auto_repeat else (180, 80, 80)
        repeat_surf = font.render(repeat_text, True, repeat_color)
        screen.blit(repeat_surf, (WINDOW_W // 2 - repeat_surf.get_width() // 2, bar_y + 6))

        # Right: status message
        if status_msg:
            st_color = STATUS_COLOR if (now - last_save_time) < 3.0 and "Saved" in status_msg else TEXT_COLOR
            st_surf = small_font.render(status_msg, True, st_color)
            screen.blit(st_surf, (WINDOW_W - st_surf.get_width() - 10, bar_y + 8))

        # Bottom line: preset name
        preset_info = f"[{preset_idx+1}/{len(preset_names)}] {current_preset}"
        pi_surf = small_font.render(preset_info, True, LABEL_COLOR)
        screen.blit(pi_surf, (10, bar_y + 28))

        pygame.display.flip()
        clock.tick(60)

    pygame.mixer.quit()
    pygame.quit()
    print("SFX Tweaker closed.")


if __name__ == "__main__":
    main()
