#!/usr/bin/env python3

"""Submit a TEM_UW_APP case to SLURM (or run it in the foreground).

Submission chain
----------------
    case_submit.sh                  root entrypoint; deactivates conda
      -> launchers/case_submit.py   this file; validates run_config.yaml
      -> launchers/sbatch.sh        the batch job
      -> launchers/case_run.sh      runs src/driver.py in the case directory

Usage
-----
Run ``case_submit.sh`` without arguments from the case directory, the directory
that holds the case-local ``run_config.yaml``. INPUT/, OUTPUT/ and
``tem_config.yaml`` are created there.

``run_mode: local`` runs in the foreground, ``slurm`` submits ``sbatch.sh``.
Keys not in ``config/run_config.yaml`` are rejected.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("TUP_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "src"))

import tem_config


def main() -> int:
    case_dir = Path.cwd()
    if not (case_dir / tem_config.CASE_FILE).exists():
        sys.exit(
            f"{tem_config.CASE_FILE} not found in {case_dir}; run case_submit.sh from the case directory"
        )
    try:
        cfg = tem_config.load()
    except (KeyError, ValueError, FileNotFoundError) as error:
        sys.exit(f"Invalid {tem_config.CASE_FILE}: {error}")

    env = {**os.environ, "TUP_ROOT": str(ROOT), "TUP_MODULES": " ".join(cfg["modules"])}
    if cfg["run_mode"] == "local":
        return subprocess.run(
            ["bash", str(ROOT / "launchers" / "case_run.sh")], env=env, check=False
        ).returncode

    cmd = [
        "sbatch",
        f"--job-name={cfg['case_name']}",
        "--nodes=1",
        f"--ntasks={cfg['mpi_tasks']}",
        f"--mem={cfg['mem']}g",
        f"--time={cfg['walltime']}:00:00",
        f"--output={case_dir}/slurm-%j.out",
    ]
    cmd += [f"--partition={cfg['partition']}"] if cfg["partition"] else []
    cmd += [f"--account={cfg['account']}"] if cfg["account"] else []
    cmd += shlex.split(cfg["sbatch_options"])
    cmd.append(str(ROOT / "launchers" / "sbatch.sh"))
    return subprocess.run(cmd, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
