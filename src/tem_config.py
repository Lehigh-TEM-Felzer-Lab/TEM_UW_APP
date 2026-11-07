# tem_config.py
"""Load, merge and validate the TUP run configuration and the TEM core profile."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "run_config.yaml"
CASE_FILE = "run_config.yaml"

# Sections whose keys are chosen by the user and therefore not checked against the defaults
FREE_SECTIONS = {"netcdf_varmap", "tem"}
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
    "wind",
    "u10",
    "v10",
    "elev",
}
# Static input files named relative to static_dir
STATIC_FILES = (
    "texture_file",
    "ozone_file",
    "ndep_file",
    "co2_file",
    "max_cohorts_file",
    "cohorts_file",
)
REQUIRED = [
    "core",
    "netcdf_input_file",
    "lon_min",
    "lon_max",
    "lat_min",
    "lat_max",
    "start_year",
    "end_year",
]


def expand(value: str, base: Path) -> Path:
    """Expand ~ and environment variables; relative paths are relative to base."""
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else base / path


def is_path_key(key: str) -> bool:
    return key.endswith(("_file", "_dir"))


def load_profile(core: str, case_dir: Path) -> dict:
    """The profile YAML named by core: a file in profiles/ or a path."""
    path = ROOT / "profiles" / f"{core}.yaml"
    if not path.is_file():
        path = expand(core, case_dir)
    if not path.is_file():
        names = sorted(p.stem for p in (ROOT / "profiles").glob("*.yaml"))
        raise FileNotFoundError(f"core '{core}' is not a profile ({names}) or a file")
    profile = yaml.safe_load(path.read_text())
    template = path.parent / profile["xml_template"]
    if not template.is_file():
        template = ROOT / "templates" / profile["xml_template"]
    profile["xml_template"] = template
    profile["profile_file"] = path
    return profile


def load() -> dict:
    """Return the defaults overlaid with run_config.yaml of the current directory (the case directory)."""
    os.environ.setdefault("TUP_ROOT", str(ROOT))
    case_dir = Path.cwd()
    cfg = yaml.safe_load(DEFAULT_CONFIG.read_text())
    case = yaml.safe_load((case_dir / CASE_FILE).read_text()) or {}
    for key, value in case.items():
        if key not in cfg:
            raise KeyError(f"Unknown run_config key: {key}")
        cfg[key] = {**(cfg[key] or {}), **value} if key in FREE_SECTIONS else value
    for key in REQUIRED:
        if cfg[key] is None:
            raise ValueError(f"run_config key '{key}' is required")
    cfg["netcdf_varmap"] = cfg["netcdf_varmap"] or {}
    cfg["tem"] = cfg["tem"] or {}
    unknown = set(cfg["netcdf_varmap"]) - VARMAP_KEYS
    if unknown:
        raise KeyError(
            f"Unknown netcdf_varmap keys {sorted(unknown)}; allowed: {sorted(VARMAP_KEYS)}"
        )
    cfg["profile"] = load_profile(cfg["core"], case_dir)
    cfg["params_dir"] = cfg["params_dir"] or ROOT / "params" / cfg["profile"]["name"]
    cfg["static_dir"] = cfg["static_dir"] or ROOT / "static"
    for key, value in cfg.items():
        if is_path_key(key) and key not in STATIC_FILES:
            if isinstance(value, str) and value:
                cfg[key] = expand(value, case_dir)
            elif isinstance(value, list):
                cfg[key] = [expand(v, case_dir) for v in value]
    for key in STATIC_FILES:
        cfg[key] = expand(str(cfg[key]), cfg["static_dir"])
    cfg["case_dir"] = case_dir
    cfg["case_name"] = cfg["case_name"] or case_dir.name
    return cfg
