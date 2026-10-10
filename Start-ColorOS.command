#!/bin/zsh
set -eu
PROJECT_ROOT="${0:A:h}"
export COLOROS_AVD_WORKSPACE="$PROJECT_ROOT/work/coloros"
if [[ ! -f "$COLOROS_AVD_WORKSPACE/local/runtime.json" ]]; then
    print -u2 'Build ColorOS candidate first: python3 scripts/build_coloros.py'
    exit 1
fi
exec python3 "$PROJECT_ROOT/scripts/launch.py" --wait "$@"
