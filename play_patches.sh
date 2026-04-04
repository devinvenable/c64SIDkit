#!/usr/bin/env bash
# SFX A/B comparison tool.
# Plays each mapped pair (reference vs our patch), asks which to keep.
# At exit, dumps the final mapping decisions.
#
# Usage: ./play_patches.sh           (A/B comparison mode)
#        ./play_patches.sh [folder]  (simple playback of a folder)

PATCHES_DIR="patches"
REFERENCE_DIR="reference"

# --- Simple playback mode if a folder arg is given ---
if [ -n "$1" ]; then
  DIR="${1%/}"
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
    [ ! -f "$wav" ] && python -m sid_sfx.cli preview "$patch" 2>/dev/null
    if [ ! -f "$wav" ]; then
      echo "[$name] — FAILED to render, skipping"
      continue
    fi
    echo ">>> $name"
    aplay "$wav" 2>/dev/null
    echo ""
  done
  echo "Done."
  exit 0
fi

# --- A/B comparison mode ---

# Mapping: our_patch -> reference_name (without ref_ prefix)
declare -A MAPPING=(
  ["blaster_bolt"]="xwing_blaster"
  ["xwing_blaster_filtered"]="xwing_blaster"
  ["xwing_blaster_octdown"]="xwing_blaster"
  ["heavy_repeater_filtered"]="heavy_repeater"
  ["heavy_repeater_octdown"]="heavy_repeater"
  ["ion_cannon_filtered"]="ion_cannon"
  ["ion_cannon_octdown"]="ion_cannon"
  ["tie_cannon_filtered"]="tie_cannon"
  ["turbolaser_filtered"]="turbolaser"
  ["turbolaser_octdown"]="turbolaser"
  ["powerup_shield"]="powerup_shield"
  ["powerup_speed"]="powerup_speed"
  ["powerup_spread"]="powerup_spread"
  ["shield_on_v3"]="shield_on"
)

declare -A DECISIONS
skipped=()

ensure_wav() {
  local json="$1"
  local wav="${json%.json}.wav"
  if [ ! -f "$wav" ] && [ -f "$json" ]; then
    python -m sid_sfx.cli preview "$json" 2>/dev/null
  fi
  echo "$wav"
}

echo "=== SFX A/B Comparison ==="
echo "For each pair: [A] = in-game original, [B] = our replacement"
echo "Commands: a=keep original, b=keep ours, r=replay, s=skip, q=quit"
echo ""

for our_name in $(echo "${!MAPPING[@]}" | tr ' ' '\n' | sort); do
  ref_name="${MAPPING[$our_name]}"
  ref_json="$REFERENCE_DIR/ref_${ref_name}.json"
  our_json="$PATCHES_DIR/${our_name}.json"

  if [ ! -f "$ref_json" ]; then
    echo "[$ref_name] — reference not found, skipping"
    skipped+=("$our_name")
    continue
  fi
  if [ ! -f "$our_json" ]; then
    echo "[$our_name] — our patch not found, skipping"
    skipped+=("$our_name")
    continue
  fi

  ref_wav=$(ensure_wav "$ref_json")
  our_wav=$(ensure_wav "$our_json")

  if [ ! -f "$ref_wav" ] || [ ! -f "$our_wav" ]; then
    echo "[$our_name] — WAV render failed, skipping"
    skipped+=("$our_name")
    continue
  fi

  echo "--- ${ref_name} ---"

  while true; do
    echo "  [A] original: ref_${ref_name}"
    aplay "$ref_wav" 2>/dev/null

    echo "  [B] ours: ${our_name}"
    aplay "$our_wav" 2>/dev/null

    read -rp "  Keep? (a=original, b=ours, r=replay, s=skip, q=quit): " choice
    case "$choice" in
      a|A)
        DECISIONS["$our_name"]="KEEP_ORIGINAL:$ref_name"
        echo "  → Keeping original ($ref_name)"
        break
        ;;
      b|B)
        DECISIONS["$our_name"]="USE_OURS:$our_name"
        echo "  → Using ours ($our_name)"
        break
        ;;
      r|R)
        echo "  (replaying...)"
        ;;
      s|S)
        echo "  → Skipped"
        skipped+=("$our_name")
        break
        ;;
      q|Q)
        echo ""
        echo "Quitting early."
        break 2
        ;;
      *)
        echo "  Invalid choice. Use a/b/r/s/q"
        ;;
    esac
  done
  echo ""
done

# --- Dump results ---
echo ""
echo "========================================="
echo "  SFX MAPPING DECISIONS"
echo "========================================="
echo ""

originals=()
ours=()

for name in $(echo "${!DECISIONS[@]}" | tr ' ' '\n' | sort); do
  decision="${DECISIONS[$name]}"
  ref_name="${MAPPING[$name]}"
  case "$decision" in
    KEEP_ORIGINAL:*)
      originals+=("$ref_name (was: $name)")
      echo "  ORIGINAL  $ref_name  (rejected: $name)"
      ;;
    USE_OURS:*)
      ours+=("$name -> $ref_name")
      echo "  OURS      $name  ->  replaces $ref_name"
      ;;
  esac
done

if [ ${#skipped[@]} -gt 0 ]; then
  echo ""
  echo "  SKIPPED:"
  for s in "${skipped[@]}"; do
    echo "    - $s"
  done
fi

echo ""
echo "Summary: ${#ours[@]} replacements, ${#originals[@]} kept original, ${#skipped[@]} skipped"
echo "========================================="
