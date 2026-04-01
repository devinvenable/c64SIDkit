"""CLI for the SID SFX authoring pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sid_sfx.schema import SfxPatch, Waveform, hz_to_sid_freq, sid_freq_to_hz
from sid_sfx.wav_export import render_patch_to_wav
from sid_sfx.asm_export import patches_to_asm, save_asm


def cmd_preview(args):
    """Render a patch JSON to WAV."""
    patch = SfxPatch.load_json(args.input)
    out = args.output or args.input.replace(".json", ".wav")
    render_patch_to_wav(patch, out)
    freq_hz = sid_freq_to_hz(patch.frequency)
    print(f"Rendered {patch.name} -> {out}  ({freq_hz:.1f} Hz, {patch.waveform.name})")


def cmd_export(args):
    """Export one or more patch JSONs to assembly."""
    patches = []
    for path in args.inputs:
        patches.append(SfxPatch.load_json(path))

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
    print(f"7-byte:     {' '.join(f'${v:02X}' for v in b)}")
    if patch.description:
        print(f"Desc:       {patch.description}")


def cmd_from_hex(args):
    """Create a patch JSON from 7 hex bytes."""
    hex_str = args.hex.replace(" ", "").replace(",", "").replace("$", "").replace("0x", "")
    data = bytes.fromhex(hex_str)
    patch = SfxPatch.from_bytes(data, name=args.name)
    out = args.output or f"{args.name}.json"
    patch.save_json(out)
    print(f"Created {out} from hex data")


def main():
    parser = argparse.ArgumentParser(
        prog="sid-sfx",
        description="SID SFX authoring pipeline — preview & export C64 sound effects",
    )
    sub = parser.add_subparsers(dest="command")

    p_preview = sub.add_parser("preview", help="Render patch to WAV")
    p_preview.add_argument("input", help="Patch JSON file")
    p_preview.add_argument("-o", "--output", help="Output WAV path")
    p_preview.set_defaults(func=cmd_preview)

    p_export = sub.add_parser("export", help="Export patches to assembly")
    p_export.add_argument("inputs", nargs="+", help="Patch JSON files")
    p_export.add_argument("-o", "--output", help="Output .asm path")
    p_export.add_argument("-l", "--label", default="sfx_data", help="Table label")
    p_export.set_defaults(func=cmd_export)

    p_info = sub.add_parser("info", help="Show patch details")
    p_info.add_argument("input", help="Patch JSON file")
    p_info.set_defaults(func=cmd_info)

    p_hex = sub.add_parser("from-hex", help="Create patch from 7 hex bytes")
    p_hex.add_argument("hex", help="7 hex bytes (e.g. '01 21 18 00 06 06 00')")
    p_hex.add_argument("-n", "--name", default="imported", help="Patch name")
    p_hex.add_argument("-o", "--output", help="Output JSON path")
    p_hex.set_defaults(func=cmd_from_hex)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
