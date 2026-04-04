#!/usr/bin/env python3
"""Pygame SFX audition grid — click tiles to play presets via VICE, vote up/down."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pygame

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sid_sfx.presets import PRESETS
from sid_sfx.schema import SfxPatch, sid_freq_to_hz
from sid_sfx.vice_emulator import _build_prg, _find_vice

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_W, WINDOW_H = 1200, 800
TILE_W, TILE_H = 180, 120
PAD = 10
COLS = 6

BG_COLOR = (64, 49, 141)          # C64-ish dark blue
TILE_COLOR = (40, 30, 100)
TILE_HOVER = (60, 50, 130)
TILE_PLAYING = (100, 80, 180)
TEXT_COLOR = (200, 200, 220)
VOTE_UP_COLOR = (40, 160, 60)     # green tint
VOTE_DOWN_COLOR = (180, 50, 50)   # red tint
VOTE_BTN_SIZE = 24
VOTE_BTN_PAD = 6

# VICE C64 boot takes ~4s before our program executes
VICE_BOOT_S = 4.5
# How long to play the SFX after boot
PLAY_DURATION_S = 3.0

# ---------------------------------------------------------------------------
# Game filter (same as cli._apply_game_filter)
# ---------------------------------------------------------------------------

def _apply_game_filter(patch: SfxPatch) -> None:
    if patch.voice == 1 and patch.filter_mode == "off":
        patch.filter_mode = "bandpass"
        patch.filter_cutoff = 0x90
        patch.filter_resonance = 0xF

# ---------------------------------------------------------------------------
# VICE playback (runs in background thread)
# ---------------------------------------------------------------------------

# Track the currently running VICE process so we can kill it on new click
_vice_proc: subprocess.Popen | None = None
_vice_lock = threading.Lock()
_playing_name: str | None = None


def _play_via_vice(name: str, patch: SfxPatch):
    """Build a .prg and launch VICE to play it through speakers."""
    global _vice_proc, _playing_name

    p = copy.deepcopy(patch)
    _apply_game_filter(p)
    prg_data = _build_prg(p)

    # Kill any currently playing VICE instance
    with _vice_lock:
        if _vice_proc and _vice_proc.poll() is None:
            _vice_proc.terminate()
            try:
                _vice_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _vice_proc.kill()
        _playing_name = name

    vice_bin = _find_vice()
    PAL_CLOCK = 985248
    total_cycles = int((VICE_BOOT_S + PLAY_DURATION_S) * PAL_CLOCK)

    with tempfile.NamedTemporaryFile(suffix=".prg", delete=False) as f:
        f.write(prg_data)
        prg_path = f.name

    try:
        cmd = [
            vice_bin, "-console",
            "-sound",
            "-sounddev", "pulse",
            "-soundoutput", "1",
            "-soundbufsize", "200",
            "-soundvolume", "100",
            "-sidmodel", "1",       # 8580
            "-limitcycles", str(total_cycles),
            "-autostart", prg_path,
        ]

        with _vice_lock:
            _vice_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        _vice_proc.wait()
    finally:
        os.unlink(prg_path)
        with _vice_lock:
            if _playing_name == name:
                _playing_name = None


def play_preset(name: str, patch: SfxPatch):
    """Launch VICE playback in a background thread."""
    t = threading.Thread(target=_play_via_vice, args=(name, patch), daemon=True)
    t.start()

# ---------------------------------------------------------------------------
# Tile layout helpers
# ---------------------------------------------------------------------------

def tile_rect(index: int, scroll_y: int = 0) -> pygame.Rect:
    col = index % COLS
    row = index // COLS
    x = PAD + col * (TILE_W + PAD)
    y = PAD + row * (TILE_H + PAD) - scroll_y
    return pygame.Rect(x, y, TILE_W, TILE_H)


def vote_btn_rects(tile: pygame.Rect) -> tuple[pygame.Rect, pygame.Rect]:
    """Return (up_rect, down_rect) within a tile."""
    bx = tile.x + tile.width // 2
    by = tile.y + tile.height - VOTE_BTN_SIZE - VOTE_BTN_PAD
    up_rect = pygame.Rect(bx - VOTE_BTN_SIZE - 4, by, VOTE_BTN_SIZE, VOTE_BTN_SIZE)
    down_rect = pygame.Rect(bx + 4, by, VOTE_BTN_SIZE, VOTE_BTN_SIZE)
    return up_rect, down_rect

# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def draw_tile(
    surface: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    index: int,
    name: str,
    patch: SfxPatch,
    vote: int,
    is_playing: bool,
    scroll_y: int,
    mouse_pos: tuple[int, int],
):
    rect = tile_rect(index, scroll_y)

    # Skip tiles fully offscreen
    if rect.bottom < 0 or rect.top > WINDOW_H:
        return

    # Base color
    if is_playing:
        color = TILE_PLAYING
    elif rect.collidepoint(mouse_pos):
        color = TILE_HOVER
    else:
        color = TILE_COLOR

    # Vote tint
    if vote == 1:
        color = tuple(min(255, c + 30) for c in VOTE_UP_COLOR)
    elif vote == -1:
        color = tuple(min(255, c + 30) for c in VOTE_DOWN_COLOR)

    pygame.draw.rect(surface, color, rect, border_radius=6)
    border_color = (180, 160, 255) if is_playing else (100, 90, 160)
    pygame.draw.rect(surface, border_color, rect, width=2 if is_playing else 1, border_radius=6)

    # Preset name
    label = font.render(name, True, TEXT_COLOR)
    lx = rect.x + (rect.width - label.get_width()) // 2
    ly = rect.y + 10
    surface.blit(label, (lx, ly))

    # Info line
    freq_hz = sid_freq_to_hz(patch.frequency)
    info = f"v{patch.voice} {patch.waveform.name} {freq_hz:.0f}Hz"
    info_surf = small_font.render(info, True, (150, 150, 170))
    ix = rect.x + (rect.width - info_surf.get_width()) // 2
    iy = rect.y + 35
    surface.blit(info_surf, (ix, iy))

    # Playing indicator
    if is_playing:
        play_surf = small_font.render(">> PLAYING <<", True, (255, 220, 100))
        px = rect.x + (rect.width - play_surf.get_width()) // 2
        py = rect.y + 55
        surface.blit(play_surf, (px, py))

    # Vote buttons
    up_rect, down_rect = vote_btn_rects(rect)

    # Up button
    up_color = (60, 200, 80) if vote == 1 else (80, 80, 100)
    pygame.draw.rect(surface, up_color, up_rect, border_radius=4)
    up_label = small_font.render("\u25b2", True, TEXT_COLOR)
    surface.blit(up_label, (up_rect.x + 5, up_rect.y + 2))

    # Down button
    dn_color = (200, 60, 60) if vote == -1 else (80, 80, 100)
    pygame.draw.rect(surface, dn_color, down_rect, border_radius=4)
    dn_label = small_font.render("\u25bc", True, TEXT_COLOR)
    surface.blit(dn_label, (down_rect.x + 5, down_rect.y + 2))

    # Vote indicator text
    if vote != 0:
        vtxt = "+1" if vote == 1 else "-1"
        vsurf = small_font.render(vtxt, True, (60, 200, 80) if vote == 1 else (200, 60, 60))
        vx = rect.x + (rect.width - vsurf.get_width()) // 2
        vy = rect.y + 75
        surface.blit(vsurf, (vx, vy))

# ---------------------------------------------------------------------------
# Print votes on exit
# ---------------------------------------------------------------------------

def print_votes(votes: dict[str, int]):
    print("\n=== SFX Votes ===")
    for name in PRESETS:
        v = votes.get(name, 0)
        label = "+1 (upvote)" if v == 1 else "-1 (downvote)" if v == -1 else "0 (no vote)"
        print(f"  {name}: {label}")

    upvoted = [n for n in PRESETS if votes.get(n, 0) == 1]
    downvoted = [n for n in PRESETS if votes.get(n, 0) == -1]

    print(f"\n=== Upvoted ({len(upvoted)}) ===")
    print(f"  {', '.join(upvoted) if upvoted else '(none)'}")

    print(f"\n=== Downvoted ({len(downvoted)}) ===")
    print(f"  {', '.join(downvoted) if downvoted else '(none)'}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Verify VICE is available
    try:
        vice_bin = _find_vice()
        print(f"Using VICE: {vice_bin}")
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Init pygame (no pre-rendering needed — VICE plays live)
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("SFX Audition Grid — VICE playback")

    font = pygame.font.SysFont("monospace", 16, bold=True)
    small_font = pygame.font.SysFont("monospace", 13)

    preset_names = list(PRESETS.keys())
    votes: dict[str, int] = {name: 0 for name in preset_names}

    scroll_y = 0
    rows = (len(preset_names) + COLS - 1) // COLS
    content_h = PAD + rows * (TILE_H + PAD)

    clock = pygame.time.Clock()
    running = True

    print(f"Ready — {len(preset_names)} presets. Click to play via VICE.")

    while running:
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
            elif event.type == pygame.MOUSEWHEEL:
                scroll_y = max(0, min(scroll_y - event.y * 30, max(0, content_h - WINDOW_H)))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for i, name in enumerate(preset_names):
                    rect = tile_rect(i, scroll_y)
                    if not rect.collidepoint(mx, my):
                        continue
                    up_rect, down_rect = vote_btn_rects(rect)
                    if up_rect.collidepoint(mx, my):
                        votes[name] = 0 if votes[name] == 1 else 1
                    elif down_rect.collidepoint(mx, my):
                        votes[name] = 0 if votes[name] == -1 else -1
                    else:
                        # Play via VICE (kills any currently playing sound)
                        play_preset(name, PRESETS[name])
                    break

        # Draw
        screen.fill(BG_COLOR)

        # Title bar
        title = font.render(
            "SFX Audition — click=play via VICE, scroll, ESC=quit",
            True, TEXT_COLOR,
        )
        screen.blit(title, (PAD, PAD // 2 - 2))

        for i, name in enumerate(preset_names):
            draw_tile(
                screen, font, small_font,
                i, name, PRESETS[name],
                votes[name],
                _playing_name == name,
                scroll_y - 30,  # offset for title bar
                mouse_pos,
            )

        pygame.display.flip()
        clock.tick(60)

    # Kill any running VICE on exit
    with _vice_lock:
        if _vice_proc and _vice_proc.poll() is None:
            _vice_proc.terminate()

    pygame.quit()
    print_votes(votes)


if __name__ == "__main__":
    main()
