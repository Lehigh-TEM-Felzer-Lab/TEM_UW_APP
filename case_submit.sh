#!/bin/bash -l

# case_submit.sh - root entrypoint. Run it from the case directory (the one
# holding run_config.yaml); it hands over to launchers/case_submit.py.
# No arguments: everything comes from <case directory>/run_config.yaml.

conda deactivate >/dev/null 2>&1

TEM_UW_APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
export TEM_UW_APP_ROOT

"$TEM_UW_APP_ROOT/launchers/case_submit.py"
