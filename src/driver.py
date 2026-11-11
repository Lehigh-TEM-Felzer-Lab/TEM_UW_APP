# driver.py
"""Build the XTEM case of the current directory (INPUT/*.nc, tem_config.yaml) and run it.

20261109 Changed: the staged climate has exactly the steps of the run (run_length); CO2 covers start_year to
         end_year + 1; the staged fire and population files are flash.nc and popdens.nc.
20261109 Fixed: the time axis of daily and monthly forcing is checked step by step; the rank pieces of an
         interrupted run are removed.
20261110 Changed: the optional gdp_file and cropfire_file (GDSTEM-FIRE terms of the fire model) are staged as gdp.nc and crop.nc.
"""

import logging
import re
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
    "standage",
    "tillflag",
    "fertflag",
    "irrgflag",
    "disturbflag",
    "disturbmonth",
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
    ds = ds.drop_encoding()
    enc = {}
    for name, var in ds.data_vars.items():
        enc[name] = {"zlib": True, "complevel": 4}
        if name in INT_VARS:
            ds[name] = var.fillna(INT_FILL).astype("int64")
            enc[name]["_FillValue"] = np.int64(INT_FILL)
        elif var.dtype.kind == "f":
            enc[name]["dtype"] = "float32"
    for axis, direction in (("lat", "north"), ("lon", "east")):
        if axis in ds.coords:
            ds[axis] = ds[axis].astype("float32")
            ds[axis].attrs.update(units=f"degrees_{direction}")
    if "cohort" in ds.coords:
        ds["cohort"] = ds.cohort.astype("int64")
    ds.attrs.setdefault("Conventions", "CF-1.8")
    ds.to_netcdf(path, format="NETCDF4", encoding=enc)
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
    ds = xr.merge([regrid_file(f, cfg, lon, lat) for f in files(paths)], join="outer")
    if "time" in ds.coords:
        year = ds.time.dt.year
        ds = ds.sel(time=(year >= cfg["start_year"]) & (year <= cfg["end_year"]))
    return ds


def regrid_file(path: Path, cfg: dict, lon: np.ndarray, lat: np.ndarray) -> xr.Dataset:
    """Every lat/lon variable of a NetCDF file on the model grid."""
    with xr.open_dataset(path, engine="netcdf4") as source:
        ds = source.rename(
            {
                k: v
                for k, v in clim.RENAME.items()
                if k in source.dims or k in source.coords
            }
        )
        ds = (
            ds.assign_coords(lon=((ds.lon + 180) % 360) - 180)
            .sortby("lon")
            .sortby("lat")
        )
        out = {}
        for name, da in ds.data_vars.items():
            if {"lat", "lon"} <= set(da.dims):
                nearest = (
                    name in NEAREST
                    or "cohort" in da.dims
                    or name == cfg["varmap"].get("mask", "mask")
                )
                method = "nearest" if nearest else cfg["regrid_method"]
                out[name] = clim.to_grid(
                    da, lon, lat, method, cfg["horizontal_resolution"]
                ).load()
    return xr.Dataset(out)


def climate(cfg: dict, lon: np.ndarray, lat: np.ndarray) -> tuple[xr.Dataset, dict]:
    """climate.nc (monthly or daily steps, noleap) and the time-independent fields wind and elev, if mapped."""
    res, y0, y1 = cfg["horizontal_resolution"], cfg["start_year"], cfg["end_year"]
    pad = max(2.0, 2 * res)
    ds = clim.open_dataset(
        cfg["climate_file"],
        (lon[0] - pad, lon[-1] + pad, lat[0] - pad, lat[-1] + pad),
        cfg["netcdf_climate_in_frequency"],
    )
    daily = cfg["step"] == "day"
    steps = cfg["run_steps"]  # the climate holds exactly the steps of the run
    dates = xr.date_range(
        start=f"{y0}-01-01",
        periods=steps,
        freq="D" if daily else "MS",
        calendar="noleap",
        use_cftime=True,
    )
    expected = dates.year * 100 + dates.month
    if daily:
        expected = expected * 100 + dates.day
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
            da = da.sel(time=(da.time.dt.year >= y0) & (da.time.dt.year <= y1))
            da = da.sel(time=~((da.time.dt.month == 2) & (da.time.dt.day == 29)))
        else:
            if name in CLIMATE or (name == "wind" and "time" in da.dims):
                da = clim.monthly(da, name, cfg["netcdf_climate_in_frequency"])
            if name == "wind" and "time" in da.dims:
                da = da.groupby("time.month").mean()
            elif "time" in da.dims:
                da = da.sel(time=(da.time.dt.year >= y0) & (da.time.dt.year <= y1))
        if name in CLIMATE:
            da = da.isel(time=slice(0, steps))
            stamp = da.time.dt.year * 100 + da.time.dt.month
            if daily:
                stamp = stamp * 100 + da.time.dt.day
            if not np.array_equal(stamp.values, expected):
                raise ValueError(
                    f"{name}: input must contain each requested {'day' if daily else 'month'} once in order"
                )
        fields[name] = clim.to_grid(da, lon, lat, cfg["regrid_method"], res).load()
        if name in CLIMATE:
            fields[name] = fields[name].transpose("time", "lat", "lon")
    days = DAILY if daily else MIDMONTH
    time = np.array(
        [(y - y0) * 365 + d for y in range(y0, y1 + 1) for d in days][:steps],
        dtype=float,
    )
    attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    out = xr.Dataset(
        {
            n: (("time", "lat", "lon"), fields[n].values, {"units": u})
            for n, u in {**CLIMATE, "prec": "mm" if daily else CLIMATE["prec"]}.items()
        },
        coords={"time": ("time", time, attrs), "lat": lat, "lon": lon},
        attrs={"geospatial_lon_resolution": res, "geospatial_lat_resolution": res},
    )
    ds.close()
    return out, {k: v for k, v in fields.items() if k in ("wind", "elev")}


MIDMONTH = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
DAILY = [d + 0.5 for d in range(365)]


def write_config(cfg: dict, present: set[str]) -> None:
    """tem_config.yaml from the XTEM template: the keys of run_config.yaml that it has, the years and the varmap."""
    template = cfg["tem_src"] / "templates" / "tem_config.yaml"
    values = {
        key: value
        for key, value in yaml.safe_load(template.read_text()).items()
        if not tem_config.is_calibration_key(key)
    }
    overrides = {k: v for k, v in cfg.items() if k not in tem_config.APP_KEYS}
    unknown = {
        key
        for key in overrides
        if key not in values and not tem_config.is_calibration_key(key)
    }
    if unknown:
        raise KeyError(f"{template} is missing keys {sorted(unknown)}")
    y0, y1 = cfg["start_year"], cfg["end_year"]
    lon, lat = grid(cfg)
    temvars = cfg["temoutvars"]
    clmvars = cfg["clmoutvars"]
    values.update(overrides)
    values.update(
        clmstartyr=y0,
        de_startyear=y0,
        startyr=y0,
        endyr=y1,
        lulclastyr=y1,
        mxnumgrid=int(lon.size * lat.size),
        clmoutflag=int(bool(clmvars)),
        clmoutvars=clmvars,
        temoutflag=int(bool(temvars)),
        temoutvars=temvars,
        climate_file="./INPUT/climate.nc",
        static_file="./INPUT/static.nc",
        lulc_file="./INPUT/lulc.nc",
        co2_file="./INPUT/co2.nc",
        lightning_file="./INPUT/flash.nc",
        population_file="./INPUT/popdens.nc",
        gdp_file="./INPUT/gdp.nc" if cfg["gdp_file"] else None,
        cropfire_file="./INPUT/crop.nc" if cfg["cropfire_file"] else None,
        storm_file="./INPUT/storm.nc",
        nfert_file="./INPUT/nfert.nc",
    )
    values["varmap"] = {
        k: v
        for k, v in cfg["varmap"].items()
        if k in tem_config.MODEL_KEYS and v in present
    }
    (cfg["case_dir"] / "tem_config.yaml").write_text(
        yaml.safe_dump(values, sort_keys=False)
    )


def build(cfg: dict) -> None:
    case = cfg["case_dir"]
    for sub in ("INPUT", "OUTPUT"):
        (case / sub).mkdir(parents=True, exist_ok=True)
    lon, lat = grid(cfg)
    clim_ds, extra = climate(cfg, lon, lat)
    present = save(clim_ds, case / "INPUT" / "climate.nc")
    static = (
        merged(cfg["static_file"], cfg, lon, lat)
        if cfg["static_file"]
        else xr.Dataset()
    )
    for name, da in extra.items():
        if name not in static:
            static[name] = da.assign_attrs(units="m s-1" if name == "wind" else "m")
    if static.data_vars:
        present |= save(static, case / "INPUT" / "static.nc")
    for key, name in (
        ("lulc_file", "lulc.nc"),
        ("lightning_file", "flash.nc"),
        ("population_file", "popdens.nc"),
        ("gdp_file", "gdp.nc"),
        ("cropfire_file", "crop.nc"),
        ("nfert_file", "nfert.nc"),
    ):
        if cfg[key]:
            present |= save(merged(cfg[key], cfg, lon, lat), case / "INPUT" / name)
    if cfg["storm_disturbance"]:
        present |= save(
            merged(cfg["storm_file"], cfg, lon, lat),
            case / "INPUT" / "storm.nc",
        )
    if cfg["co2_file"]:
        with xr.open_mfdataset(
            files(cfg["co2_file"]), combine="by_coords", engine="netcdf4"
        ) as co2:
            years = co2.time.dt.year
            y0, y1 = cfg["start_year"], cfg["end_year"]
            selected = co2.sel(time=(years >= y0) & (years <= y1 + 1)).sortby("time")
            if list(selected.time.dt.year.values[: y1 - y0 + 1]) != list(
                range(y0, y1 + 1)
            ):
                raise ValueError("CO2 input must have one value per simulation year")
            if len(set(selected.time.dt.year.values)) != selected.sizes["time"]:
                raise ValueError("CO2 input contains duplicate years")
            present |= save(selected.load(), case / "INPUT" / "co2.nc")
    write_config(cfg, present)
    log.info(
        "Built %s: %d x %d cells of %g degrees",
        case,
        lon.size,
        lat.size,
        cfg["horizontal_resolution"],
    )


def clear_rank_files(cfg: dict, native: Path) -> None:
    """Clear temporary rank pieces from an interrupted run of this case."""
    files = [native]
    if cfg["ostateflag"]:
        state = Path(cfg["ostatefile"])
        files.append(state if state.is_absolute() else cfg["case_dir"] / state)
    for file in files:
        if not file.parent.is_dir():
            continue
        base = re.escape(file.name)
        if file == native and cfg["output_new_file_freq"]:
            stem, suffix = re.escape(file.stem), re.escape(file.suffix)
            base = rf"{stem}_\d{{6}}-\d{{6}}{suffix}"
        pattern = re.compile(rf"{base}\.\d{{4,}}")
        for candidate in file.parent.iterdir():
            if pattern.fullmatch(candidate.name):
                candidate.unlink(missing_ok=True)


def run(cfg: dict) -> int:
    if not cfg["tem_exe"].is_file():
        raise FileNotFoundError(
            f"{cfg['tem_exe']} is missing. Build the requested TEM executable first."
        )
    native = Path(cfg["output_file"])
    native.parent.mkdir(parents=True, exist_ok=True)
    before = native.stat().st_mtime_ns if native.exists() else None
    cmd = [str(cfg["tem_exe"])]
    tasks = tem_config.mpi_tasks(cfg)
    clear_rank_files(cfg, native)
    if tasks > 1:
        cmd = ["mpirun", "-n", str(tasks), *cmd]
    log.info("Running %s", " ".join(cmd))
    with open(cfg["case_dir"] / "logs" / "tem.out", "w") as out:
        status = subprocess.run(
            cmd, cwd=cfg["case_dir"], stdout=out, stderr=subprocess.STDOUT, check=False
        ).returncode
    if (
        not status
        and not cfg["output_new_file_freq"]
        and (not native.exists() or native.stat().st_mtime_ns == before)
    ):
        raise RuntimeError(
            "TEM produced no new output. Check logs/tem.out and the TEM log."
        )
    if not status:
        clear_rank_files(cfg, native)
    return status


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
