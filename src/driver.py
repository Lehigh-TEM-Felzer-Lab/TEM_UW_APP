# driver.py
"""Build the TEM_2026 case of the current directory (INPUT/*.nc, tem_config.yaml) and run it."""

import logging
import subprocess
import sys
from glob import glob
from pathlib import Path

import numpy as np
import xarray as xr
import yaml

import tem_climate as clim
import tem_config

log = logging.getLogger("DRIVER")
CLIMATE = {
    "tair": "degC",
    "dtr": "degC",
    "prec": "mm month-1",
    "nirr": "W m-2",
    "vpr": "hPa",
}
NEAREST = {
    "lulc",
    "chrtarea",
    "potveg",
    "currentveg",
    "subtype",
    "agstate",
    "agprevstate",
}
INT_FILL = -9999
INT_VARS = NEAREST - {"lulc", "chrtarea"} | {
    "tillflag",
    "fertflag",
    "irrgflag",
    "disturbflag",
    "disturbmonth",
}


def save(ds: xr.Dataset, path: Path) -> set[str]:
    """Write with float32 for floats (coordinates too), int64 for the categorical fields and the cohort axis."""
    enc = {}
    for k in ds.data_vars:
        if k in INT_VARS:
            ds[k] = ds[k].fillna(INT_FILL).astype("int64")
            enc[k] = {"_FillValue": np.int64(INT_FILL)}
        elif ds[k].dtype.kind == "f":
            ds[k] = ds[k].astype("float32")
    ds = ds.assign_coords(
        {k: ds[k].astype("float32") for k in ("lat", "lon") if k in ds.coords}
    )
    if "cohort" in ds.dims:
        ds = ds.assign_coords(
            cohort=np.arange(1, ds.sizes["cohort"] + 1, dtype="int64")
        )
    ds.to_netcdf(path, encoding=enc)
    return set(ds.data_vars)


def grid(cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    res = cfg["horizontal_resolution"]
    lon = np.arange(cfg["lon_min"], cfg["lon_max"] + res / 2, res).round(4)
    lat = np.arange(cfg["lat_min"], cfg["lat_max"] + res / 2, res).round(4)
    return lon, lat


def files(paths: list[Path]) -> list[str]:
    """The files that the paths and globs match."""
    found = sorted({f for p in paths for f in glob(str(p))})
    if not found:
        raise FileNotFoundError(f"No file matches {[str(p) for p in paths]}")
    return found


def merged(
    paths: list[Path], cfg: dict, lon: np.ndarray, lat: np.ndarray
) -> xr.Dataset:
    """The regridded variables of all the files."""
    return xr.merge([regrid_file(f, cfg, lon, lat) for f in files(paths)])


def regrid_file(path: Path, cfg: dict, lon: np.ndarray, lat: np.ndarray) -> xr.Dataset:
    """Every lat/lon variable of a NetCDF file on the model grid."""
    ds = xr.open_dataset(path)
    ds = ds.rename(
        {k: v for k, v in clim.RENAME.items() if k in ds.dims or k in ds.coords}
    )
    ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    out = {}
    for name, da in ds.data_vars.items():
        if {"lat", "lon"} <= set(da.dims):
            method = "nearest" if name in NEAREST else cfg["regrid_method"]
            out[name] = clim.to_grid(
                da, lon, lat, method, cfg["horizontal_resolution"]
            ).load()
    return xr.Dataset(out)


def climate(cfg: dict, lon: np.ndarray, lat: np.ndarray) -> tuple[xr.Dataset, dict]:
    """climate.nc (monthly or daily steps, noleap) and the time-independent fields wind and elev, if mapped."""
    res, y0, y1 = cfg["horizontal_resolution"], cfg["start_year"], cfg["end_year"]
    pad = max(2.0, 2 * res)
    ds = clim.open_dataset(
        cfg["netcdf_climate_in_file"],
        (lon[0] - pad, lon[-1] + pad, lat[0] - pad, lat[-1] + pad),
        cfg["netcdf_climate_in_frequency"],
    )
    daily = cfg["run_dt_units"] == "day"
    nyears = y1 - y0 + 1
    steps = 365 if daily else 12
    fields = {}
    for name in [*CLIMATE, "wind", "elev"]:
        da = clim.derive(
            name,
            ds,
            cfg["varmap"],
            cfg["netcdf_climate_in_frequency"],
            cfg["surface_pressure_hpa"],
        )
        if da is None:
            if name in CLIMATE:
                raise ValueError(
                    f"varmap cannot supply '{name}' (see config/run_config.yaml)"
                )
            continue
        if daily and name in CLIMATE:
            da = da.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
            da = da.sel(time=~((da.time.dt.month == 2) & (da.time.dt.day == 29)))
        else:
            if name in CLIMATE or (name == "wind" and "time" in da.dims):
                da = clim.monthly(da, name, cfg["netcdf_climate_in_frequency"])
            if name == "wind" and "time" in da.dims:
                da = da.groupby("time.month").mean()
            elif "time" in da.dims:
                da = da.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
        if name in CLIMATE and da.time.size != steps * nyears:
            raise ValueError(
                f"{name}: {da.time.size} steps found, {steps * nyears} needed"
            )
        fields[name] = clim.to_grid(da, lon, lat, cfg["regrid_method"], res).load()
    days = DAILY if daily else MIDMONTH
    time = np.array(
        [(y - y0) * 365 + d for y in range(y0, y1 + 1) for d in days], dtype=float
    )
    attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    out = xr.Dataset(
        {
            n: (("time", "lat", "lon"), fields[n].values, {"units": u})
            for n, u in {**CLIMATE, "prec": "mm" if daily else CLIMATE["prec"]}.items()
        },
        coords={"time": ("time", time, attrs), "lat": lat, "lon": lon},
    )
    return out, {k: v for k, v in fields.items() if k in ("wind", "elev")}


MIDMONTH = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
DAILY = [d + 0.5 for d in range(365)]


def write_config(cfg: dict, present: set[str]) -> None:
    """tem_config.yaml from the TEM_2026 template: the keys of run_config.yaml that it has, the years and the varmap."""
    template = cfg["tem_src"] / "templates" / "tem_config.yaml"
    model_cfg = {
        key: value
        for key, value in yaml.safe_load(template.read_text()).items()
        if not tem_config.is_calibration_key(key)
    }
    y0, y1 = cfg["start_year"], cfg["end_year"]
    lon, lat = grid(cfg)
    values = {k: v for k, v in cfg.items() if k not in tem_config.APP_KEYS}
    values |= {
        "clmstartyr": y0,
        "de_startyear": y0,
        "startyr": y0,
        "endyr": y1,
        "transtime": y1 - y0 + 1,
        "lulclastyr": y1,
        "mxnumgrid": lon.size * lat.size,
        "clmoutflag": int(bool(cfg["clmoutvars"])),
        "nclmout": len(cfg["clmoutvars"]),
        "clmoutvars": ",".join(cfg["clmoutvars"]) or "missing",
        "temoutflag": int(bool(cfg["temoutvars"])),
        "ntemout": len(cfg["temoutvars"]),
        "temoutvars": ",".join(cfg["temoutvars"]) or "missing",
        "netcdf_climate_in_file": "./INPUT/climate.nc",
        "netcdf_static_in_file": "./INPUT/static.nc",
        "netcdf_lulc_in_file": "./INPUT/lulc.nc",
        "netcdf_co2_in_file": "./INPUT/co2.nc",
        "netcdf_fire_in_file": "./INPUT/lightning.nc",
        "netcdf_population_in_file": "./INPUT/population.nc",
    }
    unknown = {
        key
        for key in values
        if key not in model_cfg and not tem_config.is_calibration_key(key)
    }
    if unknown:
        raise KeyError(f"{template} is missing keys {sorted(unknown)}")
    values["varmap"] = {
        key: value
        for key, value in cfg["varmap"].items()
        if key in tem_config.MODEL_KEYS and value.split("+")[0].split("[")[0] in present
    }
    model_cfg.update(values)
    (cfg["case_dir"] / "tem_config.yaml").write_text(
        yaml.safe_dump(model_cfg, sort_keys=False)
    )


def build(cfg: dict) -> None:
    case = cfg["case_dir"]
    for sub in ("INPUT", "OUTPUT"):
        (case / sub).mkdir(parents=True, exist_ok=True)
    lon, lat = grid(cfg)
    clim_ds, extra = climate(cfg, lon, lat)
    present = save(clim_ds, case / "INPUT" / "climate.nc")
    static = (
        merged(cfg["netcdf_static_in_file"], cfg, lon, lat)
        if cfg["netcdf_static_in_file"]
        else xr.Dataset()
    )
    for name, da in extra.items():
        if name not in static:
            static[name] = da.assign_attrs(units="m s-1" if name == "wind" else "m")
    if static.data_vars:
        present |= save(static, case / "INPUT" / "static.nc")
    for key, name in (
        ("netcdf_lulc_in_file", "lulc.nc"),
        ("netcdf_fire_in_file", "lightning.nc"),
        ("netcdf_population_in_file", "population.nc"),
    ):
        if cfg[key]:
            present |= save(merged(cfg[key], cfg, lon, lat), case / "INPUT" / name)
    if cfg["netcdf_co2_in_file"]:
        co2 = xr.open_mfdataset(files(cfg["netcdf_co2_in_file"]), combine="by_coords")
        present |= save(co2.load(), case / "INPUT" / "co2.nc")
    write_config(cfg, present)
    log.info(
        "Built %s: %d x %d cells of %g degrees",
        case,
        lon.size,
        lat.size,
        cfg["horizontal_resolution"],
    )


def run(cfg: dict) -> int:
    cmd = [str(cfg["tem_exe"])]
    tasks = cfg["n_cpus"] // cfg["n_nodes"] * cfg["n_nodes"]
    if tasks > 1:
        cmd = ["mpirun", "-n", str(tasks), *cmd]
    log.info("Running %s", " ".join(cmd))
    with open(cfg["case_dir"] / "logs" / "tem.out", "w") as out:
        return subprocess.run(
            cmd, cwd=cfg["case_dir"], stdout=out, stderr=subprocess.STDOUT, check=False
        ).returncode


def main() -> int:
    cfg = tem_config.load()
    (cfg["case_dir"] / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg["case_dir"] / f"{cfg['logfile']}.log"),
        ],
    )
    build(cfg)
    return run(cfg) if cfg["run_model"] else 0


if __name__ == "__main__":
    sys.exit(main())
