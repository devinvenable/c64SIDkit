#!/usr/bin/env bash
# Play SFX patches one at a time, showing name before each.
# Usage: ./play_patches.sh [folder]    (default: patches/)
#        ./play_patches.sh reference/

DIR="${1:-patches}"
DIR="${DIR%/}"

if [ ! -d "$DIR" ]; then
  echo "Directory not found: $DIR"
  exit 1
fi

shopt -s nullglob
files=("$DIR"/*.json)
if [ ${#files[@]} -eq 0 ]; then
  echo "No .json patches in $DIR/"
  exit 1
fi

echo "Playing ${#files[@]} patches from $DIR/"
echo "---"

for patch in "${files[@]}"; do
  name=$(basename "$patch" .json)
  wav="${patch%.json}.wav"

  # Generate WAV if missing
  if [ ! -f "$wav" ]; then
    python -m sid_sfx.cli preview "$patch" 2>/dev/null
  fi

  if [ ! -f "$wav" ]; then
    echo "[$name] — FAILED to render, skipping"
    continue
  fi

  echo ">>> $name"
  aplay "$wav" 2>/dev/null
  echo ""
done

echo "Done."
