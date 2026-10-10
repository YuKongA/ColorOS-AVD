#!/bin/zsh
set -eu
PROJECT_ROOT="${0:A:h}"
export COLOROS_AVD_WORKSPACE="$PROJECT_ROOT/work/coloros"
exec python3 "$PROJECT_ROOT/scripts/uninstall.py" "$@"
