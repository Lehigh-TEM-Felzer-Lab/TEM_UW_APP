#!/bin/bash
# Preprocess the case in the current (submission) directory.
set -euo pipefail

export TUP_ROOT="${TUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [ -n "${TUP_MODULES:-}" ]; then
    for module in $TUP_MODULES; do module load "$module"; done
fi

exec python "$TUP_ROOT/src/driver.py"
