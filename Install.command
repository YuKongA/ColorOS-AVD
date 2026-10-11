#!/bin/zsh
set -eu
PROJECT_ROOT="${0:A:h}"
exec python3 "$PROJECT_ROOT/scripts/installer.py" "$@"
