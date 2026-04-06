"""CLI for the SID SFX authoring pipeline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sid_sfx.schema import SfxPatch, Waveform, hz_to_sid_freq, sid_freq_to_hz
from sid_sfx.wav_export import render_patch_to_wav
from sid_sfx.asm_export import patches_to_asm, patches_to_asm_tables, patches_to_game_tables, save_asm, save_asm_tables
from sid_sfx.spectral_diff import generate_diff_report
from sid_sfx.presets import PRESETS


def cmd_preview(args):
    """Render a patch JSON to WAV."""
    patch = SfxPatch.load_json(args.input)

    # Game engine applies band-pass filter to voice 1 blasters.
    # Warn if a voice 1 patch has no filter — preview won't match gameplay.
    if patch.voice == 1 and patch.filter_mode == "off" and not args.no_game_filter:
        print(f"WARNING: Voice 1 patch '{patch.name}' has filter_mode=off.")
        print("  Game applies band-pass (res=$F, cutoff=$90) to all voice 1 SFX.")
        print("  Preview will NOT match gameplay. Add filter fields or use --no-game-filter to suppress.")
        print("  Auto-applying game filter for accurate preview.")
        patch.filter_mode = "bandpass"
        patch.filter_cutoff = 0x90
        patch.filter_resonance = 0xF

    out = args.output or args.input.replace(".json", ".wav")
    render_patch_to_wav(
        patch,
        out,
        emulator=args.emulator,
        chip_model=args.chip,
    )
    freq_hz = sid_freq_to_hz(patch.frequency)
    emu_desc = args.emulator if args.emulator == "svf" else f"{args.emulator}/{args.chip}"
    print(f"Rendered {patch.name} -> {out}  ({freq_hz:.1f} Hz, {patch.waveform.name}, {emu_desc})")


def cmd_export(args):
    """Export one or more patch JSONs to assembly."""
    patches = []
    for path in args.inputs:
        patches.append(SfxPatch.load_json(path))

    if args.format == "tables":
        if args.output:
            save_asm_tables(patches, args.output)
            print(f"Exported {len(patches)} SFX (separate tables) -> {args.output}")
        else:
            print(patches_to_asm_tables(patches))
    else:
        if args.output:
            save_asm(patches, args.output, label=args.label)
            print(f"Exported {len(patches)} SFX -> {args.output}")
        else:
            print(patches_to_asm(patches, label=args.label))


def cmd_info(args):
    """Show patch details."""
    patch = SfxPatch.load_json(args.input)
    b = patch.to_bytes()
    freq_hz = sid_freq_to_hz(patch.frequency)
    print(f"Name:       {patch.name}")
    print(f"Voice:      {patch.voice}")
    print(f"Waveform:   {patch.waveform.name}")
    print(f"Frequency:  ${patch.freq_hi:02X}{patch.freq_lo:02X} ({freq_hz:.1f} Hz)")
    print(f"Attack:     {patch.attack}  Decay: {patch.decay}")
    print(f"Sustain:    {patch.sustain}  Release: {patch.release}")
    print(f"PW High:    ${patch.pw_hi:02X}")
    print(f"Duration:   {patch.duration_frames} frames")
    if patch.has_sweep:
        sweep_hz = sid_freq_to_hz(patch.sweep_target)
        print(f"Sweep:      ${patch.sweep_target_hi:02X}{patch.sweep_target_lo:02X} ({sweep_hz:.1f} Hz), {patch.sweep_type}")
    if patch.has_vibrato:
        print(f"Vibrato:    {patch.vibrato_rate:.1f} Hz, depth {patch.vibrato_depth} SID units")
    print(f"7-byte:     {' '.join(f'${v:02X}' for v in b)}")
    if patch.description:
        print(f"Desc:       {patch.description}")


def cmd_game_export(args):
    """Export blaster patches in exact game table format."""
    patches = []
    for path in args.inputs:
        patches.append(SfxPatch.load_json(path))
    output = patches_to_game_tables(patches)
    if args.output:
        Path(args.output).write_text(output + "\n")
        print(f"Exported {len(patches)} blaster variants (game format) -> {args.output}")
    else:
        print(output)


def cmd_compare(args):
    """Render a patch through all available backends for comparison."""
    patch = SfxPatch.load_json(args.input)

    # Auto-apply game filter for voice 1 (same as preview)
    if patch.voice == 1 and patch.filter_mode == "off" and not args.no_game_filter:
        print(f"Auto-applying game band-pass filter for voice 1 patch '{patch.name}'.")
        patch.filter_mode = "bandpass"
        patch.filter_cutoff = 0x90
        patch.filter_resonance = 0xF

    base = args.input.replace(".json", "")
    backends = ["resid", "svf", "vice"]
    chip = args.chip

    for backend in backends:
        out_path = f"{base}_{backend}.wav"
        try:
            render_patch_to_wav(patch, out_path, emulator=backend, chip_model=chip)
            freq_hz = sid_freq_to_hz(patch.frequency)
            emu_desc = backend if backend == "svf" else f"{backend}/{chip}"
            print(f"  {backend:6s} -> {out_path}  ({freq_hz:.1f} Hz, {patch.waveform.name}, {emu_desc})")
        except Exception as e:
            print(f"  {backend:6s} -> FAILED: {e}")

    print("Compare complete.")


def cmd_from_hex(args):
    """Create a patch JSON from 7 hex bytes."""
    hex_str = args.hex.replace(" ", "").replace(",", "").replace("$", "").replace("0x", "")
    data = bytes.fromhex(hex_str)
    patch = SfxPatch.from_bytes(data, name=args.name)
    out = args.output or f"{args.name}.json"
    patch.save_json(out)
    print(f"Created {out} from hex data")


def _apply_game_filter(patch: SfxPatch) -> None:
    """Auto-apply game band-pass filter for voice 1 patches with filter_mode=off."""
    if patch.voice == 1 and patch.filter_mode == "off":
        patch.filter_mode = "bandpass"
        patch.filter_cutoff = 0x90
        patch.filter_resonance = 0xF


def _render_preset(name: str, patch: SfxPatch, output_dir: str, emulator: str, chip: str, apply_filter: bool) -> str:
    """Render a single preset to WAV and print info. Returns the output path."""
    import copy
    p = copy.deepcopy(patch)
    if apply_filter:
        _apply_game_filter(p)
    out_path = str(Path(output_dir) / f"{name}.wav")
    render_patch_to_wav(p, out_path, emulator=emulator, chip_model=chip)
    freq_hz = sid_freq_to_hz(p.frequency)
    emu_desc = emulator if emulator == "svf" else f"{emulator}/{chip}"
    print(f"  {name:20s} -> {out_path}  ({freq_hz:.1f} Hz, {p.waveform.name}, {emu_desc})")
    return out_path


def _play_wav(wav_path: str) -> None:
    """Play a WAV file through speakers. Uses pygame if available, else aplay/paplay/afplay."""
    try:
        import pygame
        import pygame.mixer
        pygame.mixer.init()
        sound = pygame.mixer.Sound(wav_path)
        sound.play()
        pygame.time.wait(int(sound.get_length() * 1000) + 100)
        pygame.mixer.quit()
        return
    except ImportError:
        pass

    for player in ["paplay", "aplay", "afplay"]:
        if shutil.which(player):
            subprocess.run([player, wav_path], check=True)
            return

    print("Warning: no audio player found. Install pygame or ensure paplay/aplay/afplay is available.",
          file=sys.stderr)


def _play_via_vice(patch: SfxPatch) -> None:
    """Play a patch through VICE live audio (not WAV recording)."""
    import copy
    from sid_sfx.vice_emulator import _build_prg, _find_vice

    p = copy.deepcopy(patch)
    _apply_game_filter(p)
    prg_data = _build_prg(p)
    vice_bin = _find_vice()

    PAL_CLOCK = 985248
    VICE_BOOT_S = 4.5
    PLAY_DURATION_S = 3.0
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
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    finally:
        os.unlink(prg_path)


def cmd_play(args):
    """Render built-in SFX presets to WAV and play through speakers."""
    if args.list:
        print(f"Available presets ({len(PRESETS)}):")
        for name, patch in PRESETS.items():
            freq_hz = sid_freq_to_hz(patch.frequency)
            print(f"  {name:20s}  v{patch.voice} {patch.waveform.name:10s} {freq_hz:7.1f} Hz  {patch.description}")
        return

    save_wavs = args.output_dir is not None
    apply_filter = not args.no_game_filter
    use_vice_live = args.emulator == "vice"

    if args.all:
        if save_wavs:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            print(f"Playing all {len(PRESETS)} presets (saving to {args.output_dir}/)...")
        else:
            print(f"Playing all {len(PRESETS)} presets...")

        tmpdir = None if save_wavs else tempfile.mkdtemp()
        output_dir = args.output_dir if save_wavs else tmpdir

        for name, patch in PRESETS.items():
            if use_vice_live:
                import copy
                p = copy.deepcopy(patch)
                if apply_filter:
                    _apply_game_filter(p)
                print(f"  {name:20s} (VICE live)...")
                _play_via_vice(p)
            else:
                wav_path = _render_preset(name, patch, output_dir, args.emulator, args.chip, apply_filter)
                _play_wav(wav_path)
                if not save_wavs:
                    os.unlink(wav_path)

        if tmpdir:
            os.rmdir(tmpdir)
        if save_wavs:
            print(f"Done — {len(PRESETS)} WAV files in {args.output_dir}/")
        return

    if not args.preset:
        print("Error: specify a preset name, --list, or --all", file=sys.stderr)
        sys.exit(1)

    name = args.preset
    if name not in PRESETS:
        print(f"Error: unknown preset '{name}'. Use --list to see available presets.", file=sys.stderr)
        sys.exit(1)

    patch = PRESETS[name]

    if use_vice_live:
        import copy
        p = copy.deepcopy(patch)
        if apply_filter:
            _apply_game_filter(p)
        print(f"  {name:20s} (VICE live)...")
        _play_via_vice(p)
        if save_wavs:
            print("Note: VICE WAV recording is unreliable. Saved WAV may have dropped audio.")
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            _render_preset(name, patch, args.output_dir, args.emulator, args.chip, apply_filter)
        return

    if save_wavs:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        wav_path = _render_preset(name, patch, args.output_dir, args.emulator, args.chip, apply_filter)
    else:
        tmpdir = tempfile.mkdtemp()
        wav_path = _render_preset(name, patch, tmpdir, args.emulator, args.chip, apply_filter)

    _play_wav(wav_path)

    if not save_wavs:
        os.unlink(wav_path)
        os.rmdir(tmpdir)


def cmd_spectral_diff(args):
    """Render with two backends and compare spectral similarity."""
    raw_backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    if len(raw_backends) != 2:
        raise ValueError("--backends must contain exactly two comma-separated backends, e.g. resid,svf")
    backend_a, backend_b = raw_backends

    report = generate_diff_report(
        patch_path=args.input,
        backend_a=backend_a,
        backend_b=backend_b,
        output_dir=args.output_dir,
        chip_model=args.chip,
    )
    print(report)


def main():
    parser = argparse.ArgumentParser(
        prog="sid-sfx",
        description="SID SFX authoring pipeline — preview & export C64 sound effects",
    )
    sub = parser.add_subparsers(dest="command")

    p_preview = sub.add_parser("preview", help="Render patch to WAV")
    p_preview.add_argument("input", help="Patch JSON file")
    p_preview.add_argument("-o", "--output", help="Output WAV path")
    p_preview.add_argument(
        "--emulator",
        choices=["resid", "svf", "vice"],
        default="resid",
        help="Preview emulator backend",
    )
    p_preview.add_argument(
        "--chip",
        choices=["6581", "8580"],
        default="8580",
        help="SID chip model (used by reSID emulator)",
    )
    p_preview.add_argument(
        "--no-game-filter",
        action="store_true",
        default=False,
        help="Disable auto-applying game band-pass filter on voice 1 patches",
    )
    p_preview.set_defaults(func=cmd_preview)

    p_export = sub.add_parser("export", help="Export patches to assembly")
    p_export.add_argument("inputs", nargs="+", help="Patch JSON files")
    p_export.add_argument("-o", "--output", help="Output .asm path")
    p_export.add_argument("-l", "--label", default="sfx_data", help="Table label")
    p_export.add_argument("-f", "--format", choices=["flat", "tables"], default="flat",
                          help="Export format: 'flat' (single table) or 'tables' (separate sfx_data + sfx_sweep)")
    p_export.set_defaults(func=cmd_export)

    p_game = sub.add_parser("game-export", help="Export blaster patches in game table format")
    p_game.add_argument("inputs", nargs="+", help="Blaster variant patch JSONs (indices 1+)")
    p_game.add_argument("-o", "--output", help="Output .asm path")
    p_game.set_defaults(func=cmd_game_export)

    p_compare = sub.add_parser("compare", help="Render patch through all backends for comparison")
    p_compare.add_argument("input", help="Patch JSON file")
    p_compare.add_argument(
        "--chip",
        choices=["6581", "8580"],
        default="8580",
        help="SID chip model",
    )
    p_compare.add_argument(
        "--no-game-filter",
        action="store_true",
        default=False,
        help="Disable auto-applying game band-pass filter on voice 1 patches",
    )
    p_compare.set_defaults(func=cmd_compare)

    p_info = sub.add_parser("info", help="Show patch details")
    p_info.add_argument("input", help="Patch JSON file")
    p_info.set_defaults(func=cmd_info)

    p_hex = sub.add_parser("from-hex", help="Create patch from 7 hex bytes")
    p_hex.add_argument("hex", help="7 hex bytes (e.g. '01 21 18 00 06 06 00')")
    p_hex.add_argument("-n", "--name", default="imported", help="Patch name")
    p_hex.add_argument("-o", "--output", help="Output JSON path")
    p_hex.set_defaults(func=cmd_from_hex)

    p_play = sub.add_parser("play", help="Audition built-in SFX presets")
    p_play.add_argument("preset", nargs="?", default=None, help="Preset name to render")
    p_play.add_argument("--list", action="store_true", help="List all available preset names")
    p_play.add_argument("--all", action="store_true", help="Render ALL presets to WAV")
    p_play.add_argument(
        "--emulator",
        choices=["resid", "svf", "vice"],
        default="resid",
        help="Preview emulator backend",
    )
    p_play.add_argument(
        "--chip",
        choices=["6581", "8580"],
        default="8580",
        help="SID chip model",
    )
    p_play.add_argument(
        "--no-game-filter",
        action="store_true",
        default=False,
        help="Disable auto-applying game band-pass filter on voice 1 patches",
    )
    p_play.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Output directory for WAV files (renders without saving if omitted)",
    )
    p_play.set_defaults(func=cmd_play)

    p_spectral = sub.add_parser("spectral-diff", help="Compare WAV renders across two emulator backends")
    p_spectral.add_argument("input", help="Patch JSON file")
    p_spectral.add_argument(
        "--backends",
        default="resid,svf",
        help="Comma-separated backend names to compare (e.g. resid,svf)",
    )
    p_spectral.add_argument(
        "--chip",
        choices=["6581", "8580"],
        default="8580",
        help="SID chip model (used by reSID backend)",
    )
    p_spectral.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Directory where rendered comparison WAV files will be written",
    )
    p_spectral.set_defaults(func=cmd_spectral_diff)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    try:
        args.func(args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
