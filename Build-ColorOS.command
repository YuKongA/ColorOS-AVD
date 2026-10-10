#!/bin/zsh
set -eu
PROJECT_ROOT="${0:A:h}"
cd "$PROJECT_ROOT"
exec python3 "$PROJECT_ROOT/scripts/build_coloros.py" "$@"
