#!/bin/bash
# Preprocess the case in the current (submission) directory.
set -euo pipefail

export TEM_UW_APP_ROOT="${TEM_UW_APP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [ -n "${TEM_UW_APP_MODULES:-}" ]; then
    for module in $TEM_UW_APP_MODULES; do module load "$module"; done
fi

exec python "$TEM_UW_APP_ROOT/src/driver.py" "$@"
