#!/usr/bin/env bash
# Launch the SFX tweaker and VICE audition tool side by side.
#
# Usage:
#   ./sfx_studio.sh              Launch both tools
#   ./sfx_studio.sh fire         Launch tweaker on a specific preset

DIR="$(cd "$(dirname "$0")" && pwd)"
PRG="$DIR/tools/sfx_audition.prg"
TWEAKER="$DIR/tools/sfx_tweaker.py"

# Launch VICE with the audition .prg
if command -v x64sc &>/dev/null; then
    x64sc "$PRG" &
    VICE_PID=$!
    echo "VICE audition started (PID $VICE_PID)"
else
    echo "WARNING: x64sc not found — skipping VICE audition"
fi

# Launch the Pygame tweaker (pass preset arg if given)
python3 "$TWEAKER" "$@"

# Kill VICE when tweaker exits
if [ -n "$VICE_PID" ] && kill -0 "$VICE_PID" 2>/dev/null; then
    kill "$VICE_PID" 2>/dev/null
    echo "VICE closed."
fi
