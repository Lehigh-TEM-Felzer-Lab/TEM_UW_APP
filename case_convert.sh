#!/bin/bash -l

# case_convert.sh - run from the case directory after the TEM core has finished.
# Converts every output file in HIST/ to NetCDF files in OUTPUT/ (see README).

conda deactivate >/dev/null 2>&1

TUP_ROOT="$(cd "$(dirname "$0")" && pwd)"
export TUP_ROOT

"$TUP_ROOT/launchers/case_run.sh" convert
