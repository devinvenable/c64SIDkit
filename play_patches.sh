#!/usr/bin/env bash
# SFX playback & A/B comparison tool with multi-backend support.
#
# Usage:
#   ./play_patches.sh                       A/B comparison (reference vs ours)
#   ./play_patches.sh [folder]              Play all patches in folder (resid)
#   ./play_patches.sh --compare [folder]    Play each patch through resid + vice
#   ./play_patches.sh --vice [folder]       Play all patches via VICE backend
#   ./play_patches.sh --backend <name> [folder]  Play via specific backend (resid|svf|vice)

PATCHES_DIR="patches"
REFERENCE_DIR="reference"
PLAYER="mpv --really-quiet"
BACKEND="resid"
COMPARE_MODE=false

# --- Parse flags ---
while [[ "$1" == --* ]]; do
  case "$1" in
    --compare)  COMPARE_MODE=true; shift ;;
    --vice)     BACKEND="vice"; shift ;;
    --backend)  BACKEND="$2"; shift 2 ;;
    *)          echo "Unknown flag: $1"; exit 1 ;;
  esac
done

render_wav() {
  local json="$1" backend="$2" out="$3"
  if [ ! -f "$out" ] || [ "$json" -nt "$out" ]; then
    python -m sid_sfx.cli preview "$json" --emulator "$backend" -o "$out" 2>/dev/null
  fi
}

# --- Simple / compare playback mode if a folder arg is given ---
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

  if $COMPARE_MODE; then
    echo "Comparing ${#files[@]} patches from $DIR/ — resid vs vice"
    echo "---"
    for patch in "${files[@]}"; do
      name=$(basename "$patch" .json)
      wav_resid="${patch%.json}_resid.wav"
      wav_vice="${patch%.json}_vice.wav"
      render_wav "$patch" resid "$wav_resid"
      render_wav "$patch" vice "$wav_vice"
      if [ ! -f "$wav_resid" ] || [ ! -f "$wav_vice" ]; then
        echo "[$name] — render failed, skipping"
        continue
      fi
      echo ">>> $name [resid]"
      $PLAYER "$wav_resid"
      echo ">>> $name [vice]"
      $PLAYER "$wav_vice"
      echo ""
    done
  else
    echo "Playing ${#files[@]} patches from $DIR/ (backend: $BACKEND)"
    echo "---"
    for patch in "${files[@]}"; do
      name=$(basename "$patch" .json)
      if [ "$BACKEND" = "resid" ]; then
        wav="${patch%.json}.wav"
      else
        wav="${patch%.json}_${BACKEND}.wav"
      fi
      render_wav "$patch" "$BACKEND" "$wav"
      if [ ! -f "$wav" ]; then
        echo "[$name] — FAILED to render, skipping"
        continue
      fi
      echo ">>> $name [$BACKEND]"
      $PLAYER "$wav"
      echo ""
    done
  fi
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
  local json="$1" backend="${2:-resid}"
  local wav
  if [ "$backend" = "resid" ]; then
    wav="${json%.json}.wav"
  else
    wav="${json%.json}_${backend}.wav"
  fi
  if [ ! -f "$wav" ] && [ -f "$json" ]; then
    python -m sid_sfx.cli preview "$json" --emulator "$backend" -o "$wav" 2>/dev/null
  fi
  echo "$wav"
}

echo "=== SFX A/B Comparison ==="
echo "For each pair: [A] = in-game original, [B] = our replacement"
if $COMPARE_MODE; then
  echo "Backend comparison: plays our patch through resid then vice"
fi
echo "Commands: a=keep original, b=keep ours, r=replay, s=skip, q=quit"
echo "          v=hear vice render, 1=resid only, 2=vice only"
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
  our_wav=$(ensure_wav "$our_json" "$BACKEND")
  our_wav_vice=$(ensure_wav "$our_json" vice)

  if [ ! -f "$ref_wav" ] || [ ! -f "$our_wav" ]; then
    echo "[$our_name] — WAV render failed, skipping"
    skipped+=("$our_name")
    continue
  fi

  echo "--- ${ref_name} ---"

  while true; do
    echo "  [A] original: ref_${ref_name}"
    $PLAYER "$ref_wav"

    echo "  [B] ours: ${our_name} [$BACKEND]"
    $PLAYER "$our_wav"

    if $COMPARE_MODE && [ -f "$our_wav_vice" ]; then
      echo "  [B-vice] ours via VICE: ${our_name}"
      $PLAYER "$our_wav_vice"
    fi

    read -rp "  Keep? (a=original, b=ours, r=replay, v=vice, s=skip, q=quit): " choice
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
      v|V)
        if [ -f "$our_wav_vice" ]; then
          echo "  [VICE render]: ${our_name}"
          $PLAYER "$our_wav_vice"
        else
          echo "  (VICE render not available)"
        fi
        ;;
      1)
        echo "  [resid]: ${our_name}"
        $PLAYER "$(ensure_wav "$our_json" resid)"
        ;;
      2)
        echo "  [vice]: ${our_name}"
        $PLAYER "$(ensure_wav "$our_json" vice)"
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
        echo "  Invalid choice. Use a/b/r/v/1/2/s/q"
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
