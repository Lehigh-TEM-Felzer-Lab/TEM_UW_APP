# tem_config.py
"""Load and validate the run configuration: config/run_config.yaml overlaid with ./run_config.yaml.

20261109 Changed: run_length and run_length_units replace end_year (end_year is derived); varmap values are
         one variable name; sand, silt, clay, storm and hurricane are varmap keys; tem_exe defaults to build or
         build_mpi of tem_src (one executable runs monthly and daily steps).
20261109 Updated: validation of grid, CO2, nitrogen, spin-up and run_dt keys; output variable lists must be
         YAML sequences of names.
20261111 Changed: fire is the GDSTEM-FIRE model and needs gdp_file (varmap key gdp); cropfire_file and the fire_seed, fire_mode, fire_topography and fire_prescribed_end keys are gone. Earlier: gdp_file switched on the GDSTEM-FIRE terms of the fire
         model; run_dt and run_length are converted to seconds (time_units.py) and may be written in any unit.
"""

import os
from pathlib import Path

import yaml

import time_units

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
    "sand",
    "silt",
    "clay",
    "lulc",
    "co2",
    "ozone",
    "ndep",
    "lightning",
    "popdens",
    "gdp",
    "storm",
    "hurricane",
    "nfertcrop",
    "nfertpasture",
    "mask",
}
# keys of run_config.yaml that are not keys of tem_config.yaml; all the others are written to it
APP_KEYS = {
    "step",
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
    "run_steps",
    "climate_file",
    "netcdf_climate_in_frequency",
    "static_file",
    "lulc_file",
    "co2_file",
    "lightning_file",
    "population_file",
    "gdp_file",
    "storm_file",
    "nfert_file",
    "surface_pressure_hpa",
    "varmap",
    "clmoutvars",
    "temoutvars",
}
INPUT_KEYS = [
    "climate_file",
    "static_file",
    "lulc_file",
    "co2_file",
    "lightning_file",
    "population_file",
    "gdp_file",
    "storm_file",
    "nfert_file",
]
REQUIRED = [
    "tem_src",
    "climate_file",
    "static_file",
    "lulc_file",
    "lon_min",
    "lon_max",
    "lat_min",
    "lat_max",
    "start_year",
    "run_length",
    "run_length_units",
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
    bad = {
        k: v
        for k, v in cfg["varmap"].items()
        if not isinstance(v, str) or set(v) & set("+[]|")
    }
    if bad:
        raise ValueError(
            f"varmap values must be one variable name, without sums or options: {bad}"
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
    for key in INPUT_KEYS:
        value = cfg[key]
        if value is not None:
            cfg[key] = [
                expand(p, case_dir)
                for p in (value if isinstance(value, list) else [value])
            ]
    # run length: run_length in run_length_units from 1 January of start_year; end_year is the last year it touches
    n = cfg["run_length"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("run_length must be a positive integer")
    cfg["step"] = time_units.step_kind(cfg["run_dt"], cfg["run_dt_units"])
    steps = time_units.run_steps(n, cfg["run_length_units"], cfg["step"])
    if steps is None:
        raise ValueError(
            f"run_length {n} {cfg['run_length_units']} "
            f"({time_units.run_seconds(n, cfg['run_length_units'])} s) is not a whole number of "
            f"{cfg['run_dt']} {cfg['run_dt_units']} steps"
        )
    cfg["run_steps"] = steps
    cfg["end_year"] = (
        cfg["start_year"] + -(-steps // (12 if cfg["step"] == "month" else 365)) - 1
    )
    if cfg["horizontal_resolution"] <= 0 or any(
        cfg[f"{axis}_min"] > cfg[f"{axis}_max"] for axis in ("lon", "lat")
    ):
        raise ValueError(
            "Grid bounds and horizontal_resolution must define a nonempty grid"
        )
    if cfg["xnfertflag"] not in (1, 2):
        raise ValueError(
            "xnfertflag must be 1 (long-term average) or 2 (transient): fertilizer is read from input data"
        )
    if cfg["agfertflag"] == 1 and not cfg["nfert_file"]:
        raise ValueError("agfertflag 1 needs nfert_file")
    if cfg["xtco2flag"] and not cfg["co2_file"]:
        raise ValueError("xtco2flag needs co2_file")
    if (
        cfg["spinflag"] == 2
        and not 1 <= cfg["de_nyears"] <= cfg["end_year"] - cfg["start_year"] + 1
    ):
        raise ValueError(
            "de_nyears must fit within the climate input years for spinflag: 2"
        )
    storm = cfg["storm_disturbance"]
    if not isinstance(storm, int) or storm not in (0, 1):
        raise ValueError("storm_disturbance must be true or false")
    if storm and not cfg["storm_file"]:
        raise ValueError("storm_disturbance needs storm_file")
    if cfg["veg_fire"] and not (cfg["lightning_file"] and cfg["population_file"] and cfg["gdp_file"]):
        raise ValueError("veg_fire needs lightning_file, population_file and gdp_file")
    if cfg["netcdf_climate_in_frequency"] not in ("hourly", "daily", "monthly"):
        raise ValueError("netcdf_climate_in_frequency must be hourly, daily or monthly")
    if cfg["step"] == "day" and cfg["netcdf_climate_in_frequency"] != "daily":
        raise ValueError("a daily step needs netcdf_climate_in_frequency daily")
    for key in ("n_nodes", "n_cpus", "n_cpus_per_task"):
        if cfg[key] < 1:
            raise ValueError(f"{key} must be at least 1")
    if cfg["n_cpus"] < cfg["n_nodes"]:
        raise ValueError("n_cpus must be at least n_nodes")
    if cfg["run_mode"] not in ("local", "slurm"):
        raise ValueError("run_mode must be local or slurm")
    if cfg["tem_exe"] is None:
        build = "build_mpi" if mpi_tasks(cfg) > 1 else "build"
        cfg["tem_exe"] = cfg["tem_src"] / build / "xtem"
    else:
        cfg["tem_exe"] = expand(cfg["tem_exe"], case_dir)
    cfg["output_file"] = str(expand(cfg["output_file"], case_dir))
    for key in ("clmoutvars", "temoutvars"):
        names = cfg[key]
        if not isinstance(names, list) or any(
            not isinstance(name, str) or not name for name in names
        ):
            raise ValueError(f"{key} must be a YAML sequence of output variable names")
        cfg[key] = list(dict.fromkeys(name.lower() for name in names))
    cfg["case_dir"] = case_dir
    cfg["case_name"] = cfg["case_name"] or case_dir.name
    return cfg


def mpi_tasks(cfg: dict) -> int:
    """Match the TEM_UW_APP layout used by the local and SLURM launchers."""
    return cfg["n_cpus"] // cfg["n_nodes"] * cfg["n_nodes"]
