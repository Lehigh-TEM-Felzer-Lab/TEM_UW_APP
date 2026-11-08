#!/bin/bash
# SLURM batch job: the sbatch options are set by case_submit.py.
set -euo pipefail
exec bash "$TEM_UW_APP_ROOT/launchers/case_run.sh"
