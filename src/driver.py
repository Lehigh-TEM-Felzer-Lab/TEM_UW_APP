# driver.py
"""Create the TEM case of the current directory (INPUT/, HIST/, OUTPUT/, tem_config.xml, tem_in.txt),
or with the argument convert turn HIST/ into the NetCDF files of OUTPUT/."""

import logging
import os
import sys
from pathlib import Path

import tem_case
import tem_config
import tem_output_nc
import tem_preprocess

log = logging.getLogger("DRIVER")


def main() -> int:
    os.environ.setdefault("TUP_ROOT", str(tem_config.ROOT))
    cfg = tem_config.load()
    case = cfg["case_dir"]
    (case / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(case / "logs" / "tup.log"),
        ],
    )
    log.info("Case %s, core %s", cfg["case_name"], cfg["profile"]["name"])
    if "convert" in sys.argv[1:]:
        tem_output_nc.run(cfg)
    else:
        tem_case.stage(cfg, tem_preprocess.run(cfg))
    log.info("Finished %s", Path(case))
    return 0


if __name__ == "__main__":
    sys.exit(main())
