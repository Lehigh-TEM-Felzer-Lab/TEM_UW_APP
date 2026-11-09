# tem_config.py
"""Load and validate the run configuration: config/run_config.yaml overlaid with ./run_config.yaml."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "run_config.yaml"
CASE_FILE = "run_config.yaml"

# varmap keys read by the app from the climate files (derived to TEM units)
CLIMATE_KEYS = {
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
    "u10",
    "v10",
}
# varmap keys passed to the model for the other files (and wind, elev from the climate files)
MODEL_KEYS = {
    "wind",
    "elev",
    "texture",
    "lulc",
    "co2",
    "ozone",
    "ndep",
    "lightning",
    "popdens",
    "nfertcrop",
    "nfertpasture",
    "mask",
}
# keys of run_config.yaml that are not keys of tem_config.yaml; all the others are written to it
APP_KEYS = {
    "tem_src",
    "case_dir",
    "tem_exe",
    "modules",
    "run_mode",
    "run_model",
    "constraint_node",
    "exclusive_node",
    "walltime",
    "n_nodes",
    "n_cpus",
    "partition",
    "n_cpus_per_task",
    "mem",
    "sbatch_options",
    "logfile",
    "case_name",
    "horizontal_resolution",
    "lon_min",
    "lon_max",
    "lat_min",
    "lat_max",
    "regrid_method",
    "start_year",
    "end_year",
    "netcdf_climate_in_file",
    "netcdf_climate_in_frequency",
    "netcdf_static_in_file",
    "netcdf_lulc_in_file",
    "netcdf_co2_in_file",
    "netcdf_fire_in_file",
    "netcdf_population_in_file",
    "surface_pressure_hpa",
    "varmap",
    "clmoutvars",
    "temoutvars",
}
INPUT_KEYS = [
    "netcdf_climate_in_file",
    "netcdf_static_in_file",
    "netcdf_lulc_in_file",
    "netcdf_co2_in_file",
    "netcdf_fire_in_file",
    "netcdf_population_in_file",
]
REQUIRED = [
    "tem_src",
    "netcdf_climate_in_file",
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


def is_calibration_key(key: str) -> bool:
    return isinstance(key, str) and len(key) > 4 and key.endswith("_dat")


def load() -> dict:
    """Defaults overlaid with run_config.yaml of the current directory (the case directory)."""
    os.environ.setdefault("TEM_UW_APP_ROOT", str(ROOT))
    case_dir = Path.cwd()
    cfg = yaml.safe_load(DEFAULT_CONFIG.read_text())
    case = yaml.safe_load((case_dir / CASE_FILE).read_text()) or {}
    if any(is_calibration_key(key) for key in case):
        cfg = {key: value for key, value in cfg.items() if not is_calibration_key(key)}
    for key, value in case.items():
        if key not in cfg and not is_calibration_key(key):
            raise KeyError(f"Unknown run_config key: {key}")
        cfg[key] = {**(cfg[key] or {}), **(value or {})} if key == "varmap" else value
    for key in REQUIRED:
        if cfg[key] is None:
            raise ValueError(f"run_config key '{key}' is required")
    cfg["varmap"] = cfg["varmap"] or {}
    unknown = set(cfg["varmap"]) - CLIMATE_KEYS - MODEL_KEYS
    if unknown:
        raise KeyError(
            f"Unknown varmap keys {sorted(unknown)}; allowed: {sorted(CLIMATE_KEYS | MODEL_KEYS)}"
        )
    cfg["tem_src"] = expand(cfg["tem_src"], case_dir)
    for key, value in cfg.items():
        if isinstance(value, str) and "{tem_src}" in value:
            cfg[key] = value.replace("{tem_src}", str(cfg["tem_src"]))
        if is_calibration_key(key):
            path = cfg[key]
            if not isinstance(path, str) or not path:
                raise ValueError(f"{key} needs a site calibration file path")
            cfg[key] = str(expand(path, case_dir))
    cfg["tem_exe"] = expand(cfg["tem_exe"], case_dir)
    for key in INPUT_KEYS:
        value = cfg[key]
        if value is not None:
            cfg[key] = [
                expand(p, case_dir)
                for p in (value if isinstance(value, list) else [value])
            ]
    if cfg["veg_fire"] and not (
        cfg["netcdf_fire_in_file"] and cfg["netcdf_population_in_file"]
    ):
        raise ValueError(
            "veg_fire needs netcdf_fire_in_file and netcdf_population_in_file"
        )
    if cfg["run_dt"] != 1 or cfg["run_dt_units"] not in ("month", "day"):
        raise ValueError("run_dt is 1 and run_dt_units is month or day")
    if cfg["run_dt_units"] == "day" and cfg["netcdf_climate_in_frequency"] != "daily":
        raise ValueError("run_dt_units day needs netcdf_climate_in_frequency daily")
    for key in ("n_nodes", "n_cpus", "n_cpus_per_task"):
        if cfg[key] < 1:
            raise ValueError(f"{key} must be at least 1")
    if cfg["n_cpus"] < cfg["n_nodes"]:
        raise ValueError("n_cpus must be at least n_nodes")
    cfg["case_dir"] = case_dir
    cfg["case_name"] = cfg["case_name"] or case_dir.name
    return cfg
