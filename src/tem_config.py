# tem_config.py
"""Load and validate the run configuration: config/run_config.yaml overlaid with ./run_config.yaml."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "run_config.yaml"
CASE_FILE = "run_config.yaml"
FREE = {"netcdf_varmap", "tem", "tem_varmap", "fire"}
VARMAP_KEYS = {
    "tair",
    "tmin",
    "tmax",
    "dtr",
    "prec",
    "nirr",
    "vpr",
    "dewpoint",
    "huss",
    "ps",
}
VARMAP_KEYS |= {"wind", "u10", "v10", "elev"}
REQUIRED = [
    "tem2026_dir",
    "netcdf_input_file",
    "lon_min",
    "lon_max",
    "lat_min",
    "lat_max",
    "start_year",
    "end_year",
]


def expand(value: str, base: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path if path.is_absolute() else base / path


def load() -> dict:
    """Defaults overlaid with run_config.yaml of the current directory (the case directory)."""
    os.environ.setdefault("TUP_ROOT", str(ROOT))
    case_dir = Path.cwd()
    cfg = yaml.safe_load(DEFAULT_CONFIG.read_text())
    case = yaml.safe_load((case_dir / CASE_FILE).read_text()) or {}
    for key, value in case.items():
        if key not in cfg:
            raise KeyError(f"Unknown run_config key: {key}")
        cfg[key] = {**(cfg[key] or {}), **(value or {})} if key in FREE else value
    for key in REQUIRED:
        if cfg[key] is None:
            raise ValueError(f"run_config key '{key}' is required")
    for key in FREE:
        cfg[key] = cfg[key] or {}
    unknown = set(cfg["netcdf_varmap"]) - VARMAP_KEYS
    if unknown:
        raise KeyError(
            f"Unknown netcdf_varmap keys {sorted(unknown)}; allowed: {sorted(VARMAP_KEYS)}"
        )
    for key in ("tem2026_dir", "tem_exe", "static_file", "lulc_file", "co2_file"):
        if cfg[key]:
            cfg[key] = expand(cfg[key], case_dir)
    if (cfg["tem"].get("run_dt", 1), cfg["tem"].get("run_dt_units", "month")) != (
        1,
        "month",
    ):
        raise ValueError(
            "The app writes monthly forcing: run_dt must be 1 and run_dt_units month"
        )
    cfg["tem_exe"] = cfg["tem_exe"] or cfg["tem2026_dir"] / "build" / "xtem"
    for key in ("flashes_file", "popdens_file"):
        if cfg["fire"].get(key):
            cfg["fire"][key] = expand(cfg["fire"][key], case_dir)
    nif = cfg["netcdf_input_file"]
    cfg["netcdf_input_file"] = [
        expand(p, case_dir) for p in (nif if isinstance(nif, list) else [nif])
    ]
    cfg["case_dir"] = case_dir
    cfg["case_name"] = cfg["case_name"] or case_dir.name
    return cfg
