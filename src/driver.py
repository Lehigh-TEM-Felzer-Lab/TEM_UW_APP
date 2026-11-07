# driver.py
"""Create the TEM case of the current directory: INPUT/, HIST/, OUTPUT/, tem_config.xml, tem_in.txt."""

import logging
import os
import sys
from pathlib import Path

import tup_case
import tup_config
import tup_preprocess

log = logging.getLogger("DRIVER")


def main() -> int:
    os.environ.setdefault("TUP_ROOT", str(tup_config.ROOT))
    cfg = tup_config.load()
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
    tup_case.stage(cfg, tup_preprocess.run(cfg))
    log.info("Finished %s", Path(case))
    return 0


if __name__ == "__main__":
    sys.exit(main())
